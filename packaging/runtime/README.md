# Moteur bureautique embarqué

Chaque construction de livraison doit déposer ici, sous le nom `office-runtime`,
le moteur LibreOffice correspondant au système et à l’architecture ciblés. Ce dossier
est intégré automatiquement par la recette PyInstaller.

Arborescences reconnues :

- Windows : `office-runtime/program/soffice.exe` ou la distribution officielle
  PortableApps sous `office-runtime/LibreOfficePortable/App/libreoffice/program/soffice.exe` ;
- macOS : `office-runtime/LibreOffice.app/Contents/MacOS/soffice` ;
- Linux : `office-runtime/program/soffice`.

Les trois moteurs sont construits séparément : un binaire Windows ne doit jamais être
placé dans le paquet macOS ou Linux. Conserver dans le paquet les fichiers `LICENSE`,
`NOTICE` et les mentions tierces fournis avec la distribution utilisée.

Le moteur n’est jamais téléchargé au lancement. L’application privilégie toujours
cette copie privée et utilise l’installation système uniquement pendant le développement.
