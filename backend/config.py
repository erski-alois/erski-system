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
# Google Cloud Console「已授權的重新導向URI」填的網址必須跟這裡完全一致(逐字元比對,
# 差一個斜線都會被Google拒絕)。預設值是正式站網址,本機開發環境沒辦法真的完成整個
# OAuth流程(Google Console只登記了正式網址一筆,而且這個開發環境對外連線也連不到
# Google的伺服器),要在本機測試需要另外用環境變數覆蓋成ngrok之類的臨時對外網址。
GOOGLE_OAUTH_REDIRECT_URI = os.environ.get(
    "GOOGLE_OAUTH_REDIRECT_URI", "https://app.erskischool.com/api/auth/google/callback"
)
GOOGLE_OAUTH_CONFIGURED = bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)
# LINE Developers Console的「Callback URL」填的網址必須跟這裡完全一致,道理跟上面
# GOOGLE_OAUTH_REDIRECT_URI一樣。
LINE_OAUTH_REDIRECT_URI = os.environ.get(
    "LINE_OAUTH_REDIRECT_URI", "https://app.erskischool.com/api/auth/line/callback"
)
LINE_OAUTH_CONFIGURED = bool(LINE_CHANNEL_ID and LINE_CHANNEL_SECRET)
OAUTH_CONFIGURED = bool(GOOGLE_OAUTH_CONFIGURED or LINE_OAUTH_CONFIGURED)

# ------------------------------------------------------------------
# Flask本身的密鑰，用來簽發會員/員工登入token(見authtoken.py)。
# 沒有設定時authtoken.py會fallback成一組寫死在程式碼裡的開發用預設值並印出警告，
# 正式環境務必設定，否則任何人都能自己簽出合法登入token。
# ------------------------------------------------------------------
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")

# ------------------------------------------------------------------
# Cloudflare R2(物件儲存，用來放教練宣傳照/證件照等圖片檔案)。
# 尚未申請/設定前這些都會是None，storage_r2.py會回報「尚未設定」，
# 相關上傳功能會繼續沿用目前「檔案內容直接存進資料庫(file_data欄位)」的舊做法，
# 不會因為沒設定R2就整個壞掉。
# ------------------------------------------------------------------
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")
# 對外可直接存取圖片的網域，例如R2的Public Development URL(*.r2.dev)或你自己綁定的網域，
# 結尾不要加斜線。之後圖片網址會是 R2_PUBLIC_BASE_URL + "/" + 檔案在bucket裡的路徑。
R2_PUBLIC_BASE_URL = os.environ.get("R2_PUBLIC_BASE_URL", "").rstrip("/")
R2_CONFIGURED = bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET_NAME)

# 資料庫每日自動備份專用的另一個獨立bucket(故意跟上面教練照片的R2_BUCKET_NAME
# 分開，這個bucket不應該開啟Public Development URL，備份內容不能公開存取)。
# 沿用同一組R2帳號金鑰(R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY)，
# 只是多指定一個bucket名稱。見backend/scripts/backup_to_r2.py。
R2_BACKUP_BUCKET_NAME = os.environ.get("R2_BACKUP_BUCKET_NAME")
R2_BACKUP_CONFIGURED = bool(R2_CONFIGURED and R2_BACKUP_BUCKET_NAME)

# ------------------------------------------------------------------
# Sentry(錯誤監控)。尚未申請/設定前是None，app.py開頭的sentry_sdk.init()
# 就完全不會執行，系統照常運作，只是不會有「未預期錯誤自動通知」這個功能。
# ------------------------------------------------------------------
SENTRY_DSN = os.environ.get("SENTRY_DSN")
SENTRY_CONFIGURED = bool(SENTRY_DSN)

