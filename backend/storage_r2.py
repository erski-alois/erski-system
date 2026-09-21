"""
Cloudflare R2物件儲存的輔助函式。

R2跟AWS S3用同一套API協定(S3相容)，所以直接用boto3這個Amazon官方的S3
SDK就能操作R2，只是把endpoint_url改指到Cloudflare而已，不需要另外裝
Cloudflare專屬的SDK。

用途：教練的宣傳照/證件照等圖片檔案，目前是直接把檔案內容(base64)存進
資料庫的coach_certificate_files.file_data欄位。檔案一多，資料庫會越來越肥、
備份還原也會變慢。這支模組讓我們可以改成「檔案放R2，資料庫只存檔案的
路徑(key)」，之後有需要再串進app.py既有的上傳/刪除路由。

設定方式：Render後台(或本機.env)設定以下環境變數(參考config.py)：
    R2_ACCOUNT_ID、R2_ACCESS_KEY_ID、R2_SECRET_ACCESS_KEY、
    R2_BUCKET_NAME、R2_PUBLIC_BASE_URL

尚未設定這些變數以前，is_configured()會回傳False，呼叫上傳/刪除函式
會丟出RuntimeError，呼叫端應該自行檢查is_configured()並在未設定時
繼續沿用舊的「存進資料庫」做法(不會因為這個模組而讓現有功能壞掉)。
"""

import mimetypes
import uuid

import config

_client = None  # 延遲初始化，避免還沒設定R2環境變數時，一import就出錯


def is_configured():
    return config.R2_CONFIGURED


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not config.R2_CONFIGURED:
        raise RuntimeError(
            "Cloudflare R2尚未設定(缺少R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/"
            "R2_SECRET_ACCESS_KEY/R2_BUCKET_NAME其中之一)，無法使用R2上傳/刪除功能。"
        )
    import boto3
    from botocore.config import Config as BotoConfig

    _client = boto3.client(
        "s3",
        endpoint_url=f"https://{config.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=config.R2_ACCESS_KEY_ID,
        aws_secret_access_key=config.R2_SECRET_ACCESS_KEY,
        # R2跟S3在簽名版本上有些微差異，用's3v4'搭配'auto' region是Cloudflare官方建議的寫法
        config=BotoConfig(signature_version="s3v4"),
        region_name="auto",
    )
    return _client


def build_object_key(coach_id, category, original_filename):
    """組出檔案在bucket裡的路徑，例如 coaches/12/promo_photo/<uuid>.jpg。
    用uuid當檔名主體，避免不同教練上傳同名檔案互相覆蓋，也避免檔名裡
    有中文或特殊符號在URL裡出問題。"""
    ext = ""
    if original_filename and "." in original_filename:
        ext = "." + original_filename.rsplit(".", 1)[-1].lower()
    return f"coaches/{coach_id}/{category}/{uuid.uuid4().hex}{ext}"


def upload_bytes(file_bytes, object_key, content_type=None):
    """把檔案內容(bytes)上傳到R2的指定路徑。回傳可以直接用<img src>顯示的公開網址。"""
    client = _get_client()
    if not content_type:
        content_type = mimetypes.guess_type(object_key)[0] or "application/octet-stream"
    client.put_object(
        Bucket=config.R2_BUCKET_NAME,
        Key=object_key,
        Body=file_bytes,
        ContentType=content_type,
    )
    return public_url(object_key)


def delete_object(object_key):
    """刪除R2上的檔案。檔案本來就不存在也不會報錯(S3/R2的delete是冪等操作)。"""
    client = _get_client()
    client.delete_object(Bucket=config.R2_BUCKET_NAME, Key=object_key)


def public_url(object_key):
    if not config.R2_PUBLIC_BASE_URL:
        raise RuntimeError("R2_PUBLIC_BASE_URL尚未設定，無法組出圖片的公開網址。")
    return f"{config.R2_PUBLIC_BASE_URL}/{object_key}"
