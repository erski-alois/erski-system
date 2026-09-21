"""新增staff_notifications資料表(後台員工通知,跟會員自己看的notifications分開)

起因:「學員購買課程後,後台完全沒有任何提醒通知」——之前系統完全沒有任何
staff/admin端的提醒機制,員工要知道有新訂單只能自己去後台各個分頁翻查。

這次新增一張全體員工共用的通知清單(不是每個員工各自一份已讀狀態的設計,
小團隊共用一份提醒清單就夠用),目前只在app.py的_log_purchase_notification
(學員完成購買/付款的統一入口)寫入一筆,後台新增通知鈴鐺UI可以查看/標記已讀。

這支migration只新增一張表,不影響任何現有資料表/資料。

Revision ID: a1c7f2b940de
Revises: f4a2c9e6d813
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1c7f2b940de'
down_revision: Union[str, Sequence[str], None] = 'f4a2c9e6d813'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他新增資料表的migration一樣(例如customer_feedback那支),直接拿底層DBAPI連線
    # 執行(避免SQLAlchemy的text()把SQL裡的冒號誤判成具名綁定參數)。這支migration
    # 只支援PostgreSQL(正式環境),本機SQLite開發改schema.sql、由init_schema()直接
    # 建表,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS staff_notifications (
            id SERIAL PRIMARY KEY,
            category TEXT NOT NULL DEFAULT 'purchase',
            message TEXT NOT NULL,
            member_id INTEGER REFERENCES members(id),
            order_id INTEGER,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
        )
    """)

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute("DROP TABLE IF EXISTS staff_notifications")
    connection.commit()
