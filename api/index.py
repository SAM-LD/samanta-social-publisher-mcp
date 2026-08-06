from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

Provider = Literal["meta", "linkedin"]
OWNER_ID = "00000000-0000-4000-8000-000000000001"
app = FastAPI(title="Samanta Social Publisher MCP", version="2.0.0")


def env(name: str) -> str:
    return os.getenv(name, "").strip()


def base_url() -> str:
    return env("APP_BASE_URL").rstrip("/") or "https://samanta-social-publisher-mcp-9by1.vercel.app"


def configured(name: str) -> bool:
    return bool(env(name))


def _secret() -> bytes:
    value = env("OAUTH_STATE_SECRET")
    if len(value) < 32:
        raise HTTPException(503, "OAUTH_STATE_SECRET no está configurado correctamente")
    return value.encode()


def _fernet() -> Fernet:
    key = hashlib.sha256(b"samanta-token-v1|" + _secret()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise HTTPException(500, "No se pudo descifrar el token") from exc


def state_create(provider: Provider) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"provider": provider, "iat": int(time.time()), "nonce": secrets.token_urlsafe(24)}, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def state_validate(state: str, provider: Provider) -> None:
    try:
        payload, supplied = state.split(".", 1)
        expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            raise ValueError
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        data = json.loads(raw)
        if data["provider"] != provider or int(time.time()) - int(data["iat"]) > 600:
            raise ValueError
    except Exception as exc:
        raise HTTPException(400, "Estado OAuth inválido o vencido") from exc


def admin_required(authorization: str | None) -> None:
    expected = hmac.new(_secret(), b"samanta-admin-v1", hashlib.sha256).hexdigest()
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(403, "Autorización inválida")


def sb_headers(prefer: str | None = None) -> dict[str, str]:
    key = env("SUPABASE_SECRET_KEY")
    if not key:
        raise HTTPException(503, "Supabase no está configurado")
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    return headers


def sb(method: str, path: str, *, params: dict[str, Any] | None = None, payload: Any = None, prefer: str | None = None) -> Any:
    url = env("SUPABASE_URL").rstrip("/") + "/rest/v1/" + path.lstrip("/")
    try:
        response = httpx.request(method, url, headers=sb_headers(prefer), params=params, json=payload, timeout=25)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "No se pudo acceder a Supabase") from exc
    if response.status_code >= 400:
        raise HTTPException(502, {"provider": "supabase", "status": response.status_code, "error": response.text[:500]})
    if not response.content:
        return None
    return response.json()


def provider_request(method: str, url: str, *, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None, data: dict[str, Any] | None = None, payload: Any = None) -> httpx.Response:
    try:
        response = httpx.request(method, url, headers=headers, params=params, data=data, json=payload, timeout=30)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "No se pudo acceder al proveedor") from exc
    if response.status_code >= 400:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text[:500]
        raise HTTPException(502, {"status": response.status_code, "error": detail})
    return response


def upsert_account(provider: Provider, external_id: str, label: str, scopes: list[str], metadata: dict[str, Any], access_token: str, expires_at: datetime | None = None) -> dict[str, Any]:
    rows = sb("POST", "social_accounts", params={"on_conflict": "owner_id,provider,external_account_id"}, payload={"owner_id": OWNER_ID, "provider": provider, "external_account_id": external_id, "account_label": label, "connected": True, "scopes": scopes, "token_expires_at": expires_at.isoformat() if expires_at else None, "last_verified_at": datetime.now(timezone.utc).isoformat(), "metadata": metadata}, prefer="resolution=merge-duplicates,return=representation")
    account = rows[0]
    sb("POST", "rpc/store_social_token", payload={"p_social_account_id": account["id"], "p_access_token_ciphertext": encrypt(access_token), "p_refresh_token_ciphertext": None, "p_encryption_version": 1})
    return account


def account_token(account_id: str) -> str:
    rows = sb("POST", "rpc/read_social_token", payload={"p_social_account_id": account_id})
    if not rows:
        raise HTTPException(409, "La cuenta no tiene token")
    return decrypt(rows[0]["access_token_ciphertext"])


def get_content(content_id: str) -> dict[str, Any]:
    rows = sb("GET", "content_items", params={"select": "*", "id": f"eq.{content_id}", "owner_id": f"eq.{OWNER_ID}", "limit": "1"})
    if not rows:
        raise HTTPException(404, "Contenido no encontrado")
    return rows[0]


