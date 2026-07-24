"""
核心排課邏輯 v2
------------
室內滑雪(高雄機台): 體驗 / 包機 / 團課 / 自主練習 共用同一台機台,
同一時段(依 start_hour + duration 展開的整點區間)只能有一筆有效佔用。
跳台體驗是獨立資源,不受此限制。
"""

import uuid
from datetime import datetime, timedelta
from db import get_conn
import pricing

ACTIVE_INDOOR_STATUSES = ("pending_payment", "open", "confirmed", "needs_manual_review")


def _occupied_hours(start_hour, duration_minutes):
    """回傳這堂課會佔用的整點時段集合,例如 60分鐘從10點開始 -> {10}; 120分鐘 -> {10,11}"""
    hours_needed = max(1, (duration_minutes + 59) // 60)
    return set(range(start_hour, start_hour + hours_needed))


def _has_conflict(conn, booking_date, start_hour, duration_minutes, exclude_session_id=None):
    rows = conn.execute(
        """SELECT * FROM indoor_sessions
           WHERE booking_date=? AND status IN (?,?,?,?)""",
        (booking_date, *ACTIVE_INDOOR_STATUSES),
    ).fetchall()
    target = _occupied_hours(start_hour, duration_minutes)
    for r in rows:
        if exclude_session_id and r["id"] == exclude_session_id:
            continue
        existing = _occupied_hours(r["start_hour"], r["duration_minutes"])
        if target & existing:
            return True
    return False


MAX_CONTINUOUS_HOURS = 2  # 同一人連續課程上限(雙板/單板時數合併計算,避免用換裝備繞過限制)


def _check_continuous_hours(conn, member_id, booking_date, start_hour, duration_minutes):
    """檢查加入這堂課後,該會員當天是否會連續超過 MAX_CONTINUOUS_HOURS 小時(不分裝備類型)。"""
    rows = conn.execute(
        """SELECT s.start_hour, s.duration_minutes FROM indoor_session_members sm
           JOIN indoor_sessions s ON sm.session_id = s.id
           WHERE sm.member_id=? AND s.booking_date=? AND sm.status='enrolled'
           AND s.status IN (?,?,?,?)""",
        (member_id, booking_date, *ACTIVE_INDOOR_STATUSES),
    ).fetchall()
    hours = set()
    for r in rows:
        hours |= _occupied_hours(r["start_hour"], r["duration_minutes"])
    hours |= _occupied_hours(start_hour, duration_minutes)

    sorted_hours = sorted(hours)
    max_run = 1
    current_run = 1
    for i in range(1, len(sorted_hours)):
        if sorted_hours[i] == sorted_hours[i - 1] + 1:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 1
    if max_run > MAX_CONTINUOUS_HOURS:
        raise ValueError(
            f"同一人連續課程不得超過 {MAX_CONTINUOUS_HOURS} 小時(雙板/單板時數合併計算),請分開時段預約"
        )


def _log_notification(conn, member_id, notify_type, content, channel="system"):
    """記錄一筆通知(目前為模擬,尚未真正串接LINE/Email/簡訊發送)。"""
    conn.execute(
        """INSERT INTO notifications (member_id, channel, notify_type, content, status)
           VALUES (?, ?, ?, ?, 'simulated')""",
        (member_id, channel, notify_type, content),
    )


def check_and_auto_cancel_group_classes():
    """
    開課前24小時仍未滿最低成班人數的團課場次,自動取消並通知已報名/候補學員。
    正式上線建議用排程器(例如 APScheduler)每小時自動呼叫;此環境無背景排程,
    暫時提供後台手動觸發的端點。
    """
    conn = get_conn()
    now = datetime.now()
    cutoff = now + timedelta(hours=24)
    candidates = conn.execute(
        "SELECT * FROM indoor_sessions WHERE category='group_class' AND status='open'"
    ).fetchall()

    cancelled_ids = []
    for gc in candidates:
        class_dt = datetime.strptime(f"{gc['booking_date']} {gc['start_hour']:02d}:00", "%Y-%m-%d %H:%M")
        if class_dt <= cutoff:
            members = conn.execute(
                """SELECT * FROM indoor_session_members WHERE session_id=?
                   AND status IN ('enrolled','waitlisted')""",
                (gc["id"],),
            ).fetchall()
            conn.execute("UPDATE indoor_sessions SET status='cancelled' WHERE id=?", (gc["id"],))
            conn.execute(
                "UPDATE indoor_session_members SET status='cancelled' WHERE session_id=?", (gc["id"],)
            )
            for m in members:
                _log_notification(
                    conn, m["member_id"], "group_class_cancelled",
                    f"{gc['booking_date']} {gc['start_hour']}:00 團課因開課前24小時仍未滿{pricing.GROUP_CLASS_MIN}人,已自動取消",
                )
            cancelled_ids.append(gc["id"])
    conn.commit()
    conn.close()
    return cancelled_ids


def _validate_hour(start_hour):
    if not (pricing.INDOOR_START_HOUR <= start_hour <= pricing.INDOOR_LAST_START_HOUR):
        raise ValueError(
            f"開課時間僅接受 {pricing.INDOOR_START_HOUR}:00 ~ {pricing.INDOOR_LAST_START_HOUR}:00(整點開課)"
        )


def _insert_participants(conn, ref_type, ref_id, participants):
    """participants: [{'gender':'male','age':30,'height_cm':170,'weight_kg':65,'shoe_size':'26'}, ...]"""
    for p in participants or []:
        conn.execute(
            """INSERT INTO booking_participants
               (ref_type, ref_id, gender, age, height_cm, weight_kg, shoe_size)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ref_type, ref_id, p.get("gender"), p.get("age"),
             p.get("height_cm"), p.get("weight_kg"), p.get("shoe_size")),
        )


# ------------------------------------------------------------------
# 體驗課
# ------------------------------------------------------------------
def book_trial(member_id, booking_date, start_hour, headcount, equipment_type=None, participants=None, coach_id=None):
    _validate_hour(start_hour)
    price = pricing.compute_trial_price(headcount)
    conn = get_conn()

    if equipment_type:
        existing = conn.execute(
            """SELECT sm.id FROM indoor_session_members sm
               JOIN indoor_sessions s ON sm.session_id = s.id
               WHERE sm.member_id=? AND s.category='trial' AND sm.equipment_type=?
               AND sm.status='enrolled' AND s.status != 'cancelled'""",
            (member_id, equipment_type),
        ).fetchone()
        if existing:
            conn.close()
            equip_label = "雙板" if equipment_type == "ski" else "單板"
            raise ValueError(f"體驗課({equip_label})每人僅限預約一次,你已經預約過了")

    conflict = _has_conflict(conn, booking_date, start_hour, 50)
    status = "needs_manual_review" if conflict else "pending_payment"

    cur = conn.execute(
        """INSERT INTO indoor_sessions
           (booking_date, start_hour, duration_minutes, category, coach_id, max_capacity, status)
           VALUES (?, ?, 50, 'trial', ?, ?, ?)""",
        (booking_date, start_hour, coach_id, headcount, status),
    )
    session_id = cur.lastrowid
    cur2 = conn.execute(
        """INSERT INTO indoor_session_members (session_id, member_id, headcount, equipment_type, price)
           VALUES (?, ?, ?, ?, ?)""",
        (session_id, member_id, headcount, equipment_type, price),
    )
    _insert_participants(conn, "indoor_session_member", cur2.lastrowid, participants)
    conn.execute(
        """INSERT INTO orders (member_id, order_type, amount, status, ref_type, ref_id)
           VALUES (?, 'trial', ?, 'pending', 'indoor_session', ?)""",
        (member_id, price, session_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM indoor_sessions WHERE id=?", (session_id,)).fetchone()
    conn.close()
    return {**dict(row), "price": price}


# ------------------------------------------------------------------
# 包機課(堂數包購買 + 使用堂數預約)
# ------------------------------------------------------------------
def purchase_charter_pass(member_id, package_size, headcount_type):
    """建立堂數包購買訂單。remaining 先為0,付款成功後由 finalize_charter_purchase 正式產生權益。"""
    price = pricing.compute_charter_price(package_size, headcount_type)
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO charter_passes (member_id, package_size, headcount_type, remaining)
           VALUES (?, ?, ?, 0)""",
        (member_id, package_size, headcount_type),
    )
    pass_id = cur.lastrowid
    order_cur = conn.execute(
        """INSERT INTO orders (member_id, order_type, amount, status, ref_type, ref_id)
           VALUES (?, 'charter_pass', ?, 'pending', 'charter_pass', ?)""",
        (member_id, price, pass_id),
    )
    order_id = order_cur.lastrowid
    conn.commit()
    conn.close()
    return {"pass_id": pass_id, "order_id": order_id, "price": price, "remaining": 0}


def mark_order_paid(ref_type, ref_id):
    """一次性付費項目(體驗課/自主練習/跳台)付款確認後,將對應訂單標記為已付款。"""
    conn = get_conn()
    order = conn.execute(
        "SELECT * FROM orders WHERE ref_type=? AND ref_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
        (ref_type, ref_id),
    ).fetchone()
    if order:
        conn.execute("UPDATE orders SET status='paid' WHERE id=?", (order["id"],))
        conn.commit()
    conn.close()


def finalize_charter_purchase(order_id):
    """付款確認成功後呼叫:把訂單標記為已付款,正式產生堂數權益與明細帳(對照系統分析書 9.1)。"""
    conn = get_conn()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order or order["status"] == "paid":
        conn.close()
        return  # 找不到訂單,或已經處理過(避免重複入帳)
    pass_row = conn.execute("SELECT * FROM charter_passes WHERE id=?", (order["ref_id"],)).fetchone()
    if not pass_row:
        conn.close()
        return
    conn.execute("UPDATE orders SET status='paid' WHERE id=?", (order_id,))
    conn.execute(
        "UPDATE charter_passes SET remaining = remaining + ? WHERE id=?",
        (pass_row["package_size"], pass_row["id"]),
    )
    conn.execute(
        """INSERT INTO entitlement_ledger
           (member_id, entitlement_type, entitlement_ref_id, change_type, amount, order_id, note)
           VALUES (?, 'charter_pass', ?, 'purchase', ?, ?, ?)""",
        (order["member_id"], pass_row["id"], pass_row["package_size"], order_id,
         f"購買{pass_row['package_size']}堂堂數包"),
    )
    conn.commit()
    conn.close()


def book_charter(member_id, booking_date, start_hour, charter_pass_id, equipment_type=None, participants=None, coach_id=None):
    """使用已購買的包機堂數包來預約一堂課(不再另外收費,扣抵堂數)。"""
    _validate_hour(start_hour)
    conn = get_conn()
    cpass = conn.execute("SELECT * FROM charter_passes WHERE id=?", (charter_pass_id,)).fetchone()
    if not cpass or cpass["member_id"] != member_id:
        conn.close()
        raise ValueError("找不到此會員的包機堂數包")
    if cpass["remaining"] <= 0:
        conn.close()
        raise ValueError("包機堂數已用完,請重新購買")

    _check_continuous_hours(conn, member_id, booking_date, start_hour, 50)

    conflict = _has_conflict(conn, booking_date, start_hour, 50)
    status = "needs_manual_review" if conflict else "confirmed"

    cur = conn.execute(
        """INSERT INTO indoor_sessions
           (booking_date, start_hour, duration_minutes, category, coach_id, max_capacity,
            status, charter_package_size)
           VALUES (?, ?, 50, 'charter', ?, ?, ?, ?)""",
        (booking_date, start_hour, coach_id, cpass["headcount_type"], status, cpass["package_size"]),
    )
    session_id = cur.lastrowid
    cur2 = conn.execute(
        """INSERT INTO indoor_session_members (session_id, member_id, headcount, equipment_type, price)
           VALUES (?, ?, ?, ?, 0)""",
        (session_id, member_id, cpass["headcount_type"], equipment_type),
    )
    _insert_participants(conn, "indoor_session_member", cur2.lastrowid, participants)
    conn.execute("UPDATE charter_passes SET remaining = remaining - 1 WHERE id=?", (charter_pass_id,))
    conn.execute(
        """INSERT INTO entitlement_ledger
           (member_id, entitlement_type, entitlement_ref_id, change_type, amount, booking_ref_type, booking_ref_id, note)
           VALUES (?, 'charter_pass', ?, 'reserve', -1, 'indoor_session_member', ?, ?)""",
        (member_id, charter_pass_id, cur2.lastrowid, f"預約 {booking_date} {start_hour}:00 包機課,圈存1堂"),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM indoor_sessions WHERE id=?", (session_id,)).fetchone()
    remaining_after = cpass["remaining"] - 1
    lesson_number = cpass["package_size"] - remaining_after
    conn.close()
    return {
        **dict(row),
        "lesson_number": lesson_number,
        "package_size": cpass["package_size"],
        "remaining": remaining_after,
    }


# ------------------------------------------------------------------
# 自主練習
# ------------------------------------------------------------------
def book_self_practice(member_id, booking_date, start_hour, duration_minutes, headcount=1,
                        equipment_type=None, participants=None, use_plan_quota=False):
    _validate_hour(start_hour)
    price = pricing.compute_self_practice_price(duration_minutes)
    conn = get_conn()

    quota_consumed = False
    if use_plan_quota:
        quota_consumed = _consume_quota(conn, member_id, booking_date, "self_practice")
        if not quota_consumed:
            conn.close()
            raise ValueError("本季自主練習額度已用完或無有效方案")
        price = 0

    conflict = _has_conflict(conn, booking_date, start_hour, duration_minutes)
    status = "needs_manual_review" if conflict else "pending_payment"

    cur = conn.execute(
        """INSERT INTO indoor_sessions
           (booking_date, start_hour, duration_minutes, category, max_capacity, status)
           VALUES (?, ?, ?, 'self_practice', ?, ?)""",
        (booking_date, start_hour, duration_minutes, headcount, status),
    )
    session_id = cur.lastrowid
    cur2 = conn.execute(
        """INSERT INTO indoor_session_members (session_id, member_id, headcount, equipment_type, price, quota_consumed)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, member_id, headcount, equipment_type, price, quota_consumed),
    )
    _insert_participants(conn, "indoor_session_member", cur2.lastrowid, participants)
    if not quota_consumed:
        conn.execute(
            """INSERT INTO orders (member_id, order_type, amount, status, ref_type, ref_id)
               VALUES (?, 'self_practice', ?, 'pending', 'indoor_session', ?)""",
            (member_id, price, session_id),
        )
    conn.commit()
    row = conn.execute("SELECT * FROM indoor_sessions WHERE id=?", (session_id,)).fetchone()
    conn.close()
    return {**dict(row), "price": price, "quota_consumed": quota_consumed}


# ------------------------------------------------------------------
# 團課(會員限定,滿2人開課,滿4人截止,可指定教練)
# ------------------------------------------------------------------
def enroll_group_class(member_id, booking_date, start_hour, equipment_type=None, participant=None):
    """
    團課:多位會員各自報名同一時段,滿2人開課、滿4人截止。
    不可指定教練(教練由後台/排班另行安排,不在報名時選擇)。
    僅限已持有有效 A/B 方案會員資格的會員報名(方案本身需付費訂閱,見 subscribe_plan)。
    """
    _validate_hour(start_hour)
    conn = get_conn()

    plan = conn.execute(
        "SELECT * FROM member_plans WHERE member_id=? AND is_active=1", (member_id,)
    ).fetchone()
    if not plan:
        conn.close()
        raise ValueError("團課限定已訂閱 A/B 方案的會員才能報名")

    quota_consumed = _consume_quota(conn, member_id, booking_date, "group_class")
    if not quota_consumed:
        conn.close()
        raise ValueError("本季團課額度已用完,或月繳方案本月尚未繳費(請洽客服確認繳費狀態)")

    session = conn.execute(
        """SELECT * FROM indoor_sessions
           WHERE booking_date=? AND start_hour=? AND category='group_class'
           AND status IN ('open','confirmed')""",
        (booking_date, start_hour),
    ).fetchone()

    if session:
        current_count = conn.execute(
            "SELECT COUNT(*) c FROM indoor_session_members WHERE session_id=? AND status='enrolled'",
            (session["id"],),
        ).fetchone()["c"]
        session_id = session["id"]
        is_waitlist = current_count >= pricing.GROUP_CLASS_MAX
    else:
        conflict = _has_conflict(conn, booking_date, start_hour, 50)
        if conflict:
            conn.close()
            raise ValueError("此時段機台已被其他課程佔用")
        cur = conn.execute(
            """INSERT INTO indoor_sessions
               (booking_date, start_hour, duration_minutes, category, coach_id, max_capacity, status)
               VALUES (?, ?, 50, 'group_class', NULL, ?, 'open')""",
            (booking_date, start_hour, pricing.GROUP_CLASS_MAX),
        )
        session_id = cur.lastrowid
        current_count = 0
        is_waitlist = False

    member_status = "waitlisted" if is_waitlist else "enrolled"
    cur = conn.execute(
        """INSERT INTO indoor_session_members (session_id, member_id, headcount, equipment_type, price, status)
           VALUES (?, ?, 1, ?, ?, ?)""",
        (session_id, member_id, equipment_type, pricing.GROUP_CLASS_PRICE or 0, member_status),
    )
    _insert_participants(conn, "indoor_session_member", cur.lastrowid, [participant] if participant else None)
    new_count = current_count if is_waitlist else current_count + 1
    just_confirmed = (not is_waitlist) and new_count >= pricing.GROUP_CLASS_MIN and current_count < pricing.GROUP_CLASS_MIN
    if not is_waitlist and new_count >= pricing.GROUP_CLASS_MIN:
        conn.execute("UPDATE indoor_sessions SET status='confirmed' WHERE id=?", (session_id,))
        if just_confirmed:
            enrolled = conn.execute(
                "SELECT member_id FROM indoor_session_members WHERE session_id=? AND status='enrolled'",
                (session_id,),
            ).fetchall()
            for e in enrolled:
                _log_notification(conn, e["member_id"], "group_class_confirmed",
                                   f"{booking_date} {start_hour}:00 團課已成班,將如期開課")

    if is_waitlist:
        _log_notification(conn, member_id, "group_class_waitlisted",
                           f"{booking_date} {start_hour}:00 團課已滿4人,已為你加入候補名單")

    conn.commit()
    conn.close()
    return {
        "session_id": session_id,
        "enrolled_count": new_count,
        "min_required": pricing.GROUP_CLASS_MIN,
        "max_capacity": pricing.GROUP_CLASS_MAX,
        "price": pricing.GROUP_CLASS_PRICE,
        "waitlisted": is_waitlist,
    }


# ------------------------------------------------------------------
# 跳台體驗(獨立資源,不受機台時段互斥限制)
# ------------------------------------------------------------------
def book_jump(member_id, booking_date, start_time, duration_minutes, equipment_type=None, participants=None):
    price = pricing.compute_jump_price(duration_minutes)
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO jump_bookings (member_id, booking_date, start_time, duration_minutes, equipment_type, price)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (member_id, booking_date, start_time, duration_minutes, equipment_type, price),
    )
    booking_id = cur.lastrowid
    _insert_participants(conn, "jump_booking", booking_id, participants)
    conn.execute(
        """INSERT INTO orders (member_id, order_type, amount, status, ref_type, ref_id)
           VALUES (?, 'jump', ?, 'pending', 'jump_booking', ?)""",
        (member_id, price, booking_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM jump_bookings WHERE id=?", (booking_id,)).fetchone()
    conn.close()
    return dict(row)


# ------------------------------------------------------------------
# A/B 方案訂閱(年費/月費),訂閱成功後才會擁有團課報名資格與包機/自主練習季度額度
# ------------------------------------------------------------------
def apply_for_plan(member_id, plan_name, billing_cycle):
    """客戶申請團課方案,狀態為待審核,需後台審核通過才會正式生效。"""
    if plan_name not in pricing.PLAN_FEE:
        raise ValueError("方案僅接受 A 或 B")
    if billing_cycle not in pricing.PLAN_FEE[plan_name]:
        raise ValueError("計費週期僅接受 annual 或 monthly")
    conn = get_conn()
    existing = conn.execute(
        "SELECT * FROM plan_applications WHERE member_id=? AND status='pending'", (member_id,)
    ).fetchone()
    if existing:
        conn.close()
        raise ValueError("你已經有一筆待審核的方案申請,請等候客服審核")
    cur = conn.execute(
        """INSERT INTO plan_applications (member_id, plan_name, billing_cycle, status)
           VALUES (?, ?, ?, 'pending')""",
        (member_id, plan_name, billing_cycle),
    )
    conn.commit()
    application_id = cur.lastrowid
    conn.close()
    return {"application_id": application_id, "price": pricing.PLAN_FEE[plan_name][billing_cycle]}


def review_plan_application(application_id, staff_id, approve, reason=None):
    """後台審核團課方案申請;核准則正式指派方案(產生費用待付款),拒絕則僅記錄。"""
    conn = get_conn()
    app_row = conn.execute("SELECT * FROM plan_applications WHERE id=?", (application_id,)).fetchone()
    if not app_row:
        conn.close()
        raise ValueError("找不到這筆申請")
    if app_row["status"] != "pending":
        conn.close()
        raise ValueError("這筆申請已經審核過了")

    new_status = "approved" if approve else "rejected"
    conn.execute(
        "UPDATE plan_applications SET status=?, reviewed_by_staff_id=?, reviewed_at=datetime('now') WHERE id=?",
        (new_status, staff_id, application_id),
    )
    conn.commit()
    conn.close()

    notif_conn = get_conn()
    _log_notification(
        notif_conn, app_row["member_id"],
        "plan_application_approved" if approve else "plan_application_rejected",
        f"你申請的方案{app_row['plan_name']}已{'核准,方案已生效' if approve else '被拒絕' + (f'({reason})' if reason else '')}",
    )
    notif_conn.commit()
    notif_conn.close()

    result = {"ok": True, "status": new_status}
    if approve:
        result["plan"] = subscribe_plan(
            member_id=app_row["member_id"], plan_name=app_row["plan_name"],
            billing_cycle=app_row["billing_cycle"], assigned_by_staff_id=staff_id,
        )
    return result


def subscribe_plan(member_id, plan_name, billing_cycle, assigned_by_staff_id=None):
    if plan_name not in pricing.PLAN_FEE:
        raise ValueError("方案僅接受 A 或 B")
    if billing_cycle not in pricing.PLAN_FEE[plan_name]:
        raise ValueError("計費週期僅接受 annual 或 monthly")
    price = pricing.PLAN_FEE[plan_name][billing_cycle]
    conn = get_conn()
    conn.execute("UPDATE member_plans SET is_active=0 WHERE member_id=?", (member_id,))
    cur = conn.execute(
        """INSERT INTO member_plans (member_id, plan_name, billing_cycle, fee_paid, assigned_by_staff_id, is_active)
           VALUES (?, ?, ?, ?, ?, 1)""",
        (member_id, plan_name, billing_cycle, price, assigned_by_staff_id),
    )
    conn.commit()
    plan_id = cur.lastrowid
    conn.close()
    return {"plan_id": plan_id, "plan_name": plan_name, "billing_cycle": billing_cycle, "price": price}


# ------------------------------------------------------------------
# A/B 方案季度額度扣抵
# ------------------------------------------------------------------
def _check_monthly_billing_paid(conn, member_id, plan):
    """
    月繳方案:確認當月已繳費才能使用額度。
    若當月尚無繳費紀錄,自動產生一筆待付款紀錄並回傳 False(擋下,需先付款)。
    年繳方案不受此限制,直接回傳 True。
    """
    if plan["billing_cycle"] != "monthly":
        return True
    period = datetime.now().strftime("%Y-%m")
    record = conn.execute(
        "SELECT * FROM plan_billing_records WHERE member_plan_id=? AND period=?",
        (plan["id"], period),
    ).fetchone()
    if not record:
        conn.execute(
            """INSERT INTO plan_billing_records (member_plan_id, member_id, period, amount, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (plan["id"], member_id, period, plan["fee_paid"]),
        )
        conn.commit()
        return False
    return record["status"] == "paid"


def _get_quota_cycle(conn, plan, on_date):
    """
    回傳 (cycle_key, season_period_for_amounts)。
    不論年繳或月繳,額度週期都是「以第一次使用額度當天(quota_cycle_start)起算,
    每滿一個月為新一期」的滾動月計算,不是固定日曆季節區間。
    年繳/月繳唯一的差異是:月繳需要先確認當月已繳費才能使用額度(見 _check_monthly_billing_paid),
    年繳已一次付清整年費用,不需要每月再次確認繳費。
    """
    if not plan["quota_cycle_start"]:
        conn.execute(
            "UPDATE member_plans SET quota_cycle_start=? WHERE id=?", (on_date, plan["id"])
        )
        start_str = on_date
    else:
        start_str = plan["quota_cycle_start"]

    start = datetime.strptime(start_str, "%Y-%m-%d").date()
    cur = datetime.strptime(on_date, "%Y-%m-%d").date()
    months = (cur.year - start.year) * 12 + (cur.month - start.month)
    if cur.day < start.day:
        months -= 1
    cycle_index = max(months, 0)

    total_month_index = (start.month - 1) + cycle_index
    cycle_month = total_month_index % 12 + 1
    season_period = "summer" if cycle_month in pricing.SUMMER_MONTHS else "winter"
    return str(cycle_index), season_period


def _consume_quota(conn, member_id, booking_date, quota_type):
    """quota_type: 'charter' or 'self_practice' 或 'group_class'。成功扣抵回傳 True,額度不足回傳 False。"""
    plan = conn.execute(
        "SELECT * FROM member_plans WHERE member_id=? AND is_active=1", (member_id,)
    ).fetchone()
    if not plan:
        return False

    if not _check_monthly_billing_paid(conn, member_id, plan):
        return False

    cycle_key, season_period = _get_quota_cycle(conn, plan, booking_date)
    quota_rule = pricing.get_plan_quota(plan["plan_name"], season_period)
    allowed = quota_rule[quota_type]

    usage = conn.execute(
        "SELECT * FROM member_quota_cycles WHERE member_id=? AND cycle_key=?",
        (member_id, cycle_key),
    ).fetchone()

    used = usage[f"{quota_type}_used"] if usage else 0
    if used >= allowed:
        return False

    if usage:
        conn.execute(
            f"""UPDATE member_quota_cycles SET {quota_type}_used = {quota_type}_used + 1
                WHERE id=?""",
            (usage["id"],),
        )
    else:
        col = f"{quota_type}_used"
        conn.execute(
            f"""INSERT INTO member_quota_cycles (member_id, cycle_key, {col}) VALUES (?, ?, 1)""",
            (member_id, cycle_key),
        )
    return True


def _peek_quota_cycle(plan, on_date):
    """唯讀版本:查詢用,不會像 _get_quota_cycle 一樣在尚未使用時就設定 quota_cycle_start。"""
    if not plan["quota_cycle_start"]:
        # 尚未開始使用額度,顯示以「今天」為起點的第0期供參考
        season_period, _ = pricing.season_period_and_year(on_date)
        return "0", season_period
    start = datetime.strptime(plan["quota_cycle_start"], "%Y-%m-%d").date()
    cur = datetime.strptime(on_date, "%Y-%m-%d").date()
    months = (cur.year - start.year) * 12 + (cur.month - start.month)
    if cur.day < start.day:
        months -= 1
    cycle_index = max(months, 0)
    total_month_index = (start.month - 1) + cycle_index
    cycle_month = total_month_index % 12 + 1
    season_period = "summer" if cycle_month in pricing.SUMMER_MONTHS else "winter"
    return str(cycle_index), season_period


def get_quota_status(member_id, on_date):
    conn = get_conn()
    plan = conn.execute(
        "SELECT * FROM member_plans WHERE member_id=? AND is_active=1", (member_id,)
    ).fetchone()
    if not plan:
        conn.close()
        return None
    cycle_key, season_period = _peek_quota_cycle(plan, on_date)
    quota_rule = pricing.get_plan_quota(plan["plan_name"], season_period)
    usage = conn.execute(
        "SELECT * FROM member_quota_cycles WHERE member_id=? AND cycle_key=?",
        (member_id, cycle_key),
    ).fetchone()
    monthly_paid = True
    current_month_billing = None
    if plan["billing_cycle"] == "monthly":
        period = datetime.now().strftime("%Y-%m")
        record = conn.execute(
            "SELECT * FROM plan_billing_records WHERE member_plan_id=? AND period=?",
            (plan["id"], period),
        ).fetchone()
        monthly_paid = bool(record and record["status"] == "paid")
        current_month_billing = dict(record) if record else None
    conn.close()
    used = dict(usage) if usage else {"charter_used": 0, "self_practice_used": 0, "group_class_used": 0}
    return {
        "plan_name": plan["plan_name"],
        "billing_cycle": plan["billing_cycle"],
        "cycle_key": cycle_key,
        "quota_cycle_start": plan["quota_cycle_start"],
        "charter_total": quota_rule["charter"],
        "charter_used": used["charter_used"],
        "self_practice_total": quota_rule["self_practice"],
        "self_practice_used": used["self_practice_used"],
        "group_class_total": quota_rule["group_class"],
        "group_class_used": used.get("group_class_used", 0),
        "monthly_paid": monthly_paid,
        "current_month_billing": current_month_billing,
    }


# ------------------------------------------------------------------
# 日本教練課(可跨多日,每天各自選半日/全日/雪場/人數;
# 若指定教練,需確認該教練在所選的每一天都能上班)
# ------------------------------------------------------------------
JAPAN_ACTIVE_STATUSES = ("pending_payment", "confirmed")


def _resort_available_coaches(conn, resort_id, date_str):
    """回傳該雪場在該日期「有上班」的教練 id 清單(依後台指派的雪場教練名單扣除請假/出差)。"""
    roster = conn.execute(
        "SELECT coach_id FROM resort_coaches WHERE resort_id=?", (resort_id,)
    ).fetchall()
    available = []
    for r in roster:
        leave = conn.execute(
            """SELECT 1 FROM coach_schedule WHERE coach_id=? AND work_date=?
               AND status != 'working'""",
            (r["coach_id"], date_str),
        ).fetchone()
        if not leave:
            available.append(r["coach_id"])
    return available


def book_japan_multi_day(member_id, bookings, equipment_type=None, participants=None, needs_accommodation=False):
    """
    bookings: [{'resort_id':1,'date':'2026-12-20','day_type':'full'|'half',
                'half_day_slot':'morning'|'afternoon'|None,'headcount':2,
                'coach_id':3|None}, ...]
    equipment_type / participants:整趟行程共用一組(教練與雪場整趟行程一致,人員資料也是同一批人)
    """
    conn = get_conn()

    for b in bookings:
        try:
            pricing.validate_japan_season(b["date"])
        except ValueError as e:
            conn.close()
            raise e

        if b.get("coach_id"):
            # 指定教練:確認當天有上班
            leave = conn.execute(
                """SELECT * FROM coach_schedule WHERE coach_id=? AND work_date=?
                   AND status != 'working'""",
                (b["coach_id"], b["date"]),
            ).fetchone()
            if leave:
                conn.close()
                raise ValueError(f"指定教練於 {b['date']} 無法上班({leave['status']}),請洽詢客服")
            # 指定教練:確認當天還沒被其他人訂走(一位教練一天僅能帶一組)
            taken = conn.execute(
                f"""SELECT * FROM japan_bookings
                    WHERE coach_id=? AND booking_date=?
                    AND status IN ({",".join("?"*len(JAPAN_ACTIVE_STATUSES))})""",
                (b["coach_id"], b["date"], *JAPAN_ACTIVE_STATUSES),
            ).fetchone()
            if taken:
                conn.close()
                raise ValueError(f"該教練於 {b['date']} 已有課程,無法訂課,請選擇其他教練或日期")
        else:
            # 不指定教練:依雪場教練名單計算容量,避免 over booking
            available = _resort_available_coaches(conn, b["resort_id"], b["date"])
            existing_count = conn.execute(
                f"""SELECT COUNT(*) c FROM japan_bookings
                    WHERE resort_id=? AND booking_date=?
                    AND status IN ({",".join("?"*len(JAPAN_ACTIVE_STATUSES))})""",
                (b["resort_id"], b["date"], *JAPAN_ACTIVE_STATUSES),
            ).fetchone()["c"]
            if existing_count >= len(available):
                conn.close()
                raise ValueError(f"該雪場於 {b['date']} 教練已全數排滿,請洽詢客服或選擇其他日期/雪場")

    group_key = uuid.uuid4().hex[:12]
    created = []
    total_price = 0
    first_booking_id = None
    for b in bookings:
        designate = bool(b.get("coach_id"))
        if b["day_type"] == "half" and not b.get("half_day_slot"):
            conn.close()
            raise ValueError("半日課請選擇上午(9-12)或下午(13-16)時段")
        price = pricing.compute_japan_price(b["day_type"], b["headcount"], designate)
        cur = conn.execute(
            """INSERT INTO japan_bookings
               (member_id, resort_id, booking_date, day_type, half_day_slot,
                headcount, equipment_type, coach_id, designate_coach, needs_accommodation, price, group_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (member_id, b["resort_id"], b["date"], b["day_type"], b.get("half_day_slot"),
             b["headcount"], equipment_type, b.get("coach_id"), designate,
             bool(needs_accommodation), price, group_key),
        )
        created.append(cur.lastrowid)
        if first_booking_id is None:
            first_booking_id = cur.lastrowid
        total_price += price
    _insert_participants(conn, "japan_booking", first_booking_id, participants)
    conn.execute(
        """INSERT INTO orders (member_id, order_type, amount, status, ref_type, ref_id)
           VALUES (?, 'japan_trip', ?, 'pending', 'japan_booking', ?)""",
        (member_id, total_price, first_booking_id),
    )
    conn.commit()
    conn.close()
    return {"group_key": group_key, "booking_ids": created, "total_price": total_price}


# ------------------------------------------------------------------
# 後台:訂客資料總覽(彙整所有類型的預約紀錄,供客服以上查詢)
# ------------------------------------------------------------------
CATEGORY_LABEL = {
    "trial": "體驗課",
    "charter": "包機課",
    "self_practice": "自主練習",
    "group_class": "團課",
    "jump": "跳台體驗",
    "japan": "日本教練課",
}


def _payment_info(conn, ref_type, ref_id):
    """依 ref_type/ref_id 查最新一筆付款紀錄,回傳 (payment_status, payment_method) 或 (None, None)。"""
    tx = conn.execute(
        """SELECT payment_status, payment_method FROM transactions
           WHERE ref_type=? AND ref_id=? ORDER BY created_at DESC LIMIT 1""",
        (ref_type, ref_id),
    ).fetchone()
    if not tx:
        return None, None
    return tx["payment_status"], tx["payment_method"]


def _payment_label(payment_status, payment_method):
    if not payment_status:
        return "已預約・未付款"
    if payment_status == "confirmed":
        method_label = {"online_card": "已刷卡", "onsite": "已現場付款", "bank_transfer": "已匯款"}.get(payment_method, "已付款")
        return f"已預約・{method_label}"
    if payment_status == "awaiting_backoffice_review":
        method_label = {"onsite": "現場付款", "bank_transfer": "匯款"}.get(payment_method, "付款")
        return f"已預約・待核對({method_label})"
    return "已預約・未付款"


def get_all_bookings(member_id=None, category=None, date_from=None, date_to=None, coach_id=None):
    conn = get_conn()
    rows = []

    # 體驗/包機/自主練習/團課(indoor_sessions + indoor_session_members)
    q = """
        SELECT sm.id AS member_ref_id, s.id AS session_id, m.id AS member_id, m.name AS member_name, m.phone AS member_phone,
               s.category, s.booking_date, s.start_hour, s.duration_minutes,
               s.status, sm.headcount, sm.equipment_type, sm.price, s.coach_id, st.name AS coach_name
        FROM indoor_session_members sm
        JOIN indoor_sessions s ON sm.session_id = s.id
        JOIN members m ON sm.member_id = m.id
        LEFT JOIN staff st ON s.coach_id = st.id
        WHERE sm.status = 'enrolled'
    """
    params = []
    if member_id:
        q += " AND m.id = ?"
        params.append(member_id)
    if coach_id:
        q += " AND s.coach_id = ?"
        params.append(coach_id)
    if date_from:
        q += " AND s.booking_date >= ?"
        params.append(date_from)
    if date_to:
        q += " AND s.booking_date <= ?"
        params.append(date_to)
    for r in conn.execute(q, params).fetchall():
        if category and r["category"] != category:
            continue
        pay_status, pay_method = _payment_info(conn, "indoor_session", r["session_id"])
        if r["category"] == "charter":
            payment_label = "已預約・已付款(堂數包)"
        elif r["category"] == "group_class" and not r["price"]:
            payment_label = "已預約・免費(方案資格內)"
        elif r["category"] == "self_practice" and not r["price"]:
            payment_label = "已預約・免費(方案額度扣抵)"
        else:
            payment_label = _payment_label(pay_status, pay_method)
        rows.append({
            "booking_ref_id": r["member_ref_id"], "session_id": r["session_id"],
            "member_id": r["member_id"], "member_name": r["member_name"],
            "member_phone": r["member_phone"], "category": r["category"],
            "category_label": CATEGORY_LABEL.get(r["category"], r["category"]),
            "date": r["booking_date"], "time": f"{r['start_hour']}:00",
            "duration_minutes": r["duration_minutes"], "status": r["status"],
            "headcount": r["headcount"], "equipment_type": r["equipment_type"], "price": r["price"],
            "coach_id": r["coach_id"], "coach_name": r["coach_name"],
            "payment_status": pay_status, "payment_method": pay_method,
            "payment_label": payment_label,
        })

    # 跳台體驗
    if not category or category == "jump":
        q = "SELECT j.*, m.name AS member_name, m.phone AS member_phone FROM jump_bookings j JOIN members m ON j.member_id = m.id WHERE 1=1"
        params = []
        if member_id:
            q += " AND m.id = ?"; params.append(member_id)
        if date_from:
            q += " AND j.booking_date >= ?"; params.append(date_from)
        if date_to:
            q += " AND j.booking_date <= ?"; params.append(date_to)
        for r in conn.execute(q, params).fetchall():
            pay_status, pay_method = _payment_info(conn, "jump_booking", r["id"])
            rows.append({
                "booking_ref_id": r["id"],
                "member_id": r["member_id"], "member_name": r["member_name"],
                "member_phone": r["member_phone"], "category": "jump",
                "category_label": CATEGORY_LABEL["jump"],
                "date": r["booking_date"], "time": r["start_time"],
                "duration_minutes": r["duration_minutes"], "status": r["status"],
                "headcount": None, "price": r["price"],
                "payment_status": pay_status, "payment_method": pay_method,
                "payment_label": _payment_label(pay_status, pay_method),
            })

    # 日本教練課
    if not category or category == "japan":
        q = """SELECT j.*, m.name AS member_name, m.phone AS member_phone, r.name AS resort_name,
                      st.name AS coach_name
               FROM japan_bookings j JOIN members m ON j.member_id = m.id
               JOIN ski_resorts r ON j.resort_id = r.id
               LEFT JOIN staff st ON j.coach_id = st.id WHERE 1=1"""
        params = []
        if member_id:
            q += " AND m.id = ?"; params.append(member_id)
        if coach_id:
            q += " AND j.coach_id = ?"; params.append(coach_id)
        if date_from:
            q += " AND j.booking_date >= ?"; params.append(date_from)
        if date_to:
            q += " AND j.booking_date <= ?"; params.append(date_to)
        for r in conn.execute(q, params).fetchall():
            # 同一趟行程(group_key)共用第一天的付款紀錄
            pay_status, pay_method = _payment_info(conn, "japan_booking", r["id"])
            if not pay_status:
                first_id = conn.execute(
                    "SELECT id FROM japan_bookings WHERE group_key=? ORDER BY booking_date LIMIT 1",
                    (r["group_key"],),
                ).fetchone()
                if first_id and first_id["id"] != r["id"]:
                    pay_status, pay_method = _payment_info(conn, "japan_booking", first_id["id"])
            rows.append({
                "booking_ref_id": r["id"], "group_key": r["group_key"],
                "member_id": r["member_id"], "member_name": r["member_name"],
                "member_phone": r["member_phone"], "category": "japan",
                "category_label": CATEGORY_LABEL["japan"],
                "date": r["booking_date"],
                "time": r["day_type"] + (f"/{r['half_day_slot']}" if r["half_day_slot"] else ""),
                "duration_minutes": None, "status": r["status"],
                "headcount": r["headcount"], "price": r["price"],
                "resort_name": r["resort_name"],
                "equipment_type": r["equipment_type"], "needs_accommodation": bool(r["needs_accommodation"]),
                "coach_id": r["coach_id"], "coach_name": r["coach_name"] or ("不指定" if not r["designate_coach"] else None),
                "payment_status": pay_status, "payment_method": pay_method,
                "payment_label": _payment_label(pay_status, pay_method),
            })

    conn.close()
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


# ============================================================
# 客戶自行修改/取消預約(含時間限制:日本教練課提前1個月、室內滑雪提前3天;
# 若由客服以上員工操作(is_staff=True),不受此限制)
# ============================================================
INDOOR_SELF_EDIT_DAYS = 3
JAPAN_SELF_EDIT_DAYS = 30


def _check_edit_window(booking_date_str, min_days, is_staff):
    if is_staff:
        return
    days_left = (datetime.strptime(booking_date_str, "%Y-%m-%d").date() - datetime.now().date()).days
    if days_left < min_days:
        raise ValueError(f"課程開始前 {min_days} 天內無法自行修改/取消,請洽客服協助處理")


def cancel_indoor_booking(member_ref_id, is_staff=False):
    conn = get_conn()
    row = conn.execute(
        """SELECT sm.*, s.booking_date, s.category, s.charter_package_size
           FROM indoor_session_members sm JOIN indoor_sessions s ON sm.session_id = s.id
           WHERE sm.id=?""",
        (member_ref_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise ValueError("找不到這筆預約")
    if row["status"] == "cancelled":
        conn.close()
        raise ValueError("這筆預約已經取消過了")

    _check_edit_window(row["booking_date"], INDOOR_SELF_EDIT_DAYS, is_staff)

    conn.execute("UPDATE indoor_session_members SET status='cancelled' WHERE id=?", (member_ref_id,))

    # 包機:取消後把堂數還給會員的堂數包
    if row["category"] == "charter":
        pass_row = conn.execute(
            """SELECT id FROM charter_passes WHERE member_id=? AND package_size=? ORDER BY id DESC LIMIT 1""",
            (row["member_id"], row["charter_package_size"]),
        ).fetchone()
        if pass_row:
            conn.execute("UPDATE charter_passes SET remaining = remaining + 1 WHERE id=?", (pass_row["id"],))
            conn.execute(
                """INSERT INTO entitlement_ledger
                   (member_id, entitlement_type, entitlement_ref_id, change_type, amount, booking_ref_type, booking_ref_id, note)
                   VALUES (?, 'charter_pass', ?, 'release', 1, 'indoor_session_member', ?, ?)""",
                (row["member_id"], pass_row["id"], member_ref_id, "取消預約,解除圈存1堂"),
            )

    # 團課:若場次剩餘人數低於開課門檻,場次狀態改回 open;取消的是正式名額則遞補候補
    if row["category"] == "group_class":
        if row["status"] == "enrolled":
            waitlisted = conn.execute(
                """SELECT * FROM indoor_session_members WHERE session_id=? AND status='waitlisted'
                   ORDER BY created_at LIMIT 1""",
                (row["session_id"],),
            ).fetchone()
            if waitlisted:
                conn.execute(
                    "UPDATE indoor_session_members SET status='enrolled' WHERE id=?", (waitlisted["id"],)
                )
                _log_notification(
                    conn, waitlisted["member_id"], "waitlist_promoted",
                    f"{row['booking_date']} 團課候補遞補成功,已確認為正式名額,請留意上課時間",
                )
        remaining_count = conn.execute(
            "SELECT COUNT(*) c FROM indoor_session_members WHERE session_id=? AND status='enrolled'",
            (row["session_id"],),
        ).fetchone()["c"]
        new_status = "confirmed" if remaining_count >= pricing.GROUP_CLASS_MIN else "open"
        conn.execute("UPDATE indoor_sessions SET status=? WHERE id=?", (new_status, row["session_id"]))

    # 若該場次已經沒有任何有效報名人,場次本身也標記取消
    still_enrolled = conn.execute(
        "SELECT COUNT(*) c FROM indoor_session_members WHERE session_id=? AND status='enrolled'",
        (row["session_id"],),
    ).fetchone()["c"]
    if still_enrolled == 0:
        conn.execute("UPDATE indoor_sessions SET status='cancelled' WHERE id=?", (row["session_id"],))

    conn.commit()
    conn.close()
    return {"ok": True}


def reschedule_indoor_booking(member_ref_id, new_date, new_hour, is_staff=False):
    conn = get_conn()
    row = conn.execute(
        """SELECT sm.*, s.booking_date, s.start_hour, s.duration_minutes, s.category, s.id AS session_id
           FROM indoor_session_members sm JOIN indoor_sessions s ON sm.session_id = s.id
           WHERE sm.id=?""",
        (member_ref_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise ValueError("找不到這筆預約")

    _check_edit_window(row["booking_date"], INDOOR_SELF_EDIT_DAYS, is_staff)
    _validate_hour(new_hour)

    conflict = _has_conflict(conn, new_date, new_hour, row["duration_minutes"], exclude_session_id=row["session_id"])
    if conflict:
        conn.close()
        raise ValueError("新時段已被其他課程佔用,請選擇其他時段")

    conn.execute(
        "UPDATE indoor_sessions SET booking_date=?, start_hour=? WHERE id=?",
        (new_date, new_hour, row["session_id"]),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


def cancel_jump_booking(jump_booking_id, is_staff=False):
    conn = get_conn()
    row = conn.execute("SELECT * FROM jump_bookings WHERE id=?", (jump_booking_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("找不到這筆預約")
    if row["status"] == "cancelled":
        conn.close()
        raise ValueError("這筆預約已經取消過了")
    _check_edit_window(row["booking_date"], INDOOR_SELF_EDIT_DAYS, is_staff)
    conn.execute("UPDATE jump_bookings SET status='cancelled' WHERE id=?", (jump_booking_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


def reschedule_jump_booking(jump_booking_id, new_date, new_time, is_staff=False):
    conn = get_conn()
    row = conn.execute("SELECT * FROM jump_bookings WHERE id=?", (jump_booking_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("找不到這筆預約")
    _check_edit_window(row["booking_date"], INDOOR_SELF_EDIT_DAYS, is_staff)
    conn.execute(
        "UPDATE jump_bookings SET booking_date=?, start_time=? WHERE id=?",
        (new_date, new_time, jump_booking_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


def cancel_japan_trip(group_key, is_staff=False):
    conn = get_conn()
    trip_rows = conn.execute(
        "SELECT * FROM japan_bookings WHERE group_key=? ORDER BY booking_date", (group_key,)
    ).fetchall()
    if not trip_rows:
        conn.close()
        raise ValueError("找不到這趟行程")
    earliest_date = trip_rows[0]["booking_date"]
    _check_edit_window(earliest_date, JAPAN_SELF_EDIT_DAYS, is_staff)
    conn.execute("UPDATE japan_bookings SET status='cancelled' WHERE group_key=?", (group_key,))
    conn.commit()
    conn.close()
    return {"ok": True, "cancelled_days": len(trip_rows)}


# ============================================================
# 管理報表 / 營收統計(對照系統分析書 M12)
# ============================================================
ORDER_TYPE_LABEL = {
    "charter_pass": "包機堂數包",
    "trial": "體驗課",
    "self_practice": "自主練習",
    "jump": "跳台體驗",
    "japan_trip": "日本教練課",
    "plan_subscription": "團課方案",
}


def get_report_summary(date_from, date_to):
    conn = get_conn()

    # 營收(以已付款訂單為準,對照系統分析書「報表由交易明細彙總」原則)
    revenue_rows = conn.execute(
        """SELECT order_type, COUNT(*) c, SUM(amount) total
           FROM orders WHERE status='paid' AND created_at >= ? AND created_at < ?
           GROUP BY order_type""",
        (date_from, date_to + " 23:59:59"),
    ).fetchall()
    revenue_by_type = [
        {"order_type": r["order_type"], "label": ORDER_TYPE_LABEL.get(r["order_type"], r["order_type"]),
         "count": r["c"], "total": r["total"]}
        for r in revenue_rows
    ]
    total_revenue = sum(r["total"] for r in revenue_by_type)

    # 訂閱方案費用(不透過orders表,額外加總)
    plan_fee_row = conn.execute(
        "SELECT COUNT(*) c, SUM(fee_paid) total FROM member_plans WHERE created_at >= ? AND created_at < ?",
        (date_from, date_to + " 23:59:59"),
    ).fetchone()
    if plan_fee_row["total"]:
        total_revenue += plan_fee_row["total"]
        revenue_by_type.append({
            "order_type": "plan_subscription", "label": "團課方案",
            "count": plan_fee_row["c"], "total": plan_fee_row["total"],
        })

    # 各課程種類預約堂數(不含取消)
    booking_counts = {}
    for cat in ("trial", "charter", "self_practice", "group_class"):
        c = conn.execute(
            """SELECT COUNT(*) c FROM indoor_sessions
               WHERE category=? AND status != 'cancelled' AND booking_date >= ? AND booking_date <= ?""",
            (cat, date_from, date_to),
        ).fetchone()["c"]
        booking_counts[cat] = c
    booking_counts["jump"] = conn.execute(
        "SELECT COUNT(*) c FROM jump_bookings WHERE status != 'cancelled' AND booking_date >= ? AND booking_date <= ?",
        (date_from, date_to),
    ).fetchone()["c"]
    booking_counts["japan"] = conn.execute(
        "SELECT COUNT(*) c FROM japan_bookings WHERE status != 'cancelled' AND booking_date >= ? AND booking_date <= ?",
        (date_from, date_to),
    ).fetchone()["c"]

    # 機台利用率(已預約時數 / 總可預約時數)
    booked_hours = conn.execute(
        """SELECT SUM(CAST((duration_minutes + 59) / 60 AS INTEGER)) h FROM indoor_sessions
           WHERE status != 'cancelled' AND booking_date >= ? AND booking_date <= ?""",
        (date_from, date_to),
    ).fetchone()["h"] or 0
    days = (datetime.strptime(date_to, "%Y-%m-%d") - datetime.strptime(date_from, "%Y-%m-%d")).days + 1
    total_available_hours = days * (pricing.INDOOR_LAST_START_HOUR - pricing.INDOOR_START_HOUR + 1)
    utilization = round(booked_hours / total_available_hours * 100, 1) if total_available_hours else 0

    # 教練績效(帶課次數,室內+日本合計)
    coach_rows = conn.execute(
        """SELECT st.id, st.name, COUNT(*) c FROM indoor_sessions s
           JOIN staff st ON s.coach_id = st.id
           WHERE s.status != 'cancelled' AND s.booking_date >= ? AND s.booking_date <= ?
           GROUP BY st.id""",
        (date_from, date_to),
    ).fetchall()
    coach_perf = {r["id"]: {"name": r["name"], "count": r["c"]} for r in coach_rows}
    japan_coach_rows = conn.execute(
        """SELECT st.id, st.name, COUNT(*) c FROM japan_bookings j
           JOIN staff st ON j.coach_id = st.id
           WHERE j.status != 'cancelled' AND j.booking_date >= ? AND j.booking_date <= ?
           GROUP BY st.id""",
        (date_from, date_to),
    ).fetchall()
    for r in japan_coach_rows:
        if r["id"] in coach_perf:
            coach_perf[r["id"]]["count"] += r["c"]
        else:
            coach_perf[r["id"]] = {"name": r["name"], "count": r["c"]}

    # 體驗課轉正式課程追蹤:曾上過體驗課的會員中,有多少人後續也訂了包機或團課
    trial_member_ids = [r["member_id"] for r in conn.execute(
        """SELECT DISTINCT sm.member_id FROM indoor_session_members sm
           JOIN indoor_sessions s ON sm.session_id = s.id
           WHERE s.category='trial' AND sm.status='enrolled'"""
    ).fetchall()]
    converted = 0
    for mid in trial_member_ids:
        has_paid_course = conn.execute(
            """SELECT 1 FROM indoor_session_members sm JOIN indoor_sessions s ON sm.session_id = s.id
               WHERE sm.member_id=? AND s.category IN ('charter','group_class') AND sm.status='enrolled' LIMIT 1""",
            (mid,),
        ).fetchone()
        if has_paid_course:
            converted += 1
    trial_conversion = {
        "trial_customers": len(trial_member_ids),
        "converted_to_paid": converted,
        "conversion_rate_pct": round(converted / len(trial_member_ids) * 100, 1) if trial_member_ids else 0,
    }

    conn.close()
    return {
        "date_from": date_from, "date_to": date_to,
        "total_revenue": total_revenue,
        "revenue_by_type": revenue_by_type,
        "booking_counts": booking_counts,
        "machine_utilization_pct": utilization,
        "coach_performance": sorted(coach_perf.values(), key=lambda x: -x["count"]),
        "trial_conversion": trial_conversion,
    }
