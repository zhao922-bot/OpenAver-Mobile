"""Image payload decode + magic-byte helpers.

Host → codec 對應只存在於 core.image_host_policy；本模組只認得 codec 名字。
"""
from __future__ import annotations

from core.image_host_policy import codec_for_host

# 魔數表唯一一份（D3／BE-TEST-14）：image_media_type 與 looks_like_image 共用。
_IMAGE_MAGICS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # 需再驗 WEBP；見 image_media_type
    (b"BM", "image/bmp"),
)


_AVIF_BRANDS = (b"avif", b"avis")
_FTYP_MAX = 256  # ftyp 盒 size 的合理上限，防怪 size


def _is_avif(content: bytes) -> bool:
    """ftyp 盒的 major brand 或任一 compatible brand 是 avif／avis（mp42、heic 等不是圖）。

    合法 AVIF 的 major brand 可以是 mif1／miaf，avif 只出現在 compatible brands。
    """
    if len(content) < 12 or content[4:8] != b"ftyp":
        return False
    if content[8:12] in _AVIF_BRANDS:
        return True
    size = int.from_bytes(content[0:4], "big")
    if size < 16 or size > min(len(content), _FTYP_MAX):
        return False
    return any(content[i:i + 4] in _AVIF_BRANDS for i in range(16, size - 3, 4))


def image_media_type(content: bytes) -> str | None:
    """依魔數回傳 media type；認不出來回 None。"""
    if not content:
        return None
    if _is_avif(content):
        return "image/avif"
    for magic, media in _IMAGE_MAGICS:
        if content.startswith(magic):
            if media == "image/webp":
                # RIFF....WEBP
                if len(content) >= 12 and content[8:12] == b"WEBP":
                    return media
                continue
            return media
    return None


def looks_like_image(content: bytes) -> bool:
    """內容是不是可辨識的圖片位元組（魔數表與 image_media_type 同一份）。"""
    return image_media_type(content) is not None


def _decode_javdb_xor(content: bytes) -> bytes:
    if len(content) < 2:
        return b""
    key = content[0]
    return bytes(b ^ key for b in content[1:])


_CODECS = {
    "javdb-xor": _decode_javdb_xor,
}


def decode_image_payload(host: str, content: bytes) -> bytes:
    """依 registry 的 payload_codec 解碼；查不到 codec 則原樣回傳。

    未實作的 codec 名 → ValueError（不得靜默原樣回傳）。
    """
    codec = codec_for_host(host)
    if codec is None:
        return content
    decoder = _CODECS.get(codec)
    if decoder is None:
        raise ValueError(f"unknown image payload_codec: {codec}")
    return decoder(content)
