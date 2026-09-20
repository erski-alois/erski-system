"""CSIA 7個場次價格更新

依你最新提供的7個場次價格更新資料(對照六十節灌進去的原始價格,這次的異動是):
  - Jan 8-11 :含住宿300000 -> 301000(課程本身225000不變)
  - Jan 9-11 :課程本身205000 -> 200000,含住宿265000 -> 257000
  - Jan 12-14:課程本身205000 -> 200000,含住宿265000 -> 257000
  - Jan 15-18:含住宿300000 -> 301000(課程本身225000不變)
  - Jan 16-18:課程本身205000 -> 200000,含住宿265000 -> 262000
  - Jan 20-26:課程本身390000 -> 370000,含住宿456000 -> 496000
  - Jan 21-26:330000 / 438000,跟六十節先前的判斷(當初33000疑似筆誤,當作330000處理)
    一致,這次你直接給的金額也是330000,等於確認了那個判斷是對的,這筆沒有異動。

套用這支migration前已經用Render的唯讀SQL查詢工具確認正式環境csia_registrations還是
0筆(還沒有人報名過CSIA),所以直接更新價格不會影響任何已送出報名的金額快照(已送出的
報名金額是報名當下寫進csia_registrations.amount的快照值,本來就不會因為之後場次價格
異動而改變,這是延續五十九節「後端算金額、不信任前端」設計的既有行為)。

Revision ID: 0a7dca1b851d
Revises: cde5a694239c
Create Date: 2026-09-20 07:05:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0a7dca1b851d'
down_revision: Union[str, Sequence[str], None] = 'cde5a694239c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 新價格:(date_label, price_jpy_basic, price_jpy_with_stay)。7個場次的date_label都是
# 唯一值,用它當比對依據(跟cde5a694239c那支migration判斷「哪些場次含預備課程」時用
# format_note比對是同一套邏輯:用場次本身有辨識度的欄位比對,不用寫死id)。
_NEW_PRICES = [
    ('Jan 8-11', 225000, 301000),
    ('Jan 9-11', 200000, 257000),
    ('Jan 12-14', 200000, 257000),
    ('Jan 15-18', 225000, 301000),
    ('Jan 16-18', 200000, 262000),
    ('Jan 20-26', 370000, 496000),
    ('Jan 21-26', 330000, 438000),
]

# upgrade前的舊價格,downgrade用來還原(跟六十節灌進去的種子資料金額一致)。
_OLD_PRICES = [
    ('Jan 8-11', 225000, 300000),
    ('Jan 9-11', 205000, 265000),
    ('Jan 12-14', 205000, 265000),
    ('Jan 15-18', 225000, 300000),
    ('Jan 16-18', 205000, 265000),
    ('Jan 20-26', 390000, 456000),
    ('Jan 21-26', 330000, 438000),
]


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他CSIA migration一樣,直接拿底層DBAPI連線執行,避免SQLAlchemy的text()把SQL
    # 裡的冒號誤判成具名綁定參數。這支migration單純更新價格兩個欄位,對同一個date_label
    # 重複套用結果不變,天生冪等,不需要額外的「是否已套用過」判斷。
    connection = op.get_bind().connection
    cursor = connection.cursor()
    for date_label, price_basic, price_with_stay in _NEW_PRICES:
        cursor.execute(
            "UPDATE csia_courses SET price_jpy_basic=%s, price_jpy_with_stay=%s WHERE date_label=%s",
            (price_basic, price_with_stay, date_label),
        )
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    connection = op.get_bind().connection
    cursor = connection.cursor()
    for date_label, price_basic, price_with_stay in _OLD_PRICES:
        cursor.execute(
            "UPDATE csia_courses SET price_jpy_basic=%s, price_jpy_with_stay=%s WHERE date_label=%s",
            (price_basic, price_with_stay, date_label),
        )
    connection.commit()
