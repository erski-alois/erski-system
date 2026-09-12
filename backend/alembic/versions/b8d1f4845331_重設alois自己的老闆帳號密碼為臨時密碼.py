"""重設Alois自己的老闆帳號(A0002)密碼為臨時密碼

背景:上一支migration(0cee2608b2cc)依你當時的指示,把老闆/股東/主管這9個帳號的
密碼統一改成123456,但刻意排除了你自己這個帳號(A0002),不動你的密碼——所以
你的A0002密碼其實還是「更早之前」設定的那組。這次你反映後台登入一直顯示密碼
錯誤(且我實際查過正式環境的即時log,確認短時間內有十幾次對`/api/auth/staff-login`
的401失敗紀錄,時間點跟你回報的時間吻合),但你自己也不確定原本密碼是什麼——
密碼在資料庫裡是雜湊過的值,我這邊也讀不出明碼,沒辦法幫你「找回」原密碼,
只能比照忘記密碼的處理方式,直接重設成一組新密碼。

依你的指示,這次直接把A0002(Alois自己的老闆帳號)密碼重設為 000000,方便你先
登入,務必請你登入後台後,盡快到後台的「帳號安全(變更密碼)」把密碼改成你自己
記得住、别人猜不到的密碼——000000這種全部同一個數字的密碼非常容易被猜到,只
建議當作「登入用一次就馬上改掉」的臨時密碼,不要長期使用。

這支migration只會動到A0002這一個帳號的password_hash欄位,不會影響其他任何
帳號(包括上一支migration已經改成123456的那9個帳號、你另外的教練身份JK0001,
都不會被這支migration動到)。

這支migration設計成可以重複執行,結果都一樣(idempotent):每次都是直接把A0002
的密碼設成000000,不管原本密碼是什麼、重跑幾次結果都一樣。

Revision ID: b8d1f4845331
Revises: 0cee2608b2cc
Create Date: 2026-09-12 05:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
from werkzeug.security import generate_password_hash


# revision identifiers, used by Alembic.
revision: str = 'b8d1f4845331'
down_revision: Union[str, Sequence[str], None] = '0cee2608b2cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_WORK_ID = "A0002"  # Alois自己的老闆帳號(跟他另一筆教練身份JK0001是不同的員工記錄)
_NEW_PASSWORD = "000000"


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()把SQL裡的
    # 冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),本機SQLite
    # 開發改schema.sql、由init_schema()直接建表+灌種子資料,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    cursor.execute("SELECT id FROM staff WHERE work_id=%s", (_WORK_ID,))
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            f"找不到工號 {_WORK_ID},請確認上一支migration(d5ebe1868207/0cee2608b2cc)"
            f"是否已經正確套用,migration中止。"
        )

    new_hash = generate_password_hash(_NEW_PASSWORD)
    cursor.execute("UPDATE staff SET password_hash=%s WHERE work_id=%s", (new_hash, _WORK_ID))

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # 密碼是敏感資料,downgrade沒辦法還原「migration執行前」原本的密碼(那個雜湊值
    # 沒有被記錄下來,而且原密碼本來就是使用者自己都想不起來的狀態),這裡故意不做
    # 任何還原動作。如果需要復原,請直接告訴我需要改成什麼密碼,用另一支migration處理。
    pass
