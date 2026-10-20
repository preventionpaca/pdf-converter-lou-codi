# PDF Converter – Lou Còdi

Application bureautique libre permettant de convertir, organiser et personnaliser
des documents PDF. Tous les traitements documentaires sont effectués localement.

## État du projet

La branche `main` contient la reconstruction 2.0 à partir du paquet Debian 1.1.6.
La version actuelle est une préversion de développement : le module PDF vers Office
est préservé dans une architecture testable, et les briques d'organisation PDF sont
en cours d'intégration.

## Développement

### Données locales et assistant de rédaction

Au premier démarrage, l’application crée automatiquement une base SQLite
`loucodi.db` dans le dossier de données de l’utilisateur. Aucun serveur de base
de données n’est requis. Le chemin respecte les conventions de Windows, macOS
et Linux.

Depuis une zone de texte, le bouton ChatGPT copie une consigne de dictée ou de
reformulation puis ouvre le site ChatGPT dans le navigateur par défaut. Aucun
contenu n’est envoyé automatiquement. L’utilisateur colle lui-même la consigne,
puis peut rapatrier le résultat par le presse-papiers et le relire avant insertion.

Le module **Stock et découpe** conserve localement le stock de plaques dans
SQLite. Il accepte des formats et quantités différents, l’état des chutes, une
liste de pièces saisie dans un tableau ou importée depuis les rectangles d’un
projet Lou Còdi, puis calcule un premier plan de placement en tenant compte de
l’épaisseur de lame (3 mm par défaut). L’optimisation actuelle concerne les
pièces rectangulaires et reste une heuristique : le plan doit être contrôlé avant
la découpe réelle.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/lou-codi-pdf-converter
```

Les installateurs de livraison embarquent le moteur bureautique allégé de Lou Còdi pour
les DOCX et XLSX usuels. Aucun document n’est envoyé sur Internet. Si LibreOffice est
déjà installé sur l’ordinateur, il est détecté automatiquement pour les conversions
fidèles, PowerPoint, OpenDocument, les anciens formats et les mises en page complexes.
LibreOffice reste un logiciel indépendant et n’est pas inclus dans les paquets Lou Còdi.

Dans Document Studio, un DOCX peut être ouvert comme document courant ou inséré à la
suite des pages existantes. Les PDF conservent leur rendu d’origine ; une pipette
typographique relève la police, la taille, la couleur et le style d’un texte sélectionnable.
Le catalogue de polices inventorie les familles installées, propose la plus proche si la
police manque et ouvre sa recherche sur Google Fonts. L’OCR des pages scannées reste
facultatif et n’est activé que si Tesseract est disponible sur l’ordinateur.

L’installation complète ajoute le raccourci et les dossiers de travail.
L’installation personnalisée permet de désactiver ces éléments facultatifs ; le cœur de
l’application et ses bibliothèques PDF sont toujours installés.

Au premier lancement, l’application présente son fonctionnement gratuit. Un rappel de
soutien volontaire est ensuite proposé toutes les vingt ouvertures ; il peut être
désactivé définitivement. Le paiement reste facultatif et ne bloque aucune fonction.

Les livraisons autonomes embarquent Python et leurs bibliothèques afin de ne dépendre
d’aucun téléchargement à l’exécution. Leur procédure de construction est décrite dans
`packaging/standalone/README.md`.

## Licence

PDF Converter – Lou Còdi est un logiciel libre distribué sous licence
**GNU Affero General Public License v3.0 ou ultérieure** (`AGPL-3.0-or-later`).

Le code source correspondant à chaque version publiée doit rester disponible avec
ses scripts de construction. Les bibliothèques et moteurs embarqués conservent leurs
propres licences, répertoriées dans `THIRD_PARTY_NOTICES.md`.

© Lou Còdi — Club de programmation.

Code source : <https://github.com/preventionpaca/pdf-converter-lou-codi>
