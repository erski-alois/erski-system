"""
CSIA滑雪教練考照專區
------------
會員瀏覽課程場次、線上填寫CSIA官方報名流程需要的考生資訊並送出報名;
後台管理課程場次(新增/編輯價格與名額/確認開班或取消)與報名名單(標記付款、取消)。

跟其他預約種類不同,CSIA報名故意不掛進orders/transactions那一套「線上刷卡/
綠界」的通用付款機制——這裡的報名費一律是匯款轉帳(比照你的指示「收費請提供
匯款帳號」),由客服在後台核對匯款後手動標記為已付款,不需要客戶在系統內完成
線上刷卡這個步驟,所以用csia_registrations.payment_status這個欄位自己記錄
即可,不需要建立orders表的訂單紀錄。
"""

import json

from db import get_conn, rows_to_dicts
import booking as booking_module

REASON_OPTIONS = (
    "want_job",          # 想應徵滑雪教練工作
    "know_level",        # 想知道自己的程度如何
    "need_visa",         # 想申請日本工作簽證
    "improve_ski",       # 想精進滑行能力
    "improve_teaching",  # 想精進教學能力
    "other",             # 其他
)

_REQUIRED_TEXT_FIELDS = ("chinese_name",)

# 2026-09第二次改版:報名費金額改成CSIA官方的日圓報價,每個場次有兩種方案。
# JPY_TO_TWD_RATE:依你的指示「以日元匯率1:5與台幣共同顯示」,1新台幣=5日圓,
# 換算新台幣時直接把日圓金額除以這個倍率——僅供畫面上參考對照用,不影響實際
# 報名費金額仍以日圓計價/收費為準(CSIA原始報價就是日圓)。
JPY_TO_TWD_RATE = 5
PRICE_OPTIONS = ("basic", "with_stay")
_PRICE_OPTION_COLUMN = {"basic": "price_jpy_basic", "with_stay": "price_jpy_with_stay"}


def _to_twd(jpy_amount):
    """日圓金額換算新台幣(四捨五入取整數),金額是None時原樣回傳None(代表「金額洽詢」)。"""
    if jpy_amount is None:
        return None
    return round(jpy_amount / JPY_TO_TWD_RATE)


def _with_price_display(course_dict):
    """幫課程場次dict補上兩種方案換算後的新台幣金額,方便前端直接顯示,不用自己再算一次。"""
    course_dict["price_twd_basic"] = _to_twd(course_dict.get("price_jpy_basic"))
    course_dict["price_twd_with_stay"] = _to_twd(course_dict.get("price_jpy_with_stay"))
    return course_dict


def _course_registered_count(conn, course_id):
    """這個課程場次目前有效(未取消)的報名人數。"""
    return conn.execute(
        "SELECT COUNT(*) c FROM csia_registrations WHERE course_id=? AND status != 'cancelled'",
        (course_id,),
    ).fetchone()["c"]


