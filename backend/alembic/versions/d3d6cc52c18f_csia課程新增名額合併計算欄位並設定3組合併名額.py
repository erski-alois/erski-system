"""CSIA課程場次新增「名額合併計算」欄位(capacity_group_key)

依你的指示:「第一梯(中文翻譯班含預備課程)」要和「第一梯(中文翻譯班)」合併計算
名額、「第三梯(中文翻譯班含預備課程)」要和「第三梯(中文翻譯班)」合併計算名額、
Level 2(含預備課程/不含預備課程這兩個場次)也要合併計算名額——因為這些其實是
同一批學員分階段上課的同一個班(先上預備課,接著上正式課的人是同一批),不是
兩批獨立的學員各佔8個名額,原本的名額計算方式(每個場次各自獨立算,各自上限8人)
會低估實際報名狀況、導致額滿判斷不準確。

這支migration做兩件事:
1. 新增capacity_group_key欄位(可為NULL,選填——大部分場次,例如第二梯英文班,
   沒有這種分階段上課的情況,維持各自獨立計算,不用填這個欄位)。
2. 依你的指示,把現有6個場次分成3組(用date_label比對,天生冪等):
   - l1_batch1:Jan 8-11(第一梯含預備課程) + Jan 9-11(第一梯)
   - l1_batch3:Jan 15-18(第三梯含預備課程) + Jan 16-18(第三梯)
   - l2_batch1:Jan 20-26(L2第一梯含預備課程) + Jan 21-26(L2第一梯)
   第二梯(英文班,Jan 12-14)不在任何一組,維持獨立計算,不受影響。

實際的「合併計算」邏輯在backend/csia.py的_capacity_group_course_ids()/
_group_registered_count():同一個capacity_group_key底下所有場次的有效報名人數
會加總起來,一起跟max_headcount比較是否額滿,而不是每個場次各自比較。

Revision ID: d3d6cc52c18f
Revises: b8e4f271a935
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3d6cc52c18f'
down_revision: Union[str, Sequence[str], None] = 'b8e4f271a935'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GROUP_BY_DATE_LABEL = (
    ('Jan 8-11', 'l1_batch1'),
    ('Jan 9-11', 'l1_batch1'),
    ('Jan 15-18', 'l1_batch3'),
    ('Jan 16-18', 'l1_batch3'),
    ('Jan 20-26', 'l2_batch1'),
    ('Jan 21-26', 'l2_batch1'),
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('csia_courses') as batch_op:
        batch_op.add_column(sa.Column('capacity_group_key', sa.Text(), nullable=True))

    connection = op.get_bind().connection
    cursor = connection.cursor()
    for date_label, group_key in _GROUP_BY_DATE_LABEL:
        cursor.execute(
            "UPDATE csia_courses SET capacity_group_key=%s WHERE date_label=%s",
            (group_key, date_label),
        )
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('csia_courses') as batch_op:
        batch_op.drop_column('capacity_group_key')
