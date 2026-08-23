"""baseline schema — 對應 schema_postgres.sql 的完整初版schema(41張表+種子資料)

這支migration取代原本「每次啟動都執行db.py重建schema」的作法。日後要
改資料表結構，不要回頭改這個檔案，而是用 `alembic revision -m "說明"`
新增下一支migration，在裡面用 op.execute("ALTER TABLE ...") 寫要改的
內容，並且要同步手動更新 backend/schema.sql 與 backend/schema_postgres.sql
這兩份「目前最新結構長怎樣」的參考文件(這兩份不是migration本身，只是
方便新環境/新開發者一眼看到目前完整結構，實際套用結構變更一律靠
migration，不要再靠整份重跑schema.sql)。

Revision ID: 25e295d8f420
Revises:
Create Date: 2026-08-23 07:36:39.161611

"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '25e295d8f420'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA_SQL_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "schema_postgres.sql")


def upgrade() -> None:
    with open(_SCHEMA_SQL_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    # 不用 op.execute(schema_sql):Alembic的op.execute會把字串包成SQLAlchemy
    # 的text()執行,text()會把SQL裡任何「冒號後面接文字/數字」的地方(例如
    # pricing_config種子資料裡的JSON字串 {"1":1500,...})誤判成具名綁定參數
    # (:1500)而報錯。改成直接拿底層DBAPI連線(psycopg2)執行,就不會有這個
    # 誤判 — psycopg2只認%s/%(name)s這種參數格式,不會誤解JSON裡的冒號。
    connection = op.get_bind()
    raw_cursor = connection.connection.cursor()
    raw_cursor.execute(schema_sql)
    raw_cursor.close()


def downgrade() -> None:
    # 這是最初版schema，往下降版本代表整套系統資料表都要砍掉，
    # 正式環境不應該真的執行這個，這裡刻意留空、不提供一鍵砍表的功能，
    # 需要復原請改用資料庫層級的備份還原。
    raise NotImplementedError(
        "baseline schema不提供downgrade(避免正式環境誤觸整套刪表)，"
        "需要復原請使用資料庫的備份/還原機制。"
    )
