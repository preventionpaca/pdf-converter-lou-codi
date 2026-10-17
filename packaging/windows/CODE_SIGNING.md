# Signature Windows de Lou Còdi Workshop

L'installateur contient déjà `AppPublisher=Lou Còdi`. Ce champ renseigne Windows dans la
fiche du programme et la désinstallation, mais il ne peut pas produire la mention
« éditeur vérifié » dans SmartScreen ou le contrôle de compte utilisateur.

Pour afficher un éditeur vérifié, les exécutables et le programme d'installation doivent
porter une signature Authenticode émise par une autorité reconnue. Le nom affiché sera le
nom légal validé dans le certificat, pas un nom de marque librement saisi.

## Décision à prendre

Choisir une des voies suivantes :

1. publier un paquet MSIX dans le Microsoft Store ; Microsoft le signe lors de la
   publication ;
2. souscrire un service Microsoft Artifact Signing si le statut juridique et le pays du
   détenteur sont admissibles ;
3. acquérir un certificat OV auprès d'une autorité de certification reconnue ;
4. étudier un service de signature destiné aux projets libres. Son acceptation dépend de
   ses critères et ne doit pas être présumée.

Une signature autosignée ne convient pas à une diffusion publique : elle reste inconnue
des autres ordinateurs et n'apporte pas la confiance SmartScreen attendue.

## Informations nécessaires

- titulaire légal du certificat : personne physique, association ou société ;
- pays et adresse vérifiables ;
- nom d'éditeur qui pourra légalement apparaître ;
- moyen de signature choisi ;
- secret, jeton matériel ou identité de signature conservé hors du dépôt Git ;
- URL RFC 3161 du service d'horodatage.

## Chaîne de publication future

1. construire l'exécutable principal ;
2. signer et horodater l'exécutable principal ;
3. construire le `Setup.exe` ;
4. signer et horodater le `Setup.exe` ;
5. vérifier les deux signatures avec `signtool verify /pa /v` ;
6. publier sans jamais modifier les fichiers signés.

Même signé, un nouveau certificat peut encore déclencher temporairement SmartScreen le
temps d'acquérir une réputation. En revanche, Windows pourra afficher l'identité vérifiée
du signataire et cette réputation pourra être conservée entre les versions signées avec la
même identité.
