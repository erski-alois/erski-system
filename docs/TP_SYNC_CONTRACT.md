# Render/PostgreSQL 與 TurboPlus 同步契約

## 已確認的架構

| 面向 | 決定 |
| --- | --- |
| 主資料來源 | Render PostgreSQL |
| 正式前台與 API | `https://app.erskischool.com`（Render） |
| TP 定位 | 本機同步營運後台 |
| 資料方向 | Render → TP，單向唯讀快照 |
| 主鍵對照 | `(entity, source_id)` |
| 衝突處理 | Render 永遠優先；TP 不得以同步程序回寫 Render |

## 第一階段：安全快照

Render 提供以下有金鑰保護的端點：

- `GET /api/integrations/tp/v1/manifest`
- `GET /api/integrations/tp/v1/snapshot/<entity>?after_id=0&limit=200`

TP 主機下載全量 JSON 到非公開 `exeFile\erski_tp_sync\outbox`。此階段沒有 TP 資料寫入、沒有
改寫 `.fda`、沒有刪除資料；因此可以在不影響營運的情況下先驗證資料筆數與欄位。

每次同步都是完整快照。`after_id` 只用於同次快照的分頁，不能作為「只抓新資料」的依據，
因為既有訂單、付款、課程和額度都可能被更新。

## 第二階段：TP 原生匯入器（尚未實作）

開始前，必須先確認 TurboPlus 支援的正式寫入/匯入介面與每個目標表單的欄位對應。匯入器必須：

1. 建立不可變的 `來源實體`、`Render source_id`、`上次同步時間`、`同步狀態` 欄位。
2. 以 `(entity, source_id)` 做 upsert，不以姓名、電話、訂單文字等人工欄位對照。
3. 僅更新來自 Render 的鏡像欄位；TP 本地營運註記需另存，不能回寫或覆蓋 Render 欄位。
4. 一批完整快照通過筆數與關聯檢查後才切換；失敗時保留前一版鏡像並寫入同步稽核。
5. 不同步密碼/hash、身分證、地址、健康與同行人資料、ATM 虛擬帳號、金流交易識別碼、第三方金鑰。

在 TP 的原生寫入方式確認前，禁止以直接編輯表單資料檔的方式「試寫」。

## 上線前檢核

- Render 必須以環境變數設定 `TP_SYNC_SHARED_SECRET`，不能提交到 Git。
- TP 同步主機只能以 HTTPS 連線到正式網域，設定檔權限限系統管理員。
- 先執行 `--dry-run`，核對每個 entity 的筆數與抽樣資料。
- 再啟用 outbox 快照，並保留每次同步的時間、版本、筆數與錯誤結果。
- 對 TP 匯入器做「重跑同一快照不重複建檔」測試、付款狀態更新測試、取消/退款/堂數回補測試後，才可供日常營運使用。