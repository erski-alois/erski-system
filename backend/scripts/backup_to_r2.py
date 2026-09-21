"""
每日自動備份:把正式資料庫(PostgreSQL)的資料匯出、上傳到Cloudflare R2,
補足Render本身PITR(Point-in-Time Recovery)保留天數不夠長的問題
(見README「備份驗證」章節——Render目前只保留過去3天內的還原點)。

設計上刻意不使用pg_dump/pg_restore這兩支外部程式，原因：
1. 這支程式會跑在Render的Cron Job服務上，那個服務的作業系統版本能不能裝到
   跟正式資料庫完全相同的PostgreSQL大版本的client工具不確定(這次資料庫是
   PostgreSQL 18，市面上Linux套件庫不一定馬上就有對應版本的postgresql-client)，
   版本兜不起來的話pg_dump可能直接拒絕執行或匯出失敗。
2. 改用Python標準的psycopg2(這個專案本來就有裝)搭配PostgreSQL的COPY指令，
   直接把每一張表的資料匯出成CSV，不依賴任何額外安裝的系統套件、也不受
   資料庫大版本限制，穩定度更高。

備份的是「資料」，不是「資料表結構」——資料表結構本來就已經由
backend/schema_postgres.sql + backend/alembic/versions/ 完整記錄並受版本控管，
真的要整個重建資料庫，正確作法是用alembic upgrade head重建結構，
再把這裡備份出來的CSV匯回去，不是直接複製這份備份檔案本身當資料庫用。

備份檔案存放位置：Cloudflare R2的「另一個獨立、不公開的bucket」
(環境變數R2_BACKUP_BUCKET_NAME指定，故意跟教練照片用的R2_BUCKET_NAME
分開，避免備份檔案不小心透過教練照片那個bucket的Public Development URL
被任何人下載——備份裡有會員/教練個資跟訂單資料，絕對不能是公開的)。

保留策略：預設保留最近30天的每日備份，超過天數的舊備份會自動刪除，
避免R2空間無限增長；30天可以用環境變數BACKUP_RETENTION_DAYS調整。
"""

import csv
import datetime
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 指到backend/目錄

import config
import storage_r2


RETENTION_DAYS = int(os.environ.get("BACKUP_RETENTION_DAYS", "30"))
BACKUP_PREFIX = "db-backups/"


def _log(msg):
    print(f"[backup_to_r2] {msg}", flush=True)


def _get_all_table_names(cur):
    cur.execute(
        """SELECT table_name FROM information_schema.tables
           WHERE table_schema='public' AND table_type='BASE TABLE'
           ORDER BY table_name"""
    )
    return [r[0] for r in cur.fetchall()]


def _dump_database_to_zip_bytes():
    import psycopg2

    if not config.DATABASE_URL or not config.DATABASE_URL.startswith(("postgres://", "postgresql://")):
        raise RuntimeError("DATABASE_URL未設定或不是PostgreSQL連線字串，這支備份工具只支援正式環境(PostgreSQL)")

    conn = psycopg2.connect(config.DATABASE_URL)
    conn.set_session(readonly=True)  # 備份只讀取，不寫入，避免任何意外動到正式資料
    try:
        cur = conn.cursor()
        table_names = _get_all_table_names(cur)
        _log(f"找到 {len(table_names)} 張資料表: {', '.join(table_names)}")

        zip_buffer = io.BytesIO()
        manifest = {
            "backed_up_at_utc": datetime.datetime.utcnow().isoformat() + "Z",
            "tables": {},
        }
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for table in table_names:
                csv_buffer = io.StringIO()
                # COPY ... TO STDOUT是PostgreSQL內建指令，效能好、且是完全用psycopg2
                # 這個既有相依套件就能做到的方式，不需要外部pg_dump程式。
                cur.copy_expert(f'COPY "{table}" TO STDOUT WITH CSV HEADER', csv_buffer)
                content = csv_buffer.getvalue()
                row_count = max(0, content.count("\n") - 1)  # 扣掉header那一行
                zf.writestr(f"{table}.csv", content)
                manifest["tables"][table] = row_count
            zf.writestr("manifest.json", _json_dumps(manifest))
        cur.close()
        return zip_buffer.getvalue(), manifest
    finally:
        conn.close()


def _json_dumps(obj):
    import json
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _cleanup_old_backups():
    """刪除超過RETENTION_DAYS天的舊備份，避免R2空間無限增長。"""
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=RETENTION_DAYS)
    objects = storage_r2.list_backup_objects(BACKUP_PREFIX)
    deleted = 0
    for obj in objects:
        if obj["last_modified"].replace(tzinfo=None) < cutoff:
            storage_r2.delete_backup_object(obj["key"])
            deleted += 1
            _log(f"已刪除過期備份: {obj['key']}(超過{RETENTION_DAYS}天)")
    return deleted


def run_backup():
    """執行一次完整備份(匯出+上傳+清理過期備份),回傳這一輪的摘要dict。
    R2備份bucket未設定、或匯出/上傳過程中出錯，都會直接raise例外，
    由呼叫端(CLI的main()，或app.py排程/手動觸發API)決定怎麼處理
    (CLI印錯誤訊息+結束程式碼；app.py則記錄log並回報Sentry)。"""
    if not config.R2_BACKUP_CONFIGURED:
        raise RuntimeError(
            "R2_BACKUP_BUCKET_NAME(或R2帳號憑證)尚未設定，無法執行備份。"
            "請參考README設定這組環境變數(需要在Cloudflare另外建立一個不公開的bucket)。"
        )

    _log(f"開始備份，目標bucket: {config.R2_BACKUP_BUCKET_NAME}")
    zip_bytes, manifest = _dump_database_to_zip_bytes()

    # 精確到微秒(而不是只到秒):手動觸發跟排程萬一在同一秒內都執行、或使用者短時間內
    # 連續按兩次「立即執行一次備份」,只到秒的時間戳記會撞出同一個object_key、
    # 造成後面那次備份把前面那次覆蓋掉、實際上少了一份備份卻不會有任何錯誤訊息。
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
    object_key = f"{BACKUP_PREFIX}erski-backup-{timestamp}.zip"
    storage_r2.upload_backup_bytes(zip_bytes, object_key)
    total_rows = sum(manifest["tables"].values())
    _log(f"備份完成: {object_key}({len(zip_bytes)/1024:.1f} KB, 共{len(manifest['tables'])}張表、{total_rows}筆資料)")

    deleted = _cleanup_old_backups()
    _log(f"清理舊備份完成，本次刪除 {deleted} 個超過{RETENTION_DAYS}天的備份")
    _log("全部完成")

    return {
        "object_key": object_key,
        "size_bytes": len(zip_bytes),
        "table_count": len(manifest["tables"]),
        "total_rows": total_rows,
        "deleted_old_backups": deleted,
        "backed_up_at_utc": manifest["backed_up_at_utc"],
    }


def main():
    """指令列直接執行用(例如本機手動測試:python backend/scripts/backup_to_r2.py)。
    app.py的排程/手動觸發API不會呼叫這支函式，而是直接呼叫上面的run_backup()，
    自己處理例外(這樣才能在Flask process裡正常記錄log/回報Sentry，
    不會因為這裡的sys.exit(1)把整個worker process也跟著關掉)。"""
    try:
        run_backup()
    except Exception as e:
        _log(f"錯誤: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
