"""insurance_brackets新增勞保/健保/勞退雇主負擔欄位,並更新為115年(2026年)最新投保級距數據;
coach_payroll_records新增對應的雇主負擔欄位

依你的指示「後台薪資管理勞健保投保級距表請參考勞保局及健保局分別修正勞保、勞退及健保費
公司負擔及自付額」,分成兩部分:

① insurance_brackets(勞健保投保級距表,後台「薪資管理」分頁可直接編輯的那張表)——
原本只有labor_insurance_employee/health_insurance_employee兩欄(員工自付額),而且
資料是舊的(最高級距43,900元,對應109~114年間的舊制),這次:
  - 新增labor_insurance_employer(勞保雇主負擔)、health_insurance_employer(健保雇主
    負擔)、pension_employer(勞退雇主提繳,原本完全沒有這個項目)三個欄位。
  - 整批清空重建成115年(2026年)最新的11級投保薪資分級表(最高45,800元,115.1.1起
    生效,基本工資調升至29,500元)——這是勞保「普通事故+就業保險」這個級距表本身的
    法定級距數量(不論實際薪資多高,投保薪資都會封頂在45,800元這一級,所以這11級
    對勞保這個項目來說是「完整」的,不會有超出範圍的情況)。數字來源:勞保費率12.5%
    (普通事故11.5%+就業保險1%,員工負擔20%/雇主負擔70%/政府負擔10%);健保費率
    5.17%(被保險人本人負擔30%/投保單位負擔60%/政府負擔10%,健保署「公、民營事業、
    機構及有一定雇主之受僱者(115.1.1生效)」保險費負擔金額表);勞退雇主強制提繳率6%
    (以「月提繳工資分級表」115.1.1生效版本裡,跟勞保投保薪資這11級落在同一區間的
    對應級距金額計算,兩份級距表在這個薪資區間剛好是同樣的11個級距金額)。

  這裡有一件事要說清楚:健保投保金額分級表本身實際上不只11級,薪資更高的被保險人
  還有更高的級距(最高到31萬多),但因為ER Ski目前用這張表的地方(教練薪資的勞健保
  參考值)實際薪資範圍不會用到那麼高,這次沒有把健保/勞退更高的級距也一併建進來;
  如果之後有教練或員工的基本薪資超過45,800元,系統會依既有的「找不到落點時取最接近
  一筆」的查詢邏輯,套用這裡最高一筆(第11級)的健保/勞退參考值,這種情況下健保/勞退
  金額可能會偏低於實際應繳金額(勞保部分則不受影響,因為45,800元本來就是勞保法定封頂
  級距,不會低估),請留意這種情況、需要的話用後台既有的「人工覆蓋」欄位手動修正,或
  告訴我要不要把表格往上延伸更多級距。

② coach_payroll_records(每位教練每月的薪資紀錄)——原本只存labor_insurance/
  health_insurance這兩個「員工自付額」欄位(從薪資裡扣除,影響教練實際所得),完全沒有
  記錄「公司負擔」這部分金額,導致公司實際負擔的教練人事成本(月結損益裡的「教練薪資
  支出」)被低估——這是勞健保/勞退雇主負擔的部分,雖然不會影響教練拿到的實際所得,
  但是公司真實會發生的成本。這次新增labor_insurance_employer/health_insurance_employer/
  pension_employer三個欄位,存放依級距表帶出的雇主負擔參考值(可比照原本員工自付額的
  做法,在薪資管理分頁人工覆蓋)。

Revision ID: 9cf25a805f20
Revises: 1e1b602c542f
Create Date: 2026-09-21 11:06:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '9cf25a805f20'
down_revision: Union[str, Sequence[str], None] = '1e1b602c542f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 115年(2026年)勞保投保薪資分級表(11級,115.1.1生效,最高45,800元),搭配同一區間內
# 健保投保金額分級表、勞退月提繳工資分級表的對應級距金額,合併成一張表:
# (bracket_min, bracket_max, insured_salary,
#  labor_insurance_employee, labor_insurance_employer,
#  health_insurance_employee, health_insurance_employer,
#  pension_employer)
_BRACKETS_2026 = [
    (0,     29500,     29500, 738,  2582, 458, 1428, 1770),
    (29501, 30300,     30300, 758,  2651, 470, 1466, 1818),
    (30301, 31800,     31800, 795,  2783, 493, 1539, 1908),
    (31801, 33300,     33300, 833,  2914, 516, 1611, 1998),
    (33301, 34800,     34800, 870,  3045, 540, 1684, 2088),
    (34801, 36300,     36300, 908,  3176, 563, 1757, 2178),
    (36301, 38200,     38200, 955,  3342, 592, 1849, 2292),
    (38201, 40100,     40100, 1002, 3509, 622, 1940, 2406),
    (40101, 42000,     42000, 1050, 3675, 651, 2032, 2520),
    (42001, 43900,     43900, 1098, 3841, 681, 2124, 2634),
    (43901, 999999999, 45800, 1145, 4008, 710, 2216, 2748),
]


def upgrade() -> None:
    """Upgrade schema."""
    connection = op.get_bind().connection
    cursor = connection.cursor()

    cursor.execute("ALTER TABLE insurance_brackets ADD COLUMN IF NOT EXISTS labor_insurance_employer INTEGER NOT NULL DEFAULT 0")
    cursor.execute("ALTER TABLE insurance_brackets ADD COLUMN IF NOT EXISTS health_insurance_employer INTEGER NOT NULL DEFAULT 0")
    cursor.execute("ALTER TABLE insurance_brackets ADD COLUMN IF NOT EXISTS pension_employer INTEGER NOT NULL DEFAULT 0")

    cursor.execute("ALTER TABLE coach_payroll_records ADD COLUMN IF NOT EXISTS labor_insurance_employer INTEGER NOT NULL DEFAULT 0")
    cursor.execute("ALTER TABLE coach_payroll_records ADD COLUMN IF NOT EXISTS health_insurance_employer INTEGER NOT NULL DEFAULT 0")
    cursor.execute("ALTER TABLE coach_payroll_records ADD COLUMN IF NOT EXISTS pension_employer INTEGER NOT NULL DEFAULT 0")

    # 這張表整份是「對照勞保局/健保局最新公告的參考數據」,不是逐筆累積的營運資料,
    # 舊的10級(最高43,900元,舊制)資料已經過時,直接整批清空重建成115年最新11級,
    # 不保留舊資料(這點跟原本前端「儲存級距表」本來就是整批覆蓋式儲存的設計一致)。
    cursor.execute("DELETE FROM insurance_brackets")
    for (bmin, bmax, insured, labor_emp, labor_er, health_emp, health_er, pension_er) in _BRACKETS_2026:
        cursor.execute(
            """INSERT INTO insurance_brackets
               (bracket_min, bracket_max, insured_salary,
                labor_insurance_employee, labor_insurance_employer,
                health_insurance_employee, health_insurance_employer, pension_employer)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (bmin, bmax, insured, labor_emp, labor_er, health_emp, health_er, pension_er),
        )

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # 這張表是「參考數據表」,downgrade不會試著還原成109~114年間的舊制數字(沒有意義,
    # 而且舊制數字已經過時,不建議真的用),只把新增的欄位移除。如果真的需要用舊制
    # 數字,請告訴我,我可以另外處理。
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute("ALTER TABLE insurance_brackets DROP COLUMN IF EXISTS labor_insurance_employer")
    cursor.execute("ALTER TABLE insurance_brackets DROP COLUMN IF EXISTS health_insurance_employer")
    cursor.execute("ALTER TABLE insurance_brackets DROP COLUMN IF EXISTS pension_employer")
    cursor.execute("ALTER TABLE coach_payroll_records DROP COLUMN IF EXISTS labor_insurance_employer")
    cursor.execute("ALTER TABLE coach_payroll_records DROP COLUMN IF EXISTS health_insurance_employer")
    cursor.execute("ALTER TABLE coach_payroll_records DROP COLUMN IF EXISTS pension_employer")
    connection.commit()
