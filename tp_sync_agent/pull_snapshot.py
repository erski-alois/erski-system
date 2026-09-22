"""ERSKI Render -> TurboPlus 本機唯讀快照下載器。

這個程式不會改寫 TP 表單或正式資料。它只下載完整快照到指定 outbox，供已確認的
TP 原生匯入轉接器讀取。使用 Python 標準函式庫，不需要安裝額外套件。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


HEADER_NAME = "X-ERSKI-TP-Sync-Key"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def request_json(base_url: str, secret: str, path: str, params: dict | None = None) -> dict:
    url = base_url.rstrip("/") + path
    if params:
        url += "?" + urlencode(params)
    request = Request(url, headers={HEADER_NAME: secret, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # 刻意不輸出 request header 或完整網址參數，避免同步金鑰或不必要資料進 log。
        raise RuntimeError(f"同步服務回應 HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError("無法連線到 Render 同步服務") from exc


def fetch_entity(base_url: str, secret: str, entity: str) -> Iterator[dict]:
    after_id = 0
    while True:
        page = request_json(
            base_url, secret, f"/api/integrations/tp/v1/snapshot/{entity}",
            {"after_id": after_id, "limit": 200},
        )
        yield page
        next_after_id = page.get("next_after_id")
        if next_after_id is None:
            return
        after_id = int(next_after_id)


def write_json_atomically(destination: Path, document: dict) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="ERSKI Render -> TP 唯讀完整快照下載器")
    parser.add_argument("--config", required=True, type=Path, help="TP 本機受保護的 sync.env 路徑")
    parser.add_argument("--out", required=True, type=Path, help="JSON 快照 outbox 路徑")
    parser.add_argument("--dry-run", action="store_true", help="只驗證連線與筆數，不寫入檔案")
    args = parser.parse_args()

    if not args.config.is_file():
        print("找不到同步設定檔。", file=sys.stderr)
        return 2
    settings = read_env(args.config)
    base_url = settings.get("ERSKI_SYNC_BASE_URL", "").rstrip("/")
    secret = settings.get("ERSKI_TP_SYNC_SHARED_SECRET", "")
    if not base_url.startswith("https://") or not secret:
        print("同步設定不完整；網址必須使用 https，且必須設定同步金鑰。", file=sys.stderr)
        return 2

    try:
        manifest = request_json(base_url, secret, "/api/integrations/tp/v1/manifest")
        if manifest.get("mode") != "read_only_full_snapshot":
            raise RuntimeError("同步模式不相容")
        totals: dict[str, int] = {}
        for item in manifest.get("entities", []):
            entity = item["name"]
            records: list[dict] = []
            for page in fetch_entity(base_url, secret, entity):
                records.extend(page.get("records", []))
            totals[entity] = len(records)
            if not args.dry_run:
                write_json_atomically(args.out / f"{entity}.json", {
                    "api_version": manifest.get("api_version"),
                    "mode": manifest.get("mode"),
                    "entity": entity,
                    "records": records,
                })
        print("同步檢查完成：" + "、".join(f"{key} {value} 筆" for key, value in totals.items()))
        if args.dry_run:
            print("這是 dry-run；未寫入任何 TP 或 outbox 資料。")
        return 0
    except RuntimeError as exc:
        print(f"同步未完成：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())