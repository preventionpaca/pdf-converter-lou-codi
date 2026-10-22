const LC_TABLES = Object.freeze({licenses: 'Licences', installations: 'Installations', events: 'Statistiques'});
const LC_MAX_INSTALLATIONS = 3;
const LC_ALLOWED_MODULES = Object.freeze(['workshop','pdf_studio','pdf_to_office','documents_to_pdf','organize_pdf','decorate_pdf','document_studio','cutting_optimization','code_lab','website']);
const LC_ALLOWED_ACTIONS = Object.freeze(['open','convert','download','quiz']);

function doGet() {
  return LC_json_({ok: true, service: 'Lou Còdi collecte', version: 2});
}

function doPost(event) {
  try {
    const payload = JSON.parse((event.postData && event.postData.contents) || '{}');
    LC_authorizeClient_(payload.client_token);
    const handlers = {request_license: LC_requestLicense_, activate: LC_activate_, deactivate: LC_deactivate_, telemetry: LC_recordTelemetry_};
    const handler = handlers[String(payload.action || '')];
    if (!handler) throw new Error('Action inconnue.');
    return LC_json_(handler(payload));
  } catch (error) {
    return LC_json_({ok: false, error: String(error.message || error)});
  }
}

function LC_config_() {
  const properties = PropertiesService.getScriptProperties();
  const config = {
    apiUrl: String(properties.getProperty('LC_GRIST_API_URL') || 'https://docs.getgrist.com').replace(/\/$/, ''),
    docId: String(properties.getProperty('LC_GRIST_DOC_ID') || '').trim(),
    apiKey: String(properties.getProperty('LC_GRIST_API_KEY') || '').trim(),
  };
  if (!config.docId || !config.apiKey) throw new Error('Configuration Grist incomplète.');
  return config;
}

function LC_grist_(method, path, body) {
  const config = LC_config_();
  const options = {method: method, muteHttpExceptions: true, headers: {Authorization: 'Bearer ' + config.apiKey, Accept: 'application/json'}};
  if (body !== undefined) { options.contentType = 'application/json'; options.payload = JSON.stringify(body); }
  const response = UrlFetchApp.fetch(config.apiUrl + '/api/docs/' + encodeURIComponent(config.docId) + path, options);
  const status = response.getResponseCode();
  if (status < 200 || status >= 300) throw new Error('Stockage indisponible (' + status + ').');
  return JSON.parse(response.getContentText() || '{}');
}

function LC_records_(table) { return LC_grist_('get', '/tables/' + table + '/records').records || []; }
function LC_append_(table, fields) { return LC_grist_('post', '/tables/' + table + '/records', {records: [{fields: fields}]}); }
function LC_patch_(table, id, fields) { return LC_grist_('patch', '/tables/' + table + '/records', {records: [{id: Number(id), fields: fields}]}); }

function LC_ensureTables_() {
  const existing = LC_grist_('get', '/tables').tables || [];
  const ids = existing.map(function(table) { return String(table.id || ''); });
  const definitions = [
    {id: LC_TABLES.licenses, columns: [
      {id:'Cle', fields:{type:'Text'}}, {id:'Email', fields:{type:'Text'}},
      {id:'Statut', fields:{type:'Choice', widgetOptions:'{"choices":["active","disabled"]}'}},
      {id:'Cree_le', fields:{type:'DateTime:Europe/Paris'}}, {id:'Modifie_le', fields:{type:'DateTime:Europe/Paris'}}
    ]},
    {id: LC_TABLES.installations, columns: [
      {id:'Cle', fields:{type:'Text'}}, {id:'Installation', fields:{type:'Text'}},
      {id:'Systeme', fields:{type:'Text'}}, {id:'Version', fields:{type:'Text'}},
      {id:'Statut', fields:{type:'Choice', widgetOptions:'{"choices":["active","inactive"]}'}},
      {id:'Activee_le', fields:{type:'DateTime:Europe/Paris'}}, {id:'Derniere_activite', fields:{type:'DateTime:Europe/Paris'}}
    ]},
    {id: LC_TABLES.events, columns: [
      {id:'Recu_le', fields:{type:'DateTime:Europe/Paris'}}, {id:'Heure_evenement', fields:{type:'Text'}},
      {id:'Version', fields:{type:'Text'}}, {id:'Systeme', fields:{type:'Text'}},
      {id:'Module', fields:{type:'Text'}}, {id:'Action', fields:{type:'Text'}},
      {id:'Resultat', fields:{type:'Text'}}, {id:'Dimensions', fields:{type:'Text'}}
    ]}
  ];
  const created = [];
  definitions.forEach(function(definition) {
    if (ids.indexOf(definition.id) === -1) {
      LC_grist_('post', '/tables', {tables: [definition]});
      created.push(definition.id);
    }
  });
  return {created: created};
}

function LC_requestLicense_(payload) {
  const email = LC_normalizeEmail_(payload.email);
  if (!email) throw new Error('Adresse électronique invalide.');
  const lock = LockService.getScriptLock(); lock.waitLock(10000);
  try {
    const records = LC_records_(LC_TABLES.licenses);
    const record = records.find(function(item) { return LC_normalizeEmail_((item.fields || {}).Email) === email; });
    const now = Math.floor(Date.now() / 1000);
    const key = record ? String((record.fields || {}).Cle || '') : LC_createLicenseKey_();
    if (record) LC_patch_(LC_TABLES.licenses, record.id, {Modifie_le: now});
    else LC_append_(LC_TABLES.licenses, {Cle: key, Email: email, Statut: 'active', Cree_le: now, Modifie_le: now});
    MailApp.sendEmail({to: email, subject: 'Votre licence gratuite Lou Còdi Workshop', htmlBody: '<p>Voici votre licence gratuite Lou Còdi Workshop :</p><p style="font-size:20px;font-weight:bold">' + LC_escapeHtml_(key) + '</p><p>Elle permet d’activer jusqu’à trois ordinateurs.</p>'});
    return {ok: true, message: 'La licence a été envoyée par courrier électronique.'};
  } finally { lock.releaseLock(); }
}

