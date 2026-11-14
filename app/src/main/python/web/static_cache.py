"""Serve packaged UI code fresh and revalidate other static assets.

JavaScript, CSS and JSON use no-store and ignore conditional validators:
APK updates can preserve both mtime and length, making metadata ETags stale.
Images and fonts retain no-cache with ordinary ETag/Last-Modified validation.
Canonical MIME overrides also apply to both 200 and 304 responses.
"""
import os

from fastapi.staticfiles import StaticFiles


# issue #66：app 自己宣告 MIME，不交給 OS registry。
# 精簡版 Windows registry 會把 HKEY_CLASSES_ROOT\.js 的 Content Type 污染成
# text/plain，導致 ES module 被瀏覽器 strict-MIME 拒收。對 /static 下這幾個副檔名
# 一律以 WHATWG canonical MIME 回應，免疫於 OS registry / guess_type 的查表結果。
_FORCED_CONTENT_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
}


class NoCacheStaticFiles(StaticFiles):
    """Disable UI-code caching while preserving other asset revalidation."""

    def file_response(self, full_path, stat_result, scope, status_code=200):
        ext = os.path.splitext(str(full_path))[1].lower()
        ui_code = ext in {'.js', '.mjs', '.css', '.json'}
        if ui_code:
            # Packaged files can retain the same mtime and byte length across
            # APK updates. Starlette's metadata ETag then incorrectly returns
            # 304 for changed code. Serve local UI code fresh, including imports;
            # retain ordinary conditional caching for fonts and images.
            scope = dict(scope)
            scope['headers'] = [
                (name, value) for name, value in scope.get('headers', [])
                if name.lower() not in {b'if-none-match', b'if-modified-since'}
            ]
        # super 回傳 200 FileResponse 或 304 NotModifiedResponse；
        # 兩者在 __init__ 執行後 headers dict 仍可直接寫入（post-construction mutation）。
        # 注意：NotModifiedResponse.__init__ 的白名單過濾在「建構時」已完成；
        # 我們在建構後才 mutate，故白名單不介入——header 直接寫入即生效。
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = "no-store" if ui_code else "no-cache"
        # issue #66：依副檔名查表，命中才 post-construction 覆寫 Content-Type。
        # header 寫死後不再走 guess_type，對任何 mimetypes.init() / registry 重讀免疫。
        forced = _FORCED_CONTENT_TYPES.get(ext)
        if forced is not None:
            response.headers["Content-Type"] = forced
        return response
