"""Render/PostgreSQL 提供給 TurboPlus 的唯讀營運鏡像契約。

這個模組刻意不實作任何寫入資料庫的功能。同步模型是：TP 的本機同步程式
定期向 Render 拉取一次完整快照，並以 source_id 作為 TP 端的穩定對照鍵。

請勿在這裡加入密碼、password_hash、身分證、生日、地址、健康/同行人資料、
ATM 虛擬帳號、第三方交易編號或任何金鑰。
"""

from __future__ import annotations

from datetime import datetime, timezone
import hmac

from db import get_conn, rows_to_dicts


API_VERSION = "v1"

# 每一個查詢皆使用固定 SQL；entity 只可從本表選取，絕不直接拼入 SQL。
# 所有輸出都以 source_id 作為 TP 寫入時的冪等對照鍵。
ENTITY_QUERIES = {
    "members": """
        SELECT id AS source_id, name, phone, email, internal_level,
               primary_equipment, auth_provider, created_at
        FROM members WHERE id > ? ORDER BY id LIMIT ?
    """,
    "staff": """
        SELECT id AS source_id, work_id, name, display_code, nickname, phone, email,
               role, branch, is_coach, is_active, display_order, created_at
        FROM staff WHERE id > ? ORDER BY id LIMIT ?
    """,
    "coach_schedule": """
        SELECT id AS source_id, coach_id AS coach_source_id, work_date, status
        FROM coach_schedule WHERE id > ? ORDER BY id LIMIT ?
    """,
    "japan_regions": """
        SELECT id AS source_id, code, name, requires_resort_selection,
               allow_designate_coach, requires_accommodation_option,
               resort_list_editable, display_order
        FROM japan_regions WHERE id > ? ORDER BY id LIMIT ?
    """,
    "resorts": """
        SELECT id AS source_id, region_id AS region_source_id, code, name, is_active
        FROM ski_resorts WHERE id > ? ORDER BY id LIMIT ?
    """,
    "orders": """
        SELECT id AS source_id, member_id AS member_source_id, order_type, amount,
               discount_amount, paid_amount, refunded_amount, currency, status,
               ref_type, ref_id AS ref_source_id, created_at
        FROM orders WHERE id > ? ORDER BY id LIMIT ?
    """,
    "payments": """
        SELECT id AS source_id, member_id AS member_source_id, order_id AS order_source_id,
               ref_type, ref_id AS ref_source_id, amount, payment_type, payment_method,
               payment_status, confirmed_by_staff_id AS confirmed_by_staff_source_id,
               created_at
        FROM transactions WHERE id > ? ORDER BY id LIMIT ?
    """,
    "charter_passes": """
        SELECT id AS source_id, member_id AS member_source_id, package_size,
               headcount_type, remaining, equipment_type, created_at
        FROM charter_passes WHERE id > ? ORDER BY id LIMIT ?
    """,
    "member_plans": """
        SELECT id AS source_id, member_id AS member_source_id, plan_name, billing_cycle,
               fee_paid, quota_cycle_start, assigned_by_staff_id AS assigned_by_staff_source_id,
               is_active, created_at
        FROM member_plans WHERE id > ? ORDER BY id LIMIT ?
    """,
    "member_quota_cycles": """
        SELECT id AS source_id, member_id AS member_source_id, cycle_key, charter_used,
               self_practice_used, group_class_used
        FROM member_quota_cycles WHERE id > ? ORDER BY id LIMIT ?
    """,
    "indoor_sessions": """
        SELECT id AS source_id, booking_date, start_hour, duration_minutes, category,
               coach_id AS coach_source_id,
               assistant_coach_id AS assistant_coach_source_id, max_capacity, status,
               charter_package_size, designate_fee, attendance_status, checked_in_at,
               checked_in_by_staff_id AS checked_in_by_staff_source_id, created_at
        FROM indoor_sessions WHERE id > ? ORDER BY id LIMIT ?
    """,
    "indoor_session_members": """
        SELECT id AS source_id, session_id AS session_source_id,
               member_id AS member_source_id, headcount, equipment_type, price,
               quota_consumed, status, created_at
        FROM indoor_session_members WHERE id > ? ORDER BY id LIMIT ?
    """,
    "jump_bookings": """
        SELECT id AS source_id, member_id AS member_source_id, booking_date, start_time,
               duration_minutes, equipment_type, price, status, attendance_status,
               checked_in_at, checked_in_by_staff_id AS checked_in_by_staff_source_id,
               created_at
        FROM jump_bookings WHERE id > ? ORDER BY id LIMIT ?
    """,
    "japan_bookings": """
        SELECT id AS source_id, member_id AS member_source_id,
               resort_id AS resort_source_id, booking_date, day_type, half_day_slot,
               headcount, equipment_type, coach_id AS coach_source_id, designate_coach,
               designate_fee, needs_accommodation, price, group_key, payment_plan,
               deposit_amount, deposit_paid, deposit_paid_date, deposit_payment_method,
               balance_amount, balance_paid, balance_paid_date, balance_payment_method,
               status, attendance_status, checked_in_at,
               checked_in_by_staff_id AS checked_in_by_staff_source_id, created_at
        FROM japan_bookings WHERE id > ? ORDER BY id LIMIT ?
    """,
    "japan_other_resort_requests": """
        SELECT id AS source_id, member_id AS member_source_id, resort_name, start_date,
               end_date, day_type, half_day_slot, headcount, equipment_type,
               needs_accommodation, status,
               handled_by_staff_id AS handled_by_staff_source_id, handled_at, created_at
        FROM japan_other_resort_requests WHERE id > ? ORDER BY id LIMIT ?
    """,
}

