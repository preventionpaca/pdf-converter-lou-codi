const LC_SPACE_SUFFIX = '.loucodi-espace';
const LC_BRAND = '#183F70';

function LC_homepage_() {
  return CardService.newCardBuilder()
    .setHeader(CardService.newCardHeader().setTitle('Lou Còdi Espace'))
    .addSection(CardService.newCardSection()
      .addWidget(CardService.newTextParagraph().setText(
        'Ouvrez un courriel, puis choisissez Lou Còdi Espace dans la barre latérale pour le relier.'
      )))
    .build();
}

function LC_openMessage(event) {
  const message = LC_currentMessage_(event);
  const spaces = LC_spaceFiles_();
  const section = CardService.newCardSection()
    .addWidget(CardService.newDecoratedText().setTopLabel('Objet').setText(LC_escape_(message.getSubject() || 'Sans objet')))
    .addWidget(CardService.newDecoratedText().setTopLabel('Expéditeur').setText(LC_escape_(message.getFrom() || 'Non indiqué')))
    .addWidget(CardService.newDecoratedText().setTopLabel('Destinataires').setText(LC_escape_(message.getTo() || 'Non indiqués')))
    .addWidget(CardService.newDecoratedText().setTopLabel('Date').setText(LC_escape_(LC_date_(message.getDate()))));

  if (!spaces.length) {
    section.addWidget(CardService.newTextParagraph().setText(
      'Aucun espace synchronisé n’a été trouvé dans ce Google Drive. Dans Lou Còdi Espace, liez d’abord un dossier Drive et enregistrez l’espace.'
    ));
  } else {
    const selector = CardService.newSelectionInput()
      .setType(CardService.SelectionInputType.DROPDOWN)
      .setTitle('Ajouter dans l’espace')
      .setFieldName('spaceFileId');
    spaces.forEach(function(space, index) {
      selector.addItem(space.title, space.fileId, index === 0);
    });
    section.addWidget(selector);
    section.addWidget(CardService.newButtonSet().addButton(
      CardService.newTextButton()
        .setText('Relier ce courriel')
        .setTextButtonStyle(CardService.TextButtonStyle.FILLED)
        .setBackgroundColor(LC_BRAND)
        .setOnClickAction(CardService.newAction().setFunctionName('LC_addCurrentMessage'))
    ));
  }

  return CardService.newCardBuilder()
    .setHeader(CardService.newCardHeader().setTitle('Relier à Lou Còdi Espace'))
    .addSection(section)
    .build();
}

function LC_addCurrentMessage(event) {
  const fileId = LC_formValue_(event, 'spaceFileId');
  if (!fileId) throw new Error('Choisissez un espace Lou Còdi.');
  const message = LC_currentMessage_(event);
  const file = DriveApp.getFileById(fileId);
  const payload = JSON.parse(file.getBlob().getDataAsString('UTF-8'));
  if (!payload || !Array.isArray(payload.resources)) {
    throw new Error('Le fichier sélectionné n’est pas un espace Lou Còdi valide.');
  }
  const permalink = message.getThread().getPermalink();
  const alreadyLinked = payload.resources.some(function(resource) {
    return resource && resource.target === permalink;
  });
  if (!alreadyLinked) {
    payload.resources.push({
      identifier: Utilities.getUuid().replace(/-/g, ''),
      title: message.getSubject() || 'Courriel sans objet',
      kind: 'gmail_message',
      target: permalink,
      tags: [],
      account_email: Session.getActiveUser().getEmail() || '',
      details: 'De : ' + (message.getFrom() || '—') + ' • À : ' + (message.getTo() || '—'),
      created_at: new Date().toISOString(),
      gmail_message_id: message.getId(),
      gmail_thread_id: message.getThread().getId(),
      message_date: message.getDate().toISOString()
    });
    file.setContent(JSON.stringify(payload, null, 2));
  }
  return CardService.newActionResponseBuilder()
    .setNotification(CardService.newNotification().setText(
      alreadyLinked ? 'Ce courriel est déjà relié à cet espace.' : 'Courriel relié à « ' + payload.space_title + ' ».'
    ))
    .build();
}

function LC_currentMessage_(event) {
  if (!event || !event.gmail || !event.gmail.messageId || !event.gmail.accessToken) {
    throw new Error('Ouvrez d’abord un courriel dans Gmail.');
  }
  GmailApp.setCurrentMessageAccessToken(event.gmail.accessToken);
  return GmailApp.getMessageById(event.gmail.messageId);
}

function LC_spaceFiles_() {
  const files = DriveApp.searchFiles("trashed = false and title contains '" + LC_SPACE_SUFFIX + "'");
  const spaces = [];
  while (files.hasNext()) {
    const file = files.next();
    if (!file.getName().endsWith(LC_SPACE_SUFFIX)) continue;
    try {
      const payload = JSON.parse(file.getBlob().getDataAsString('UTF-8'));
      if (payload && payload.space_title && Array.isArray(payload.resources)) {
        spaces.push({fileId: file.getId(), title: String(payload.space_title)});
      }
    } catch (error) {
      console.warn('Index Lou Còdi ignoré : ' + file.getName() + ' — ' + error);
    }
  }
  spaces.sort(function(a, b) { return a.title.localeCompare(b.title, 'fr'); });
  return spaces;
}

function LC_formValue_(event, name) {
  const input = event && event.commonEventObject && event.commonEventObject.formInputs
    ? event.commonEventObject.formInputs[name]
    : null;
  const values = input && input.stringInputs ? input.stringInputs.value : [];
  return values && values.length ? String(values[0]) : '';
}

function LC_date_(value) {
  return Utilities.formatDate(value, Session.getScriptTimeZone(), 'dd/MM/yyyy HH:mm');
}

function LC_escape_(value) {
  return String(value).replace(/[&<>]/g, function(character) {
    return {'&': '&amp;', '<': '&lt;', '>': '&gt;'}[character];
  });
}
