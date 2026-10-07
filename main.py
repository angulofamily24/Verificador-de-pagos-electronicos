from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.config import get_settings
from app.db import close_pool, init_pool, pool
from app.email_parser import parse_davivienda_email
from app.handlers import handle_message, pending_watcher
from app.service import register_email


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool(get_settings().database_url)
    watcher = asyncio.create_task(pending_watcher())
    yield
    watcher.cancel()
    await close_pool()


app = FastAPI(title="Verificador de pagos", lifespan=lifespan)


def verify_signature(raw: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(get_settings().meta_app_secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))  # tiempo constante


@app.get("/webhooks/whatsapp", response_class=PlainTextResponse)
async def verify_webhook(mode: str = Query("", alias="hub.mode"),
                         token: str = Query("", alias="hub.verify_token"),
                         challenge: str = Query("", alias="hub.challenge")):
    if mode == "subscribe" and hmac.compare_digest(token, get_settings().whatsapp_verify_token):
        return challenge
    raise HTTPException(403, "Token de verificación inválido")


async def _claim_event(event_id: str) -> bool:
    """Idempotencia: True solo la primera vez que se ve este evento."""
    async with pool().acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO webhook_events (event_id) VALUES ($1) "
            "ON CONFLICT DO NOTHING RETURNING event_id", event_id) is not None


@app.post("/webhooks/whatsapp")
async def receive_webhook(request: Request, background: BackgroundTasks):
    raw = await request.body()
    if not verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(401, "Firma inválida")  # antes de tocar cualquier dato
    payload = json.loads(raw)
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                if await _claim_event(msg["id"]):
                    background.add_task(handle_message, msg)
    return {"status": "ok"}  # responder rápido; el trabajo pesado va en segundo plano


class CorreoIn(BaseModel):
    msg_id: str
    subject: str = ""
    body: str
    received_at: datetime


@app.post("/internal/correos")
async def ingest_email(c: CorreoIn, x_ingest_token: str = Header("")):
    if not hmac.compare_digest(x_ingest_token, get_settings().ingest_token):
        raise HTTPException(401, "Token inválido")
    parsed = parse_davivienda_email(c.subject, c.body, c.received_at)
    if parsed is None:
        return {"status": "ignored"}
    status = await register_email(c.msg_id, parsed["valor"], parsed["fecha_hora"],
                                  parsed["referencia"])
    return {"status": status}


@app.get("/health")
async def health():
    return {"ok": True}
