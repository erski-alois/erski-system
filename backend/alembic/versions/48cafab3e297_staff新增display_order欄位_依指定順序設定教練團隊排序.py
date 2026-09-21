"""staff新增display_order欄位,依你指定的順序設定教練團隊頁面排序

依你的指示,公開的「教練團隊」頁面(/api/coaches)這次改成依你指定的順序顯示,
不再是資料庫原本的預設順序(之前完全沒有排序邏輯,顯示順序其實是不固定的,
依資料庫查詢當下回傳的順序而定)。

你給的順序是:
    Alois-Laco-Spin-一路-Mo-Nancy-玉米-鋒-Seina-Nita-阿用-琮博-傑-Yumi-Amber-
    菜脯-瑄-球-雞米-Andy-小于-肇廷

我套用這支migration前,先用Render的唯讀SQL查詢工具查了一次正式環境目前的
教練名單(role='coach'),把你給的22個名字/暱稱逐一比對到資料庫裡實際的
教練記錄,比對結果:

- 21位都順利比對到,依你給的順序設定display_order(10, 20, 30...依序遞增,
  中間預留間隔,方便你之後要插隊調整順序或加新教練時,不用整批重編號):
  Alois(id6)、LACO(id8)、SPIN(id9)、蔡一路/暱稱一路(id11)、MO(id12)、
  NANCY(id17)、玉米(id19)、鋒/IVAN(id13)、SEINA(id15)、NITA(id14)、
  阿用(id16)、黃琮博/暱稱Rizz(id20)、阿傑(id22)、YUMI(id7)、Amber(id10)、
  菜脯(id23)、瑄瑄(id21)、球球(id18)、雞米(id39)、Andy(id37)、小于(id38)。

- **「肇廷」這個名字,我在正式環境目前role='coach'的名單裡完全找不到對得起來
  的人(姓名、暱稱都沒有符合的)**,所以這支migration沒有幫他設定順序,
  順序清單裡也跳過他這個位置(21位的順序沒有因此中斷或留空號,只是少了
  肇廷這一位)。有可能是還沒建立這位教練的員工帳號、或是名字打法跟系統裡
  登記的不同(例如其實登記的是別的暱稱),麻煩你確認一下,我再另外出一支
  migration補上他的順序。

- **「Lily」(id36)這位教練目前是在職狀態(is_active=1),但你給的順序清單
  裡沒有提到她**,這支migration沒有幫她設定display_order(維持欄位預設值
  9999),所以她目前會排在你指定的21位教練「之後」。如果她其實也要排進
  順序裡的某個位置,麻煩告訴我要插在哪裡。

- 另外查詢正式環境時,**額外發現目前有一筆work_id='test'、role='coach'、
  is_active=1的教練記錄(id35,姓名直接就是"test")**,這筆帳號因為是在職
  狀態,理論上也會出現在公開的教練團隊頁面上——這應該是先前測試留下的假
  資料,不是這次要處理的問題,這裡先提醒你,如果要清掉請告訴我,我再另外
  出一支migration處理(這支migration沒有動到這筆資料,is_active停用/刪除
  這種操作,我不會自己判斷該怎麼處理你們的人事資料)。

技術上這次新增staff.display_order欄位(INTEGER,預設9999),數字越小排越
前面,沒有特別設定過的教練(含Lily、test帳號、已停用的教練)一律沿用預設值
9999,依id次序排在最後;/api/coaches這支公開API的查詢這次加上
「ORDER BY s.display_order ASC, s.id ASC」。

Revision ID: 48cafab3e297
Revises: 06b9a315b5d4
Create Date: 2026-09-21 03:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '48cafab3e297'
down_revision: Union[str, Sequence[str], None] = '06b9a315b5d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (姓名, display_order)——依你給的順序,依序間隔10編號,方便之後插隊調整。
# 用staff.id直接對應(套用前已用Render唯讀SQL工具查過正式環境目前的教練id),
# 不再依姓名字串重新比對一次,避免萬一有同名情況誤改到別人。
_COACH_ORDER = [
    (6, "Alois", 10),
    (8, "LACO", 20),
    (9, "SPIN", 30),
    (11, "蔡一路", 40),
    (12, "MO", 50),
    (17, "NANCY", 60),
    (19, "玉米", 70),
    (13, "鋒/IVAN", 80),
    (15, "SEINA", 90),
    (14, "NITA", 100),
    (16, "阿用", 110),
    (20, "黃琮博", 120),
    (22, "阿傑", 130),
    (7, "YUMI", 140),
    (10, "Amber", 150),
    (23, "菜脯", 160),
    (21, "瑄瑄", 170),
    (18, "球球", 180),
    (39, "雞米", 190),
    (37, "Andy", 200),
    (38, "小于", 210),
]


def upgrade() -> None:
    """Upgrade schema."""
    # 這支migration只支援PostgreSQL(正式環境+本機Postgres測試資料庫),沿用專案裡
    # 資料異動類migration的既有慣例——本機SQLite開發改schema.sql、由init_schema()
    # 直接建表,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    cursor.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS display_order INTEGER DEFAULT 9999")

    # 逐筆設定,同時比對姓名確保id沒有對錯人(避免套用到跟預期不符的環境時
    # 誤改到不相干的員工資料;姓名對不起來就直接跳過這一筆,不會硬改)。
    for staff_id, expected_name, order in _COACH_ORDER:
        cursor.execute("SELECT name FROM staff WHERE id=%s AND role='coach'", (staff_id,))
        row = cursor.fetchone()
        if row is None or row[0] != expected_name:
            continue
        cursor.execute("UPDATE staff SET display_order=%s WHERE id=%s", (order, staff_id))

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute("ALTER TABLE staff DROP COLUMN IF EXISTS display_order")
    connection.commit()
