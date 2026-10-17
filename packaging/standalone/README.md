# Construction autonome

La construction autonome embarque l’interpréteur Python et les dépendances propres à
Lou Còdi, mais **n’embarque pas LibreOffice**. Les DOCX et XLSX ordinaires utilisent le
moteur de conversion allégé intégré. Lorsqu’une installation système de LibreOffice est
détectée, elle est utilisée pour une conversion fidèle et pour les formats complexes,
anciens ou PowerPoint.

L’absence de LibreOffice ne doit jamais empêcher l’installation ou le lancement de Lou
Còdi. L’interface indique clairement le moteur disponible et ses limites.

La dictée locale expérimentale n’est plus embarquée. Le bouton ChatGPT ouvre le
navigateur et le presse-papiers sert de passerelle explicite ; aucun texte n’est envoyé
automatiquement par Lou Còdi.

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
