"""Field capabilities exposed by the explicit maintenance source picker."""
from core.custom_source.views import custom_source_views
from core.metatube.state import metatube_state
from core.source_config import get_manual_only_sources
from core.scraper import source_display_name

ELEMENTS = ('cover', 'plot', 'samples', 'tags')
# Fields returned by each built-in's detail parser. A supported field can
# still be absent on a particular release.
_BUILTIN = {
    'dmm': ELEMENTS, 'jav321': ELEMENTS, 'd2pass': ELEMENTS, 'heyzo': ELEMENTS,
    'fc-javten': ELEMENTS, 'jable': ELEMENTS,
    'javbus': ('cover', 'samples', 'tags'), 'javdb': ('cover', 'samples', 'tags'),
    'fc2': ('cover', 'samples', 'tags'), 'javlibrary': ('cover', 'samples', 'tags'),
    'avsox': ('cover', 'tags'),
}
_CUSTOM_FIELDS = {'cover': 'cover', 'summary': 'plot', 'sample_images': 'samples', 'tags': 'tags'}


def element_sources(config, shell):
    options = {field: [] for field in ELEMENTS}
    manual = get_manual_only_sources()
    manual_ids = {source.id for source in manual}
    availability = metatube_state.availability_map()
    rows = [row for row in config.get('sources', []) if isinstance(row, dict)]
    seen = set()

    def add(source, label, fields):
        if source in seen:
            return
        seen.add(source)
        for field in fields:
            options[field].append({'id': source, 'label': label or source})

    for row in sorted(rows, key=lambda row: row.get('order', 0)):
        source = row.get('id')
        if not isinstance(source, str) or not row.get('enabled') or source in manual_ids:
            continue
        fields = _BUILTIN.get(source, ())
        if source.startswith('metatube:') and availability.get(source):
            fields = ELEMENTS
        if fields:
            add(source, row.get('display_name_raw') or source_display_name(source), fields)
    if shell.get('available'):
        sites = shell.get('sites')
        for source in manual:
            if sites is None or source.id in sites:
                add(source.id, source.display_name_key, _BUILTIN[source.id])
    for view in custom_source_views():
        if view.routable:
            spec = view.loaded.spec
            if spec.fetch == 'cf' and not shell.get('available'):
                continue
            add(view.config.id, spec.name, [_CUSTOM_FIELDS[f.name] for f in spec.fields if f.name in _CUSTOM_FIELDS])
    return options
