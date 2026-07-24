# IG Comment Analyzer

以 Python 3.12、Playwright 與 Pandas 建立的 Instagram 留言蒐集、分析與報告工具。它會登入 Instagram、保存瀏覽器 Session，透過 Instagram 網頁留言 API 分頁蒐集貼文／Reel 留言，輸出 CSV、Excel、圖表、HTML 與 PDF。

> Instagram 會不定期修改介面、限制自動化行為或要求安全驗證；請只分析您有權存取的公開內容，並遵守 Instagram 的服務條款。若出現兩步驟驗證或 Challenge，請以 `HEADLESS=false` 執行並在瀏覽器中完成驗證，再重新執行。

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

編輯 `.env`：

```dotenv
IG_USERNAME=your_instagram_username
IG_PASSWORD=your_instagram_password
HEADLESS=false
CRAWL_TIMEOUT_SECONDS=30
MAX_RETRIES=3
MAX_COMMENTS=0
CRAWL_DELAY_SECONDS=0.35
```

- `MAX_COMMENTS=0` 表示抓取全部可取得的留言；設為正整數可限制筆數。
- `CRAWL_DELAY_SECONDS` 控制 API 分頁間隔，留言極多時可略為提高以降低限流風險。

首次建議使用 `HEADLESS=false`，方便處理 Instagram 顯示的安全驗證。成功登入後，根目錄的 `session.json` 會保存登入狀態；此檔案含敏感 Cookie，請勿提交或分享。

## 使用方式

```powershell
# 只蒐集留言，產生 output/comments.csv 和 output/comments.xlsx
python main.py crawl https://www.instagram.com/p/xxxxxxxx/

# 分析既有 output/comments.csv，產生 analysis.json 和 duplicate_comments.xlsx
python main.py analyze

# 從既有留言產生 assets/*.png、output/report.html、output/report.pdf
python main.py report

# 一次完成蒐集、分析與報告
python main.py all https://www.instagram.com/p/xxxxxxxx/
```

## 產出內容

- `output/comments.csv`：UTF-8 with BOM CSV；包含 username、comment、comment_time、likes、reply_count、is_verified、profile_url、comment_id。
- `output/comments.xlsx`：同一份資料，欄寬自動調整。
- `output/duplicate_comments.xlsx`：完全相同留言摘要（以及小資料集的相似留言對）。
- `output/analysis.json`：總留言、唯一留言者、平均長度、Top 20、關鍵字、標註、Emoji、「我挺／I support」應援隊伍、時間與長度分布等完整資料。
- `assets/*.png`：留言者、應援隊伍、關鍵字、Emoji、長度、日期趨勢與文字雲圖表。
- `output/report.html`、`output/report.pdf`：Bootstrap 5 響應式分析報告。
- `logs/app.log`：輪替的詳細執行與錯誤紀錄。
- 長時間爬取時會定期寫入 `output/comments.partial.csv` 作為檢查點。

## 定時自動更新（GitHub Actions）

倉庫已設定 `Scheduled data update` workflow：每天台灣時間 **上午 10:00**、**晚間 22:00** 爬取 `POST_URL`、產生報告，並更新 GitHub Pages。

需在 GitHub repo 設定：

- Secrets：`IG_USERNAME`、`IG_PASSWORD`、（建議）`IG_SESSION_JSON`
- Variables：`POST_URL`（Instagram 貼文網址）

也可在 Actions 頁面手動執行 `workflow_dispatch`。

> 完整抓取十萬則留言可能接近或超過一小時；workflow 設有 concurrency，重疊執行會取消舊任務。Instagram 也可能對雲端 IP 要求驗證，建議定期在本機更新 `session.json` 並同步到 `IG_SESSION_JSON` secret。


- **登入失敗／停留在登入頁**：檢查 `.env` 憑證、將 `HEADLESS` 設為 `false` 並完成安全驗證；必要時刪除 `session.json` 後重試。
- **逾時或網路不穩**：提高 `CRAWL_TIMEOUT_SECONDS`，工具會對頁面開啟進行重試。
- **留言極多**：Instagram 單篇可有數萬～十數萬則留言；完整抓取可能需要數十分鐘到數小時。可用 `MAX_COMMENTS` 先取樣，確認流程後再設 `0` 全抓。
- **抓不到留言**：確認貼文可由登入帳號看到且留言未關閉；完整錯誤會記錄在 `logs/app.log`。
- **PDF 或 Plotly 圖表失敗**：再次執行 `playwright install chromium`，並確認 `kaleido` 已隨 requirements 安裝。
