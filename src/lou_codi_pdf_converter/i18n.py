from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import arabic_reshaper
from bidi.algorithm import get_display

LANGUAGES = {
    "fr": "Français",
    "en": "English",
    "de": "Deutsch",
    "es": "Español",
    "it": "Italiano",
    "zh": "中文",
    "tr": "Türkçe",
    "ar": get_display(arabic_reshaper.reshape("العربية")),
}

_language = "fr"

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "Que souhaitez-vous faire ?": "What would you like to do?",
        "PDF vers Office": "PDF to Office",
        "Documents vers PDF": "Documents to PDF",
        "Organiser les PDF": "Organize PDFs",
        "Habillage PDF": "Customize PDF",
        "Conversion PDF vers Word et extraction de tableaux Excel.": "Convert PDF to Word and extract Excel tables.",
        "Documents bureautiques et images, individuellement ou par lots.": "Office documents and images, individually or in batches.",
        "Fusion, extraction, réorganisation et rotation des pages.": "Merge, extract, reorder and rotate pages.",
        "Filigranes, en-têtes et pieds de page avec aperçu.": "Watermarks, headers and footers with preview.",
        "Ouvrir le module": "Open module", "Soutenir Lou Còdi ♥": "Support Lou Còdi ♥",
        "TRAITEMENT LOCAL": "LOCAL PROCESSING", "Aucun document transmis sur Internet": "No document sent over the Internet",
        "Destination": "Destination", "Parcourir…": "Browse…", "Choisir…": "Choose…", "Annuler": "Cancel",
        "Fermer": "Close", "Supprimer": "Delete", "Retirer": "Remove", "Tout effacer": "Clear all",
        "Tout vider": "Clear all", "Prêt.": "Ready.", "Ouvrir le résultat": "Open result",
        "Ouvrir les résultats": "Open results", "Valider et exporter": "Apply and export",
        "Actualiser l’aperçu": "Refresh preview", "Ajouter des PDF…": "Add PDFs…",
        "Ajouter des documents…": "Add documents…", "Pages :": "Pages:", "Toutes": "All",
        "Première page": "First page", "Dernière page": "Last page", "Pages paires": "Even pages",
        "Pages impaires": "Odd pages", "Personnalisé…": "Custom…", "Couleur": "Color",
        "Choisir un PDF…": "Choose a PDF…", "Convertir": "Convert", "Convertir en PDF": "Convert to PDF",
    },
    "de": {
        "Que souhaitez-vous faire ?": "Was möchten Sie tun?", "PDF vers Office": "PDF zu Office",
        "Documents vers PDF": "Dokumente zu PDF", "Organiser les PDF": "PDFs organisieren", "Habillage PDF": "PDF gestalten",
        "Conversion PDF vers Word et extraction de tableaux Excel.": "PDF in Word umwandeln und Excel-Tabellen extrahieren.",
        "Documents bureautiques et images, individuellement ou par lots.": "Office-Dokumente und Bilder einzeln oder stapelweise.",
        "Fusion, extraction, réorganisation et rotation des pages.": "Seiten zusammenführen, extrahieren, neu ordnen und drehen.",
        "Filigranes, en-têtes et pieds de page avec aperçu.": "Wasserzeichen, Kopf- und Fußzeilen mit Vorschau.",
        "Ouvrir le module": "Modul öffnen", "Soutenir Lou Còdi ♥": "Lou Còdi unterstützen ♥",
        "TRAITEMENT LOCAL": "LOKALE VERARBEITUNG", "Destination": "Ziel", "Parcourir…": "Durchsuchen…",
        "Choisir…": "Auswählen…", "Annuler": "Abbrechen", "Fermer": "Schließen", "Supprimer": "Löschen",
        "Prêt.": "Bereit.", "Ouvrir le résultat": "Ergebnis öffnen", "Valider et exporter": "Anwenden und exportieren",
        "Actualiser l’aperçu": "Vorschau aktualisieren", "Pages :": "Seiten:", "Toutes": "Alle",
        "Première page": "Erste Seite", "Dernière page": "Letzte Seite", "Pages paires": "Gerade Seiten",
        "Pages impaires": "Ungerade Seiten", "Personnalisé…": "Benutzerdefiniert…", "Couleur": "Farbe",
        "Choisir un PDF…": "PDF auswählen…", "Convertir": "Konvertieren", "Convertir en PDF": "In PDF konvertieren",
    },
    "es": {
        "Que souhaitez-vous faire ?": "¿Qué desea hacer?", "PDF vers Office": "PDF a Office",
        "Documents vers PDF": "Documentos a PDF", "Organiser les PDF": "Organizar PDF", "Habillage PDF": "Personalizar PDF",
        "Conversion PDF vers Word et extraction de tableaux Excel.": "Convierte PDF a Word y extrae tablas de Excel.",
        "Documents bureautiques et images, individuellement ou par lots.": "Documentos e imágenes, individualmente o por lotes.",
        "Fusion, extraction, réorganisation et rotation des pages.": "Combina, extrae, reordena y gira páginas.",
        "Filigranes, en-têtes et pieds de page avec aperçu.": "Marcas de agua, encabezados y pies con vista previa.",
        "Ouvrir le module": "Abrir módulo", "Soutenir Lou Còdi ♥": "Apoyar a Lou Còdi ♥",
        "TRAITEMENT LOCAL": "PROCESAMIENTO LOCAL", "Destination": "Destino", "Parcourir…": "Examinar…",
        "Choisir…": "Elegir…", "Annuler": "Cancelar", "Fermer": "Cerrar", "Supprimer": "Eliminar",
        "Prêt.": "Listo.", "Ouvrir le résultat": "Abrir resultado", "Valider et exporter": "Aplicar y exportar",
        "Actualiser l’aperçu": "Actualizar vista previa", "Pages :": "Páginas:", "Toutes": "Todas",
        "Première page": "Primera página", "Dernière page": "Última página", "Pages paires": "Páginas pares",
        "Pages impaires": "Páginas impares", "Personnalisé…": "Personalizado…", "Couleur": "Color",
        "Choisir un PDF…": "Elegir un PDF…", "Convertir": "Convertir", "Convertir en PDF": "Convertir a PDF",
    },
    "it": {
        "Que souhaitez-vous faire ?": "Cosa desideri fare?", "PDF vers Office": "PDF in Office",
        "Documents vers PDF": "Documenti in PDF", "Organiser les PDF": "Organizza PDF", "Habillage PDF": "Personalizza PDF",
        "Conversion PDF vers Word et extraction de tableaux Excel.": "Converti PDF in Word ed estrai tabelle Excel.",
        "Documents bureautiques et images, individuellement ou par lots.": "Documenti e immagini, singolarmente o in serie.",
        "Fusion, extraction, réorganisation et rotation des pages.": "Unisci, estrai, riordina e ruota le pagine.",
        "Filigranes, en-têtes et pieds de page avec aperçu.": "Filigrane, intestazioni e piè di pagina con anteprima.",
        "Ouvrir le module": "Apri modulo", "Soutenir Lou Còdi ♥": "Sostieni Lou Còdi ♥",
        "TRAITEMENT LOCAL": "ELABORAZIONE LOCALE", "Destination": "Destinazione", "Parcourir…": "Sfoglia…",
        "Choisir…": "Scegli…", "Annuler": "Annulla", "Fermer": "Chiudi", "Supprimer": "Elimina",
        "Prêt.": "Pronto.", "Ouvrir le résultat": "Apri risultato", "Valider et exporter": "Applica ed esporta",
        "Actualiser l’aperçu": "Aggiorna anteprima", "Pages :": "Pagine:", "Toutes": "Tutte",
        "Première page": "Prima pagina", "Dernière page": "Ultima pagina", "Pages paires": "Pagine pari",
        "Pages impaires": "Pagine dispari", "Personnalisé…": "Personalizzato…", "Couleur": "Colore",
        "Choisir un PDF…": "Scegli un PDF…", "Convertir": "Converti", "Convertir en PDF": "Converti in PDF",
    },
    "zh": {
        "Que souhaitez-vous faire ?": "您想做什么？", "PDF vers Office": "PDF 转 Office",
        "Documents vers PDF": "文档转 PDF", "Organiser les PDF": "整理 PDF", "Habillage PDF": "美化 PDF",
        "Conversion PDF vers Word et extraction de tableaux Excel.": "将 PDF 转换为 Word 并提取 Excel 表格。",
        "Documents bureautiques et images, individuellement ou par lots.": "单个或批量转换办公文档和图像。",
        "Fusion, extraction, réorganisation et rotation des pages.": "合并、提取、重排和旋转页面。",
        "Filigranes, en-têtes et pieds de page avec aperçu.": "带预览的水印、页眉和页脚。",
        "Ouvrir le module": "打开模块", "Soutenir Lou Còdi ♥": "支持 Lou Còdi ♥", "TRAITEMENT LOCAL": "本地处理",
        "Destination": "目标文件夹", "Parcourir…": "浏览…", "Choisir…": "选择…", "Annuler": "取消",
        "Fermer": "关闭", "Supprimer": "删除", "Prêt.": "就绪。", "Ouvrir le résultat": "打开结果",
        "Valider et exporter": "应用并导出", "Actualiser l’aperçu": "刷新预览", "Pages :": "页面：", "Toutes": "全部",
        "Première page": "第一页", "Dernière page": "最后一页", "Pages paires": "偶数页", "Pages impaires": "奇数页",
        "Personnalisé…": "自定义…", "Couleur": "颜色", "Choisir un PDF…": "选择 PDF…",
        "Convertir": "转换", "Convertir en PDF": "转换为 PDF",
    },
    "tr": {
        "Que souhaitez-vous faire ?": "Ne yapmak istersiniz?", "PDF vers Office": "PDF'den Office'e",
        "Documents vers PDF": "Belgelerden PDF'ye", "Organiser les PDF": "PDF'leri düzenle", "Habillage PDF": "PDF'yi özelleştir",
        "Conversion PDF vers Word et extraction de tableaux Excel.": "PDF'yi Word'e dönüştürün ve Excel tablolarını çıkarın.",
        "Documents bureautiques et images, individuellement ou par lots.": "Ofis belgeleri ve görselleri tek tek veya toplu işleyin.",
        "Fusion, extraction, réorganisation et rotation des pages.": "Sayfaları birleştirin, ayırın, sıralayın ve döndürün.",
        "Filigranes, en-têtes et pieds de page avec aperçu.": "Önizlemeli filigran, üstbilgi ve altbilgi.",
        "Ouvrir le module": "Modülü aç", "Soutenir Lou Còdi ♥": "Lou Còdi'yi destekle ♥", "TRAITEMENT LOCAL": "YEREL İŞLEME",
        "Destination": "Hedef", "Parcourir…": "Gözat…", "Choisir…": "Seç…", "Annuler": "İptal",
        "Fermer": "Kapat", "Supprimer": "Sil", "Prêt.": "Hazır.", "Ouvrir le résultat": "Sonucu aç",
        "Valider et exporter": "Uygula ve dışa aktar", "Actualiser l’aperçu": "Önizlemeyi yenile", "Pages :": "Sayfalar:",
        "Toutes": "Tümü", "Première page": "İlk sayfa", "Dernière page": "Son sayfa", "Pages paires": "Çift sayfalar",
        "Pages impaires": "Tek sayfalar", "Personnalisé…": "Özel…", "Couleur": "Renk",
        "Choisir un PDF…": "PDF seç…", "Convertir": "Dönüştür", "Convertir en PDF": "PDF'ye dönüştür",
    },
    "ar": {
        "Que souhaitez-vous faire ?": "ماذا تريد أن تفعل؟", "PDF vers Office": "PDF إلى Office",
        "Documents vers PDF": "المستندات إلى PDF", "Organiser les PDF": "تنظيم ملفات PDF", "Habillage PDF": "تخصيص PDF",
        "Conversion PDF vers Word et extraction de tableaux Excel.": "تحويل PDF إلى Word واستخراج جداول Excel.",
        "Documents bureautiques et images, individuellement ou par lots.": "مستندات وصور مفردة أو بالجملة.",
        "Fusion, extraction, réorganisation et rotation des pages.": "دمج الصفحات واستخراجها وإعادة ترتيبها وتدويرها.",
        "Filigranes, en-têtes et pieds de page avec aperçu.": "علامات مائية ورؤوس وتذييلات مع معاينة.",
        "Ouvrir le module": "فتح الوحدة", "Soutenir Lou Còdi ♥": "ادعم Lou Còdi ♥", "TRAITEMENT LOCAL": "معالجة محلية",
        "Destination": "الوجهة", "Parcourir…": "استعراض…", "Choisir…": "اختيار…", "Annuler": "إلغاء",
        "Fermer": "إغلاق", "Supprimer": "حذف", "Prêt.": "جاهز.", "Ouvrir le résultat": "فتح النتيجة",
        "Valider et exporter": "تطبيق وتصدير", "Actualiser l’aperçu": "تحديث المعاينة", "Pages :": "الصفحات:",
        "Toutes": "الكل", "Première page": "الصفحة الأولى", "Dernière page": "الصفحة الأخيرة", "Pages paires": "الصفحات الزوجية",
        "Pages impaires": "الصفحات الفردية", "Personnalisé…": "مخصص…", "Couleur": "اللون",
        "Choisir un PDF…": "اختيار PDF…", "Convertir": "تحويل", "Convertir en PDF": "تحويل إلى PDF",
    },
}

