"""將 TurboPlus 營運操作表回寫至 Render 的受控轉接器。

只讀取 42 號「TP營運操作申請」表內待送出的資料，並把 Render 回覆寫回同一筆；
43 號表只記錄批次結果。絕不修改既有 TP 營運表單或任何會員、訂單鏡像資料。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tp_mirror_support as import_to_tp
from tp_env_support import read_env


ENCODING = "cp950"
OPERATION_FORM_ID = 42
AUDIT_FORM_ID = 43
OPERATION_FORM_NAME = "TP營運操作申請"
AUDIT_FORM_NAME = "TP營運回寫稽核"
SYSTEM_TAIL_FIELDS = 5

OPERATION_FIELDS = [
    ("操作識別碼", "單行文字", "120", ""),
    ("操作類型", "單行文字", "80", ""),
    ("目標類型", "單行文字", "80", ""),
    ("目標來源ID", "單行文字", "80", ""),
    ("執行人員來源ID", "單行文字", "60", ""),
    ("指派教練來源ID", "單行文字", "60", ""),
    ("退款金額", "數值欄位", "30", ""),
    ("原因或備註", "多行文字", "300", ""),
    ("操作說明", "單行文字", "160", ""),
    ("處理狀態", "單行文字", "60", "待送出"),
    ("送出時間UTC", "單行文字", "30", ""),
    ("回覆時間UTC", "單行文字", "30", ""),
    ("Render回覆", "多行文字", "600", ""),
    ("重送次數", "數值欄位", "20", "0"),
    ("最後處理摘要", "單行文字", "200", ""),
]

AUDIT_FIELDS = [
    ("回寫批次ID", "單行文字", "100", ""),
    ("執行時間UTC", "單行文字", "30", ""),
    ("掃描筆數", "數值欄位", "30", ""),
    ("完成筆數", "數值欄位", "30", ""),
    ("拒絕筆數", "數值欄位", "30", ""),
    ("暫留筆數", "數值欄位", "30", ""),
    ("執行結果", "單行文字", "80", ""),
    ("結果摘要", "多行文字", "600", ""),
]

ACTION_MAP = {
    "確認待核對付款": "confirm_pending_payment",
    "confirm_pending_payment": "confirm_pending_payment",
    "指派室內課程教練": "assign_indoor_coach",
    "assign_indoor_coach": "assign_indoor_coach",
    "指派日本課程教練": "assign_japan_coach",
    "assign_japan_coach": "assign_japan_coach",
    "提出退款申請": "request_refund",
    "request_refund": "request_refund",
    "核准退款": "approve_refund",
    "approve_refund": "approve_refund",
    "駁回退款": "reject_refund",
    "reject_refund": "reject_refund",
}

TARGET_TYPE = {
    "confirm_pending_payment": "transaction",
    "assign_indoor_coach": "indoor_session",
    "assign_japan_coach": "japan_booking",
    "request_refund": "order",
    "approve_refund": "order",
    "reject_refund": "order",
}


def read_text(path: Path) -> str:
    return path.read_bytes().decode(ENCODING)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode(ENCODING, errors="replace"))
    os.replace(temporary, path)


def clean(value: object) -> str:
    return import_to_tp.strip_value(value)


def backup_schema(tp_root: Path) -> None:
    source = tp_root / "form"
    destination = tp_root / "exeFile" / "erski_tp_writeback" / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "list.txt", destination / "list.txt")
    for form_id in (OPERATION_FORM_ID, AUDIT_FORM_ID):
        for suffix in (".ifc", ".fmr"):
            p = source / f"{form_id}{suffix}"
            if p.exists():
                shutil.copy2(p, destination / p.name)
        p = source / str(form_id)
        if p.exists():
            shutil.copytree(p, destination / str(form_id), dirs_exist_ok=True)


def create_form(form_dir: Path, form_id: int, name: str, fields: list[tuple[str, str, str, str]]) -> None:
    ifc = form_dir / f"{form_id}.ifc"
    fmr = form_dir / f"{form_id}.fmr"
    data_dir = form_dir / str(form_id)
    expected = [field[0] for field in fields]
    if ifc.exists() or fmr.exists() or data_dir.exists():
        if not (ifc.exists() and fmr.exists() and data_dir.is_dir()):
            raise RuntimeError(f"TP 表單 {form_id} 設定不完整，為避免覆蓋資料已停止")
        if import_to_tp.field_names(fmr) != expected:
            raise RuntimeError(f"TP 表單 {form_id} 欄位與營運回寫契約不同，為避免覆蓋資料已停止")
        return
    template_ifc = read_text(form_dir / "35.ifc")
    if "ERSKI操作稽核紀錄" not in template_ifc:
        raise RuntimeError("找不到預期 TP 表單樣板，已停止")
    write_text_atomic(ifc, template_ifc.replace("ERSKI操作稽核紀錄", name))
    template = import_to_tp.template_field_lines(form_dir)
    write_text_atomic(fmr, import_to_tp.build_fmr(template, fields))
    data_dir.mkdir(parents=True, exist_ok=False)


def ensure_schema(tp_root: Path, dry_run: bool) -> None:
    form_dir = tp_root / "form"
    required = (form_dir / "35.ifc", form_dir / "39.fmr", form_dir / "list.txt")
    if not all(p.exists() for p in required):
        raise RuntimeError("找不到 TP 表單樣板，已停止")
    if dry_run:
        return
    backup_schema(tp_root)
    create_form(form_dir, OPERATION_FORM_ID, OPERATION_FORM_NAME, OPERATION_FIELDS)
    create_form(form_dir, AUDIT_FORM_ID, AUDIT_FORM_NAME, AUDIT_FIELDS)
    names = [x for x in read_text(form_dir / "list.txt").replace("\r\n", "\n").split("\n") if x]
    for name in (OPERATION_FORM_NAME, AUDIT_FORM_NAME):
        if name not in names:
            names.append(name)
    write_text_atomic(form_dir / "list.txt", "\n".join(names) + "\n")


def iter_rows(data_dir: Path):
    for path in sorted(data_dir.glob("*.fda")):
        text = read_text(path).replace("\r\n", "\n")
        rows = [line.split(",") for line in text.split("\n") if line]
        if rows:
            yield path, rows


def value_index() -> dict[str, int]:
    return {name: idx + 1 for idx, (name, *_rest) in enumerate(OPERATION_FIELDS)}


def get_value(row: list[str], index: dict[str, int], name: str) -> str:
    position = index[name]
    return row[position] if len(row) > position else ""


def set_value(row: list[str], index: dict[str, int], name: str, value: object) -> None:
    position = index[name]
    if len(row) <= position:
        row.extend([""] * (position + 1 - len(row)))
    row[position] = clean(value)


def row_action_id(row: list[str], source_path: Path, row_number: int, index: dict[str, int]) -> str:
    existing = get_value(row, index, "操作識別碼").strip()
    if existing:
        return existing
    digest = hashlib.sha256((str(source_path) + ":" + str(row_number) + ":" + row[0]).encode("utf-8")).hexdigest()[:24]
    return "TPW-" + digest


def request_render(base_url: str, secret: str, document: dict) -> tuple[int, dict]:
    req = Request(
        base_url.rstrip("/") + "/api/integrations/tp/v1/writeback/actions",
        method="POST",
        data=json.dumps(document, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-ERSKI-TP-Writeback-Key": secret,
        },
    )
    try:
        with urlopen(req, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = {"message": "Render 未提供可讀取的錯誤訊息"}
        return exc.code, body
    except URLError as exc:
        raise RuntimeError("無法連線到 Render 回寫服務") from exc


def payload_for(action_type: str, row: list[str], index: dict[str, int]) -> dict:
    reason = get_value(row, index, "原因或備註").strip()
    if action_type in ("assign_indoor_coach", "assign_japan_coach"):
        return {"coach_source_id": get_value(row, index, "指派教練來源ID").strip()}
    if action_type == "request_refund":
        return {"amount": get_value(row, index, "退款金額").strip(), "reason": reason}
    if action_type == "reject_refund":
        return {"reason": reason}
    return {}


def write_rows(path: Path, rows: list[list[str]]) -> None:
    minimum = 1 + len(OPERATION_FIELDS)
    lines = []
    for row in rows:
        head = [clean(v) for v in row[:minimum]]
        tail = [str(v) for v in row[minimum:]]
        lines.append(",".join(head + tail))
    write_text_atomic(path, "\n".join(lines) + "\n")


def append_audit(tp_root: Path, scanned: int, completed: int, rejected: int, pending: int,
                 notes: list[str], dry_run: bool) -> None:
    if dry_run:
        return
    now = datetime.now(timezone.utc)
    serial = import_to_tp.excel_serial(now)
    data_dir = tp_root / "form" / str(AUDIT_FORM_ID)
    existing = sum(len(rows) for _path, rows in iter_rows(data_dir))
    values = [
        "TPW-" + now.strftime("%Y%m%d%H%M%S"), now.isoformat(), str(scanned),
        str(completed), str(rejected), str(pending),
        "完成" if not pending else "有暫留項目",
        "；".join(notes)[:560],
    ]
    row = [f"{serial}-{existing}", *values, *import_to_tp.new_system_tail(AUDIT_FORM_ID, serial, existing, now)]
    path = data_dir / f"{now.strftime('%Y%m%d')}.fda"
    prior = read_text(path) if path.exists() else ""
    write_text_atomic(path, prior + ",".join(clean(v) for v in row) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="處理 TP 營運操作申請並受控回寫 Render")
    parser.add_argument("--tp-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tp_root = args.tp_root.resolve()
    ensure_schema(tp_root, args.dry_run)
    if not args.config.is_file():
        raise RuntimeError("找不到回寫設定檔")
    settings = read_env(args.config)
    base_url = settings.get("ERSKI_WRITEBACK_BASE_URL", "").rstrip("/")
    secret = settings.get("ERSKI_TP_WRITEBACK_SHARED_SECRET", "")
    if not base_url.startswith("https://") or not secret:
        raise RuntimeError("回寫設定不完整；網址必須使用 https，且必須設定獨立回寫金鑰")

    index = value_index()
    scanned = completed = rejected = pending = 0
    notes: list[str] = []
    for path, rows in iter_rows(tp_root / "form" / str(OPERATION_FORM_ID)):
        changed = False
        for n, row in enumerate(rows):
            status = get_value(row, index, "處理狀態").strip() or "待送出"
            if status not in ("待送出", "傳送失敗"):
                continue
            scanned += 1
            action_type = ACTION_MAP.get(get_value(row, index, "操作類型").strip())
            if not action_type:
                set_value(row, index, "處理狀態", "拒絕")
                set_value(row, index, "Render回覆", "不支援的操作類型")
                set_value(row, index, "最後處理摘要", "請改用表單提供的操作類型")
                rejected += 1
                changed = True
                continue
            action_id = row_action_id(row, path, n, index)
            set_value(row, index, "操作識別碼", action_id)
            set_value(row, index, "目標類型", TARGET_TYPE[action_type])
            retries = int(get_value(row, index, "重送次數") or 0)
            document = {
                "action_id": action_id,
                "action_type": action_type,
                "target_source_id": get_value(row, index, "目標來源ID").strip(),
                "actor_staff_source_id": get_value(row, index, "執行人員來源ID").strip(),
                "payload": payload_for(action_type, row, index),
            }
            now = datetime.now(timezone.utc).isoformat()
            set_value(row, index, "送出時間UTC", now)
            set_value(row, index, "重送次數", retries + 1)
            try:
                code, response = request_render(base_url, secret, document)
            except RuntimeError as exc:
                set_value(row, index, "處理狀態", "傳送失敗")
                set_value(row, index, "Render回覆", str(exc))
                set_value(row, index, "最後處理摘要", "保留待下次重送")
                pending += 1
                notes.append("連線失敗")
                changed = True
                continue

            message = str(response.get("message") or response.get("error") or "已收到回覆")
            set_value(row, index, "回覆時間UTC", datetime.now(timezone.utc).isoformat())
            set_value(row, index, "Render回覆", json.dumps(response, ensure_ascii=False, separators=(",", ":")))
            set_value(row, index, "最後處理摘要", message)
            if code == 200 and response.get("status") == "applied":
                set_value(row, index, "處理狀態", "完成")
                completed += 1
            elif code == 400 and response.get("status") == "rejected":
                set_value(row, index, "處理狀態", "拒絕")
                rejected += 1
            else:
                set_value(row, index, "處理狀態", "傳送失敗")
                pending += 1
            changed = True
        if changed and not args.dry_run:
            write_rows(path, rows)

    append_audit(tp_root, scanned, completed, rejected, pending, notes, args.dry_run)
    print(f"TP 回寫掃描 {scanned} 筆；完成 {completed}、拒絕 {rejected}、暫留 {pending}。")
    return 1 if pending else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print("TP 回寫未完成：" + str(exc), file=sys.stderr)
        raise SystemExit(1)
