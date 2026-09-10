"""後台(股東/主管/老闆)預設密碼統一改成123456,Alois除外

依你的要求:「除了Alois外,後台所有人預設密碼都用123456,登入後台後讓所有人自行
更改密碼」。這支migration把上一支migration(d5ebe1868207)剛設定好工號的9位
老闆/股東/主管員工帳號(Henry/Winnie/Laco/Spin/雞米/Andy/小于/慈慈/Lili,對應
工號A0001/A0003/B0001/B0002/B0003/C0002/C0003/C0005/C0006)的登入密碼,一律
改設成123456;Alois(A0002)刻意排除在外,不動他的密碼。

「後台」這裡指的是股東/主管/老闆這3種角色(登入的是「員工後台管理」畫面);
教練是走另一個獨立的「教練頁面」登入,不在這次的指示範圍內,這支migration
不會動到任何教練帳號的密碼(包含Alois/Laco/Spin額外的教練身份JK0001/JK0002/
JK0003,也都不會被這支migration動到)。

這支migration設計成可以重複執行,結果都一樣(idempotent):每次都是直接把這9個
工號的密碼設成123456,不管原本密碼是什麼、重跑幾次結果都一樣。

⚠️老實跟你說一個目前還沒有解決、跟這次改動直接相關的問題:員工後台登入(auth.py
的staff_login函式)目前密碼驗證這段程式碼是「刻意關閉」的狀態(只要工號正確、
帳號是啟用中,不管密碼欄位打對打錯或留空都能登入),這是先前就已經回報過、
標註「正式上線前務必修好」但你還沒明確回覆要不要處理的既有問題。也就是說,
在那個問題修好之前,這裡設定的123456其實「還沒有真的生效」——目前不管密碼
欄位打什麼都能登入這9個帳號,不是只有打123456才能登入。這支migration只是
先把資料庫裡「登記的密碼」設定好,等你確認要修復登入驗證那個問題之後,
123456才會是「真正擋著、需要正確輸入才能登入」的密碼,詳情請見對話裡的說明。

Revision ID: 0cee2608b2cc
Revises: d5ebe1868207
Create Date: 2026-09-10 09:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
from werkzeug.security import generate_password_hash


# revision identifiers, used by Alembic.
revision: str = '0cee2608b2cc'
down_revision: Union[str, Sequence[str], None] = 'd5ebe1868207'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 上一支migration(d5ebe1868207)設定的10位老闆/股東/主管工號,扣掉Alois(A0002)
_WORK_IDS_TO_RESET = [
    "A0001",  # Henry(老闆)
    "A0003",  # Winnie(老闆)
    "B0001",  # Laco(股東)
    "B0002",  # Spin(股東)
    "B0003",  # 雞米(股東)
    "C0002",  # Andy(主管)
    "C0003",  # 小于(主管)
    "C0005",  # 慈慈(主管)
    "C0006",  # Lili(主管)
]

_NEW_PASSWORD = "123456"


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()把SQL裡的
    # 冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),本機SQLite
    # 開發改schema.sql、由init_schema()直接建表+灌種子資料,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    new_hash = generate_password_hash(_NEW_PASSWORD)

    # 先確認這9個工號都已經存在(理論上上一支migration已經建立好了,如果查不到
    # 代表migration套用順序有問題,寧可直接失敗、不要悄悄跳過)。
    cursor.execute(
        "SELECT work_id FROM staff WHERE work_id = ANY(%s)",
        (_WORK_IDS_TO_RESET,),
    )
    found = {row[0] for row in cursor.fetchall()}
    missing = [w for w in _WORK_IDS_TO_RESET if w not in found]
    if missing:
        raise RuntimeError(
            f"找不到工號:{missing},請確認上一支migration(d5ebe1868207)是否已經"
            f"正確套用,migration中止。"
        )

    cursor.execute(
        "UPDATE staff SET password_hash=%s WHERE work_id = ANY(%s)",
        (new_hash, _WORK_IDS_TO_RESET),
    )

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # 密碼是敏感資料,downgrade沒辦法還原「migration執行前」原本的密碼(那個雜湊值
    # 沒有被記錄下來),這裡故意不做任何還原動作。如果需要復原,請直接告訴我需要
    # 改成什麼密碼,用另一支migration處理。
    pass
