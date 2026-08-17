from flask import Flask, request, jsonify, send_from_directory, Response, send_file
import functools
import os
import json

from db import get_conn, init_db, rows_to_dicts
import auth
import booking
import pricing
import payroll

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
app = Flask(__name__)


@app.route("/")
def serve_frontend():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/manifest.json")
def serve_manifest():
    return send_from_directory(FRONTEND_DIR, "manifest.json", mimetype="application/manifest+json")


@app.route("/sw.js")
def serve_service_worker():
    # Service Worker 必須從網站根目錄提供,且不能被瀏覽器快取太久,否則更新不會立即生效
    resp = send_from_directory(FRONTEND_DIR, "sw.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/icon-192.png")
def serve_icon_192():
    return send_from_directory(FRONTEND_DIR, "icon-192.png", mimetype="image/png")


@app.route("/icon-512.png")
def serve_icon_512():
    return send_from_directory(FRONTEND_DIR, "icon-512.png", mimetype="image/png")


@app.route("/logo-erski.png")
def serve_login_logo():
    return send_from_directory(FRONTEND_DIR, "logo-erski.png", mimetype="image/png")


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
            if not staff["is_active"]:
                return jsonify({"error": "此帳號已停用"}), 401
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
    conn = get_conn()
    conn.execute(
        """INSERT INTO notifications (member_id, channel, notify_type, content, status)
           VALUES (?, 'email', 'registration_success', ?, 'simulated')""",
        (member["id"], f"歡迎加入 ERSKI,{member['name']} 您的會員註冊已完成!"),
    )
    conn.commit()
    conn.close()
    member.pop("password_hash", None)
    return jsonify(member), 201


import random
import string


def _generate_partner_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


@app.route("/api/admin/partners", methods=["GET"])
@require_role("manager")
def admin_list_partners():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM partner_organizations ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/partners", methods=["POST"])
@require_role("manager")
def admin_create_partner():
    d = request.json
    conn = get_conn()
    code = d.get("code") or _generate_partner_code()
    try:
        cur = conn.execute(
            """INSERT INTO partner_organizations (name, contact_name, contact_phone, contact_email, code, rebate_rate)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (d["name"], d.get("contact_name"), d.get("contact_phone"), d.get("contact_email"),
             code, d.get("rebate_rate", 0)),
        )
        conn.commit()
        partner_id = cur.lastrowid
    except Exception:
        conn.close()
        return jsonify({"error": "此優惠碼已存在,請換一組"}), 400
    conn.close()
    return jsonify({"id": partner_id, "code": code}), 201


@app.route("/api/admin/partners/<int:partner_id>", methods=["PUT"])
@require_role("manager")
def admin_update_partner(partner_id):
    d = request.json
    conn = get_conn()
    conn.execute(
        "UPDATE partner_organizations SET name=?, contact_name=?, contact_phone=?, contact_email=?, rebate_rate=?, is_active=? WHERE id=?",
        (d["name"], d.get("contact_name"), d.get("contact_phone"), d.get("contact_email"),
         d.get("rebate_rate", 0), d.get("is_active", 1), partner_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/partners/<int:partner_id>/report", methods=["GET"])
@require_role("manager")
def admin_partner_report(partner_id):
    """匯出該合作單位所推薦會員的訂單資料,供計算回饋/回扣參考。"""
    conn = get_conn()
    partner = conn.execute("SELECT * FROM partner_organizations WHERE id=?", (partner_id,)).fetchone()
    if not partner:
        conn.close()
        return jsonify({"error": "找不到此合作單位"}), 404
    members = conn.execute(
        "SELECT id, name, phone, email, created_at FROM members WHERE referral_partner_id=?", (partner_id,)
    ).fetchall()
    member_ids = [m["id"] for m in members]
    total_revenue = 0
    orders_detail = []
    if member_ids:
        placeholders = ",".join("?" * len(member_ids))
        orders = conn.execute(
            f"""SELECT o.*, m.name AS member_name FROM orders o JOIN members m ON o.member_id = m.id
                WHERE o.member_id IN ({placeholders}) AND o.status='paid'""",
            member_ids,
        ).fetchall()
        orders_detail = rows_to_dicts(orders)
        total_revenue = sum(o["amount"] for o in orders)
    conn.close()
    rebate_amount = round(total_revenue * (partner["rebate_rate"] or 0))
    return jsonify({
        "partner": dict(partner),
        "referred_members": rows_to_dicts(members),
        "referred_member_count": len(members),
        "total_paid_revenue": total_revenue,
        "rebate_rate": partner["rebate_rate"],
        "rebate_amount": rebate_amount,
        "orders": orders_detail,
    })


@app.route("/api/members/<int:member_id>/referral-code", methods=["PUT"])
def set_member_referral_code(member_id):
    """會員填寫優惠碼(僅能設定一次,設定過後不可再自行更改,避免濫用回饋歸屬)。"""
    d = request.json
    conn = get_conn()
    member = conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    if not member:
        conn.close()
        return jsonify({"error": "找不到此會員"}), 404
    if member["referral_code"]:
        conn.close()
        return jsonify({"error": "已經填寫過優惠碼,無法再次更改"}), 400
    partner = conn.execute(
        "SELECT * FROM partner_organizations WHERE code=? AND is_active=1", (d["code"],)
    ).fetchone()
    if not partner:
        conn.close()
        return jsonify({"error": "優惠碼不存在或已失效"}), 400
    conn.execute(
        "UPDATE members SET referral_code=?, referral_partner_id=? WHERE id=?",
        (d["code"], partner["id"], member_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "partner_name": partner["name"]})


@app.route("/api/members/<int:member_id>/password", methods=["PUT"])
def set_member_password(member_id):
    d = request.json
    try:
        auth.set_member_password(member_id, d["new_password"], d.get("current_password"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = get_conn()
    m = conn.execute("SELECT name FROM members WHERE id=?", (member_id,)).fetchone()
    conn.execute(
        """INSERT INTO notifications (member_id, channel, notify_type, content, status)
           VALUES (?, 'email', 'password_changed', ?, 'simulated')""",
        (member_id, f"{m['name']} 您好,你的 ERSKI 帳號登入密碼已成功變更。若非本人操作請立即聯繫客服。"),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


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
    today = booking.today_tw().isoformat()
    quota = booking.get_quota_status(member_id, today)

    all_bookings = booking.get_all_bookings(member_id=member_id)
    my_bookings = [b for b in all_bookings if b["status"] != "cancelled"]
    # 保留原本 upcoming/incomplete 欄位供舊版相容(以付款狀態判斷,而非課程狀態)
    upcoming = [b for b in my_bookings if b["payment_status"] == "confirmed"]
    incomplete = [b for b in my_bookings if b["payment_status"] != "confirmed"]
    japan_payment_status = booking.get_member_japan_payment_status(member_id)

    m_dict = dict(m)
    has_password = bool(m_dict.pop("password_hash", None))

    return jsonify({
        "member": m_dict,
        "has_password": has_password,
        "member_code": compute_member_code(dict(m)),
        "profile_complete": auth.is_profile_complete(m),
        "charter_passes": rows_to_dicts(passes),
        "plan": dict(plan) if plan else None,
        "quota_status": quota,
        "my_bookings": my_bookings,
        "upcoming_bookings": upcoming,
        "incomplete_bookings": incomplete,
        "japan_payment_status": japan_payment_status,
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


@app.route("/api/members/<int:member_id>/companions", methods=["GET"])
def list_member_companions(member_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM member_companions WHERE member_id=? ORDER BY created_at DESC", (member_id,)
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/members/<int:member_id>/companions", methods=["POST"])
def create_member_companion(member_id):
    d = request.json
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO member_companions (member_id, name, gender, age, height_cm, weight_kg, shoe_size, equipment_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (member_id, d.get("name"), d.get("gender"), d.get("age"), d.get("height_cm"),
         d.get("weight_kg"), d.get("shoe_size"), d.get("equipment_type")),
    )
    conn.commit()
    companion_id = cur.lastrowid
    conn.close()
    return jsonify({"id": companion_id}), 201


@app.route("/api/members/<int:member_id>/companions/<int:companion_id>", methods=["PUT"])
def update_member_companion(member_id, companion_id):
    d = request.json
    conn = get_conn()
    conn.execute(
        """UPDATE member_companions SET name=?, gender=?, age=?, height_cm=?, weight_kg=?, shoe_size=?, equipment_type=?
           WHERE id=? AND member_id=?""",
        (d.get("name"), d.get("gender"), d.get("age"), d.get("height_cm"),
         d.get("weight_kg"), d.get("shoe_size"), d.get("equipment_type"), companion_id, member_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/members/<int:member_id>/companions/<int:companion_id>", methods=["DELETE"])
def delete_member_companion(member_id, companion_id):
    conn = get_conn()
    conn.execute("DELETE FROM member_companions WHERE id=? AND member_id=?", (companion_id, member_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


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
@app.route("/api/admin/pricing-config", methods=["GET"])
@require_role("manager")
def admin_list_pricing_config():
    return jsonify(pricing.list_all_configs())


@app.route("/api/admin/pricing-config/<config_key>", methods=["PUT"])
@require_role("manager")
def admin_update_pricing_config(config_key):
    d = request.json
    conn = get_conn()
    before = conn.execute("SELECT * FROM pricing_config WHERE config_key=?", (config_key,)).fetchone()
    if not before:
        conn.close()
        return jsonify({"error": "找不到此設定項目"}), 404
    try:
        json.loads(d["config_value"]) if isinstance(d["config_value"], str) else d["config_value"]
    except (ValueError, TypeError):
        conn.close()
        return jsonify({"error": "格式不是合法的JSON,請檢查輸入內容"}), 400
    conn.close()

    new_value = d["config_value"] if not isinstance(d["config_value"], str) else json.loads(d["config_value"])
    pricing.set_config(config_key, new_value, staff_id=request.current_staff["id"])

    conn2 = get_conn()
    conn2.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'update_pricing_config', 'pricing_config', ?, ?, ?)""",
        (request.current_staff["id"], before["id"], json.dumps({config_key: before["config_value"]}),
         json.dumps({config_key: new_value})),
    )
    conn2.commit()
    conn2.close()
    return jsonify({"ok": True})


