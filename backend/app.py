from flask import Flask, request, jsonify, send_from_directory
import functools
import os
import json

from db import get_conn, init_db, rows_to_dicts
import auth
import booking
import pricing

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
app = Flask(__name__)


@app.route("/")
def serve_frontend():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Staff-Id"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response


@app.route("/api/<path:_any>", methods=["OPTIONS"])
def cors_preflight(_any):
    return "", 204


ROLE_RANK = {"coach": 1, "cs": 2, "manager": 3, "boss": 4}


def require_role(min_role):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            work_id = request.headers.get("X-Staff-Id")
            conn = get_conn()
            staff = conn.execute("SELECT * FROM staff WHERE work_id=?", (work_id,)).fetchone()
            conn.close()
            if not staff:
                return jsonify({"error": "未登入或工號無效"}), 401
            if ROLE_RANK.get(staff["role"], 0) < ROLE_RANK[min_role]:
                return jsonify({"error": "權限不足"}), 403
            request.current_staff = dict(staff)
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ------------------------------------------------------------------
# 會員登入 / 建立
# ------------------------------------------------------------------
@app.route("/api/auth/oauth-login", methods=["POST"])
def oauth_login():
    data = request.json
    result = auth.mock_oauth_login(data["provider"], data["mock_external_id"])
    return jsonify(result)


@app.route("/api/auth/create-member", methods=["POST"])
def create_member():
    member = auth.create_member(request.json)
    return jsonify(member), 201


@app.route("/api/auth/staff-login", methods=["POST"])
def staff_login_route():
    data = request.json
    staff = auth.staff_login(data["work_id"], data["password"])
    if not staff:
        return jsonify({"error": "工號或密碼錯誤"}), 401
    return jsonify(staff)


@app.route("/api/members/<int:member_id>", methods=["GET"])
def get_member(member_id):
    conn = get_conn()
    m = conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    passes = conn.execute("SELECT * FROM charter_passes WHERE member_id=?", (member_id,)).fetchall()
    plan = conn.execute(
        "SELECT * FROM member_plans WHERE member_id=? AND is_active=1", (member_id,)
    ).fetchone()
    conn.close()
    if not m:
        return jsonify({"error": "member not found"}), 404
    from datetime import date
    today = date.today().isoformat()
    quota = booking.get_quota_status(member_id, today)

    all_bookings = booking.get_all_bookings(member_id=member_id)
    my_bookings = [b for b in all_bookings if b["status"] != "cancelled"]
    # 保留原本 upcoming/incomplete 欄位供舊版相容(以付款狀態判斷,而非課程狀態)
    upcoming = [b for b in my_bookings if b["payment_status"] == "confirmed"]
    incomplete = [b for b in my_bookings if b["payment_status"] != "confirmed"]

    return jsonify({
        "member": dict(m),
        "member_code": compute_member_code(dict(m)),
        "charter_passes": rows_to_dicts(passes),
        "plan": dict(plan) if plan else None,
        "quota_status": quota,
        "my_bookings": my_bookings,
        "upcoming_bookings": upcoming,
        "incomplete_bookings": incomplete,
    })


def compute_member_code(m):
    """會員編號 = 註冊年(4碼)+月(2碼)+滑行項目(ski=1/snowboard=2)+性別(男=1/女=2)+流水序號(4碼,用會員id補零)。
       性別或主要滑行項目尚未填寫時回傳 None(前端顯示尚未產生編號)。"""
    if not m.get("gender") or not m.get("primary_equipment") or not m.get("created_at"):
        return None
    year = m["created_at"][0:4]
    month = m["created_at"][5:7]
    equip_digit = "1" if m["primary_equipment"] == "ski" else "2"
    gender_digit = "1" if m["gender"] == "male" else "2"
    seq = str(m["id"]).zfill(4)
    return f"{year}{month}{equip_digit}{gender_digit}{seq}"


