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

import csv
import io
import json
import re

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
_REASON_LABELS = {
    "want_job": "想應徵滑雪教練工作",
    "know_level": "想知道自己的程度如何",
    "need_visa": "想申請日本工作簽證",
    "improve_ski": "想精進滑行能力",
    "improve_teaching": "想精進教學能力",
    "other": "其他",
}

# 2026-09第三次改版:國家/地區改成下拉選單,學員選一個分類、地址本身(中文/英文
# 地址欄位)還是自己填文字——下拉選單只負責「分類」,不是取代原本的地址欄位。
# 前端下拉選單的選項就是這個清單(見index.html的#csiaAddressCountry),後端只
# 檢查「有沒有選」,不特別檢查選的字串是否剛好在這個清單裡,避免以後前端選項
# 異動還要跟著改後端、部署順序卡住彼此。
ADDRESS_COUNTRY_OPTIONS = ("台灣", "日本", "香港", "澳門", "中國", "新加坡", "馬來西亞", "其他")

# 2026-09第三次改版:依你的指示新增必填欄位。chinese_name本來就必填,這次新增
# CSIA會員編號、緊急聯絡人姓名/電話,以及新增的國家/地區下拉選單。
_REQUIRED_FIELD_MESSAGES = {
    "chinese_name": "請填寫中文姓名",
    "address_country": "請選擇國家/地區",
    "csia_member_number": "請填寫CSIA會員編號",
    "emergency_contact_name": "請填寫緊急聯絡人姓名",
    "emergency_contact_phone": "請填寫緊急聯絡人電話",
}
_REQUIRED_TEXT_FIELDS = tuple(_REQUIRED_FIELD_MESSAGES.keys())

# 手機/緊急聯絡電話「防呆」格式檢查:先把常見的分隔符號(空格、破折號、括號)拿掉,
# 允許開頭有一個「+」(國碼),剩下的必須全部是數字,長度限制8~15碼——這個範圍
# 同時涵蓋台灣手機(09xxxxxxxx共10碼)跟日本/其他國家常見的手機碼數,故意不寫死
# 成只認台灣09開頭的格式,避免擋到國際學員。
_PHONE_STRIP_PATTERN = re.compile(r"[\s\-()]")


def _validate_phone_format(value, field_label):
    """檢查電話號碼格式,value是空字串/None時直接跳過(呼叫端自行決定這個欄位
    是否必填,這裡只負責「有填的話格式對不對」)。格式不對時丟ValueError。"""
    if not value:
        return
    cleaned = _PHONE_STRIP_PATTERN.sub("", value.strip())
    digits = cleaned[1:] if cleaned.startswith("+") else cleaned
    if not digits.isdigit() or not (8 <= len(digits) <= 15):
        raise ValueError(f"{field_label}格式不正確,請確認只包含數字(可加國碼+、可用-或空格分隔),長度需在8~15碼之間")

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


