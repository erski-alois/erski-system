"""重設Alois教練身份(work_id='Alois')的登入密碼為臨時密碼

背景:上一支migration(43138117f0a9)把你的「教練身份」那筆員工記錄的工號從
JK0001改成文字「Alois」,當時明確說「只改工號,密碼完全不動」。這次你反映
教練頁登入不了——這筆教練身份記錄從一開始建立(migration d5ebe1868207)到
現在,密碼從來沒有被任何一支migration動過,所以密碼還是最早那組佔位密碼
(當時的說明是:用生日2000-01-01的後6碼"000101"當預設密碼)。如果你後來
忘記這組密碼、或曾經改過忘記改成什麼,就會登入不了。

密碼在資料庫裡是雜湊過的值,我這邊讀不出明碼,沒辦法幫你「找回」原密碼,
只能比照忘記密碼的處理方式重設。依你的指示,把這筆教練身份(work_id目前是
「Alois」、role='coach')的密碼重設為 000000,方便你先登入,務必請你登入
教練頁後,盡快去改成自己記得住、别人猜不到的密碼——000000這種全部同一個
數字的密碼非常容易被猜到,只建議當作「登入一次就馬上改掉」的臨時密碼。

這支migration只會動到「work_id='Alois' AND role='coach'」這一筆記錄的
password_hash欄位,不會影響你的老闆帳號(A0002,五十三節已經重設過密碼,
這裡不會再動它),也不會影響其他任何員工/教練帳號。

這支migration設計成可以重複執行,結果都一樣(idempotent):每次都是直接把
這筆教練身份記錄的密碼設成000000,不管原本密碼是什麼、重跑幾次結果都一樣。

Revision ID: 612c5a98e6a2
Revises: 43138117f0a9
Create Date: 2026-09-12 06:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
from werkzeug.security import generate_password_hash


# revision identifiers, used by Alembic.
revision: str = '612c5a98e6a2'
down_revision: Union[str, Sequence[str], None] = '43138117f0a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_WORK_ID = "Alois"  # 上一支migration(43138117f0a9)把Alois的教練身份工號從JK0001改成這個
_ROLE = "coach"
_NEW_PASSWORD = "000000"


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()把SQL裡的
    # 冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),本機SQLite
    # 開發改schema.sql、由init_schema()直接建表+灌種子資料,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    # 用work_id+role一起比對,確保只動到Alois的教練身份這一筆,不會誤動到
    # 他的老闆帳號(A0002,role='boss')或任何其他同名員工。
    cursor.execute("SELECT id FROM staff WHERE work_id=%s AND role=%s", (_WORK_ID, _ROLE))
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            f"找不到工號「{_WORK_ID}」、角色「{_ROLE}」的員工記錄,請確認上一支migration"
            f"(43138117f0a9)是否已經正確套用,migration中止。"
        )

    new_hash = generate_password_hash(_NEW_PASSWORD)
    cursor.execute("UPDATE staff SET password_hash=%s WHERE id=%s", (new_hash, row[0]))
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # 密碼是敏感資料,downgrade沒辦法還原「migration執行前」原本的密碼(那個雜湊值
    # 沒有被記錄下來),這裡故意不做任何還原動作。如果需要復原,請直接告訴我需要
    # 改成什麼密碼,用另一支migration處理。
    pass
