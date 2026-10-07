from __future__ import annotations

from datetime import datetime
from decimal import Decimal


async def register_email(msg_id: str, valor: Decimal, fecha: datetime, referencia: str | None) -> str:
    return "stored"
