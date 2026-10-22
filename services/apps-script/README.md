# Collecteur Apps Script Lou Còdi

Ce Web App reçoit uniquement les demandes de licence, activations et événements
d’usage consentis. Il ne fournit aucune donnée de consultation et ne contient aucun
tableau de bord : la consultation reste dans l’administration de `loucodi.fr`, après
authentification Google et contrôle de la table Grist `Administrateurs`.

Le collecteur utilise le **même document Grist** que l’administration. Il ne crée ni
tableur Google ni base indépendante. Les tables attendues (`Licences`,
`Installations`, `Statistiques`) sont décrites dans
le fichier `admin-apps-script/schema-grist.json` du dépôt du site.

## Propriétés de script privées

- `LC_GRIST_API_URL` : `https://docs.getgrist.com` par défaut ;
- `LC_GRIST_DOC_ID` : identifiant du document déjà utilisé par l’administration ;
- `LC_GRIST_API_KEY` : jeton Grist, conservé uniquement côté serveur ;
- `LC_CLIENT_TOKEN` : jeton d’écriture distinct, injecté dans les paquets logiciels.

Le Web App doit être exécuté par son propriétaire et accessible aux clients installés.
La connaissance de `LC_CLIENT_TOKEN` permet seulement d’appeler les quatre actions
d’écriture exposées ; elle ne permet jamais de lire Grist ni d’ouvrir l’administration.

La télémétrie est inactive sans consentement explicite. Elle ne transmet aucun fichier,
contenu, nom de fichier, chemin, adresse électronique ou identifiant d’installation.
Les dimensions autorisées sont limitées au format et au moteur de conversion.
