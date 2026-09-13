"""orders表order_type欄位新增'group_class'這個選項

背景:這次「再測試一下金流,尤其是團課刷卡的部份」的過程中,發現團課
(group_class)報名成功後從來不會建立orders訂單,一旦後台把團課設定成
「額外收費」(pricing_config.group_class_price不是null),不管客戶選哪一種
付款方式(信用卡/現場付款/匯款轉帳都一樣),付款一律會失敗並顯示
「找不到對應的訂單,或訂單狀態不允許付款」——因為找不到訂單可以付款。

目前團課額度設定是null(不額外收費,算會員資格內),所以這個bug暫時不會
被實際客戶碰到,這次是主動測試發現的。已經在booking.py補上
enroll_group_class()建立訂單的邏輯(用於團課的每一位會員各自的報名記錄id
當ref_id,不是session本身的id,因為同一場團課session最多可以有4位會員
各自報名、各自要付款,共用session id當ref_id的話,不同會員的付款訂單會
互相干擾),但orders.order_type欄位原本的CHECK constraint不包含
'group_class'這個值,新增訂單時會直接被資料庫擋下(CHECK constraint
violation)。這支migration把'group_class'加進允許的選項清單。

這支migration只調整這一個CHECK constraint,不影響任何既有資料列,也不會
建立/刪除任何資料。

Revision ID: ae71bf8cb630
Revises: 612c5a98e6a2
Create Date: 2026-09-13 07:40:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'ae71bf8cb630'
down_revision: Union[str, Sequence[str], None] = '612c5a98e6a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_CHECK_SQL = (
    "order_type IN ('charter_pass', 'trial', 'self_practice', 'jump', "
    "'japan_trip', 'plan_subscription', 'group_class')"
)


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()把SQL裡的
    # 冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),本機SQLite
    # 開發改schema.sql、由init_schema()直接建表,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    # 動態查出orders.order_type現有CHECK constraint的實際名稱,而不是寫死猜測
    # (Postgres沒有明確命名的CHECK constraint,名稱是建表當下自動產生的,
    # 直接寫死名稱萬一跟正式環境實際的名稱對不起來,DROP CONSTRAINT會找不到、
    # migration會中止,比動態查詢更不保險)。
    cursor.execute(
        """
        SELECT con.conname, pg_get_constraintdef(con.oid) AS def
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        WHERE rel.relname = 'orders' AND con.contype = 'c'
          AND pg_get_constraintdef(con.oid) ILIKE %s
        """,
        ('%order_type%',),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            "在orders表上找不到order_type欄位現有的CHECK constraint,"
            "migration中止,請人工確認資料庫實際結構是否跟預期不同。"
        )
    constraint_name, constraint_def = row
    if "'group_class'" in constraint_def:
        return  # 已經加過了(idempotent:重複執行這支migration不會出錯)

    cursor.execute(f'ALTER TABLE orders DROP CONSTRAINT "{constraint_name}"')
    cursor.execute(f"ALTER TABLE orders ADD CONSTRAINT orders_order_type_check CHECK ({_NEW_CHECK_SQL})")
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # 故意不做任何事:如果團課付費功能已經上線、資料庫裡已經有order_type='group_class'
    # 的訂單存在,復原CHECK constraint(拿掉'group_class'這個選項)會導致既有資料違反
    # constraint,PostgreSQL的ALTER TABLE ADD CONSTRAINT在驗證階段就會直接失敗。
    # 如果真的需要復原,請先確認資料庫裡沒有任何group_class訂單,再另外手動處理。
    pass
