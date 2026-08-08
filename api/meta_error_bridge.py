from __future__ import annotations

from urllib.parse import parse_qs, urlencode


def install_meta_error_bridge() -> None:
    from fastapi import FastAPI

    original = FastAPI.__call__
    if getattr(original, "_samanta_meta_error_bridge", False):
        return

    async def patched(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/oauth/meta/callback":
            query_text = (scope.get("query_string") or b"").decode("utf-8", errors="ignore")
            query = parse_qs(query_text, keep_blank_values=True)
            if not query.get("error") and query.get("error_message"):
                message = query["error_message"][0]
                code = (query.get("error_code") or [""])[0]
                detail = f"Meta OAuth {code}: {message}" if code else f"Meta OAuth: {message}"
                new_query = query_text + ("&" if query_text else "") + urlencode({"error": detail})
                scope = dict(scope)
                scope["query_string"] = new_query.encode("utf-8")
        return await original(self, scope, receive, send)

    patched._samanta_meta_error_bridge = True
    FastAPI.__call__ = patched
