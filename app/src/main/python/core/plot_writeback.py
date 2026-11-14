"""Read and update ``<plot>`` / ``<originalplot>`` in an existing NFO.

Only these two elements are changed.  The write goes through the shared atomic
writer so Android external-storage failures cannot truncate the original NFO.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Tuple, Union

from core.atomic_write import atomic_write
from core.nfo_updater import set_element_text
from core.nfo_utils import sanitize_nfo_bytes
from core.title_writeback import (
    NfoNotFoundError,
    NfoParseError,
    strip_illegal_xml_chars,
)


class PlotEmptyError(Exception):
    """NFO has no non-empty ``<plot>`` element."""


class PlotChangedError(Exception):
    """The plot no longer matches the original saved by this batch."""


def read_nfo_plots(nfo_path: Union[str, Path]) -> Tuple[str, str]:
    """Return ``(plot, original_plot)`` while preserving internal newlines."""
    path = Path(nfo_path)
    if not path.exists():
        raise NfoNotFoundError(str(nfo_path))
    raw = sanitize_nfo_bytes(path.read_bytes())
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise NfoParseError(str(exc)) from exc
    plot = (root.findtext("plot") or "").strip()
    original = (root.findtext("originalplot") or "").strip()
    return plot, original


def rewrite_nfo_plot(
    nfo_path: Union[str, Path],
    *,
    new_plot: str,
    new_original: Optional[str],
    expected_source: Optional[str] = None,
) -> bytes:
    """Rewrite plot fields and return the serialized XML.

    ``new_original`` uses three states: ``None`` keeps the existing value,
    ``""`` removes ``<originalplot>``, and a non-empty string replaces it.
    """
    path = Path(nfo_path)
    if not path.exists():
        raise NfoNotFoundError(str(nfo_path))

    new_plot = strip_illegal_xml_chars(new_plot)
    if new_original is not None:
        new_original = strip_illegal_xml_chars(new_original)

    raw = sanitize_nfo_bytes(path.read_bytes())
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise NfoParseError(str(exc)) from exc

    plot_elem = root.find("plot")
    if expected_source is not None and (
        (root.findtext('plot') or '').strip() != expected_source
        or (root.findtext('originalplot') or '').strip() != expected_source
    ):
        raise PlotChangedError(str(nfo_path))
    if plot_elem is None or not (plot_elem.text or "").strip():
        raise PlotEmptyError(str(nfo_path))

    old_plot = plot_elem.text or ""
    old_original_elem = root.find("originalplot")
    old_original = (
        old_original_elem.text or ""
        if old_original_elem is not None
        else None
    )

    plot_same = old_plot == new_plot
    if new_original is None:
        original_same = True
    elif new_original == "":
        original_same = old_original_elem is None
    else:
        original_same = (
            old_original_elem is not None and old_original == new_original
        )
    if plot_same and original_same:
        return raw

    set_element_text(root, "plot", new_plot)
    if new_original is None:
        pass
    elif new_original == "":
        if old_original_elem is not None:
            root.remove(old_original_elem)
    else:
        set_element_text(
            root,
            "originalplot",
            new_original,
            after_tag="plot",
        )

    out = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with atomic_write(
        path,
        mode="wb",
        suffix=".nfo.tmp",
        mobile_fallback=True,
    ) as handle:
        handle.write(out)
    return out


def fill_empty_nfo_plot(
    nfo_path: Union[str, Path],
    *,
    new_plot: str,
    new_original: str,
) -> bool:
    """Fill ``<plot>`` only when it is missing or empty.

    Returns ``True`` when the file changed and ``False`` when another process
    already populated the plot. Existing summaries are never overwritten.
    """
    path = Path(nfo_path)
    if not path.exists():
        raise NfoNotFoundError(str(nfo_path))

    plot_text = strip_illegal_xml_chars(new_plot).strip()
    original_text = strip_illegal_xml_chars(new_original).strip()
    if not plot_text:
        raise PlotEmptyError(str(nfo_path))

    raw = sanitize_nfo_bytes(path.read_bytes())
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise NfoParseError(str(exc)) from exc

    plot_elem = root.find("plot")
    if plot_elem is not None and (plot_elem.text or "").strip():
        return False

    set_element_text(root, "plot", plot_text, after_tag="premiered")
    if original_text:
        set_element_text(
            root,
            "originalplot",
            original_text,
            after_tag="plot",
        )
    else:
        original_elem = root.find("originalplot")
        if original_elem is not None:
            root.remove(original_elem)

    out = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with atomic_write(
        path,
        mode="wb",
        suffix=".nfo.tmp",
        mobile_fallback=True,
    ) as handle:
        handle.write(out)
    return True
