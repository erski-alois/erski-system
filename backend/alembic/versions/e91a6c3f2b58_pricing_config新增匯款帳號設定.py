"""pricing_config新增匯款帳號設定(bank_account_indoor/bank_account_japan)

配合「後台新增一個設定匯款帳號的地方,並分開設定室內雪機及日本滑雪的匯款帳號」
這項需求,複用既有的pricing_config資料表(不用另外新增資料表,做法比照這張表
既有的其他設定項目,例如japan_full_day_price),新增兩筆設定:

- bank_account_indoor:室內雪機/包機/體驗課/跳台體驗/團課,選擇「匯款轉帳」
  付款時顯示給客戶的匯款帳號。
- bank_account_japan:日本教練課專用的匯款帳號,跟室內雪機的分開設定
  (因為日本教練課金額較大、經手單位可能不同,分開設定方便對帳)。

兩筆的預設值都是空字串(銀行名稱/代碼/帳號/戶名/備註都還沒填),上線後
請主管到後台「價格設定」分頁裡新增的「匯款帳號設定」表單填寫實際的匯款帳戶
資訊,不需要再跑一次migration。

用INSERT ... ON CONFLICT DO NOTHING(不是直接INSERT)是為了保險:如果這支
migration意外被重複執行、或這兩個key因為某些原因已經存在,也不會因為
config_key的UNIQUE約束而讓整支migration失敗。

Revision ID: e91a6c3f2b58
Revises: b7e1c4a9f603
Create Date: 2026-09-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e91a6c3f2b58'
down_revision: Union[str, Sequence[str], None] = 'b7e1c4a9f603'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DEFAULT_ACCOUNT_JSON = '{"bank_name":"","bank_code":"","account_number":"","account_name":"","note":""}'

_UPGRADE_STATEMENTS = [
    (
        "INSERT INTO pricing_config (config_key, config_value, label) VALUES "
        "('bank_account_indoor', %s, '匯款帳號(室內雪機/包機/體驗課/跳台體驗/團課,匯款轉帳付款時顯示給客戶)') "
        "ON CONFLICT (config_key) DO NOTHING",
        (_DEFAULT_ACCOUNT_JSON,),
    ),
    (
        "INSERT INTO pricing_config (config_key, config_value, label) VALUES "
        "('bank_account_japan', %s, '匯款帳號(日本教練課,匯款轉帳付款時顯示給客戶)') "
        "ON CONFLICT (config_key) DO NOTHING",
        (_DEFAULT_ACCOUNT_JSON,),
    ),
]


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()
    # 把SQL裡的冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),
    # 本機SQLite開發改schema.sql、由init_schema()直接建表+灌種子資料,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()
    for stmt, params in _UPGRADE_STATEMENTS:
        cursor.execute(stmt, params)
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute("DELETE FROM pricing_config WHERE config_key IN ('bank_account_indoor', 'bank_account_japan')")
    connection.commit()
