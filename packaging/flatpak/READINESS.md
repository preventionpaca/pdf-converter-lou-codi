# Préparation Flatpak / Flathub — Lou Còdi Workshop

Ce document est un inventaire de préparation. Ce n'est volontairement pas un manifeste
Flatpak : la politique Flathub actuelle interdit qu'un manifeste de soumission soit généré
par une IA. Le manifeste et la demande d'intégration devront être rédigés et envoyés par le
mainteneur humain du projet.

## Identité proposée

- Nom public : `Lou Còdi Workshop`
- Identifiant Flatpak : `io.github.preventionpaca.pdf-converter-lou-codi`
- Dépôt amont : `https://github.com/preventionpaca/pdf-converter-lou-codi`
- Licence du programme : `AGPL-3.0-or-later`
- Type AppStream : `desktop-application`
- Développeur : `Lou Còdi`
- Commande : `lou-codi-pdf-converter`
- Icône amont : `src/lou_codi_pdf_converter/assets/croix-lou-codi.png` (1254 × 1254, RGBA)

L'identifiant suit la règle Flathub des projets hébergés sur GitHub et correspond au chemin
exact du dépôt. Il doit être considéré comme définitif avant toute soumission.

## Fichiers à intégrer en amont

Le mainteneur doit rédiger puis faire valider :

1. `io.github.preventionpaca.pdf-converter-lou-codi.desktop` ;
2. `io.github.preventionpaca.pdf-converter-lou-codi.metainfo.xml` ;
3. une icône PNG ou SVG installée sous le même identifiant ;
4. au moins une capture propre, sans donnée personnelle, publiée à une URL figée par tag
   ou commit ;
5. un bloc `releases` AppStream correspondant à une version stable ;
6. un manifeste de dépendances Python généré hors ligne avec `flatpak-pip-generator` ;
7. le manifeste Flatpak final, écrit et vérifié humainement.

Les métadonnées doivent au minimum comporter le nom, un résumé anglais et français, une
description anglaise complète, le développeur, la licence, la catégorie, les captures, les
URL du dépôt et de suivi des anomalies, la commande de lancement et l'historique des
versions.

## Runtime et construction

- Choisir, au moment de la soumission, la dernière branche encore maintenue de
  `org.freedesktop.Platform` et de son SDK.
- Construire l'application depuis les sources ; ne pas déposer le `.deb`, l'archive
  PyInstaller ou un autre binaire dans la soumission Flathub.
- Toutes les archives Python et leurs empreintes doivent être déclarées comme sources : la
  construction Flathub n'a pas d'accès réseau.
- Dépendances Python directes : pypdf, pdfplumber, pdf2docx, PyMuPDF, openpyxl, Pillow,
  reportlab, arabic-reshaper, python-bidi et python-docx.

## Permissions envisagées

Objectif minimal après adaptation aux portails :

- affichage X11/XWayland pour Tkinter ;
- accès créé et limité au dossier Téléchargements ;
- ouverture de fichiers et d'URL via les portails du bureau ;
- aucun accès réseau pour le traitement des documents.

L'envoi facultatif de statistiques anonymes doit rester désactivé dans la variante Flatpak
si la permission réseau n'est pas déclarée. S'il est conservé, la permission réseau et sa
finalité devront être annoncées clairement sur la fiche Flathub.

## Adaptations nécessaires avant soumission

1. Remplacer les sélecteurs de fichiers Tkinter qui exigent un accès direct au système de
   fichiers par les portails FileChooser, ou justifier une permission plus large. Flathub
   exige l'usage des portails lorsqu'ils couvrent le besoin.
2. Vérifier les favoris vers Google Drive, NAS et dossiers personnels dans le bac à sable.
3. Utiliser le portail OpenURI pour ouvrir les PDF, dossiers et liens hypertextes.
4. Tester l’ouverture du navigateur pour le raccourci ChatGPT.
5. Désactiver proprement la détection de LibreOffice hôte : une application Flatpak ne peut
   pas exécuter directement le LibreOffice installé sur l'hôte. La conversion locale allégée
   restera disponible dans cette édition.
6. Fournir une traduction anglaise complète et relue de toute l'interface et des
   métadonnées.
7. Publier d'abord une version stable : Flathub n'accepte pas une première soumission
   directement comme bêta et sa branche stable n'est pas destinée aux versions alpha.

## Contrôles humains avant envoi

```text
flatpak-builder --force-clean build-dir <identifiant>.yml
flatpak-builder --user --install --force-clean build-dir <identifiant>.yml
flatpak run <identifiant>
flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest <identifiant>.yml
flatpak run --command=flatpak-builder-lint org.flatpak.Builder appstream <identifiant>.metainfo.xml
```

Tester au minimum : lancement, icône, PDF vers Office, création et export de document,
ouverture/enregistrement par portail, liens externes, microphone, données persistantes,
mise à jour et désinstallation.

## Soumission

- La demande doit viser la branche `new-pr` de `flathub/flathub`, jamais `master`.
- Le titre attendu est `Add io.github.preventionpaca.pdf-converter-lou-codi`.
- Le mainteneur humain doit déclarer honnêtement toute partie du programme ou du matériel de
  présentation qui a été produite ou substantiellement assistée par une IA.
- Ni un agent ni une automatisation IA ne doit ouvrir la demande, écrire sa description,
  ses commentaires de revue ou ses réponses.

## Points bloquants actuels

- la version préparée `2.0.0a6` est une alpha et non une version stable ;
- les portails de fichiers ne sont pas encore intégrés ;
- les captures propres et permanentes ne sont pas encore publiées ;
- le manifeste de soumission doit être écrit humainement ;
- l'identité publique et les coordonnées de support doivent être confirmées.
