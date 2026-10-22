const SHEETS = Object.freeze({
  licenses: 'Licences',
  installations: 'Installations',
  events: 'Statistiques',
});
const MAX_INSTALLATIONS = 3;

/** Run once after setting ADMIN_EMAIL and ADMIN_PASSWORD in Script Properties. */
function setupService() {
  const properties = PropertiesService.getScriptProperties();
  requireProperty_(properties, 'ADMIN_EMAIL');
  requireProperty_(properties, 'ADMIN_PASSWORD');
  let spreadsheetId = properties.getProperty('SPREADSHEET_ID');
  if (!spreadsheetId) {
    const spreadsheet = SpreadsheetApp.create('Lou Còdi — licences et statistiques');
    spreadsheetId = spreadsheet.getId();
    properties.setProperty('SPREADSHEET_ID', spreadsheetId);
    initializeSheets_(spreadsheet);
  }
  return SpreadsheetApp.openById(spreadsheetId).getUrl();
}

function doGet(event) {
  if ((event.parameter.view || '') !== 'admin') {
    return json_({ok: true, service: 'Lou Còdi licences et statistiques'});
  }
  return HtmlService.createTemplateFromFile('Dashboard')
    .evaluate()
    .setTitle('Lou Còdi — licences et statistiques')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.DEFAULT);
}

function doPost(event) {
  try {
    const payload = JSON.parse((event.postData && event.postData.contents) || '{}');
    const action = String(payload.action || '');
    const handlers = {
      request_license: requestLicense_,
      activate: activate_,
      deactivate: deactivate_,
      telemetry: recordTelemetry_,
    };
    if (!handlers[action]) throw new Error('Action inconnue.');
    return json_(handlers[action](payload));
  } catch (error) {
    return json_({ok: false, error: String(error.message || error)});
  }
}

function requestLicense_(payload) {
  const email = normalizeEmail_(payload.email);
  if (!email) throw new Error('Adresse électronique invalide.');
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const sheet = sheet_(SHEETS.licenses);
    const rows = values_(sheet);
    let row = rows.findIndex((item, index) => index > 0 && normalizeEmail_(item[1]) === email);
    let key;
    if (row > 0) {
      key = String(rows[row][0]);
      sheet.getRange(row + 1, 5).setValue(new Date());
    } else {
      key = createLicenseKey_();
      sheet.appendRow([key, email, 'active', new Date(), new Date()]);
    }
    MailApp.sendEmail({
      to: email,
      subject: 'Votre licence gratuite Lou Còdi Workshop',
      htmlBody: '<p>Voici votre licence gratuite Lou Còdi Workshop :</p>' +
        '<p style="font-size:20px;font-weight:bold">' + escapeHtml_(key) + '</p>' +
        '<p>Elle permet d’activer jusqu’à trois ordinateurs.</p>',
    });
    return {ok: true, message: 'La licence a été envoyée par courrier électronique.'};
  } finally {
    lock.releaseLock();
  }
}

function activate_(payload) {
  const email = normalizeEmail_(payload.email);
  const key = normalizeKey_(payload.license_key);
  const installationId = safe_(payload.installation_id, 96);
  if (!email || !key || !installationId) throw new Error('Informations d’activation incomplètes.');
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const license = findLicense_(email, key);
    if (!license || license.status !== 'active') throw new Error('Licence inconnue ou désactivée.');
    const sheet = sheet_(SHEETS.installations);
    const rows = values_(sheet);
    const existing = rows.findIndex((row, index) => index > 0 && String(row[0]) === key && String(row[1]) === installationId);
    if (existing > 0) {
      sheet.getRange(existing + 1, 7).setValue(new Date());
      return {ok: true, activated: true, slots_used: countActive_(rows, key)};
    }
    if (countActive_(rows, key) >= MAX_INSTALLATIONS) {
      throw new Error('Cette licence est déjà active sur trois ordinateurs.');
    }
    sheet.appendRow([
      key, installationId, safe_(payload.os, 40), safe_(payload.app_version, 40),
      'active', new Date(), new Date(),
    ]);
    return {ok: true, activated: true, slots_used: countActive_(values_(sheet), key)};
  } finally {
    lock.releaseLock();
  }
}

function deactivate_(payload) {
  const key = normalizeKey_(payload.license_key);
  const installationId = safe_(payload.installation_id, 96);
  const sheet = sheet_(SHEETS.installations);
  const rows = values_(sheet);
  const index = rows.findIndex((row, i) => i > 0 && String(row[0]) === key && String(row[1]) === installationId);
  if (index < 1) throw new Error('Installation inconnue.');
  sheet.getRange(index + 1, 5).setValue('inactive');
  sheet.getRange(index + 1, 7).setValue(new Date());
  return {ok: true};
}