@app.route("/api/pricing", methods=["GET"])
def get_pricing():
    return jsonify({
        "trial": pricing.get_config("trial_price"),
        "charter": pricing.get_config("charter_price"),
        "self_practice": pricing.get_config("self_practice_price"),
        "jump": pricing.get_config("jump_price"),
        "japan_full_day": pricing.get_config("japan_full_day_price"),
        "japan_half_day": pricing.get_config("japan_half_day_price"),
        "japan_designate_coach_fee": pricing.get_config("japan_coach_designate_fee"),
        "group_class_min": pricing.get_config("group_class_min"),
        "group_class_max": pricing.get_config("group_class_max"),
        "indoor_hours": {"start": pricing.get_config("indoor_start_hour"), "last_start": pricing.get_config("indoor_last_start_hour")},
        "plan_quota": pricing.get_config("plan_quota"),
        "plan_fee": pricing.get_config("plan_fee"),
        "booking_window_days": pricing.get_config("booking_window_days"),
        "japan_season_months": sorted(pricing.JAPAN_SEASON_MONTHS),
    })


# ------------------------------------------------------------------
# 室內滑雪:日曆可用性(某月/某日的機台狀況 + 跳台預約)
# ------------------------------------------------------------------
@app.route("/api/indoor/month/<year_month>", methods=["GET"])
def indoor_month_view(year_month):
    """year_month格式 YYYY-MM,回傳當月每天的機台/團課/跳台概況,供大日曆顯示狀態用。"""
    conn = get_conn()
    sessions = conn.execute(
        """SELECT booking_date, category, start_hour, duration_minutes, status FROM indoor_sessions
           WHERE booking_date LIKE ? AND status != 'cancelled'""",
        (f"{year_month}-%",),
    ).fetchall()
    jumps = conn.execute(
        "SELECT booking_date, start_time, duration_minutes FROM jump_bookings WHERE booking_date LIKE ? AND status != 'cancelled'",
        (f"{year_month}-%",),
    ).fetchall()
    by_day = {}
    for s in sessions:
        by_day.setdefault(s["booking_date"], {"indoor": 0, "jump": 0, "group_class": 0})
        if s["category"] == "group_class":
            by_day[s["booking_date"]]["group_class"] += 1
        else:
            by_day[s["booking_date"]]["indoor"] += 1
    for j in jumps:
        by_day.setdefault(j["booking_date"], {"indoor": 0, "jump": 0, "group_class": 0})
        by_day[j["booking_date"]]["jump"] += 1
    conn.close()
    return jsonify(by_day)


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
    before = conn.execute("SELECT * FROM ski_resorts WHERE id=?", (resort_id,)).fetchone()
    if not before:
        conn.close()
        return jsonify({"error": "找不到此雪場"}), 404
    conn.execute(
        "UPDATE ski_resorts SET code=?, name=?, is_active=? WHERE id=?",
        (d.get("code") or before["code"], d.get("name") or before["name"], d.get("is_active", 1), resort_id),
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
    today = booking.today_tw().isoformat()
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
        (booking.today_tw().isoformat(),),
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


@app.route("/api/admin/team-calendar", methods=["GET"])
@require_role("cs")
def admin_team_calendar():
    """
    共用班表日曆:回傳某個月份,每一天所有在職教練的狀態(上班/請假種類)與當天課程數,
    供後台畫出類似TimeTree的「一眼看到誰哪天在忙什麼」共用月曆。
    沒有明確請假紀錄的日期,預設視為正常上班。
    """
    month = request.args.get("month")  # 格式 YYYY-MM
    if not month:
        return jsonify({"error": "請提供 month 參數(YYYY-MM)"}), 400
    year, mo = map(int, month.split("-"))
    import calendar as calendar_module
    last_day = calendar_module.monthrange(year, mo)[1]
    date_from = f"{year:04d}-{mo:02d}-01"
    date_to = f"{year:04d}-{mo:02d}-{last_day:02d}"

    conn = get_conn()
    coaches = conn.execute("SELECT id, name FROM staff WHERE role='coach' AND is_active=1 ORDER BY name").fetchall()

    schedule_rows = conn.execute(
        "SELECT coach_id, work_date, status, reason FROM coach_schedule WHERE work_date >= ? AND work_date <= ?",
        (date_from, date_to),
    ).fetchall()
    schedule_map = {(r["coach_id"], r["work_date"]): {"status": r["status"], "reason": r["reason"]} for r in schedule_rows}

    session_rows = conn.execute(
        """SELECT coach_id, booking_date, COUNT(*) c FROM indoor_sessions
           WHERE status != 'cancelled' AND coach_id IS NOT NULL
             AND booking_date >= ? AND booking_date <= ?
           GROUP BY coach_id, booking_date""",
        (date_from, date_to),
    ).fetchall()
    session_map = {}
    for r in session_rows:
        session_map[(r["coach_id"], r["booking_date"])] = session_map.get((r["coach_id"], r["booking_date"]), 0) + r["c"]

    japan_rows = conn.execute(
        """SELECT coach_id, booking_date, COUNT(*) c FROM japan_bookings
           WHERE status != 'cancelled' AND coach_id IS NOT NULL
             AND booking_date >= ? AND booking_date <= ?
           GROUP BY coach_id, booking_date""",
        (date_from, date_to),
    ).fetchall()
    for r in japan_rows:
        session_map[(r["coach_id"], r["booking_date"])] = session_map.get((r["coach_id"], r["booking_date"]), 0) + r["c"]

    conn.close()

    days = {}
    for day_num in range(1, last_day + 1):
        date_str = f"{year:04d}-{mo:02d}-{day_num:02d}"
        entries = []
        for c in coaches:
            sched = schedule_map.get((c["id"], date_str))
            status = sched["status"] if sched else "working"
            reason = sched["reason"] if sched else None
            entries.append({
                "coach_id": c["id"], "coach_name": c["name"],
                "status": status, "reason": reason,
                "session_count": session_map.get((c["id"], date_str), 0),
            })
        days[date_str] = entries

    return jsonify({"month": month, "coaches": rows_to_dicts(coaches), "days": days})


@app.route("/api/booking/japan", methods=["POST"])
def book_japan():
    d = request.json
    try:
        result = booking.book_japan_multi_day(
            member_id=d["member_id"], bookings=d["bookings"],
            equipment_type=d.get("equipment_type"), participants=d.get("participants"),
            needs_accommodation=d.get("needs_accommodation", False),
            payment_plan=d.get("payment_plan", "full"),
            group_key=d.get("group_key"),
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
    try:
        cur = conn.execute(
            """INSERT INTO transactions
               (member_id, ref_type, ref_id, amount, payment_type, payment_method, payment_status, provider_ref)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (d["member_id"], d.get("ref_type"), d.get("ref_id"), d["amount"],
             d.get("payment_type", "full"), d["payment_method"], result["status"], result["provider_ref"]),
        )
        tx_id = cur.lastrowid
        if result["status"] == "confirmed" and d.get("ref_type") == "charter_order":
            booking.finalize_charter_purchase(d["ref_id"], conn=conn)
        elif result["status"] == "confirmed" and d.get("ref_type") in ("indoor_session", "jump_booking", "japan_booking"):
            booking.mark_order_paid(d["ref_type"], d["ref_id"], conn=conn, payment_method=d["payment_method"])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
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


@app.route("/api/admin/check-ins/pending", methods=["GET"])
@require_role("cs")
def admin_pending_check_ins():
    from datetime import date
    up_to_date = request.args.get("up_to_date") or booking.today_tw().isoformat()
    result = booking.get_pending_check_ins(up_to_date)
    return jsonify(result)


@app.route("/api/admin/sessions/<int:session_id>/check-in", methods=["POST"])
@require_role("cs")
def admin_check_in_indoor(session_id):
    d = request.json
    try:
        result = booking.check_in_indoor_session(
            session_id, d["attendance_status"], d.get("lesson_notes"), request.current_staff["id"]
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/admin/jump-bookings/<int:jump_id>/check-in", methods=["POST"])
@require_role("cs")
def admin_check_in_jump(jump_id):
    d = request.json
    try:
        result = booking.check_in_jump_booking(
            jump_id, d["attendance_status"], d.get("lesson_notes"), request.current_staff["id"]
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/admin/japan-bookings/<int:japan_id>/check-in", methods=["POST"])
@require_role("cs")
def admin_check_in_japan(japan_id):
    d = request.json
    try:
        result = booking.check_in_japan_booking(
            japan_id, d["attendance_status"], d.get("lesson_notes"), request.current_staff["id"]
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


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
        (booking.today_tw().isoformat(),),
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
    try:
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
        if tx and tx["ref_type"] == "charter_order":
            booking.finalize_charter_purchase(tx["ref_id"], conn=conn)
        elif tx and tx["ref_type"] in ("indoor_session", "jump_booking", "japan_booking"):
            booking.mark_order_paid(tx["ref_type"], tx["ref_id"], conn=conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
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
    conn = get_conn()
    try:
        result = booking.subscribe_plan(
            member_id=member_id, plan_name=d["plan_name"], billing_cycle=d["billing_cycle"],
            assigned_by_staff_id=request.current_staff["id"], conn=conn,
        )
        conn.execute(
            """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
               VALUES (?, 'assign_plan', 'member', ?, '{}', ?)""",
            (request.current_staff["id"], member_id, json.dumps(result)),
        )
        conn.commit()
        return jsonify(result), 201
    except ValueError as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@app.route("/api/admin/staff", methods=["GET"])
@require_role("manager")
def admin_list_staff():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, work_id, name, display_code, phone, birthday, role, branch, is_active FROM staff WHERE is_active=1"
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/staff/<int:staff_id>", methods=["DELETE"])
@require_role("manager")
def admin_delete_staff(staff_id):
    """停用教練/員工帳號(軟刪除:保留歷史預約/稽核紀錄的關聯,僅從清單中隱藏、無法再登入)。"""
    conn = get_conn()
    before = conn.execute("SELECT * FROM staff WHERE id=?", (staff_id,)).fetchone()
    if not before:
        conn.close()
        return jsonify({"error": "找不到此員工"}), 404
    conn.execute("UPDATE staff SET is_active=0 WHERE id=?", (staff_id,))
    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'delete_staff', 'staff', ?, ?, ?)""",
        (request.current_staff["id"], staff_id,
         json.dumps({"is_active": 1}), json.dumps({"is_active": 0, "name": before["name"]})),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


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
        {"work_id": w, "name": n, "role": r, "password": bday.replace("-", "")[2:8]}
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
        """SELECT s.id, s.name, s.display_code, cp.promo_photo, cp.self_intro, cp.resume, cp.experience, cp.rank
           FROM staff s LEFT JOIN coach_profiles cp ON cp.coach_id = s.id
           WHERE s.role='coach' AND s.is_active=1"""
    ).fetchall()
    result = []
    for r in rows:
        certs = conn.execute(
            "SELECT cert_type, cert_name, cert_level FROM coach_certifications WHERE coach_id=?", (r["id"],)
        ).fetchall()
        caps = conn.execute(
            """SELECT co.name FROM coach_capabilities cc
               JOIN coach_capability_options co ON cc.capability_option_id = co.id
               WHERE cc.coach_id=?""",
            (r["id"],),
        ).fetchall()
        d = dict(r)
        d["certifications"] = rows_to_dicts(certs)
        d["capabilities"] = [c["name"] for c in caps]
        result.append(d)
    conn.close()
    return jsonify(result)


@app.route("/api/admin/coaches/<int:coach_id>/basic-info", methods=["GET"])
@require_role("coach")
def admin_get_coach_basic_info(coach_id):
    is_self = request.current_staff["role"] == "coach" and request.current_staff["id"] == coach_id
    if not is_self and ROLE_RANK.get(request.current_staff["role"], 0) < ROLE_RANK["manager"]:
        return jsonify({"error": "權限不足"}), 403
    conn = get_conn()
    row = conn.execute(
        "SELECT id, work_id, name, display_code, phone, birthday, id_number, address, branch FROM staff WHERE id=?", (coach_id,)
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "找不到此教練"}), 404
    return jsonify(dict(row))


@app.route("/api/admin/coaches/<int:coach_id>/basic-info", methods=["PUT"])
@require_role("coach")
def admin_update_coach_basic_info(coach_id):
    """教練可以編輯自己的姓名/身分證字號/生日/地址/電話/分店;工號由主管以上異動,避免教練自己誤改登入帳號。"""
    is_self = request.current_staff["role"] == "coach" and request.current_staff["id"] == coach_id
    is_manager_up = ROLE_RANK.get(request.current_staff["role"], 0) >= ROLE_RANK["manager"]
    if not is_self and not is_manager_up:
        return jsonify({"error": "權限不足"}), 403
    d = request.json
    conn = get_conn()
    before = conn.execute("SELECT * FROM staff WHERE id=?", (coach_id,)).fetchone()
    if not before:
        conn.close()
        return jsonify({"error": "找不到此教練"}), 404
    display_code = d.get("display_code") or before["display_code"]
    if not is_manager_up:
        display_code = before["display_code"]  # 顯示代號仍限主管以上異動
    conn.execute(
        "UPDATE staff SET name=?, display_code=?, phone=?, birthday=?, id_number=?, address=?, branch=? WHERE id=?",
        (d.get("name") or before["name"], display_code,
         d.get("phone") or before["phone"], d.get("birthday") or before["birthday"],
         d.get("id_number") or before["id_number"], d.get("address") or before["address"],
         d.get("branch") or before["branch"], coach_id),
    )
    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'update_coach_basic_info', 'staff', ?, ?, ?)""",
        (request.current_staff["id"], coach_id,
         json.dumps({"name": before["name"], "display_code": before["display_code"],
                     "phone": before["phone"], "branch": before["branch"]}),
         json.dumps(d)),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/location-options", methods=["GET"])
@require_role("coach")
def admin_list_location_options():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM coach_location_options ORDER BY id").fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/location-options", methods=["POST"])
@require_role("manager")
def admin_create_location_option():
    d = request.json
    conn = get_conn()
    try:
        cur = conn.execute("INSERT INTO coach_location_options (name) VALUES (?)", (d["name"],))
        conn.commit()
        loc_id = cur.lastrowid
    except Exception:
        conn.close()
        return jsonify({"error": "此駐在地名稱已存在"}), 400
    conn.close()
    return jsonify({"id": loc_id}), 201


@app.route("/api/admin/capability-options", methods=["GET"])
@require_role("coach")
def admin_list_capability_options():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM coach_capability_options ORDER BY id").fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/capability-options", methods=["POST"])
@require_role("manager")
def admin_create_capability_option():
    d = request.json
    conn = get_conn()
    try:
        cur = conn.execute("INSERT INTO coach_capability_options (name) VALUES (?)", (d["name"],))
        conn.commit()
        cap_id = cur.lastrowid
    except Exception:
        conn.close()
        return jsonify({"error": "此能力名稱已存在"}), 400
    conn.close()
    return jsonify({"id": cap_id}), 201


@app.route("/api/admin/coaches/<int:coach_id>/details", methods=["GET"])
@require_role("coach")
def admin_get_coach_details(coach_id):
    is_self = request.current_staff["role"] == "coach" and request.current_staff["id"] == coach_id
    if not is_self and ROLE_RANK.get(request.current_staff["role"], 0) < ROLE_RANK["manager"]:
        return jsonify({"error": "權限不足"}), 403
    conn = get_conn()
    profile = conn.execute("SELECT * FROM coach_profiles WHERE coach_id=?", (coach_id,)).fetchone()
    capabilities = conn.execute(
        "SELECT capability_option_id FROM coach_capabilities WHERE coach_id=?", (coach_id,)
    ).fetchall()
    certifications = conn.execute(
        "SELECT id, cert_type, cert_name, cert_level FROM coach_certifications WHERE coach_id=?", (coach_id,)
    ).fetchall()
    locations = conn.execute(
        "SELECT location_option_id FROM coach_locations WHERE coach_id=?", (coach_id,)
    ).fetchall()
    conn.close()
    is_manager_up = ROLE_RANK.get(request.current_staff["role"], 0) >= ROLE_RANK["manager"]
    result = {
        "contract_type": profile["contract_type"] if profile else None,
        "rank": profile["rank"] if profile else None,
        "hourly_rate": profile["hourly_rate"] if profile else None,
        "resume": profile["resume"] if profile else None,
        "experience": profile["experience"] if profile else None,
        "self_intro": profile["self_intro"] if profile else None,
        "years_of_service": profile["years_of_service"] if profile else None,
        "contract_year": profile["contract_year"] if profile else None,
        "capability_option_ids": [r["capability_option_id"] for r in capabilities],
        "certifications": rows_to_dicts(certifications),
        "location_option_ids": [r["location_option_id"] for r in locations],
    }
    if is_manager_up:
        # 薪資相關資料屬於人事機密,教練自己登入時看不到(即使是查詢自己的details)
        result["base_salary"] = profile["base_salary"] if profile else None
        result["rate_group_class"] = profile["rate_group_class"] if profile else None
        result["rate_trial"] = profile["rate_trial"] if profile else None
        result["rate_assistant"] = profile["rate_assistant"] if profile else None
        result["japan_commission_rate"] = profile["japan_commission_rate"] if profile else None
    return jsonify(result)


@app.route("/api/admin/coaches/<int:coach_id>/details", methods=["PUT"])
@require_role("coach")
def admin_update_coach_details(coach_id):
    """
    一次性覆蓋教練的職稱/能力/證照/駐在地/合約類型/年資/合約年(前端管理整組清單後送出取代)。
    教練自己登入時,能編輯「職稱」「教練能力」「證照」(對外顯示於教練團隊頁面的資料);
    「駐在地(教練分配)」「合約類型」「時薪」「年資」「合約年」屬於人事/派工決策,僅主管以上能異動,
    教練自己送出這幾項會被忽略、維持原值不變。
    """
    is_self = request.current_staff["role"] == "coach" and request.current_staff["id"] == coach_id
    is_manager_up = ROLE_RANK.get(request.current_staff["role"], 0) >= ROLE_RANK["manager"]
    if not is_self and not is_manager_up:
        return jsonify({"error": "權限不足"}), 403
    d = request.json
    conn = get_conn()
    before_profile = conn.execute("SELECT * FROM coach_profiles WHERE coach_id=?", (coach_id,)).fetchone()

    rank = d.get("rank") if "rank" in d else (before_profile["rank"] if before_profile else None)
    if is_manager_up:
        contract_type = d.get("contract_type")
        hourly_rate = d.get("hourly_rate")
        years_of_service = d.get("years_of_service")
        contract_year = d.get("contract_year")
    else:
        contract_type = before_profile["contract_type"] if before_profile else None
        hourly_rate = before_profile["hourly_rate"] if before_profile else None
        years_of_service = before_profile["years_of_service"] if before_profile else None
        contract_year = before_profile["contract_year"] if before_profile else None

    if is_manager_up:
        base_salary = d.get("base_salary")
        rate_group_class = d.get("rate_group_class")
        rate_trial = d.get("rate_trial")
        rate_assistant = d.get("rate_assistant")
        japan_commission_rate = d.get("japan_commission_rate")
    else:
        base_salary = before_profile["base_salary"] if before_profile else None
        rate_group_class = before_profile["rate_group_class"] if before_profile else None
        rate_trial = before_profile["rate_trial"] if before_profile else None
        rate_assistant = before_profile["rate_assistant"] if before_profile else None
        japan_commission_rate = before_profile["japan_commission_rate"] if before_profile else None

    conn.execute(
        """INSERT INTO coach_profiles
           (coach_id, contract_type, rank, hourly_rate, years_of_service, contract_year,
            base_salary, rate_group_class, rate_trial, rate_assistant, japan_commission_rate, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(coach_id) DO UPDATE SET
             contract_type=excluded.contract_type, rank=excluded.rank, hourly_rate=excluded.hourly_rate,
             years_of_service=excluded.years_of_service, contract_year=excluded.contract_year,
             base_salary=excluded.base_salary, rate_group_class=excluded.rate_group_class,
             rate_trial=excluded.rate_trial, rate_assistant=excluded.rate_assistant,
             japan_commission_rate=excluded.japan_commission_rate, updated_at=datetime('now')""",
        (coach_id, contract_type, rank, hourly_rate, years_of_service, contract_year,
         base_salary, rate_group_class, rate_trial, rate_assistant, japan_commission_rate),
    )

    if is_manager_up:
        conn.execute("DELETE FROM coach_locations WHERE coach_id=?", (coach_id,))
        for loc_id in d.get("location_option_ids", []):
            conn.execute(
                "INSERT OR IGNORE INTO coach_locations (coach_id, location_option_id) VALUES (?, ?)",
                (coach_id, loc_id),
            )

    conn.execute("DELETE FROM coach_capabilities WHERE coach_id=?", (coach_id,))
    for cap_id in d.get("capability_option_ids", []):
        conn.execute(
            "INSERT OR IGNORE INTO coach_capabilities (coach_id, capability_option_id) VALUES (?, ?)",
            (coach_id, cap_id),
        )

    conn.execute("DELETE FROM coach_certifications WHERE coach_id=?", (coach_id,))
    for cert in d.get("certifications", []):
        if cert.get("cert_type") and cert.get("cert_level"):
            conn.execute(
                "INSERT INTO coach_certifications (coach_id, cert_type, cert_name, cert_level) VALUES (?, ?, ?, ?)",
                (coach_id, cert["cert_type"], cert.get("cert_name"), cert["cert_level"]),
            )

    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'update_coach_details', 'coach', ?, '{}', ?)""",
        (request.current_staff["id"], coach_id, json.dumps(d)),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/coaches/<int:coach_id>/profile", methods=["GET"])
@require_role("coach")
def admin_get_coach_profile(coach_id):
    is_self = request.current_staff["role"] == "coach" and request.current_staff["id"] == coach_id
    if not is_self and ROLE_RANK.get(request.current_staff["role"], 0) < ROLE_RANK["cs"]:
        return jsonify({"error": "權限不足"}), 403
    conn = get_conn()
    row = conn.execute("SELECT * FROM coach_profiles WHERE coach_id=?", (coach_id,)).fetchone()
    conn.close()
    return jsonify(dict(row) if row else {})


@app.route("/api/admin/coaches/<int:coach_id>/profile", methods=["PUT"])
@require_role("coach")
def admin_update_coach_profile(coach_id):
    is_self = request.current_staff["role"] == "coach" and request.current_staff["id"] == coach_id
    if not is_self and ROLE_RANK.get(request.current_staff["role"], 0) < ROLE_RANK["cs"]:
        return jsonify({"error": "權限不足"}), 403
    d = request.json
    conn = get_conn()
    conn.execute(
        """INSERT INTO coach_profiles (coach_id, promo_photo, id_photo, self_intro, resume, experience, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(coach_id) DO UPDATE SET
             promo_photo=COALESCE(excluded.promo_photo, coach_profiles.promo_photo),
             id_photo=COALESCE(excluded.id_photo, coach_profiles.id_photo),
             self_intro=COALESCE(excluded.self_intro, coach_profiles.self_intro),
             resume=COALESCE(excluded.resume, coach_profiles.resume),
             experience=COALESCE(excluded.experience, coach_profiles.experience),
             updated_at=datetime('now')""",
        (coach_id, d.get("promo_photo"), d.get("id_photo"), d.get("self_intro"), d.get("resume"), d.get("experience")),
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


@app.route("/api/admin/orders/<int:order_id>/discount", methods=["PUT"])
@require_role("manager")
def admin_set_order_discount(order_id):
    d = request.json
    conn = get_conn()
    before = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not before:
        conn.close()
        return jsonify({"error": "找不到此訂單"}), 404
    discount_amount = int(d.get("discount_amount", 0))
    if discount_amount < 0 or discount_amount > before["amount"]:
        conn.close()
        return jsonify({"error": "折扣金額不合理"}), 400
    conn.execute("UPDATE orders SET discount_amount=? WHERE id=?", (discount_amount, order_id))
    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'set_order_discount', 'order', ?, ?, ?)""",
        (request.current_staff["id"], order_id,
         json.dumps({"discount_amount": before["discount_amount"]}), json.dumps({"discount_amount": discount_amount})),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/orders/<int:order_id>/record-payment", methods=["POST"])
@require_role("cs")
def admin_record_order_payment(order_id):
    """客服/主管在後台記錄一筆實際收到的款項(可支援訂金/尾款分次收款)。"""
    d = request.json
    conn = get_conn()
    try:
        order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            return jsonify({"error": "找不到此訂單"}), 404
        amount = int(d["amount"])
        payment_type = d.get("payment_type", "full")
        payable = order["amount"] - order["discount_amount"]
        new_paid = order["paid_amount"] + amount
        if new_paid > payable:
            return jsonify({"error": f"收款金額超過應付金額(應付NT${payable},已收NT${order['paid_amount']})"}), 400

        conn.execute(
            """INSERT INTO transactions (member_id, order_id, ref_type, ref_id, amount, payment_type, payment_method, payment_status, confirmed_by_staff_id, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?)""",
            (order["member_id"], order_id, order["ref_type"], order["ref_id"], amount,
             payment_type, d.get("payment_method", "onsite"), request.current_staff["id"], d.get("note")),
        )
        new_status = "paid" if new_paid >= payable else order["status"]
        conn.execute("UPDATE orders SET paid_amount=?, status=? WHERE id=?", (new_paid, new_status, order_id))
        conn.execute(
            """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
               VALUES (?, 'record_order_payment', 'order', ?, ?, ?)""",
            (request.current_staff["id"], order_id,
             json.dumps({"paid_amount": order["paid_amount"]}), json.dumps({"paid_amount": new_paid, "amount": amount})),
        )

        # 若這筆收款讓訂單正式完成付款,依原本邏輯觸發權益產生(與此筆收款合併在同一筆交易內,避免分段寫入不一致)
        if new_status == "paid" and order["status"] != "paid":
            if order["ref_type"] == "charter_pass":
                booking.finalize_charter_purchase(order_id, conn=conn)
            elif order["ref_type"] in ("indoor_session", "jump_booking", "japan_booking"):
                booking.mark_order_paid(order["ref_type"], order["ref_id"], conn=conn)

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return jsonify({"ok": True, "new_status": new_status, "paid_amount": new_paid})


@app.route("/api/admin/orders/<int:order_id>/refund", methods=["POST"])
@require_role("manager")
def admin_refund_order(order_id):
    d = request.json
    conn = get_conn()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        conn.close()
        return jsonify({"error": "找不到此訂單"}), 404
    amount = int(d["amount"])
    max_refundable = order["paid_amount"] - order["refunded_amount"]
    if amount <= 0 or amount > max_refundable:
        conn.close()
        return jsonify({"error": f"退款金額不合理(最多可退NT${max_refundable})"}), 400

    conn.execute(
        """INSERT INTO transactions (member_id, order_id, ref_type, ref_id, amount, payment_type, payment_method, payment_status, confirmed_by_staff_id, note)
           VALUES (?, ?, ?, ?, ?, 'refund', 'manual_grant', 'refunded', ?, ?)""",
        (order["member_id"], order_id, order["ref_type"], order["ref_id"], amount,
         request.current_staff["id"], d.get("reason")),
    )
    new_refunded = order["refunded_amount"] + amount
    new_status = "refunded" if new_refunded >= order["paid_amount"] else order["status"]
    conn.execute("UPDATE orders SET refunded_amount=?, status=? WHERE id=?", (new_refunded, new_status, order_id))
    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'refund_order', 'order', ?, ?, ?)""",
        (request.current_staff["id"], order_id,
         json.dumps({"refunded_amount": order["refunded_amount"]}),
         json.dumps({"refunded_amount": new_refunded, "reason": d.get("reason")})),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "new_status": new_status, "refunded_amount": new_refunded})


