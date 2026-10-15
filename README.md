# PDF Converter – Lou Còdi

Application bureautique libre permettant de convertir, organiser et personnaliser
des documents PDF. Tous les traitements documentaires sont effectués localement.

## État du projet

La branche `main` contient la reconstruction 2.0 à partir du paquet Debian 1.1.6.
La version actuelle est une préversion de développement : le module PDF vers Office
est préservé dans une architecture testable, et les briques d'organisation PDF sont
en cours d'intégration.

## Développement

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/lou-codi-pdf-converter
```

Pour convertir les documents Office vers PDF, LibreOffice doit être installé
localement. Aucun document n'est envoyé sur Internet.

## Licence

GPL-3.0-or-later. © Lou Còdi.

