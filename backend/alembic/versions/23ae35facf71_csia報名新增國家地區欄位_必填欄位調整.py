"""CSIA報名新增國家/地區欄位(結構變更僅此一項,其餘為應用層邏輯)

依你的指示這次改了6件事,但只有第1件牽涉資料庫結構變更,其餘5件都是應用層
(csia.py/app.py/前端)的驗證邏輯或功能,不需要改資料表結構:

1. 地址填寫改成「國家/地區」下拉選單+學員自行輸入地址文字:新增
   address_country欄位(TEXT,可為NULL)。下拉選單本身只是拿來做分類用,
   地址還是由學員在原本就有的address_chinese/address_english欄位自行輸入
   文字,這兩個欄位這次沒有變動。

2. 手機號碼防呆:純應用層格式驗證(csia.py的_validate_phone_format),不需要
   改資料庫結構,mobile_number欄位型別維持TEXT不變。

3. CSIA會員編號改為必填、4. 緊急聯絡人姓名/電話改為必填:這兩項刻意沒有在
   資料庫層加NOT NULL限制——套用這支migration前,已經用Render的唯讀SQL
   查詢工具確認正式環境csia_registrations目前有2筆真實報名資料(id=1,2,
   兩筆都是「酆士豪」這個名字),而且這2筆的emergency_contact_name/
   emergency_contact_phone都是NULL(當時這兩個欄位還是選填的),如果在這裡
   加NOT NULL,migration套用時會直接失敗(既有資料不符合新限制)。改成只在
   應用層(csia.py的create_registration/admin_update_registration)擋新增/
   修改時必須填寫,舊資料維持原樣不受影響——這2筆真實報名的緊急聯絡人資料
   目前還是空的,請客服之後跟這位學員確認補齊,或透過後台新增的「編輯」
   功能手動補上。

5. 報名一個名字只能報一次:同樣是應用層檢查(csia.py的create_registration
   新增查詢),不是資料庫UNIQUE INDEX——因為套用這支migration前查到的正式
   環境資料,「酆士豪」這個名字剛好已經對同一場次(course_id=11)重複報名
   了2筆(id=1和id=2),如果加UNIQUE INDEX,migration套用時會直接因為既有
   資料違反限制而失敗。這兩筆重複資料要保留哪一筆、刪除哪一筆,是需要你
   確認的業務判斷,我不會在migration裡自動幫你決定刪除其中一筆——這次一併
   新增了後台「刪除報名」功能,請你到後台CSIA報名管理確認這2筆(id=1、2)
   實際狀況後,用新增的刪除按鈕手動處理其中一筆重複的。

6. 後台可以對報名考生進行修改、刪除及資料每個人整筆匯出:全部是csia.py新增
   函式(admin_update_registration擴充、新增admin_delete_registration、新增
   export_registration_csv)+app.py新增路由(DELETE /api/admin/csia/
   registrations/<id>、GET .../export),不涉及資料庫結構變更。

Revision ID: 23ae35facf71
Revises: 35c6bd2b2180
Create Date: 2026-09-20 10:15:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '23ae35facf71'
down_revision: Union[str, Sequence[str], None] = '35c6bd2b2180'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他CSIA migration一樣,直接拿底層DBAPI連線執行,避免SQLAlchemy的text()把
    # SQL裡的冒號誤判成具名綁定參數。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    # 新增國家/地區欄位,單純新增欄位,IF NOT EXISTS包起來確保重複套用不出錯。
    # 不設NOT NULL(既有2筆真實報名資料這個欄位當然是空的,報名時是必填的)。
    cursor.execute("ALTER TABLE csia_registrations ADD COLUMN IF NOT EXISTS address_country TEXT")

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute("ALTER TABLE csia_registrations DROP COLUMN IF EXISTS address_country")
    connection.commit()
