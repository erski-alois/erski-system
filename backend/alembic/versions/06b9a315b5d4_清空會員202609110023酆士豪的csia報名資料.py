"""清空會員202609110023(酆士豪)的CSIA報名資料

依你的指示「清空會員202609110023的報名資料」。這個會員編號依compute_member_code()
的組成規則(年4碼+月2碼+滑行項目1碼+性別1碼+會員id流水序號4碼)解出來對應的是
member_id=23——已經用Render的唯讀SQL查詢工具查過正式環境members表確認,id=23的
會員姓名/性別/滑行項目/註冊時間(2026-09-10)組出來的會員編號就是202609110023,
姓名是「酆士豪」,正好就是六十四節提到、目前正式環境csia_registrations裡那2筆
重複報名(id=1、id=2,同一場次Level 1第一梯報名了兩次)的當事人。

「清空報名資料」這裡的判斷是:把這個會員在csia_registrations裡的報名紀錄全部
刪除(這2筆重複資料都清掉,不是只留一筆),讓這個會員之後可以重新乾淨地報名一次
——不是只清空某些欄位、保留報名紀錄本身。如果你的意思其實是只留一筆、清掉另一筆
重複的就好,或者這個會員其實還有其他業務課程(室內雪機/日本教練課等)的預約資料
也要一併清掉,請告訴我,我再另外處理(這支migration只動csia_registrations這張
表,其他預約/訂單資料完全沒有動到)。

安全性考量:DELETE語句同時用member_id=23跟chinese_name='酆士豪'兩個條件一起比對
(不是只用member_id),避免萬一套用到其他環境(例如本機測試資料庫)時,剛好也有
一個id=23的會員、但實際上是不相干的人,誤刪到不該刪的資料。

Revision ID: 06b9a315b5d4
Revises: 23ae35facf71
Create Date: 2026-09-20 16:05:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '06b9a315b5d4'
down_revision: Union[str, Sequence[str], None] = '23ae35facf71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute(
        "DELETE FROM csia_registrations WHERE member_id=%s AND chinese_name=%s",
        (23, '酆士豪'),
    )
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # 資料已經被刪除,downgrade沒有辦法把原本的報名內容(職業/緊急聯絡人/報考原因
    # 等所有欄位)還原回來,故意設計成no-op。如果真的需要復原,請先告訴我,這筆
    # 資料被刪除前的完整內容我這裡有留存記錄,可以視情況協助手動處理。
    pass
