from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

Provider = Literal["meta", "linkedin"]

app = FastAPI(title="Samanta Social Publisher MCP", version="1.3.0")


def env_present(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def approval_required() -> bool:
    return os.getenv("APPROVAL_REQUIRED", "true").strip().lower() != "false"


def base_url() -> str:
    return os.getenv(
        "APP_BASE_URL", "https://samanta-social-publisher-mcp.vercel.app"
    ).rstrip("/")


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _oauth_secret() -> bytes:
    secret = os.getenv("OAUTH_STATE_SECRET", "").strip()
    if len(secret) < 32:
        raise HTTPException(
            status_code=503,
            detail="OAUTH_STATE_SECRET debe estar configurado con al menos 32 caracteres",
        )
    return secret.encode("utf-8")


def create_oauth_state(provider: Provider) -> str:
    payload = {
        "provider": provider,
        "nonce": secrets.token_urlsafe(24),
        "issued_at": int(time.time()),
    }
    encoded = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        _oauth_secret(), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded}.{_b64url_encode(signature)}"


def validate_oauth_state(
    state: str, expected_provider: Provider, max_age_seconds: int = 600
) -> dict[str, object]:
    try:
        encoded, signature = state.split(".", 1)
        supplied_signature = _b64url_decode(signature)
        expected_signature = hmac.new(
            _oauth_secret(), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ValueError("invalid signature")
        payload = json.loads(_b64url_decode(encoded))
        issued_at = int(payload["issued_at"])
        provider = payload["provider"]
        nonce = payload["nonce"]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Estado OAuth inválido") from exc

    now = int(time.time())
    if provider != expected_provider:
        raise HTTPException(status_code=400, detail="Proveedor OAuth incorrecto")
    if not isinstance(nonce, str) or len(nonce) < 20:
        raise HTTPException(status_code=400, detail="Nonce OAuth inválido")
    if issued_at > now + 60 or now - issued_at > max_age_seconds:
        raise HTTPException(status_code=400, detail="Estado OAuth vencido")

    return payload


def integration_status() -> dict[str, bool]:
    return {
        "supabase": env_present("SUPABASE_URL")
        and env_present("SUPABASE_PUBLISHABLE_KEY")
        and env_present("SUPABASE_SECRET_KEY"),
        "meta": env_present("META_APP_ID") and env_present("META_APP_SECRET"),
        "linkedin": env_present("LINKEDIN_CLIENT_ID")
        and env_present("LINKEDIN_CLIENT_SECRET"),
        "oauth_state": len(os.getenv("OAUTH_STATE_SECRET", "").strip()) >= 32,
    }


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers[
        "Content-Security-Policy"
    ] = "default-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
    return response


@app.get("/health")
def health() -> dict[str, object]:
    status = integration_status()
    return {
        "status": "ok",
        "runtime": "fastapi",
        "version": app.version,
        "time": datetime.now(timezone.utc).isoformat(),
        "supabase_configured": status["supabase"],
        "meta_configured": status["meta"],
        "linkedin_configured": status["linkedin"],
        "oauth_state_configured": status["oauth_state"],
        "approval_required": approval_required(),
    }


@app.get("/ready")
def ready() -> dict[str, object]:
    status = integration_status()
    missing = [name for name, configured in status.items() if not configured]
    if missing:
        raise HTTPException(
            status_code=503,
            detail={"ready": False, "missing": missing},
        )
    return {"ready": True, "approval_required": approval_required()}


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    status = health()

    def card(label: str, ok: bool, detail: str) -> str:
        state = "Configurado" if ok else "Pendiente"
        css = "ok" if ok else "pending"
        return f"""
        <section class='card'>
          <div class='row'><h2>{label}</h2><span class='{css}'>{state}</span></div>
          <p>{detail}</p>
        </section>
        """

    return f"""
    <!doctype html>
    <html lang='es'>
      <head>
        <meta charset='utf-8'>
        <meta name='viewport' content='width=device-width,initial-scale=1'>
        <title>Samanta Social Publisher</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 0; background:#f7f5f0; color:#171717; }}
          main {{ max-width:760px; margin:48px auto; padding:0 20px; }}
          h1 {{ font-family: Georgia, serif; font-size:38px; margin-bottom:6px; }}
          .subtitle {{ color:#595959; margin-bottom:28px; }}
          .card {{ background:#fff; border:1px solid #ddd7cc; border-radius:14px; padding:18px 20px; margin:12px 0; }}
          .row {{ display:flex; justify-content:space-between; align-items:center; gap:20px; }}
          .row h2 {{ margin:0; font-size:18px; }}
          .ok,.pending {{ border-radius:999px; padding:5px 10px; font-size:13px; }}
          .ok {{ background:#e7f3ea; color:#245c31; }}
          .pending {{ background:#f4ead7; color:#755318; }}
          .actions {{ display:flex; gap:12px; flex-wrap:wrap; margin-top:22px; }}
          a.button {{ text-decoration:none; padding:11px 15px; border-radius:9px; border:1px solid #171717; color:#171717; background:#fff; }}
          .notice {{ margin-top:24px; padding:16px; border-left:4px solid #171717; background:#fff; }}
        </style>
      </head>
      <body>
        <main>
          <h1>Samanta Social Publisher</h1>
          <p class='subtitle'>Panel privado de integración y aprobación.</p>
          {card('Supabase', bool(status['supabase_configured']), 'Base de datos, autenticación, aprobaciones y auditoría.')}
          {card('Meta', bool(status['meta_configured']), 'Instagram y Facebook mediante una aplicación oficial de Meta.')}
          {card('LinkedIn', bool(status['linkedin_configured']), 'Perfil profesional mediante OAuth oficial de LinkedIn.')}
          {card('Seguridad OAuth', bool(status['oauth_state_configured']), 'Firma y validación del parámetro state para evitar solicitudes manipuladas.')}
          <div class='actions'>
            <a class='button' href='/connect/meta'>Conectar Meta</a>
            <a class='button' href='/connect/linkedin'>Conectar LinkedIn</a>
            <a class='button' href='/health'>Ver estado técnico</a>
            <a class='button' href='/ready'>Ver preparación</a>
          </div>
          <div class='notice'><strong>Regla de seguridad:</strong> ningún contenido se publica sin aprobación expresa.</div>
        </main>
      </body>
    </html>
    """


@app.get("/connect/meta")
def connect_meta() -> RedirectResponse:
    app_id = os.getenv("META_APP_ID", "").strip()
    if not app_id:
        raise HTTPException(status_code=503, detail="META_APP_ID no está configurado")
    query = urlencode(
        {
            "client_id": app_id,
            "redirect_uri": f"{base_url()}/oauth/meta/callback",
            "state": create_oauth_state("meta"),
            "response_type": "code",
            "scope": "pages_show_list,pages_read_engagement,instagram_basic,instagram_content_publish",
        }
    )
    return RedirectResponse(f"https://www.facebook.com/v23.0/dialog/oauth?{query}")


@app.get("/connect/linkedin")
def connect_linkedin() -> RedirectResponse:
    client_id = os.getenv("LINKEDIN_CLIENT_ID", "").strip()
    if not client_id:
        raise HTTPException(status_code=503, detail="LINKEDIN_CLIENT_ID no está configurado")
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": f"{base_url()}/oauth/linkedin/callback",
            "state": create_oauth_state("linkedin"),
            "scope": "openid profile email w_member_social",
        }
    )
    return RedirectResponse(f"https://www.linkedin.com/oauth/v2/authorization?{query}")


