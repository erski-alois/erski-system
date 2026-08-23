"""orders 退款雙重核准欄位

退款金額達NT$5,000以上時,需要「另一位主管或老闆」二次核准才會真的執行退款
(送出申請的人不能自己核准),對應規則書的雙重核准要求。詳見
README_部署交接指南.md。

Revision ID: 6dd56acf62a5
Revises: 25e295d8f420
Create Date: 2026-08-23 09:21:42.218950

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6dd56acf62a5'
down_revision: Union[str, Sequence[str], None] = '25e295d8f420'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATEMENTS = [
    "ALTER TABLE orders ADD COLUMN pending_refund_amount INTEGER",
    "ALTER TABLE orders ADD COLUMN pending_refund_reason TEXT",
    "ALTER TABLE orders ADD COLUMN pending_refund_requested_by INTEGER REFERENCES staff(id)",
    "ALTER TABLE orders ADD COLUMN pending_refund_requested_at TEXT",
]


def upgrade() -> None:
    """Upgrade schema."""
    # 跟baseline migration一樣直接拿底層DBAPI連線執行,不用op.execute()
    # (avoid SQLAlchemy text()把SQL裡的冒號誤判成具名綁定參數;這幾句雖然
    # 沒有冒號,但保持同一個寫法方便以後維護)。
    connection = op.get_bind().connection
    cursor = connection.cursor()
    for stmt in _STATEMENTS:
        cursor.execute(stmt)
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError(
        "這支migration新增的是退款雙重核准欄位,沒有實作一鍵downgrade(避免"
        "正式環境誤操作把有審核紀錄的欄位砍掉)。需要回復請手動評估。"
    )
