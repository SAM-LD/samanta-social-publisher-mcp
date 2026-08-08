from __future__ import annotations

import hashlib
import hmac
import html
import time
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from api.index import env, provider_request, upsert_account

router = APIRouter()

_MANUAL_KEY_SHA256 = "fbe065a68378e225d3e3883c409ea8df848f354b428f65f3e4eb0b0cda64c03a"
_MANUAL_EXPIRES_AT = 1786204800  # 2026-08-08 16:00:00 UTC
_REQUIRED_SCOPES = {
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "instagram_basic",
    "instagram_content_publish",
}


def _authorized(key: str) -> bool:
    if time.time() > _MANUAL_EXPIRES_AT:
        return False
    digest = hashlib.sha256((key or "").encode()).hexdigest()
    return hmac.compare_digest(digest, _MANUAL_KEY_SHA256)


def _page(message: str, *, ok: bool = False) -> HTMLResponse:
    title = "Meta conectado" if ok else "Conectar Meta"
    return HTMLResponse(
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title></head>"
        "<body style='font-family:Arial;max-width:720px;margin:48px auto;padding:0 20px'>"
        f"<h1>{html.escape(title)}</h1><p>{message}</p>"
        "<p><strong>No se publica nada sin aprobación expresa.</strong></p>"
        "</body></html>"
    )


@router.get("/connect/meta/manual", response_class=HTMLResponse)
def manual_meta_form(key: str = ""):
    if not _authorized(key):
        raise HTTPException(403, "Enlace vencido o inválido")
    safe_key = html.escape(key, quote=True)
    return HTMLResponse(
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Conectar Meta</title></head>"
        "<body style='font-family:Arial;max-width:720px;margin:48px auto;padding:0 20px'>"
        "<h1>Conectar Meta</h1>"
        "<p>Pegá abajo el token de acceso generado en Meta. El token se valida y se guarda cifrado.</p>"
        "<form method='post' action='/connect/meta/manual'>"
        f"<input type='hidden' name='key' value='{safe_key}'>"
        "<textarea name='access_token' required autocomplete='off' spellcheck='false' "
        "style='width:100%;height:140px' placeholder='Token de acceso de Meta'></textarea>"
        "<p><button type='submit' style='padding:10px 18px'>Conectar</button></p>"
        "</form><p><strong>No se publica nada sin aprobación expresa.</strong></p>"
        "</body></html>"
    )


@router.post("/connect/meta/manual", response_class=HTMLResponse)
async def manual_meta_connect(request: Request):
    raw = (await request.body()).decode("utf-8", errors="ignore")
    form = parse_qs(raw, keep_blank_values=True)
    key = (form.get("key") or [""])[0]
    token = (form.get("access_token") or [""])[0].strip()
    if not _authorized(key):
        raise HTTPException(403, "Enlace vencido o inválido")
    if not token:
        raise HTTPException(422, "Falta el token de acceso")

    version = env("META_GRAPH_VERSION") or "v23.0"
    graph = f"https://graph.facebook.com/{version}"

    effective_token = token
    try:
        exchanged = provider_request(
            "GET",
            f"{graph}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": env("META_APP_ID"),
                "client_secret": env("META_APP_SECRET"),
                "fb_exchange_token": token,
            },
        ).json()
        effective_token = str(exchanged.get("access_token") or token)
    except HTTPException:
        effective_token = token

    permissions = provider_request(
        "GET",
        f"{graph}/me/permissions",
        params={"access_token": effective_token},
    ).json().get("data") or []
    granted = {
        str(item.get("permission"))
        for item in permissions
        if item.get("status") == "granted" and item.get("permission")
    }
    missing = sorted(_REQUIRED_SCOPES - granted)
    if missing:
        raise HTTPException(409, "Faltan permisos en el token de Meta: " + ", ".join(missing))

    pages = provider_request(
        "GET",
        f"{graph}/me/accounts",
        params={
            "fields": "id,name,access_token,tasks,instagram_business_account{id,username,name}",
            "limit": "100",
            "access_token": effective_token,
        },
    ).json().get("data") or []

    count = 0
    scopes = sorted(_REQUIRED_SCOPES)
    for page in pages:
        page_id = str(page.get("id") or "")
        page_token = str(page.get("access_token") or "")
        if not page_id or not page_token:
            continue
        upsert_account(
            "meta",
            f"facebook:{page_id}",
            str(page.get("name") or page_id),
            scopes,
            {"channel": "facebook", "page_id": page_id},
            page_token,
        )
        count += 1
        ig = page.get("instagram_business_account") or {}
        if ig.get("id"):
            ig_id = str(ig["id"])
            upsert_account(
                "meta",
                f"instagram:{ig_id}",
                str(ig.get("username") or ig.get("name") or ig_id),
                scopes,
                {"channel": "instagram", "ig_user_id": ig_id, "page_id": page_id},
                page_token,
            )
            count += 1

    if not count:
        raise HTTPException(409, "Meta no devolvió páginas administradas. Verificá que el token tenga acceso a tu Página.")

    return _page(
        f"Conexión completada. Cuentas guardadas: {count}. Los tokens quedaron cifrados.",
        ok=True,
    )
