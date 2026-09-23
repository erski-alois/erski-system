"""更正CSIA Jan21-26場次住宿晚數為6晚

上一支migration(f6a3d1e8c027)把「L2第一梯(英文班)・6 Days course」(Jan 21-26)
這筆場次的nights_of_stay填成4晚,這是筆誤——你確認正確的住宿晚數是6晚,這次更正。

用date_label='Jan 21-26'比對(這個date_label在csia_courses裡是唯一值),天生
冪等,重複套用結果不變。

Revision ID: b8e4f271a935
Revises: f6a3d1e8c027
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b8e4f271a935'
down_revision: Union[str, Sequence[str], None] = 'f6a3d1e8c027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE csia_courses SET nights_of_stay=%s WHERE date_label=%s",
        (6, 'Jan 21-26'),
    )
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE csia_courses SET nights_of_stay=%s WHERE date_label=%s",
        (4, 'Jan 21-26'),
    )
    connection.commit()