def get_account(content: dict[str, Any]) -> dict[str, Any]:
    channel = content["channel"]
    rows = sb("GET", "social_accounts", params={"select": "*", "owner_id": f"eq.{OWNER_ID}", "connected": "eq.true"}) or []
    rows = [row for row in rows if (row.get("metadata") or {}).get("channel") == channel]
    selected = content.get("social_account_id")
    if selected:
        rows = [row for row in rows if row["id"] == selected]
    if len(rows) != 1:
        raise HTTPException(409, "Debe existir exactamente una cuenta conectada para el canal")
    return rows[0]


def approved(content_id: str) -> bool:
    rows = sb("GET", "approvals", params={"select": "id", "content_id": f"eq.{content_id}", "owner_id": f"eq.{OWNER_ID}", "decision": "eq.approved", "limit": "1"})
    return bool(rows)


def publish_linkedin(content: dict[str, Any], account: dict[str, Any], token: str) -> str:
    if content.get("media_urls"):
        raise HTTPException(422, "LinkedIn admite por ahora publicaciones de texto")
    author = (account.get("metadata") or {}).get("author_urn") or f"urn:li:person:{account['external_account_id']}"
    response = provider_request("POST", "https://api.linkedin.com/rest/posts", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "X-Restli-Protocol-Version": "2.0.0", "Linkedin-Version": env("LINKEDIN_VERSION") or "202607"}, payload={"author": author, "commentary": content["body"], "visibility": "PUBLIC", "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []}, "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False})
    return response.headers.get("x-restli-id") or "linkedin:published"


def publish_facebook(content: dict[str, Any], account: dict[str, Any], token: str) -> str:
    page_id = (account.get("metadata") or {}).get("page_id")
    if not page_id:
        raise HTTPException(409, "Falta Page ID")
    version = env("META_GRAPH_VERSION") or "v23.0"
    if content.get("media_urls"):
        response = provider_request("POST", f"https://graph.facebook.com/{version}/{page_id}/photos", data={"url": content["media_urls"][0], "caption": content["body"], "access_token": token})
    else:
        response = provider_request("POST", f"https://graph.facebook.com/{version}/{page_id}/feed", data={"message": content["body"], "access_token": token})
    data = response.json()
    return str(data.get("post_id") or data.get("id") or "facebook:published")


def publish_instagram(content: dict[str, Any], account: dict[str, Any], token: str) -> str:
    ig_id = (account.get("metadata") or {}).get("ig_user_id")
    media = content.get("media_urls") or []
    if not ig_id or len(media) != 1:
        raise HTTPException(422, "Instagram requiere una cuenta válida y un solo archivo público")
    version = env("META_GRAPH_VERSION") or "v23.0"
    create = provider_request("POST", f"https://graph.facebook.com/{version}/{ig_id}/media", data={"image_url": media[0], "caption": content["body"], "access_token": token}).json()
    creation_id = create.get("id")
    if not creation_id:
        raise HTTPException(502, "Meta no devolvió un contenedor")
    result = provider_request("POST", f"https://graph.facebook.com/{version}/{ig_id}/media_publish", data={"creation_id": creation_id, "access_token": token}).json()
    return str(result.get("id") or "instagram:published")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
    return response


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "version": app.version, "supabase_configured": configured("SUPABASE_URL") and configured("SUPABASE_SECRET_KEY"), "meta_configured": configured("META_APP_ID") and configured("META_APP_SECRET"), "linkedin_configured": configured("LINKEDIN_CLIENT_ID") and configured("LINKEDIN_CLIENT_SECRET"), "oauth_state_configured": len(env("OAUTH_STATE_SECRET")) >= 32, "oauth_exchange_implemented": True, "publishing_implemented": True, "approval_required": True}


@app.get("/ready")
def ready() -> dict[str, Any]:
    status = health()
    if not all(status[key] for key in ("supabase_configured", "meta_configured", "linkedin_configured", "oauth_state_configured")):
        raise HTTPException(503, {"ready": False})
    return {"ready": True, "approval_required": True}


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return """<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Samanta Social Publisher</title></head><body style='font-family:Arial;max-width:720px;margin:48px auto;padding:0 20px'><h1>Samanta Social Publisher</h1><p>OAuth, almacenamiento cifrado y publicación con aprobación expresa.</p><p><a href='/connect/linkedin'>Conectar LinkedIn</a> · <a href='/connect/meta'>Conectar Meta</a> · <a href='/health'>Estado</a></p><strong>Nada se publica sin una aprobación registrada para el contenido.</strong></body></html>"""


