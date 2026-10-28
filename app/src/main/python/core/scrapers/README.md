# core/scrapers — 來源爬蟲文件

> **適用狀態：post-spec-85（v0.11.0）**  
> 描述清理後的穩定行為。不包含已移除的死碼（javbus variant 探查、SCRAPER_CLASSES 等）。

---

## 1. 來源能力矩陣

### 1.1 有碼來源（CENSORED_SOURCES）

| 來源 ID | 顯示名 | exact 番號 | keyword-fuzzy | prefix 範圍 | 可能需日本 IP | 桌面限定 CF | 封面浮水印 | 備註 |
|---------|--------|-----------|---------------|------------|---------|------------|-----------|------|
| `dmm` | DMM | ✅ | ✅ | ❌ | ⚠️ 依地區 | ❌ | ❌ | GraphQL API；部分地區需日本 IP（VPN/proxy）；數位 PPV 新片優先；封面高畫質；模糊搜尋（175c 起）：女優／系列／導演／label／片商以 DMM ID 精準列出（含未發行），**不宣告前綴／部分番號**（token 子字串會混入重製版，CD-175c-10）；模糊搜尋結果卡番號取列表階段批次查到的官方番號（`makerContentId`），精準搜尋仍走 `_parse_number` |
| `javbus` | JavBus | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | 直打 detail URL；封面無浮水印但**僅右半裁切**；~~搜尋端點 `/search/` 已 404~~ → **2026-08-29 實測回 200、30 筆**（variant 探查於 spec-85 移除是產品決定，與端點死活無關，見 §2 與陷阱表）；模糊搜尋（175c 起）：女優／系列／導演／label 先把名稱解析成站方代號再列完整清單（`/ja/<代號>`），片商沿用 173 樣本投票；所有清單請求每次帶 `existmag=all`（含無磁鏈片）；無碼前綴（如 `HEYZO`）一般搜尋 404 時改問 `/uncensored/search/`；查詢字含空白改 `+`，403／429／503 一律 `SourceBlocked`（不當查無） |
| `jav321` | Jav321 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | keyword 搜尋恆回空，故不註冊為 search provider |
| `javdb` | JavDB | ✅ | ✅ | ✅ | ❌ | ⚠️ | 網頁有／API 無 | 模糊搜尋由 `core/search_providers/javdb.py` 負責（`search_by_keyword` 恆回 `[]`）；**網頁路徑封面有 `javdb.com` 浮水印；資料介面路徑無浮水印**（見 §5）|
| `javlibrary` | JavLibrary | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | **manual_only**：不進 SOURCE_ORDER fan-out；exact-only（CD-70b）；需 CfTransport（桌面版限定）；封面 hotlink DMM CDN（`pl.jpg`，同 dmm 無浮水印）；手動版本切換：**eager 全抓、新片優先、三手動入口（lightbox/search/switch-source）多版本皆出切換器**（spec-86 done，含 T7 switch-source follow-on） |

### 1.2 無碼來源（UNCENSORED_SOURCES）

| 來源 ID | 顯示名 | exact 番號 | keyword-fuzzy | prefix 範圍 | 可能需日本 IP | 桌面限定 CF | 封面浮水印 | 備註 |
|---------|--------|-----------|---------------|------------|---------|------------|-----------|------|
| `d2pass` | D2Pass | ✅ | ❌ | ❌ | ❌ | ❌ | [需確認] | 無碼；日期格式番號（caribbeancom / 1pondo 等） |
| `heyzo` | HEYZO | ✅ | ❌ | ❌ | ❌ | ❌ | [需確認] | 無碼；HEYZO-XXXX 格式 |
| `fc2` | FC2 | ✅ | ❌ | ❌ | ❌ | ❌ | [需確認] | 無碼；**官方站 `adult.contents.fc2.com`**（0.13.12 起，`fc2_official.py`；舊的 javten 鏡像已於 0.13.13 改名接管成獨立來源 `fc-javten`，見 `fc2_javten.py`）；**有發行日**（官方頁「販売日」）；連不上／非 200 一律靜默回 `None`，與其他來源同語意 |
| `avsox` | AVSOX | ✅ | ❌ | ❌ | ❌ | ❌ | [需確認] | 無碼；模糊鏈永不呼叫（`search_by_keyword` 刻意不接線） |
| `fc-javten` | FC2-javten | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | **manual_only**：不進 `SOURCE_ORDER` fan-out；javten.com 鏡像站；補得到官方已下架的番號；**無發售日期**（結構性沒有此欄位）；需 CF transport（桌面版限定） |

