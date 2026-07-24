import sqlite3
import os
import hashlib

DB_PATH = os.path.join(os.path.dirname(__file__), "erski.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _hash(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


DEMO_STAFF = [
    # work_id, name, display_code, birthday(YYYYMMDD), role, branch
    ("0001", "陳老闆", "", "19800101", "boss", "高雄"),
    ("0002", "林主管", "", "19850202", "manager", "高雄"),
    ("0003", "黃客服", "", "19900303", "cs", "高雄"),
    ("0004", "張教練", "甲", "19950404", "coach", "高雄"),
    ("0005", "李教練", "乙", "19960505", "coach", "高雄"),
]


def _seed_demo_staff(conn):
    for work_id, name, code, birthday, role, branch in DEMO_STAFF:
        password = birthday[2:8]  # 生日六碼(YYMMDD)
        conn.execute(
            """INSERT OR IGNORE INTO staff
               (work_id, name, display_code, phone, birthday, password_hash, role, branch)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (work_id, name, code, "0900000000", birthday, _hash(password), role, branch),
        )
    # 示範:把甲、乙教練指派到雪場 A(id=1),供日本教練課容量計算測試
    coach_ids = conn.execute(
        "SELECT id FROM staff WHERE work_id IN ('0004','0005')"
    ).fetchall()
    for c in coach_ids:
        conn.execute(
            "INSERT OR IGNORE INTO resort_coaches (resort_id, coach_id) VALUES (1, ?)",
            (c["id"],),
        )


def init_db(reset=False):
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = get_conn()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    _seed_demo_staff(conn)
    conn.commit()
    conn.close()


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db(reset=True)
    print(f"Database initialized at {DB_PATH}")
    print("示範員工帳號(工號 / 密碼 / 角色): "
          "0001/800101/boss、0002/850202/manager、0003/900303/cs、0004/950404/coach")