_support_card_source = (
    "Lou Còdi est un petit club de programmation qui imagine des outils de terrain "
    "accessibles, efficaces et rapides à prendre en main. Votre soutien aide à faire vivre "
    "le projet, développer de nouvelles idées et maintenir ces logiciels utiles à tous."
)

_help_menu_translations = {
    "en": ("Help", "Guides and user manuals", "Software registration", "Privacy", "About", "Contact"),
    "de": ("Hilfe", "Anleitungen und Handbücher", "Software registrieren", "Datenschutz", "Über", "Kontakt"),
    "es": ("Ayuda", "Guías y manuales", "Registro del software", "Privacidad", "Acerca de", "Contacto"),
    "it": ("Aiuto", "Guide e manuali", "Registrazione del software", "Privacy", "Informazioni", "Contatto"),
    "zh": ("帮助", "指南和用户手册", "软件注册", "隐私", "关于", "联系"),
    "tr": ("Yardım", "Kılavuzlar ve kullanım belgeleri", "Yazılım kaydı", "Gizlilik", "Hakkında", "İletişim"),
    "ar": ("المساعدة", "الأدلة وكتيبات الاستخدام", "تسجيل البرنامج", "الخصوصية", "حول", "اتصال"),
}
for _code, _labels in _help_menu_translations.items():
    TRANSLATIONS[_code].update(dict(zip(
        ("Aide", "Guides et modes d’emploi", "Enregistrement du logiciel", "Confidentialité", "À propos", "Contact"),
        _labels,
    )))

