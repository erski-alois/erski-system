"""新增日本滑雪獨立分區「妙高高原」

起因:你先試著透過後台「雪場管理」把「妙高高原」加到既有的「其他雪場」分區底下,
結果會員端「日本滑雪」頁面看不到——原因是「其他雪場」這個分區2026-09-21當天
才被改成「純文字打需求、不給選雪場下拉選單」的特殊流程(見index.html的
isOtherResort邏輯:currentJapanRegion.code === "other" 時,不管這個分區底下
實際有幾筆ski_resorts,前端一律不顯示雪場清單,直接跳去自由文字需求表單),
所以不管在「其他雪場」底下加多少個雪場,會員都看不到、選不到。

跟你確認後,決定新增一個完全獨立的「妙高高原」分區(跟藏王溫泉滑雪場、鬼首滑雪
一樣是「單一雪場、免選、by school指派教練」的模式,不像北海道/白馬地區有多個
雪場要選)。

這支migration做三件事:

1. 新增 japan_regions 一筆「妙高高原」(code='myoko'):
   - requires_resort_selection=0:比照藏王/鬼首,只有一個雪場,不用給下拉選單
   - allow_designate_coach=1:比照藏王/北海道/鬼首/白馬,開放客戶指定教練
   - requires_accommodation_option=0:沒有要求詢問住宿(只有鬼首=1)
   - resort_list_editable=0:比照藏王/鬼首,固定一個雪場、不開放後台自行增刪
   - display_order=5:排在白馬地區(4)之後、其他雪場之前,「其他雪場」這個
     萬用分區原本display_order=5,這次順移成6,維持放在導覽選單最下面
     (概念上「其他雪場」是找不到對應分區時的最後選項,放最後面比較合理)

2. 把你之前手動透過「雪場管理」加到「其他雪場」底下的那筆孤兒資料
   (ski_resorts.name='妙高高原', 目前掛在region_id=5)重新指派過去新的
   「妙高高原」分區,code也順便改成'myoko_main'(比照zao_main/onikoube_main
   的命名慣例)。這筆資料目前還沒有指派任何駐點教練(resort_coaches查詢
   結果是空的),用UPDATE直接搬過去、不會遺失/衝突任何既有指派資料。
   如果因為某些原因這筆舊資料已經不存在了(例如你自己在後台手動刪除掉),
   就改用INSERT新增一筆,兩種情況都會處理到。

Revision ID: 84f5beee3f57
Revises: 8532bf57e96a
Create Date: 2026-09-22 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '84f5beee3f57'
down_revision: Union[str, Sequence[str], None] = '8532bf57e96a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()
    # 把SQL裡的冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),
    # 本機SQLite開發改schema.sql、由init_schema()直接建表+灌種子資料,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    # 「其他雪場」分區順移到最後面
    cursor.execute("UPDATE japan_regions SET display_order=6 WHERE code='other'")

    # 新增「妙高高原」分區(用ON CONFLICT保險,避免重複執行時因code的UNIQUE約束整支失敗)
    cursor.execute("""
        INSERT INTO japan_regions
            (code, name, requires_resort_selection, allow_designate_coach,
             requires_accommodation_option, resort_list_editable, display_order)
        VALUES ('myoko', '妙高高原', 0, 1, 0, 0, 5)
        ON CONFLICT (code) DO NOTHING
    """)

    cursor.execute("SELECT id FROM japan_regions WHERE code='myoko'")
    myoko_region_id = cursor.fetchone()[0]

    # 把之前誤加在「其他雪場」底下、名稱是「妙高高原」的那筆孤兒雪場資料搬過來這個新分區;
    # 如果那筆資料已經不存在了(找不到),就直接新增一筆。
    cursor.execute("""
        UPDATE ski_resorts SET region_id=%s, code='myoko_main'
        WHERE name='妙高高原' AND region_id != %s
    """, (myoko_region_id, myoko_region_id))
    if cursor.rowcount == 0:
        cursor.execute("""
            INSERT INTO ski_resorts (region_id, code, name)
            SELECT %s, 'myoko_main', '妙高高原'
            WHERE NOT EXISTS (SELECT 1 FROM ski_resorts WHERE region_id=%s)
        """, (myoko_region_id, myoko_region_id))

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute("SELECT id FROM japan_regions WHERE code='myoko'")
    row = cursor.fetchone()
    if row:
        myoko_region_id = row[0]
        cursor.execute("DELETE FROM ski_resorts WHERE region_id=%s", (myoko_region_id,))
        cursor.execute("DELETE FROM japan_regions WHERE id=%s", (myoko_region_id,))
    cursor.execute("UPDATE japan_regions SET display_order=5 WHERE code='other'")
    connection.commit()
