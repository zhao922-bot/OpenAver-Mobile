from core.multipart_tokens import (
    detect_multipart_token,
    is_multipart_keyword,
    strip_part_token,
)
from core.organizer import (
    _detect_multipart_token,
    _is_multipart_kw,
    _strip_part_token,
)
from core.rename_normalizer import multipart_token


def test_multipart_token_primitives_share_one_contract():
    filename = "MIRD-151-cd2.mkv"

    assert detect_multipart_token(filename) == ("cd2", 2)
    assert strip_part_token("MIRD-151-cd2") == "MIRD-151"
    assert is_multipart_keyword("-pt2") is True
    assert is_multipart_keyword("-4k") is False

    assert _detect_multipart_token(filename) == ("cd2", 2)
    assert _strip_part_token("MIRD-151-cd2") == "MIRD-151"
    assert _is_multipart_kw("-pt2") is True
    assert multipart_token("MIRD-151-cd2") == "cd2"


def test_multipart_token_requires_a_real_boundary_and_single_digit():
    assert detect_multipart_token("apartment1.mp4") is None
    assert detect_multipart_token("ABC-123-cd10.mp4") is None
    assert detect_multipart_token("ABC-123_disc9.mp4") == ("disc9", 9)
