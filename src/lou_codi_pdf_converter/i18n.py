from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk

LANGUAGES = {
    "fr": "Français",
    "en": "English",
    "de": "Deutsch",
    "es": "Español",
    "it": "Italiano",
    "zh": "中文",
    "tr": "Türkçe",
    "ar": "العربية",
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
    return TRANSLATIONS.get(_language, {}).get(text, text)


def untr(text: str) -> str:
    """Return the French source text for a translated choice, when known."""
    translations = TRANSLATIONS.get(_language, {})
    return next((source for source, translated in translations.items() if translated == text), text)


def translate_widget_tree(root: tk.Misc) -> None:
    """Translate static Tk texts after an interface has been constructed."""
    try:
        text = root.cget("text")
        if text:
            root.configure(text=tr(str(text)))
    except tk.TclError:
        pass
    if isinstance(root, (tk.Tk, tk.Toplevel)):
        title = root.title()
        for source, translated in TRANSLATIONS.get(_language, {}).items():
            title = title.replace(source, translated)
        root.title(title)
    if isinstance(root, ttk.Notebook):
        for tab_id in root.tabs():
            root.tab(tab_id, text=tr(root.tab(tab_id, "text")))
    if isinstance(root, ttk.Treeview):
        for column in root["columns"]:
            root.heading(column, text=tr(root.heading(column, "text")))
    for child in root.winfo_children():
        translate_widget_tree(child)