import csv
import io


def _parse_csv(csv_text):
    f = io.StringIO(csv_text)
    return list(csv.DictReader(f))


@app.route("/api/admin/import/members", methods=["POST"])
@require_role("manager")
def admin_import_members():
    """
    匯入既有會員資料。CSV欄位:name,phone,email,birth_date,gender,address,emergency_contact_name,emergency_contact_phone
    僅 name 為必填,其餘欄位可留空。以 phone 或 email 判斷是否已存在(存在則略過,不覆蓋)。
    """
    d = request.json
    try:
        rows = _parse_csv(d["csv_text"])
    except Exception as e:
        return jsonify({"error": f"CSV格式解析失敗:{e}"}), 400

    conn = get_conn()
    created, skipped, failed = [], [], []
    for i, row in enumerate(rows, start=2):  # row 2 = 第一筆資料(第1行是標題)
        name = (row.get("name") or "").strip()
        if not name:
            failed.append({"row": i, "reason": "缺少姓名"})
            continue
        phone = (row.get("phone") or "").strip() or None
        email = (row.get("email") or "").strip() or None
        existing = None
        if phone:
            existing = conn.execute("SELECT id FROM members WHERE phone=?", (phone,)).fetchone()
        if not existing and email:
            existing = conn.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone()
        if existing:
            skipped.append({"row": i, "reason": f"已存在會員(id={existing['id']}),略過"})
            continue
        try:
            cur = conn.execute(
                """INSERT INTO members
                   (name, phone, email, birth_date, gender, address,
                    emergency_contact_name, emergency_contact_phone, auth_provider)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'email')""",
                (name, phone, email, (row.get("birth_date") or "").strip() or None,
                 (row.get("gender") or "").strip() or None, (row.get("address") or "").strip() or None,
                 (row.get("emergency_contact_name") or "").strip() or None,
                 (row.get("emergency_contact_phone") or "").strip() or None),
            )
            created.append({"row": i, "member_id": cur.lastrowid, "name": name})
        except Exception as e:
            failed.append({"row": i, "reason": str(e)})
    conn.commit()
    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'import_members', 'members', 0, '{}', ?)""",
        (request.current_staff["id"], json.dumps({"created": len(created), "skipped": len(skipped), "failed": len(failed)})),
    )
    conn.commit()
    conn.close()
    return jsonify({"created": created, "skipped": skipped, "failed": failed})


@app.route("/api/admin/import/coaches", methods=["POST"])
@require_role("manager")
def admin_import_coaches():
    """
    匯入既有教練資料。CSV欄位:name,work_id,birthday,phone,branch
    name/work_id/birthday為必填。預設密碼為生日六碼。以work_id判斷是否已存在(存在則略過)。
    """
    d = request.json
    try:
        rows = _parse_csv(d["csv_text"])
    except Exception as e:
        return jsonify({"error": f"CSV格式解析失敗:{e}"}), 400

    conn = get_conn()
    created, skipped, failed = [], [], []
    for i, row in enumerate(rows, start=2):
        name = (row.get("name") or "").strip()
        work_id = (row.get("work_id") or "").strip()
        birthday = (row.get("birthday") or "").strip()
        if not name or not work_id or not birthday:
            failed.append({"row": i, "reason": "姓名/工號/生日為必填"})
            continue
        existing = conn.execute("SELECT id FROM staff WHERE work_id=?", (work_id,)).fetchone()
        if existing:
            skipped.append({"row": i, "reason": f"工號已存在(id={existing['id']}),略過"})
            continue
        try:
            password = birthday.replace("-", "")[2:8]
            cur = conn.execute(
                """INSERT INTO staff (work_id, name, phone, birthday, password_hash, role, branch)
                   VALUES (?, ?, ?, ?, ?, 'coach', ?)""",
                (work_id, name, (row.get("phone") or "").strip() or None, birthday,
                 auth.hash_password(password), (row.get("branch") or "").strip() or "高雄"),
            )
            created.append({"row": i, "staff_id": cur.lastrowid, "name": name, "default_password": password})
        except Exception as e:
            failed.append({"row": i, "reason": str(e)})
    conn.commit()
    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'import_coaches', 'staff', 0, '{}', ?)""",
        (request.current_staff["id"], json.dumps({"created": len(created), "skipped": len(skipped), "failed": len(failed)})),
    )
    conn.commit()
    conn.close()
    return jsonify({"created": created, "skipped": skipped, "failed": failed})