@app.route("/api/members/<int:member_id>/notifications", methods=["GET"])
def member_notifications(member_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE member_id=? ORDER BY created_at DESC LIMIT 50", (member_id,)
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/members/<int:member_id>/entitlement-ledger", methods=["GET"])
def member_entitlement_ledger(member_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM entitlement_ledger WHERE member_id=? ORDER BY created_at DESC LIMIT 50", (member_id,)
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/members/<int:member_id>/profile", methods=["PUT"])
def update_member_profile(member_id):
    d = request.json
    fields = [
        "name", "phone", "emergency_contact_name", "emergency_contact_phone",
        "birth_date", "gender", "id_number", "blood_type", "address",
        "line_id", "social_handle", "height_cm", "weight_kg",
        "snowboard_length", "snowboard_boot_size", "ski_length", "ski_boot_size",
        "machine_level", "snow_level", "primary_equipment",
    ]
    updates = {k: v for k, v in d.items() if k in fields}
    if not updates:
        return jsonify({"error": "no valid fields"}), 400
    set_clause = ", ".join(f"{k}=?" for k in updates)
    conn = get_conn()
    conn.execute(f"UPDATE members SET {set_clause} WHERE id=?", (*updates.values(), member_id))
    conn.commit()
    row = conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    conn.close()
    return jsonify(dict(row))


# ------------------------------------------------------------------
# 價目表(前台課表顯示用)
# ------------------------------------------------------------------
@app.route("/api/pricing", methods=["GET"])
def get_pricing():
    return jsonify({
        "trial": pricing.TRIAL_PRICE,
        "charter": pricing.CHARTER_PRICE,
        "self_practice": pricing.SELF_PRACTICE_PRICE,
        "jump": pricing.JUMP_PRICE,
        "japan_full_day": pricing.JAPAN_FULL_DAY_PRICE,
        "japan_half_day": pricing.JAPAN_HALF_DAY_PRICE,
        "japan_designate_coach_fee": pricing.JAPAN_COACH_DESIGNATE_FEE,
        "group_class_min": pricing.GROUP_CLASS_MIN,
        "group_class_max": pricing.GROUP_CLASS_MAX,
        "indoor_hours": {"start": pricing.INDOOR_START_HOUR, "last_start": pricing.INDOOR_LAST_START_HOUR},
        "plan_quota": pricing.PLAN_QUOTA,
        "plan_fee": pricing.PLAN_FEE,
        "booking_window_days": pricing.BOOKING_WINDOW_DAYS,
        "japan_season_months": sorted(pricing.JAPAN_SEASON_MONTHS),
    })


# ------------------------------------------------------------------
# 室內滑雪:日曆可用性(某月/某日的機台狀況 + 跳台預約)
# ------------------------------------------------------------------
@app.route("/api/indoor/day/<date_str>", methods=["GET"])
def indoor_day_view(date_str):
    conn = get_conn()
    sessions = conn.execute(
        """SELECT * FROM indoor_sessions WHERE booking_date=?
           AND status != 'cancelled' ORDER BY start_hour""",
        (date_str,),
    ).fetchall()
    result = []
    for s in sessions:
        members = conn.execute(
            "SELECT * FROM indoor_session_members WHERE session_id=? AND status='enrolled'",
            (s["id"],),
        ).fetchall()
        result.append({**dict(s), "members": rows_to_dicts(members)})
    jumps = conn.execute(
        "SELECT * FROM jump_bookings WHERE booking_date=? AND status != 'cancelled'",
        (date_str,),
    ).fetchall()
    conn.close()
    return jsonify({"indoor_sessions": result, "jump_bookings": rows_to_dicts(jumps)})


# ------------------------------------------------------------------
# 體驗課
# ------------------------------------------------------------------
@app.route("/api/booking/trial", methods=["POST"])
def book_trial():
    d = request.json
    try:
        result = booking.book_trial(
            member_id=d["member_id"], booking_date=d["booking_date"],
            start_hour=d["start_hour"], headcount=d["headcount"],
            equipment_type=d.get("equipment_type"), participants=d.get("participants"),
            coach_id=d.get("coach_id"),
        )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ------------------------------------------------------------------
# 包機課(先購買堂數包,再用堂數包預約時段)
# ------------------------------------------------------------------
@app.route("/api/charter/purchase", methods=["POST"])
def purchase_charter():
    d = request.json
    try:
        result = booking.purchase_charter_pass(
            member_id=d["member_id"], package_size=d["package_size"], headcount_type=d["headcount_type"]
        )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/booking/charter", methods=["POST"])
def book_charter():
    d = request.json
    try:
        result = booking.book_charter(
            member_id=d["member_id"], booking_date=d["booking_date"], start_hour=d["start_hour"],
            charter_pass_id=d["charter_pass_id"],
            equipment_type=d.get("equipment_type"), participants=d.get("participants"),
            coach_id=d.get("coach_id"),
        )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ------------------------------------------------------------------
# 自主練習
# ------------------------------------------------------------------
@app.route("/api/booking/self-practice", methods=["POST"])
def book_self_practice():
    d = request.json
    try:
        result = booking.book_self_practice(
            member_id=d["member_id"], booking_date=d["booking_date"], start_hour=d["start_hour"],
            duration_minutes=d["duration_minutes"], headcount=d.get("headcount", 1),
            equipment_type=d.get("equipment_type"), participants=d.get("participants"),
            use_plan_quota=d.get("use_plan_quota", False),
        )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ------------------------------------------------------------------
# 團課
# ------------------------------------------------------------------
@app.route("/api/booking/group-class", methods=["POST"])
def enroll_group_class():
    d = request.json
    try:
        result = booking.enroll_group_class(
            member_id=d["member_id"], booking_date=d["booking_date"], start_hour=d["start_hour"],
            equipment_type=d.get("equipment_type"), participant=d.get("participant"),
        )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ------------------------------------------------------------------
# 跳台體驗
# ------------------------------------------------------------------
@app.route("/api/booking/jump", methods=["POST"])
def book_jump():
    d = request.json
    try:
        result = booking.book_jump(
            member_id=d["member_id"], booking_date=d["booking_date"],
            start_time=d["start_time"], duration_minutes=d["duration_minutes"],
            equipment_type=d.get("equipment_type"), participants=d.get("participants"),
        )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ------------------------------------------------------------------
# 日本教練課
# ------------------------------------------------------------------
@app.route("/api/japan-regions", methods=["GET"])
def list_japan_regions():
    """公開API:回傳所有分區,每個分區附帶該分區的雪場清單(若需要選擇雪場)。"""
    conn = get_conn()
    regions = conn.execute(
        "SELECT * FROM japan_regions ORDER BY display_order"
    ).fetchall()
    result = []
    for r in regions:
        resorts = conn.execute(
            "SELECT * FROM ski_resorts WHERE region_id=? AND is_active=1", (r["id"],)
        ).fetchall()
        result.append({**dict(r), "resorts": rows_to_dicts(resorts)})
    conn.close()
    return jsonify(result)


@app.route("/api/resorts", methods=["GET"])
def list_resorts():
    conn = get_conn()
    region_id = request.args.get("region_id", type=int)
    q = "SELECT * FROM ski_resorts WHERE is_active=1"
    params = []
    if region_id:
        q += " AND region_id=?"
        params.append(region_id)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/resorts/<int:resort_id>/coaches", methods=["GET"])
def list_resort_coaches_public(resort_id):
    """供客戶端選擇日本教練課指定教練時使用(不需要員工權限)。"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT s.id, s.name, s.display_code FROM resort_coaches rc
           JOIN staff s ON rc.coach_id = s.id WHERE rc.resort_id=?""",
        (resort_id,),
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/resorts/<int:resort_id>", methods=["DELETE"])
@require_role("manager")
def admin_delete_resort(resort_id):
    conn = get_conn()
    conn.execute("UPDATE ski_resorts SET is_active=0 WHERE id=?", (resort_id,))
    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'delete_resort', 'ski_resort', ?, '{"is_active": 1}', '{"is_active": 0}')""",
        (request.current_staff["id"], resort_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/resorts", methods=["GET"])
@require_role("cs")
def admin_list_resorts():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM ski_resorts ORDER BY id").fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/resorts", methods=["POST"])
@require_role("manager")
def admin_create_resort():
    d = request.json
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO ski_resorts (region_id, code, name) VALUES (?, ?, ?)",
        (d["region_id"], d["code"], d["name"]),
    )
    resort_id = cur.lastrowid
    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'create_resort', 'ski_resort', ?, '{}', ?)""",
        (request.current_staff["id"], resort_id, json.dumps({"name": d["name"], "region_id": d["region_id"]})),
    )
    conn.commit()
    conn.close()
    return jsonify({"id": resort_id}), 201


