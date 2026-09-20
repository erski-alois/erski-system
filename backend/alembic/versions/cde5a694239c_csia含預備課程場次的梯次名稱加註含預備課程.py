"""CSIA含預備課程場次的梯次名稱加註含預備課程

依你的指示,7個場次裡有3個(Jan 8-11、Jan 15-18、Jan 20-26)的課程內容包含
「1 Day Pre course」(預備課程),但原本的梯次名稱(batch_label)跟同一語言/
同一Level的其他場次沒有區別,例如Jan 8-11(有預備課程)跟Jan 9-11(沒有預備
課程)的梯次名稱都是「第一梯(中文翻譯班)」,會員在報名下拉選單上沒辦法直接
分辨哪個場次包含預備課程。這支migration把這3個場次的梯次名稱改成:
  - Jan 8-11:第一梯(中文翻譯班) -> 第一梯(中文翻譯班含預備課程)
  - Jan 15-18:第三梯(中文翻譯班) -> 第三梯(中文翻譯班含預備課程)
  - Jan 20-26:第一梯(英文班) -> 第一梯(英文班含預備課程)

用format_note欄位裡有沒有「Pre course」字樣來判斷是不是含預備課程的場次(這
3個場次的format_note分別是'1 Day Pre course + 3 Days course'跟'7 Days・
1 Day Pre course + 6 Days course'),不是用日期或id這種寫死的方式比對,避免
未來場次資料異動時比對失準。只改梯次名稱文字,不動任何其他欄位(價格/人數/
狀態/報名資料都不受影響)。

Revision ID: cde5a694239c
Revises: 3023ade98435
Create Date: 2026-09-20 06:54:16.664135

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'cde5a694239c'
down_revision: Union[str, Sequence[str], None] = '3023ade98435'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他CSIA migration一樣,直接拿底層DBAPI連線執行,避免SQLAlchemy的text()把SQL
    # 裡的冒號誤判成具名綁定參數。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    # WHERE子句本身就是天然的重複套用防呆:已經改過的場次batch_label會含有
    # 「含預備課程」字樣,NOT LIKE條件會讓這些場次不再被UPDATE命中,不會重複
    # 疊加文字(例如變成「...含預備課程含預備課程)」)。
    cursor.execute("""
        UPDATE csia_courses
        SET batch_label = REPLACE(batch_label, ')', '含預備課程)')
        WHERE format_note LIKE '%Pre course%'
          AND batch_label NOT LIKE '%含預備課程%'
    """)

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute("""
        UPDATE csia_courses
        SET batch_label = REPLACE(batch_label, '含預備課程)', ')')
        WHERE format_note LIKE '%Pre course%'
          AND batch_label LIKE '%含預備課程%'
    """)
    connection.commit()
