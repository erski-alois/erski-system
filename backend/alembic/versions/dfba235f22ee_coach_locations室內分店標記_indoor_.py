"""coach_locations室內分店標記_indoor_sessions指定費_charter_pass_requests

這支migration支援三項新功能:
1. 室內滑雪(包機)比照日本滑雪,開放會員在前台自選教練(coach_location_options
   新增is_indoor_branch欄位標記哪些駐在地選項屬於室內分店,預設把既有的
   「高雄」選項標記為室內分店;教練指派後台已經有「教練駐在地」勾選介面,
   不用再改)。
2. 選擇教練後可能加收指定費,先把費率設定加進pricing_config(預設NT$500,
   後台可調整),並在indoor_sessions加一個designate_fee欄位記錄實際金額
   (這次先只記錄,不接自動收款,收費由客服後台依紀錄手動處理)。
3. 會員可以對已購買的包機堂數包送出「取消」或「換堂數包大小」申請,退不退
   款、換多少都由客服後台審核決定,新增charter_pass_requests表存放這些
   申請紀錄。

Revision ID: dfba235f22ee
Revises: 6dd56acf62a5
Create Date: 2026-08-23 11:28:04.276265

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dfba235f22ee'
down_revision: Union[str, Sequence[str], None] = '6dd56acf62a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_STATEMENTS = [
    "ALTER TABLE coach_location_options ADD COLUMN is_indoor_branch BOOLEAN NOT NULL DEFAULT FALSE",
    "UPDATE coach_location_options SET is_indoor_branch = TRUE WHERE name = '高雄'",
    "ALTER TABLE indoor_sessions ADD COLUMN designate_fee INTEGER NOT NULL DEFAULT 0",
    """INSERT INTO pricing_config (config_key, config_value, label)
       VALUES ('charter_coach_designate_fee', '500', '室內滑雪包機指定教練加收費用')
       ON CONFLICT (config_key) DO NOTHING""",
    """CREATE TABLE charter_pass_requests (
        id SERIAL PRIMARY KEY,
        charter_pass_id INTEGER NOT NULL REFERENCES charter_passes(id),
        member_id INTEGER NOT NULL REFERENCES members(id),
        request_type TEXT NOT NULL CHECK(request_type IN ('cancel','resize')),
        requested_package_size INTEGER,
        note TEXT,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
        handled_by_staff_id INTEGER REFERENCES staff(id),
        handled_at TEXT,
        created_at TEXT DEFAULT (to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
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
        "這支migration新增的是教練室內分店標記/指定教練費用/包機堂數包申請功能,"
        "沒有實作一鍵downgrade(避免正式環境誤操作把已有申請紀錄的資料表砍掉)。"
        "需要回復請手動評估。"
    )