def _with_stay_label(course_dict):
    """2026-09第七次改版:依你提供的各場次住宿晚數,補上「含X晚住宿+早餐+晚餐」這種
    文字給前端直接顯示用(nights_of_stay沒填時,維持原本「含住宿+早餐+晚餐」的講法,
    不強制每個場次都要填晚數)。"""
    nights = course_dict.get("nights_of_stay")
    course_dict["with_stay_label"] = f"含{nights}晚住宿+早餐+晚餐" if nights else "含住宿+早餐+晚餐"
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
        result.append(_with_stay_label(_with_price_display(d)))
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
            raise ValueError(_REQUIRED_FIELD_MESSAGES[field])

    try:
        _validate_phone_format(data.get("mobile_number"), "手機號碼")
        _validate_phone_format(data.get("emergency_contact_phone"), "緊急聯絡人電話")
    except ValueError:
        conn.close()
        raise

    # 2026-09第三次改版:依你的指示「報名一個名字只能報一次」——這裡採取的判斷
    # 是「同一個姓名(去除頭尾空白、不分大小寫比對)只要還有一筆未取消的報名紀錄,
    # 不論是哪個場次,都不能再送出新報名」,不是只擋「同一場次」而已。這是因為
    # 正式環境目前剛好就有一筆真實的重複案例可以對照(酆士豪這個名字對同一場次
    # 報名了兩次),如果之後發現有學員是合理地「先報Level 1、通過後再報Level 2」
    # 這種跨場次的正常情境,而不是誤按重複送出,請告訴我,我再把這個判斷改成只
    # 擋「同一場次」重複報名就好。
    existing_dup = conn.execute(
        "SELECT id FROM csia_registrations WHERE status != 'cancelled' AND lower(trim(chinese_name)) = lower(?)",
        (data.get("chinese_name").strip(),),
    ).fetchone()
    if existing_dup:
        conn.close()
        raise ValueError("這個姓名已經有一筆有效的報名紀錄,同一位學員僅能報名一次;如需修改資料或改報其他場次,請聯繫客服協助處理,不要重複送出報名")

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
            address_country, address_chinese, address_english, address_other, mobile_number, email, line_or_whatsapp_id,
            csia_member_number, occupation, emergency_contact_name, emergency_contact_phone,
            existing_certifications, ski_experience, teaching_experience, reasons, reason_other,
            eligibility_confirmed, price_option, amount
        ) VALUES (?,?,?,?, ?,?,?, ?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?,?, ?,?,?,?, ?,?,?,?,?, ?,?,?)""",
        (
            member_id, course["id"], 1, 1,
            data.get("membership_card_file_name"), data.get("membership_card_mime_type"), data.get("membership_card_image"),
            data.get("waiver_file_name"), data.get("waiver_mime_type"), data.get("waiver_image"),
            data.get("designation"), data.get("chinese_name").strip(), data.get("kanji_or_other_name"), data.get("examiner_call_name"),
            data.get("birth_date"), data.get("gender"),
            data.get("address_country"), data.get("address_chinese"), data.get("address_english"), data.get("address_other"),
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
        result.append(_with_stay_label(_with_price_display(d)))
    conn.close()
    return result


_COURSE_EDITABLE_FIELDS = (
    "level", "batch_label", "language", "course_name", "format_note",
    "date_label", "date_sort_key", "venue", "price_jpy_basic", "price_jpy_with_stay",
    "nights_of_stay", "min_headcount", "max_headcount", "status", "notes",
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
            venue, price_jpy_basic, price_jpy_with_stay, nights_of_stay, min_headcount, max_headcount,
            status, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            data.get("level"), data.get("batch_label"), data.get("language"), data.get("course_name"),
            data.get("format_note"), data.get("date_label"), data.get("date_sort_key"),
            data.get("venue") or "宮城鬼首滑雪場 Onikoube, Miyagi",
            data.get("price_jpy_basic"), data.get("price_jpy_with_stay"), data.get("nights_of_stay"),
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



# 2026-09第三次改版:後台開放編輯考生基本資料(依你的指示「後台可以對報名考生
# 進行修改」)。刻意不放course_id/member_id進這個清單——換場次牽涉名額/金額
# 快照重新計算,換會員更是幾乎不會有的操作,這兩個都不是「修改考生資料」這個
# 需求本來要處理的範圍,如果之後真的需要「後台把某筆報名轉到另一個場次」這種
# 功能,請告訴我,需要另外設計(要重新檢查名額、是否要重新计算金額等)。
# 會員卡/Waiver上傳圖檔也不放進來——後台修改圖片檔案是另一組UI(檔案上傳),
# 不是這次「修改考生資料」文字欄位的需求範圍。
_REGISTRATION_EDITABLE_FIELDS = (
    "designation", "chinese_name", "kanji_or_other_name", "examiner_call_name",
    "birth_date", "gender",
    "address_country", "address_chinese", "address_english", "address_other",
    "mobile_number", "email", "line_or_whatsapp_id",
    "csia_member_number", "occupation", "emergency_contact_name", "emergency_contact_phone",
    "existing_certifications", "ski_experience", "teaching_experience", "reason_other",
    "price_option", "amount",
)


def admin_update_registration(reg_id, data, staff_id=None):
    """後台更新一筆報名。原本只能改payment_status/status/staff_note這三個欄位,
    2026-09第三次改版依你的指示擴充成也能修改考生基本資料(_REGISTRATION_EDITABLE_
    FIELDS這份清單裡的欄位)——只有data裡實際有出現的欄位才會被更新,沒出現的
    欄位維持原樣(部分更新,不是整筆覆蓋)。標記為payment_status='paid'時,自動
    記錄paid_at時間並通知會員;標記status='cancelled'時,也通知會員。"""
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

    # 後台編輯考生資料:必填欄位如果被帶進來要改,不能改成空白;電話類欄位如果
    # 有帶新值,一樣要跑格式防呆檢查,跟會員自己填表單時的規則一致。
    if "chinese_name" in data and not (data.get("chinese_name") or "").strip():
        conn.close()
        raise ValueError(_REQUIRED_FIELD_MESSAGES["chinese_name"])
    for f in ("address_country", "csia_member_number", "emergency_contact_name", "emergency_contact_phone"):
        if f in data and not (data.get(f) or "").strip():
            conn.close()
            raise ValueError(_REQUIRED_FIELD_MESSAGES[f])
    try:
        if "mobile_number" in data:
            _validate_phone_format(data.get("mobile_number"), "手機號碼")
        if "emergency_contact_phone" in data:
            _validate_phone_format(data.get("emergency_contact_phone"), "緊急聯絡人電話")
    except ValueError:
        conn.close()
        raise
    if "price_option" in data and data.get("price_option") not in PRICE_OPTIONS:
        conn.close()
        raise ValueError("價格方案不正確")

    for f in _REGISTRATION_EDITABLE_FIELDS:
        if f in data:
            value = data[f]
            if f == "chinese_name" and isinstance(value, str):
                value = value.strip()
            sets.append(f"{f}=?")
            params.append(value)
    if "reasons" in data:
        reasons = data["reasons"]
        if not isinstance(reasons, list):
            reasons = []
        reasons = [r for r in reasons if r in REASON_OPTIONS]
        sets.append("reasons=?")
        params.append(json.dumps(reasons))

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


def admin_delete_registration(reg_id):
    """後台刪除一筆報名資料(依你的指示新增,原本完全沒有刪除功能)。這是直接
    硬刪除資料庫紀錄,不是標記取消(標記取消請用admin_update_registration改
    status='cancelled',那個會保留紀錄並通知會員;這支是真的整筆刪掉,刪了就
    沒有了,前端按這個按鈕前務必要有二次確認)。"""
    conn = get_conn()
    row = conn.execute("SELECT id FROM csia_registrations WHERE id=?", (reg_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("找不到這筆報名資料,可能已經被刪除")
    conn.execute("DELETE FROM csia_registrations WHERE id=?", (reg_id,))
    conn.commit()
    conn.close()


def admin_get_registration(reg_id):
    """後台用:查詢單筆報名的完整資料(含會員/課程場次資訊),給匯出功能使用。"""
    conn = get_conn()
    row = conn.execute(
        """SELECT r.*, m.name AS member_name, m.phone AS member_phone,
               c.level, c.batch_label, c.course_name, c.date_label, c.venue
           FROM csia_registrations r
           JOIN members m ON r.member_id = m.id
           JOIN csia_courses c ON r.course_id = c.id
           WHERE r.id=?""",
        (reg_id,),
    ).fetchone()
    conn.close()
    if not row:
        raise ValueError("找不到這筆報名資料")
    result = dict(row)
    result["amount_twd"] = _to_twd(result.get("amount"))
    return result


_GENDER_LABELS = {"male": "男", "female": "女", "other": "其他"}
_PAYMENT_STATUS_LABELS = {"unpaid": "未付款", "paid": "已付款", "refunded": "已退款"}
_REG_STATUS_LABELS = {"submitted": "已送出,待確認", "confirmed": "已確認", "cancelled": "已取消"}
_PRICE_OPTION_LABELS = {"basic": "課程本身", "with_stay": "含住宿+早餐+晚餐"}


def export_registration_csv(reg_id):
    """把單一考生的整筆報名資料匯出成CSV(依你的指示「資料每個人整筆匯出」)。
    刻意不把會員卡/Waiver圖檔的base64內容塞進CSV(那樣檔案會很肥、Excel也打不開
    圖片),只匯出「是否已上傳」這個狀態;真的要看圖片內容,後台畫面上本來就有
    縮圖可以看。回傳(檔名, CSV位元組內容),位元組內容開頭加上UTF-8 BOM
    (\\ufeff),是因為Excel預設用非UTF-8的編碼去猜測CSV檔案,沒有BOM的話中文
    字會變亂碼——這個做法跟前端既有的CSV匯出(CSV_TEMPLATES那組)用的是同一招。"""
    r = admin_get_registration(reg_id)
    reasons = []
    try:
        reasons = json.loads(r.get("reasons") or "[]")
    except (TypeError, ValueError):
        reasons = []
    reason_text = "、".join(_REASON_LABELS.get(k, k) for k in reasons)
    if r.get("reason_other"):
        reason_text = f"{reason_text}(其他:{r['reason_other']})" if reason_text else f"其他:{r['reason_other']}"

    rows = [
        ("報名編號", r.get("id")),
        ("課程等級", r.get("level")),
        ("場次梯次", r.get("batch_label")),
        ("課程名稱", r.get("course_name")),
        ("日期", r.get("date_label")),
        ("場地", r.get("venue")),
        ("職稱/身分", r.get("designation") or ""),
        ("中文姓名", r.get("chinese_name") or ""),
        ("護照姓名/其他姓名", r.get("kanji_or_other_name") or ""),
        ("考官稱呼", r.get("examiner_call_name") or ""),
        ("出生日期", r.get("birth_date") or ""),
        ("性別", _GENDER_LABELS.get(r.get("gender"), r.get("gender") or "")),
        ("國家/地區", r.get("address_country") or ""),
        ("中文通訊地址", r.get("address_chinese") or ""),
        ("英文地址", r.get("address_english") or ""),
        ("其他地址補充", r.get("address_other") or ""),
        ("手機號碼", r.get("mobile_number") or ""),
        ("Email", r.get("email") or ""),
        ("LINE ID / WhatsApp", r.get("line_or_whatsapp_id") or ""),
        ("CSIA會員編號", r.get("csia_member_number") or ""),
        ("職業", r.get("occupation") or ""),
        ("緊急聯絡人姓名", r.get("emergency_contact_name") or ""),
        ("緊急聯絡人電話", r.get("emergency_contact_phone") or ""),
        ("已持有相關證照", r.get("existing_certifications") or ""),
        ("滑雪經驗", r.get("ski_experience") or ""),
        ("教學經驗", r.get("teaching_experience") or ""),
        ("報考原因", reason_text),
        ("CSIA會員卡已上傳", "是" if r.get("membership_card_image") else "否"),
        ("CSIA Waiver已上傳", "是" if r.get("waiver_image") else "否"),
        ("價格方案", _PRICE_OPTION_LABELS.get(r.get("price_option"), r.get("price_option") or "")),
        ("報名費(JPY)", r.get("amount") if r.get("amount") is not None else "金額洽詢"),
        ("報名費(約NT$)", r.get("amount_twd") if r.get("amount_twd") is not None else "金額洽詢"),
        ("付款狀態", _PAYMENT_STATUS_LABELS.get(r.get("payment_status"), r.get("payment_status") or "")),
        ("報名狀態", _REG_STATUS_LABELS.get(r.get("status"), r.get("status") or "")),
        ("客服備註", r.get("staff_note") or ""),
        ("會員登入姓名", r.get("member_name") or ""),
        ("會員登入電話", r.get("member_phone") or ""),
        ("報名建立時間", r.get("created_at") or ""),
    ]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["欄位", "內容"])
    writer.writerows(rows)
    csv_bytes = ("﻿" + buf.getvalue()).encode("utf-8")
    safe_name = (r.get("chinese_name") or "考生").replace("/", "_").replace("\\", "_")
    filename = f"CSIA報名資料_{safe_name}_{r.get('id')}.csv"
    return filename, csv_bytes
