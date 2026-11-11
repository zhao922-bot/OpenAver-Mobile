# Android Python Patch Set

The Android build does not maintain a second fork of the whole upstream Python
tree.  `app/src/main/python/` is a reproducible payload:

1. start from OpenAver `v0.17.18`
   (`af0d99741e63e71980773c9ade04c473407a60b7`);
2. copy `core/`, `web/`, `locales/`, `LICENSE`,
   `dmm_prefix_table.json`, and `maker_mapping.json`;
3. apply the numbered patches in this directory.

Upstream JavaScript `__tests__` directories and upstream docs are not shipped
inside the APK.  The patch verifier ignores those intentionally omitted files.

## Refresh an upstream release

```bash
python tools/prepare_python_tree.py \
  --upstream-root /path/to/OpenAver \
  --output-root app/src/main/python \
  --force
tools/apply_patches.sh app/src/main/python
python tools/verify_python_sync.py \
  --upstream-root /path/to/OpenAver \
  --source-root app/src/main/python
```

The verifier checks that the upstream checkout is the commit recorded in
`manifest.json` before it replays the patches.  When adding a new Android
adaptation, add its upstream-relative file to one of the existing groups in
`tools/generate_patches.py`, regenerate the patch set, and run the verifier.
Do not edit a current Android file without updating its patch.

## Patch groups

| Patch | Scope |
| --- | --- |
| `001-pydantic-v1-compat.patch` | Pydantic v1 compatibility used by Chaquopy |
| `002-mobile-bootstrap.patch` | Embedded server, mobile data root, compression |
| `003-android-native-focal.patch` | Native focal detector and in-process runner |
| `004-network-and-scraper-fallbacks.patch` | requests fallbacks and TLS/proxy compatibility |
| `005-android-file-writeback.patch` | Shared media I/O for NFO, cover, poster, fanart, samples, STRM and title writeback through the SAF bridge, plus preview-first source-titled combined file/folder normalization with rollback, stable external-storage plan fingerprints, CJK-adjacent number detection, 255-byte shared-stem repair for files truncated by Android external-storage clients, and idempotent database initialization with reused query connections |
| `006-mobile-web-routers.patch` | mobile scanner/showcase/capability routes, batch tag-source updates, missing-sidecar number recovery, source-title rename previews, and combined filename/folder rename execution |
| `007-mobile-ui-and-localization.patch` | Simplified Chinese defaults, navigation, unified mobile state/error cards, single-load compiled theme CSS, shared global toast dispatch, compact and high-contrast library-insight summary/deep-dive views, responsive search and scanner layouts, touch-safe floating handle, desktop-only settings cleanup, system video-player handoff, task controls, safe batch maintenance, persistent settings save state, the phone-specific Help guide with tutorial removal, coordinated scanner action controls, the merged source-driven file/folder naming UI, and bounded video/actress cover image windows that release decoded bitmaps after cards leave the viewport |
| `008-mobile-loopback-auth.patch` | process-local token gate for the embedded loopback server |
| `009-remove-demo-subsystem.patch` | removes developer-only motion-lab/design-system pages, scripts, styles, and demo images |
| `010-woff2-only-icons.patch` | keeps the Bootstrap Icons WOFF2 asset and removes the duplicate WOFF fallback |
| `011-echarts-insights-bundle.patch` | replaces full ECharts with the reproducible Insights-only build and vendor manifest |
| `012-bs4-html-parser.patch` | replaces runtime `lxml` parsing with BeautifulSoup `html.parser` across scrapers and custom sources |
| `013-remove-desktop-runtime-and-pages.patch` | removes the desktop runtime, connection shell, updater, and desktop-only pages |
| `014-mobile-ai-services.patch` | adds remote face detection, image-similarity indexing, AI backfill state, settings panels, and the associated mobile router/UI code |

`manifest.json` records the exact file membership for automated checks.

## Regenerate patches

Use the upstream checkout at the pinned tag and the current Android payload:

```bash
python tools/generate_patches.py \
  --upstream-root /path/to/OpenAver \
  --source-root app/src/main/python \
  --output-dir patches
```
