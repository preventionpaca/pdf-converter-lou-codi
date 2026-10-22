# Service gratuit de licences et statistiques

Ce dossier contient le Web App Google Apps Script de Lou Còdi Workshop. Il crée un
tableur privé avec trois feuilles (`Licences`, `Installations`, `Statistiques`), envoie
les clés gratuites par courrier électronique et limite chaque clé à trois postes.

## Installation

1. Créer un projet Apps Script depuis le compte Google Workspace administrateur.
2. Copier `Code.gs` et ajouter un fichier HTML nommé `Dashboard` avec le contenu de
   `Dashboard.html`.
3. Dans **Paramètres du projet > Propriétés du script**, créer :
   - `ADMIN_EMAIL` : l'adresse fonctionnelle privée chargée des licences ;
   - `ADMIN_PASSWORD` : une phrase secrète longue et unique pour le tableau de secours ;
   - `ADMIN_API_KEY` : une autre valeur aléatoire longue, partagée uniquement avec
     l’administration Apps Script du site.
4. Exécuter `setupService` une fois et autoriser le script. La fonction renvoie l'URL
   du tableur privé créé automatiquement.
5. Déployer comme **Application Web**, exécutée par le propriétaire, accessible à
   toute personne disposant du lien. Conserver l'URL `/exec`.
6. Le tableau de bord se trouve à `URL_EXEC?view=admin` et demande `ADMIN_PASSWORD`.

L’administration principale du site utilise `ADMIN_API_KEY` pour charger les chiffres
et gérer les licences côté serveur. Cette clé ne doit jamais être envoyée au navigateur.

Ne jamais placer l'adresse administratrice, le mot de passe, l'identifiant du tableur
ou l'URL privée dans Git. L'URL publique `/exec` pourra être injectée dans les paquets
Windows et Linux au moment de la construction.

La collecte reste désactivée tant que l'utilisateur n'a pas donné son consentement.
Les événements ne contiennent ni document, ni texte, ni chemin de fichier, ni adresse
électronique. Les adresses des licences sont conservées séparément.
