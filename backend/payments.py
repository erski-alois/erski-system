"""
金流抽象層
------------
所有金流商(綠界 ECPay / 藍新 NewebPay / Stripe...)都實作同一個
PaymentProvider 介面。正式串接時只需要新增一個 Provider class,
不需要更動任何 booking / route 的商業邏輯。

2026-08:已通過綠界特約商店審核,新增 EcpayProvider,正式串接「全方位金流」
(信用卡/網路ATM/ATM櫃員機)。是否啟用由 config.ECPAY_CONFIGURED 決定
(也就是 Render 環境變數 ECPAY_MERCHANT_ID / ECPAY_HASH_KEY / ECPAY_HASH_IV
是否都已設定):
  - 三個環境變數都有設定 -> active_provider 自動變成 EcpayProvider
  - 只要有一個沒設定(例如本機開發、還沒申請好)-> 自動fallback成
    MockPaymentProvider,不會噴錯,行為跟串接前一樣(模擬付款)。
「現場付款」「匯款轉帳」不管有沒有串接綠界,一律走原本的人工核帳流程
(awaiting_backoffice_review,等待客服在後台核准)。
"""

from abc import ABC, abstractmethod
import hashlib
import html as html_module
import urllib.parse
import uuid
from datetime import datetime

import config


class PaymentProvider(ABC):
    @abstractmethod
    def create_payment(self, amount: int, payment_method: str, order_ref: str) -> dict:
        """回傳 {'status': ..., 'provider_ref': str}。
        status 可能是:
          - 'confirmed':已確認付款完成(目前只有Mock的線上刷卡會走這個,
            真正金流一律要等使用者實際完成付款、由webhook回調才能確認)
          - 'awaiting_backoffice_review':需要客服人工核對入帳(現場付款/匯款轉帳)
          - 'redirect':需要導向使用者到金流商付款頁面完成付款(綠界信用卡/網路ATM/
            ATM櫃員機都是這種),呼叫端(app.py的/api/payments/create)看到這個
            status時,要把 provider_ref 組進 /api/payments/ecpay/checkout/<provider_ref>
            這個網址回傳給前端,由前端把瀏覽器導向過去。
        """
        raise NotImplementedError


class MockPaymentProvider(PaymentProvider):
    """開發/示範用途,或綠界金鑰尚未設定時的安全預設值。"""

    def create_payment(self, amount: int, payment_method: str, order_ref: str) -> dict:
        provider_ref = f"MOCK-{uuid.uuid4().hex[:10].upper()}"
        if payment_method == "online_card":
            # 正式串接時,這裡會呼叫金流商 API 並導向付款頁,
            # 由 webhook 回傳結果後才更新為 confirmed。
            return {"status": "confirmed", "provider_ref": provider_ref}
        else:
            # onsite / bank_transfer / webatm / atm(未串接真金流時)都需要人工核對入帳
            return {"status": "awaiting_backoffice_review", "provider_ref": provider_ref}


# ------------------------------------------------------------------
# 綠界(ECPay) AioCheckOut/V5
# ------------------------------------------------------------------
ECPAY_TEST_ENDPOINT = "https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5"
ECPAY_PRODUCTION_ENDPOINT = "https://payment.ecpay.com.tw/Cashier/AioCheckOut/V5"

# 我們自己(前端付款彈窗)的payment_method值 -> 綠界ChoosePayment參數值
ECPAY_CHOOSE_PAYMENT = {
    "online_card": "Credit",
    "webatm": "WebATM",
    "atm": "ATM",
}

# ATM櫃員機付款期限(天):超過這個天數虛擬帳號會失效,會員需要重新產生付款單。
ECPAY_ATM_EXPIRE_DAYS = 3


def _ecpay_urlencode_whole_string(raw: str) -> str:
    """對「整串」HashKey=...&k=v&...&HashIV=...做URL編碼(注意:是整串一起編碼,
    包含裡面的=和&分隔符號本身也會被編碼成%3D/%26,不是只編碼各個參數值後再用
    literal的&/=接起來——這點很容易搞錯,之前一版實作就是誤植成「只編碼各別的
    值」,實際拿綠界官方文件(developers.ecpay.com.tw/2902/)的範例參數組驗算,
    算出來的CheckMacValue對不起來,才發現要整串一起編碼)。
    綠界官方PHP SDK(github.com/ECPay/SDK_PHP)的UrlService其實是延續PHP
    urlencode()的行為,跟Python urllib.parse.quote_plus在一個地方不一樣:
    '~'這個字元PHP urlencode()會編碼成%7E,但Python quote_plus預設當作安全字元
    完全不編碼(quote_plus的safe參數只能新增安全字元、無法強制編碼預設安全字元,
    所以用replace手動補上)。編碼完後,以下7組是PHP urlencode()不會編碼、但
    Python quote_plus預設會編碼成%XX的符號,要轉回原字元,才會跟綠界一致。"""
    encoded = urllib.parse.quote_plus(raw).replace("~", "%7E")
    return (
        encoded.replace("%2D", "-")
        .replace("%5F", "_")
        .replace("%2E", ".")
        .replace("%21", "!")
        .replace("%2A", "*")
        .replace("%28", "(")
        .replace("%29", ")")
    )


