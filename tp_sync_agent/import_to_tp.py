"""將 Render 完整快照安全鏡像至 TurboPlus 獨立營運表單。

只建立/更新專用的 40、41 號表單，不會碰既有 TP 表單。資料以
(同步實體, Render來源ID) 唯一對照；來源不存在時標示待確認，絕不自動刪除。
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Iterable


ENCODING = "cp950"
MIRROR_FORM_ID = 40
AUDIT_FORM_ID = 41
MIRROR_FORM_NAME = "Render同步營運鏡像"
AUDIT_FORM_NAME = "Render同步執行紀錄"
SYSTEM_TAIL_FIELDS = 5

MIRROR_FIELDS = [
    ("同步實體", "單行文字", "60", ""),
    ("Render來源ID", "單行文字", "60", ""),
    ("來源鍵", "組合欄位", "140", "[[同步實體]]:[[Render來源ID]]"),
    ("顯示標題", "單行文字", "200", ""),
    ("狀態", "單行文字", "80", ""),
    ("營運日期時段", "單行文字", "80", ""),
    ("會員來源ID", "單行文字", "60", ""),
    ("教練來源ID", "單行文字", "60", ""),
    ("雪場來源ID", "單行文字", "60", ""),
    ("金額", "數值欄位", "30", ""),
    ("營運摘要", "多行文字", "600", ""),
    ("Render建立時間", "單行文字", "30", ""),
    ("同步版本", "單行文字", "20", ""),
    ("本次同步時間UTC", "單行文字", "30", ""),
    ("資料雜湊", "單行文字", "64", ""),
    ("同步結果", "單行文字", "80", ""),
]
AUDIT_FIELDS = [
    ("同步批次ID", "單行文字", "80", ""),
    ("同步開始時間UTC", "單行文字", "30", ""),
    ("同步完成時間UTC", "單行文字", "30", ""),
    ("同步模式", "單行文字", "40", ""),
    ("資料版本", "單行文字", "20", ""),
    ("總資料筆數", "數值欄位", "30", ""),
    ("新增筆數", "數值欄位", "30", ""),
    ("更新筆數", "數值欄位", "30", ""),
    ("來源未出現筆數", "數值欄位", "30", ""),
    ("執行結果", "單行文字", "80", ""),
    ("各類資料筆數", "多行文字", "600", ""),
]

ENTITY_LABELS = {
    "members": "會員",
    "staff": "員工／教練",
    "coach_schedule": "教練班表",
    "japan_regions": "日本分區",
    "resorts": "雪場",
    "orders": "訂單",
    "payments": "付款",
    "charter_passes": "包機堂數",
    "member_plans": "會員方案",
    "member_quota_cycles": "方案額度",
    "indoor_sessions": "室內時段",
    "indoor_session_members": "室內參加者",
    "jump_bookings": "跳台預約",
    "japan_bookings": "日本預約",
    "japan_other_resort_requests": "其他雪場需求",
}
SENSITIVE_OR_NOISY_KEYS = {
    "phone", "email", "auth_provider", "password", "password_hash", "id_number",
    "address", "provider_ref", "ecpay_trade_no", "atm_bank_code", "atm_virtual_account",
    "note", "lesson_notes", "participants",
}


def read_text(path: Path) -> str:
    return path.read_bytes().decode(ENCODING)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode(ENCODING, errors="replace"))
    os.replace(temporary, path)


def strip_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = text.replace(",", "，").replace("\x08", " ").replace("\x00", " ")
    return " ".join(text.split())


def field_names(path: Path) -> list[str]:
    return [line.split(",", 1)[0] for line in read_text(path).splitlines() if line]


def template_field_lines(form_dir: Path) -> dict[str, str]:
    lines = [line for line in read_text(form_dir / "39.fmr").splitlines() if line]
    by_type: dict[str, str] = {}
    for line in lines:
        parts = line.split(",")
        if len(parts) > 4:
            by_type.setdefault(parts[2], line)
    needed = {"單行文字", "數值欄位", "多行文字", "組合欄位"}
    if not needed.issubset(by_type):
        raise RuntimeError("找不到建立鏡像表單所需的 TP 欄位設定樣板")
    return by_type


def build_fmr(template_lines: dict[str, str], fields: list[tuple[str, str, str, str]]) -> str:
    rows: list[str] = []
    for name, field_type, width, default in fields:
        parts = template_lines[field_type].split(",")
        parts[0] = name
        parts[2] = field_type
        parts[3] = width
        parts[4] = default
        rows.append(",".join(parts))
    return "\n".join(rows) + "\n"


def backup_before_schema_change(tp_root: Path, form_dir: Path) -> None:
    backup_root = tp_root / "exeFile" / "erski_tp_sync" / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(form_dir / "list.txt", backup_root / "list.txt")
    for form_id in (MIRROR_FORM_ID, AUDIT_FORM_ID):
        for suffix in (".ifc", ".fmr"):
            candidate = form_dir / f"{form_id}{suffix}"
            if candidate.exists():
                shutil.copy2(candidate, backup_root / candidate.name)
        candidate_dir = form_dir / str(form_id)
        if candidate_dir.exists():
            shutil.copytree(candidate_dir, backup_root / str(form_id), dirs_exist_ok=True)


def create_form_if_missing(form_dir: Path, form_id: int, form_name: str, fields: list[tuple[str, str, str, str]]) -> None:
    ifc_path = form_dir / f"{form_id}.ifc"
    fmr_path = form_dir / f"{form_id}.fmr"
    data_path = form_dir / str(form_id)
    expected_fields = [item[0] for item in fields]
    if ifc_path.exists() or fmr_path.exists() or data_path.exists():
        if not (ifc_path.exists() and fmr_path.exists() and data_path.is_dir()):
            raise RuntimeError(f"TP 表單 {form_id} 的設定不完整，為避免覆蓋既有資料已停止")
        if field_names(fmr_path) != expected_fields:
            raise RuntimeError(f"TP 表單 {form_id} 的欄位與同步契約不一致，為避免覆蓋既有資料已停止")
        return

    template_ifc = read_text(form_dir / "35.ifc")
    if "ERSKI操作稽核紀錄" not in template_ifc:
        raise RuntimeError("找不到 TP 表單設定樣板中的預期名稱，已停止建立")
    write_text_atomic(ifc_path, template_ifc.replace("ERSKI操作稽核紀錄", form_name))
    write_text_atomic(fmr_path, build_fmr(template_field_lines(form_dir), fields))
    data_path.mkdir(parents=True, exist_ok=False)


def ensure_schema(tp_root: Path, dry_run: bool) -> None:
    form_dir = tp_root / "form"
    required = [form_dir / "35.ifc", form_dir / "39.fmr", form_dir / "list.txt"]
    if not all(path.exists() for path in required):
        raise RuntimeError("找不到預期的 TurboPlus 表單設定樣板，已停止")
    if dry_run:
        return

    backup_before_schema_change(tp_root, form_dir)
    create_form_if_missing(form_dir, MIRROR_FORM_ID, MIRROR_FORM_NAME, MIRROR_FIELDS)
    create_form_if_missing(form_dir, AUDIT_FORM_ID, AUDIT_FORM_NAME, AUDIT_FIELDS)
    names = read_text(form_dir / "list.txt").replace("\r\n", "\n").split("\n")
    names = [name for name in names if name]
    for form_name in (MIRROR_FORM_NAME, AUDIT_FORM_NAME):
        if form_name not in names:
            names.append(form_name)
    write_text_atomic(form_dir / "list.txt", "\n".join(names) + "\n")


def load_json_snapshots(outbox: Path) -> tuple[dict[str, list[dict]], str]:
    snapshots: dict[str, list[dict]] = {}
    api_version = "v1"
    for entity in ENTITY_LABELS:
        path = outbox / f"{entity}.json"
        if not path.is_file():
            raise RuntimeError(f"缺少完整快照檔：{path.name}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("entity") != entity or data.get("mode") != "read_only_full_snapshot":
            raise RuntimeError(f"快照檔格式不正確：{path.name}")
        records = data.get("records")
        if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
            raise RuntimeError(f"快照資料格式不正確：{path.name}")
        snapshots[entity] = records
        api_version = str(data.get("api_version") or api_version)
    return snapshots, api_version


def pick(record: dict, *keys: str) -> object:
    for key in keys:
        if record.get(key) not in (None, ""):
            return record[key]
    return ""


def date_and_time(record: dict) -> str:
    date_value = pick(record, "booking_date", "work_date", "start_date", "created_at")
    time_value = pick(record, "start_time", "start_hour", "half_day_slot", "end_date")
    return " ".join(item for item in (strip_value(date_value), strip_value(time_value)) if item)


def human_title(entity: str, record: dict) -> str:
    label = ENTITY_LABELS[entity]
    primary = pick(record, "name", "resort_name", "work_id", "code", "group_key")
    source_id = strip_value(record.get("source_id"))
    return f"{label} {strip_value(primary) or '#' + source_id}"


def safe_summary(record: dict) -> str:
    keys = [
        "order_type", "category", "payment_type", "payment_method", "day_type", "equipment_type",
        "headcount", "duration_minutes", "package_size", "remaining", "plan_name", "billing_cycle",
        "cycle_key", "deposit_paid", "balance_paid", "is_active", "is_coach", "branch",
    ]
    fragments = [f"{key}={strip_value(record[key])}" for key in keys if key in record and key not in SENSITIVE_OR_NOISY_KEYS]
    return "；".join(fragments)


def record_hash(record: dict) -> str:
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def mirror_values(entity: str, record: dict, synced_at: str, api_version: str) -> list[str]:
    source_id = strip_value(record.get("source_id"))
    status = pick(record, "status", "payment_status", "attendance_status")
    if status in (None, "") and "is_active" in record:
        status = "啟用" if record["is_active"] else "停用"
    amount = pick(record, "amount", "price", "fee_paid", "remaining")
    return [
        entity,
        source_id,
        f"{entity}:{source_id}",
        human_title(entity, record),
        strip_value(status),
        date_and_time(record),
        strip_value(pick(record, "member_source_id")),
        strip_value(pick(record, "coach_source_id", "assistant_coach_source_id")),
        strip_value(pick(record, "resort_source_id")),
        strip_value(amount),
        safe_summary(record),
        strip_value(pick(record, "created_at")),
        api_version,
        synced_at,
        record_hash(record),
        "已同步",
    ]


def iter_form_rows(form_data_dir: Path) -> Iterable[tuple[Path, int, list[str]]]:
    for file_path in sorted(form_data_dir.glob("*.fda")):
        text = read_text(file_path).replace("\r\n", "\n")
        for line_number, line in enumerate(text.split("\n")):
            if line:
                yield file_path, line_number, line.split(",")


def excel_serial(now: datetime) -> str:
    base = datetime(1899, 12, 30, tzinfo=timezone.utc)
    return f"{(now - base).total_seconds() / 86400:.10f}"


def new_system_tail(form_id: int, serial_base: str, sequence: int, now: datetime) -> list[str]:
    date_text = now.strftime("%Y%m%d")
    return ["\x08\x08127.0.0.1", date_text, f"{form_id}\x08\x08\x08\x08{serial_base}", date_text, str(sequence)]


def update_mirror_form(tp_root: Path, snapshots: dict[str, list[dict]], api_version: str, synced_at: str, dry_run: bool) -> tuple[int, int, int, int]:
    data_dir = tp_root / "form" / str(MIRROR_FORM_ID)
    expected_length = 1 + len(MIRROR_FIELDS)
    rows_by_file: dict[Path, list[list[str]]] = {}
    existing: dict[tuple[str, str], tuple[Path, int]] = {}
    for file_path, line_number, row in iter_form_rows(data_dir):
        if len(row) < expected_length:
            raise RuntimeError(f"鏡像表單資料格式不完整：{file_path.name} 第 {line_number + 1} 列")
        rows_by_file.setdefault(file_path, []).append(row)
        key = (row[1], row[2])
        if key in existing:
            raise RuntimeError(f"鏡像表單發現重複來源鍵：{key[0]}:{key[1]}")
        existing[key] = (file_path, len(rows_by_file[file_path]) - 1)

    now = datetime.now(timezone.utc)
    serial_base = excel_serial(now)
    new_rows: list[list[str]] = []
    seen: set[tuple[str, str]] = set()
    added = updated = 0
    for entity, records in snapshots.items():
        for record in records:
            source_id = strip_value(record.get("source_id"))
            if not source_id:
                raise RuntimeError(f"{entity} 快照出現缺少 source_id 的資料")
            key = (entity, source_id)
            if key in seen:
                raise RuntimeError(f"{entity} 快照出現重複 source_id：{source_id}")
            seen.add(key)
            values = mirror_values(entity, record, synced_at, api_version)
            if key in existing:
                file_path, row_index = existing[key]
                row = rows_by_file[file_path][row_index]
                tail = row[expected_length:]
                if len(tail) < SYSTEM_TAIL_FIELDS:
                    tail = new_system_tail(MIRROR_FORM_ID, serial_base, row_index, now)
                rows_by_file[file_path][row_index] = [row[0], *values, *tail]
                updated += 1
            else:
                sequence = len(existing) + len(new_rows)
                new_rows.append([f"{serial_base}-{sequence}", *values, *new_system_tail(MIRROR_FORM_ID, serial_base, sequence, now)])
                added += 1

    missing = 0
    for key, (file_path, row_index) in existing.items():
        if key in seen:
            continue
        row = rows_by_file[file_path][row_index]
        row[5] = "來源未出現在本次快照"
        row[14] = synced_at
        row[16] = "待人工確認"
        missing += 1

    if new_rows:
        today_file = data_dir / f"{now.strftime('%Y%m%d')}.fda"
        if today_file.exists():
            rows_by_file.setdefault(today_file, []).extend(new_rows)
        else:
            rows_by_file[today_file] = new_rows

    if not dry_run:
        for file_path, rows in rows_by_file.items():
            content_rows = []
            for row in rows:
                values = [strip_value(value) for value in row[:expected_length]]
                tail = [str(value) for value in row[expected_length:]]
                content_rows.append(",".join([*values, *tail]))
            write_text_atomic(file_path, "\n".join(content_rows) + ("\n" if content_rows else ""))
    return sum(len(records) for records in snapshots.values()), added, updated, missing


def append_audit_row(tp_root: Path, api_version: str, started_at: str, completed_at: str, totals: Counter, added: int, updated: int, missing: int, dry_run: bool) -> None:
    if dry_run:
        return
    data_dir = tp_root / "form" / str(AUDIT_FORM_ID)
    now = datetime.now(timezone.utc)
    serial_base = excel_serial(now)
    prior_rows = sum(1 for _ in iter_form_rows(data_dir))
    batch_id = f"TPR-{now.strftime('%Y%m%d%H%M%S')}"
    values = [
        batch_id, started_at, completed_at, "Render→TP完整快照", api_version,
        str(sum(totals.values())), str(added), str(updated), str(missing), "完成",
        "；".join(f"{key}={value}" for key, value in sorted(totals.items())),
    ]
    row = [f"{serial_base}-{prior_rows}", *values, *new_system_tail(AUDIT_FORM_ID, serial_base, prior_rows, now)]
    today_file = data_dir / f"{now.strftime('%Y%m%d')}.fda"
    current = read_text(today_file) if today_file.exists() else ""
    write_text_atomic(today_file, current + ",".join(strip_value(value) for value in row) + "\n")


def acquire_lock(lock_path: Path) -> int:
    try:
        return os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError("已有同步程序執行中，為避免資料重複寫入已停止") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="將 Render 快照鏡像到 TurboPlus 專用營運表單")
    parser.add_argument("--tp-root", type=Path, required=True, help="TurboPlus 網站根目錄")
    parser.add_argument("--out", type=Path, required=True, help="pull_snapshot.py 產生的 outbox 路徑")
    parser.add_argument("--dry-run", action="store_true", help="只驗證快照與匯入計畫，不建立或修改 TP 表單")
    args = parser.parse_args()

    tp_root = args.tp_root.resolve()
    outbox = args.out.resolve()
    started = datetime.now(timezone.utc)
    lock_path = tp_root / "exeFile" / "erski_tp_sync" / ".import.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = acquire_lock(lock_path)
    try:
        snapshots, api_version = load_json_snapshots(outbox)
        ensure_schema(tp_root, args.dry_run)
        synced_at = datetime.now(timezone.utc).isoformat()
        total, added, updated, missing = update_mirror_form(tp_root, snapshots, api_version, synced_at, args.dry_run)
        totals = Counter({entity: len(records) for entity, records in snapshots.items()})
        completed = datetime.now(timezone.utc).isoformat()
        append_audit_row(tp_root, api_version, started.isoformat(), completed, totals, added, updated, missing, args.dry_run)
        mode = "dry-run" if args.dry_run else "已寫入 TP 鏡像表單"
        print(f"{mode}：共 {total} 筆；新增 {added}、更新 {updated}、來源未出現 {missing}。")
        print("；".join(f"{entity} {count} 筆" for entity, count in sorted(totals.items())))
        return 0
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"TP 鏡像匯入未完成：{exc}", file=sys.stderr)
        return 1
    finally:
        os.close(lock_handle)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())