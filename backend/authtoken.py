"""
簽發與驗證登入token(會員/員工),取代原本「後端直接信任前端傳來的member_id欄位、
或是X-Staff-Id這個沒有簽章保護的工號」的作法。

背景(2026-08實測發現的問題,詳見README_部署交接指南.md第二節):
之前的寫法是前端直接在request body/path帶member_id,後端完全沒有驗證「傳這個
member_id的人是不是這個會員本人」;員工端也只是檢查X-Staff-Id這個工號字串在
資料庫裡存不存在、有沒有啟用,沒有任何簽章保護,任何人知道/猜到一個工號或
member_id數字就能發API請求冒用身分。這支模組把「登入」這件事變成:登入成功後
發一組簽章過的token給前端,之後每個需要身分驗證的請求都要附上這組token,後端
驗證token本身有沒有被竄改、有沒有過期,不再相信前端直接聲稱的身分。

用itsdangerous(Flask本身的相依套件,不需要額外安裝/新增requirements.txt)做
簽章與時效驗證,是無狀態(stateless)token,不是Django/Flask-Login那種需要在
資料庫或記憶體存session的機制:
1. token不是偽造的(沒有正確SECRET_KEY簽不出合法token,竄改內容會讓簽章失敗)
2. token有時效,過期後即使簽章正確也會被拒絕,不需要額外實作「登出/撤銷」機制
3. 伺服器不用記錄哪些token目前有效,重啟/gunicorn多個worker都不受影響,
   只要所有worker用同一組SECRET_KEY(用環境變數設定,天生就是所有worker共用同一份)

⚠️正式環境務必透過環境變數FLASK_SECRET_KEY設定一組固定亂數值(見.env.example,
可用 `python3 -c "import secrets; print(secrets.token_hex(32))"` 產生)。
沒有設定的話會fallback成一組寫在程式碼裡的固定字串——這組字串因為是公開原始碼
的一部分,正式環境如果沒有覆蓋掉它,等於任何人都能自己簽出合法token,完全沒有
保護效果,啟動時只會印出警告,不會擋下啟動(避免忘記設定時整個服務直接掛掉),
但務必在正式營運前確認這組警告沒有出現在啟動log裡。
"""

import secrets
import warnings

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

import config

_DEV_FALLBACK_SECRET = "erski-dev-only-insecure-secret-請勿在正式環境使用這組值"

if config.FLASK_SECRET_KEY:
    _SECRET_KEY = config.FLASK_SECRET_KEY
else:
    _SECRET_KEY = _DEV_FALLBACK_SECRET
    if config.IS_PRODUCTION:
        warnings.warn(
            "⚠️正式環境(ERSKI_ENV=production)沒有設定FLASK_SECRET_KEY環境變數,"
            "目前登入token使用的是寫在程式碼裡的開發用預設密鑰,任何人都可以自己"
            "簽出合法登入token,等於完全沒有身分驗證保護!請立即在環境變數設定"
            "一組隨機字串(可用 python3 -c \"import secrets; print(secrets.token_hex(32))\" 產生)。"
        )

# 用不同的salt讓「員工token」跟「會員token」即使密鑰相同也不能互相冒用
# (例如拿到一組會員token沒辦法拿去當員工token用)。
_STAFF_SERIALIZER = URLSafeTimedSerializer(_SECRET_KEY, salt="erski-staff-token")
_MEMBER_SERIALIZER = URLSafeTimedSerializer(_SECRET_KEY, salt="erski-member-token")

STAFF_TOKEN_MAX_AGE = 8 * 3600           # 員工token有效期限:8小時,過期需要重新登入
MEMBER_TOKEN_MAX_AGE = 30 * 24 * 3600    # 會員token有效期限:30天(會員登入頻率低,不用像員工那麼短)


def issue_staff_token(work_id: str) -> str:
    return _STAFF_SERIALIZER.dumps({"work_id": work_id})