@app.get("/oauth/meta/callback")
def meta_callback(
    state: str,
    code: str | None = None,
    error: str | None = None,
) -> dict[str, object]:
    if error:
        raise HTTPException(status_code=400, detail=error)
    validate_oauth_state(state, "meta")
    return {
        "authorization_received": bool(code),
        "provider": "meta",
        "state_validated": True,
        "token_exchange_completed": False,
        "next_step": "Configurar intercambio seguro y almacenamiento cifrado del token.",
    }


@app.get("/oauth/linkedin/callback")
def linkedin_callback(
    state: str,
    code: str | None = None,
    error: str | None = None,
) -> dict[str, object]:
    if error:
        raise HTTPException(status_code=400, detail=error)
    validate_oauth_state(state, "linkedin")
    return {
        "authorization_received": bool(code),
        "provider": "linkedin",
        "state_validated": True,
        "token_exchange_completed": False,
        "next_step": "Configurar intercambio seguro y almacenamiento cifrado del token.",
    }


@app.get("/mcp")
def mcp_status() -> dict[str, object]:
    status = integration_status()
    return {
        "name": "samanta-social-publisher-mcp",
        "version": app.version,
        "ready": all(status.values()),
        "approval_required": approval_required(),
        "publishing_enabled": False,
        "reason": "El intercambio OAuth y las herramientas MCP de publicación todavía no están completos.",
    }
