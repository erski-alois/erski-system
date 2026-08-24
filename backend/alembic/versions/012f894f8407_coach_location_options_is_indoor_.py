"""coach_location_options_is_indoor_branch改回integer

上一支migration(5b50ca4c851f的前一支dfba235f22ee)把is_indoor_branch欄位建成了
PostgreSQL的BOOLEAN型別，跟這個專案其他所有布林狀態欄位的慣例(一律用INTEGER存0/1，
讓SQLite/PostgreSQL的0/1語意完全一致，見schema_postgres.sql開頭註明)不一致——而
app.py/booking.py的程式碼(WHERE lo.is_indoor_branch = 1、INSERT時傳1/0)本來就是照
INTEGER的語意寫的，沒有配合改成PostgreSQL布林值的true/false寫法。這個型別不一致會讓
`WHERE lo.is_indoor_branch = 1`這種查詢在PostgreSQL上直接報型別錯誤(operator does
not exist: boolean = integer)，導致包機預約頁「指定教練」下拉選單那支API
(/api/indoor-coaches)壞掉。

這支migration把這個欄位改回INTEGER，讓它跟其他欄位、跟程式碼原本的寫法一致。

Revision ID: 012f894f8407
Revises: 5b50ca4c851f
Create Date: 2026-08-24 03:47:37.842891

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '012f894f8407'
down_revision: Union[str, Sequence[str], None] = '5b50ca4c851f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_STATEMENTS = [
    "ALTER TABLE coach_location_options ALTER COLUMN is_indoor_branch DROP DEFAULT",
    "ALTER TABLE coach_location_options ALTER COLUMN is_indoor_branch TYPE INTEGER USING is_indoor_branch::int",
    "ALTER TABLE coach_location_options ALTER COLUMN is_indoor_branch SET DEFAULT 0",
]


def upgrade() -> None:
    """Upgrade schema."""
    # 跟前面幾支migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的
    # text()把SQL裡的冒號誤判成具名綁定參數)。這支migration只支援
    # PostgreSQL(正式環境),本機SQLite開發改schema.sql、由init_schema()
    # 直接建表,不會走這支migration(SQLite本來就沒有真正的BOOLEAN型別，
    # 不會有這個問題)。
    connection = op.get_bind().connection
    cursor = connection.cursor()
    for stmt in _UPGRADE_STATEMENTS:
        cursor.execute(stmt)
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError(
        "這支migration把is_indoor_branch欄位型別從BOOLEAN改回INTEGER，"
        "沒有實作一鍵downgrade。需要回復請手動評估。"
    )