# Shared navigation and list vocabulary used across the modules. Keeping this
# set complete prevents one window from mixing French with the chosen locale.
_shared_ui_sources = (
    "Compte Google", "+ Compte", "+ Nouvel espace", "+ Sous-espace", "Supprimer l’espace",
    "Classer l’espace", "+ Ajouter une ressource", "Ajouter lien ou texte copié",
    "Lier un dossier Drive", "Ouvrir dossier Drive", "Actualiser Drive", "Archiver l’album Photos",
    "Dossier albums NAS", "Rechercher", "Mes espaces", "Dictionnaire des tags", "À classer",
    "Déposez ici fichiers, dossiers ou liens — images, ZIP, tableurs et documents sont acceptés.",
    "Titre", "Expéditeur / destinataire", "Type", "Date d’ajout", "Tags", "Compte", "Emplacement",
    "Ouvrir", "Modifier les tags", "Renommer", "Actualiser les infos", "Déplacer vers…",
    "Retirer de l’espace", "Les éléments restent à leur emplacement d’origine.",
    "Fiche de connaissance IA", "Fiche ChatGPT", "Fiche Claude", "Fiche Gemini",
    "Conversation ChatGPT", "Conversation Claude", "Conversation Gemini", "Fichier local",
    "Dossier local", "Dossier Google Drive", "Document Google Drive", "Tableur Google Sheets",
    "Album Google Photos", "Courriel Gmail", "Lien Internet ou vidéo",
)
_shared_ui_translations = {
    "en": ("Google account", "+ Account", "+ New space", "+ Subspace", "Delete space", "Organize space", "+ Add resource", "Add copied link or text", "Link a Drive folder", "Open Drive folder", "Refresh Drive", "Archive Photos album", "NAS albums folder", "Search", "My spaces", "Tag dictionary", "To classify", "Drop files, folders or links here — images, ZIP files, spreadsheets and documents are accepted.", "Title", "Sender / recipient", "Type", "Date added", "Tags", "Account", "Location", "Open", "Edit tags", "Rename", "Refresh information", "Move to…", "Remove from space", "Items remain in their original location.", "AI knowledge note", "ChatGPT note", "Claude note", "Gemini note", "ChatGPT conversation", "Claude conversation", "Gemini conversation", "Local file", "Local folder", "Google Drive folder", "Google Drive document", "Google Sheets spreadsheet", "Google Photos album", "Gmail message", "Web link or video"),
    "de": ("Google-Konto", "+ Konto", "+ Neuer Bereich", "+ Unterbereich", "Bereich löschen", "Bereich einordnen", "+ Ressource hinzufügen", "Kopierten Link oder Text hinzufügen", "Drive-Ordner verknüpfen", "Drive-Ordner öffnen", "Drive aktualisieren", "Fotos-Album archivieren", "NAS-Albumordner", "Suchen", "Meine Bereiche", "Tag-Wörterbuch", "Einzuordnen", "Dateien, Ordner oder Links hier ablegen — Bilder, ZIP-Dateien, Tabellen und Dokumente werden akzeptiert.", "Titel", "Absender / Empfänger", "Typ", "Hinzugefügt am", "Tags", "Konto", "Speicherort", "Öffnen", "Tags bearbeiten", "Umbenennen", "Informationen aktualisieren", "Verschieben nach…", "Aus Bereich entfernen", "Elemente bleiben an ihrem ursprünglichen Speicherort.", "KI-Wissensnotiz", "ChatGPT-Notiz", "Claude-Notiz", "Gemini-Notiz", "ChatGPT-Unterhaltung", "Claude-Unterhaltung", "Gemini-Unterhaltung", "Lokale Datei", "Lokaler Ordner", "Google-Drive-Ordner", "Google-Drive-Dokument", "Google-Sheets-Tabelle", "Google-Fotos-Album", "Gmail-Nachricht", "Weblink oder Video"),
    "es": ("Cuenta de Google", "+ Cuenta", "+ Nuevo espacio", "+ Subespacio", "Eliminar espacio", "Clasificar espacio", "+ Añadir recurso", "Añadir enlace o texto copiado", "Vincular carpeta de Drive", "Abrir carpeta de Drive", "Actualizar Drive", "Archivar álbum de Fotos", "Carpeta de álbumes NAS", "Buscar", "Mis espacios", "Diccionario de etiquetas", "Por clasificar", "Suelte aquí archivos, carpetas o enlaces — se aceptan imágenes, ZIP, hojas de cálculo y documentos.", "Título", "Remitente / destinatario", "Tipo", "Fecha de adición", "Etiquetas", "Cuenta", "Ubicación", "Abrir", "Editar etiquetas", "Renombrar", "Actualizar información", "Mover a…", "Quitar del espacio", "Los elementos permanecen en su ubicación original.", "Ficha de conocimiento IA", "Ficha ChatGPT", "Ficha Claude", "Ficha Gemini", "Conversación ChatGPT", "Conversación Claude", "Conversación Gemini", "Archivo local", "Carpeta local", "Carpeta de Google Drive", "Documento de Google Drive", "Hoja de Google Sheets", "Álbum de Google Fotos", "Correo de Gmail", "Enlace web o vídeo"),
    "it": ("Account Google", "+ Account", "+ Nuovo spazio", "+ Sottospazio", "Elimina spazio", "Classifica spazio", "+ Aggiungi risorsa", "Aggiungi link o testo copiato", "Collega cartella Drive", "Apri cartella Drive", "Aggiorna Drive", "Archivia album Foto", "Cartella album NAS", "Cerca", "I miei spazi", "Dizionario tag", "Da classificare", "Trascina qui file, cartelle o link — sono accettati immagini, ZIP, fogli di calcolo e documenti.", "Titolo", "Mittente / destinatario", "Tipo", "Data di aggiunta", "Tag", "Account", "Posizione", "Apri", "Modifica tag", "Rinomina", "Aggiorna informazioni", "Sposta in…", "Rimuovi dallo spazio", "Gli elementi restano nella posizione originale.", "Scheda conoscenza IA", "Scheda ChatGPT", "Scheda Claude", "Scheda Gemini", "Conversazione ChatGPT", "Conversazione Claude", "Conversazione Gemini", "File locale", "Cartella locale", "Cartella Google Drive", "Documento Google Drive", "Foglio Google Sheets", "Album Google Foto", "Messaggio Gmail", "Link web o video"),
    "zh": ("Google 账号", "+ 账号", "+ 新建空间", "+ 子空间", "删除空间", "空间分类", "+ 添加资源", "添加复制的链接或文本", "关联 Drive 文件夹", "打开 Drive 文件夹", "刷新 Drive", "归档相册", "NAS 相册文件夹", "搜索", "我的空间", "标签词典", "待分类", "将文件、文件夹或链接拖到此处 — 支持图片、ZIP、电子表格和文档。", "标题", "发件人 / 收件人", "类型", "添加日期", "标签", "账号", "位置", "打开", "编辑标签", "重命名", "刷新信息", "移动到…", "从空间移除", "项目仍保留在原始位置。", "AI 知识卡片", "ChatGPT 卡片", "Claude 卡片", "Gemini 卡片", "ChatGPT 对话", "Claude 对话", "Gemini 对话", "本地文件", "本地文件夹", "Google Drive 文件夹", "Google Drive 文档", "Google Sheets 表格", "Google Photos 相册", "Gmail 邮件", "网页链接或视频"),
    "tr": ("Google hesabı", "+ Hesap", "+ Yeni alan", "+ Alt alan", "Alanı sil", "Alanı sınıflandır", "+ Kaynak ekle", "Kopyalanan bağlantı veya metni ekle", "Drive klasörü bağla", "Drive klasörünü aç", "Drive'ı yenile", "Fotoğraflar albümünü arşivle", "NAS albüm klasörü", "Ara", "Alanlarım", "Etiket sözlüğü", "Sınıflandırılacak", "Dosya, klasör veya bağlantıları buraya bırakın — resim, ZIP, tablo ve belgeler kabul edilir.", "Başlık", "Gönderen / alıcı", "Tür", "Eklenme tarihi", "Etiketler", "Hesap", "Konum", "Aç", "Etiketleri düzenle", "Yeniden adlandır", "Bilgileri yenile", "Şuraya taşı…", "Alandan kaldır", "Öğeler özgün konumlarında kalır.", "Yapay zekâ bilgi notu", "ChatGPT notu", "Claude notu", "Gemini notu", "ChatGPT konuşması", "Claude konuşması", "Gemini konuşması", "Yerel dosya", "Yerel klasör", "Google Drive klasörü", "Google Drive belgesi", "Google Sheets tablosu", "Google Fotoğraflar albümü", "Gmail iletisi", "Web bağlantısı veya video"),
    "ar": ("حساب Google", "+ حساب", "+ مساحة جديدة", "+ مساحة فرعية", "حذف المساحة", "تصنيف المساحة", "+ إضافة مورد", "إضافة رابط أو نص منسوخ", "ربط مجلد Drive", "فتح مجلد Drive", "تحديث Drive", "أرشفة ألبوم الصور", "مجلد ألبومات NAS", "بحث", "مساحاتي", "قاموس الوسوم", "للتصنيف", "أفلت الملفات أو المجلدات أو الروابط هنا — الصور وملفات ZIP والجداول والمستندات مقبولة.", "العنوان", "المرسل / المستلم", "النوع", "تاريخ الإضافة", "الوسوم", "الحساب", "الموقع", "فتح", "تعديل الوسوم", "إعادة التسمية", "تحديث المعلومات", "نقل إلى…", "إزالة من المساحة", "تبقى العناصر في موقعها الأصلي.", "بطاقة معرفة بالذكاء الاصطناعي", "بطاقة ChatGPT", "بطاقة Claude", "بطاقة Gemini", "محادثة ChatGPT", "محادثة Claude", "محادثة Gemini", "ملف محلي", "مجلد محلي", "مجلد Google Drive", "مستند Google Drive", "جدول Google Sheets", "ألبوم Google Photos", "رسالة Gmail", "رابط ويب أو فيديو"),
}
for _code, _labels in _shared_ui_translations.items():
    TRANSLATIONS[_code].update(dict(zip(_shared_ui_sources, _labels, strict=True)))

