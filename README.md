# IG Comment Analyzer

以 Python 3.12 與 Pandas 建立的 Instagram 留言分析與報告工具。可從既有 `comments.csv` 產出分析、圖表、HTML 與 PDF。

> **Instagram 自動爬取與 GitHub Actions 排程已停用。**  
> 先前以帳密／Playwright 抓別人貼文留言的做法容易觸發風控並導致帳號被鎖；官方 Graph API 也無法讀取別人貼文的留言。請改為匯入既有留言檔後執行 `analyze`／`report`。

## 安裝

需要 Python 3.12。

```powershell
cd ig-comment-analyzer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
Copy-Item .env.example .env
```

`.env` 僅在你刻意重新啟用爬取時才需要 Instagram 憑證；一般分析可不填帳密。

## 使用方式

```powershell
# 分析既有 output/comments.csv，產生 analysis.json 和 duplicate_comments.xlsx
python main.py analyze

# 從既有留言產生 assets/*.png、output/report.html、output/report.pdf
python main.py report
```

將別人提供或既有的留言 CSV 放到 `output/comments.csv`（欄位需含 username、comment、comment_time 等），再執行上述指令即可。

### 爬取（預設需明確啟用）

`crawl`／`all` 需設定 `ALLOW_IG_CRAWL=true`。請只用**備用帳號**，並拉長間隔：

```dotenv
ALLOW_IG_CRAWL=true
IG_USERNAME=...
IG_PASSWORD=...
HEADLESS=false
CRAWL_DELAY_SECONDS=3.0
MAX_COMMENTS=500
```

```powershell
python main.py crawl https://www.instagram.com/p/xxxxxxxx/
```

首次登入建議 `HEADLESS=false` 以便完成驗證。成功後會寫入新的 `session.json`。  
**不要**把新帳密放回 GitHub Actions；雲端排程仍保持停用。

## 產出內容

- `output/comments.csv`：UTF-8 with BOM CSV；包含 username、comment、comment_time、likes、reply_count、is_verified、profile_url、comment_id。
- `output/comments.xlsx`：同一份資料，欄寬自動調整。
- `output/duplicate_comments.xlsx`：完全相同留言摘要（以及小資料集的相似留言對）。
- `output/analysis.json`：總留言、唯一留言者、平均長度、Top 20、關鍵字、標註、Emoji、「我挺／I support」應援隊伍、時間與長度分布等完整資料。
- `assets/*.png`：留言者、應援隊伍、關鍵字、Emoji、長度、日期趨勢與文字雲圖表。
- `output/report.html`、`output/report.pdf`：Bootstrap 5 響應式分析報告。
- `logs/app.log`：輪替的詳細執行與錯誤紀錄。

## GitHub Actions

定時自動爬取 workflow（`Scheduled data update`）已在 GitHub 上停用，並自倉庫移除。`pages-build-deployment`（GitHub Pages）仍可依 repo 設定運作，但不會再登入 Instagram。

請到 repo **Settings → Secrets and variables → Actions** 刪除不再需要的 `IG_USERNAME`、`IG_PASSWORD`、`IG_SESSION_JSON`，避免憑證殘留。

## 續抓／檢查點

爬蟲會持續寫入：

- `output/crawl_state.json`：最後翻頁游標 `next_min_id`、筆數、時間窗、最舊／最新留言時間
- `output/comments.partial.csv`：已抓留言（每頁更新）

中斷後直接再執行同一指令即可接續，已存在的 `comment_id` 不會重複寫入。  
同一時間窗若已 `status=exhausted/completed`，會略過重抓。

下次若要抓「中午之後」，改：

```dotenv
COMMENT_BEFORE=
COMMENT_AFTER=2026-07-25T12:01:00+08:00
```

這會開新時間窗（不沿用舊的歷史游標），但仍會合併既有 CSV、以 id 去重。
