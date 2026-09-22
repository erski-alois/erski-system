"""室內滑雪機台營業時間改為13:00-21:00、新增星期一公休設定

依你的指示「室內滑雪課程營業時間更改為13:00-21:00, 星期一公休」新增。

這支migration做兩件事,都是改pricing_config(複用既有機制,不用另外新增資料表,
跟e91a6c3f2b58新增匯款帳號設定那支migration是同一種做法):

1. 把indoor_start_hour從10改成13(對應開始營業時間13:00)。indoor_last_start_hour
   維持20不變(20:00開課,標準1小時的課程剛好20:00-21:00結束,符合「到21:00」的
   營業時間)——只有60分鐘以上的自主練習(90/120分鐘)在20:00開課會跑到21:00之後
   結束,這是原本就存在、這次沒有另外處理的邊界情況,先不擋。

2. 新增indoor_closed_weekdays設定,值為[0](Python的datetime.weekday():星期一=0),
   代表室內滑雪機台每週一公休。後台程式(booking.py四支室內預約函式:體驗課/包機/
   自主練習/團課)新增了pricing.validate_indoor_not_closed_day()檢查,擋下公休日
   當天的新預約/改期(員工後台改期不受此限,比照既有的_check_edit_window慣例)。
   跳台體驗(book_jump)是獨立資源,這次公休範圍沒有要求連跳台一起停,所以沒有擋。

   之所以做成陣列(而不是單一布林值「星期一是否公休」),是為了以後如果公休日
   調整成不只星期一,後台改這個設定值就好,不需要再跑一次migration或改程式碼。

用UPDATE(不是INSERT ... ON CONFLICT)處理indoor_start_hour,因為這個key本來就
一定存在(schema seed資料本來就有);indoor_closed_weekdays則跟bank_account_*
那兩筆一樣用INSERT ... ON CONFLICT DO NOTHING,保險用(避免重複執行/key已存在
時讓整支migration失敗)。

Revision ID: 8532bf57e96a
Revises: a1c7f2b940de
Create Date: 2026-09-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8532bf57e96a'
down_revision: Union[str, Sequence[str], None] = 'a1c7f2b940de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()
    # 把SQL裡的冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),
    # 本機SQLite開發改schema.sql、由init_schema()直接建表+灌種子資料,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    cursor.execute(
        "UPDATE pricing_config SET config_value=%s WHERE config_key='indoor_start_hour'",
        ('13',),
    )
    cursor.execute(
        "INSERT INTO pricing_config (config_key, config_value, label) VALUES "
        "('indoor_closed_weekdays', %s, %s) "
        "ON CONFLICT (config_key) DO NOTHING",
        ('[0]', '室內滑雪機台公休日(0~6對應星期一~星期日,目前為[0]=星期一公休)'),
    )
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE pricing_config SET config_value=%s WHERE config_key='indoor_start_hour'",
        ('10',),
    )
    cursor.execute("DELETE FROM pricing_config WHERE config_key='indoor_closed_weekdays'")
    connection.commit()