function recordTelemetry_(payload) {
  const events = Array.isArray(payload.events) ? payload.events.slice(0, 100) : [];
  if (!events.length) return {ok: true, recorded: 0};
  const rows = events.map(event => [
    new Date(), safe_(event.time, 40), safe_(event.app_version, 40), safe_(event.os, 40),
    safe_(event.module, 80), safe_(event.action, 80), safe_(event.result, 40),
    JSON.stringify(event.dimensions || {}).slice(0, 1000),
  ]);
  const sheet = sheet_(SHEETS.events);
  sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
  return {ok: true, recorded: rows.length};
}

function adminSnapshot(password) {
  authorizeAdmin_(password);
  const licenses = values_(sheet_(SHEETS.licenses)).slice(1);
  const installations = values_(sheet_(SHEETS.installations)).slice(1);
  const events = values_(sheet_(SHEETS.events)).slice(1);
  const activeInstallations = installations.filter(row => row[4] === 'active');
  const modules = {};
  events.forEach(row => { modules[row[4]] = (modules[row[4]] || 0) + 1; });
  return {
    admin: PropertiesService.getScriptProperties().getProperty('ADMIN_EMAIL'),
    licenses: licenses.length,
    active_installations: activeInstallations.length,
    events: events.length,
    modules: modules,
    recent_licenses: licenses.slice(-25).reverse().map(row => ({
      key: maskKey_(row[0]), email: row[1], status: row[2], created: String(row[3]),
    })),
  };
}

function setLicenseStatus(password, licenseKey, status) {
  authorizeAdmin_(password);
  if (!['active', 'disabled'].includes(status)) throw new Error('Statut invalide.');
  const sheet = sheet_(SHEETS.licenses);
  const rows = values_(sheet);
  const index = rows.findIndex((row, i) => i > 0 && String(row[0]) === licenseKey);
  if (index < 1) throw new Error('Licence inconnue.');
  sheet.getRange(index + 1, 3).setValue(status);
  return {ok: true};
}

function initializeSheets_(spreadsheet) {
  const definitions = [
    [SHEETS.licenses, ['Clé', 'E-mail', 'Statut', 'Créée le', 'Dernière demande']],
    [SHEETS.installations, ['Clé', 'Installation', 'Système', 'Version', 'Statut', 'Activée le', 'Dernière activité']],
    [SHEETS.events, ['Reçu le', 'Heure arrondie', 'Version', 'Système', 'Module', 'Action', 'Résultat', 'Dimensions']],
  ];
  definitions.forEach((definition, index) => {
    const sheet = index === 0 ? spreadsheet.getSheets()[0] : spreadsheet.insertSheet();
    sheet.setName(definition[0]);
    sheet.getRange(1, 1, 1, definition[1].length).setValues([definition[1]]).setFontWeight('bold');
    sheet.setFrozenRows(1);
  });
}

function findLicense_(email, key) {
  const row = values_(sheet_(SHEETS.licenses)).find((item, index) =>
    index > 0 && String(item[0]) === key && normalizeEmail_(item[1]) === email
  );
  return row ? {key: row[0], email: row[1], status: row[2]} : null;
}

function sheet_(name) {
  const id = requireProperty_(PropertiesService.getScriptProperties(), 'SPREADSHEET_ID');
  const sheet = SpreadsheetApp.openById(id).getSheetByName(name);
  if (!sheet) throw new Error('Feuille absente : ' + name);
  return sheet;
}

function values_(sheet) { return sheet.getDataRange().getValues(); }
function countActive_(rows, key) { return rows.filter((row, i) => i > 0 && String(row[0]) === key && row[4] === 'active').length; }
function normalizeEmail_(value) { const email = String(value || '').trim().toLowerCase(); return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) ? email : ''; }
function normalizeKey_(value) { return String(value || '').trim().toUpperCase().replace(/[^A-Z0-9-]/g, '').slice(0, 40); }
function safe_(value, limit) { return String(value || '').replace(/[\r\n\t]/g, ' ').slice(0, limit); }
function createLicenseKey_() { const raw = Utilities.getUuid().replace(/-/g, '').toUpperCase(); return 'LC-' + raw.slice(0, 6) + '-' + raw.slice(6, 12) + '-' + raw.slice(12, 18); }
function maskKey_(key) { const value = String(key); return value.slice(0, 6) + '••••••' + value.slice(-4); }
function escapeHtml_(value) { return String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])); }
function authorizeAdmin_(password) { if (String(password || '') !== requireProperty_(PropertiesService.getScriptProperties(), 'ADMIN_PASSWORD')) throw new Error('Accès refusé.'); }
function requireProperty_(properties, name) { const value = properties.getProperty(name); if (!value) throw new Error('Propriété manquante : ' + name); return value; }
function json_(value) { return ContentService.createTextOutput(JSON.stringify(value)).setMimeType(ContentService.MimeType.JSON); }
