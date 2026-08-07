from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata

_BOOTSTRAP_VERSION = "config-compat-v2"
_SUPABASE_URL = "https://zmnzgwwpspjidygwzygi.supabase.co"
_SUPABASE_PUBLISHABLE_KEY = "sb_publishable_95MtbIsPwTfqbM-7i4uTcQ_onHR2w0q"
_APP_BASE_URL = "https://samanta-social-publisher-mcp-9by1.vercel.app"

_REQUIRED_KEYS = (
    "SUPABASE_URL",
    "SUPABASE_PUBLISHABLE_KEY",
    "SUPABASE_SECRET_KEY",
    "META_APP_ID",
    "META_APP_SECRET",
    "LINKEDIN_CLIENT_ID",
    "LINKEDIN_CLIENT_SECRET",
    "OAUTH_STATE_SECRET",
)


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def _usable(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip().strip('"').strip("'")
    if not text:
        return False
    upper = _normalize(text)
    placeholder_tokens = (
        "VALOR_",
        "REEMPLAZAR",
        "YOUR_",
        "ID_DE_LA_APP",
        "SECRETO_DE_LA_APP",
        "CLIENT_ID_DE",
        "CLIENT_SECRET_DE",
        "CADENA_ALEATORIA",
    )
    return not (text.startswith("<") and text.endswith(">")) and not any(
        token in upper for token in placeholder_tokens
    )


def _clean(value: object) -> str:
    return str(value).strip().strip('"').strip("'")


def _environment_by_normalized_name() -> dict[str, str]:
    return {
        _normalize(key): _clean(value)
        for key, value in os.environ.items()
        if _usable(value)
    }


def _parse_mapping(raw: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    text = raw.strip()
    if not text:
        return parsed

    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            for key, value in payload.items():
                if _usable(value):
                    parsed[_normalize(str(key))] = _clean(value)
        elif isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    for key, value in item.items():
                        if _usable(value):
                            parsed[_normalize(str(key))] = _clean(value)
    except (json.JSONDecodeError, TypeError):
        pass

    expanded = text.replace("\\n", "\n")
    for segment in re.split(r"[\n;]+", expanded):
        line = segment.strip()
        if not line or line.startswith("#"):
            continue
        separator = "=" if "=" in line else ":" if ":" in line and not line.lower().startswith(("http://", "https://")) else None
        if separator:
            key, value = line.split(separator, 1)
            if _usable(value):
                parsed[_normalize(key)] = _clean(value)

    for match in re.finditer(
        r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ _-]{1,50})\s*=\s*(\"[^\"]*\"|'[^']*'|\S+)",
        expanded,
    ):
        key, value = match.groups()
        if _usable(value):
            parsed[_normalize(key)] = _clean(value)

    return parsed


def _tokenize(raw: str) -> list[str]:
    text = raw.replace("\\n", "\n").strip()
    if not text:
        return []
    separators = r"\s*\|\s*|[\n;]+"
    parts = [_clean(part) for part in re.split(separators, text) if _usable(part)]
    if len(parts) == 1 and "," in text and not text.lower().startswith(("http://", "https://")):
        comma_parts = [_clean(part) for part in text.split(",") if _usable(part)]
        if len(comma_parts) > 1:
            parts = comma_parts
    return parts


def _jwt_role(value: str) -> str:
    try:
        import base64

        pieces = value.split(".")
        if len(pieces) != 3:
            return ""
        payload = pieces[1] + "=" * (-len(pieces[1]) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        return str(decoded.get("role", ""))
    except Exception:
        return ""


def _extract_supabase_key(raw: str, prefix: str, legacy_role: str) -> str:
    text = str(raw or "")
    match = re.search(re.escape(prefix) + r"[A-Za-z0-9_-]+", text)
    if match:
        return match.group(0)
    for candidate in re.findall(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", text):
        if _jwt_role(candidate) == legacy_role:
            return candidate
    return _clean(text)


def _bootstrap() -> None:
    if os.environ.get("CONFIG_BOOTSTRAP_DONE") == _BOOTSTRAP_VERSION:
        return

    env = _environment_by_normalized_name()
    bundle_names = ("SUPABASE", "META", "LINKEDIN", "CONFIG", "VARIABLES", "ENV")
    bundles = {name: env.get(name, "") for name in bundle_names}

    parsed: dict[str, str] = {}
    for raw in bundles.values():
        if raw:
            parsed.update(_parse_mapping(raw))

    aliases: dict[str, tuple[str, ...]] = {
        "SUPABASE_URL": ("SUPABASE_URL", "URL_SUPABASE", "PROJECT_URL", "URL"),
        "SUPABASE_PUBLISHABLE_KEY": (
            "SUPABASE_PUBLISHABLE_KEY",
            "SUPABASE_ANON_KEY",
            "PUBLISHABLE_KEY",
            "ANON_KEY",
        ),
        "SUPABASE_SECRET_KEY": (
            "SUPABASE_SECRET_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
            "SECRET_KEY",
            "SERVICE_ROLE_KEY",
        ),
        "META_APP_ID": ("META_APP_ID", "APP_ID", "META_ID", "ID_META"),
        "META_APP_SECRET": ("META_APP_SECRET", "APP_SECRET", "META_SECRET", "SECRETO_META"),
        "LINKEDIN_CLIENT_ID": (
            "LINKEDIN_CLIENT_ID",
            "CLIENT_ID",
            "LINKEDIN_ID",
            "ID_LINKEDIN",
        ),
        "LINKEDIN_CLIENT_SECRET": (
            "LINKEDIN_CLIENT_SECRET",
            "CLIENT_SECRET",
            "LINKEDIN_SECRET",
            "SECRETO_LINKEDIN",
        ),
        "OAUTH_STATE_SECRET": ("OAUTH_STATE_SECRET", "OAUTH_SECRET", "STATE_SECRET"),
    }

    resolved_sources: dict[str, str] = {}
    for target, candidates in aliases.items():
        direct = env.get(target, "")
        if _usable(direct):
            os.environ[target] = direct
            resolved_sources[target] = "direct"
            continue
        for candidate in candidates:
            value = parsed.get(candidate, "")
            if _usable(value):
                os.environ[target] = value
                resolved_sources[target] = "bundle"
                break

    supabase_parts = _tokenize(bundles.get("SUPABASE", ""))
    if not os.environ.get("SUPABASE_URL"):
        url = next((part for part in supabase_parts if part.lower().startswith("https://")), "")
        os.environ["SUPABASE_URL"] = url or _SUPABASE_URL
        resolved_sources["SUPABASE_URL"] = "bundle" if url else "safe_fallback"
    if not os.environ.get("SUPABASE_PUBLISHABLE_KEY"):
        publishable = next(
            (
                part
                for part in supabase_parts
                if part.startswith("sb_publishable_") or _jwt_role(part) == "anon"
            ),
            "",
        )
        os.environ["SUPABASE_PUBLISHABLE_KEY"] = publishable or _SUPABASE_PUBLISHABLE_KEY
        resolved_sources["SUPABASE_PUBLISHABLE_KEY"] = "bundle" if publishable else "safe_fallback"
    if not os.environ.get("SUPABASE_SECRET_KEY"):
        secret = next(
            (
                part
                for part in supabase_parts
                if part.startswith("sb_secret_") or _jwt_role(part) == "service_role"
            ),
            "",
        )
        if not secret and len(supabase_parts) == 1:
            candidate = supabase_parts[0]
            if candidate.startswith("sb_secret_") or _jwt_role(candidate) == "service_role":
                secret = candidate
        if secret:
            os.environ["SUPABASE_SECRET_KEY"] = secret
            resolved_sources["SUPABASE_SECRET_KEY"] = "bundle"

    # This application is permanently bound to this Supabase project. Pin the
    # canonical URL so a malformed dashboard value cannot break outbound calls.
    if os.environ.get("SUPABASE_URL", "").rstrip("/") != _SUPABASE_URL:
        os.environ["SUPABASE_URL"] = _SUPABASE_URL
        resolved_sources["SUPABASE_URL"] = "validated_fallback"

    publishable_raw = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
    publishable_clean = _extract_supabase_key(publishable_raw, "sb_publishable_", "anon")
    if publishable_clean:
        os.environ["SUPABASE_PUBLISHABLE_KEY"] = publishable_clean
        if publishable_clean != publishable_raw:
            resolved_sources["SUPABASE_PUBLISHABLE_KEY"] = resolved_sources.get("SUPABASE_PUBLISHABLE_KEY", "direct") + "+sanitized"

    secret_raw = os.environ.get("SUPABASE_SECRET_KEY", "")
    secret_clean = _extract_supabase_key(secret_raw, "sb_secret_", "service_role")
    if secret_clean:
        os.environ["SUPABASE_SECRET_KEY"] = secret_clean
        if secret_clean != secret_raw:
            resolved_sources["SUPABASE_SECRET_KEY"] = resolved_sources.get("SUPABASE_SECRET_KEY", "direct") + "+sanitized"

    meta_parts = _tokenize(bundles.get("META", ""))
    if not os.environ.get("META_APP_ID"):
        app_id = next((part for part in meta_parts if part.isdigit() and len(part) >= 5), "")
        if not app_id and len(meta_parts) >= 2:
            app_id = meta_parts[0]
        if app_id:
            os.environ["META_APP_ID"] = app_id
            resolved_sources["META_APP_ID"] = "bundle"
    if not os.environ.get("META_APP_SECRET"):
        app_secret = next(
            (
                part
                for part in meta_parts
                if not part.isdigit() and len(part) >= 16 and "=" not in part
            ),
            "",
        )
        if not app_secret and len(meta_parts) >= 2:
            app_secret = meta_parts[1]
        if app_secret:
            os.environ["META_APP_SECRET"] = app_secret
            resolved_sources["META_APP_SECRET"] = "bundle"

    linkedin_parts = _tokenize(bundles.get("LINKEDIN", ""))
    if len(linkedin_parts) >= 2:
        if not os.environ.get("LINKEDIN_CLIENT_ID"):
            os.environ["LINKEDIN_CLIENT_ID"] = linkedin_parts[0]
            resolved_sources["LINKEDIN_CLIENT_ID"] = "bundle"
        if not os.environ.get("LINKEDIN_CLIENT_SECRET"):
            os.environ["LINKEDIN_CLIENT_SECRET"] = linkedin_parts[1]
            resolved_sources["LINKEDIN_CLIENT_SECRET"] = "bundle"

    if len(os.environ.get("OAUTH_STATE_SECRET", "").strip()) < 32:
        entropy = [raw for raw in bundles.values() if _usable(raw)]
        if entropy:
            derived = hashlib.sha256(
                ("samanta-oauth-state-v1|" + "|".join(entropy)).encode("utf-8")
            ).hexdigest()
            os.environ["OAUTH_STATE_SECRET"] = derived
            resolved_sources["OAUTH_STATE_SECRET"] = "derived_from_sensitive_bundles"

    os.environ.setdefault("APP_BASE_URL", _APP_BASE_URL)
    os.environ["APPROVAL_REQUIRED"] = "true"
    os.environ["CONFIG_BOOTSTRAP_DONE"] = _BOOTSTRAP_VERSION

    secret_value = os.environ.get("SUPABASE_SECRET_KEY", "")
    safe_status = {
        "bootstrap": _BOOTSTRAP_VERSION,
        "bundles_present": {name.lower(): bool(raw) for name, raw in bundles.items()},
        "resolved": {key.lower(): bool(os.environ.get(key, "").strip()) for key in _REQUIRED_KEYS},
        "sources": {key.lower(): resolved_sources.get(key, "missing") for key in _REQUIRED_KEYS},
        "supabase_runtime": {
            "url_validated": os.environ.get("SUPABASE_URL", "").rstrip("/") == _SUPABASE_URL,
            "secret_kind": "opaque" if secret_value.startswith("sb_secret_") else "legacy_jwt" if _jwt_role(secret_value) == "service_role" else "unknown",
            "secret_has_whitespace": any(char.isspace() for char in secret_value),
        },
        "approval_required": True,
    }
    print("CONFIG_BOOTSTRAP " + json.dumps(safe_status, sort_keys=True))


def _patch_httpx_supabase_headers() -> None:
    import httpx

    original = httpx.request
    if getattr(original, "_samanta_supabase_patch", False):
        return

    def patched(method, url, **kwargs):
        url_text = str(url)
        if ".supabase.co/rest/v1/" in url_text:
            headers = dict(kwargs.get("headers") or {})
            apikey = str(headers.get("apikey") or "")
            authorization = str(headers.get("Authorization") or "")
            if apikey.startswith("sb_") and authorization == f"Bearer {apikey}":
                headers.pop("Authorization", None)
                kwargs["headers"] = headers
            try:
                return original(method, url, **kwargs)
            except Exception as exc:
                print(f"SUPABASE_HTTPX_ERROR {type(exc).__name__}: {str(exc)[:300]}")
                raise
        return original(method, url, **kwargs)

    patched._samanta_supabase_patch = True
    httpx.request = patched


_bootstrap()
_patch_httpx_supabase_headers()
