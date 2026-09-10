"""工號設定:老闆/股東/主管10人 + Alois/Laco/Spin額外的教練身份工號

依對話裡明確給的名單設定「員工工號」與「後台角色」:

    工號        姓名    角色(DB role值)
    A0001       Henry   boss  (老闆)
    A0002       Alois   boss  (老闆)
    A0003       Winnie  boss  (老闆)
    B0001       Laco    cs    (股東,DB裡的角色值沿用舊的'cs',只是後台顯示文字
                                從「客服」改成「股東」,不是新增schema欄位值)
    B0002       Spin    cs    (股東)
    B0003       雞米     cs    (股東)
    C0002       Andy    manager (主管)
    C0003       小于     manager (主管)
    C0005       慈慈     manager (主管)
    C0006       Lili    manager (主管)

另外,Alois/Laco/Spin這3位「同時也需要教練身份」——也就是說,除了上面那筆
boss/cs的後台帳號之外,這3個人還要「另外」各自有一筆role='coach'的員工
記錄(登入後台/接團課用的是不同的工號/帳號),工號分別為:

    JK0001      Alois   coach (教練身份,跟上面A0002的老闆身份是兩筆不同的員工記錄)
    JK0002      Laco    coach
    JK0003      Spin    coach

比對「這個人在資料庫裡是不是已經存在」的邏輯,因為我這裡沒有正式環境資料庫的
存取權限,無法實際查一次現有員工名單,所以採取比較保守的作法——依姓名比對
(去頭尾空白、忽略英文大小寫;中文名字要求完全相符):
  - 老闆/股東/主管10人:只在「目前角色是cs/manager/boss」的員工裡找同名的人
    (不會去動同名的教練記錄,因為那是完全獨立的身份)。找到就把工號/角色更新成
    上表的值;找不到就新增一筆員工記錄。
  - Alois/Laco/Spin的教練身份:只在「目前角色是coach」的員工裡找同名的人,
    找到就把工號更新成JK000x;找不到就新增一筆role='coach'的員工記錄。

「新增一筆員工記錄」這種情況下,因為staff.birthday/password_hash都是NOT NULL
欄位,但我不知道這些人實際的生日,所以只能先填一個佔位生日 2000-01-01(對應的
預設登入密碼就是生日六碼 000101),分店(branch)欄位也先填「高雄」佔位——
麻煩上線後幫忙確認這10+3筆員工記錄裡,哪幾筆是這支migration「新增」出來的
(可以到後台「教練管理」或員工清單看birthday是不是2000-01-01),那幾筆的
生日/分店是佔位值,煩請盡快請本人用「員工登入」用預設密碼(000101)登入後,
到「帳號安全(變更密碼)」把密碼改掉;生日/分店欄位目前沒有開放股東/主管/老闆
自己修改的頁面(現有「編輯基本資料」表單目前只開放給股東以上,且入口只掛在
教練管理裡),如果需要更正這幾筆佔位資料,請直接告訴我正確的值,我再另外
出一支migration修正,不需要自己去改資料庫。

如果這個人「本來就已經存在」於資料庫(只是角色/工號跟上表不同),這支migration
只會更新工號跟角色,不會動到原本已經有的生日/分店/密碼等其他欄位。

這支migration設計成「可以重複執行,結果都一樣」(idempotent):重跑一次不會
把同一個人重複新增,也不會把工號打架的兩個人互相覆蓋——如果偵測到某個工號
已經被「姓名對不起來」的另一筆記錄用掉,會直接讓migration失敗並丟出清楚的
錯誤訊息,不會悄悄覆蓋掉錯的資料,需要的話再麻煩告訴我實際狀況。

Revision ID: d5ebe1868207
Revises: 1eb79191a711
Create Date: 2026-09-10 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
from werkzeug.security import generate_password_hash


# revision identifiers, used by Alembic.
revision: str = 'd5ebe1868207'
down_revision: Union[str, Sequence[str], None] = '1eb79191a711'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (姓名, 工號, DB role值)——老闆/股東/主管
_ADMIN_ASSIGNMENTS = [
    ("Henry", "A0001", "boss"),
    ("Alois", "A0002", "boss"),
    ("Winnie", "A0003", "boss"),
    ("Laco", "B0001", "cs"),
    ("Spin", "B0002", "cs"),
    ("雞米", "B0003", "cs"),
    ("Andy", "C0002", "manager"),
    ("小于", "C0003", "manager"),
    ("慈慈", "C0005", "manager"),
    ("Lili", "C0006", "manager"),
]

# (姓名, 工號)——額外的教練身份(role='coach'的另一筆記錄)
_COACH_ASSIGNMENTS = [
    ("Alois", "JK0001"),
    ("Laco", "JK0002"),
    ("Spin", "JK0003"),
]

_PLACEHOLDER_BIRTHDAY = "2000-01-01"
_PLACEHOLDER_BRANCH = "高雄"


def _norm(name):
    return (name or "").strip().lower()


def _find_match(rows, name):
    """rows: [(id, name, work_id, role), ...]。回傳唯一比對到的那筆,比對不到回傳
    None,比對到超過一筆(同名同角色群組有多人)則直接丟錯,不猜。"""
    key = _norm(name)
    matches = [r for r in rows if _norm(r[1]) == key]
    if len(matches) > 1:
        raise RuntimeError(
            f"姓名「{name}」在比對範圍內找到多筆同名員工,無法自動判斷要更新哪一筆,"
            f"請人工確認後再處理:{matches}"
        )
    return matches[0] if matches else None


def _assert_work_id_free_for(cursor, work_id, name, skip_staff_id=None):
    """確保目標工號沒有被「姓名對不起來」的另一筆記錄佔用,避免這支migration
    悄悄把工號設定錯誤或覆蓋到不相干的人身上。"""
    cursor.execute("SELECT id, name FROM staff WHERE work_id=%s", (work_id,))
    row = cursor.fetchone()
    if row is None:
        return
    existing_id, existing_name = row
    if skip_staff_id is not None and existing_id == skip_staff_id:
        return
    if _norm(existing_name) != _norm(name):
        raise RuntimeError(
            f"工號「{work_id}」已經被員工「{existing_name}」(id={existing_id})使用,"
            f"跟這次要設定的「{name}」對不起來,migration中止,請人工確認實際狀況。"
        )


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()把SQL裡的
    # 冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),本機SQLite
    # 開發改schema.sql、由init_schema()直接建表+灌種子資料,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    placeholder_password = _PLACEHOLDER_BIRTHDAY.replace("-", "")[2:8]
    placeholder_hash = generate_password_hash(placeholder_password)

    # ---------------- 老闆/股東/主管(10人) ----------------
    cursor.execute("SELECT id, name, work_id, role FROM staff WHERE role IN ('cs','manager','boss')")
    admin_rows = cursor.fetchall()

    for name, work_id, role in _ADMIN_ASSIGNMENTS:
        match = _find_match(admin_rows, name)
        if match:
            staff_id = match[0]
            _assert_work_id_free_for(cursor, work_id, name, skip_staff_id=staff_id)
            cursor.execute(
                "UPDATE staff SET work_id=%s, role=%s WHERE id=%s",
                (work_id, role, staff_id),
            )
        else:
            _assert_work_id_free_for(cursor, work_id, name)
            cursor.execute(
                """INSERT INTO staff (work_id, name, phone, birthday, password_hash, role, branch)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (work_id, name, None, _PLACEHOLDER_BIRTHDAY, placeholder_hash, role, _PLACEHOLDER_BRANCH),
            )

    # ---------------- Alois/Laco/Spin的額外教練身份 ----------------
    cursor.execute("SELECT id, name, work_id, role FROM staff WHERE role='coach'")
    coach_rows = cursor.fetchall()

    for name, work_id in _COACH_ASSIGNMENTS:
        match = _find_match(coach_rows, name)
        if match:
            staff_id = match[0]
            _assert_work_id_free_for(cursor, work_id, name, skip_staff_id=staff_id)
            cursor.execute(
                "UPDATE staff SET work_id=%s WHERE id=%s",
                (work_id, staff_id),
            )
        else:
            _assert_work_id_free_for(cursor, work_id, name)
            cursor.execute(
                """INSERT INTO staff (work_id, name, phone, birthday, password_hash, role, branch)
                   VALUES (%s, %s, %s, %s, %s, 'coach', %s)""",
                (work_id, name, None, _PLACEHOLDER_BIRTHDAY, placeholder_hash, _PLACEHOLDER_BRANCH),
            )

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # 這支migration異動的是「員工帳號」這種營運資料,不是單純的schema/固定設定值,
    # 而且downgrade沒辦法安全分辨「這筆記錄是這支migration新增的」還是「這支migration
    # 執行前就已經存在、只是被更新了工號/角色」——貿然刪除或還原工號/角色反而可能
    # 誤刪或誤改到真正的員工資料。這裡故意不做任何還原動作,如果真的需要downgrade,
    # 請直接告訴我需要復原成什麼狀態,用另一支migration處理。
    pass