### 1.3 常數定義位置

```
core/scrapers/utils.py
  CENSORED_SOURCES    = ['dmm', 'javbus', 'jav321', 'javdb']  (+ javlibrary append)
  UNCENSORED_SOURCES  = ['d2pass', 'heyzo', 'fc2', 'avsox']  (+ fc-javten append)
  SOURCE_ORDER        = CENSORED_SOURCES + UNCENSORED_SOURCES  # 8 elem，不含 javlibrary
  PROXY_SOURCES       = {'dmm'}  # 可能需日本 IP 的來源（依地區；非「必須有 proxy」），DMM 是否啟用只看來源膠囊
  （模糊搜尋來源不在此檔：見 core/search_providers/registry.py 註冊表）
```

> `javlibrary` 在 `SOURCE_ORDER` 建立後才 `append` 進 `CENSORED_SOURCES`，確保不污染 fan-out 排序（CD-70b-10）。

### 1.4 評分 / 簡介覆蓋（NFO-only，spec-93）

各來源網站有提供才抓，寫進 `Video.rating`（parse 一律正規化 0–5，NFO writer ×2→Jellyfin 0–10）/ `Video.summary`。**NFO-only**：經 `_summary`/`_rating` internal carrier 只流向 NFO `<plot>`/`<rating>`（給 Jellyfin/Emby/Kodi 顯示），API 回前端前一律 strip、不進 DB、不進 OpenAver UI、不翻譯（US7 契約）。

| 來源 | 評分 | 簡介 | 取得方式（皆同請求免費，除註記） |
|------|------|------|----------------------------------|
| `dmm` | ✅ | ✅ | 簡介＝主 `DETAIL_QUERY` 的 `description`；評分＝**獨立 root probe** `reviewSummary(contentId:){average}`（三態 cache、禁擴 `DETAIL_QUERY`、失敗降級不影響主 metadata）|
| `jav321` | ✅ | ✅ | 同頁文字 `平均評価: N.N`（0–5，勿 ÷10）+ 描述 div |
| `fc2` | ✅ | ❌ | **官方站版**（0.13.12 起）：評分＝頂層 JSON-LD `Product.aggregateRating`（`reviewCount == 0` → `None`，**不走 `@graph`**）；**簡介硬定空字串**（官方商品頁無等價欄位，`fc2_official.py` 的 `summary=""`）。~~舊 javten 版的 `@graph` ＋ `div.col.des` 簡介~~ 已不在 dispatch 路徑上 |
| `heyzo` | ✅ | ✅ | 同一 JSON-LD `aggregateRating` + `description` |
| `d2pass`（1pondo/10musume）| ✅ | ✅ | 同一 phpauto JSON `AvgRating`（`<=5` guard）+ `Desc` |
| `d2pass`（caribbeancom）| ✅ | ✅ | **JSON API 已死→HTML fallback**：moviepage `itemprop=description` + `meta-rating` 星數 rune-count（0–5）|
| `javdb` | ✅ | ❌ | `.panel-block` 文字 `評分: N.N分`（站上無簡介）|
| `javbus` / `avsox` | ❌ | ❌ | 站上無此兩格 → 不做 |

---

## 2. 番號重複（collision）行為

### 2.1 各來源預設給哪部

| 情境 | 行為 |
|------|------|
| JavBus 裸 URL（`/SONE-001`）| 命中舊版（第一個上架的版本） |
| DMM GraphQL | 命中數位版（通常為最新版） |
| JavLibrary 搜尋列表 | 可能回傳多筆版本（見 §2.2） |

