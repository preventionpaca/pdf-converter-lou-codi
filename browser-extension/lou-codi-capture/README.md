# Lou Còdi Capture

Extension de développement Chrome/Chromium reliée au pont local de Lou Còdi Workshop.

## Tester sans publier

1. Lancez Lou Còdi Workshop depuis les sources.
2. Dans Chrome, ouvrez `chrome://extensions`.
3. Activez **Mode développeur**, puis **Charger l’extension non empaquetée**.
4. Sélectionnez ce dossier `browser-extension/lou-codi-capture`.
5. Sur une page, un lien, une image ou une sélection, faites un clic droit puis choisissez
   **Ajouter à Lou Còdi Espace** et l’espace destinataire.

L’extension parle uniquement au service local `127.0.0.1:47632`. Aucun contenu
n’est envoyé à un serveur Lou Còdi.

Pour tester le service permanent sous Linux, exécutez une fois :

```sh
sh packaging/linux/install-capture-service-dev.sh
```

Le service utilisateur démarre ensuite avec la session Linux, même lorsque la
fenêtre du Workshop est fermée.
