/**
 * Google Apps Script — corre en TU cuenta de Gmail (sin app de OAuth que verificar).
 * 1) En Gmail, crea un filtro que etiquete con "Davivienda" las notificaciones del banco.
 * 2) Script Properties: INGEST_TOKEN = el mismo valor del .env del servidor.
 * 3) Activador por tiempo: enviarCorreosNuevos() cada 1 minuto.
 */
const ENDPOINT = 'https://TU-DOMINIO/internal/correos';

function enviarCorreosNuevos() {
  const token = PropertiesService.getScriptProperties().getProperty('INGEST_TOKEN');
  const enviado = GmailApp.getUserLabelByName('Davivienda-enviado') ||
                  GmailApp.createLabel('Davivienda-enviado');
  const hilos = GmailApp.search('label:Davivienda -label:Davivienda-enviado newer_than:2d', 0, 50);
  hilos.forEach(function (hilo) {
    hilo.getMessages().forEach(function (m) {
      UrlFetchApp.fetch(ENDPOINT, {
        method: 'post',
        contentType: 'application/json',
        headers: { 'X-Ingest-Token': token },
        payload: JSON.stringify({
          msg_id: m.getId(),
          subject: m.getSubject(),
          body: m.getPlainBody(),
          received_at: m.getDate().toISOString(),
        }),
        muteHttpExceptions: true,
      });
    });
    hilo.addLabel(enviado); // el servidor igual deduplica por msg_id
  });
}
