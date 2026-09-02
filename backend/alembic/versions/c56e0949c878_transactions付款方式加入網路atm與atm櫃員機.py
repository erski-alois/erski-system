"""transactions付款方式加入網路ATM與ATM櫃員機

配合正式串接綠界(ECPay)全方位金流,transactions.payment_method原本只允許
'online_card'/'onsite'/'bank_transfer'/'manual_grant',現在要多開放
'webatm'(網路ATM)、'atm'(ATM櫃員機,暫不開放前端選用,但底層先建好,
之後要開放時不需要再動一次資料庫結構)。

PostgreSQL的CHECK約束在建表時沒有特別命名,系統會自動用預設命名規則
(通常是transactions_payment_method_check),但為了不依賴這個可能因環境
而異的預設命名,這裡改成先動態查詢pg_constraint找出實際的約束名稱,
刪除後用一個固定的名稱重新建立,這樣以後如果還要再改一次也能穩定引用。

Revision ID: c56e0949c878
Revises: 3f3154aeb343
Create Date: 2026-08-28 09:46:22.981164

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c56e0949c878'
down_revision: Union[str, Sequence[str], None] = '3f3154aeb343'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_CONSTRAINT_NAME = "transactions_payment_method_check"


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()
    # 把SQL裡的冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),
    # 本機SQLite開發改schema.sql、由init_schema()直接建表,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT con.conname FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        WHERE rel.relname = 'transactions' AND con.contype = 'c'
          AND pg_get_constraintdef(con.oid) LIKE '%payment_method%'
        """
    )
    row = cursor.fetchone()
    if row:
        old_name = row[0]
        cursor.execute(f'ALTER TABLE transactions DROP CONSTRAINT "{old_name}"')
    cursor.execute(
        f"""ALTER TABLE transactions ADD CONSTRAINT {_NEW_CONSTRAINT_NAME}
            CHECK (payment_method IN ('online_card','onsite','bank_transfer','manual_grant','webatm','atm'))"""
    )
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # 注意:如果資料庫裡已經有payment_method='webatm'或'atm'的紀錄,還原這支
    # migration會因為違反約束而失敗,這是預期行為(避免還原後留下違反約束的髒資料),
    # 需要先手動處理那些資料列才能真的downgrade。
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute(f'ALTER TABLE transactions DROP CONSTRAINT "{_NEW_CONSTRAINT_NAME}"')
    cursor.execute(
        """ALTER TABLE transactions ADD CONSTRAINT transactions_payment_method_check
            CHECK (payment_method IN ('online_card','onsite','bank_transfer','manual_grant'))"""
    )
    connection.commit()