_launcher_sources = (
    "DES OUTILS PRATIQUES, EN LOCAL, POUR CRÉER ET FABRIQUER",
    "Convertir, organiser et enrichir vos documents PDF.",
    "Créer et mettre en page des documents, dessins et schémas.",
    "Optimisation de découpe",
    "Disposer les pièces, calculer les coupes et réduire les chutes.",
    "Comprendre, expérimenter, modifier et créer avec Python, JavaScript, HTML et CSS.",
    "Relier documents, Drive, courriels et albums Photos, et transformer vos échanges avec les IA en fiches de connaissance.",
    "Calculateurs pratiques", "Regrouper les petits calculs utiles à l’atelier.",
    "Domotique et automatismes", "Préparer des installations, commandes et automatismes simples.",
    "Mémo d’atelier", "Lexique, conversions, formules et références techniques.",
    "Préparer les trajectoires d’outil et les programmes d’usinage.",
    "Bientôt disponible", "Module non installé", "Découvrir le module",
    "Les outils PDF restent gratuits. Votre soutien aide à maintenir le projet et à développer les prochains modules.",
)
_launcher_translations = {
    "en": ("PRACTICAL, LOCAL TOOLS FOR CREATING AND MAKING", "Convert, organize and enhance your PDF documents.", "Create and lay out documents, drawings and diagrams.", "Cutting optimization", "Arrange parts, calculate cuts and reduce waste.", "Learn, experiment, modify and create with Python, JavaScript, HTML and CSS.", "Connect documents, Drive, emails and Photos albums, and turn your AI conversations into knowledge notes.", "Practical calculators", "Bring together useful workshop calculations.", "Home automation and controls", "Prepare simple installations, controls and automation.", "Workshop memo", "Glossary, conversions, formulas and technical references.", "Prepare tool paths and machining programs.", "Coming soon", "Module not installed", "Discover module", "PDF tools remain free. Your support helps maintain the project and develop future modules."),
    "de": ("PRAKTISCHE, LOKALE WERKZEUGE ZUM ERSTELLEN UND BAUEN", "PDF-Dokumente konvertieren, organisieren und erweitern.", "Dokumente, Zeichnungen und Diagramme erstellen und gestalten.", "Zuschnittoptimierung", "Teile anordnen, Schnitte berechnen und Verschnitt reduzieren.", "Mit Python, JavaScript, HTML und CSS lernen, experimentieren, ändern und erstellen.", "Dokumente, Drive, E-Mails und Fotos-Alben verknüpfen und KI-Unterhaltungen in Wissensnotizen umwandeln.", "Praktische Rechner", "Nützliche Werkstattberechnungen bündeln.", "Hausautomation und Steuerungen", "Einfache Installationen, Steuerungen und Automatisierungen vorbereiten.", "Werkstatt-Merkblatt", "Glossar, Umrechnungen, Formeln und technische Referenzen.", "Werkzeugwege und Bearbeitungsprogramme vorbereiten.", "Demnächst verfügbar", "Modul nicht installiert", "Modul entdecken", "Die PDF-Werkzeuge bleiben kostenlos. Ihre Unterstützung hilft, das Projekt zu pflegen und kommende Module zu entwickeln."),
    "es": ("HERRAMIENTAS PRÁCTICAS Y LOCALES PARA CREAR Y FABRICAR", "Convierta, organice y mejore sus documentos PDF.", "Cree y diseñe documentos, dibujos y esquemas.", "Optimización de corte", "Disponga piezas, calcule cortes y reduzca desperdicios.", "Aprenda, experimente, modifique y cree con Python, JavaScript, HTML y CSS.", "Conecte documentos, Drive, correos y álbumes de Fotos, y transforme conversaciones con IA en fichas de conocimiento.", "Calculadoras prácticas", "Reúna cálculos útiles para el taller.", "Domótica y automatismos", "Prepare instalaciones, controles y automatismos sencillos.", "Memo de taller", "Glosario, conversiones, fórmulas y referencias técnicas.", "Prepare trayectorias de herramienta y programas de mecanizado.", "Próximamente", "Módulo no instalado", "Descubrir módulo", "Las herramientas PDF siguen siendo gratuitas. Su apoyo ayuda a mantener el proyecto y desarrollar próximos módulos."),
    "it": ("STRUMENTI PRATICI E LOCALI PER CREARE E REALIZZARE", "Converti, organizza e arricchisci i tuoi documenti PDF.", "Crea e impagina documenti, disegni e schemi.", "Ottimizzazione del taglio", "Disponi i pezzi, calcola i tagli e riduci gli scarti.", "Impara, sperimenta, modifica e crea con Python, JavaScript, HTML e CSS.", "Collega documenti, Drive, e-mail e album Foto e trasforma le conversazioni con le IA in schede di conoscenza.", "Calcolatori pratici", "Riunisci i piccoli calcoli utili in officina.", "Domotica e automazioni", "Prepara installazioni, comandi e automazioni semplici.", "Promemoria d’officina", "Glossario, conversioni, formule e riferimenti tecnici.", "Prepara percorsi utensile e programmi di lavorazione.", "Prossimamente", "Modulo non installato", "Scopri il modulo", "Gli strumenti PDF restano gratuiti. Il tuo sostegno aiuta a mantenere il progetto e sviluppare i prossimi moduli."),
    "zh": ("用于创作和制作的实用本地工具", "转换、整理和完善 PDF 文档。", "创建并排版文档、图纸和示意图。", "切割优化", "排列零件、计算切割并减少废料。", "使用 Python、JavaScript、HTML 和 CSS 学习、实验、修改和创作。", "关联文档、Drive、邮件和相册，并将 AI 对话转换为知识卡片。", "实用计算器", "汇集车间常用的小型计算。", "家庭自动化与控制", "准备简单的安装、控制和自动化方案。", "车间备忘录", "术语、换算、公式和技术参考。", "准备刀具路径和加工程序。", "即将推出", "模块未安装", "了解模块", "PDF 工具将继续免费。您的支持有助于维护项目并开发后续模块。"),
    "tr": ("OLUŞTURMAK VE ÜRETMEK İÇİN PRATİK, YEREL ARAÇLAR", "PDF belgelerinizi dönüştürün, düzenleyin ve zenginleştirin.", "Belgeler, çizimler ve şemalar oluşturup düzenleyin.", "Kesim optimizasyonu", "Parçaları yerleştirin, kesimleri hesaplayın ve fireyi azaltın.", "Python, JavaScript, HTML ve CSS ile öğrenin, deneyin, değiştirin ve üretin.", "Belgeleri, Drive'ı, e-postaları ve Fotoğraflar albümlerini bağlayın; yapay zekâ konuşmalarını bilgi notlarına dönüştürün.", "Pratik hesaplayıcılar", "Atölyede yararlı küçük hesapları bir araya getirin.", "Ev otomasyonu ve kontroller", "Basit kurulumlar, kontroller ve otomasyonlar hazırlayın.", "Atölye notları", "Sözlük, dönüşümler, formüller ve teknik kaynaklar.", "Takım yollarını ve işleme programlarını hazırlayın.", "Yakında", "Modül yüklü değil", "Modülü keşfet", "PDF araçları ücretsiz kalır. Desteğiniz projenin bakımına ve gelecek modüllerin geliştirilmesine yardımcı olur."),
    "ar": ("أدوات عملية ومحلية للإنشاء والتصنيع", "تحويل مستندات PDF وتنظيمها وتحسينها.", "إنشاء المستندات والرسومات والمخططات وتنسيقها.", "تحسين القص", "ترتيب القطع وحساب القصات وتقليل الهدر.", "التعلم والتجربة والتعديل والإنشاء باستخدام Python وJavaScript وHTML وCSS.", "ربط المستندات وDrive والبريد وألبومات الصور وتحويل محادثات الذكاء الاصطناعي إلى بطاقات معرفة.", "حاسبات عملية", "جمع الحسابات الصغيرة المفيدة في الورشة.", "المنزل الذكي والتحكم", "إعداد تركيبات وأوامر وأتمتة بسيطة.", "مذكرة الورشة", "مصطلحات وتحويلات وصيغ ومراجع تقنية.", "إعداد مسارات الأدوات وبرامج التشغيل.", "قريباً", "الوحدة غير مثبتة", "اكتشاف الوحدة", "تظل أدوات PDF مجانية. يساعد دعمكم على صيانة المشروع وتطوير الوحدات القادمة."),
}
for _code, _labels in _launcher_translations.items():
    TRANSLATIONS[_code].update(dict(zip(_launcher_sources, _labels, strict=True)))