@app.route("/api/admin/import/charter-passes", methods=["POST"])
@require_role("manager")
def admin_import_charter_passes():
    """
    匯入既有包機堂數包(讓客戶在舊系統已購買但尚未用完的堂數可以延續)。
    CSV欄位:member_phone_or_email,package_size,headcount_type,remaining
    以電話或Email比對既有會員,找不到會員的那一列會失敗,需先匯入會員。
    """
    d = request.json
    try:
        rows = _parse_csv(d["csv_text"])
    except Exception as e:
        return jsonify({"error": f"CSV格式解析失敗:{e}"}), 400

    conn = get_conn()
    created, failed = [], []
    for i, row in enumerate(rows, start=2):
        key = (row.get("member_phone_or_email") or "").strip()
        if not key:
            failed.append({"row": i, "reason": "缺少會員電話或Email"})
            continue
        member = conn.execute("SELECT id FROM members WHERE phone=? OR email=?", (key, key)).fetchone()
        if not member:
            failed.append({"row": i, "reason": f"找不到對應會員({key}),請先匯入會員資料"})
            continue
        try:
            package_size = int(row["package_size"])
            headcount_type = int(row["headcount_type"])
            remaining = int(row["remaining"])
        except (KeyError, ValueError):
            failed.append({"row": i, "reason": "package_size/headcount_type/remaining 格式錯誤"})
            continue
        cur = conn.execute(
            """INSERT INTO charter_passes (member_id, package_size, headcount_type, remaining)
               VALUES (?, ?, ?, ?)""",
            (member["id"], package_size, headcount_type, remaining),
        )
        conn.execute(
            """INSERT INTO entitlement_ledger
               (member_id, entitlement_type, entitlement_ref_id, change_type, amount, note)
               VALUES (?, 'charter_pass', ?, 'manual_adjust', ?, '資料匯入:延續舊系統堂數')""",
            (member["id"], cur.lastrowid, remaining),
        )
        created.append({"row": i, "member_id": member["id"], "pass_id": cur.lastrowid, "remaining": remaining})
    conn.commit()
    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'import_charter_passes', 'charter_passes', 0, '{}', ?)""",
        (request.current_staff["id"], json.dumps({"created": len(created), "failed": len(failed)})),
    )
    conn.commit()
    conn.close()
    return jsonify({"created": created, "failed": failed})


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
    date_from = request.args.get("date_from") or (booking.today_tw().replace(day=1)).isoformat()
    date_to = request.args.get("date_to") or booking.today_tw().isoformat()
    result = booking.get_report_summary(date_from, date_to)
    return jsonify(result)


@app.route("/api/admin/insurance-brackets", methods=["GET"])
@require_role("manager")
def admin_list_insurance_brackets():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM insurance_brackets ORDER BY bracket_min").fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/insurance-brackets", methods=["PUT"])
@require_role("manager")
def admin_update_insurance_brackets():
    """整批覆蓋勞健保級距表(前端管理整份清單後送出取代),供對照勞保局/健保署最新公告更新用。"""
    d = request.json
    conn = get_conn()
    conn.execute("DELETE FROM insurance_brackets")
    for b in d.get("brackets", []):
        conn.execute(
            """INSERT INTO insurance_brackets
               (bracket_min, bracket_max, insured_salary, labor_insurance_employee, health_insurance_employee)
               VALUES (?, ?, ?, ?, ?)""",
            (b["bracket_min"], b["bracket_max"], b["insured_salary"],
             b["labor_insurance_employee"], b["health_insurance_employee"]),
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/payroll", methods=["GET"])
@require_role("manager")
def admin_list_payroll():
    """查詢某個月份所有教練的薪資紀錄清單(尚未產生過的教練不會出現在清單裡,需先產生)。"""
    period = request.args.get("period")
    if not period:
        return jsonify({"error": "請提供 period 參數(YYYY-MM)"}), 400
    conn = get_conn()
    rows = conn.execute(
        """SELECT pr.*, st.name AS coach_name, cp.rank AS coach_rank FROM coach_payroll_records pr
           JOIN staff st ON pr.coach_id = st.id
           LEFT JOIN coach_profiles cp ON cp.coach_id = st.id
           WHERE pr.period=? ORDER BY st.name""",
        (period,),
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/payroll/generate", methods=["POST"])
@require_role("manager")
def admin_generate_payroll():
    """為某位教練(或全部教練)產生/重新計算某個月份的薪資紀錄。"""
    d = request.json
    period = d.get("period")
    if not period:
        return jsonify({"error": "請提供 period(YYYY-MM)"}), 400
    coach_id = d.get("coach_id")
    conn = get_conn()
    if coach_id:
        coach_ids = [coach_id]
    else:
        coach_ids = [r["id"] for r in conn.execute("SELECT id FROM staff WHERE role='coach' AND is_active=1").fetchall()]
    conn.close()
    results = [payroll.generate_coach_payroll(cid, period, staff_id=request.current_staff["id"]) for cid in coach_ids]
    return jsonify(results)


@app.route("/api/admin/payroll/<int:record_id>", methods=["PUT"])
@require_role("manager")
def admin_update_payroll_record(record_id):
    """人工更新加班獎金/其他補貼/勞健保覆蓋值/備註,自動重新計算實際所得。"""
    d = request.json
    try:
        result = payroll.update_payroll_manual_fields(
            record_id,
            overtime_bonus=d.get("overtime_bonus"),
            other_subsidy=d.get("other_subsidy"),
            other_subsidy_note=d.get("other_subsidy_note"),
            labor_insurance=d.get("labor_insurance"),
            health_insurance=d.get("health_insurance"),
            notes=d.get("notes"),
            japan_travel_subsidy=d.get("japan_travel_subsidy"),
            japan_transportation_subsidy=d.get("japan_transportation_subsidy"),
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/admin/japan-bookings", methods=["GET"])
@require_role("cs")
def admin_list_japan_bookings():
    """日本教練課訂單總覽,可用 date_from/date_to 篩選,供尾款收款/退佣/轉介管理使用。"""
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    conn = get_conn()
    q = """SELECT jb.*, m.name AS member_name, r.name AS resort_name, st.name AS coach_name,
                  p.name AS rebate_partner_name
           FROM japan_bookings jb
           JOIN members m ON jb.member_id = m.id
           LEFT JOIN ski_resorts r ON jb.resort_id = r.id
           LEFT JOIN staff st ON jb.coach_id = st.id
           LEFT JOIN partner_organizations p ON jb.rebate_partner_id = p.id
           WHERE jb.status != 'cancelled'"""
    params = []
    if date_from:
        q += " AND jb.booking_date >= ?"; params.append(date_from)
    if date_to:
        q += " AND jb.booking_date <= ?"; params.append(date_to)
    q += " ORDER BY jb.booking_date"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/japan-bookings/<int:booking_id>/collect-balance", methods=["POST"])
@require_role("cs")
def admin_collect_japan_balance(booking_id):
    """後台收取日本教練課尾款(適用於選擇「先繳訂金」的訂單)。"""
    d = request.json
    conn = get_conn()
    jb = conn.execute("SELECT * FROM japan_bookings WHERE id=?", (booking_id,)).fetchone()
    if not jb:
        conn.close()
        return jsonify({"error": "找不到此筆日本教練課訂單"}), 404
    if jb["payment_plan"] != "deposit":
        conn.close()
        return jsonify({"error": "此訂單為全額付款,無需另外收尾款"}), 400
    if not jb["deposit_paid"]:
        conn.close()
        return jsonify({"error": "訂金尚未確認繳納,請先確認訂金"}), 400
    conn.execute(
        """UPDATE japan_bookings SET balance_paid=1, balance_paid_date=?, balance_payment_method=?,
           balance_collected_by_staff_id=? WHERE id=?""",
        (d.get("balance_paid_date") or booking.today_tw().isoformat(), d.get("balance_payment_method"),
         request.current_staff["id"], booking_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/japan-bookings/<int:booking_id>/rebate", methods=["PUT"])
@require_role("manager")
def admin_set_japan_rebate(booking_id):
    """設定退佣(對應合作單位),退介紹費由主管以上手動填寫;會自動重新計算教練收入
    (公式:教練收入 = (報價-退佣金額) x 教練提成比例)。"""
    d = request.json
    conn = get_conn()
    jb = conn.execute("SELECT * FROM japan_bookings WHERE id=?", (booking_id,)).fetchone()
    if not jb:
        conn.close()
        return jsonify({"error": "找不到此筆日本教練課訂單"}), 404
    rebate_partner_id = d.get("rebate_partner_id")
    rebate_amount = d.get("rebate_amount", 0)
    rebate_date = d.get("rebate_date")
    coach_income = jb["coach_income"]
    if jb["coach_commission_rate"] is not None:
        coach_income = round((jb["price"] - rebate_amount) * jb["coach_commission_rate"])
    conn.execute(
        """UPDATE japan_bookings SET rebate_partner_id=?, rebate_amount=?, rebate_date=?, coach_income=?
           WHERE id=?""",
        (rebate_partner_id, rebate_amount, rebate_date, coach_income, booking_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "coach_income": coach_income})


@app.route("/api/admin/japan-bookings/<int:booking_id>/referral", methods=["PUT"])
@require_role("boss")
def admin_set_japan_referral(booking_id):
    """設定轉介單/轉介費用/轉介對象,僅限老闆填寫。"""
    d = request.json
    conn = get_conn()
    jb = conn.execute("SELECT * FROM japan_bookings WHERE id=?", (booking_id,)).fetchone()
    if not jb:
        conn.close()
        return jsonify({"error": "找不到此筆日本教練課訂單"}), 404
    conn.execute(
        "UPDATE japan_bookings SET referral_form=?, referral_fee=?, referral_target=? WHERE id=?",
        (d.get("referral_form"), d.get("referral_fee", 0), d.get("referral_target"), booking_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/partners/<int:partner_id>/japan-bookings", methods=["GET"])
@require_role("manager")
def admin_partner_japan_bookings(partner_id):
    """合作單位底下的日本教練課退佣紀錄:自動帶出訂課人/課程項目/課程人數/課費,退介紹費為手動填寫值。"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT jb.id, jb.booking_date, m.name AS member_name, jb.equipment_type,
                  jb.headcount, jb.price, jb.rebate_amount, jb.rebate_date
           FROM japan_bookings jb JOIN members m ON jb.member_id = m.id
           WHERE jb.rebate_partner_id=? ORDER BY jb.booking_date DESC""",
        (partner_id,),
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/japan-bookings/<int:booking_id>", methods=["GET"])
@require_role("cs")
def admin_get_japan_booking(booking_id):
    conn = get_conn()
    jb = conn.execute(
        """SELECT jb.*, m.name AS member_name, r.name AS resort_name, st.name AS coach_name,
                  p.name AS rebate_partner_name
           FROM japan_bookings jb
           JOIN members m ON jb.member_id = m.id
           LEFT JOIN ski_resorts r ON jb.resort_id = r.id
           LEFT JOIN staff st ON jb.coach_id = st.id
           LEFT JOIN partner_organizations p ON jb.rebate_partner_id = p.id
           WHERE jb.id=?""",
        (booking_id,),
    ).fetchone()
    conn.close()
    if not jb:
        return jsonify({"error": "找不到此筆日本教練課訂單"}), 404
    return jsonify(dict(jb))


@app.route("/api/admin/profit-loss", methods=["GET"])
@require_role("manager")
def admin_profit_loss():
    period = request.args.get("period")
    if not period:
        return jsonify({"error": "請提供 period 參數(YYYY-MM)"}), 400
    return jsonify(payroll.get_profit_loss_summary(period))


@app.route("/api/admin/payroll/<int:record_id>/payslip.pdf", methods=["GET"])
@require_role("manager")
def admin_download_payslip(record_id):
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            output_path = tmp.name
        payroll.generate_payslip_pdf(record_id, output_path)
        conn = get_conn()
        r = conn.execute(
            "SELECT pr.period, st.name FROM coach_payroll_records pr JOIN staff st ON pr.coach_id=st.id WHERE pr.id=?",
            (record_id,),
        ).fetchone()
        conn.close()
        filename = f"薪資單_{r['name']}_{r['period']}.pdf" if r else "薪資單.pdf"
        return send_file(output_path, as_attachment=True, download_name=filename, mimetype="application/pdf")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/admin/reports/export", methods=["GET"])
@require_role("manager")
def admin_reports_export():
    from datetime import date
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font

    date_from = request.args.get("date_from") or (booking.today_tw().replace(day=1)).isoformat()
    date_to = request.args.get("date_to") or booking.today_tw().isoformat()
    r = booking.get_report_summary(date_from, date_to)

    wb = Workbook()
    bold = Font(bold=True)

    ws1 = wb.active
    ws1.title = "營收總覽"
    ws1.append([f"ERSKI 管理報表 {r['date_from']} ~ {r['date_to']}"])
    ws1["A1"].font = bold
    ws1.append([])
    ws1.append(["項目", "金額/數值"])
    ws1.append(["本期總營收(NT$)", r["total_revenue"]])
    ws1.append(["機台利用率(%)", r["machine_utilization_pct"]])
    ws1.append([])
    ws1.append(["各課程種類營收"])
    ws1.append(["課程種類", "筆數", "金額(NT$)"])
    for x in r["revenue_by_type"]:
        ws1.append([x["label"], x["count"], x["total"]])
    ws1.append([])
    ws1.append(["各課程預約數"])
    ws1.append(["課程種類", "筆數"])
    cat_label = {"trial": "體驗課", "charter": "包機課", "self_practice": "自主練習",
                 "group_class": "團課", "jump": "跳台體驗", "japan": "日本教練課"}
    for k, v in r["booking_counts"].items():
        ws1.append([cat_label.get(k, k), v])

    ws2 = wb.create_sheet("教練績效")
    ws2.append(["教練姓名", "帶課次數", "授課時數", "時薪(NT$)", "預估授課費用(NT$)"])
    for c in r["coach_performance"]:
        ws2.append([c["name"], c["count"], c["hours"], c.get("hourly_rate") or "", c.get("estimated_pay") or ""])

    ws3 = wb.create_sheet("體驗課轉換")
    tc = r["trial_conversion"]
    ws3.append(["體驗課會員數", "已轉正式課程人數", "轉換率(%)"])
    ws3.append([tc["trial_customers"], tc["converted_to_paid"], tc["conversion_rate_pct"]])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(
        buf.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=ERSKI_report_{date_from}_{date_to}.xlsx"},
    )


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


@app.route("/api/faq", methods=["GET"])
def list_faq():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM faq_entries WHERE is_active=1 ORDER BY category, id").fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/faq/ask", methods=["POST"])
def ask_faq():
    """簡易關鍵字比對客服機器人:依關鍵字重疊數量找出最相關的FAQ,找不到則記錄為待回覆問題。"""
    d = request.json
    question_text = (d.get("question") or "").strip()
    if not question_text:
        return jsonify({"error": "請輸入問題內容"}), 400

    conn = get_conn()
    entries = conn.execute("SELECT * FROM faq_entries WHERE is_active=1").fetchall()
    best_match, best_score = None, 0
    for e in entries:
        keywords = [k.strip() for k in (e["keywords"] or "").split(",") if k.strip()]
        score = sum(1 for k in keywords if k in question_text)
        if score > best_score:
            best_score, best_match = score, e

    if best_match:
        conn.close()
        return jsonify({"matched": True, "question": best_match["question"], "answer": best_match["answer"]})

    conn.execute(
        "INSERT INTO faq_unanswered_log (member_id, question_text) VALUES (?, ?)",
        (d.get("member_id"), question_text),
    )
    conn.commit()
    conn.close()
    return jsonify({"matched": False, "message": "很抱歉,目前無法自動回答這個問題,已為你建立客服案件,將由專人協助處理。"})


@app.route("/api/admin/faq", methods=["POST"])
@require_role("cs")
def admin_create_faq():
    d = request.json
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO faq_entries (question, answer, keywords, category) VALUES (?, ?, ?, ?)",
        (d["question"], d["answer"], d.get("keywords", ""), d.get("category", "")),
    )
    conn.commit()
    faq_id = cur.lastrowid
    conn.close()
    return jsonify({"id": faq_id}), 201


@app.route("/api/admin/faq/<int:faq_id>", methods=["PUT"])
@require_role("cs")
def admin_update_faq(faq_id):
    d = request.json
    conn = get_conn()
    conn.execute(
        "UPDATE faq_entries SET question=?, answer=?, keywords=?, category=?, is_active=? WHERE id=?",
        (d["question"], d["answer"], d.get("keywords", ""), d.get("category", ""), d.get("is_active", 1), faq_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/faq/<int:faq_id>", methods=["DELETE"])
@require_role("cs")
def admin_delete_faq(faq_id):
    conn = get_conn()
    conn.execute("UPDATE faq_entries SET is_active=0 WHERE id=?", (faq_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/faq/unanswered", methods=["GET"])
@require_role("cs")
def admin_list_unanswered_faq():
    conn = get_conn()
    rows = conn.execute(
        """SELECT u.*, m.name AS member_name FROM faq_unanswered_log u
           LEFT JOIN members m ON u.member_id = m.id
           WHERE u.status='pending' ORDER BY u.created_at"""
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/faq/unanswered/<int:log_id>/resolve", methods=["POST"])
@require_role("cs")
def admin_resolve_unanswered_faq(log_id):
    d = request.json
    conn = get_conn()
    conn.execute(
        "UPDATE faq_unanswered_log SET status='resolved', resolved_by_staff_id=?, resolution_note=? WHERE id=?",
        (request.current_staff["id"], d.get("resolution_note"), log_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/equipment", methods=["GET"])
@require_role("cs")
def admin_list_equipment():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM equipment_items ORDER BY id").fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/equipment", methods=["POST"])
@require_role("manager")
def admin_create_equipment():
    d = request.json
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO equipment_items (name, equipment_type, notes) VALUES (?, ?, ?)",
        (d["name"], d["equipment_type"], d.get("notes")),
    )
    conn.commit()
    eq_id = cur.lastrowid
    conn.close()
    return jsonify({"id": eq_id}), 201


@app.route("/api/admin/equipment/<int:equipment_id>/status", methods=["PUT"])
@require_role("cs")
def admin_update_equipment_status(equipment_id):
    d = request.json
    conn = get_conn()
    before = conn.execute("SELECT status FROM equipment_items WHERE id=?", (equipment_id,)).fetchone()
    conn.execute("UPDATE equipment_items SET status=? WHERE id=?", (d["status"], equipment_id))
    conn.execute(
        """INSERT INTO audit_log (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, 'update_equipment_status', 'equipment_item', ?, ?, ?)""",
        (request.current_staff["id"], equipment_id,
         json.dumps({"status": before["status"] if before else None}), json.dumps({"status": d["status"]})),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/equipment/<int:equipment_id>/logs", methods=["GET"])
@require_role("cs")
def admin_list_equipment_logs(equipment_id):
    conn = get_conn()
    rows = conn.execute(
        """SELECT l.*, st.name AS staff_name FROM equipment_maintenance_log l
           LEFT JOIN staff st ON l.staff_id = st.id
           WHERE l.equipment_id=? ORDER BY l.created_at DESC""",
        (equipment_id,),
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/equipment/<int:equipment_id>/logs", methods=["POST"])
@require_role("cs")
def admin_create_equipment_log(equipment_id):
    d = request.json
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO equipment_maintenance_log (equipment_id, log_type, description, photo, staff_id)
           VALUES (?, ?, ?, ?, ?)""",
        (equipment_id, d["log_type"], d.get("description"), d.get("photo"), request.current_staff["id"]),
    )
    conn.commit()
    log_id = cur.lastrowid
    conn.close()
    return jsonify({"id": log_id}), 201


