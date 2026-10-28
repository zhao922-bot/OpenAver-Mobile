"""跨站共用的查詢契約與進度式補詳情（175a）。

本套件不在此處 import 任何子模組：import 圖由各檔自己決定，避免套件層綁死順序。
頂層不得 import core.scraper 與 core.database（plan CD-175a-1）；頂層 import core.scrapers.* 是允許的，
需要 core.scraper 的名字一律函式內延後取用。
"""
