# Scraper parser fixtures

These fixtures are deliberately small, stable HTML samples for the parser
baseline used by `tests/test_scraper_parser_baseline.py`.

They represent the selectors and field shapes currently consumed by:

- `core/scrapers/fc2_official.py`
- `core/scrapers/fc2_javten.py`
- `core/scrapers/heyzo.py`
- `core/scrapers/dmm.py`
- `core/custom_source/extract.py`

The samples are synthetic and contain no production account data. When a
source changes its page structure, add a separately captured fixture instead
of weakening an existing assertion. The parser replacement must preserve every
field asserted by the baseline tests.