### 2.2 版本切換現況

- **JavBus variant 探查（spec-85 已移除）**：舊版透過 `/search/` 端點枚舉同番號多版本 ID。依賴此機制的 `get_all_variant_ids` / `search_by_variant_id` 及前端版本切換 UI 已在 **spec-85 全棧原子清除**。
  ⚠️ **訂正（2026-08-29 實測）**：這裡原本寫「該端點於 2025 年站方改版後已 404」——**不是**，`/search/{keyword}` 回的是 **HTTP 200、30 筆**，`get_ids_from_search` 現在就在用它。移除 variant 探查是**產品決定**（spec-85），不是因為端點死了。兩件事別再綁在一起講。
- **JavLibrary 手動版本切換（spec-86 done）**：同番號多版本的使用者手動切換，基於 JavLibrary 搜尋列表（非 JavBus 搜尋）。開窗時 eager 全抓所有候選的完整 detail、新片優先排序（發行日 desc，預設游標停在最新）。**三個手動入口遇多版本皆出現封面 `‹ ›` 切換器**讓使用者選版本，採用語意各異：lightbox 寫入選定版本 NFO/封面（保留不可逆警告）、search 採用選定版本進結果列、switch-source 以選定版本就地替換當前結果卡。**switch-source 單版本維持靜默直接替換**（最小驚訝；多版本才開切換器，spec-86 D7 follow-on 已於 T7 實作，反轉原 Non-Goal）。不進批次匯入、不揭露 AI agent（detail_url 為內部路由細節，AC9）。

---

## 3. 搜尋路由架構

`smart_search(query, ...)` 的四條分派路徑（`core/scraper.py`）：

### 3.1 四模式分派

| 模式 | 觸發條件 | 實際呼叫 | 引擎選擇原則 |
|------|----------|---------|-------------|
| **exact** | `is_number_format(query)` — 完整番號（SONE-205） | `search_jav_single_source(query, sid)` × enabled sources | 依 `get_enabled_source_ids()` 優先序串接直打，命中即回（early-return），不等其他來源 |
| **partial** | `is_partial_number(query)` — 縮略番號（MIDV-01） | `search_partial()` → `relay.search_by_intent`，鏈上有此能力的來源（JavBus／JavDB，依設定頁順序，關閉即略過） | 能力約束：只有部分來源能做番號前綴枚舉；非技術債，不動 |
| **prefix** | `is_prefix_only(query)` — 純前綴（MIDV） | `search_prefix()` → `relay.search_by_intent`，鏈上有此能力的來源（JavBus／JavDB，依設定頁順序，關閉即略過） | 同上；JavBus 端的 `type=1` 其實是「映画」頁籤、不是前綴搜尋（與不帶 type 逐筆相同，無害，見 `findings-javbus.md` §4）；fallback 依序試 actress → keyword。三家（JavBus／DMM／JavDB）全關回 `[]`（查無）；keyword 退路只在 jav321 自己的開關為開時才進 |
| **actress/keyword** | 其餘 | `search_actress()` → `relay.search_by_intent`（註冊表） | Active-Row 順序選引擎，三家（JavBus／DMM／JavDB）都跟設定頁開關走（見 §3.2）；女優→系列→導演→label 先由來源把名稱解析成實體再列完整清單（各家認得哪些見 §3.2），解析不到才當標題關鍵字 |

### 3.2 模糊鏈跟設定頁開關走（175b 起）

search_providers 註冊表（`javbus`、`dmm`、`javdb`）是**能力白名單**，是否參與由設定頁開關決定：