function LC_activate_(payload) {
  const email = LC_normalizeEmail_(payload.email);
  const key = LC_normalizeKey_(payload.license_key);
  const installationId = LC_safe_(payload.installation_id, 96);
  if (!email || !key || !installationId) throw new Error('Informations d’activation incomplètes.');
  const license = LC_records_(LC_TABLES.licenses).find(function(item) { const fields = item.fields || {}; return String(fields.Cle || '') === key && LC_normalizeEmail_(fields.Email) === email; });
  if (!license || String((license.fields || {}).Statut || '') !== 'active') throw new Error('Licence inconnue ou désactivée.');
  const lock = LockService.getScriptLock(); lock.waitLock(10000);
  try {
    const records = LC_records_(LC_TABLES.installations);
    const existing = records.find(function(item) { const fields = item.fields || {}; return String(fields.Cle || '') === key && String(fields.Installation || '') === installationId; });
    const activeCount = records.filter(function(item) { const fields = item.fields || {}; return String(fields.Cle || '') === key && String(fields.Statut || '') === 'active'; }).length;
    const now = Math.floor(Date.now() / 1000);
    if (existing) {
      LC_patch_(LC_TABLES.installations, existing.id, {Systeme: LC_safe_(payload.os, 40), Version: LC_safe_(payload.app_version, 40), Statut: 'active', Derniere_activite: now});
      return {ok: true, activated: true, slots_used: Math.max(1, activeCount)};
    }
    if (activeCount >= LC_MAX_INSTALLATIONS) throw new Error('Cette licence est déjà active sur trois ordinateurs.');
    LC_append_(LC_TABLES.installations, {Cle: key, Installation: installationId, Systeme: LC_safe_(payload.os, 40), Version: LC_safe_(payload.app_version, 40), Statut: 'active', Activee_le: now, Derniere_activite: now});
    return {ok: true, activated: true, slots_used: activeCount + 1};
  } finally { lock.releaseLock(); }
}

function LC_deactivate_(payload) {
  const key = LC_normalizeKey_(payload.license_key);
  const installationId = LC_safe_(payload.installation_id, 96);
  const record = LC_records_(LC_TABLES.installations).find(function(item) { const fields = item.fields || {}; return String(fields.Cle || '') === key && String(fields.Installation || '') === installationId; });
  if (!record) throw new Error('Installation inconnue.');
  LC_patch_(LC_TABLES.installations, record.id, {Statut: 'inactive', Derniere_activite: Math.floor(Date.now() / 1000)});
  return {ok: true};
}

function LC_recordTelemetry_(payload) {
  const source = Array.isArray(payload.events) ? payload.events.slice(0, 100) : [];
  if (!source.length) return {ok: true, recorded: 0};
  const now = Math.floor(Date.now() / 1000);
  const records = source.map(function(event) {
    const moduleName = LC_safe_(event.module, 80); const action = LC_safe_(event.action, 80);
    if (LC_ALLOWED_MODULES.indexOf(moduleName) === -1 || LC_ALLOWED_ACTIONS.indexOf(action) === -1) throw new Error('Événement non autorisé.');
    const dimensions = event.dimensions && typeof event.dimensions === 'object' ? event.dimensions : {}; const clean = {};
    ['format','engine','language'].forEach(function(name) { if (dimensions[name] != null) clean[name] = LC_safe_(dimensions[name], 80); });
    return {fields: {Recu_le: now, Heure_evenement: LC_safe_(event.time, 40), Version: LC_safe_(event.app_version, 40), Systeme: LC_safe_(event.os, 40), Module: moduleName, Action: action, Resultat: LC_safe_(event.result, 40), Dimensions: JSON.stringify(clean).slice(0, 500)}};
  });
  LC_grist_('post', '/tables/' + LC_TABLES.events + '/records', {records: records});
  return {ok: true, recorded: records.length};
}

function LC_authorizeClient_(token) { const expected = String(PropertiesService.getScriptProperties().getProperty('LC_CLIENT_TOKEN') || ''); if (!expected || String(token || '') !== expected) throw new Error('Client non autorisé.'); }
function LC_normalizeEmail_(value) { const email = String(value || '').trim().toLowerCase(); return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) ? email : ''; }
function LC_normalizeKey_(value) { return String(value || '').trim().toUpperCase().replace(/[^A-Z0-9-]/g, '').slice(0, 40); }
function LC_safe_(value, limit) { return String(value || '').replace(/[\r\n\t]/g, ' ').slice(0, limit); }
function LC_createLicenseKey_() { const raw = Utilities.getUuid().replace(/-/g, '').toUpperCase(); return 'LC-' + raw.slice(0, 6) + '-' + raw.slice(6, 12) + '-' + raw.slice(12, 18); }
function LC_escapeHtml_(value) { return String(value).replace(/[&<>"']/g, function(char) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]; }); }
function LC_json_(value) { return ContentService.createTextOutput(JSON.stringify(value)).setMimeType(ContentService.MimeType.JSON); }
