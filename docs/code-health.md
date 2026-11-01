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
- exact CSS rule overlap between `theme.css` and `tailwind.css`;
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
