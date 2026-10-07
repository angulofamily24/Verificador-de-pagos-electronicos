# Verificador de pagos — WhatsApp + Davivienda

Foto de recibo en WhatsApp → extracción con Claude → anti-duplicado → cruce con el
correo de abono de Davivienda → respuesta automática y registro auditable.

## Flujo
1. El cliente envía la foto. Se firma-verifica el webhook (X-Hub-Signature-256) y se
   deduplica el evento por ID de mensaje.
2. Claude extrae pagador, fecha/hora, valor, banco y referencia. **La imagen no se guarda, solo su hash.**
3. Anti-duplicado: hash de imagen + `UNIQUE(banco_origen, referencia)`.
4. Cruce con `correos_banco` por monto + ventana de tiempo (referencia solo desempata).
   Un correo confirma **un solo** pago (`usado_por UNIQUE`). Si hay varios candidatos
   iguales NO se adivina: queda para revisión manual.
5. Sin correo tras 15 min → alerta a administradores. Admin escribe `pendientes` para ver la lista.

Los intentos duplicados no crean fila: quedan en `audit_log` (append-only) y alertan al admin.

## Arranque
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # completa los valores
psql "$DATABASE_URL" -f schema.sql
pytest                          # pruebas de utilidades
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Webhook en Meta: `https://TU-DOMINIO/webhooks/whatsapp` (suscribe el campo `messages`).
Gmail: pega `scripts/gmail_forwarder.gs` en Apps Script (instrucciones en el archivo).

## Pendiente antes de producción
- **Parser de Davivienda (`app/email_parser.py`)**: es una plantilla genérica; ajústala con correos reales.
- Probar con recibos reales de Nequi, Bancolombia, PSE, etc.
- Si Davivienda incluye el nombre del pagador en el correo, añadirlo como desempate.
- Consentimiento y política de tratamiento de datos (Ley 1581 de 2012) en el primer mensaje del bot.
- Rol de BD sin UPDATE/DELETE sobre `audit_log` (ver comentario al final de `schema.sql`).
