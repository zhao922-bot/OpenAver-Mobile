"""title_writeback.py — 就地改寫 NFO 的標題相關元素（TASK-172-T1，CD-172-4）。

只改 <title>／<originaltitle>／（已存在才同步的）<sorttitle>／<openaver_title_record>，
其餘元素原樣保留。顯示標題計算全部委派 core.nfo_title_format.build_display_title。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from core.nfo_read import nfo_first_text
from core.nfo_title_format import build_display_title
from core.nfo_updater import set_element_text
from core.nfo_utils import sanitize_nfo_bytes
from core.organizer import _strip_illegal_xml_chars

# 公開別名：路由層寫 DB 前用同一支淨化函式（NFO 與 DB 同值）
strip_illegal_xml_chars = _strip_illegal_xml_chars

_DEFAULT_FORMAT = '[{num}]{title}'


class NfoNotFoundError(Exception):
    """NFO 檔案不存在。"""


class NfoParseError(Exception):
    """NFO 內容無法解析成 XML（sanitize 後仍失敗）。"""


def rewrite_nfo_titles(
    nfo_path,
    *,
    number,
    title_body,
    original_title,
    actors,
    maker,
    date,
    nfo_title_format,
) -> bytes:
    """改寫 NFO 的標題元素並回傳寫出的 bytes。

    NFO 不存在 → NfoNotFoundError；XML 無法解析 → NfoParseError（檔案不動）；
    讀／寫的 OSError 不包裝、原樣往外拋。
    """
    path = Path(nfo_path)
    if not path.exists():
        raise NfoNotFoundError(str(nfo_path))

    # sink 淨化（NFO-CTRL-01）：先淨化、後算顯示標題（與 generate_nfo 同序）
    number = _strip_illegal_xml_chars(number)
    title_body = _strip_illegal_xml_chars(title_body)
    original_title = _strip_illegal_xml_chars(original_title)
    maker = _strip_illegal_xml_chars(maker)
    date = _strip_illegal_xml_chars(date)
    actors = [_strip_illegal_xml_chars(a) for a in (actors or [])]

    raw = path.read_bytes()
    raw = sanitize_nfo_bytes(raw)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise NfoParseError(str(e)) from e

    display_title, body = build_display_title(
        number, title_body, original_title, actors, maker, date, nfo_title_format,
    )

    if number and not nfo_first_text(root, ("num", "id")):
        set_element_text(root, "num", number, after_tag="title")
    set_element_text(root, "title", display_title, after_tag="num")
    set_element_text(root, "originaltitle", original_title, after_tag="title")
    if root.find("sorttitle") is not None:
        root.find("sorttitle").text = display_title

    for old in list(root.findall("openaver_title_record")):
        root.remove(old)
    if nfo_title_format != _DEFAULT_FORMAT:
        rec = ET.SubElement(root, "openaver_title_record")
        ET.SubElement(rec, "written").text = display_title
        ET.SubElement(rec, "body").text = body

    out = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    path.write_bytes(out)
    return out