@app.route("/api/admin/equipment-logs/<int:log_id>/resolve", methods=["POST"])
@require_role("cs")
def admin_resolve_equipment_log(log_id):
    d = request.json
    conn = get_conn()
    conn.execute(
        "UPDATE equipment_maintenance_log SET status='resolved', resolved_at=datetime('now'), resolution_note=? WHERE id=?",
        (d.get("resolution_note"), log_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/equipment/<int:equipment_id>/closures", methods=["GET"])
@require_role("cs")
def admin_list_equipment_closures(equipment_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM equipment_closures WHERE equipment_id=? ORDER BY closure_date", (equipment_id,)
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/admin/equipment/<int:equipment_id>/closures", methods=["POST"])
@require_role("cs")
def admin_add_equipment_closure(equipment_id):
    d = request.json
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO equipment_closures (equipment_id, closure_date, reason) VALUES (?, ?, ?)",
        (equipment_id, d["closure_date"], d.get("reason")),
    )
    conn.commit()
    closure_id = cur.lastrowid
    conn.close()
    return jsonify({"id": closure_id}), 201


@app.route("/api/admin/equipment-closures/<int:closure_id>", methods=["DELETE"])
@require_role("cs")
def admin_delete_equipment_closure(closure_id):
    conn = get_conn()
    conn.execute("DELETE FROM equipment_closures WHERE id=?", (closure_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    import os
    if not os.path.exists(os.path.join(os.path.dirname(__file__), "erski.db")):
        init_db()
    app.run(debug=False, port=5001)