# ------------------------------------------------------------------
# Email寄送(Resend, https://resend.com)，目前只用在會員「忘記密碼」的重設密碼信
# (見mailer.py/auth.request_password_reset_email)。選用Resend是因為免費額度
# 長期可用(每月3,000封、每天100封上限，不像部分同業近年改成只給60天試用)，
# 這個規模的用量(密碼重設信，之後可能加上訂單通知)綽綽有餘。
#
# 尚未申請/設定RESEND_API_KEY前，MAIL_CONFIGURED會是False，忘記密碼功能會回傳
# 明確錯誤訊息告知尚未開通(客服後台原本就能直接清除會員密碼，不受影響)。
#
# 設定步驟:
#   1. 到 https://resend.com 註冊帳號(不需要信用卡)
#   2. 「Domains」新增你們的網域(例如 erskischool.com 或 mail.erskischool.com)，
#      依畫面指示把幾筆DNS記錄(TXT/MX/CNAME)加到你們網域的DNS設定，等驗證通過
#      (通常幾分鐘到數小時，視DNS服務商而定)
#   3. 「API Keys」建立一組新的API Key
#   4. 在Render環境變數設定 RESEND_API_KEY(上一步的Key)、
#      MAIL_FROM(例如 "ERSKI 滑雪急診室 <noreply@erskischool.com>"，
#      @後面網域必須是上面第2步驗證過的網域)
# ------------------------------------------------------------------
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
MAIL_FROM = os.environ.get("MAIL_FROM", "ERSKI 滑雪急診室 <noreply@erskischool.com>")
MAIL_CONFIGURED = bool(RESEND_API_KEY)

# 重設密碼信裡的連結網址前綴，預設跟GOOGLE_OAUTH_REDIRECT_URI/LINE_OAUTH_REDIRECT_URI
# 一樣指向正式站網址；本機開發或有獨立網址的環境可用環境變數覆蓋。
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://app.erskischool.com").rstrip("/")
# ------------------------------------------------------------------
# TurboPlus 營運鏡像同步
# ------------------------------------------------------------------
# Render/PostgreSQL 是唯一的主資料來源。TP 端只會以這組獨立金鑰「主動拉取」
# 已過濾的營運鏡像資料，絕不透過此介面回寫會員、訂單、付款或堂數。
# 金鑰只能放在 Render 的環境變數與 TP 本機同步程式的設定檔，不能寫進 Git、
# 前端程式碼或任何 TP 頁面。未設定時同步 API 會完全停用。
TP_SYNC_SHARED_SECRET = os.environ.get("TP_SYNC_SHARED_SECRET", "").strip()
TP_SYNC_CONFIGURED = bool(TP_SYNC_SHARED_SECRET)
try:
    TP_SYNC_MAX_PAGE_SIZE = max(1, min(int(os.environ.get("TP_SYNC_MAX_PAGE_SIZE", "200")), 500))
except ValueError:
    TP_SYNC_MAX_PAGE_SIZE = 200


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
    if not R2_CONFIGURED:
        problems.append("Cloudflare R2憑證未設定(R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/"
                         "R2_SECRET_ACCESS_KEY/R2_BUCKET_NAME)，圖片上傳功能會繼續把檔案"
                         "直接存進資料庫，可以先這樣運作，之後有空再設定R2也不影響現有資料")
    if not SENTRY_CONFIGURED:
        problems.append("SENTRY_DSN未設定，系統出錯時不會自動通知，只能等客戶回報才知道，"
                         "建議盡快到sentry.io申請免費帳號並設定")
    if not R2_BACKUP_CONFIGURED:
        problems.append("R2_BACKUP_BUCKET_NAME未設定，每日自動備份到Cloudflare R2的排程工具"
                         "(backend/scripts/backup_to_r2.py)會執行失敗，目前只能依賴Render本身"
                         "3天的PITR還原窗口，建議盡快在Cloudflare另外建立一個不公開的bucket並設定")
    if not MAIL_CONFIGURED:
        problems.append("RESEND_API_KEY未設定，會員「忘記密碼」自助重設功能會顯示尚未開通，"
                         "客服後台仍可直接幫會員清除密碼(等同原本的處理方式)，不受影響，"
                         "建議盡快到resend.com申請免費帳號並設定，步驟見上面說明")
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
