"""Small Pydantic v1 compatibility layer for the OpenAver Android port.

OpenAver targets Pydantic v2. Android has no official pydantic-core wheel, so
the mobile build uses the pure-Python Pydantic v1 line and supplies the few v2
APIs used by this codebase.
"""

from __future__ import annotations


def install() -> None:
    import pydantic

    if int(pydantic.VERSION.split(".", 1)[0]) >= 2:
        return

    from pydantic import BaseModel, validator

    def model_dump(self, *args, **kwargs):
        # OpenAver uses v2's model_dump() with no mode-specific arguments.
        return self.dict(*args, **kwargs)

    def model_validate(cls, value, *args, **kwargs):
        return cls.parse_obj(value)

    def model_copy(self, *args, **kwargs):
        # OpenAver calls v2's model_copy(update=...) while merging scraper
        # results. Pydantic v1 exposes the equivalent API as copy().
        return self.copy(*args, **kwargs)

    def field_validator(*fields, mode="after", **kwargs):
        if mode == "before":
            kwargs["pre"] = True
        elif mode != "after":
            raise ValueError(f"unsupported Pydantic v1 validator mode: {mode}")
        kwargs.setdefault("allow_reuse", True)
        return validator(*fields, **kwargs)

    BaseModel.model_dump = model_dump
    BaseModel.model_validate = classmethod(model_validate)
    BaseModel.model_copy = model_copy
    pydantic.field_validator = field_validator
    pydantic.ConfigDict = dict
