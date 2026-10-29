from __future__ import annotations

import pydantic

from pydantic_v1_compat import install


def test_install_backports_model_copy_on_pydantic_v1():
    if int(pydantic.VERSION.split(".", 1)[0]) >= 2:
        return

    install()

    class Payload(pydantic.BaseModel):
        title: str
        rating: int = 0

    original = Payload(title="before")
    copied = original.model_copy(update={"rating": 5})

    assert copied.title == "before"
    assert copied.rating == 5
    assert original.rating == 0


def test_install_is_idempotent():
    install()
    install()
