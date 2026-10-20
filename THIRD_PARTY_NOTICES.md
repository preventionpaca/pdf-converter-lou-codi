# Composants tiers et licences

Ce document recense les dépendances directes de PDF Converter – Lou Còdi. Les versions
exactes livrées sont consignées dans le fichier de verrouillage de chaque publication.
Les textes complets des licences doivent être inclus dans l’installateur final.

| Composant | Usage principal | Licence |
| --- | --- | --- |
| PyMuPDF / MuPDF | rendu des aperçus et manipulation PDF | AGPL-3.0 ou licence commerciale Artifex |
| pdf2docx | conversion PDF vers DOCX | MIT |
| pypdf | lecture, écriture, fusion et organisation PDF | BSD-3-Clause |
| pdfplumber | extraction de tableaux et de texte | MIT |
| openpyxl | création de classeurs XLSX | MIT |
| Pillow | traitement des images | MIT-CMU |
| ReportLab | génération des calques et contenus PDF | BSD |
| arabic-reshaper | affichage de l’arabe | MIT |
| python-bidi | affichage bidirectionnel | LGPL-3.0-or-later |
| Google API Python Client | accès autorisé aux API Gmail et People | Apache-2.0 |
| google-auth-oauthlib | connexion Google OAuth 2.0 | Apache-2.0 |
| keyring | stockage des jetons dans le coffre-fort du système | MIT |

SQLite, fourni par la bibliothèque standard Python, est placé dans le domaine public.
LibreOffice n’est pas distribué dans les paquets Lou Còdi. Lorsqu’il est déjà installé
sur l’ordinateur, Lou Còdi peut l’appeler comme logiciel externe indépendant.

## Sources officielles

- PyMuPDF : <https://github.com/pymupdf/PyMuPDF>
- pdf2docx : <https://github.com/ArtifexSoftware/pdf2docx>
- pypdf : <https://github.com/py-pdf/pypdf>
- pdfplumber : <https://github.com/jsvine/pdfplumber>
- openpyxl : <https://foss.heptapod.net/openpyxl/openpyxl>
- Pillow : <https://github.com/python-pillow/Pillow>
- ReportLab : <https://hg.reportlab.com/hg-public/reportlab>
- arabic-reshaper : <https://github.com/mpcabd/python-arabic-reshaper>
- python-bidi : <https://github.com/MeirKriheli/python-bidi>
- Google API Python Client : <https://github.com/googleapis/google-api-python-client>
- google-auth-oauthlib : <https://github.com/googleapis/google-auth-library-python-oauthlib>
- keyring : <https://github.com/jaraco/keyring>
- LibreOffice : <https://www.libreoffice.org/about-us/licenses/>

## Obligations de livraison

Une livraison binaire doit être accompagnée d’un accès gratuit au code source
correspondant de PDF Converter – Lou Còdi. Elle doit également conserver les notices,
les textes de licence et les moyens d’obtenir les sources des composants qui l’exigent.

Si une future édition embarque LibreOffice, elle devra reprendre sans modification ses
fichiers de licence et de mentions tierces, ainsi que l’adresse de son code source exact.
