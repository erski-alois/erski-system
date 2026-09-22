# ERSKI Render → TurboPlus 同步代理程式

## 資料主從

- **主資料來源：** Render 上的 ERSKI PostgreSQL。
- **TP：** 本機營運鏡像；不得透過本同步機制回寫 Render。
- **同步方向：** TP 主機主動以 HTTPS 拉取 Render 的唯讀快照。

此資料夾第一階段只會把資料安全地放到本機 `outbox`，不會直接改寫任何
TurboPlus 表單檔或正式資料。直接寫 `.fda` 或猜測 TP 的內部資料格式，可能破壞
既有索引與關聯，因此必須在確認 TP 支援的原生匯入方式後，才可建立第二階段的
「來源 ID 對應、冪等新增/更新、同步稽核」寫入轉接器。

## 設定方式

1. 在 Render Web Service 的環境變數新增 `TP_SYNC_SHARED_SECRET`。
2. 在 TP 主機建立只有系統管理員可讀的設定檔，例如：
   `D:\turboplus\127.0.0.1\exeFile\erski_tp_sync\sync.env`
3. 設定檔內容只需兩行（實際金鑰不能寄給任何人或提交 Git）：

```text
ERSKI_SYNC_BASE_URL=https://app.erskischool.com
ERSKI_TP_SYNC_SHARED_SECRET=自行產生的長隨機字串
```

4. Render 更新並部署後，在 TP 主機執行：

```text
python pull_snapshot.py --config D:\turboplus\127.0.0.1\exeFile\erski_tp_sync\sync.env --out D:\turboplus\127.0.0.1\exeFile\erski_tp_sync\outbox --dry-run
```

`--dry-run` 只檢查 Render 的同步介面與資料筆數；移除 `--dry-run` 才會產生本機 JSON 快照。

## 同步範圍

同步的是會員營運摘要、員工/教練、班表、雪場、日本與室內排課、跳台、訂單、付款
狀態、包機堂數、會員方案與額度。以下資料**永不輸出**：密碼與 hash、身分證、地址、
健康/同行人資料、ATM 虛擬帳號、金流交易識別碼、任何第三方服務金鑰。

每一次都是「完整快照」，以 `source_id` 作為 Render 原始資料的穩定鍵；不是以 ID 游標
做不完整的增量更新。日後 TP 寫入器必須把 `(entity, source_id)` 當唯一對照，才能安全
地重跑同步而不重複建檔。