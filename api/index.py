from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI(title="Samanta Social Publisher MCP", version="1.2.0")


def env_present(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def approval_required() -> bool:
    return os.getenv("APPROVAL_REQUIRED", "true").lower() != "false"


def base_url() -> str:
    return os.getenv("APP_BASE_URL", "https://samanta-social-publisher-mcp.vercel.app").rstrip("/")


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "runtime": "fastapi",
        "time": datetime.now(timezone.utc).isoformat(),
        "supabase_configured": env_present("SUPABASE_URL")
        and env_present("SUPABASE_PUBLISHABLE_KEY")
        and env_present("SUPABASE_SECRET_KEY"),
        "meta_configured": env_present("META_APP_ID") and env_present("META_APP_SECRET"),
        "linkedin_configured": env_present("LINKEDIN_CLIENT_ID")
        and env_present("LINKEDIN_CLIENT_SECRET"),
        "approval_required": approval_required(),
    }


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
          <div class='actions'>
            <a class='button' href='/connect/meta'>Conectar Meta</a>
            <a class='button' href='/connect/linkedin'>Conectar LinkedIn</a>
            <a class='button' href='/health'>Ver estado técnico</a>
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
    state = secrets.token_urlsafe(32)
    query = urlencode(
        {
            "client_id": app_id,
            "redirect_uri": f"{base_url()}/oauth/meta/callback",
            "state": state,
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
    state = secrets.token_urlsafe(32)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": f"{base_url()}/oauth/linkedin/callback",
            "state": state,
            "scope": "openid profile email w_member_social",
        }
    )
    return RedirectResponse(f"https://www.linkedin.com/oauth/v2/authorization?{query}")


@app.get("/oauth/meta/callback")
def meta_callback(code: str | None = None, error: str | None = None) -> dict[str, object]:
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {
        "authorization_received": bool(code),
        "provider": "meta",
        "token_exchange_completed": False,
        "next_step": "Configurar intercambio seguro y almacenamiento cifrado del token.",
    }


@app.get("/oauth/linkedin/callback")
def linkedin_callback(code: str | None = None, error: str | None = None) -> dict[str, object]:
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {
        "authorization_received": bool(code),
        "provider": "linkedin",
        "token_exchange_completed": False,
        "next_step": "Configurar intercambio seguro y almacenamiento cifrado del token.",
    }


@app.get("/mcp")
def mcp_status() -> dict[str, object]:
    return {
        "name": "samanta-social-publisher-mcp",
        "version": "1.2.0",
        "ready": False,
        "approval_required": approval_required(),
        "reason": "OAuth y herramientas MCP de publicación todavía no están completos.",
    }