def list_courses_for_members():
    """會員瀏覽用:只回傳還沒取消的課程場次,附上目前有效報名人數/是否已額滿,
    讓前端可以直接顯示「尚可報名X人」或「名額已滿」,不用會員自己送出才知道滿了沒。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM csia_courses WHERE status != 'cancelled' ORDER BY date_sort_key, id"
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["registered_count"] = _course_registered_count(conn, r["id"])
        d["is_full"] = d["registered_count"] >= r["max_headcount"]
        result.append(_with_price_display(d))
    conn.close()
    return result


def get_member_registrations(member_id):
    """會員自己的CSIA報名紀錄(含課程場次資訊,方便前端直接顯示,不用再另外查一次課程)。"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT r.*, c.level, c.batch_label, c.course_name, c.date_label, c.venue, c.status AS course_status
           FROM csia_registrations r JOIN csia_courses c ON r.course_id = c.id
           WHERE r.member_id=? ORDER BY r.created_at DESC""",
        (member_id,),
    ).fetchall()
    conn.close()
    result = rows_to_dicts(rows)
    for r in result:
        r["amount_twd"] = _to_twd(r.get("amount"))
    return result


def create_registration(member_id, data):
    """建立一筆CSIA報名。data是前端送來的dict,對應資料表欄位(見schema.sql的
    csia_registrations)。名額檢查用BEGIN IMMEDIATE立即取得寫入鎖,避免同時間
    多筆報名請求一起繞過額滿檢查(比照booking.enroll_group_class的做法)。"""
    course_id = data.get("course_id")
    if not course_id:
        raise ValueError("請選擇要報名的課程場次")

    conn = get_conn()
    conn.execute("BEGIN IMMEDIATE")
    course = conn.execute("SELECT * FROM csia_courses WHERE id=?", (course_id,)).fetchone()
    if not course:
        conn.close()
        raise ValueError("找不到這個課程場次")
    if course["status"] == "cancelled":
        conn.close()
        raise ValueError("這個課程場次已取消開班,無法報名")
    if course["status"] == "closed":
        conn.close()
        raise ValueError("這個課程場次已截止報名")

    for field in _REQUIRED_TEXT_FIELDS:
        if not (data.get(field) or "").strip():
            conn.close()
            raise ValueError("請填寫中文姓名")
    if not data.get("waiver_confirmed"):
        conn.close()
        raise ValueError("請先完成CSIA Waiver線上填寫,並勾選確認")
    if not data.get("membership_action_confirmed"):
        conn.close()
        raise ValueError("請先完成CSIA會員加入(Level 1)或更新(Level 2),並勾選確認")
    if not data.get("eligibility_confirmed"):
        conn.close()
        raise ValueError("請確認你的年齡、滑行程度、教學經驗及證照已符合這個等級的報名資格")

    price_option = data.get("price_option")
    if price_option not in PRICE_OPTIONS:
        conn.close()
        raise ValueError("請選擇報名費的價格方案(課程本身 / 含住宿+早餐+晚餐)")

    if _course_registered_count(conn, course["id"]) >= course["max_headcount"]:
        conn.close()
        raise ValueError(f"這個課程場次名額已滿(上限{course['max_headcount']}人),請選擇其他場次或洽詢客服")

    reasons = data.get("reasons")
    if not isinstance(reasons, list):
        reasons = []
    reasons = [r for r in reasons if r in REASON_OPTIONS]

    # 報名費金額快照:依會員選的價格方案,從課程場次目前設定的日圓金額取值(可能是
    # None,代表這個方案的金額後台還沒填,畫面上會顯示「金額洽詢」),避免後台事後
    # 改價影響已經報名者原本看到、同意的金額。
    amount = course[_PRICE_OPTION_COLUMN[price_option]]

    cur = conn.execute(
        """INSERT INTO csia_registrations (
            member_id, course_id, waiver_confirmed, membership_action_confirmed,
            membership_card_file_name, membership_card_mime_type, membership_card_image,
            waiver_file_name, waiver_mime_type, waiver_image,
            designation, chinese_name, kanji_or_other_name, examiner_call_name, birth_date, gender,
            address_chinese, address_english, address_other, mobile_number, email, line_or_whatsapp_id,
            csia_member_number, occupation, emergency_contact_name, emergency_contact_phone,
            existing_certifications, ski_experience, teaching_experience, reasons, reason_other,
            eligibility_confirmed, price_option, amount
        ) VALUES (?,?,?,?, ?,?,?, ?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?, ?,?,?,?,?, ?,?,?)""",
        (
            member_id, course["id"], 1, 1,
            data.get("membership_card_file_name"), data.get("membership_card_mime_type"), data.get("membership_card_image"),
            data.get("waiver_file_name"), data.get("waiver_mime_type"), data.get("waiver_image"),
            data.get("designation"), data.get("chinese_name").strip(), data.get("kanji_or_other_name"), data.get("examiner_call_name"),
            data.get("birth_date"), data.get("gender"),
            data.get("address_chinese"), data.get("address_english"), data.get("address_other"),
            data.get("mobile_number"), data.get("email"), data.get("line_or_whatsapp_id"),
            data.get("csia_member_number"), data.get("occupation"), data.get("emergency_contact_name"), data.get("emergency_contact_phone"),
            data.get("existing_certifications"), data.get("ski_experience"), data.get("teaching_experience"),
            json.dumps(reasons), data.get("reason_other"),
            1, price_option, amount,
        ),
    )
    reg_id = cur.lastrowid
    booking_module.log_notification(
        conn, member_id, "csia_registration_submitted",
        f"已收到你的CSIA報名({course['batch_label']} {course['course_name']},{course['date_label']}),"
        f"客服確認報名費匯款後會更新為已確認,請留意會員中心通知。",
    )
    conn.commit()
    row = conn.execute("SELECT * FROM csia_registrations WHERE id=?", (reg_id,)).fetchone()
    conn.close()
    return dict(row)


# ------------------------------------------------------------------
# 後台:課程場次管理
# ------------------------------------------------------------------
def admin_list_courses():
    """後台用:回傳所有課程場次(含已取消的,方便對照歷史紀錄),附上有效報名人數。"""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM csia_courses ORDER BY date_sort_key, id").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["registered_count"] = _course_registered_count(conn, r["id"])
        result.append(_with_price_display(d))
    conn.close()
    return result


_COURSE_EDITABLE_FIELDS = (
    "level", "batch_label", "language", "course_name", "format_note",
    "date_label", "date_sort_key", "venue", "price_jpy_basic", "price_jpy_with_stay",
    "min_headcount", "max_headcount", "status", "notes",
)


def _is_blank(value):
    """判斷欄位是否算「沒填」:字串要trim後檢查,其他型別(例如None)直接檢查真假值。"""
    if isinstance(value, str):
        return not value.strip()
    return not value


def admin_create_course(data):
    conn = get_conn()
    for f in ("level", "batch_label", "language", "course_name", "date_label"):
        if _is_blank(data.get(f)):
            conn.close()
            raise ValueError("請填寫必要欄位(等級/梯次/語言/課程名稱/日期)")
    cur = conn.execute(
        """INSERT INTO csia_courses
           (level, batch_label, language, course_name, format_note, date_label, date_sort_key,
            venue, price_jpy_basic, price_jpy_with_stay, min_headcount, max_headcount, status, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            data.get("level"), data.get("batch_label"), data.get("language"), data.get("course_name"),
            data.get("format_note"), data.get("date_label"), data.get("date_sort_key"),
            data.get("venue") or "宮城鬼首滑雪場 Onikoube, Miyagi",
            data.get("price_jpy_basic"), data.get("price_jpy_with_stay"),
            data.get("min_headcount") or 5, data.get("max_headcount") or 8,
            data.get("status") or "open", data.get("notes"),
        ),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id