@app.get("/connect/linkedin")
def connect_linkedin() -> RedirectResponse:
    query = urlencode({"response_type": "code", "client_id": env("LINKEDIN_CLIENT_ID"), "redirect_uri": f"{base_url()}/oauth/linkedin/callback", "state": state_create("linkedin"), "scope": "openid profile email w_member_social"})
    return RedirectResponse(f"https://www.linkedin.com/oauth/v2/authorization?{query}")


@app.get("/oauth/linkedin/callback", response_class=HTMLResponse)
def linkedin_callback(state: str, code: str | None = None, error: str | None = None):
    if error or not code:
        raise HTTPException(400, error or "Falta código OAuth")
    state_validate(state, "linkedin")
    token_data = provider_request("POST", "https://www.linkedin.com/oauth/v2/accessToken", headers={"Content-Type": "application/x-www-form-urlencoded"}, data={"grant_type": "authorization_code", "code": code, "client_id": env("LINKEDIN_CLIENT_ID"), "client_secret": env("LINKEDIN_CLIENT_SECRET"), "redirect_uri": f"{base_url()}/oauth/linkedin/callback"}).json()
    token = token_data.get("access_token")
    if not token:
        raise HTTPException(502, "LinkedIn no devolvió token")
    user = provider_request("GET", "https://api.linkedin.com/v2/userinfo", headers={"Authorization": f"Bearer {token}"}).json()
    external_id = str(user.get("sub") or "")
    if not external_id:
        raise HTTPException(502, "LinkedIn no devolvió identidad")
    expires = datetime.now(timezone.utc) + timedelta(seconds=int(token_data.get("expires_in") or 0)) if token_data.get("expires_in") else None
    upsert_account("linkedin", external_id, str(user.get("name") or user.get("email") or "LinkedIn"), str(token_data.get("scope") or "openid profile email w_member_social").split(), {"channel": "linkedin", "author_urn": f"urn:li:person:{external_id}"}, token, expires)
    return "<h1>LinkedIn conectado</h1><p>Token cifrado. Toda publicación requiere aprobación expresa.</p><p><a href='/'>Volver</a></p>"


@app.get("/connect/meta")
def connect_meta() -> RedirectResponse:
    version = env("META_GRAPH_VERSION") or "v23.0"
    query = urlencode({"client_id": env("META_APP_ID"), "redirect_uri": f"{base_url()}/oauth/meta/callback", "state": state_create("meta"), "response_type": "code", "scope": "pages_show_list,pages_read_engagement,pages_manage_posts,instagram_basic,instagram_content_publish"})
    return RedirectResponse(f"https://www.facebook.com/{version}/dialog/oauth?{query}")


@app.get("/oauth/meta/callback", response_class=HTMLResponse)
def meta_callback(state: str, code: str | None = None, error: str | None = None):
    if error or not code:
        raise HTTPException(400, error or "Falta código OAuth")
    state_validate(state, "meta")
    version = env("META_GRAPH_VERSION") or "v23.0"
    graph = f"https://graph.facebook.com/{version}"
    token = provider_request("GET", f"{graph}/oauth/access_token", params={"client_id": env("META_APP_ID"), "client_secret": env("META_APP_SECRET"), "redirect_uri": f"{base_url()}/oauth/meta/callback", "code": code}).json().get("access_token")
    if not token:
        raise HTTPException(502, "Meta no devolvió token")
    pages = provider_request("GET", f"{graph}/me/accounts", params={"fields": "id,name,access_token,tasks,instagram_business_account{id,username,name}", "limit": "100", "access_token": token}).json().get("data") or []
    count = 0
    scopes = ["pages_show_list", "pages_read_engagement", "pages_manage_posts", "instagram_basic", "instagram_content_publish"]
    for page in pages:
        page_id, page_token = str(page.get("id") or ""), page.get("access_token")
        if not page_id or not page_token:
            continue
        upsert_account("meta", f"facebook:{page_id}", str(page.get("name") or page_id), scopes, {"channel": "facebook", "page_id": page_id}, page_token)
        count += 1
        ig = page.get("instagram_business_account") or {}
        if ig.get("id"):
            ig_id = str(ig["id"])
            upsert_account("meta", f"instagram:{ig_id}", str(ig.get("username") or ig.get("name") or ig_id), scopes, {"channel": "instagram", "ig_user_id": ig_id, "page_id": page_id}, page_token)
            count += 1
    if not count:
        raise HTTPException(409, "Meta no devolvió páginas administradas")
    return f"<h1>Meta conectado</h1><p>Cuentas guardadas: {count}. Tokens cifrados. Toda publicación requiere aprobación expresa.</p><p><a href='/'>Volver</a></p>"


