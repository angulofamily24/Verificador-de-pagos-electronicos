CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Pagos declarados por recibo (foto de WhatsApp). La imagen NO se guarda: solo su hash.
CREATE TABLE pagos (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            UUID NOT NULL,
  pagador              TEXT,
  fecha_hora           TIMESTAMPTZ NOT NULL,
  valor                NUMERIC(18,2) NOT NULL CHECK (valor > 0),
  moneda               TEXT NOT NULL DEFAULT 'COP',
  banco_origen         TEXT,
  referencia           TEXT,
  hash_imagen          TEXT NOT NULL,
  remitente_telefono   TEXT NOT NULL,
  wa_message_id        TEXT NOT NULL UNIQUE,
  estado               TEXT NOT NULL DEFAULT 'pendiente'
                       CHECK (estado IN ('pendiente','verificado','sospechoso')),
  motivo               TEXT,
  metodo_match         TEXT,
  notificado_pendiente BOOLEAN NOT NULL DEFAULT false,
  creado_en            TIMESTAMPTZ NOT NULL DEFAULT now(),
  verificado_en        TIMESTAMPTZ,
  UNIQUE (tenant_id, hash_imagen),                   -- misma foto reenviada
  UNIQUE (tenant_id, banco_origen, referencia)       -- mismo número de recibo
);
CREATE INDEX idx_pagos_pendientes ON pagos (tenant_id, estado, valor, fecha_hora);

-- Notificaciones de abono recibidas de Davivienda (fuente de verdad).
CREATE TABLE correos_banco (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID NOT NULL,
  msg_id      TEXT NOT NULL UNIQUE,
  valor       NUMERIC(18,2) NOT NULL,
  fecha_hora  TIMESTAMPTZ NOT NULL,
  referencia  TEXT,
  usado_por   UUID UNIQUE REFERENCES pagos(id),  -- un correo confirma UN solo pago (lo garantiza la BD)
  recibido_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_correos_libres ON correos_banco (tenant_id, valor, fecha_hora)
  WHERE usado_por IS NULL;

-- Idempotencia de webhooks (Meta reintenta entregas).
CREATE TABLE webhook_events (
  event_id    TEXT PRIMARY KEY,
  recibido_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Auditoría append-only a nivel de base de datos.
CREATE TABLE audit_log (
  id             BIGSERIAL PRIMARY KEY,
  tenant_id      UUID NOT NULL,
  entity_name    TEXT NOT NULL,
  entity_id      TEXT NOT NULL,
  action         TEXT NOT NULL CHECK (action IN
                 ('CREATE','VERIFY','DUPLICATE_ATTEMPT','FLAGGED','EMAIL_RECEIVED')),
  actor          TEXT NOT NULL,
  source_channel TEXT NOT NULL DEFAULT 'whatsapp',
  before_value   JSONB,
  after_value    JSONB,
  occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_entity ON audit_log (tenant_id, entity_name, entity_id);

CREATE OR REPLACE FUNCTION prevent_audit_log_mutation() RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION 'audit_log es append-only: % no permitido', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_no_update BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation();
CREATE TRIGGER trg_audit_no_truncate BEFORE TRUNCATE ON audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION prevent_audit_log_mutation();

-- En producción conecta la app con un rol sin UPDATE/DELETE sobre audit_log:
--   REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM app_user;
--   GRANT INSERT, SELECT ON audit_log TO app_user;
