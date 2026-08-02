"""
金流抽象層
------------
所有金流商(綠界 ECPay / 藍新 NewebPay / Stripe...)都實作同一個
PaymentProvider 介面。正式串接時只需要新增一個 Provider class,
不需要更動任何 booking / route 的商業邏輯。

目前使用 MockPaymentProvider,模擬「線上刷卡」立即成功;
「現場付款」「匯款轉帳」則一律進入 awaiting_backoffice_review,
等待客服以上人員在後台「對帳核准確認」後才會 confirmed。
"""

from abc import ABC, abstractmethod
import uuid


class PaymentProvider(ABC):
    @abstractmethod
    def create_payment(self, amount: int, payment_method: str, order_ref: str) -> dict:
        """回傳 {'status': 'confirmed'|'awaiting_backoffice_review', 'provider_ref': str}"""
        raise NotImplementedError


class MockPaymentProvider(PaymentProvider):
    """開發/示範用途。正式上線時替換成 EcpayProvider / NewebPayProvider。"""

    def create_payment(self, amount: int, payment_method: str, order_ref: str) -> dict:
        provider_ref = f"MOCK-{uuid.uuid4().hex[:10].upper()}"
        if payment_method == "online_card":
            # 正式串接時,這裡會呼叫金流商 API 並導向付款頁,
            # 由 webhook 回傳結果後才更新為 confirmed。
            return {"status": "confirmed", "provider_ref": provider_ref}
        else:
            # onsite / bank_transfer 都需要人工核對入帳
            return {"status": "awaiting_backoffice_review", "provider_ref": provider_ref}


# 之後要串接真正金流時，範例寫法(尚未實作):
#
# class EcpayProvider(PaymentProvider):
#     def __init__(self, merchant_id, hash_key, hash_iv):
#         ...
#     def create_payment(self, amount, payment_method, order_ref):
#         # 呼叫 ECPay AioCheckOut API,回傳導向網址
#         # 實際 confirmed 狀態由 ECPay callback webhook 觸發
#         ...

active_provider = MockPaymentProvider()
