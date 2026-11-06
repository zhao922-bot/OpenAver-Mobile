# Vendored Android wheels

## pydantic_core 2.41.5

Prebuilt `pydantic-core` wheels for the Android Python 3.13 build.

- Source: Termux User Repository (TUR) pypi index
  https://termux-user-repository.github.io/pypi/pydantic-core/
- Build system: termux-user-repository/pypi-wheel-builder (maturin 1.12.6)
- Release asset:
  `pydantic_core-2.41.5-cp313-cp313-android_24_arm64_v8a.whl`
- SHA-256:
  `1c6ad3f171f8078102e7f345b5d53c3d79a5a5cfb953a4789f9f7e7f8149ff8c`
- Emulator test asset:
  `pydantic_core-2.41.5-cp313-cp313-android_24_x86_64.whl`
- SHA-256:
  `8178c1bbcf04f8876bb187dd2c3afd628d8196d7500673df5bad1d5a2c32c601c`
- License: MIT (embedded in the wheel)

The filenames and the internal WHEEL tags match, so no renaming is required.

Verified properties (see docs/tur-pydantic-core-2.41.5-plan.md):

- LOAD segments are 16 KB aligned (0x4000), usable on Android 15+ 16 KB page
  devices.
- NEEDED: libpython3.13.so, libdl.so, libc.so. All 208 undefined symbols
  resolve against Chaquopy's libpython3.13.so plus bionic.
- RUNPATH references Termux, but `$ORIGIN/../pydantic_core-libs` comes first and
  `libpython3.13.so` is matched by SONAME against the already-loaded Chaquopy
  runtime.
- Python sources are byte-identical to the official 2.41.5 release (LF vs CRLF
  only).

Known limitations:

- Python 3.13 is required.
- arm64-v8a is the release target. The x86_64 wheel is vendored only so the
  Android emulator can exercise the same Python dependency stack during
  validation.
- pydantic-core is pinned by pydantic's exact requirement: pydantic 2.12.5
  requires pydantic-core 2.41.5. Upgrading pydantic requires a matching core
  wheel.

Do not replace this artifact without rebuilding the APK, running the full test
suite, and verifying native loading on an Android arm64 device or emulator.
