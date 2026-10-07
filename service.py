"""Lógica central: recibo (WhatsApp) ⇄ correo de Davivienda."""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from app import audit
from app.config import get_settings
from app.db import pool
from app.extractor import extract_receipt
from app.utils import (BOGOTA, fmt_cop, norm_bank, norm_ref, parse_cop,
                       parse_dt, pick_candidate, sha256_hex)
from app.whatsapp import notify, notify_admins

log = logging.getLogger(__name__)

_MATCH_RECEIPT_SQL = """
SELECT id, referencia FROM correos_banco
WHERE tenant_id=$1 AND usado_por IS NULL AND valor=$2
  AND fecha_hora BETWEEN $3::timestamptz - make_interval(mins => $4)
                     AND $3::timestamptz + make_interval(mins => $4)
FOR UPDATE SKIP LOCKED"""

_MATCH_EMAIL_SQL = """
SELECT id, referencia, remitente_telefono, pagador FROM pagos
WHERE tenant_id=$1 AND estado='pendiente' AND valor=$2
  AND fecha_hora BETWEEN $3::timestamptz - make_interval(mins => $4)
                     AND $3::timestamptz + make_interval(mins => $4)
FOR UPDATE SKIP LOCKED"""


async def _finalize(conn, pago_id, correo_id, metodo: str) -> None:
    # usado_por es UNIQUE: la BD impide que un correo confirme dos pagos.
    await conn.execute("UPDATE correos_banco SET usado_por=$1 WHERE id=$2", pago_id, correo_id)
    await conn.execute(
        """UPDATE pagos SET estado='verificado', metodo_match=$2, verificado_en=now(),
           motivo=NULL WHERE id=$1""", pago_id, metodo)
    await audit.record(conn, entity_id=str(pago_id), action="VERIFY", actor="system",
                       after={"correo_id": str(correo_id), "metodo": metodo}, channel="system")


