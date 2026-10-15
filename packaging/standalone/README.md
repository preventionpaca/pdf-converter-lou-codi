# Construction autonome

La construction autonome embarque l’interpréteur Python, toutes les dépendances et le
moteur bureautique local utilisé pour produire les PDF. Elle ne télécharge aucun
composant lors du lancement et l’utilisateur n’a pas à installer LibreOffice.

Avant la construction, préparer le moteur de la plateforme dans
`packaging/runtime/office-runtime` selon `packaging/runtime/README.md`.

Une construction doit être produite et testée séparément sur Linux, Windows et macOS :

```bash
python -m pip install -e '.[packaging]'
python -m PyInstaller --clean packaging/standalone/lou-codi-pdf-converter.spec
pip-licenses --format=plain-vertical --with-license-file \
  > dist/lou-codi-pdf-converter/THIRD_PARTY_NOTICES.txt
```

Le dossier `dist/lou-codi-pdf-converter` est ensuite intégré dans l’installateur de
la plateforme. `LICENSE`, `THIRD_PARTY_NOTICES.md` et `SOURCE_DISTRIBUTION.md` sont
également inclus automatiquement. Les textes de licence générés doivent être relus
avant chaque livraison.

Figer les versions dans un fichier de verrouillage de livraison reste nécessaire : les
contraintes de `pyproject.toml` servent au développement, pas à reproduire indéfiniment
un installateur déjà publié.
