"""coach_locations依需求指派教練駐在地(白馬/北海道/藏王+鬼首)

依你在對話裡明確給的名單設定教練的「日本雪場駐在地」(coach_locations,决定前台
「指定教練」下拉選單、教練團隊分區顯示會抓到哪些教練):

- YUMI / AMBER / 球球 / 瑄瑄 / 菜脯 → 白馬
- NITA → 北海道
- 其餘所有教練(role='coach') → 藏王 + 鬼首(兩個都給)

「白馬」這個駐在地選項之前沒有建立過(coach_location_options原本只有種子資料
藏王/鬼首/北海道/高雄/其他,見schema.sql),這支migration先確保白馬存在,再依
上面的分組指派。

比對教練姓名時故意「去頭尾空白+忽略英文大小寫」再比對(YUMI/Yumi/yumi視為同一人),
中文名字則要求完全相符,盡量避免因為打字大小寫不同而漏掉該指派的教練——但因為我
這裡沒有正式環境資料庫的存取權限,沒辦法實際跑一次確認每個名字都真的比對得上,
麻煩部署後到後台隨便點開一兩位教練(例如YUMI、以及任一位「其他」教練)的教練詳情,
確認「駐在地」欄位勾選的地區跟預期一致,如果有沒對到名字的教練,到後台教練詳情頁
手動勾選即可,不需要再跑一次migration。

這支migration設計成「可以重複執行,結果都一樣」(idempotent):每次都會先清掉該教練
在這4個地區選項上的既有關聯、再重新指派一次,不會因為重複跑而疊加出重複資料;而且
只會動到「藏王/鬼首/北海道/白馬」這4個日本雪場駐在地,教練原本如果有勾選「高雄」
(室內滑雪分店)或「其他」,不會被這支migration動到。

Revision ID: 1eb79191a711
Revises: e91a6c3f2b58
Create Date: 2026-09-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1eb79191a711'
down_revision: Union[str, Sequence[str], None] = 'e91a6c3f2b58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 依對話裡給的名單分組(比對時會先把姓名去頭尾空白、轉小寫)
_HAKUBA_NAMES = {'yumi', 'amber', '球球', '瑄瑄', '菜脯'}
_HOKKAIDO_NAMES = {'nita'}


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()把SQL裡的
    # 冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),本機SQLite
    # 開發改schema.sql、由init_schema()直接建表+灌種子資料,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    # 1. 確保「白馬」這個駐在地選項存在(之前只建了藏王/鬼首/北海道/高雄/其他)。
    #    用ON CONFLICT DO NOTHING是為了保險:如果白馬這個名稱因為某些原因已經存在
    #    (例如你之前已經自己在後台手動新增過),不會因為name的UNIQUE約束讓migration失敗。
    cursor.execute(
        "INSERT INTO coach_location_options (name, is_indoor_branch) VALUES (%s, %s) "
        "ON CONFLICT (name) DO NOTHING",
        ('白馬', 0),
    )

    # 2. 撈出這次要用到的4個「日本雪場駐在地」選項id
    cursor.execute(
        "SELECT id, name FROM coach_location_options WHERE name IN (%s, %s, %s, %s)",
        ('藏王', '鬼首', '北海道', '白馬'),
    )
    loc_ids = {name: loc_id for loc_id, name in cursor.fetchall()}
    if not all(k in loc_ids for k in ('藏王', '鬼首', '北海道', '白馬')):
        # 理論上不會發生(藏王/鬼首/北海道是baseline schema就有的種子資料,白馬上面剛建立),
        # 但萬一環境跟預期不同,寧可讓migration直接失敗、不要悄悄跳過指派動作。
        raise RuntimeError(f"coach_location_options缺少必要的駐在地選項,目前查到:{loc_ids}")
    zao_id, oniko_id = loc_ids['藏王'], loc_ids['鬼首']
    hokkaido_id, hakuba_id = loc_ids['北海道'], loc_ids['白馬']
    managed_loc_ids = (zao_id, oniko_id, hokkaido_id, hakuba_id)

    # 3. 依教練姓名分組,指派駐在地
    cursor.execute("SELECT id, name FROM staff WHERE role='coach' AND is_active=1")
    coaches = cursor.fetchall()

    for coach_id, name in coaches:
        key = (name or '').strip().lower()
        if key in _HAKUBA_NAMES:
            target_ids = [hakuba_id]
        elif key in _HOKKAIDO_NAMES:
            target_ids = [hokkaido_id]
        else:
            target_ids = [zao_id, oniko_id]

        # 先清掉這位教練在這4個日本雪場駐在地選項上的既有關聯,再依分組結果重新指派,
        # 確保重複執行這支migration結果都一樣、不會疊加出重複資料。不會動到「高雄」
        # (室內滑雪分店)或「其他」這類不在這4個id裡的既有駐在地關聯。
        cursor.execute(
            "DELETE FROM coach_locations WHERE coach_id=%s AND location_option_id IN (%s,%s,%s,%s)",
            (coach_id, *managed_loc_ids),
        )
        for loc_id in target_ids:
            cursor.execute(
                "INSERT INTO coach_locations (coach_id, location_option_id) VALUES (%s, %s) "
                "ON CONFLICT (coach_id, location_option_id) DO NOTHING",
                (coach_id, loc_id),
            )

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # 這支migration異動的是「教練駐在地」這種營運資料,不是單純的schema/固定設定值,
    # downgrade沒辦法還原每位教練「migration執行前」原本的駐在地設定(那個狀態沒有
    # 被記錄下來)。這裡只把「白馬」這個駐在地選項本身,在沒有任何教練還掛在上面時
    # 移除,避免留下這支migration新增的殘留設定值;教練跟駐在地的關聯本身不會被還原,
    # 需要的話請到後台教練詳情頁手動調整。
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute(
        "DELETE FROM coach_location_options WHERE name = %s "
        "AND id NOT IN (SELECT DISTINCT location_option_id FROM coach_locations)",
        ('白馬',),
    )
    connection.commit()