async def process_receipt(sender: str, wa_message_id: str, image: bytes, mime: str) -> str:
    s = get_settings()
    digest = sha256_hex(image)

    async with pool().acquire() as conn:
        dup = await conn.fetchrow(
            "SELECT id FROM pagos WHERE tenant_id=$1 AND hash_imagen=$2", s.tenant_id, digest)
        if dup:
            await audit.record(conn, entity_id=str(dup["id"]), action="DUPLICATE_ATTEMPT",
                               actor=sender, after={"motivo": "misma imagen"})
            await notify_admins(f"⚠️ {sender} reenvió una imagen ya registrada.")
            return "⚠️ Esa imagen ya fue enviada antes. No se registró de nuevo."

    data = await extract_receipt(image, mime)  # llamada lenta: fuera de la conexión
    valor = parse_cop(data.get("valor")) if data else None
    if not data or not data.get("es_recibo") or valor is None:
        return ("No pude leer un recibo válido en esa imagen. "
                "Envía una foto clara y completa del comprobante.")

    fecha = parse_dt(data.get("fecha_hora"))
    banco = norm_bank(data.get("banco_origen"))
    ref = norm_ref(data.get("referencia"))
    destino = (data.get("banco_destino") or "").upper()
    pagador = data.get("pagador")

    estado, motivo = "pendiente", None
    if fecha is None:
        fecha, estado, motivo = datetime.now(BOGOTA), "sospechoso", "sin fecha legible"
    elif destino and "DAVIVIENDA" not in destino:
        estado, motivo = "sospechoso", f"el destino del recibo no es Davivienda ({destino})"
    elif ref is None:
        motivo = "sin referencia: el anti-duplicado depende del correo"

    outcome = "ninguno"
    async with pool().acquire() as conn:
        async with conn.transaction():
            pago_id = await conn.fetchval(
                """INSERT INTO pagos (tenant_id, pagador, fecha_hora, valor, banco_origen,
                   referencia, hash_imagen, remitente_telefono, wa_message_id, estado, motivo)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                   ON CONFLICT DO NOTHING RETURNING id""",
                s.tenant_id, pagador, fecha, valor, banco, ref, digest, sender,
                wa_message_id, estado, motivo)
            if pago_id is None:
                existing = await conn.fetchval(
                    """SELECT id FROM pagos WHERE tenant_id=$1 AND referencia=$2
                       AND banco_origen IS NOT DISTINCT FROM $3""", s.tenant_id, ref, banco)
                await audit.record(conn, entity_id=str(existing), action="DUPLICATE_ATTEMPT",
                                   actor=sender, after={"motivo": "misma referencia", "referencia": ref})
                outcome = "duplicado"
            else:
                await audit.record(conn, entity_id=str(pago_id), action="CREATE", actor=sender,
                                   after={"valor": valor, "banco_origen": banco,
                                          "referencia": ref, "estado": estado})
                if estado == "sospechoso":
                    await audit.record(conn, entity_id=str(pago_id), action="FLAGGED",
                                       actor="system", after={"motivo": motivo}, channel="system")
                    outcome = "sospechoso"
                else:
                    cands = [dict(c) for c in await conn.fetch(
                        _MATCH_RECEIPT_SQL, s.tenant_id, valor, fecha, s.match_window_minutes)]
                    chosen, how = pick_candidate(cands, ref)
                    if chosen:
                        await _finalize(conn, pago_id, chosen["id"], how)
                        outcome = "verificado"
                    elif how == "ambiguo":
                        await conn.execute(
                            "UPDATE pagos SET motivo='varios correos posibles: revisión manual' WHERE id=$1",
                            pago_id)
                        outcome = "ambiguo"

    resumen = f"{fmt_cop(valor)}" + (f" de {pagador}" if pagador else "")
    if outcome == "verificado":
        return f"✅ Pago verificado: {resumen}. Confirmado con la notificación de Davivienda."
    if outcome == "duplicado":
        await notify_admins(f"⚠️ Recibo duplicado (ref {ref}) enviado por {sender}.")
        return "⚠️ Ese número de recibo ya fue registrado. No se registró de nuevo."
    if outcome == "sospechoso":
        await notify_admins(f"⚠️ Recibo sospechoso de {sender}: {resumen}. Motivo: {motivo}.")
        return f"⚠️ Recibido, pero requiere revisión manual ({motivo})."
    if outcome == "ambiguo":
        await notify_admins(f"🔎 Varios pagos/correos posibles para {resumen} ({sender}). Revisión manual.")
        return "🕐 Recibido. Hay varios pagos similares; un administrador lo revisará."
    return f"🕐 Recibido: {resumen}. Esperando la notificación de Davivienda; te aviso al confirmarse."


async def register_email(msg_id: str, valor: Decimal, fecha: datetime, referencia: str | None) -> str:
    s = get_settings()
    to_notify: tuple[str, str] | None = None
    admin_msg: str | None = None
    status = "stored"
    async with pool().acquire() as conn:
        async with conn.transaction():
            correo_id = await conn.fetchval(
                """INSERT INTO correos_banco (tenant_id, msg_id, valor, fecha_hora, referencia)
                   VALUES ($1,$2,$3,$4,$5) ON CONFLICT (msg_id) DO NOTHING RETURNING id""",
                s.tenant_id, msg_id, valor, fecha, referencia)
            if correo_id is None:
                return "duplicate"
            await audit.record(conn, entity_id=str(correo_id), action="EMAIL_RECEIVED",
                               actor="gmail", after={"valor": valor, "referencia": referencia},
                               channel="email")
            cands = [dict(c) for c in await conn.fetch(
                _MATCH_EMAIL_SQL, s.tenant_id, valor, fecha, s.match_window_minutes)]
            chosen, how = pick_candidate(cands, referencia)
            if chosen:
                await _finalize(conn, chosen["id"], correo_id, how)
                status = "matched"
                to_notify = (chosen["remitente_telefono"],
                             f"✅ Pago verificado: {fmt_cop(valor)}. Confirmado con Davivienda.")
            elif how == "ambiguo":
                status = "ambiguous"
                admin_msg = f"🔎 Llegó un abono de {fmt_cop(valor)} y hay varios recibos pendientes iguales. Revisión manual."
    if to_notify:
        await notify(*to_notify)
    if admin_msg:
        await notify_admins(admin_msg)
    return status
