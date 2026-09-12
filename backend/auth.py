"""
會員端: LINE / Google OAuth (目前為 mock,正式上線改接真正 OAuth flow)
員工端: 工號 + 密碼(預設=生日六碼),登入後依角色直接導向對應畫面
"""

import hashlib
import re
import secrets
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_conn

# 註冊資料格式驗證(2026-09:依需求「註冊手機得防止客人輸入無效號碼及無效Email」新增)。
# Email用最基本的「有@、@後面有網域含.」規則,不用太嚴格(嚴格的RFC5322正規表示式反而
# 常常誤擋合法信箱),主要是擋明顯打錯/亂打的情況。
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
# 手機只接受台灣手機號碼格式:09開頭、共10碼數字。輸入時允許夾雜空格或「-」
# (例如 0912-345-678),驗證前由呼叫端先去掉這些符號。
_TW_PHONE_RE = re.compile(r"^09\d{8}$")


def is_valid_email(email: str) -> bool:
    return bool(email) and bool(_EMAIL_RE.match(email.strip()))


def is_valid_tw_phone(phone: str) -> bool:
    if not phone:
        return False
    digits = re.sub(r"[\s-]", "", phone)
    return bool(_TW_PHONE_RE.match(digits))


def hash_password(raw: str) -> str:
    """2026-08-24前的舊雜湊方式:純SHA-256、沒有加鹽。這種做法不適合存密碼——沒有鹽值
    代表同樣的密碼在不同帳號會產生一模一樣的雜湊值,而且SHA-256設計成快速運算,離線
    暴力破解/查表攻擊的成本很低,一旦資料庫外洩,密碼等於直接曝光。新密碼一律改用
    werkzeug內建的generate_password_hash(預設scrypt演算法,自動加鹽、刻意運算較慢)。
    這個函式保留下來只給_verify_password()做「舊格式相容比對」用,不要再用來產生新密碼。"""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_legacy_sha256_hash(stored: str) -> bool:
    """舊格式是64位純十六進位字元(sha256 hexdigest固定長度、只含0-9a-f);
    werkzeug新格式一定含有'$'/':'這類分隔符號,兩種格式不會混淆判斷錯誤。"""
    return bool(stored) and len(stored) == 64 and all(c in "0123456789abcdef" for c in stored.lower())


def verify_password(stored_hash: str, raw_password: str) -> bool:
    """驗證密碼,同時相容「這次上線前就已經用舊SHA-256方式存的密碼」跟「這次之後
    新設定/新變更、已經改用werkzeug強雜湊的密碼」,不用特地寫遷移程式改資料庫裡
    既有的密碼(而且雜湊本來就是單向的,沒有原始密碼也沒辦法重新雜湊既有資料)。"""
    if not stored_hash:
        return False
    if _is_legacy_sha256_hash(stored_hash):
        return hash_password(raw_password) == stored_hash
    return check_password_hash(stored_hash, raw_password)


def new_password_hash(raw_password: str) -> str:
    """設定新密碼(不論是會員第一次設定、變更密碼,或未來後台重設員工密碼)一律呼叫
    這支,不要再呼叫hash_password()存新密碼。"""
    return generate_password_hash(raw_password)


def mock_oauth_login(provider: str, mock_external_id: str) -> dict:
    """
    正式環境: provider='line' 時導向 LINE Login,取得 real user id 後呼叫此函式;
    provider='google' 時走 Google OAuth 2.0 flow。
    目前用 mock_external_id 模擬第三方回傳的使用者識別碼。
    回傳 {'is_new': bool, 'member': dict|None}
    """
    conn = get_conn()
    col = "line_user_id" if provider == "line" else "email"
    row = conn.execute(
        f"SELECT * FROM members WHERE {col} = ?", (mock_external_id,)
    ).fetchone()
    conn.close()
    if row:
        return {"is_new": False, "member": dict(row)}
    return {"is_new": True, "member": None}


def member_login(email: str, password: str):
    """2026-09新增:Email+密碼登入(正式上線用的會員登入)。這之前系統完全沒有這條路——
    舊的「用Email登入」其實是呼叫mock_oauth_login(provider='email'),只要Email存在
    就直接放行,完全沒有驗證密碼,等於任何人知道會員的Email就能登入該帳號。

    回傳三種結果(用一個dict表示,呼叫端app.py依內容組對應的HTTP狀態碼):
      - 找不到這個Email的會員:{"error": "..."}
      - 找到會員,但這個帳號是2026-09正式上線前註冊的舊帳號,從來沒有設定過密碼
        (password_hash是NULL):{"member": dict, "needs_password_setup": True}——
        這種情況刻意不擋密碼(反正對方本來就沒有密碼可以驗證),直接視為登入成功,
        但標記needs_password_setup,前端看到這個旗標要導去「會員中心」的
        「修改登入密碼」卡片,強制先設定一組密碼再繼續使用其他功能。
        (這是唯一目前能讓舊會員「恢復登入」的辦法——系統目前沒有真的寄送Email/簡訊
        驗證信的能力,沒辦法做正規的「忘記密碼,寄重設連結」流程,詳見README說明。)
      - 找到會員,且已經設定過密碼:密碼正確才回傳{"member": dict, "needs_password_setup": False},
        密碼不對回傳{"error": "..."}。"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM members WHERE email=?", ((email or "").strip(),)).fetchone()
    conn.close()
    if not row:
        return {"error": "查無此Email的會員帳號,請確認輸入是否正確,或先完成註冊"}
    member = dict(row)
    if not member.get("password_hash"):
        member.pop("password_hash", None)
        return {"member": member, "needs_password_setup": True}
    if not verify_password(member["password_hash"], password or ""):
        return {"error": "密碼不正確"}
    member.pop("password_hash", None)
    return {"member": member, "needs_password_setup": False}


def create_member(data: dict) -> dict:
    """建立新會員(正式註冊,不是demo快速登入)。姓名/手機/Email是前台註冊表單一定會
    收集的三項基本資料,這裡統一做格式驗證,不能只靠前端檢查——前端的檢查繞得過去
    (例如直接呼叫API),後端才是真正把關的地方。驗證不過一律丟ValueError,呼叫端
    (app.py)接住後回傳400跟錯誤訊息給前端顯示。

    2026-09新增:auth_provider='email'(用Email註冊/登入,目前唯一真正驗證密碼的
    登入方式)這種情況下,註冊時一併要求設定登入密碼(至少6碼),不再讓帳號一開始
    就是「沒有密碼」的狀態——這是配合「全部進入正式上線狀況,會員登入得以正式帳號
    密碼登入」這個需求的一部分。line/google/apple這3種目前還是模擬OAuth按鈕
    (還沒有串接真正的第三方OAuth,詳見mock_oauth_login的說明),沒有密碼欄位,
    維持原本「OAuth完成=身分驗證完成」的邏輯不變,不受這次改動影響。"""
    name = (data.get("name") or "").strip()
    phone = re.sub(r"[\s-]", "", data.get("phone") or "")
    email = (data.get("email") or "").strip()
    auth_provider = data.get("auth_provider")
    password = data.get("password")

    if not name:
        raise ValueError("請輸入姓名")
    if not is_valid_tw_phone(phone):
        raise ValueError("手機號碼格式不正確,請輸入台灣手機號碼(例如:0912345678)")
    if not is_valid_email(email):
        raise ValueError("Email格式不正確,請重新輸入")
    if auth_provider == "email":
        if not password or len(password) < 6:
            raise ValueError("請設定登入密碼(至少6碼)")

    conn = get_conn()
    existing = conn.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone()
    if existing:
        conn.close()
        raise ValueError("此Email已經註冊過會員,請直接使用登入方式登入,或改用其他Email註冊")

    password_hash = new_password_hash(password) if (auth_provider == "email" and password) else None
    cur = conn.execute(
        """INSERT INTO members (name, phone, line_user_id, email, auth_provider, password_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            name, phone,
            data.get("line_user_id"), email, auth_provider, password_hash,
        ),
    )
    conn.commit()
    member_id = cur.lastrowid
    row = conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    conn.close()
    return dict(row)


