"""Protocol selection, endpoint construction and connection identity (no secrets)."""
from __future__ import annotations

import hashlib
import json
from urllib.parse import urlsplit, urlunsplit

QWEN_EMBEDDINGS_PATH = "/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"
FACES_PROMPT = (
    'Locate every clearly visible human face in this image. Do not identify people. '
    'Return only a JSON object: {"faces":[{"box":[x,y,width,height],"score":0.9}]}. '
    'Coordinates must be normalized to 0..1 relative to the ENTIRE supplied image, '
    'with the top-left as origin. Boxes enclose faces, not whole bodies. '
    'Width and height must be positive; x+width and y+height must not exceed 1. '
    'score must be between 0 and 1. If there is no visible face, return {"faces":[]}. '
    'Do not return explanations, markdown or invented faces.'
)


def provider_of(cfg) -> str:
    return str(getattr(cfg, "provider", None) or "endpoint")


def endpoint_url(base: str, suffix: str) -> str:
    from core.ai_services.embeddings import EndpointError
    try:
        parts = urlsplit(base.strip())
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment:
            raise ValueError("invalid base")
        current = [p for p in parts.path.split("/") if p]
        target = [p for p in suffix.split("/") if p]
        overlap = 0
        for count in range(1, min(len(current), len(target)) + 1):
            if current[-count:] == target[:count]:
                overlap = count
        path = "/" + "/".join(current + target[overlap:])
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))
    except (ValueError, AttributeError):
        raise EndpointError("contract", "url", None) from None


def embedding_connection_id(cfg) -> str:
    provider = provider_of(cfg)
    suffix = QWEN_EMBEDDINGS_PATH if provider == "qwen" else "/v1/embeddings"
    normalized = endpoint_url(str(getattr(cfg, "url", "") or ""), suffix)
    model = str(getattr(cfg, "model", "") or "").strip()
    return hashlib.sha256(json.dumps([provider, normalized, model]).encode()).hexdigest()[:24]


def cloud_model_id(cfg, returned_model: str) -> str:
    return f"qwen:{embedding_connection_id(cfg)}:{returned_model}"


def face_model_id(cfg, returned_model: str) -> str:
    endpoint = endpoint_url(str(cfg.url), "/chat/completions")
    identity = hashlib.sha256(json.dumps([endpoint, cfg.model]).encode()).hexdigest()[:24]
    return f"vision:{identity}:{returned_model}"
