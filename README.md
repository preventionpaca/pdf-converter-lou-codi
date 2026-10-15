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

Les installateurs de livraison embarquent leur propre moteur bureautique local pour
convertir les documents Office. L’utilisateur n’a rien à installer séparément et aucun
document n’est envoyé sur Internet. Une installation LibreOffice du système peut être
utilisée comme solution de repli uniquement dans l’environnement de développement.

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