- 順序取 `get_all_source_ids_ordered()`，啟用與否由 `providers_for` 過濾；三家都跟設定頁開關走，關閉即略過、全關＝查無。
- 排除 jav321 與 metatube（無模糊能力）。
- **各家宣告的能力不同，沒宣告的安靜跳過**（175c 起）：JavBus＝女優／系列／導演／label／片商／前綴／部分番號／關鍵字；DMM＝女優／系列／導演／label／片商／關鍵字（不宣告前綴／部分番號，由鏈上下一家回答，CD-175c-10）；JavDB＝女優／系列／導演／片商／前綴／部分番號／關鍵字（無 label）。以各 provider 的 `capabilities` 為準。
- **實體守衛**：女優／系列／導演／label 的清單，接力先取前 3 部卡過 `belongs`（JavBus 以詳情頁連結代號 `Video.entity_ids` 比對、DMM 以列表階段事實比對），不屬於該實體就換下一家，不顯示。
- **本機別名展開與多代號歸併**（175d 起）：女優名先查本機別名資料（唯讀、搜尋當下不連網抓別名），組內每個名字各自解析成該來源的代號；JavBus 同名有碼／無碼各取第一筆也都列。多個代號的清單以各自日期歸併成新到舊、同一頁內去重；跨頁不去重，只靠各代號的位置（跨頁偶有重複為已接受）。DMM 清單片沒有發行日，多代號時退化成依序串接（配信日不等於發行日，不補）。
- **懶換日文正名只靠 JavDB**：繁中／簡中／羅馬字女優名在 JavBus 或 DMM 排第一、JavDB 開著時，才呼叫 JavDB 的 `alt_names` 把名字換成日文，答案仍由排第一那家給；已是假名的輸入不呼叫；JavDB 關著時與 175c 相同。換成日文後仍查無，才輪到 JavDB 自己回答。
- **續頁 token 取代伺服器端記憶**：第一頁回答時，後端把「誰回答、第一頁用了哪些代號、各自讀到哪」編成不透明 `cursor` 隨回應送出，前端存在該頁搜尋狀態、載入更多時原樣帶回；後端只問 token 指定的那家、不重算第一頁。token 與呼叫 mode 不符或損毀視為無效（顯示沒有更多，不退回從頭問起）。取代 0.17.14 起的 `_MAKER_ANSWERERS` 行程內記憶，relay 模組層不再持有可變狀態。
- **失敗必須長得像失敗**：403／429／503 → `SourceBlocked`、看不懂的回應 → `SourceUnreachable`，兩者都換下一家；只有 404／空結果才是「查無」（CD-175c-9）。

### 3.3 Exact 模式設計決策（spec-85 確立）

**採用「依優先序串接直打、命中即回（cascade early-return）」，捨棄 wait-all fan-out。**

| 方案 | 延遲（POC 實測） | 問題 |
|------|----------------|------|
| 串接直打（採用） | ~1–2.3s（命中首位或次位） | 單來源結果，不做多來源 merge |
| wait-all fan-out | 10–24s | 被最慢來源拖死；POC 確認不可行 |

cascade 行為：
- `enabled_sids = get_enabled_source_ids(availability_map)` — 尊重使用者拖曳順序
- 逐一呼叫 `search_jav_single_source(query, sid)`，命中（非空）即 `return [res]`
- 全部 miss → 回 `[]`（不 fallback 到 fan-out）
- `mode=exact` 不帶 `&source=`（UI 觸發不到此路徑）維持原 wait-all 語意，作為 API 逃生口

---

## 4. 介面契約

### 4.1 BaseScraper（`core/scrapers/base.py`）

```
class BaseScraper(ABC):
    # 必須實作（abstract）
    def _get_source_name(self) -> str:           # 回傳來源 ID（如 'javbus'）
    def search(self, number: str) -> Optional[Video]:   # 精確番號搜尋
    def search_by_keyword(self, keyword: str, limit: int = 20) -> list[Video]:  # 關鍵字搜尋
    
    # 預設實作
    def validate_number(self, number: str) -> bool      # 正規式格式驗證
    def normalize_number(self, number: str) -> str      # 委派 normalize_number_impl()
    def probe_plan(self, timeout) -> ProbePlan | None   # 測試連線通道宣告，預設 None（不可探測）
```

`search()` 約定：
- 回傳 `Video` 物件（命中）或 `None`（找不到）
- 格式錯誤拋 `ValueError`；網路超時拋 `TimeoutError`
- 不應 raise 其他未預期例外（caller 依 exception boundary 決定 fallback）