def generate_check_mac_value(params: dict, hash_key: str, hash_iv: str) -> str:
    """依綠界官方演算法計算CheckMacValue(已對照官方文件的實際範例參數組驗算過,
    確認算出來的值跟官方公布的結果完全一致):
    1. 參數依名稱排序(不分大小寫,不含CheckMacValue本身)
    2. 串接成 HashKey=xxx&key1=val1&key2=val2&...&HashIV=yyy 這一整串明文
    3. 對「整串」做URL編碼(含=和&本身也會被編碼)
    4. 轉小寫
    5. SHA256
    6. 轉大寫
    """
    clean = {k: v for k, v in params.items() if k != "CheckMacValue" and v is not None}
    items = sorted(clean.items(), key=lambda kv: kv[0].lower())
    raw = f"HashKey={hash_key}&" + "&".join(f"{k}={v}" for k, v in items) + f"&HashIV={hash_iv}"
    encoded = _ecpay_urlencode_whole_string(raw)
    return hashlib.sha256(encoded.lower().encode("utf-8")).hexdigest().upper()


def verify_check_mac_value(params: dict, hash_key: str, hash_iv: str) -> bool:
    """驗證綠界webhook(ReturnURL/PaymentInfoURL)回調帶來的CheckMacValue是否正確,
    避免有心人士偽造callback、繞過真正付款直接把訂單標記為已付款。"""
    received = str(params.get("CheckMacValue", "")).upper()
    if not received:
        return False
    expected = generate_check_mac_value(params, hash_key, hash_iv)
    return received == expected


class EcpayProvider(PaymentProvider):
    """正式串接綠界(ECPay)全方位金流:信用卡(Credit)/網路ATM(WebATM)/ATM櫃員機(ATM)。

    信用卡、網路ATM:使用者在綠界頁面操作完成後「同步」由ReturnURL回調確認結果。
    ATM櫃員機:「非同步」——使用者送出後綠界先呼叫PaymentInfoURL回傳一組虛擬帳號,
    使用者實際匯款完成後(可能是好幾天後,直到繳費期限前),綠界才會呼叫ReturnURL
    確認實際入帳,兩支webhook要分開處理。
    """

    def __init__(self, merchant_id, hash_key, hash_iv, mode="test"):
        self.merchant_id = merchant_id
        self.hash_key = hash_key
        self.hash_iv = hash_iv
        self.endpoint = ECPAY_PRODUCTION_ENDPOINT if mode == "production" else ECPAY_TEST_ENDPOINT

    def create_payment(self, amount: int, payment_method: str, order_ref: str) -> dict:
        if payment_method not in ECPAY_CHOOSE_PAYMENT:
            # 現場付款/匯款轉帳不透過綠界,維持原本人工核帳流程
            return {"status": "awaiting_backoffice_review", "provider_ref": f"OFFLINE-{uuid.uuid4().hex[:10].upper()}"}
        # 綠界MerchantTradeNo規定只能是英數字、長度上限20碼、同一特店底下不能重複。
        merchant_trade_no = ("ERSKI" + uuid.uuid4().hex[:15]).upper()[:20]
        return {"status": "redirect", "provider_ref": merchant_trade_no}

    def build_checkout_html(self, merchant_trade_no, amount, payment_method, item_name,
                             return_url, payment_info_url, client_back_url):
        """組出「自動送出的表單頁面」的HTML:使用者的瀏覽器載入這頁後會自動POST到
        綠界的AioCheckOut網址,顯示綠界的付款頁面。"""
        choose_payment = ECPAY_CHOOSE_PAYMENT.get(payment_method, "ALL")
        params = {
            "MerchantID": self.merchant_id,
            "MerchantTradeNo": merchant_trade_no,
            "MerchantTradeDate": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "PaymentType": "aio",
            "TotalAmount": int(amount),
            "TradeDesc": "捷可思滑雪學校線上付款",
            "ItemName": item_name,
            "ReturnURL": return_url,
            "ChoosePayment": choose_payment,
            "ClientBackURL": client_back_url,
            "EncryptType": 1,
        }
        if choose_payment == "ATM":
            params["ExpireDate"] = ECPAY_ATM_EXPIRE_DAYS
            params["PaymentInfoURL"] = payment_info_url
        params["CheckMacValue"] = generate_check_mac_value(params, self.hash_key, self.hash_iv)

        inputs_html = "\n".join(
            f'<input type="hidden" name="{html_module.escape(k)}" value="{html_module.escape(str(v))}">'
            for k, v in params.items()
        )
        return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head><meta charset="utf-8"><title>正在導向付款頁面...</title></head>
<body onload="document.forms[0].submit()">
  <p style="font-family:sans-serif; text-align:center; margin-top:40px;">正在導向至綠界付款頁面,請稍候,如果畫面沒有自動跳轉請按下方按鈕...</p>
  <form method="POST" action="{html_module.escape(self.endpoint)}" style="text-align:center;">
{inputs_html}
    <button type="submit">前往付款</button>
  </form>
</body>
</html>"""


def _build_active_provider():
    if config.ECPAY_CONFIGURED:
        return EcpayProvider(
            config.ECPAY_MERCHANT_ID, config.ECPAY_HASH_KEY, config.ECPAY_HASH_IV, mode=config.ECPAY_MODE
        )
    return MockPaymentProvider()


active_provider = _build_active_provider()
