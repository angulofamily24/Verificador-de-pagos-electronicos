from datetime import datetime, timezone

from email_parser import parse_davivienda_email


def test_parse_real_davivienda_email():
    body = """
    Fecha: 2026/09/28
    Hora: 16:13:33
    Valor Transacción: $3,697,200
    Clase de Movimiento: Abono Transferencia a su llave
    Lugar de Transacción: Llaves Bre-B
    Atentamente, BANCO DAVIVIENDA S.A.
    """

    result = parse_davivienda_email(
        "Movimiento de su Cta de Ahorros terminada en ****6008",
        body,
        datetime(2026, 9, 28, 16, 13, 33, tzinfo=timezone.utc),
    )

    assert result is not None
    assert result["valor"] == 3697200
    assert result["fecha_hora"] == datetime(2026, 9, 28, 16, 13, 33, tzinfo=timezone.utc)
    assert result["referencia"] == "6008"


def test_parse_non_abono_email_is_ignored():
    body = """
    Fecha: 2026/09/28
    Valor: $100,000
    Clase de Movimiento: Retiro en cajero
    """

    assert parse_davivienda_email("Notificación de retiro", body, datetime.now(timezone.utc)) is None