def verify_staff_token(token):
    """回傳token內的work_id字串;token是None/被竄改/過期時回傳None(不拋例外,方便呼叫端直接判斷)。"""
    if not token:
        return None
    try:
        data = _STAFF_SERIALIZER.loads(token, max_age=STAFF_TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("work_id")


def issue_member_token(member_id: int) -> str:
    return _MEMBER_SERIALIZER.dumps({"member_id": member_id})


def verify_member_token(token):
    """回傳token內的member_id(int);token是None/被竄改/過期時回傳None。"""
    if not token:
        return None
    try:
        data = _MEMBER_SERIALIZER.loads(token, max_age=MEMBER_TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("member_id")


# ------------------------------------------------------------------
# 2026-09新增:Google/LINE正式OAuth登入用的2組短效期簽章token。
#
# 這兩組都是無狀態(stateless)簽章token,跟上面員工/會員token同一種做法,
# 差別只在效期很短(幾十秒到10分鐘),伺服器不用另外開資料表記錄「這組token
# 有沒有被用過」——好處是不用改資料庫結構、不受多worker/重啟影響;代價是
# 嚴格來說「時效內可以重複使用」,不是真正一次性的驗證碼。因為這兩組token
# 只在使用者自己瀏覽器完成OAuth登入的當下幾秒鐘內用得到,不是給外部系統
# 呼叫的長期憑證,這個權衡是可以接受的,詳見README說明。
# ------------------------------------------------------------------
_OAUTH_STATE_SERIALIZER = URLSafeTimedSerializer(_SECRET_KEY, salt="erski-oauth-state")
_OAUTH_EXCHANGE_SERIALIZER = URLSafeTimedSerializer(_SECRET_KEY, salt="erski-oauth-exchange")

OAUTH_STATE_MAX_AGE = 600      # state:防CSRF用,使用者要在10分鐘內完成Google那邊的同意畫面操作
OAUTH_EXCHANGE_MAX_AGE = 60    # exchange_code:Google導回我們網站後,前端要在60秒內呼叫
                                # /api/auth/google/exchange換成真正的會員token,避免真正的
                                # token出現在網址列/瀏覽器紀錄裡太久


def issue_oauth_state(provider: str) -> str:
    return _OAUTH_STATE_SERIALIZER.dumps({"provider": provider, "nonce": secrets.token_hex(8)})


def verify_oauth_state(state, expected_provider: str) -> bool:
    """驗證從Google/LINE導回來的state參數:簽章正確、沒過期、provider對得上,三者都成立
    才算合法(防止CSRF——有人自己組一個假的callback網址,誘騙已登入使用者的瀏覽器去點)。"""
    if not state:
        return False
    try:
        data = _OAUTH_STATE_SERIALIZER.loads(state, max_age=OAUTH_STATE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return False
    return data.get("provider") == expected_provider


def issue_oauth_exchange_code(payload: dict) -> str:
    return _OAUTH_EXCHANGE_SERIALIZER.dumps(payload)


def verify_oauth_exchange_code(code):
    """回傳exchange_code內的payload(dict);code是None/被竄改/過期時回傳None。"""
    if not code:
        return None
    try:
        return _OAUTH_EXCHANGE_SERIALIZER.loads(code, max_age=OAUTH_EXCHANGE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


# ------------------------------------------------------------------
# 2026-09-22新增:會員「忘記密碼」用的重設密碼連結token。一樣是無狀態簽章token,
# 跟上面幾組做法相同(伺服器不用另外開資料表記錄「這組連結有沒有被用過」),
# 效期刻意設定得比OAuth exchange_code長(使用者要先離開網站去收信,不會在幾十秒內
# 完成),但也不能太長,避免信箱萬一外洩時的風險視窗拖太久,30分鐘是常見的折衷值。
# ------------------------------------------------------------------
_PASSWORD_RESET_SERIALIZER = URLSafeTimedSerializer(_SECRET_KEY, salt="erski-password-reset")
PASSWORD_RESET_MAX_AGE = 30 * 60  # 重設密碼連結:30分鐘內有效,逾時需要重新申請


def issue_password_reset_token(member_id: int) -> str:
    return _PASSWORD_RESET_SERIALIZER.dumps({"member_id": member_id})


def verify_password_reset_token(token):
    """回傳token內的member_id(int);token是None/被竄改/過期時回傳None。"""
    if not token:
        return None
    try:
        data = _PASSWORD_RESET_SERIALIZER.loads(token, max_age=PASSWORD_RESET_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("member_id")
