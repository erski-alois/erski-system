"""CSIA報名表單改版:地址整併+Waiver上傳+匯款帳號比照室內雪機

依你的指示這次改了3件事:

1. 通訊地址欄位整併:原本Street/City/Province/Country/Postal Code這5個外文地址
   子欄位,改成一欄「英文地址」(address_english),中文通訊地址(address_chinese)
   維持不變。套用這支migration前已經用Render的唯讀SQL查詢工具確認正式環境
   csia_registrations還是0筆(還沒有人報名過CSIA),所以可以安全移除這5個子欄位,
   不會有任何既有報名資料的地址欄位被清空或對不上的風險。

2. 新增Waiver上傳:CSIA官方Waiver(https://csiajapan.com/csiawaiver/)線上填寫完成
   後,學員需要把填完的檔案上傳回來,新增waiver_file_name/waiver_mime_type/
   waiver_image三個欄位,存放方式完全比照原本就有的membership_card_file_name/
   membership_card_mime_type/membership_card_image(會員卡上傳)那一組欄位。

3. CSIA匯款帳號比照室內雪機帳號:把pricing_config的bank_account_csia的銀行/
   代碼/帳號/戶名,直接從bank_account_indoor複製過來(這支migration套用時,正式
   環境當下bank_account_indoor實際設定的值是多少,就複製多少,程式碼本身完全不會
   寫死或看到真正的銀行帳號數字),並把note欄位改成提醒會員匯款後回報帳號後5碼,
   跟室內雪機既有的「用note欄位提醒客戶」做法一致,不用另外開發新的欄位或功能。
   這是一次性複製,不是「以後室內雪機帳號一改CSIA就自動跟著變」的即時連動——如果
   之後要改成兩邊帳號永遠自動同步,請告訴我,需要另外調整架構。

Revision ID: 35c6bd2b2180
Revises: 0a7dca1b851d
Create Date: 2026-09-20 08:40:44.217964

"""
import json
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '35c6bd2b2180'
down_revision: Union[str, Sequence[str], None] = '0a7dca1b851d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CSIA_BANK_NOTE = "匯款完成後,請將匯款帳號後5碼回報給客服,方便核對入帳、加速確認報名。"


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他CSIA migration一樣,直接拿底層DBAPI連線執行,避免SQLAlchemy的text()把SQL
    # 裡的冒號誤判成具名綁定參數。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    # 1. Waiver上傳三個欄位,新增,IF NOT EXISTS包起來確保重複套用不出錯。
    cursor.execute("ALTER TABLE csia_registrations ADD COLUMN IF NOT EXISTS waiver_file_name TEXT")
    cursor.execute("ALTER TABLE csia_registrations ADD COLUMN IF NOT EXISTS waiver_mime_type TEXT")
    cursor.execute("ALTER TABLE csia_registrations ADD COLUMN IF NOT EXISTS waiver_image TEXT")

    # 2. 地址欄位整併:新增address_english,移除5個外文地址子欄位(套用前已確認
    #    production的csia_registrations是0筆,安全移除)。
    cursor.execute("ALTER TABLE csia_registrations ADD COLUMN IF NOT EXISTS address_english TEXT")
    cursor.execute("ALTER TABLE csia_registrations DROP COLUMN IF EXISTS address_street")
    cursor.execute("ALTER TABLE csia_registrations DROP COLUMN IF EXISTS address_city")
    cursor.execute("ALTER TABLE csia_registrations DROP COLUMN IF EXISTS address_country")
    cursor.execute("ALTER TABLE csia_registrations DROP COLUMN IF EXISTS address_province")
    cursor.execute("ALTER TABLE csia_registrations DROP COLUMN IF EXISTS address_postal_code")

    # 3. CSIA匯款帳號比照室內雪機:讀出bank_account_indoor目前的值,把銀行/代碼/
    #    帳號/戶名複製給bank_account_csia,note改成回報後5碼的提醒。用Python讀出
    #    JSON字串處理、再寫回去,不在SQL裡直接操作JSON欄位,邏輯比較清楚也比較好debug。
    cursor.execute("SELECT config_value FROM pricing_config WHERE config_key='bank_account_indoor'")
    indoor_row = cursor.fetchone()
    if indoor_row:
        indoor_config = json.loads(indoor_row[0])
        csia_config = {
            "bank_name": indoor_config.get("bank_name", ""),
            "bank_code": indoor_config.get("bank_code", ""),
            "account_number": indoor_config.get("account_number", ""),
            "account_name": indoor_config.get("account_name", ""),
            "note": _CSIA_BANK_NOTE,
        }
        cursor.execute(
            "UPDATE pricing_config SET config_value=%s WHERE config_key='bank_account_csia'",
            (json.dumps(csia_config),),
        )

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # 故意不做復原處理:
    # - 地址欄位整併如果復原,address_english裡已經填的資料沒有辦法自動拆回
    #   Street/City/Province/Country/Postal Code這5個子欄位,復原了也是空的,沒有意義。
    # - 匯款帳號複製本來就是一次性動作,downgrade也無法得知複製前bank_account_csia
    #   原本的值是什麼(套用migration前你這裡本來就是空白的預設值,復原成空白反而
    #   會讓已經在使用的CSIA報名頁面顯示「校方尚未設定匯款帳號」)。
    # 如果真的需要復原,請先告訴我,再手動個別處理。
    pass
