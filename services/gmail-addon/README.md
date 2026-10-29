# Module Gmail — Lou Còdi Espace

Ce projet Apps Script est volontairement séparé du collecteur de licences. Il ajoute
une carte contextuelle dans Gmail quand un message est ouvert.

Le module lit uniquement les métadonnées du message ouvert. Après confirmation de
l’utilisateur, il ajoute dans le fichier `.loucodi-espace` choisi :

- l’objet ;
- l’expéditeur et les destinataires ;
- la date du message ;
- l’identifiant Gmail exact et celui de la conversation ;
- le lien permanent permettant de rouvrir la conversation.

## Installation de développement

1. Créer un **nouveau projet Apps Script**, distinct du collecteur et rattaché au
   projet Google Cloud `loucodi-workshop`.
2. Copier `Code.gs` et `appsscript.json` dans ce projet.
3. Dans **Déployer > Tester les déploiements**, installer le module pour le compte
   Google en cours.
4. Autoriser la lecture des métadonnées du message ouvert et l’accès à Drive.
5. Ouvrir Gmail, ouvrir un message, puis cliquer sur l’icône Lou Còdi Espace dans la
   barre latérale droite.

L’accès Drive sert à rechercher et mettre à jour les index `.loucodi-espace`. Aucun
contenu de courriel ni pièce jointe n’est copié. Chaque compte Google doit installer
et autoriser le module une fois.

Dans Lou Còdi, **Actualiser Drive** récupère ensuite les nouveaux courriels reliés.
