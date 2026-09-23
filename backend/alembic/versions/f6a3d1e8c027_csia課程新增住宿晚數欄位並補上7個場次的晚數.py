"""CSIA課程新增住宿晚數欄位,並補上7個場次的晚數

依你提供的最新課程場次內容,每個場次都額外標明了「含住宿+早餐+晚餐」方案實際包含
的住宿晚數(例如Jan8-11是含4晚、Jan9-11是含3晚),但csia_courses資料表原本完全沒有
存這個資訊,前台/後台畫面也只會顯示「含住宿+早餐+晚餐」,不會列出晚數。

這支migration做兩件事:
1. 新增nights_of_stay欄位(可為NULL,選填——不是每個場次都一定要標明晚數)。
2. 依你提供的內容,把7個既有場次的晚數補上:
   - Jan 8-11 (第一梯・含預備課程)  4晚
   - Jan 9-11 (第一梯)              3晚
   - Jan 12-14(第二梯・英文班)      3晚(你原文這筆漏打數字,已跟你確認是3晚,
                                          跟同樣是3 Days course的其他場次一致)
   - Jan 15-18(第三梯・含預備課程)  4晚
   - Jan 16-18(第三梯)              3晚
   - Jan 20-26(L2第一梯・含預備課程) 7晚
   - Jan 21-26(L2第一梯)            4晚

用date_label比對(這個欄位在csia_courses裡目前每筆都不同,足夠拿來對應到正確的
場次列)。天生冪等:重複套用只是把同樣的晚數再寫一次,不會出錯。

Revision ID: f6a3d1e8c027
Revises: d3f7a2c58b91
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a3d1e8c027'
down_revision: Union[str, Sequence[str], None] = 'd3f7a2c58b91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NIGHTS_BY_DATE_LABEL = (
    ('Jan 8-11', 4),
    ('Jan 9-11', 3),
    ('Jan 12-14', 3),
    ('Jan 15-18', 4),
    ('Jan 16-18', 3),
    ('Jan 20-26', 7),
    ('Jan 21-26', 4),
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('csia_courses') as batch_op:
        batch_op.add_column(sa.Column('nights_of_stay', sa.Integer(), nullable=True))

    connection = op.get_bind().connection
    cursor = connection.cursor()
    for date_label, nights in _NIGHTS_BY_DATE_LABEL:
        cursor.execute(
            "UPDATE csia_courses SET nights_of_stay=%s WHERE date_label=%s",
            (nights, date_label),
        )
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('csia_courses') as batch_op:
        batch_op.drop_column('nights_of_stay')
