"""attendance_codes上課碼下課碼

新增功能:客戶訂日本教練課完成付款確認後,系統自動產生8碼亂數的上課碼/下課碼,
供教練頁面輸入學員提供的編碼以完成報到管理(半天課程1組;全天課程上午/下午各1組;
多天課程則每天各自產生對應組數)。詳細規則見 backend/booking.py 的
_create_japan_attendance_codes 與 verify_attendance_code。

這支migration只新增一張全新的資料表,不影響任何既有資料表/資料。

Revision ID: a4f2e9c7d158
Revises: c56e0949c878
Create Date: 2026-09-05 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4f2e9c7d158'
down_revision: Union[str, Sequence[str], None] = 'c56e0949c878'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS attendance_codes (
    id SERIAL PRIMARY KEY,
    ref_type TEXT CHECK(ref_type IN ('japan_booking')) NOT NULL,
    ref_id INTEGER NOT NULL,
    session_date TEXT NOT NULL,
    session_slot TEXT CHECK(session_slot IN ('morning','afternoon')) NOT NULL,
    checkin_code TEXT NOT NULL,
    checkout_code TEXT NOT NULL,
    checkin_used_at TEXT,
    checkin_verified_by_staff_id INTEGER REFERENCES staff(id),
    checkout_used_at TEXT,
    checkout_verified_by_staff_id INTEGER REFERENCES staff(id),
    created_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
    UNIQUE(ref_type, ref_id, session_slot)
)
"""

_CREATE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_attendance_codes_ref "
    "ON attendance_codes(ref_type, ref_id)"
)


def upgrade() -> None:
    """Upgrade schema."""
    # 比照本專案其他migration的慣例,直接拿底層DBAPI連線執行(op.execute的text()
    # 會誤判SQL裡的冒號,詳見baseline migration的說明)。這支migration只需要在
    # PostgreSQL(正式環境)上執行;本機SQLite開發環境是直接由schema.sql +
    # db.init_db()建表,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute(_CREATE_TABLE_SQL)
    cursor.execute(_CREATE_INDEX_SQL)
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute("DROP TABLE IF EXISTS attendance_codes")
    connection.commit()
