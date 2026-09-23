"""CSIA Jan16-18場次含住宿價格更正為257000

依你最新指示:「第三梯(中文翻譯班)・Level 1(3 Days course)」(Jan 16-18)這筆場次的
「含住宿+早餐+晚餐」金額要從JPY 262,000改成JPY 257,000(課程本身JPY 200,000維持不變)。

這個262000是上一支migration(0a7dca1b851d)當初依你那時提供的價格特意設成跟其他場次
不同的金額,不是打錯字帶進來的——這次單純是你要更正金額,不是修bug。改完之後這個
Jan16-18場次的價格會跟同樣是「3 Days course」的Jan9-11(第一梯)、Jan12-14(第二梯)
兩個場次一致(都是200000/257000)。

套用前已經用Render唯讀SQL查詢工具確認正式環境csia_registrations目前0筆(還沒有人
報名過CSIA),所以更新這個場次的價格不會影響任何已送出報名的金額快照(報名金額是
報名當下寫進csia_registrations.amount的快照值,不會因為之後場次價格異動而改變,
延續既有設計)。

Revision ID: 3e2b537bca1e
Revises: 84f5beee3f57
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '3e2b537bca1e'
down_revision: Union[str, Sequence[str], None] = '84f5beee3f57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他CSIA價格migration一樣,直接拿底層DBAPI連線執行,避免SQLAlchemy的text()把
    # SQL裡的冒號誤判成具名綁定參數。用date_label='Jan 16-18'比對(這個date_label在
    # csia_courses裡是唯一值),天生冪等,重複套用結果不變。
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE csia_courses SET price_jpy_with_stay=%s WHERE date_label=%s AND batch_label=%s",
        (257000, 'Jan 16-18', '第三梯(中文翻譯班)'),
    )
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE csia_courses SET price_jpy_with_stay=%s WHERE date_label=%s AND batch_label=%s",
        (262000, 'Jan 16-18', '第三梯(中文翻譯班)'),
    )
    connection.commit()