`probe_plan()` 約定（設定頁「測試連線」用）：
- 簽名 `probe_plan(self, timeout) -> ProbePlan | None`；預設 `None` ＝ 不可探測
- `ProbePlan(targets, mode)`：`mode` 為 `'any'` 或 `'all'`——鏡像站用 `any`（任一通即通）、各自獨立網域用 `all`（全通才通）
- `ProbeTarget(host, send, ok_404, check, read)`；`send()` 無參數，回該來源實際查詢通道的回應物件
- `send` 依該來源實際的查詢通道，二擇一：用 scraper 自己的 Session（若有，例如 `_new_session()` 建的），或
  `requests.*(..., **self._proxy_kwargs())`；兩者都沿用注入的代理快照，不得另建不經代理的連線、不得讀目前設定
- 每個 `send` 必須帶 `timeout=timeout`、`stream=True`（讀取上限與關閉由中央負責）
- 樣本番號查無（404）算「連得到」時，在 target 上設 `ok_404=True`
- 靠驗證視窗的來源（JavLibrary、FC2-javten）在 target 上設 `cf_challenge_ok=True`：拿到明確的 Cloudflare 驗證頁訊號（`cf-mitigated: challenge` 或頁面標記）算「連得到」；單純 `server: cloudflare` 的 403 仍算被擋。是否實測由 `core/source_probe.py` 的 `skip_reason` 依桌面種類與視窗可用性決定
- 只放**查資料**的網域，不放封面／劇照圖床
- scraper 只宣告、不做判讀；通／被擋／連不到的判讀在 `core/source_probe.py`

### 4.2 normalize_number（`core/scrapers/utils.py:normalize_number_impl`）

post-spec-85（T1c 解耦後）：standalone 函式，不再實例化 `JavBusScraper`。

功能：大寫化、補連字號（`sone103` → `SONE-103`）、去除 `-UC`/`-UNCEN`/`-LEAKED` 後綴、strip 空白。

呼叫路徑：
- `core/scraper.py:normalize_number()` — module-level 公開 API，委派 `normalize_number_impl()`
- `BaseScraper.normalize_number()` — instance method，同樣委派；`D2PassScraper` override 處理日期格式特例

### 4.3 Video model（`core/scrapers/models.py`）

| 欄位 | 類型 | 說明 |
|------|------|------|
| `number` | str | 番號（SONE-205） |
| `title` | str | 影片標題 |
| `actresses` | list[Actress] | 女優列表 |
| `date` | str | 發行日期（YYYY-MM-DD）；**FC2 官方站版有**（頁面「販売日」），~~FC2 恆為空~~ 是舊 javten 實作的性質 |
| `maker` | str | 片商 |
| `cover_url` | str | 封面 URL |
| `tags` | list[str] | 類別標籤 |
| `source` | str | 資料來源 ID |
| `detail_url` | str | 詳情頁 URL |
| `director` | str | 導演 |
| `duration` | Optional[int] | 片長（分鐘） |
| `label` | str | 發行商/レーベル |
| `series` | str | 系列 |
| `sample_images` | list[str] | 劇照 URL 列表 |
| `rating` | Optional[float] | 評分 |
| `votes` | Optional[int] | 投票數 |
| `summary` | str | 簡介（僅供 NFO，不進 `to_legacy_dict`） |
| `entity_ids` | dict[str, list[str]] | 站方連結代號段（形如 `{'actors': [...], 'series': [...]}`）；僅 javbus 詳情解析填，供實體清單守衛比對；**不輸出到 `to_legacy_dict`** |

---

## 5. 封面優先序

封面欄位（`cover_url` / `sample_images`）依 **user_order（使用者在「掃描來源」頁的拖曳順序）** 解析，取第一個非空來源，兩欄各自獨立（`core/source_merger.py`）。

**不存在硬編碼封面優先序**：來源排序完全由 user_order 決定，無寫死的 cover priority 常數。

浮水印特性影響推薦排序：

