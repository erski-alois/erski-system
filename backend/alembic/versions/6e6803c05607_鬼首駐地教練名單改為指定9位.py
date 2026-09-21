"""鬼首駐地教練名單改為指定9位:Alois/Seina/雞米/小于/Andy/玉米/Nancy/琮博/阿傑

依你的指示「鬼首教練人員要有Alois/Seina/雞米/小于/Andy/玉米/Nancy/琮博/阿傑」,把
「鬼首」這個日本雪場駐在地(coach_locations)的教練名單,改成精確等於這9位——不是
在原本名單上「新增」,而是整個重設成剛好只有這9位。

套用migration前,我先用Render的唯讀SQL查詢工具查了一次正式環境目前「鬼首」駐在地
底下實際掛的教練,跟這次要求的9位名單比對如下:

- **已經在鬼首名單裡、這次繼續保留**:Alois、SEINA、NANCY、蔡育穎(你訊息裡的「玉米」
  是他的暱稱,系統帳號實際登記的姓名是蔡育穎)、黃琮博(你訊息裡的「琮博」同樣是暱稱,
  系統帳號實際登記的姓名是黃琮博)、阿傑。
- **這次新加入鬼首**:雞米、小于、Andy——這3位是比較新建立的教練帳號,目前完全沒有
  設定任何駐在地(之前建立帳號時沒有一併設定)。
- **這次從鬼首移除**(改成只保留藏王,不動藏王本身):LACO、SPIN、MO、蔡一路、阿用、
  洪名鋒(鋒/IVAN)——這6位原本鬼首/藏王都有,這次只拿掉鬼首,藏王維持不動。

比對方式比照先前「教練駐在地」那支migration(1eb79191a711)、以及「教練團隊排序」
那支migration(48cafab3e297)的既有慣例:用staff.id指定(id沿用48cafab3e297已經
跟正式環境核對過一次的同一份姓名->id清單,比姓名字串更精準、避免同名誤判),但套用
前再多一層「id+目前姓名是否仍然相符」的保險檢查——如果正式環境剛好跟我核對過的那次
快照不一致(例如剛好有教練被刪除、或id被別的員工佔用),這一筆會直接讓migration中止
並清楚列出是哪一筆對不上,不會悄悄跳過或誤改到不相干的員工資料。

這支migration只會動到「鬼首」這一個駐在地選項的教練關聯,不會動到藏王/北海道/
白馬/高雄/其他,也不會動到任何教練的其他資料。設計成可以重複執行,結果都一樣
(idempotent):每次都會先清空「鬼首」目前的全部教練關聯,再依這9位名單重新指派一次。

Revision ID: 6e6803c05607
Revises: 4e8fb6a6bd96
Create Date: 2026-09-21 09:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '6e6803c05607'
down_revision: Union[str, Sequence[str], None] = '4e8fb6a6bd96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 這次要求的9位教練:(staff.id, 系統帳號實際登記的姓名)。id沿用48cafab3e297已經
# 核對過正式環境的同一份姓名->id清單;「玉米」「琮博」是你訊息裡用的暱稱,實際登記
# 姓名分別是蔡育穎/黃琮博,這裡用系統實際登記的姓名做二次核對。
_ONIKOUBE_COACHES = [
    (6, "Alois"),
    (15, "SEINA"),
    (39, "雞米"),
    (38, "小于"),
    (37, "Andy"),
    (19, "蔡育穎"),   # 玉米
    (17, "NANCY"),
    (20, "黃琮博"),   # 琮博
    (22, "阿傑"),
]


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()把SQL裡的
    # 冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),本機SQLite
    # 開發改schema.sql、由init_schema()直接建表+灌種子資料,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    cursor.execute("SELECT id FROM coach_location_options WHERE name=%s", ('鬼首',))
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("找不到「鬼首」這個駐在地選項,migration中止,請確認baseline schema是否正常。")
    oniko_id = row[0]

    # 保險檢查:逐筆確認id+目前姓名是否仍然相符,任何一筆對不上就直接中止整支
    # migration(不悄悄跳過、也不硬改),避免正式環境跟我核對過的那次快照不一致時,
    # 誤指派到不相干的員工。
    mismatches = []
    for staff_id, expected_name in _ONIKOUBE_COACHES:
        cursor.execute("SELECT name FROM staff WHERE id=%s AND role='coach'", (staff_id,))
        r = cursor.fetchone()
        actual_name = r[0] if r else None
        if actual_name != expected_name:
            mismatches.append((staff_id, expected_name, actual_name))
    if mismatches:
        raise RuntimeError(
            "以下教練id目前的姓名跟預期不符,migration中止,不會異動任何資料:"
            + "; ".join(f"id={sid} 預期「{exp}」實際「{act}」" for sid, exp, act in mismatches)
        )

    # 先清空「鬼首」目前全部的教練關聯,再依這9位名單重新指派一次,確保結果精準
    # 等於這次指定的名單(不多不少),且重複執行這支migration結果都一樣。不會動到
    # 藏王/北海道/白馬/高雄/其他這些其他駐在地選項上的既有關聯。
    cursor.execute("DELETE FROM coach_locations WHERE location_option_id=%s", (oniko_id,))
    for staff_id, _ in _ONIKOUBE_COACHES:
        cursor.execute(
            "INSERT INTO coach_locations (coach_id, location_option_id) VALUES (%s, %s) "
            "ON CONFLICT (coach_id, location_option_id) DO NOTHING",
            (staff_id, oniko_id),
        )

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # 這支migration異動的是「教練駐在地」這種營運資料,不是單純的schema/固定設定值,
    # downgrade沒辦法還原「migration執行前」每位教練原本鬼首駐在地的設定(那個狀態
    # 沒有被記錄下來),比照先前同類型migration(1eb79191a711)的既有慣例,downgrade
    # 不做任何還原動作。如果需要復原,請到後台教練詳情頁手動調整,或告訴我要改成
    # 什麼名單,我再另外處理。
    pass
