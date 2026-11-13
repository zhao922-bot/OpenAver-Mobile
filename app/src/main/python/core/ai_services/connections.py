"""Connection defaults and one-time migration for independent AI services."""
from __future__ import annotations

DEFAULT_BASE_URLS = {
    "ollama": "http://localhost:11434",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "claude": "https://api.anthropic.com",
    "openai_official": "https://api.openai.com/v1",
    "openai": "",
}


def provider_base_url(provider: str, config: dict) -> str:
    key = "url" if provider == "ollama" else "base_url"
    return str(config.get(key) or DEFAULT_BASE_URLS.get(provider, "")).strip().rstrip("/")


def requires_api_key(provider: str, base_url: str) -> bool:
    return provider in ("gemini", "claude", "openai_official") and (
        not base_url.strip() or base_url.strip().rstrip("/") == DEFAULT_BASE_URLS[provider]
    )


def migrate_tags_connection(config: dict) -> bool:
    tags = config.setdefault("ai_services", {}).setdefault("tags", {})
    if tags.get("connection_version", 0) >= 1:
        return False
    provider = str(tags.get("provider") or "")
    source = (config.get("translate") or {}).get(provider) or {}
    # Explicit empty values are intentional; only legacy missing fields inherit.
    tags.setdefault("base_url", provider_base_url(provider, source))
    tags.setdefault("api_key", str(source.get("api_key") or ""))
    tags["connection_version"] = 1
    return True


async def fetch_provider_models(provider: str, base_url: str, api_key: str) -> list[str]:
    """Query only the supplied connection; never read another feature's config."""
    import httpx
    from core import anthropic_client, gemini_client
    if provider == "claude":
        data = await anthropic_client.list_models(api_key, timeout=10, base_url=base_url)
        items = data.get("data", [])
        return sorted({str(item["id"]) for item in items if isinstance(item, dict) and item.get("id")})
    base = base_url.rstrip("/")
    if provider == "gemini":
        url = base + "/models"
        headers = gemini_client.build_headers(api_key)
    else:
        url = base + ("/api/tags" if provider == "ollama" else "/models")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
    data = response.json()
    field = "models" if provider in ("gemini", "ollama") else "data"
    key = "name" if field == "models" else "id"
    return sorted({str(item[key]).removeprefix("models/") for item in data.get(field, [])
                   if isinstance(item, dict) and item.get(key)})
