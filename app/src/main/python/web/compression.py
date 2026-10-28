from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES
from starlette.middleware.gzip import GZipMiddleware


class SafeGZipMiddleware(GZipMiddleware):
    """GZip only for compressible page/API traffic.

    Starlette 0.50's GZipMiddleware also compresses 206 responses and binary
    streams.  Video Range responses must stay byte-for-byte untouched, so this
    wrapper removes Accept-Encoding for media/range requests before the
    standard middleware chooses its responder.
    """

    _BINARY_PREFIXES = (
        "/api/gallery/video",
        "/api/gallery/image",
        "/api/proxy-image",
        "/api/actress/photo",
        "/api/actress/crop",
    )

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            headers = scope.get("headers", ())
            has_range = any(
                key.lower() == b"range" for key, _ in headers
            )
            path = scope.get("path", "")
            if has_range or any(path.startswith(prefix) for prefix in self._BINARY_PREFIXES):
                scope = dict(scope)
                scope["headers"] = [
                    (key, value)
                    for key, value in headers
                    if key.lower() != b"accept-encoding"
                ]
        await super().__call__(scope, receive, send)

# findings-152.md §Q1-a：DS218 上 level 6 淨賠（多付 0.998s CPU 只多省 438,431 bytes，
# 在所有量到的連線速度下皆虧本）、level 9（Starlette 官方預設）純虧（2.15s）。
# level 1 是唯一在所有機器、所有連線速度組合下都不會輸的設定。鎖死不開放調整。
GZIP_COMPRESS_LEVEL = 1

# DEFAULT_EXCLUDED_CONTENT_TYPES（starlette 1.6.0）涵蓋 webp/jpeg/png/gif/avif/woff/
# woff2/audio*/video*/zip 家族/text-event-stream，但以下本專案會實際送出或轉發的格式不在
# 官方清單裡（2026-09-20 讀 starlette 1.6.0 原始碼逐行確認，見 plan-152a.md §0.3）：
# - application/octet-stream：spec-152a §2.0——6 種冷門副檔名影片（.asf/.divx/.iso/
#   .rm/.rmvb/.vob）與縮圖 fallback 未知副檔名的 content-type 落點，本專案的產出從
#   不會用這個 content-type 送可壓縮內容。
# - image/bmp：/api/gallery/image 支援的格式之一。排除理由不是「BMP 本質上已壓縮」
#   （一般 BMP 常是未壓縮點陣圖，這個前提是錯的，spec-152a D4 已明講）——真正理由是
#   使用率極低（本專案封面/縮圖來源幾乎不產生 BMP）＋與同端點其他已壓縮影像格式
#   （jpg/png/webp/gif）的排除行為維持一致，減少「同一端點裡有些格式壓有些不壓」
#   的認知負擔。代價：若真的存在 BMP 封面，它會少省一點可能有的頻寬（BMP 若剛好是
#   未壓縮內容，其實壓縮會有效果）——這是刻意接受的小代價，不是零成本決策。
# - image/jpg：它是 image/jpeg 的非 canonical 誤標，不在 starlette 官方預設清單裡。
#   現況：/api/proxy-image 只送檔頭魔數判定出的 image/*（jpeg/png/gif/webp/avif/bmp），
#   不再轉發上游 Content-Type；/api/gallery/image 的 .jpg 也對應 image/jpeg。目前沒有
#   路由會送出 image/jpg，這一項只是防禦性保留（漏掉的代價是白燒 CPU、內容不會損壞，gzip 無損）。
#   ⚠️ 切勿改成 image/* 萬用字元：starlette 的比對確實支援拆出 image/* 進行比對，
#   但那會連帶排除 image/svg+xml——SVG 是純文字，壓縮比高達 3–4 倍，starlette 官方清單
#   刻意不排除它；若改用萬用字元將造成淨損失。
GZIP_EXCLUDED_CONTENT_TYPES = (
    *DEFAULT_EXCLUDED_CONTENT_TYPES,
    "application/octet-stream",
    "image/bmp",
    "image/jpg",
)

