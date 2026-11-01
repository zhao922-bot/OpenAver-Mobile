# Code Health

`tools/code_health.py` provides a dependency-free snapshot of the mobile
source tree. It is descriptive rather than a hard release gate.

```bash
python tools/code_health.py
python tools/code_health.py --json --output code-health.json
```

The report tracks:

- source file and byte counts by language;
- Python LOC, SLOC, and comment counts;
- the largest files;
- the highest-complexity Python functions;
- exact CSS rule overlap between `theme.css` and `tailwind.css`, both as raw
  source and as stylesheets actually linked by `base.html`;
- the number of upstream patches and touched files.

Run it before and after each optimization round. A round should not increase
the top complexity or duplicate CSS unless the change documents why.

## Baseline (r32)

- Source files: 384
- Python: 64,959 LOC / 50,997 SLOC / 4,290 comment lines
- Largest files: `tailwind.css` (204,924 bytes), `capabilities.py` (119,303),
  `scanner.py` (119,009)
- Highest Python complexity: `generate_avlist` 93,
  `_load_config_unlocked` 93, `build_combined_rename_plan` 91
- CSS exact rule overlap: 149/314 rules (47.5%)
- Upstream patch surface: 8 patches, 71 files

## Round 7 checkpoint

- Loaded CSS overlap: 1/314 rules (0.3%)
- `tailwind.css`: 204,924 bytes -> 142,427 bytes
- Removed the embedded copy of `theme.css` from the Tailwind bundle while
  keeping the raw theme as the single runtime source.

## Round 8 checkpoint

- Highest Python complexity: 93 -> 61
- `generate_avlist`: 93 -> 61; source scanning, candidate refresh, deletion
  protection, per-file scanning, and focal submission are now separate helpers.
- `_load_config_unlocked`: 93 -> 8; first-run seeding and the three migration
  stages are isolated while the original lock and single save point remain.
- `build_combined_rename_plan`: 91 -> below the top-15 report; grouping, item
  construction, conflict detection, and summary calculation are separate.
- `organize_file`: 84 -> 41; title selection, template data, fallback reporting,
  and path computation are now pure planning helpers.
- `build_rename_plan`: 71 -> below the top-15 report; per-row planning and
  conflict validation are separated.
- Python LOC increased slightly because the refactor adds explicit helper
  boundaries and focused tests. The primary result is lower branch density per
  function, not a shorter file.

## Round 9 final checkpoint

- Source files: 398
- Python: 66,085 LOC / 52,039 SLOC / 4,229 comment lines
- Highest Python complexity: `generate_avlist` 61
- Loaded CSS overlap: 1/314 rules (0.3%)
- Upstream patch surface: 8 patches, 88 files
- Removed the stale metatube mock-provider injector from the settings page.
- Fixed five invalid Python escape sequences in the legacy gallery generator;
  generated JavaScript output is unchanged and now has a regression assertion.
- `compileall` passes with `SyntaxWarning` promoted to an error.
- Vulture reports no unused definitions at 80% confidence.
- The shipped Python, Java, C++, tools, tests, and docs contain no active
  `TODO`/`FIXME`/`HACK` markers.
- `.gitignore` now scopes local device screenshots, UI dumps, database backups,
  CI downloads, and patch-replay scratch directories without hiding source.

The remaining functions above complexity 50 are either router entry points with
large explicit validation/response contracts or modules already split at their
natural phase boundaries. Further reduction would require behavior-level
rewrites and should be handled as feature work, not as cleanup.
