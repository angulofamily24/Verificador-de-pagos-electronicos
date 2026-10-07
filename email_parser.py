"""Parser para correos de abono de Davivienda.

Este parser está diseñado para reconocer los formatos reales observados en el
correo de Davivienda, incluyendo:
- valor con separadores de miles
- fecha y hora en formato ISO/ddd
- cuentas terminadas ocultas con ****XXXX
- ausencia de referencia explícita
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

BOGOTA = timezone(timedelta(hours=-5))

ES_ABONO = re.compile(
    r"(abono|transferencia(?:\s+a\s+su\s+llave)?|recibiste|ingreso|cr\.?dito)",
    re.I,
)
RE_VALOR = re.compile(
    r"(?:valor\s*(?:de\s*)?(?:transacci[oó]n)?|monto|abono|ingreso)\s*[:\-]?\s*[$]?\s*([\d\s.,]+)",
    re.I,
)
RE_FECHA = re.compile(
    r"(?:fecha)\s*[:\-]?\s*(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})",
    re.I,
)
RE_HORA = re.compile(r"(?:hora)\s*[:\-]?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?", re.I)
RE_REF = re.compile(
    r"(?:referencia|comprobante|transacci[oó]n|llave)\D{0,20}([A-Za-z0-9]{4,})",
    re.I,
)
RE_CUENTA_TERMINADA = re.compile(
    r"(?:cta|cuenta)(?:\s+de\s+ahorros)?(?:\s+terminada)?(?:\s+\(o\))?\s*(?:en|#)?\s*\*{0,4}(\d{4,})",
    re.I,
)


def _parse_money(raw: str) -> Decimal | None:
    cleaned = raw.strip().replace(" ", "")
    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) > 1 and len(parts[-1]) in (2, 3):
            cleaned = "".join(parts[:-1]) + "." + parts[-1] if len(parts[-1]) == 2 else "".join(parts)
        else:
            cleaned = "".join(parts)
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 1 and len(parts[-1]) == 3:
            cleaned = "".join(parts)

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _normalize_reference(value: str | None) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"[^A-Za-z0-9]", "", value)
    return digits or None


def parse_davivienda_email(subject: str, body: str, received_at: datetime) -> dict | None:
    text = f"{subject}\n{body}"
    if not ES_ABONO.search(text):
        return None

    valor_match = RE_VALOR.search(text)
    if not valor_match:
        return None

    valor = _parse_money(valor_match.group(1))
    if valor is None:
        return None

    tzinfo = received_at.tzinfo or BOGOTA
    fecha = received_at

    date_match = RE_FECHA.search(text)
    time_match = RE_HORA.search(text)
    if date_match:
        year, month, day = map(int, date_match.groups())
        hour = int(time_match.group(1)) if time_match else 0
        minute = int(time_match.group(2)) if time_match else 0
        second = int(time_match.group(3)) if time_match and time_match.group(3) else 0
        try:
            fecha = datetime(year, month, day, hour, minute, second, tzinfo=tzinfo)
        except ValueError:
            fecha = received_at

    referencia = None
    for pattern in (RE_CUENTA_TERMINADA, RE_REF):
        match = pattern.search(text)
        if match:
            referencia = _normalize_reference(match.group(1))
            if referencia:
                break

    return {
        "valor": int(valor) if valor == valor.to_integral_value() else valor,
        "fecha_hora": fecha,
        "referencia": referencia,
    }
