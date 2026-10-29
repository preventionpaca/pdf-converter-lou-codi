# Installer Lou Còdi Workshop

Les distributions autonomes embarquent Python et les bibliothèques utilisées par les
modules PDF. Elles ne nécessitent donc pas l’installation séparée d’un environnement de
développement.

## Dépendances

- **Intégrées et obligatoires** : Python, bibliothèques PDF, interface et ressources Lou Còdi.
- **LibreOffice, facultatif** : recommandé pour les conversions fidèles de Word, Excel,
  PowerPoint, OpenDocument et des anciens formats. Sans LibreOffice, le moteur local allégé
  reste utilisable pour les DOCX et XLSX simples.
- **Navigateur, facultatif** : nécessaire pour l’aide en ligne, les comptes Google et
  l’extension Lou Còdi Capture.
- **Outils de bureau Linux, facultatifs** : `xdg-utils`, `desktop-file-utils` et
  `shared-mime-info` améliorent l’intégration au menu et à l’explorateur.

Le contrôle de préinstallation affiche les versions détectées. Sur une distribution
Debian/Ubuntu, il compare LibreOffice avec la version candidate des dépôts déjà configurés.
Sous Windows, il interroge `winget` lorsqu’il est disponible. Ce contrôle ne met jamais à
jour un logiciel tiers sans décision de l’utilisateur.

## Linux

Décompresser l’archive, puis exécuter :

```bash
./check-requirements.sh
./installer.sh
```

Lorsque Zenity est disponible, l’installation utilise des panneaux graphiques pour le
choix du mode, des modules et des options. Un parcours textuel équivalent est proposé
dans un terminal lorsque Zenity n’est pas installé.

Le programme propose une installation complète ou personnalisée et détecte une version
Lou Còdi existante avant la mise à niveau. Pour désinstaller :

```bash
~/.local/share/lou-codi-workshop/app/uninstall.sh
```

Les documents et espaces sont conservés. L’option `--purge-user-data` supprime également
les réglages Lou Còdi, mais jamais les documents créés dans Téléchargements.

Le paquet `.deb` peut aussi être installé et supprimé avec le gestionnaire habituel :

```bash
sudo apt install ./Lou-Codi-Workshop-*-linux-amd64.deb
sudo apt remove lou-codi-workshop
```

## Windows

L’installateur Inno Setup affiche les composants détectés, propose le choix des modules,
crée les associations de fichiers et enregistre le désinstalleur dans **Paramètres →
Applications**. Une installation portant le même identifiant est mise à niveau sur place.

Le paquet ZIP offre également un installateur PowerShell guidé :

```powershell
powershell -ExecutionPolicy Bypass -File .\check-requirements.ps1
powershell -ExecutionPolicy Bypass -File .\installer.ps1
```

La désinstallation Windows conserve par défaut les documents, espaces et projets de
l’utilisateur.
