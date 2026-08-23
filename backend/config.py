"""
集中管理環境變數/金鑰設定。

原則：任何金鑰、密碼、正式環境才有的設定值，一律只從環境變數讀取，
程式碼裡不寫死任何真實金鑰(只給開發用的假值/None預設值)。正式環境
(Render/Zeabur等)請在該平台的環境變數設定畫面填入這些值，不要寫進
程式碼或.env檔案後commit進版控。

本機開發可以複製 .env.example 為 .env 並填入測試值，配合
python-dotenv(見下面的load_dotenv)自動載入。
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()  # 本機開發時自動讀取 .env 檔案；正式環境通常由平台直接注入環境變數，
                    # 找不到.env檔案也不會報錯，不影響正式環境運作。
except ImportError:
    pass


ENV = os.environ.get("ERSKI_ENV", "development")  # development / staging / production
IS_PRODUCTION = ENV == "production"

# ------------------------------------------------------------------
# 資料庫(實際連線邏輯在db.py，這裡只是給其他模組需要時可以查閱同一個值)
# ------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# ------------------------------------------------------------------
# 綠界ECPay(尚未申請商店帳號前，這些都會是None，payments.py會因此
# 繼續使用MockPaymentProvider；申請到商店代號/金鑰後，把這三個環境變數
# 設定好，並在payments.py實作真正的EcpayProvider後即可切換)
# ------------------------------------------------------------------
ECPAY_MERCHANT_ID = os.environ.get("ECPAY_MERCHANT_ID")
ECPAY_HASH_KEY = os.environ.get("ECPAY_HASH_KEY")
ECPAY_HASH_IV = os.environ.get("ECPAY_HASH_IV")
# 綠界測試環境/正式環境的API網域不同，用這個切換，正式上線前務必確認是'production'
ECPAY_MODE = os.environ.get("ECPAY_MODE", "test")  # test / production
ECPAY_CONFIGURED = bool(ECPAY_MERCHANT_ID and ECPAY_HASH_KEY and ECPAY_HASH_IV)

# ------------------------------------------------------------------
# 第三方登入(LINE Login / Google OAuth)，尚未申請前為None，
# auth.py會繼續使用mock_oauth_login的模擬邏輯
# ------------------------------------------------------------------
LINE_CHANNEL_ID = os.environ.get("LINE_CHANNEL_ID")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
OAUTH_CONFIGURED = bool((LINE_CHANNEL_ID and LINE_CHANNEL_SECRET) or
                         (GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET))

# ------------------------------------------------------------------
# Flask本身的密鑰，用來簽發會員/員工登入token(見authtoken.py)。
# 沒有設定時authtoken.py會fallback成一組寫死在程式碼裡的開發用預設值並印出警告，
# 正式環境務必設定，否則任何人都能自己簽出合法登入token。
# ------------------------------------------------------------------
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")


def validate_for_production():
    """正式環境啟動時可以呼叫這個函式，及早發現「忘記設定環境變數」的問題，
    而不是等使用者實際觸發某個功能時才在深處噴錯。呼叫方式可參考
    README_部署交接指南.md。"""
    problems = []
    if not DATABASE_URL:
        problems.append("DATABASE_URL 未設定(正式環境不能用本機SQLite檔案)")
    elif DATABASE_URL.startswith("sqlite"):
        problems.append("DATABASE_URL 指向SQLite，正式環境應該用PostgreSQL")
    if not FLASK_SECRET_KEY:
        problems.append("FLASK_SECRET_KEY 未設定(會員/員工登入token會用不安全的開發用預設密鑰簽發，"
                         "任何人都能自己偽造合法登入token，務必設定一組隨機字串，"
                         "可用 python3 -c \"import secrets; print(secrets.token_hex(32))\" 產生)")
    if not ECPAY_CONFIGURED:
        problems.append("綠界金鑰未設定(ECPAY_MERCHANT_ID/ECPAY_HASH_KEY/ECPAY_HASH_IV)，"
                         "目前金流會繼續用模擬付款，正式營運前必須設定並實作真正的EcpayProvider")
    if not OAUTH_CONFIGURED:
        problems.append("LINE/Google OAuth憑證未設定，目前登入會繼續用模擬帳號，"
                         "正式營運前必須至少設定一種真實登入方式")
    return problems


if __name__ == "__main__":
    print(f"目前環境(ERSKI_ENV): {ENV}")
    problems = validate_for_production()
    if not problems:
        print("正式環境設定檢查:全部通過")
    else:
        print("正式環境設定檢查:發現以下問題尚未設定 —")
        for p in problems:
            print(f"  - {p}")