ENTITY_LABELS = {
    "members": "會員營運摘要",
    "staff": "員工與教練營運摘要",
    "coach_schedule": "教練班表",
    "japan_regions": "日本滑雪分區",
    "resorts": "雪場",
    "orders": "訂單",
    "payments": "付款狀態",
    "charter_passes": "包機堂數",
    "member_plans": "會員方案",
    "member_quota_cycles": "會員方案額度",
    "indoor_sessions": "室內滑雪時段",
    "indoor_session_members": "室內滑雪參加者",
    "jump_bookings": "跳台預約",
    "japan_bookings": "日本滑雪預約",
    "japan_other_resort_requests": "其他雪場需求",
}


def constant_time_authorized(supplied: str, expected: str) -> bool:
    """以固定時間比對同步金鑰，避免一般字串比對洩露部分金鑰資訊。"""
    return bool(supplied and expected and hmac.compare_digest(supplied, expected))


def parse_page_arguments(after_raw: str | None, limit_raw: str | None, max_page_size: int) -> tuple[int, int]:
    """解析一次完整快照中的游標，不把它當作增量同步依據。"""
    after_id = 0 if after_raw in (None, "") else int(after_raw)
    limit = max_page_size if limit_raw in (None, "") else int(limit_raw)
    if after_id < 0 or limit < 1 or limit > max_page_size:
        raise ValueError("invalid pagination")
    return after_id, limit


def get_manifest() -> dict:
    return {
        "api_version": API_VERSION,
        "mode": "read_only_full_snapshot",
        "source_of_truth": "render_postgresql",
        "entities": [
            {"name": entity, "label": ENTITY_LABELS[entity]}
            for entity in ENTITY_QUERIES
        ],
        "security": {
            "excluded": [
                "passwords", "password_hashes", "national_id_numbers", "addresses",
                "health_and_companion_data", "atm_virtual_accounts", "provider_transaction_ids",
                "third_party_credentials",
            ],
        },
    }


def get_snapshot(entity: str, after_id: int, limit: int) -> dict:
    """回傳特定實體的一頁完整快照資料。呼叫端應從 after_id=0 讀到結尾。"""
    query = ENTITY_QUERIES.get(entity)
    if query is None:
        raise KeyError(entity)

    conn = get_conn()
    try:
        records = rows_to_dicts(conn.execute(query, (after_id, limit)).fetchall())
    finally:
        conn.close()

    return {
        "api_version": API_VERSION,
        "mode": "read_only_full_snapshot",
        "entity": entity,
        "records": records,
        "next_after_id": records[-1]["source_id"] if len(records) == limit else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }