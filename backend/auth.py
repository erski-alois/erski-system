"""
會員端: LINE / Google OAuth (目前為 mock,正式上線改接真正 OAuth flow)
員工端: 工號 + 密碼(預設=生日六碼),登入後依角色直接導向對應畫面
"""

import hashlib
import secrets
from db import get_conn


def hash_password(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


def create_member(data: dict) -> dict:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO members
           (name, id_number, phone, emergency_contact_name, emergency_contact_phone,
            line_user_id, email, auth_provider)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["name"], data.get("id_number"), data.get("phone"),
            data.get("emergency_contact_name"), data.get("emergency_contact_phone"),
            data.get("line_user_id"), data.get("email"), data["auth_provider"],
        ),
    )
    conn.commit()
    member_id = cur.lastrowid
    row = conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    conn.close()
    return dict(row)


def staff_login(work_id: str, password: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM staff WHERE work_id=?", (work_id,)).fetchone()
    conn.close()
    if not row:
        return None
    if row["password_hash"] != hash_password(password):
        return None
    staff = dict(row)
    staff.pop("password_hash")
    return staff
