"""indoor_sessions加入指定教練費收款狀態欄位(designate_fee_collected_at/by_staff_id)

配合後台新增「未收指定教練費」清單功能:包機(室內滑雪charter)會員自選教練時
會加收一筆指定費(indoor_sessions.designate_fee),但這筆錢目前只是記錄金額，
實際收款完全由客服另外用現場付款/匯款等方式跟客戶收，系統裡沒有任何欄位
記錄「這筆錢到底收了沒」，容易漏收。

新增兩個欄位:
1) designate_fee_collected_at:客服實際收到這筆指定費的時間戳記,NULL表示
   還沒收。後台會有一個清單,篩選出designate_fee > 0 且這個欄位是NULL的場次，
   方便客服追蹤。
2) designate_fee_collected_by_staff_id:標記已收款的員工是誰，比照這張表
   本來就有的checked_in_by_staff_id同樣的記錄方式。

這支migration只改資料表結構(加欄位),不影響任何現有資料/功能;新增的兩個
欄位對designate_fee=0(沒有指定教練)的場次沒有意義，維持NULL即可。

Revision ID: f4a2c9e6d813
Revises: b75369f060c3
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a2c9e6d813'
down_revision: Union[str, Sequence[str], None] = 'b75369f060c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('indoor_sessions', sa.Column('designate_fee_collected_at', sa.Text(), nullable=True))
    op.add_column('indoor_sessions', sa.Column('designate_fee_collected_by_staff_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_indoor_sessions_designate_fee_collected_by_staff_id',
        'indoor_sessions', 'staff',
        ['designate_fee_collected_by_staff_id'], ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_indoor_sessions_designate_fee_collected_by_staff_id', 'indoor_sessions', type_='foreignkey')
    op.drop_column('indoor_sessions', 'designate_fee_collected_by_staff_id')
    op.drop_column('indoor_sessions', 'designate_fee_collected_at')
