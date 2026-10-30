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
| `005-android-file-writeback.patch` | NFO batch updates, cover, poster, fanart, title, and SAF bridge writes |
| `006-mobile-web-routers.patch` | mobile scanner/showcase/capability routes and batch tag-source updates |
| `007-mobile-ui-and-localization.patch` | Simplified Chinese defaults, navigation, unified mobile state/error cards, compact and high-contrast library-insight summary/deep-dive views, responsive search and scanner layouts, touch-safe floating handle, desktop-only settings cleanup, system video-player handoff, task controls, safe batch maintenance, and persistent settings save state |
| `008-mobile-loopback-auth.patch` | process-local token gate for the embedded loopback server |

`manifest.json` records the exact file membership for automated checks.

## Regenerate patches

Use the upstream checkout at the pinned tag and the current Android payload:

```bash
python tools/generate_patches.py \
  --upstream-root /path/to/OpenAver \
  --source-root app/src/main/python \
  --output-dir patches
```
