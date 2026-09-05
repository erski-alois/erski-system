"""coach_certificate_files的category加入promo_photo/id_photo分類,並搬移舊資料

配合「教練團隊照片上傳(宣傳照/證件照)改成可多檔案上傳」這項需求,原本
coach_profiles.promo_photo/coach_profiles.id_photo各只能存一張圖片(單一TEXT欄位),
現在要讓教練/後台可以一次上傳多張宣傳照、多張證件照(例如證件正反面)。

做法:重用既有的coach_certificate_files資料表(原本只給滑雪證照/相關證照/其他證照
三類使用,本來就支援「同一類別可上傳多筆、各自獨立刪除」),把category的CHECK約束
加寬,多開放'promo_photo'(宣傳照)、'id_photo'(證件照)兩個分類,不用另外新增資料表。

同時把coach_profiles裡「舊資料」(教練之前用單張上傳功能存進去的宣傳照/證件照)
搬一份進coach_certificate_files,搬移方式是直接複製一筆(對應分類),coach_profiles
的promo_photo/id_photo欄位本身不刪除、不清空(保留欄位當作備份/回溯用,新版UI之後
不會再寫入這兩個欄位,但既有資料完整保留,不會有任何教練原本上傳的照片憑空消失)。

PostgreSQL的CHECK約束處理方式比照c56e0949c878(transactions付款方式加ATM)那支
migration的做法:先動態查詢pg_constraint找出實際約束名稱、刪除後用固定名稱重建,
不依賴可能因環境而異的預設命名規則。

Revision ID: b7e1c4a9f603
Revises: a4f2e9c7d158
Create Date: 2026-09-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e1c4a9f603'
down_revision: Union[str, Sequence[str], None] = 'a4f2e9c7d158'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_CONSTRAINT_NAME = "coach_certificate_files_category_check"


def _guess_mime(data_url):
    """從data URI字串(例如"data:image/png;base64,....")解析出mime type,
    解析不出來就一律當成image/jpeg(這兩個分類本來就只收圖片)。"""
    if data_url and data_url.startswith("data:") and ";base64," in data_url:
        return data_url.split(";base64,", 1)[0][len("data:"):] or "image/jpeg"
    return "image/jpeg"


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()
    # 把SQL裡的冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),
    # 本機SQLite開發改schema.sql、由init_schema()直接建表,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    # 1) 加寬category的CHECK約束
    cursor.execute(
        """
        SELECT con.conname FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        WHERE rel.relname = 'coach_certificate_files' AND con.contype = 'c'
          AND pg_get_constraintdef(con.oid) LIKE '%category%'
        """
    )
    row = cursor.fetchone()
    if row:
        old_name = row[0]
        cursor.execute(f'ALTER TABLE coach_certificate_files DROP CONSTRAINT "{old_name}"')
    cursor.execute(
        f"""ALTER TABLE coach_certificate_files ADD CONSTRAINT {_NEW_CONSTRAINT_NAME}
            CHECK (category IN ('ski_license','related_license','other_license','promo_photo','id_photo'))"""
    )

    # 2) 把coach_profiles裡舊的單張promo_photo/id_photo搬一份進新table(欄位本身不刪除)
    cursor.execute("SELECT coach_id, promo_photo, id_photo FROM coach_profiles")
    rows = cursor.fetchall()
    for coach_id, promo_photo, id_photo in rows:
        if promo_photo:
            cursor.execute(
                """INSERT INTO coach_certificate_files (coach_id, category, file_name, mime_type, file_data)
                   VALUES (%s, 'promo_photo', %s, %s, %s)""",
                (coach_id, "舊資料轉入-宣傳照", _guess_mime(promo_photo), promo_photo),
            )
        if id_photo:
            cursor.execute(
                """INSERT INTO coach_certificate_files (coach_id, category, file_name, mime_type, file_data)
                   VALUES (%s, 'id_photo', %s, %s, %s)""",
                (coach_id, "舊資料轉入-證件照", _guess_mime(id_photo), id_photo),
            )

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError(
        "這支migration把coach_certificate_files.category加寬並搬移了coach_profiles的舊照片資料,"
        "沒有實作一鍵downgrade(還原CHECK約束前,需要先手動處理/刪除已經用新分類上傳的資料列,"
        "避免違反還原後的約束),需要回復請手動評估。"
    )
