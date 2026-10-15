from lou_codi_pdf_converter.i18n import set_language, tr, untr


def test_translation_and_reverse_translation() -> None:
    set_language("es", save=False)
    assert tr("Toutes") == "Todas"
    assert untr("Todas") == "Toutes"
    assert tr("Lou Còdi") == "Lou Còdi"
    set_language("fr", save=False)


def test_unknown_language_falls_back_to_french() -> None:
    set_language("unknown", save=False)
    assert tr("Annuler") == "Annuler"
