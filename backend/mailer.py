"""
Email寄送。目前只用在會員「忘記密碼」的重設密碼信(見auth.request_password_reset_email),
以後如果要加上訂單通知等其他Email用途,可以直接重用這支模組的send_email()。

用Resend(https://resend.com)這家Email API服務,詳見config.py開頭那段說明(選用理由/
申請步驟)。故意不裝Resend官方的Python SDK,改用Python內建的urllib直接打它的REST
API,跟auth.py呼叫LINE/Google OAuth API的做法一致,不多增加一個套件相依。

尚未設定RESEND_API_KEY前,config.MAIL_CONFIGURED會是False,呼叫send_email()會直接
丟出RuntimeError——呼叫端請自行判斷config.MAIL_CONFIGURED,不要在沒設定時還呼叫。
"""

import json
import urllib.error
import urllib.request

import config

_RESEND_ENDPOINT = "https://api.resend.com/emails"


def send_email(to_email: str, subject: str, html_body: str):
    """透過Resend寄一封HTML格式的信。任何一步失敗(未設定API Key、網路連不到Resend、
    Resend拒絕這次請求,例如寄件網域尚未驗證通過)都會丟出RuntimeError,呼叫端接住後
    自行決定要不要讓使用者知道(忘記密碼這個情境刻意不讓使用者知道寄信是否成功,
    避免被用來反查Email是否註冊過,詳見auth.request_password_reset_email的說明)。"""
    if not config.MAIL_CONFIGURED:
        raise RuntimeError("尚未設定RESEND_API_KEY,無法寄送Email(見config.py開頭說明的申請步驟)")

    payload = json.dumps({
        "from": config.MAIL_FROM,
        "to": [to_email],
        "subject": subject,
        "html": html_body,
    }).encode("utf-8")
    req = urllib.request.Request(
        _RESEND_ENDPOINT, data=payload, method="POST",
        headers={
            "Authorization": f"Bearer {config.RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Resend寄信失敗(HTTP {e.code}):{detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"連線到Resend失敗:{e.reason}")