# The generated catalogue contains every literal displayed by module widgets.
# Curated entries above remain authoritative and override machine translations.
_catalogue_path = Path(__file__).with_name("assets") / "i18n-static.json"
if _catalogue_path.exists():
    try:
        _generated_catalogue = json.loads(_catalogue_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        _generated_catalogue = {}
    for _code, _entries in _generated_catalogue.items():
        if _code in TRANSLATIONS and isinstance(_entries, dict):
            TRANSLATIONS[_code] = {**_entries, **TRANSLATIONS[_code]}

_cutting_terms = {
    "en": ("Sheet", "Wood", "Part"), "de": ("Platte", "Holz", "Teil"),
    "es": ("Placa", "Madera", "Pieza"), "it": ("Pannello", "Legno", "Pezzo"),
    "zh": ("板材", "木材", "零件"), "tr": ("Levha", "Ahşap", "Parça"),
    "ar": ("لوح", "خشب", "قطعة"),
}
for _code, _labels in _cutting_terms.items():
    TRANSLATIONS[_code].update(dict(zip(("Plaque", "Bois", "Pièce"), _labels, strict=True)))

_office_banner_sources = (
    "✓ LibreOffice détecté — conversion fidèle activée",
    "Word, Excel, PowerPoint et OpenDocument seront convertis avec LibreOffice.",
    "⚠ MODE DE CONVERSION ALLÉGÉE",
    "LibreOffice n’est pas installé : DOCX et XLSX simples seront convertis localement. PPT/PPTX, anciens formats et mises en page complexes nécessitent LibreOffice.",
)
_office_banner_translations = {
    "en": ("✓ LibreOffice detected — faithful conversion enabled", "Word, Excel, PowerPoint and OpenDocument files will be converted with LibreOffice.", "⚠ LIGHTWEIGHT CONVERSION MODE", "LibreOffice is not installed: simple DOCX and XLSX files will be converted locally. PPT/PPTX, legacy formats and complex layouts require LibreOffice."),
    "de": ("✓ LibreOffice erkannt — originalgetreue Konvertierung aktiviert", "Word-, Excel-, PowerPoint- und OpenDocument-Dateien werden mit LibreOffice konvertiert.", "⚠ VEREINFACHTER KONVERTIERUNGSMODUS", "LibreOffice ist nicht installiert: Einfache DOCX- und XLSX-Dateien werden lokal konvertiert. PPT/PPTX, ältere Formate und komplexe Layouts erfordern LibreOffice."),
    "es": ("✓ LibreOffice detectado — conversión fiel activada", "Los archivos Word, Excel, PowerPoint y OpenDocument se convertirán con LibreOffice.", "⚠ MODO DE CONVERSIÓN LIGERO", "LibreOffice no está instalado: los archivos DOCX y XLSX sencillos se convertirán localmente. PPT/PPTX, formatos antiguos y diseños complejos requieren LibreOffice."),
    "it": ("✓ LibreOffice rilevato — conversione fedele attivata", "I file Word, Excel, PowerPoint e OpenDocument saranno convertiti con LibreOffice.", "⚠ MODALITÀ DI CONVERSIONE LEGGERA", "LibreOffice non è installato: i file DOCX e XLSX semplici saranno convertiti localmente. PPT/PPTX, formati precedenti e impaginazioni complesse richiedono LibreOffice."),
    "zh": ("✓ 已检测到 LibreOffice — 已启用高保真转换", "Word、Excel、PowerPoint 和 OpenDocument 文件将使用 LibreOffice 转换。", "⚠ 轻量转换模式", "未安装 LibreOffice：简单的 DOCX 和 XLSX 文件将在本地转换。PPT/PPTX、旧格式和复杂版式需要 LibreOffice。"),
    "tr": ("✓ LibreOffice algılandı — yüksek doğruluklu dönüştürme etkin", "Word, Excel, PowerPoint ve OpenDocument dosyaları LibreOffice ile dönüştürülecek.", "⚠ HAFİF DÖNÜŞTÜRME MODU", "LibreOffice yüklü değil: basit DOCX ve XLSX dosyaları yerel olarak dönüştürülecek. PPT/PPTX, eski biçimler ve karmaşık düzenler LibreOffice gerektirir."),
    "ar": ("✓ تم اكتشاف LibreOffice — تم تفعيل التحويل الدقيق", "سيتم تحويل ملفات Word وExcel وPowerPoint وOpenDocument باستخدام LibreOffice.", "⚠ وضع التحويل الخفيف", "LibreOffice غير مثبت: سيتم تحويل ملفات DOCX وXLSX البسيطة محلياً. تتطلب ملفات PPT/PPTX والتنسيقات القديمة والتخطيطات المعقدة LibreOffice."),
}
for _code, _labels in _office_banner_translations.items():
    TRANSLATIONS[_code].update(dict(zip(_office_banner_sources, _labels, strict=True)))

_drive_ready_translations = {
    "en": "Google Drive ready", "de": "Google Drive bereit", "es": "Google Drive listo",
    "it": "Google Drive pronto", "zh": "Google Drive 已就绪", "tr": "Google Drive hazır",
    "ar": "Google Drive جاهز",
}
for _code, _label in _drive_ready_translations.items():
    TRANSLATIONS[_code]["Google Drive prêt"] = _label

TRANSLATIONS["en"].update({
    "Soutenir Lou Còdi": "Support Lou Còdi",
    "Découvrir et soutenir ♥": "Discover and support ♥",
    _support_card_source: "Lou Còdi is a small programming club that creates accessible, effective, easy-to-use tools for real-world needs. Your support helps keep the project alive, develop new ideas and maintain software that is useful to everyone.",
})
TRANSLATIONS["de"].update({
    "Soutenir Lou Còdi": "Lou Còdi unterstützen",
    "Découvrir et soutenir ♥": "Entdecken und unterstützen ♥",
    _support_card_source: "Lou Còdi ist ein kleiner Programmierclub, der zugängliche, effiziente und schnell erlernbare Werkzeuge für die Praxis entwickelt. Ihre Unterstützung hilft, das Projekt weiterzuführen, neue Ideen zu entwickeln und diese nützlichen Programme zu pflegen.",
})
TRANSLATIONS["es"].update({
    "Soutenir Lou Còdi": "Apoyar a Lou Còdi",
    "Découvrir et soutenir ♥": "Descubrir y apoyar ♥",
    _support_card_source: "Lou Còdi es un pequeño club de programación que crea herramientas prácticas, accesibles, eficaces y fáciles de aprender. Tu apoyo ayuda a mantener vivo el proyecto, desarrollar nuevas ideas y conservar programas útiles para todos.",
})
TRANSLATIONS["it"].update({
    "Soutenir Lou Còdi": "Sostieni Lou Còdi",
    "Découvrir et soutenir ♥": "Scopri e sostieni ♥",
    _support_card_source: "Lou Còdi è un piccolo club di programmazione che crea strumenti pratici, accessibili, efficaci e facili da imparare. Il tuo sostegno aiuta a mantenere vivo il progetto, sviluppare nuove idee e curare software utili a tutti.",
})
TRANSLATIONS["zh"].update({
    "Soutenir Lou Còdi": "支持 Lou Còdi",
    "Découvrir et soutenir ♥": "了解并支持 ♥",
    _support_card_source: "Lou Còdi 是一个小型编程俱乐部，致力于开发贴近实际、易于使用且高效的工具。您的支持将帮助项目持续发展、实现新想法，并维护这些对大家都有用的软件。",
})
TRANSLATIONS["tr"].update({
    "Soutenir Lou Còdi": "Lou Còdi'yi destekleyin",
    "Découvrir et soutenir ♥": "Keşfedin ve destekleyin ♥",
    _support_card_source: "Lou Còdi, sahadaki ihtiyaçlar için erişilebilir, etkili ve kolay öğrenilen araçlar geliştiren küçük bir programlama kulübüdür. Desteğiniz projenin yaşamasına, yeni fikirlerin gelişmesine ve herkes için yararlı bu yazılımların sürdürülmesine katkı sağlar.",
})
TRANSLATIONS["ar"].update({
    "Soutenir Lou Còdi": "ادعم Lou Còdi",
    "Découvrir et soutenir ♥": "اكتشف وادعم ♥",
    _support_card_source: "Lou Còdi نادٍ صغير للبرمجة يطوّر أدوات عملية وسهلة الاستخدام وفعّالة. يساعد دعمكم على استمرار المشروع وتطوير أفكار جديدة وصيانة برامج مفيدة للجميع.",
})

# Complete English catalogue used as a safe fallback for every translated interface.
# Locale-specific catalogues override it, so untranslated text never falls back to French.
TRANSLATIONS["en"].update(
    {
        "Langue": "Language", "Conversion locale par lots": "Local batch conversion",
        "Documents bureautiques et images — traitement local par lots": "Office documents and images — local batch processing",
        "Réorganiser, fusionner, extraire, dupliquer et faire pivoter les pages": "Reorder, merge, extract, duplicate and rotate pages",
        "Filigranes, en-têtes et pieds de page avec aperçu": "Watermarks, headers and footers with preview",
        "Format :": "Format:", "Ajouter des PDF…": "Add PDFs…", "Ajouter des documents…": "Add documents…",
        "Document": "Document", "Pages": "Pages", "Analyse": "Analysis", "État": "Status",
        "Mot de passe PDF :": "PDF password:", "Word (.docx)": "Word (.docx)",
        "Excel (.xlsx) — tableaux": "Excel (.xlsx) — tables", "Fichiers à convertir": "Files to convert",
        "Dossier": "Folder", "Fusionner tous les PDF produits dans un document supplémentaire": "Merge all generated PDFs into an additional document",
        "Aucun document": "No document", "Aucun PDF": "No PDF", "Aucun document transmis sur Internet": "No document sent over the Internet",
        "Ajoutez au moins un document PDF.": "Add at least one PDF document.", "Ajoutez au moins un document.": "Add at least one document.",
        "Ajoutez au moins une page.": "Add at least one page.", "Ajoutez un ou plusieurs PDF.": "Add one or more PDFs.",
        "Choisissez d’abord un document PDF.": "Choose a PDF document first.", "Choisissez un dossier existant.": "Choose an existing folder.",
        "Choisissez un dossier de destination existant.": "Choose an existing destination folder.",
        "Dossier introuvable": "Folder not found", "Dossier inaccessible": "Folder unavailable", "Document vide": "Empty document",
        "Conversion terminée": "Conversion complete", "Conversion en cours": "Conversion in progress", "Conversion…": "Converting…",
        "Analyse…": "Analyzing…", "En attente": "Waiting", "Terminé :": "Completed:", "Terminé →": "Completed →",
        "réussite(s),": "successful,", "échec(s).": "failed.", "Échec :": "Failure:", "Ouverture de": "Opening",
        "Ouverture impossible": "Unable to open", "Export impossible": "Unable to export", "Import impossible": "Unable to import",
        "Ouvrir le PDF": "Open PDF", "Ouvrir le document": "Open document", "Ouvrir le dossier": "Open folder",
        "Opération réussie": "Operation successful", "Le document a été créé dans :": "The document was created in:",
        "PDF créé :": "PDF created:", "PDF créé(s) dans :": "PDF(s) created in:", "document(s) créé(s) dans :": "document(s) created in:",
        "Aperçu": "Preview", "Aperçu actualisé.": "Preview refreshed.", "Aperçu impossible": "Unable to preview",
        "PLACEMENT À LA SOURIS": "MOUSE PLACEMENT", "Cliquez ou faites glisser l’élément choisi sur la page.": "Click or drag the selected item on the page.",
        "Choisissez un PDF puis cliquez sur\n« Actualiser l’aperçu ».": "Choose a PDF, then click\n\u201cRefresh preview\u201d.",
        "Ajuster": "Fit", "Élargir": "Expand", "Réduire": "Reduce", "Rétablir": "Redo",
        "Filigrane": "Watermark", "Logo": "Logo", "En-tête": "Header", "Pied": "Footer", "Masque": "Mask",
        "En-tête et pied de page": "Header and footer", "Masquage visuel": "Visual masking",
        "Texte libre": "Free text", "Image de filigrane": "Watermark image", "Taille": "Size",
        "Rotation (degrés)": "Rotation (degrees)", "Transparence (%)": "Transparency (%)", "Placer au premier plan": "Place in foreground",
        "Position X (mm, vide = centre)": "X position (mm, blank = center)", "Position Y (mm, vide = centre)": "Y position (mm, blank = center)",
        "Position Y (mm, vide = haut)": "Y position (mm, blank = top)", "Fichier PNG ou JPG": "PNG or JPG file",
        "Logo appliqué aux pages sélectionnées": "Logo applied to selected pages", "Largeur (mm)": "Width (mm)",
        "Sélectionnez « Logo » à droite, puis cliquez ou faites glisser sur l’aperçu.": "Select \u201cLogo\u201d on the right, then click or drag on the preview.",
        "Position en-tête": "Header position", "En-tête X (mm, vide = alignement)": "Header X (mm, blank = alignment)",
        "En-tête depuis le haut (mm)": "Header from top (mm)", "Pied de page": "Footer", "Position pied": "Footer position",
        "Pied X (mm, vide = alignement)": "Footer X (mm, blank = alignment)", "Pied depuis le bas (mm)": "Footer from bottom (mm)",
        "Taille du texte": "Text size", "Ajouter un liseré horizontal": "Add a horizontal line",
        "Ajouter rapidement :": "Quick add:", "Marge gauche": "Left margin", "Marge droite": "Right margin",
        "Zone libre": "Free area", "Zone tracée": "Drawn area", "Nom": "Name", "X (mm)": "X (mm)", "Y depuis le bas (mm)": "Y from bottom (mm)",
        "Hauteur (mm)": "Height (mm)", "Ajouter avec ces coordonnées": "Add with these coordinates", "Mettre à jour": "Update",
        "Pour tracer : sélectionnez « Masque » à droite puis faites glisser sur l’aperçu.": "To draw: select \u201cMask\u201d on the right, then drag on the preview.",
        "Attention : ces masques sont uniquement visuels. Ils ne suppriment pas de façon sécurisée les informations confidentielles du PDF.": "Warning: these masks are visual only. They do not securely remove confidential information from the PDF.",
        "Masque invalide": "Invalid mask", "Habillage terminé": "Customization complete", "Export du PDF…": "Exporting PDF…",
        "Page blanche": "Blank page", "Document source": "Source document", "Ordre": "Order", "Page": "Page", "Rotation": "Rotation",
        "Dupliquer": "Duplicate", "Tout vider": "Clear all", "Valider et exporter le PDF": "Apply and export PDF",
        "Ajouter les PDF sélectionnés": "Add selected PDFs", "Ajouter les fichiers sélectionnés": "Add selected files",
        "Choisir les documents PDF": "Choose PDF documents", "Choisir les documents ou images": "Choose documents or images",
        "Choisir des PDF — Téléchargements": "Choose PDFs — Downloads", "Choisir des documents ou images — Téléchargements": "Choose documents or images — Downloads",
        "Choisir le dossier de destination": "Choose destination folder", "Choisir ce dossier": "Choose this folder",
        "Revenir à Téléchargements": "Return to Downloads", "Téléchargements": "Downloads", "↑ Dossier parent": "↑ Parent folder",
        "Nom du fichier ou dossier": "File or folder name", "Modifié le": "Modified", "Double-cliquez sur un dossier pour l’ouvrir.": "Double-click a folder to open it.",
        "Ctrl ou Maj : sélectionner plusieurs fichiers": "Ctrl or Shift: select multiple files", "Sélection": "Selection",
        "Sélectionnez un ou plusieurs documents PDF.": "Select one or more PDF documents.",
        "Sélectionnez un ou plusieurs documents ou images pris en charge.": "Select one or more supported documents or images.",
        "Aucun tableau exploitable détecté. Un PDF scanné nécessitera l’OCR local.": "No usable table detected. A scanned PDF will require local OCR.",
        "PDF scanné probable": "Likely scanned PDF", "PDF scanné probable : OCR local non encore disponible.": "Likely scanned PDF: local OCR is not available yet.",
        "Texte détecté": "Text detected", "PDF chiffré": "Encrypted PDF", "Mot de passe requis": "Password required",
        "Ce PDF est chiffré et ne peut pas être lu.": "This PDF is encrypted and cannot be read.",
        "Ce PDF est chiffré et nécessite un mot de passe valide.": "This PDF is encrypted and requires a valid password.",
        "Une conversion est encore en cours. Fermer cette fenêtre masquera son suivi.\n\nVoulez-vous vraiment fermer ?": "A conversion is still running. Closing this window will hide its progress.\n\nDo you really want to close it?",
        "Le moteur local de ce module est prêt. L’interface détaillée sera intégrée au prochain lot.": "The local engine for this module is ready. Its detailed interface will be added in the next release.",
        "Variables : {page}  {pages}  {document}  {date}": "Variables: {page}  {pages}  {document}  {date}",
        "↑ Monter": "↑ Move up", "↓ Descendre": "↓ Move down", "↻ Rotation 90°": "↻ Rotate 90°",
        "page(s)": "page(s)", "page(s) dans le document.": "page(s) in the document.", "Placement": "Placement",
        "La page": "Page", "n’existe pas dans ce document.": "does not exist in this document.",
        "Indiquez au moins une page valide.": "Enter at least one valid page.",
        "Format non pris en charge :": "Unsupported format:",
        "LibreOffice est requis pour convertir ce document.": "LibreOffice is required to convert this document.",
        "La rotation doit être de 90, 180 ou 270 degrés.": "Rotation must be 90, 180 or 270 degrees.",
    }
)

TRANSLATIONS["ar"].update(
    {
        "Langue": "اللغة", "Conversion locale par lots": "تحويل محلي بالجملة", "Format :": "التنسيق:",
        "Ajouter des PDF…": "إضافة PDF…", "Ajouter des documents…": "إضافة مستندات…", "Document": "المستند",
        "Pages": "الصفحات", "Analyse": "التحليل", "État": "الحالة", "Mot de passe PDF :": "كلمة مرور PDF:",
        "Excel (.xlsx) — tableaux": "Excel (.xlsx) — جداول", "Fichiers à convertir": "ملفات للتحويل", "Dossier": "المجلد",
        "Aucun document": "لا يوجد مستند", "Aucun PDF": "لا يوجد PDF", "Ajoutez au moins un document PDF.": "أضف مستند PDF واحداً على الأقل.",
        "Ajoutez au moins un document.": "أضف مستنداً واحداً على الأقل.", "Ajoutez au moins une page.": "أضف صفحة واحدة على الأقل.",
        "Choisissez d’abord un document PDF.": "اختر مستند PDF أولاً.", "Choisissez un dossier existant.": "اختر مجلداً موجوداً.",
        "Dossier introuvable": "المجلد غير موجود", "Conversion terminée": "اكتمل التحويل", "Conversion en cours": "التحويل جارٍ",
        "Conversion…": "جارٍ التحويل…", "En attente": "في الانتظار", "Ouverture impossible": "تعذر الفتح", "Export impossible": "تعذر التصدير",
        "Opération réussie": "نجحت العملية", "Le document a été créé dans :": "تم إنشاء المستند في:", "Aperçu": "معاينة",
        "Aperçu actualisé.": "تم تحديث المعاينة.", "Aperçu impossible": "تعذرت المعاينة", "PLACEMENT À LA SOURIS": "الوضع بالفأرة",
        "Cliquez ou faites glisser l’élément choisi sur la page.": "انقر أو اسحب العنصر المحدد على الصفحة.",
        "Ajuster": "ملاءمة", "Élargir": "توسيع", "Réduire": "تصغير", "Rétablir": "إعادة", "Filigrane": "علامة مائية",
        "En-tête": "الرأس", "Pied": "التذييل", "Masque": "قناع", "En-tête et pied de page": "الرأس والتذييل", "Masquage visuel": "إخفاء مرئي",
        "Texte libre": "نص حر", "Image de filigrane": "صورة العلامة المائية", "Taille": "الحجم", "Rotation (degrés)": "الدوران (درجات)",
        "Transparence (%)": "الشفافية (%)", "Placer au premier plan": "وضع في المقدمة", "Position X (mm, vide = centre)": "موضع X (مم، فارغ = الوسط)",
        "Position Y (mm, vide = centre)": "موضع Y (مم، فارغ = الوسط)", "Fichier PNG ou JPG": "ملف PNG أو JPG", "Largeur (mm)": "العرض (مم)",
        "Position en-tête": "موضع الرأس", "Pied de page": "تذييل الصفحة", "Position pied": "موضع التذييل", "Taille du texte": "حجم النص",
        "Ajouter rapidement :": "إضافة سريعة:", "Marge gauche": "الهامش الأيسر", "Marge droite": "الهامش الأيمن", "Zone libre": "منطقة حرة",
        "Hauteur (mm)": "الارتفاع (مم)", "Mettre à jour": "تحديث", "Masque invalide": "قناع غير صالح", "Habillage terminé": "اكتمل التخصيص",
        "Page blanche": "صفحة فارغة", "Document source": "المستند المصدر", "Ordre": "الترتيب", "Page": "الصفحة", "Rotation": "الدوران",
        "Dupliquer": "تكرار", "Ajouter les PDF sélectionnés": "إضافة ملفات PDF المحددة", "Choisir les documents PDF": "اختيار مستندات PDF",
        "Choisir le dossier de destination": "اختيار مجلد الوجهة", "Choisir ce dossier": "اختيار هذا المجلد", "Revenir à Téléchargements": "العودة إلى التنزيلات",
        "Téléchargements": "التنزيلات", "↑ Dossier parent": "↑ المجلد الأصل", "Nom du fichier ou dossier": "اسم الملف أو المجلد", "Modifié le": "تاريخ التعديل",
        "PDF scanné probable": "يحتمل أن PDF ممسوح", "Texte détecté": "تم اكتشاف نص", "PDF chiffré": "PDF مشفر", "Mot de passe requis": "كلمة مرور مطلوبة",
    }
)

_support_source_message = (
    "Ce logiciel est mis gratuitement à votre disposition par Lou Còdi, club de "
    "programmation. Il est le fruit d’un travail bénévole et tous les traitements "
    "de vos documents sont réalisés localement sur votre ordinateur.\n\n"
    "Vous pourrez soutenir librement la création et la maintenance de nouveaux "
    "outils, sans jamais bloquer l’utilisation du logiciel."
)
_reminder_source_message = (
    "PDF Converter est mis gratuitement à votre disposition par Lou Còdi. "
    "Votre contribution volontaire aide le club à financer la création, la "
    "maintenance et la mise à disposition de nouveaux outils respectueux de "
    "votre vie privée.\n\nVous pouvez également continuer gratuitement."
)
_missing_office_runtime = "Le moteur bureautique intégré est absent de cette édition."

TRANSLATIONS["en"].update(
    {
        "Bienvenue": "Welcome",
        "Bienvenue dans PDF Converter – Lou Còdi": "Welcome to PDF Converter – Lou Còdi",
        _support_source_message: (
            "This software is provided free of charge by Lou Còdi, a programming club. "
            "It is the result of volunteer work, and all your documents are processed "
            "locally on your computer.\n\nYou may freely support the creation and maintenance "
            "of new tools, without the software ever being restricted."
        ),
        "Découvrir Lou Còdi": "Discover Lou Còdi",
        "Commencer": "Get started",
        "Soutenir Lou Còdi": "Support Lou Còdi",
        "Merci d’utiliser PDF Converter – Lou Còdi": "Thank you for using PDF Converter – Lou Còdi",
        _reminder_source_message: (
            "PDF Converter is provided free of charge by Lou Còdi. Your voluntary "
            "contribution helps the club fund the creation, maintenance and availability "
            "of new privacy-friendly tools.\n\nYou can also continue free of charge."
        ),
        "Continuer gratuitement": "Continue for free",
        "Ne plus afficher les rappels de soutien": "Do not show support reminders again",
        _missing_office_runtime: "The built-in office engine is missing from this edition.",
    }
)

TRANSLATIONS["de"].update(
    {
        "Bienvenue": "Willkommen",
        "Bienvenue dans PDF Converter – Lou Còdi": "Willkommen bei PDF Converter – Lou Còdi",
        _support_source_message: (
            "Diese Software wird vom Programmierclub Lou Còdi kostenlos bereitgestellt. "
            "Sie ist das Ergebnis ehrenamtlicher Arbeit, und alle Dokumente werden lokal "
            "auf Ihrem Computer verarbeitet.\n\nSie können die Entwicklung und Pflege neuer "
            "Werkzeuge freiwillig unterstützen, ohne dass die Nutzung eingeschränkt wird."
        ),
        "Découvrir Lou Còdi": "Lou Còdi entdecken",
        "Commencer": "Starten",
        "Soutenir Lou Còdi": "Lou Còdi unterstützen",
        "Merci d’utiliser PDF Converter – Lou Còdi": "Danke, dass Sie PDF Converter – Lou Còdi verwenden",
        _reminder_source_message: (
            "PDF Converter wird von Lou Còdi kostenlos bereitgestellt. Ihr freiwilliger "
            "Beitrag hilft dem Club, neue datenschutzfreundliche Werkzeuge zu entwickeln, "
            "zu pflegen und bereitzustellen.\n\nSie können auch kostenlos fortfahren."
        ),
        "Continuer gratuitement": "Kostenlos fortfahren",
        "Ne plus afficher les rappels de soutien": "Keine Unterstützungs­hinweise mehr anzeigen",
        _missing_office_runtime: "Die integrierte Office-Engine fehlt in dieser Ausgabe.",
    }
)

TRANSLATIONS["es"].update(
    {
        "Bienvenue": "Bienvenido",
        "Bienvenue dans PDF Converter – Lou Còdi": "Bienvenido a PDF Converter – Lou Còdi",
        _support_source_message: (
            "Este programa es ofrecido gratuitamente por Lou Còdi, un club de programación. "
            "Es fruto de un trabajo voluntario y todos los documentos se procesan localmente "
            "en su ordenador.\n\nPuede apoyar libremente la creación y el mantenimiento de "
            "nuevas herramientas sin que se bloquee nunca el programa."
        ),
        "Découvrir Lou Còdi": "Descubrir Lou Còdi",
        "Commencer": "Empezar",
        "Soutenir Lou Còdi": "Apoyar a Lou Còdi",
        "Merci d’utiliser PDF Converter – Lou Còdi": "Gracias por usar PDF Converter – Lou Còdi",
        _reminder_source_message: (
            "Lou Còdi ofrece PDF Converter gratuitamente. Su contribución voluntaria ayuda "
            "al club a financiar la creación, el mantenimiento y la disponibilidad de nuevas "
            "herramientas respetuosas con su privacidad.\n\nTambién puede continuar gratis."
        ),
        "Continuer gratuitement": "Continuar gratis",
        "Ne plus afficher les rappels de soutien": "No volver a mostrar recordatorios de apoyo",
        _missing_office_runtime: "Falta el motor ofimático integrado en esta edición.",
    }
)

TRANSLATIONS["it"].update(
    {
        "Bienvenue": "Benvenuto",
        "Bienvenue dans PDF Converter – Lou Còdi": "Benvenuto in PDF Converter – Lou Còdi",
        _support_source_message: (
            "Questo software è messo gratuitamente a disposizione da Lou Còdi, un club di "
            "programmazione. È frutto di lavoro volontario e tutti i documenti vengono "
            "elaborati localmente sul computer.\n\nPuoi sostenere liberamente la creazione e "
            "la manutenzione di nuovi strumenti senza che il software venga mai bloccato."
        ),
        "Découvrir Lou Còdi": "Scopri Lou Còdi",
        "Commencer": "Inizia",
        "Soutenir Lou Còdi": "Sostieni Lou Còdi",
        "Merci d’utiliser PDF Converter – Lou Còdi": "Grazie per aver scelto PDF Converter – Lou Còdi",
        _reminder_source_message: (
            "PDF Converter è offerto gratuitamente da Lou Còdi. Il tuo contributo volontario "
            "aiuta il club a finanziare la creazione, la manutenzione e la disponibilità di "
            "nuovi strumenti rispettosi della privacy.\n\nPuoi anche continuare gratuitamente."
        ),
        "Continuer gratuitement": "Continua gratuitamente",
        "Ne plus afficher les rappels de soutien": "Non mostrare più i promemoria di sostegno",
        _missing_office_runtime: "Il motore per ufficio integrato non è presente in questa edizione.",
    }
)

TRANSLATIONS["zh"].update(
    {
        "Bienvenue": "欢迎",
        "Bienvenue dans PDF Converter – Lou Còdi": "欢迎使用 PDF Converter – Lou Còdi",
        _support_source_message: (
            "本软件由编程俱乐部 Lou Còdi 免费提供，是志愿工作的成果。您的所有文档都只在本机处理。"
            "\n\n您可以自愿支持新工具的开发和维护，软件的使用绝不会因此受到限制。"
        ),
        "Découvrir Lou Còdi": "了解 Lou Còdi",
        "Commencer": "开始",
        "Soutenir Lou Còdi": "支持 Lou Còdi",
        "Merci d’utiliser PDF Converter – Lou Còdi": "感谢您使用 PDF Converter – Lou Còdi",
        _reminder_source_message: (
            "PDF Converter 由 Lou Còdi 免费提供。您的自愿支持将帮助俱乐部开发、维护并提供尊重隐私的新工具。"
            "\n\n您也可以继续免费使用。"
        ),
        "Continuer gratuitement": "继续免费使用",
        "Ne plus afficher les rappels de soutien": "不再显示支持提醒",
        _missing_office_runtime: "此版本缺少内置办公文档引擎。",
    }
)

TRANSLATIONS["tr"].update(
    {
        "Bienvenue": "Hoş geldiniz",
        "Bienvenue dans PDF Converter – Lou Còdi": "PDF Converter – Lou Còdi'ye hoş geldiniz",
        _support_source_message: (
            "Bu yazılım, bir programlama kulübü olan Lou Còdi tarafından ücretsiz sunulmaktadır. "
            "Gönüllü bir çalışmanın ürünüdür ve tüm belgeleriniz bilgisayarınızda yerel olarak "
            "işlenir.\n\nYazılımın kullanımı hiçbir zaman engellenmeden yeni araçların geliştirilmesini "
            "ve bakımını gönüllü olarak destekleyebilirsiniz."
        ),
        "Découvrir Lou Còdi": "Lou Còdi'yi keşfet",
        "Commencer": "Başla",
        "Soutenir Lou Còdi": "Lou Còdi'yi destekle",
        "Merci d’utiliser PDF Converter – Lou Còdi": "PDF Converter – Lou Còdi'yi kullandığınız için teşekkürler",
        _reminder_source_message: (
            "PDF Converter, Lou Còdi tarafından ücretsiz sunulmaktadır. Gönüllü katkınız, "
            "kulübün gizliliğinize saygılı yeni araçlar geliştirmesine ve bunların bakımını "
            "sağlamasına yardımcı olur.\n\nÜcretsiz olarak devam edebilirsiniz."
        ),
        "Continuer gratuitement": "Ücretsiz devam et",
        "Ne plus afficher les rappels de soutien": "Destek hatırlatmalarını bir daha gösterme",
        _missing_office_runtime: "Bu sürümde yerleşik ofis motoru bulunmuyor.",
    }
)

TRANSLATIONS["ar"].update(
    {
        "Bienvenue": "مرحباً",
        "Bienvenue dans PDF Converter – Lou Còdi": "مرحباً بك في PDF Converter – Lou Còdi",
        _support_source_message: (
            "يوفر نادي البرمجة Lou Còdi هذا البرنامج مجاناً. وهو ثمرة عمل تطوعي، وتتم معالجة "
            "جميع مستنداتك محلياً على جهازك.\n\nيمكنك دعم إنشاء الأدوات الجديدة وصيانتها طوعاً، "
            "من دون تقييد استخدام البرنامج أبداً."
        ),
        "Découvrir Lou Còdi": "اكتشف Lou Còdi",
        "Commencer": "ابدأ",
        "Soutenir Lou Còdi": "ادعم Lou Còdi",
        "Merci d’utiliser PDF Converter – Lou Còdi": "شكراً لاستخدام PDF Converter – Lou Còdi",
        _reminder_source_message: (
            "يوفر Lou Còdi برنامج PDF Converter مجاناً. تساعد مساهمتك الطوعية النادي على تمويل "
            "إنشاء أدوات جديدة تحترم خصوصيتك وصيانتها وإتاحتها.\n\nيمكنك أيضاً المتابعة مجاناً."
        ),
        "Continuer gratuitement": "المتابعة مجاناً",
        "Ne plus afficher les rappels de soutien": "عدم إظهار تذكيرات الدعم مرة أخرى",
        _missing_office_runtime: "محرك المستندات المكتبية المدمج غير موجود في هذه النسخة.",
    }
)

TRANSLATIONS["de"]["Aucun document transmis sur Internet"] = "Kein Dokument wird über das Internet übertragen"
TRANSLATIONS["es"]["Aucun document transmis sur Internet"] = "Ningún documento se transmite por Internet"
TRANSLATIONS["it"]["Aucun document transmis sur Internet"] = "Nessun documento viene trasmesso via Internet"
TRANSLATIONS["zh"]["Aucun document transmis sur Internet"] = "不会通过互联网传输任何文档"
TRANSLATIONS["tr"]["Aucun document transmis sur Internet"] = "Hiçbir belge internet üzerinden aktarılmaz"
TRANSLATIONS["ar"]["Aucun document transmis sur Internet"] = "لا يتم إرسال أي مستند عبر الإنترنت"

TRANSLATIONS["ar"].update(
    {
        "Analyse…": "جارٍ التحليل…", "Aucun tableau exploitable détecté. Un PDF scanné nécessitera l’OCR local.": "لم يتم اكتشاف جدول قابل للاستخدام. سيحتاج PDF الممسوح إلى OCR محلي.",
        "Ce PDF est chiffré et ne peut pas être lu.": "ملف PDF هذا مشفر ولا يمكن قراءته.", "Ce PDF est chiffré et nécessite un mot de passe valide.": "ملف PDF هذا مشفر ويتطلب كلمة مرور صالحة.",
        "Choisir des PDF — Téléchargements": "اختيار PDF — التنزيلات", "En-tête X (mm, vide = alignement)": "X للرأس (مم، فارغ = محاذاة)",
        "En-tête depuis le haut (mm)": "الرأس من الأعلى (مم)", "Export du PDF…": "جارٍ تصدير PDF…", "Nom": "الاسم",
        "Ouverture de": "جارٍ فتح", "Ouvrir le PDF": "فتح PDF", "Ouvrir le document": "فتح المستند", "Ouvrir le dossier": "فتح المجلد",
        "PDF créé :": "تم إنشاء PDF:", "PDF créé(s) dans :": "تم إنشاء PDF في:", "PDF scanné probable : OCR local non encore disponible.": "يحتمل أن PDF ممسوح: OCR المحلي غير متاح بعد.",
        "Pied X (mm, vide = alignement)": "X للتذييل (مم، فارغ = محاذاة)", "Pied depuis le bas (mm)": "التذييل من الأسفل (مم)",
        "Position Y (mm, vide = haut)": "موضع Y (مم، فارغ = الأعلى)", "Sélectionnez un ou plusieurs documents PDF.": "حدد مستند PDF واحداً أو أكثر.",
        "Terminé :": "اكتمل:", "Terminé →": "اكتمل →", "X (mm)": "X (مم)", "Y depuis le bas (mm)": "Y من الأسفل (مم)", "Zone tracée": "منطقة مرسومة",
        "document(s) créé(s) dans :": "تم إنشاء المستند(ات) في:", "réussite(s),": "ناجحة،", "Échec :": "فشل:", "échec(s).": "فاشلة.",
    }
)

TRANSLATIONS["ar"].update(
    {
        "Ajouter avec ces coordonnées": "إضافة بهذه الإحداثيات",
        "Ajouter les fichiers sélectionnés": "إضافة الملفات المحددة",
        "Ajouter un liseré horizontal": "إضافة خط أفقي",
        "Ajoutez un ou plusieurs PDF.": "أضف ملف PDF واحداً أو أكثر.",
        "Attention : ces masques sont uniquement visuels. Ils ne suppriment pas de façon sécurisée les informations confidentielles du PDF.": "تنبيه: هذه الأقنعة مرئية فقط ولا تحذف المعلومات السرية من PDF بأمان.",
        "Choisir des documents ou images — Téléchargements": "اختيار مستندات أو صور — التنزيلات",
        "Choisir les documents ou images": "اختيار المستندات أو الصور",
        "Choisissez un PDF puis cliquez sur\n« Actualiser l’aperçu ».": "اختر PDF ثم انقر على\n«تحديث المعاينة».",
        "Choisissez un dossier de destination existant.": "اختر مجلد وجهة موجوداً.",
        "Ctrl ou Maj : sélectionner plusieurs fichiers": "Ctrl أو Shift: تحديد عدة ملفات",
        "Document vide": "مستند فارغ",
        "Documents bureautiques et images — traitement local par lots": "مستندات وصور — معالجة محلية بالجملة",
        "Dossier inaccessible": "تعذر الوصول إلى المجلد",
        "Double-cliquez sur un dossier pour l’ouvrir.": "انقر مرتين على مجلد لفتحه.",
        "Filigranes, en-têtes et pieds de page avec aperçu": "علامات مائية ورؤوس وتذييلات مع معاينة",
        "Fusionner tous les PDF produits dans un document supplémentaire": "دمج كل ملفات PDF المنتجة في مستند إضافي",
        "Import impossible": "تعذر الاستيراد", "Logo": "الشعار",
        "Logo appliqué aux pages sélectionnées": "الشعار مطبق على الصفحات المحددة",
        "Ouvrir les résultats": "فتح النتائج",
        "Pour tracer : sélectionnez « Masque » à droite puis faites glisser sur l’aperçu.": "للرسم: حدد «قناع» على اليمين ثم اسحب على المعاينة.",
        "Retirer": "إزالة",
        "Réorganiser, fusionner, extraire, dupliquer et faire pivoter les pages": "إعادة ترتيب الصفحات ودمجها واستخراجها وتكرارها وتدويرها",
        "Sélection": "التحديد",
        "Sélectionnez un ou plusieurs documents ou images pris en charge.": "حدد مستنداً أو صورة مدعومة واحدة أو أكثر.",
        "Sélectionnez « Logo » à droite, puis cliquez ou faites glisser sur l’aperçu.": "حدد «الشعار» على اليمين، ثم انقر أو اسحب على المعاينة.",
        "Tout effacer": "مسح الكل", "Tout vider": "إفراغ الكل",
        "Une conversion est encore en cours. Fermer cette fenêtre masquera son suivi.\n\nVoulez-vous vraiment fermer ?": "ما زال التحويل جارياً. سيؤدي إغلاق هذه النافذة إلى إخفاء تقدمه.\n\nهل تريد حقاً الإغلاق؟",
        "Valider et exporter le PDF": "تطبيق PDF وتصديره", "Word (.docx)": "Word (.docx)",
        "Le moteur local de ce module est prêt. L’interface détaillée sera intégrée au prochain lot.": "محرك هذه الوحدة المحلي جاهز، وستضاف واجهتها التفصيلية في الإصدار القادم.",
        "Variables : {page}  {pages}  {document}  {date}": "المتغيرات: {page}  {pages}  {document}  {date}",
        "↑ Monter": "↑ نقل لأعلى", "↓ Descendre": "↓ نقل لأسفل", "↻ Rotation 90°": "↻ تدوير 90°",
        "page(s)": "صفحة/صفحات", "page(s) dans le document.": "صفحة/صفحات في المستند.", "Placement": "موضع",
        "La page": "الصفحة", "n’existe pas dans ce document.": "غير موجودة في هذا المستند.",
        "Indiquez au moins une page valide.": "أدخل صفحة صحيحة واحدة على الأقل.",
        "Format non pris en charge :": "تنسيق غير مدعوم:",
        "LibreOffice est requis pour convertir ce document.": "LibreOffice مطلوب لتحويل هذا المستند.",
        "La rotation doit être de 90, 180 ou 270 degrés.": "يجب أن يكون الدوران 90 أو 180 أو 270 درجة.",
    }
)


def settings_path() -> Path:
    return Path.home() / ".config" / "lou-codi-pdf-converter" / "preferences.json"


def load_language() -> str:
    try:
        value = json.loads(settings_path().read_text(encoding="utf-8")).get("language", "fr")
    except (OSError, ValueError, TypeError, AttributeError):
        value = "fr"
    return value if value in LANGUAGES else "fr"


def set_language(language: str, *, save: bool = True) -> None:
    global _language
    _language = language if language in LANGUAGES else "fr"
    if save:
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            preferences = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(preferences, dict):
                preferences = {}
        except (OSError, ValueError, TypeError):
            preferences = {}
        preferences["language"] = _language
        path.write_text(json.dumps(preferences, ensure_ascii=False, indent=2), encoding="utf-8")


def get_language() -> str:
    return _language


def tr(text: str) -> str:
    if _language == "fr":
        return text
    language_map = TRANSLATIONS.get(_language, {})
    translated = language_map.get(text)
    if translated is None:
        translated = text
        replacements = dict(TRANSLATIONS.get("en", {}))
        replacements.update(language_map)
        for source in sorted(replacements, key=len, reverse=True):
            if source in translated:
                translated = translated.replace(source, replacements[source])
    return _shape_arabic(translated) if _language == "ar" else translated


def untr(text: str) -> str:
    """Return the French source text for a translated choice, when known."""
    translations = TRANSLATIONS.get(_language, {})
    return next(
        (
            source
            for source, translated in translations.items()
            if translated == text or (_language == "ar" and _shape_arabic(translated) == text)
        ),
        text,
    )


def _shape_arabic(text: str) -> str:
    return get_display(arabic_reshaper.reshape(text))


def install_messagebox_translations() -> None:
    """Translate native Tk message boxes, including those created after startup."""
    if getattr(messagebox, "_lou_codi_i18n", False):
        return
    for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel"):
        original = getattr(messagebox, name)

        def translated_box(title: str, message: str, *args: object, _original=original, **kwargs: object):
            return _original(tr(title), tr(message), *args, **kwargs)

        setattr(messagebox, name, translated_box)
    messagebox._lou_codi_i18n = True


def translate_widget_tree(root: tk.Misc) -> None:
    """Translate static Tk texts after an interface has been constructed."""
    try:
        text = root.cget("text")
        if text:
            root.configure(text=tr(str(text)))
    except tk.TclError:
        pass
    if isinstance(root, (tk.Tk, tk.Toplevel)):
        root.title(tr(root.title()))
    if isinstance(root, ttk.Notebook):
        for tab_id in root.tabs():
            root.tab(tab_id, text=tr(root.tab(tab_id, "text")))
    if isinstance(root, ttk.Treeview):
        for column in ("#0", *root["columns"]):
            root.heading(column, text=tr(root.heading(column, "text")))
    if isinstance(root, ttk.Combobox):
        values = tuple(root.cget("values"))
        if values:
            root.configure(values=tuple(tr(str(value)) for value in values))
    if isinstance(root, tk.Menu):
        try:
            end = root.index("end")
        except tk.TclError:
            end = None
        if end is not None:
            for index in range(end + 1):
                try:
                    label = root.entrycget(index, "label")
                    if label:
                        root.entryconfigure(index, label=tr(label))
                except tk.TclError:
                    continue
    for child in root.winfo_children():
        translate_widget_tree(child)