@app.route("/api/admin/resorts/<int:resort_id>", methods=["PUT"])
@require_role("manager")
def admin_update_resort(resort_id):
    d = request.json
    conn = get_conn()
    conn.execute(
        "UPDATE ski_resorts SET code=?, name=?, is_active=? WHERE id=?",
        (d.get("code"), d.get("name"), d.get("is_active", 1), resort_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/resort-coaches", methods=["GET"])
@require_role("cs")
def admin_list_resort_coaches():
    resort_id = request.args.get("resort_id", type=int)
    conn = get_conn()
    q = """SELECT rc.id, rc.resort_id, rc.coach_id, s.name AS coach_name, s.display_code
           FROM resort_coaches rc JOIN staff s ON rc.coach_id = s.id"""
    params = []
    if resort_id:
        q += " WHERE rc.resort_id=?"
        params.append(resort_id)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/resort-coaches", methods=["POST"])
@require_role("manager")
def admin_assign_resort_coach():
    d = request.json
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO resort_coaches (resort_id, coach_id) VALUES (?, ?)",
            (d["resort_id"], d["coach_id"]),
        )
        conn.commit()
        new_id = cur.lastrowid
    except Exception:
        conn.close()
        return jsonify({"error": "此教練已在該雪場名單中"}), 400
    conn.close()
    return jsonify({"id": new_id}), 201


@app.route("/api/admin/resort-coaches/<int:assignment_id>", methods=["DELETE"])
@require_role("manager")
def admin_remove_resort_coach(assignment_id):
    conn = get_conn()
    conn.execute("DELETE FROM resort_coaches WHERE id=?", (assignment_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/coach-schedule", methods=["POST"])
def admin_set_coach_schedule():
    d = request.json
    work_id = request.headers.get("X-Staff-Id")
    conn = get_conn()
    staff = conn.execute("SELECT * FROM staff WHERE work_id=?", (work_id,)).fetchone()
    if not staff:
        conn.close()
        return jsonify({"error": "未登入或工號無效"}), 401
    is_self = staff["role"] == "coach" and staff["id"] == d.get("coach_id")
    if not is_self and ROLE_RANK.get(staff["role"], 0) < ROLE_RANK["cs"]:
        conn.close()
        return jsonify({"error": "權限不足"}), 403
    conn.execute(
        """INSERT INTO coach_schedule (coach_id, work_date, status, reason)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(coach_id, work_date) DO UPDATE SET status=excluded.status, reason=excluded.reason""",
        (d["coach_id"], d["work_date"], d["status"], d.get("reason")),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True}), 201


@app.route("/api/admin/coach/my-bookings", methods=["GET"])
@require_role("coach")
def coach_my_bookings():
    from datetime import date
    today = date.today().isoformat()
    rows = booking.get_all_bookings(coach_id=request.current_staff["id"], date_from=today)
    return jsonify(rows)


@app.route("/api/admin/coach/my-schedule", methods=["GET"])
@require_role("coach")
def coach_my_schedule():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM coach_schedule WHERE coach_id=? ORDER BY work_date",
        (request.current_staff["id"],),
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/group-classes/check-auto-cancel", methods=["POST"])
@require_role("cs")
def admin_check_group_auto_cancel():
    cancelled = booking.check_and_auto_cancel_group_classes()
    return jsonify({"auto_cancelled_session_ids": cancelled})


@app.route("/api/admin/group-classes", methods=["GET"])
@require_role("cs")
def admin_list_group_classes():
    """列出未來已確認開課(滿2人以上)的團課場次,供後台指派教練用。"""
    from datetime import date
    conn = get_conn()
    rows = conn.execute(
        """SELECT s.*, st.name AS coach_name,
               (SELECT COUNT(*) FROM indoor_session_members sm
                WHERE sm.session_id = s.id AND sm.status='enrolled') AS enrolled_count
           FROM indoor_sessions s LEFT JOIN staff st ON s.coach_id = st.id
           WHERE s.category='group_class' AND s.status IN ('open','confirmed')
           AND s.booking_date >= ?
           ORDER BY s.booking_date, s.start_hour""",
        (date.today().isoformat(),),
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/group-classes/<int:session_id>/assign-coach", methods=["POST"])
@require_role("cs")
def admin_assign_group_class_coach(session_id):
    d = request.json
    conn = get_conn()
    before = conn.execute("SELECT coach_id FROM indoor_sessions WHERE id=?", (session_id,)).fetchone()
    if not before:
        conn.close()
        return jsonify({"error": "找不到這個場次"}), 404
    conn.execute("UPDATE indoor_sessions SET coach_id=? WHERE id=?", (d.get("coach_id"), session_id))
    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'assign_group_coach', 'indoor_session', ?, ?, ?)""",
        (request.current_staff["id"], session_id,
         json.dumps({"coach_id": before["coach_id"]}), json.dumps({"coach_id": d.get("coach_id")})),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/coach-schedule", methods=["GET"])
@require_role("cs")
def admin_list_coach_schedule():
    coach_id = request.args.get("coach_id", type=int)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    conn = get_conn()
    q = "SELECT cs.*, s.name AS coach_name FROM coach_schedule cs JOIN staff s ON cs.coach_id = s.id WHERE 1=1"
    params = []
    if coach_id:
        q += " AND cs.coach_id=?"; params.append(coach_id)
    if date_from:
        q += " AND cs.work_date>=?"; params.append(date_from)
    if date_to:
        q += " AND cs.work_date<=?"; params.append(date_to)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/booking/japan", methods=["POST"])
def book_japan():
    d = request.json
    try:
        result = booking.book_japan_multi_day(
            member_id=d["member_id"], bookings=d["bookings"],
            equipment_type=d.get("equipment_type"), participants=d.get("participants"),
            needs_accommodation=d.get("needs_accommodation", False),
        )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ------------------------------------------------------------------
# 付款
# ------------------------------------------------------------------
@app.route("/api/payments/create", methods=["POST"])
def create_payment():
    from payments import active_provider
    d = request.json
    result = active_provider.create_payment(
        amount=d["amount"], payment_method=d["payment_method"], order_ref=d["order_ref"]
    )
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO transactions
           (member_id, ref_type, ref_id, amount, payment_type, payment_method, payment_status, provider_ref)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (d["member_id"], d.get("ref_type"), d.get("ref_id"), d["amount"],
         d.get("payment_type", "full"), d["payment_method"], result["status"], result["provider_ref"]),
    )
    conn.commit()
    tx_id = cur.lastrowid
    conn.close()
    if result["status"] == "confirmed" and d.get("ref_type") == "charter_order":
        booking.finalize_charter_purchase(d["ref_id"])
    elif result["status"] == "confirmed" and d.get("ref_type") in ("indoor_session", "jump_booking", "japan_booking"):
        booking.mark_order_paid(d["ref_type"], d["ref_id"])
    return jsonify({"transaction_id": tx_id, **result}), 201


@app.route("/api/admin/sessions/<int:session_id>/cancel", methods=["POST"])
@require_role("cs")
def admin_cancel_session(session_id):
    """客服協調後決定直接取消此場次(取消所有報名此場次的會員,不受時間限制)。"""
    conn = get_conn()
    members = conn.execute(
        "SELECT id FROM indoor_session_members WHERE session_id=? AND status='enrolled'", (session_id,)
    ).fetchall()
    conn.close()
    for m in members:
        try:
            booking.cancel_indoor_booking(m["id"], is_staff=True)
        except ValueError:
            pass
    return jsonify({"ok": True, "cancelled_count": len(members)})


@app.route("/api/admin/sessions/needs-review", methods=["GET"])
@require_role("cs")
def admin_sessions_needs_review():
    """列出因時段衝突而標記「需人工協調」的機台場次。"""
    from datetime import date
    conn = get_conn()
    rows = conn.execute(
        """SELECT s.*, GROUP_CONCAT(m.name, '、') AS member_names
           FROM indoor_sessions s
           JOIN indoor_session_members sm ON sm.session_id = s.id AND sm.status='enrolled'
           JOIN members m ON sm.member_id = m.id
           WHERE s.status='needs_manual_review' AND s.booking_date >= ?
           GROUP BY s.id ORDER BY s.booking_date, s.start_hour""",
        (date.today().isoformat(),),
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/sessions/<int:session_id>/resolve", methods=["POST"])
@require_role("cs")
def admin_resolve_session(session_id):
    """客服協調後,標記此場次為已確認保留。"""
    conn = get_conn()
    conn.execute("UPDATE indoor_sessions SET status='confirmed' WHERE id=?", (session_id,))
    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'resolve_session_conflict', 'indoor_session', ?, '{"status":"needs_manual_review"}', '{"status":"confirmed"}')""",
        (request.current_staff["id"], session_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/payments/pending", methods=["GET"])
@require_role("cs")
def admin_pending_payments():
    """列出待客服核對入帳的付款(現場付款/匯款轉帳),供後台核准使用。"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT t.*, m.name AS member_name, m.phone AS member_phone
           FROM transactions t JOIN members m ON t.member_id = m.id
           WHERE t.payment_status='awaiting_backoffice_review'
           ORDER BY t.created_at"""
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/payments/<int:tx_id>/confirm", methods=["POST"])
@require_role("cs")
def confirm_payment(tx_id):
    conn = get_conn()
    tx = conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    conn.execute(
        "UPDATE transactions SET payment_status='confirmed', confirmed_by_staff_id=? WHERE id=?",
        (request.current_staff["id"], tx_id),
    )
    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'confirm_payment', 'transaction', ?, ?, ?)""",
        (request.current_staff["id"], tx_id,
         json.dumps({"payment_status": tx["payment_status"]}) if tx else "{}",
         json.dumps({"payment_status": "confirmed"})),
    )
    conn.commit()
    conn.close()
    if tx and tx["ref_type"] == "charter_order":
        booking.finalize_charter_purchase(tx["ref_id"])
    elif tx and tx["ref_type"] in ("indoor_session", "jump_booking", "japan_booking"):
        booking.mark_order_paid(tx["ref_type"], tx["ref_id"])
    return jsonify({"ok": True})


# ------------------------------------------------------------------
# 後台:會員管理 / A-B 方案指派
# ------------------------------------------------------------------
SENSITIVE_MEMBER_FIELDS = ["id_number", "blood_type", "address", "emergency_contact_phone"]


def _mask_sensitive_member_fields(member_dict, staff_role):
    """對照系統分析書13.1「高度敏感資料」分級:客服僅能看到遮罩後的內容,主管以上才看得到完整值。"""
    if ROLE_RANK.get(staff_role, 0) >= ROLE_RANK["manager"]:
        return member_dict
    masked = dict(member_dict)
    for field in SENSITIVE_MEMBER_FIELDS:
        val = masked.get(field)
        if val:
            masked[field] = val[:1] + "*" * max(len(val) - 2, 1) + (val[-1:] if len(val) > 1 else "")
    return masked


@app.route("/api/admin/members", methods=["GET"])
@require_role("cs")
def admin_list_members():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM members ORDER BY created_at DESC").fetchall()
    conn.close()
    members = rows_to_dicts(rows)
    members = [_mask_sensitive_member_fields(m, request.current_staff["role"]) for m in members]
    return jsonify(members)


@app.route("/api/admin/bookings", methods=["GET"])
@require_role("cs")
def admin_list_bookings():
    """訂客資料總覽:彙整所有類型的預約紀錄,可用 query string 篩選
       member_id / category / date_from / date_to"""
    result = booking.get_all_bookings(
        member_id=request.args.get("member_id", type=int),
        category=request.args.get("category"),
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
    )
    return jsonify(result)


@app.route("/api/plans/apply", methods=["POST"])
def apply_for_plan():
    d = request.json
    try:
        result = booking.apply_for_plan(
            member_id=d["member_id"], plan_name=d["plan_name"], billing_cycle=d["billing_cycle"]
        )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/members/<int:member_id>/plan-applications", methods=["GET"])
def member_plan_applications(member_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM plan_applications WHERE member_id=? ORDER BY created_at DESC", (member_id,)
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/plan-applications", methods=["GET"])
@require_role("cs")
def admin_list_plan_applications():
    conn = get_conn()
    rows = conn.execute(
        """SELECT pa.*, m.name AS member_name FROM plan_applications pa
           JOIN members m ON pa.member_id = m.id
           WHERE pa.status='pending' ORDER BY pa.created_at"""
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/plan-applications/<int:application_id>/review", methods=["POST"])
@require_role("cs")
def admin_review_plan_application(application_id):
    d = request.json
    try:
        result = booking.review_plan_application(
            application_id, request.current_staff["id"], approve=d["approve"], reason=d.get("reason")
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/admin/plan-billing/pending", methods=["GET"])
@require_role("cs")
def admin_pending_plan_billing():
    conn = get_conn()
    rows = conn.execute(
        """SELECT pbr.*, m.name AS member_name FROM plan_billing_records pbr
           JOIN members m ON pbr.member_id = m.id
           WHERE pbr.status='pending' ORDER BY pbr.created_at"""
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/plan-billing/<int:record_id>/confirm", methods=["POST"])
@require_role("cs")
def admin_confirm_plan_billing(record_id):
    conn = get_conn()
    conn.execute("UPDATE plan_billing_records SET status='paid' WHERE id=?", (record_id,))
    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'confirm_plan_billing', 'plan_billing_record', ?, '{"status":"pending"}', '{"status":"paid"}')""",
        (request.current_staff["id"], record_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/members/<int:member_id>/assign-plan", methods=["POST"])
@require_role("cs")
def assign_plan(member_id):
    d = request.json
    try:
        result = booking.subscribe_plan(
            member_id=member_id, plan_name=d["plan_name"], billing_cycle=d["billing_cycle"],
            assigned_by_staff_id=request.current_staff["id"],
        )
        conn = get_conn()
        conn.execute(
            """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
               VALUES (?, 'assign_plan', 'member', ?, '{}', ?)""",
            (request.current_staff["id"], member_id, json.dumps(result)),
        )
        conn.commit()
        conn.close()
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/admin/staff", methods=["GET"])
@require_role("manager")
def admin_list_staff():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, work_id, name, display_code, phone, birthday, role, branch FROM staff"
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/staff", methods=["POST"])
@require_role("manager")
def admin_create_staff():
    d = request.json
    password = d["birthday"].replace("-", "")[2:8]
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO staff (work_id, name, display_code, phone, birthday, password_hash, role, branch)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (d["work_id"], d["name"], d.get("display_code"), d.get("phone"), d["birthday"],
         auth.hash_password(password), d["role"], d["branch"]),
    )
    staff_id = cur.lastrowid
    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'create_staff', 'staff', ?, '{}', ?)""",
        (request.current_staff["id"], staff_id, json.dumps({"work_id": d["work_id"], "role": d["role"]})),
    )
    conn.commit()
    conn.close()
    return jsonify({"id": staff_id, "default_password": password}), 201


@app.route("/api/auth/demo-staff", methods=["GET"])
def demo_staff_list():
    # 僅供本地端示範快速登入使用,正式上線需移除此端點
    from db import DEMO_STAFF
    return jsonify([
        {"work_id": w, "name": n, "role": r, "password": bday[2:8]}
        for w, n, code, bday, r, branch in DEMO_STAFF
    ])


# ------------------------------------------------------------------
# 教練團隊
# ------------------------------------------------------------------
@app.route("/api/coaches", methods=["GET"])
def list_coaches_public():
    """公開:教練團隊介紹頁面(不含證件照)。"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT s.id, s.name, s.display_code, cp.promo_photo, cp.self_intro
           FROM staff s LEFT JOIN coach_profiles cp ON cp.coach_id = s.id
           WHERE s.role='coach'"""
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/coaches/<int:coach_id>/profile", methods=["GET"])
@require_role("cs")
def admin_get_coach_profile(coach_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM coach_profiles WHERE coach_id=?", (coach_id,)).fetchone()
    conn.close()
    return jsonify(dict(row) if row else {})


@app.route("/api/admin/coaches/<int:coach_id>/profile", methods=["PUT"])
@require_role("cs")
def admin_update_coach_profile(coach_id):
    d = request.json
    conn = get_conn()
    conn.execute(
        """INSERT INTO coach_profiles (coach_id, promo_photo, id_photo, self_intro, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(coach_id) DO UPDATE SET
             promo_photo=COALESCE(excluded.promo_photo, coach_profiles.promo_photo),
             id_photo=COALESCE(excluded.id_photo, coach_profiles.id_photo),
             self_intro=COALESCE(excluded.self_intro, coach_profiles.self_intro),
             updated_at=datetime('now')""",
        (coach_id, d.get("promo_photo"), d.get("id_photo"), d.get("self_intro")),
    )
    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'update_coach_profile', 'coach', ?, '{}', ?)""",
        (request.current_staff["id"], coach_id, json.dumps({"self_intro": d.get("self_intro")})),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ------------------------------------------------------------------
# 修改/取消預約(客戶自行操作有時間限制;員工操作不受限)
# ------------------------------------------------------------------
def _is_staff_request():
    work_id = request.headers.get("X-Staff-Id")
    if not work_id:
        return False
    conn = get_conn()
    staff = conn.execute(
        "SELECT * FROM staff WHERE work_id=?", (work_id,)
    ).fetchone()
    conn.close()
    return bool(staff) and ROLE_RANK.get(staff["role"], 0) >= ROLE_RANK["cs"]


@app.route("/api/booking/indoor/<int:member_ref_id>/cancel", methods=["POST"])
def cancel_indoor(member_ref_id):
    try:
        result = booking.cancel_indoor_booking(member_ref_id, is_staff=_is_staff_request())
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/booking/indoor/<int:member_ref_id>/reschedule", methods=["POST"])
def reschedule_indoor(member_ref_id):
    d = request.json
    try:
        result = booking.reschedule_indoor_booking(
            member_ref_id, d["new_date"], d["new_hour"], is_staff=_is_staff_request()
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/booking/jump/<int:jump_id>/cancel", methods=["POST"])
def cancel_jump(jump_id):
    try:
        result = booking.cancel_jump_booking(jump_id, is_staff=_is_staff_request())
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/booking/jump/<int:jump_id>/reschedule", methods=["POST"])
def reschedule_jump(jump_id):
    d = request.json
    try:
        result = booking.reschedule_jump_booking(
            jump_id, d["new_date"], d["new_time"], is_staff=_is_staff_request()
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/booking/japan/<group_key>/cancel", methods=["POST"])
def cancel_japan(group_key):
    try:
        result = booking.cancel_japan_trip(group_key, is_staff=_is_staff_request())
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/admin/orders", methods=["GET"])
@require_role("cs")
def admin_list_orders():
    member_id = request.args.get("member_id", type=int)
    conn = get_conn()
    q = "SELECT o.*, m.name AS member_name FROM orders o JOIN members m ON o.member_id = m.id WHERE 1=1"
    params = []
    if member_id:
        q += " AND o.member_id=?"; params.append(member_id)
    q += " ORDER BY o.created_at DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/reports/summary", methods=["GET"])
@require_role("manager")
def admin_reports_summary():
    from datetime import date, timedelta
    date_from = request.args.get("date_from") or (date.today().replace(day=1)).isoformat()
    date_to = request.args.get("date_to") or date.today().isoformat()
    result = booking.get_report_summary(date_from, date_to)
    return jsonify(result)


@app.route("/api/admin/entitlement-ledger", methods=["GET"])
@require_role("cs")
def admin_entitlement_ledger():
    member_id = request.args.get("member_id", type=int)
    conn = get_conn()
    q = "SELECT * FROM entitlement_ledger WHERE 1=1"
    params = []
    if member_id:
        q += " AND member_id=?"; params.append(member_id)
    q += " ORDER BY created_at DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/audit-log", methods=["GET"])
@require_role("manager")
def admin_audit_log():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 100").fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    import os
    if not os.path.exists(os.path.join(os.path.dirname(__file__), "erski.db")):
        init_db()
    app.run(debug=False, port=5001)
