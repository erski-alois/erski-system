"""新增customer_feedback表:客戶意見反應

依你的指示「常見問題先不開放,隱藏起來,待客服機器人完善後再公開,但要新增一個地方
讓客戶反應意見或提出意見」,「常見問題」頁面隱藏的部分是純前端調整(拿掉會員端導覽
連結,頁面本身與後台FAQ管理都還在,不需要migration),這支migration負責新增的是
補上的那個「讓客戶反應意見」的資料表。

欄位設計比照這次稍早新增的japan_other_resort_requests(以及更早的charter_pass_requests)
「會員提出、後台審核/處理」既有模式:status採pending(待處理)/contacted(已聯繫)/
closed(已結案)三態,handled_by_staff_id/staff_note/handled_at記錄後台處理過程。
content為必填的意見內容,category是會員自選的選填分類(建議/稱讚/客訴/其他,前端下拉
選單提供,後端不做嚴格限制,允許之後前端調整選項不用跟著改schema)。

這支migration完全是新增資料表,不會動到任何既有資料表或既有資料。

Revision ID: 1e1b602c542f
Revises: f18ab078246b
Create Date: 2026-09-21 11:04:13.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '1e1b602c542f'
down_revision: Union[str, Sequence[str], None] = 'f18ab078246b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()把SQL裡的
    # 冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),本機SQLite
    # 開發改schema.sql、由init_schema()直接建表,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customer_feedback (
            id SERIAL PRIMARY KEY,
            member_id INTEGER NOT NULL REFERENCES members(id),
            category TEXT,                    -- 會員自選分類(選填):建議/稱讚/客訴/其他
            content TEXT NOT NULL,             -- 意見內容
            status TEXT CHECK(status IN ('pending','contacted','closed')) NOT NULL DEFAULT 'pending',
            handled_by_staff_id INTEGER REFERENCES staff(id),
            staff_note TEXT,                   -- 後台回覆內容(會員自己看得到)
            handled_at TEXT,
            created_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
        )
    """)

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # 故意不砍表:如果已經有會員送出過意見(customer_feedback有資料),直接砍表
    # 會造成資料遺失。如果真的需要復原,請先確認沒有任何意見資料,再另外手動處理。
    pass
