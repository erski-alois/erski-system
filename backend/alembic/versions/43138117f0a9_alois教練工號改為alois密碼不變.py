"""Alois的教練身份工號改為Alois(密碼不變)

背景:d5ebe1868207那支migration把Alois的教練身份工號設定為JK0001(跟他的老闆
身份A0002是兩筆不同的員工記錄)。這次依你的指示,把這筆教練身份的工號直接改成
「Alois」這個文字,方便他自己記得、不用再記JK0001這組代號——密碼欄位完全不動,
只改work_id這一個欄位。

這支migration只會找「目前work_id是JK0001、姓名是Alois、角色是coach」這一筆
員工記錄(用這3個條件一起比對,避免萬一工號被別的原因搶先改掉或對錯人),把
work_id改成「Alois」;不會動到他的老闆身份帳號(A0002,上一支migration
b8d1f4845331剛把這個帳號的密碼重設過),也不會動到password_hash欄位。

這支migration設計成可以重複執行,結果都一樣(idempotent):第一次執行後,
work_id已經變成Alois,不再符合「work_id=JK0001」這個比對條件,重跑不會找到
任何符合的記錄,直接跳過、不會報錯。

Revision ID: 43138117f0a9
Revises: b8d1f4845331
Create Date: 2026-09-12 05:45:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '43138117f0a9'
down_revision: Union[str, Sequence[str], None] = 'b8d1f4845331'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD_WORK_ID = "JK0001"
_NEW_WORK_ID = "Alois"
_NAME = "Alois"
_ROLE = "coach"


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()把SQL裡的
    # 冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),本機SQLite
    # 開發改schema.sql、由init_schema()直接建表+灌種子資料,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    # 先確認新工號「Alois」目前的狀況:
    #   1. 完全沒人用→正常往下走,進行改名。
    #   2. 已經被「這支migration自己」改過(名字=Alois、角色=coach)→代表重複執行,
    #      idempotent設計下直接跳過、不當作錯誤(不然重跑這支migration會誤判成
    #      衝突而中止)。
    #   3. 被其他不相干的人佔用→真的是衝突,中止並丟出清楚訊息,不悄悄覆蓋。
    cursor.execute("SELECT id, name, role FROM staff WHERE work_id=%s", (_NEW_WORK_ID,))
    existing = cursor.fetchone()
    if existing is not None:
        existing_id, existing_name, existing_role = existing
        if existing_name == _NAME and existing_role == _ROLE:
            # 就是這支migration自己改出來的那筆,重複執行,安靜跳過。
            return
        raise RuntimeError(
            f"工號「{_NEW_WORK_ID}」已經被員工「{existing_name}」(id={existing_id})使用,"
            f"跟這次要改名的教練身份對不起來,migration中止,請人工確認實際狀況。"
        )

    cursor.execute(
        "SELECT id FROM staff WHERE work_id=%s AND name=%s AND role=%s",
        (_OLD_WORK_ID, _NAME, _ROLE),
    )
    row = cursor.fetchone()
    if row is None:
        # 找不到「舊工號JK0001+Alois+coach」這筆,代表資料狀態跟預期不符(理論上
        # 不該發生,因為上面已經排除了「已經改名過」的情況),保守起見直接跳過、
        # 不當作錯誤,不去猜測或動到不確定的資料。
        return

    cursor.execute("UPDATE staff SET work_id=%s WHERE id=%s", (_NEW_WORK_ID, row[0]))
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # 工號是員工登入用的識別值,downgrade沒辦法安全判斷「這是不是這支migration改的
    # 那一筆」(萬一之後又手動改過),這裡故意不做任何還原動作。如果需要復原,
    # 請直接告訴我需要改回什麼工號,用另一支migration處理。
    pass
