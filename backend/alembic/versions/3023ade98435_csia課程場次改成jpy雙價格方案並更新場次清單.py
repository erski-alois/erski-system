"""CSIA課程場次改成JPY雙價格方案並更新場次清單

依你最新提供的7個CSIA場次(Level 1五場+Level 2兩場)整批取代原本種子資料的10場,
價格改成CSIA官方的日圓報價,每個場次都有兩種方案:
  - price_jpy_basic:課程本身費用(不含住宿餐食)
  - price_jpy_with_stay:含住宿+早餐+晚餐

原本單一的price欄位(NT$/JPY混用、金額洽詢)拿掉,改成這兩個JPY欄位;前端會員端會
依匯率1:5(1新台幣=5日圓)同時換算顯示新台幣供參考,報名時讓會員從下拉選單選擇其中
一種方案,選擇結果存進csia_registrations新增的price_option欄位,金額快照(amount)
也改存日圓。

注意:你提供的第7個場次(Jan 21-26 Level 2)方案一金額寫的是JPY33000,對照其他場次
兩個方案都落在20~46萬日圓區間、且這個場次自己的方案二是438000,33000明顯偏低、落差
過大,判斷應該是筆誤漏打一個0,這裡先當作330000處理,請務必確認金額是否正確,不對的
話告訴我再另外補一支migration修正。

套用這支migration前已經用Render的唯讀SQL查詢工具確認正式環境csia_registrations目前
是0筆(還沒有任何人報名過CSIA課程),所以可以安全整批清空csia_courses重新灌資料,不會
有報名紀錄的course_id變成孤兒外鍵的風險。

Revision ID: 3023ade98435
Revises: 5e07df42e113
Create Date: 2026-09-20 06:29:16.296894

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '3023ade98435'
down_revision: Union[str, Sequence[str], None] = '5e07df42e113'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 新的7個課程場次:(level, batch_label, language, course_name, format_note, date_label,
# date_sort_key, price_jpy_basic, price_jpy_with_stay)
_NEW_COURSES = [
    ('L1', '第一梯(中文翻譯班)', 'chinese', 'Level 1', '1 Day Pre course + 3 Days course', 'Jan 8-11', '2027-01-08', 225000, 300000),
    ('L1', '第一梯(中文翻譯班)', 'chinese', 'Level 1', '3 Days course', 'Jan 9-11', '2027-01-09', 205000, 265000),
    ('L1', '第二梯(英文班)', 'english', 'Level 1', '3 Days course', 'Jan 12-14', '2027-01-12', 205000, 265000),
    ('L1', '第三梯(中文翻譯班)', 'chinese', 'Level 1', '1 Day Pre course + 3 Days course', 'Jan 15-18', '2027-01-15', 225000, 300000),
    ('L1', '第三梯(中文翻譯班)', 'chinese', 'Level 1', '3 Days course', 'Jan 16-18', '2027-01-16', 205000, 265000),
    ('L2', '第一梯(英文班)', 'english', 'Level 2', '7 Days・1 Day Pre course + 6 Days course', 'Jan 20-26', '2027-01-20', 390000, 456000),
    ('L2', '第一梯(英文班)', 'english', 'Level 2', '6 Days course', 'Jan 21-26', '2027-01-21', 330000, 438000),
]


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()把SQL裡的
    # 冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),本機SQLite
    # 開發改schema.sql、由init_schema()直接建表+灌種子資料,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    # 1. 新增兩個JPY價格欄位、移除舊的單一price欄位。用IF NOT EXISTS/IF EXISTS包起來,
    #    重複套用這支migration也不會出錯。
    cursor.execute("ALTER TABLE csia_courses ADD COLUMN IF NOT EXISTS price_jpy_basic INTEGER")
    cursor.execute("ALTER TABLE csia_courses ADD COLUMN IF NOT EXISTS price_jpy_with_stay INTEGER")
    cursor.execute("ALTER TABLE csia_courses DROP COLUMN IF EXISTS price")

    # 2. csia_registrations新增price_option欄位,記錄會員報名時選的是哪一種價格方案,
    #    並補上CHECK約束(用DO區塊包起來,判斷約束是否已存在,確保重複套用不會出錯)。
    cursor.execute("ALTER TABLE csia_registrations ADD COLUMN IF NOT EXISTS price_option TEXT")
    cursor.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'csia_registrations_price_option_check'
            ) THEN
                ALTER TABLE csia_registrations
                    ADD CONSTRAINT csia_registrations_price_option_check
                    CHECK (price_option IN ('basic','with_stay'));
            END IF;
        END $$;
    """)

    # 3. 整批取代課程場次種子資料。用「是否已經有price_jpy_basic不是NULL的資料列」
    #    當作「這支migration的重灌步驟是否已經執行過」的判斷依據——舊的10筆種子資料
    #    在上面ADD COLUMN之後,price_jpy_basic必然是NULL,只有重灌過的新資料才會有值,
    #    確保重複套用這支migration不會重複清空/重複灌資料。
    cursor.execute("SELECT COUNT(*) FROM csia_courses WHERE price_jpy_basic IS NOT NULL")
    if cursor.fetchone()[0] == 0:
        cursor.execute("DELETE FROM csia_courses")
        for (level, batch_label, language, course_name, format_note,
             date_label, date_sort_key, price_basic, price_with_stay) in _NEW_COURSES:
            cursor.execute(
                """INSERT INTO csia_courses
                   (level, batch_label, language, course_name, format_note, date_label, date_sort_key,
                    price_jpy_basic, price_jpy_with_stay)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (level, batch_label, language, course_name, format_note,
                 date_label, date_sort_key, price_basic, price_with_stay),
            )

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # 故意不做復原處理:這支migration整批取代了課程場次資料,如果已經有人報名新場次,
    # 復原會讓報名資料的course_id/price_option失去對應或變成不合法的值。如果真的需要
    # 復原,請先確認沒有任何新場次的報名資料,再另外手動處理。
    pass
