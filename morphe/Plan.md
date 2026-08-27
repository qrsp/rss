# Morphe Patch RSS Feed 產生器設計計畫

利用 GitHub Actions 與 Python 打造 Morphe Patch 新軟體上架 RSS Feed。

## 設計架構與技術決策

- **核心語言與邏輯**：使用 Python 3 撰寫抓取與 RSS XML 產生邏輯 (`generate_rss.py`)。
- **資料來源與範圍**：
  - 抓取 `https://awesome-morphe.vercel.app/whats-new.json`，直接選取前 2 個陣列元素（最近 2 個日期群組）。
  - 對照 `https://awesome-morphe.vercel.app/bundles.json` 提取 App 資訊（名稱、Icon、簡介、分類）。
- **新軟體判定機制**：
  - 唯一識別碼格式為 `repo/bundle:package_name`（例：`Nai64/Nai64Patches:com.google.android.apps.bard`）。
  - 當發現未曾在 `known_apps.txt` 中出現的 `repo/bundle:package_name` 時，即判定為新軟體條目。
- **RSS Feed (<item>) 規格**：
  - **Title**: `App Name`（僅 App 名稱，若無名稱則為 Package Name，不含 Repo/Bundle 前綴）。
  - **Link**: `https://awesome-morphe.vercel.app/?app={package_name}#whats-new`
  - **Description**: HTML 格式：
    - 一開始即為 **App 簡述 (app_desc)**，方便使用者無需點開即可瞭解軟體功能。
    - 包含 App Icon、Package Name、Category 以及此 App 支援的 Patches 清單。
    - 不顯示 Bundle Title 與 Stars 數量。
  - **GUID**: `repo/bundle:package_name` (`isPermaLink="false"`)
- **動態保留上限與排序**：
  - 新產生的條目於 `feed.xml` 置頂（最新條目在前）。
  - **預設保留上限**：最大保留條目數量為 **200 筆**。
  - **動態擴展機制**：若單次新增軟體數量 **超過 200 筆**，當次最大保留上限自動擴展為 **500 筆**。超過保留上限的舊條目自動修剪。
- **紀錄檔**：
  - 執行完畢後，自動將新產生的識別碼追加至 `known_apps.txt`。
- **GitHub Actions 排程與自動化**：
  - **排程頻率**：每日固定 **台灣時間早上 06:00**（UTC 22:00, `cron: '0 22 * * *'`）自動執行，並支援 `workflow_dispatch` 手動觸發。
  - **Commit & Push 策略**：僅在有新增軟體 (`feed.xml` 或 `known_apps.txt` 變動) 時自動 commit & push，未有變動則跳過 commit。
