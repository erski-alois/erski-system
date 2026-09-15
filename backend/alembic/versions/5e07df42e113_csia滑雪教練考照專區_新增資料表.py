"""CSIA滑雪教練考照專區:新增csia_courses/csia_registrations兩張表,
以及CSIA匯款帳號設定(pricing_config的bank_account_csia這個key)

依你的指示,在「高雄滑雪」「日本滑雪」同一層新增一個「CSIA滑雪教練考照專區」,
讓會員可以直接在網站上瀏覽你提供的Level 1/Level 2課程場次、線上填寫CSIA官方
報名流程需要的完整考生資訊(含上傳2026/27 CSIA會員卡)、送出報名;後台則新增
「CSIA報名管理」分頁,可以管理課程場次(新增/編輯價格與名額/確認開班或取消)、
查看報名名單與上傳的會員卡、標記已收到報名費匯款。

這支migration建立兩張新資料表:
  - csia_courses:課程場次(依你提供的內容先灌好10筆Level 1/Level 2場次資料,
    日期依「2026/27雪季」慣例推算為2027年1月;報名費金額你還沒提供,price先留
    NULL,畫面會顯示「金額洽詢」,你之後可以直接在後台「CSIA報名管理」分頁填入
    實際金額,不需要再跑一次migration)。
  - csia_registrations:每一筆報名的完整考生資料(對照CSIA官方報名表格的19項
    欄位,外加已持有證照/滑雪經驗/教學經驗/報考原因/資格確認,以及付款狀態)。

另外在pricing_config新增一筆bank_account_csia(空白匯款帳號,格式比照既有的
bank_account_indoor/bank_account_japan),你之後在後台「價格設定」分頁的
「匯款帳號設定」區塊,就會多一張「CSIA滑雪教練考照報名費」的帳號設定卡片,
填好之後,會員報名CSIA課程、選擇匯款轉帳繳費時,就會看到你填的匯款帳號。

這支migration完全是新增資料表/新增設定值,不會動到任何既有資料表或既有資料。

Revision ID: 5e07df42e113
Revises: ae71bf8cb630
Create Date: 2026-09-15 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '5e07df42e113'
down_revision: Union[str, Sequence[str], None] = 'ae71bf8cb630'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 課程場次種子資料:(level, batch_label, language, course_name, format_note, date_label, date_sort_key)
_SEED_COURSES = [
    ('L1', '第一梯(中文翻譯班)', 'chinese', 'Level 1 Pre course + course', '考前班＋考試', 'Jan 8-11', '2027-01-08'),
    ('L1', '第一梯(中文翻譯班)', 'chinese', 'Level 1 course', '考試', 'Jan 9-11', '2027-01-09'),
    ('L1', '第二梯(英文班)', 'english', 'Level 1', None, 'Jan 12-14', '2027-01-12'),
    ('L1', '第三梯(中文翻譯班)', 'chinese', 'Level 1 Pre course + course', '考前班＋考試', 'Jan 15-18', '2027-01-15'),
    ('L1', '第三梯(中文翻譯班)', 'chinese', 'Level 1', '考試', 'Jan 16-18', '2027-01-16'),
    ('L2', '第一梯(英文班)', 'english', 'Level 2 Pre course + Course', '考前班＋滑行課程＋教學課程＋考試', 'Jan 20-26', '2027-01-20'),
    ('L2', '第一梯(英文班)', 'english', 'Level 2 Ski + Tech + Exam', '滑行課程＋教學課程＋考試', 'Jan 21-26', '2027-01-21'),
    ('L2', '第一梯(英文班)', 'english', 'Level 2 Ski + Exam', '滑行課程＋考試', 'Jan 21-22, 25-26', '2027-01-21'),
    ('L2', '第一梯(英文班)', 'english', 'Level 2 Teach + Exam', '教學課程考試＋教學考試', 'Jan 23-26', '2027-01-23'),
    ('L2', '第一梯(英文班)', 'english', 'Level 2 Exam', None, 'Jan 25-26', '2027-01-25'),
]


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()把SQL裡的
    # 冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),本機SQLite
    # 開發改schema.sql、由init_schema()直接建表+灌種子資料,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS csia_courses (
            id SERIAL PRIMARY KEY,
            level TEXT CHECK(level IN ('L1','L2')) NOT NULL,
            batch_label TEXT NOT NULL,
            language TEXT CHECK(language IN ('chinese','english')) NOT NULL,
            course_name TEXT NOT NULL,
            format_note TEXT,
            date_label TEXT NOT NULL,
            date_sort_key TEXT,
            venue TEXT DEFAULT '宮城鬼首滑雪場 Onikoube, Miyagi',
            price INTEGER,
            min_headcount INTEGER NOT NULL DEFAULT 5,
            max_headcount INTEGER NOT NULL DEFAULT 8,
            status TEXT CHECK(status IN ('open','confirmed','cancelled','closed')) NOT NULL DEFAULT 'open',
            notes TEXT,
            created_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
            updated_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS csia_registrations (
            id SERIAL PRIMARY KEY,
            member_id INTEGER NOT NULL REFERENCES members(id),
            course_id INTEGER NOT NULL REFERENCES csia_courses(id),
            waiver_confirmed INTEGER NOT NULL DEFAULT 0,
            membership_action_confirmed INTEGER NOT NULL DEFAULT 0,
            membership_card_file_name TEXT,
            membership_card_mime_type TEXT,
            membership_card_image TEXT,
            designation TEXT,
            chinese_name TEXT NOT NULL,
            kanji_or_other_name TEXT,
            examiner_call_name TEXT,
            birth_date TEXT,
            gender TEXT CHECK(gender IN ('male','female','other')),
            address_chinese TEXT,
            address_street TEXT,
            address_city TEXT,
            address_country TEXT,
            address_province TEXT,
            address_postal_code TEXT,
            address_other TEXT,
            mobile_number TEXT,
            email TEXT,
            line_or_whatsapp_id TEXT,
            csia_member_number TEXT,
            occupation TEXT,
            emergency_contact_name TEXT,
            emergency_contact_phone TEXT,
            existing_certifications TEXT,
            ski_experience TEXT,
            teaching_experience TEXT,
            reasons TEXT,
            reason_other TEXT,
            eligibility_confirmed INTEGER NOT NULL DEFAULT 0,
            amount INTEGER,
            payment_status TEXT CHECK(payment_status IN ('unpaid','paid','refunded')) NOT NULL DEFAULT 'unpaid',
            paid_at TEXT,
            status TEXT CHECK(status IN ('submitted','confirmed','cancelled')) NOT NULL DEFAULT 'submitted',
            staff_note TEXT,
            created_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
        )
    """)

    # 種子資料:課程場次(用date_label+course_name當作「是不是已經灌過」的判斷依據,
    # 避免重複執行這支migration時重複灌出好幾份一樣的課程)
    cursor.execute("SELECT COUNT(*) FROM csia_courses")
    if cursor.fetchone()[0] == 0:
        for level, batch_label, language, course_name, format_note, date_label, date_sort_key in _SEED_COURSES:
            cursor.execute(
                """INSERT INTO csia_courses
                   (level, batch_label, language, course_name, format_note, date_label, date_sort_key)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (level, batch_label, language, course_name, format_note, date_label, date_sort_key),
            )

    # 種子資料:CSIA匯款帳號設定(空白,格式比照既有的bank_account_indoor/bank_account_japan)
    cursor.execute("SELECT COUNT(*) FROM pricing_config WHERE config_key='bank_account_csia'")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            """INSERT INTO pricing_config (config_key, config_value, label) VALUES (%s, %s, %s)""",
            (
                'bank_account_csia',
                '{"bank_name":"","bank_code":"","account_number":"","account_name":"","note":""}',
                '匯款帳號(CSIA滑雪教練考照報名費,匯款轉帳付款時顯示給客戶)',
            ),
        )

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # 故意不做刪表處理:如果已經有人報名(csia_registrations有資料),直接砍表會
    # 造成資料遺失。如果真的需要復原,請先確認沒有任何報名資料,再另外手動處理。
    pass
