# Scoop New Apps RSS Generator Plan

利用 GitHub Actions 與 Python 打造 Scoop 官方 Bucket 新軟體上架 RSS Feed。

## 設計架構與技術決策

1. **核心腳本 (Python 3)**
   - 使用 Python 3 撰寫抓取與 RSS 產生邏輯。
   - 解析 Scoop app JSON 宣告檔（`description`, `homepage`, `version`, `license` 等欄位）。
   - 生成與維護標準 RSS 2.0 格式的 `feed.xml`。

2. **倉庫變動追蹤與零 Clone 優化 (GitHub REST API)**
   - GitHub Actions 執行時透過 GitHub REST API (`GET /repos/{owner}/{repo}/commits?since=25h`) 直接查詢 Scoop 4 個官方倉庫近 25 小時內的 Commit：
     - `ScoopInstaller/Main`
     - `ScoopInstaller/Extras`
     - `ScoopInstaller/Nonportable`
     - `ScoopInstaller/Nirsoft`
   - 完全避免 `git clone` 完整倉庫，大幅縮短執行時間與網路頻寬消耗。

3. **新軟體判定與 Commit Title 快速過濾 (`known_apps.txt`)**
   - 從 Git Commit Title 解析潛在軟體名稱（例如 `telegram: Update...` 提取出 `telegram`）。
   - 直接將變動軟體名稱與 `known_apps.txt` 比對；若為已知軟體則迅速跳過，避免額外發送細節 API。
   - 發現未曾見過的新軟體時，獲取該 Commit 的 JSON 宣告檔內容，提取相關資訊並新增至 `feed.xml`。
   - 執行完畢後，自動將新軟體追加至 `known_apps.txt` 並將更新 commit & push 回 GitHub 倉庫。

4. **RSS Feed 動態管理策略 (`feed.xml`)**
   - 採用累積歷史記錄機制，最新產生的軟體條目插入至 `feed.xml` 開頭。
   - **動態保留上限**：
     - 預設最大保留條目數量為 **200 筆**。
     - 若單次新增軟體數量 **超過 200 筆**，當次最大保留上限自動擴展為 **500 筆**。
   - 條目格式：
     - **標題**: `[Bucket] App名稱 v版本號`
     - **連結**: 官方 Homepage（無 Homepage 則退回 GitHub 檔案網址）
     - **內文**: 包含軟體說明 (`description`)、Bucket 名稱、版本號與授權資訊 (`license`)。

5. **自動化排程與發布 (GitHub Actions & GitHub Pages)**
   - **排程頻率**: 每日台灣時間早上 06:00 (UTC 22:00) 自動執行，並支援 `workflow_dispatch` 手動觸發。
   - **發布平台**: 透過 GitHub Pages 發布 `feed.xml`，方便 RSS 閱讀器直接透過 HTTP/HTTPS URL 訂閱。