| 來源 | 封面特性 | 推薦排序建議 |
|------|----------|------------|
| JavBus | 無浮水印，但右半裁切 | 排前（若可接受裁切）|
| DMM | 無浮水印，全框高畫質 | 排前（部分地區需日本 IP） |
| Jav321 | 無浮水印，全框 | 排前 |
| JavDB | 網頁路徑有 `javdb.com` 浮水印；資料介面路徑無浮水印、全框 | 排前（0.15.1 起 javdb 走資料介面優先 ⇒ 一般情況下拿到的是無浮水印那張；只有降級到網頁備援時才會帶浮水印）|

> ⚠️ **2026-08-28 再訂正**：同日稍早曾用「平均像素差 ＋ >30% 像素比例」判定
> 「網頁路徑與資料介面路徑是同一張、都沒有浮水印」——**那組統計量分不出半透明浮水印
> 與 JPEG 重編碼雜訊**（兩者都落在平均差 2–5、>30 的像素 1–2%）。把差異圖放大存成
> PNG 後，中央有清楚的 `javdb.com` 字樣：網頁那條有浮水印，資料介面那條沒有。
> （SONE-205 / ABW-300 各自確認；五片同尺寸。）
>
> 📌 **這條敘述曾經影響過推薦排序**（「JavBus / DMM / Jav321 排於 JavDB 之前」）。
> **本次只訂正事實，不改任何預設排序**——排序是 owner 的設定，要不要因此調整是另一件事。

---

## 6. 陷阱速查

完整陷阱列表見 [`feature/AI_COLLABORATION/gotchas-backend.md`](../../feature/AI_COLLABORATION/gotchas-backend.md)，以下為最高頻觸發點一覽：

| 陷阱 | 一句話 |
|------|--------|
| Mock patch target | 測試 patch 要指**使用端** `core.scraper.*`，不是定義端 `core.scrapers.javbus.*`；否則 mock 不生效、測試打真網路 |
| DMM 開關與代理範圍 | DMM 能不能被用只看設定頁來源膠囊（`config.sources[]` 的 `enabled`），與 Proxy 欄是否填寫無關；Proxy 欄填了之後哪些連線走代理由 `core/proxy_policy.py` 依「僅 DMM／所有來源」決定 |
| ~~JavBus 搜尋端點已死~~ | ⛔ **2026-08-29 實測推翻**：`/search/{keyword}` 回的是 **HTTP 200、30 筆**，不是 404（`get_ids_from_search('a')` 當場驗過，`_build_search_url` 本來就在組這個網址）。舊敘述「**不可**再實作任何依賴 `/search/` 的功能」曾讓一位 reviewer 判定某個 task 的樣本來源已死並下 BLOCK。**exact 走 detail URL、partial/prefix 走 `get_ids_from_search`** 這半仍然正確，是分工不是能力限制。⚠️ 這是 live-only 事實，要據此做決定前**自己再驗一次**（見 `gotchas-backend.md` `BE-VERIFY-03`）|
| javlibrary manual_only | `get_enabled_source_ids()` 自動排除 manual_only 來源，javlibrary 不進 cascade head；只能由進階搜尋顯式指定 |
| 模糊搜尋跟開關走 | 模糊路徑（女優／關鍵字／前綴／部分番號）三家（JavBus／DMM／JavDB）都看設定頁來源膠囊，關閉即略過、三家全關＝查無（175b 起；舊的「JavBus always-on」已廢）；explicit 指定來源不受膠囊限制 |
| ~~FC2 無發行日~~ | ⛔ **0.13.12 起作廢**：該不變式屬於舊的 javten 鏡像實作（0.13.13 起為 `fc2_javten.py`／來源 `fc-javten`，仍硬定 `date=""`——站方結構性沒有這個欄位）。現行 `fc2` 走官方站 `fc2_official.py`，**會回傳發行日**（spec-118 AC-1.2 就是要它）。看到 FC2 有日期**不是 bug**，看到它恆空才是 |
| 路徑處理 | `file:///` URI 轉換一律用 `core/path_utils.py`，禁止手動 strip/建構 |
