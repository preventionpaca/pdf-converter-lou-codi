from lou_codi_pdf_converter.i18n import TRANSLATIONS, set_language, tr, untr


def test_translation_and_reverse_translation() -> None:
    set_language("es", save=False)
    assert tr("Toutes") == "Todas"
    assert untr("Todas") == "Toutes"
    assert tr("Lou Còdi") == "Lou Còdi"
    set_language("fr", save=False)


def test_unknown_language_falls_back_to_french() -> None:
    set_language("unknown", save=False)
    assert tr("Annuler") == "Annuler"


def test_english_and_arabic_catalogues_cover_the_same_interface() -> None:
    assert set(TRANSLATIONS["en"]) <= set(TRANSLATIONS["ar"])
    set_language("ar", save=False)
    assert tr("Ajoutez au moins un document PDF.") != "Ajoutez au moins un document PDF."
    set_language("fr", save=False)


def test_main_workspace_vocabulary_is_complete_in_every_language() -> None:
    required = {
        "+ Nouvel espace", "Supprimer l’espace", "Ajouter lien ou texte copié",
        "Titre", "Expéditeur / destinataire", "Date d’ajout", "Emplacement",
        "Modifier les tags", "Déplacer vers…", "Retirer de l’espace",
        "Fichier local", "Album Google Photos", "Courriel Gmail",
    }
    for language, catalogue in TRANSLATIONS.items():
        assert required <= set(catalogue), language
        assert all(catalogue[source] != source for source in required), language


def test_launcher_cards_are_complete_in_every_language() -> None:
    required = {
        "Convertir, organiser et enrichir vos documents PDF.",
        "Optimisation de découpe", "Calculateurs pratiques",
        "Domotique et automatismes", "Mémo d’atelier", "Bientôt disponible",
        "Les outils PDF restent gratuits. Votre soutien aide à maintenir le projet et à développer les prochains modules.",
    }
    for language, catalogue in TRANSLATIONS.items():
        assert required <= set(catalogue), language
        assert all(catalogue[source] != source for source in required), language


def test_representative_labels_from_every_module_are_translated() -> None:
    required = {
        "CONVERTIR, ORGANISER ET ENRICHIR VOS PDF — EN LOCAL",
        "Fichiers à convertir", "Ajouter des documents…", "Catalogue des polices",
        "Image de filigrane", "Stock et plan de découpe", "Ajouter au stock",
        "Voir le code source", "Dictionnaire des tags", "Plaque", "Bois", "Pièce",
        "✓ LibreOffice détecté — conversion fidèle activée",
        "Word, Excel, PowerPoint et OpenDocument seront convertis avec LibreOffice.",
        "Google Drive prêt",
    }
    for language, catalogue in TRANSLATIONS.items():
        assert required <= set(catalogue), language
        assert all(catalogue[source] != source for source in required), language
