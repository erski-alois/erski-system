"""重設鋒/IVAN(work_id='2008')教練帳號的登入密碼為臨時密碼

依你的指示,幫鋒(登入帳號/工號 2008,role='coach')直接給一組臨時密碼。密碼在
資料庫裡是雜湊過的值,我這邊讀不出他目前實際在用的密碼是什麼,沒辦法「查詢」
或「提供」他原本的密碼,只能比照忘記密碼的處理方式,直接重設成一組新的臨時
密碼。

比照專案裡其他新建教練帳號預設密碼的慣例(生日後六碼),用他的生日1983-01-17
後六碼當臨時密碼:**830117**。請把「帳號:2008、臨時密碼:830117」提供給他,
並請他登入後盡快到「帳號安全(變更密碼)」自行改成別人猜不到的密碼——臨時密碼
只建議當作登入一次用,不要長期使用。

這支migration只會動到「work_id='2008' AND role='coach'」這一筆記錄(鋒/IVAN)
的password_hash欄位,不會影響其他任何員工/教練帳號。設計成可以重複執行,結果
都一樣(idempotent):每次都是直接把這筆記錄的密碼設成830117,不管原本密碼是
什麼、重跑幾次結果都一樣。

Revision ID: 4e8fb6a6bd96
Revises: 48cafab3e297
Create Date: 2026-09-21 03:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
from werkzeug.security import generate_password_hash


# revision identifiers, used by Alembic.
revision: str = '4e8fb6a6bd96'
down_revision: Union[str, Sequence[str], None] = '48cafab3e297'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_WORK_ID = "2008"  # 鋒/IVAN
_ROLE = "coach"
_NEW_PASSWORD = "830117"  # 依他的生日1983-01-17後六碼


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他密碼重設migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()把
    # SQL裡的冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),
    # 本機SQLite開發改schema.sql、由init_schema()直接建表,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    # 用work_id+role一起比對,確保只動到鋒這一筆教練帳號,不會誤動到同工號但
    # 角色不同、或其他任何員工的記錄。
    cursor.execute("SELECT id, name FROM staff WHERE work_id=%s AND role=%s", (_WORK_ID, _ROLE))
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            f"找不到工號「{_WORK_ID}」、角色「{_ROLE}」的員工記錄,migration中止,"
            f"請確認工號是否正確。"
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