@app.post("/content")
def content_create(data: dict[str, Any] = Body(...), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    admin_required(authorization)
    channel = data.get("channel")
    if channel not in {"instagram", "facebook", "linkedin"} or not str(data.get("body") or "").strip():
        raise HTTPException(422, "Canal y texto son obligatorios")
    rows = sb("POST", "content_items", payload={"owner_id": OWNER_ID, "channel": channel, "content_type": data.get("content_type", "post"), "title": data.get("title"), "body": str(data["body"]), "media_urls": data.get("media_urls") or [], "status": "draft", "social_account_id": data.get("social_account_id")}, prefer="return=representation")
    return {"content": rows[0]}


@app.post("/content/{content_id}/decision")
def content_decision(content_id: str, data: dict[str, Any] = Body(...), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    admin_required(authorization)
    decision = data.get("decision")
    if decision not in {"approved", "rejected"}:
        raise HTTPException(422, "Decisión inválida")
    get_content(content_id)
    sb("POST", "approvals", params={"on_conflict": "content_id,owner_id"}, payload={"content_id": content_id, "owner_id": OWNER_ID, "decision": decision, "note": data.get("note")}, prefer="resolution=merge-duplicates,return=minimal")
    sb("PATCH", "content_items", params={"id": f"eq.{content_id}"}, payload={"status": decision}, prefer="return=minimal")
    return {"content_id": content_id, "decision": decision}


@app.post("/content/{content_id}/publish")
def content_publish(content_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    admin_required(authorization)
    content = get_content(content_id)
    if content.get("status") != "approved" or not approved(content_id):
        raise HTTPException(409, "Falta aprobación expresa")
    existing = sb("GET", "publish_jobs", params={"select": "*", "content_id": f"eq.{content_id}", "status": "eq.succeeded", "limit": "1"})
    if existing:
        return {"published": True, "idempotent": True, "external_post_id": content.get("external_post_id")}
    account = get_account(content)
    jobs = sb("POST", "publish_jobs", payload={"content_id": content_id, "owner_id": OWNER_ID, "provider": account["provider"], "status": "running", "attempts": 1, "locked_at": datetime.now(timezone.utc).isoformat()}, prefer="return=representation")
    job_id = jobs[0]["id"]
    try:
        sb("PATCH", "content_items", params={"id": f"eq.{content_id}"}, payload={"status": "publishing"}, prefer="return=minimal")
        token = account_token(account["id"])
        if content["channel"] == "linkedin":
            external_id = publish_linkedin(content, account, token)
        elif content["channel"] == "facebook":
            external_id = publish_facebook(content, account, token)
        else:
            external_id = publish_instagram(content, account, token)
        sb("PATCH", "content_items", params={"id": f"eq.{content_id}"}, payload={"status": "published", "published_at": datetime.now(timezone.utc).isoformat(), "external_post_id": external_id, "last_error": None}, prefer="return=minimal")
        sb("PATCH", "publish_jobs", params={"id": f"eq.{job_id}"}, payload={"status": "succeeded", "completed_at": datetime.now(timezone.utc).isoformat()}, prefer="return=minimal")
        return {"published": True, "external_post_id": external_id}
    except HTTPException as exc:
        error_text = json.dumps(exc.detail, ensure_ascii=False)[:1500]
        sb("PATCH", "publish_jobs", params={"id": f"eq.{job_id}"}, payload={"status": "failed", "completed_at": datetime.now(timezone.utc).isoformat(), "last_error": error_text}, prefer="return=minimal")
        sb("PATCH", "content_items", params={"id": f"eq.{content_id}"}, payload={"status": "failed", "last_error": error_text}, prefer="return=minimal")
        raise


@app.get("/mcp")
def mcp_status() -> dict[str, Any]:
    try:
        accounts = sb("GET", "social_accounts", params={"select": "id", "owner_id": f"eq.{OWNER_ID}", "connected": "eq.true"}) or []
    except HTTPException:
        accounts = []
    return {"name": "samanta-social-publisher-mcp", "version": app.version, "ready": health()["oauth_state_configured"], "oauth_exchange_implemented": True, "publishing_implemented": True, "publishing_enabled": bool(accounts), "connected_accounts": len(accounts), "approval_required": True, "safety": "No se publica sin aprobación expresa registrada."}