REQUIRED_PROFILE_FIELDS = [
    "name", "birth_date", "address", "phone", "email",
    "emergency_contact_name", "emergency_contact_phone",
]


def is_profile_complete(member_row) -> bool:
    m = dict(member_row)
    return all(m.get(f) for f in REQUIRED_PROFILE_FIELDS)


def set_member_password(member_id: int, new_password: str, current_password: str = None):
    """
    設定/變更會員登入密碼。若會員已經有設定過密碼,變更時必須先驗證目前密碼正確;
    若尚未設定過密碼(例如首次完成註冊資料),可直接設定不需驗證。
    """
    conn = get_conn()
    row = conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("找不到此會員")
    if row["password_hash"]:
        if not current_password or not verify_password(row["password_hash"], current_password):
            conn.close()
            raise ValueError("目前密碼不正確")
    conn.execute(
        "UPDATE members SET password_hash=? WHERE id=?", (new_password_hash(new_password), member_id)
    )
    conn.commit()
    conn.close()


def admin_reset_member_password(member_id: int):
    """2026-09新增:員工端(客服以上)幫會員清除登入密碼,用於「會員忘記密碼,聯繫客服
    協助」這個情境。直接把password_hash清成NULL,不是「員工幫會員設一組新密碼」
    (員工不應該知道/決定會員實際使用的密碼)。清除後這個帳號回到「尚未設定過密碼」
    狀態,會員下次用Email登入(見member_login)會被引導直接設定一組新密碼,
    效果等同於一般系統的「忘記密碼」流程。"""
    conn = get_conn()
    row = conn.execute("SELECT id FROM members WHERE id=?", (member_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("找不到此會員")
    conn.execute("UPDATE members SET password_hash=NULL WHERE id=?", (member_id,))
    conn.commit()
    conn.close()


def set_staff_password(staff_id: int, new_password: str, current_password: str = None, require_current: bool = True):
    """
    設定/變更員工(含教練)登入密碼。require_current=True(本人變更自己的密碼)時,一定要先
    驗證目前密碼正確才能改;require_current=False(主管以上代其他員工重設,例如員工忘記密碼)
    則不需要驗證目前密碼——呼叫端(app.py)負責判斷這兩種情況分別對應到誰在操作,這支函式
    本身不做權限判斷。
    """
    conn = get_conn()
    row = conn.execute("SELECT * FROM staff WHERE id=?", (staff_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("找不到此員工")
    if require_current:
        if not current_password or not verify_password(row["password_hash"], current_password):
            conn.close()
            raise ValueError("目前密碼不正確")
    if not new_password or len(new_password) < 6:
        conn.close()
        raise ValueError("新密碼至少需要6碼")
    conn.execute(
        "UPDATE staff SET password_hash=? WHERE id=?", (new_password_hash(new_password), staff_id)
    )
    conn.commit()
    conn.close()


def staff_login(work_id: str, password: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM staff WHERE work_id=?", (work_id,)).fetchone()
    conn.close()
    if not row:
        return None
    if not row["is_active"]:
        return None
    # 2026-09:依需求「全部進入正式上線狀況」,把先前刻意註解掉的密碼驗證加回來。
    # 教練登入(教練專屬頁面)跟後台登入(股東/主管/老闆的員工後台管理)共用這同一支
    # 函式,這裡修好,兩種登入的密碼驗證會同時恢復,不用分開改兩次。
    if not verify_password(row["password_hash"], password):
        return None
    staff = dict(row)
    staff.pop("password_hash")
    return staff