def admin_update_course(course_id, data):
    from db import NOW_SQL
    conn = get_conn()
    row = conn.execute("SELECT id FROM csia_courses WHERE id=?", (course_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("找不到這個課程場次")
    updates = {k: v for k, v in data.items() if k in _COURSE_EDITABLE_FIELDS}
    if not updates:
        conn.close()
        return
    set_clause = ", ".join(f"{k}=?" for k in updates)
    conn.execute(
        f"UPDATE csia_courses SET {set_clause}, updated_at={NOW_SQL} WHERE id=?",
        (*updates.values(), course_id),
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------
# 後台:報名名單管理
# ------------------------------------------------------------------
def admin_list_registrations(course_id=None):
    conn = get_conn()
    q = """SELECT r.*, m.name AS member_name, m.phone AS member_phone,
               c.level, c.batch_label, c.course_name, c.date_label
           FROM csia_registrations r
           JOIN members m ON r.member_id = m.id
           JOIN csia_courses c ON r.course_id = c.id
           WHERE 1=1"""
    params = []
    if course_id:
        q += " AND r.course_id=?"
        params.append(course_id)
    q += " ORDER BY r.created_at DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    result = rows_to_dicts(rows)
    for r in result:
        r["amount_twd"] = _to_twd(r.get("amount"))
    return result


def admin_update_registration(reg_id, data, staff_id=None):
    """後台更新一筆報名的付款狀態/報名狀態/備註。標記為payment_status='paid'時,
    自動記錄paid_at時間並通知會員;標記status='cancelled'時,也通知會員。"""
    from db import NOW_SQL
    conn = get_conn()
    row = conn.execute(
        """SELECT r.*, c.batch_label, c.course_name, c.date_label FROM csia_registrations r
           JOIN csia_courses c ON r.course_id = c.id WHERE r.id=?""",
        (reg_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise ValueError("找不到這筆報名資料")

    sets, params = [], []
    if "payment_status" in data:
        payment_status = data["payment_status"]
        if payment_status not in ("unpaid", "paid", "refunded"):
            conn.close()
            raise ValueError("付款狀態不正確")
        sets.append("payment_status=?")
        params.append(payment_status)
        if payment_status == "paid" and row["payment_status"] != "paid":
            sets.append(f"paid_at={NOW_SQL}")
    if "status" in data:
        status = data["status"]
        if status not in ("submitted", "confirmed", "cancelled"):
            conn.close()
            raise ValueError("報名狀態不正確")
        sets.append("status=?")
        params.append(status)
    if "staff_note" in data:
        sets.append("staff_note=?")
        params.append(data["staff_note"])

    if not sets:
        conn.close()
        return

    params.append(reg_id)
    conn.execute(f"UPDATE csia_registrations SET {', '.join(sets)} WHERE id=?", params)

    if data.get("payment_status") == "paid" and row["payment_status"] != "paid":
        booking_module.log_notification(
            conn, row["member_id"], "csia_payment_confirmed",
            f"你的CSIA報名費已確認收訖({row['batch_label']} {row['course_name']},{row['date_label']}),報名已確認。",
        )
    if data.get("status") == "cancelled" and row["status"] != "cancelled":
        booking_module.log_notification(
            conn, row["member_id"], "csia_registration_cancelled",
            f"你的CSIA報名已被取消({row['batch_label']} {row['course_name']},{row['date_label']}),如有疑問請洽詢客服。",
        )

    conn.commit()
    conn.close()
