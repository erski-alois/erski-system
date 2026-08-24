"""教練自助後台擴充:新增聯絡資訊/滑行資料/三則短介紹欄位、證照檔案上傳資料表

配合「教練登入後可自行編輯更多個人資料、瀏覽自己的薪資與完整上課歷史」這項需求:

1. staff新增暱稱/email/LINE/IG/FB五個聯絡資訊欄位(純資訊用途,不影響登入,
   跟members.email/line_user_id那種拿來做OAuth登入識別的欄位不同,這裡沒有UNIQUE限制)。
2. coach_profiles新增滑行項目/滑行專長/雪齡/其他相關經歷,以及三個新的短文字欄位
   (自我介紹/給學員一句話/代表教練一句話,前端各自限制30字)。原本的self_intro欄位
   (舊版「自我介紹/給學員的一句話」合併欄位)照使用者指示保留不動、不搬移資料,
   純粹當作歷史資料繼續顯示,新的三個欄位一開始都是空的、教練登入後自行填寫。
3. 新增coach_certificate_files資料表,存放教練上傳的「滑雪證照/相關證照/其他證照」
   檔案(每一類都可以上傳多筆,圖片或PDF都收,做法比照現有promo_photo/id_photo,
   把檔案內容直接以base64存進TEXT欄位,不用額外接外部檔案儲存服務)。

Revision ID: 9a89c72d2c49
Revises: 012f894f8407
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a89c72d2c49'
down_revision: Union[str, Sequence[str], None] = '012f894f8407'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_STATEMENTS = [
    "ALTER TABLE staff ADD COLUMN nickname TEXT",
    "ALTER TABLE staff ADD COLUMN email TEXT",
    "ALTER TABLE staff ADD COLUMN line_id TEXT",
    "ALTER TABLE staff ADD COLUMN instagram TEXT",
    "ALTER TABLE staff ADD COLUMN facebook TEXT",
    "ALTER TABLE coach_profiles ADD COLUMN discipline TEXT",
    "ALTER TABLE coach_profiles ADD COLUMN specialty TEXT",
    "ALTER TABLE coach_profiles ADD COLUMN snow_years INTEGER",
    "ALTER TABLE coach_profiles ADD COLUMN other_experience TEXT",
    "ALTER TABLE coach_profiles ADD COLUMN bio_intro TEXT",
    "ALTER TABLE coach_profiles ADD COLUMN message_to_students TEXT",
    "ALTER TABLE coach_profiles ADD COLUMN coach_motto TEXT",
    """CREATE TABLE coach_certificate_files (
        id SERIAL PRIMARY KEY,
        coach_id INTEGER NOT NULL REFERENCES staff(id),
        category TEXT NOT NULL CHECK(category IN ('ski_license','related_license','other_license')),
        file_name TEXT,
        mime_type TEXT,
        file_data TEXT NOT NULL,
        uploaded_at TEXT DEFAULT (to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
    )""",
]


def upgrade() -> None:
    """Upgrade schema."""
    # 跟前面幾支migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的
    # text()把SQL裡的冒號誤判成具名綁定參數)。這支migration只支援
    # PostgreSQL(正式環境),本機SQLite開發改schema.sql、由init_schema()
    # 直接建表,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()
    for stmt in _UPGRADE_STATEMENTS:
        cursor.execute(stmt)
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError(
        "這支migration新增的是教練自助後台的個人資料欄位與證照上傳資料表,"
        "沒有實作一鍵downgrade(避免正式環境誤操作把教練已填寫的資料/已上傳的證照砍掉)。"
        "需要回復請手動評估。"
    )
