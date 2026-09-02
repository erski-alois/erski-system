"""transactions新增綠界(ECPay)金流回調需要的欄位

配合正式串接綠界「全方位金流」(信用卡/網路ATM/ATM櫃員機):
1. ecpay_trade_no:綠界那邊自己的交易編號(TradeNo,ReturnURL回調會帶,跟我們自己
   產生的MerchantTradeNo(存在既有的provider_ref欄位)是不同的兩組編號,對帳/客服
   查詢時可能都需要用到,分開存)。
2. atm_bank_code / atm_virtual_account / atm_expire_date:選擇「ATM櫃員機」付款時,
   綠界會另外呼叫PaymentInfoURL回傳一組虛擬帳號銀行代碼/帳號/繳費期限,要存起來
   才能顯示在會員的「未付款項目」讓客戶知道要匯到哪裡、什麼時候之前要匯完。
   信用卡/網路ATM付款不會用到這三欄,允許NULL。

Revision ID: 3f3154aeb343
Revises: 9a89c72d2c49
Create Date: 2026-08-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f3154aeb343'
down_revision: Union[str, Sequence[str], None] = '9a89c72d2c49'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_STATEMENTS = [
    "ALTER TABLE transactions ADD COLUMN ecpay_trade_no TEXT",
    "ALTER TABLE transactions ADD COLUMN atm_bank_code TEXT",
    "ALTER TABLE transactions ADD COLUMN atm_virtual_account TEXT",
    "ALTER TABLE transactions ADD COLUMN atm_expire_date TEXT",
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
    connection = op.get_bind().connection
    cursor = connection.cursor()
    for col in ("ecpay_trade_no", "atm_bank_code", "atm_virtual_account", "atm_expire_date"):
        cursor.execute(f"ALTER TABLE transactions DROP COLUMN {col}")
    connection.commit()
