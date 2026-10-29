from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf"
LOGO = ROOT / "src" / "lou_codi_pdf_converter" / "assets" / "croix-lou-codi.png"

NAVY = colors.HexColor("#193B66")
BLUE = colors.HexColor("#2368AF")
PALE = colors.HexColor("#F0F4F9")
INK = colors.HexColor("#23384D")
GOLD = colors.HexColor("#F4B942")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="CoverTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=NAVY, alignment=TA_CENTER, spaceAfter=10))
styles.add(ParagraphStyle(name="CoverSub", parent=styles["Normal"], fontSize=12, leading=17, textColor=INK, alignment=TA_CENTER))
styles.add(ParagraphStyle(name="H1LC", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=NAVY, spaceBefore=8, spaceAfter=10))
styles.add(ParagraphStyle(name="H2LC", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=BLUE, spaceBefore=10, spaceAfter=6))
styles.add(ParagraphStyle(name="BodyLC", parent=styles["BodyText"], fontSize=10.3, leading=15, textColor=INK, spaceAfter=7))
styles.add(ParagraphStyle(name="NoteLC", parent=styles["BodyText"], fontSize=9.6, leading=14, textColor=INK, backColor=PALE, borderColor=BLUE, borderWidth=0.7, borderPadding=8, spaceBefore=7, spaceAfter=9))
styles.add(ParagraphStyle(name="FooterLC", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#65798D"), alignment=TA_CENTER))


def bullets(items: list[str]) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(item, styles["BodyLC"]), leftIndent=4) for item in items],
        bulletType="bullet",
        leftIndent=18,
        bulletColor=BLUE,
        spaceAfter=7,
    )


def steps(items: list[str]) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(item, styles["BodyLC"]), leftIndent=4) for item in items],
        bulletType="1",
        start="1",
        leftIndent=22,
        bulletColor=NAVY,
        spaceAfter=7,
    )


def page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D7E1EC"))
    canvas.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#65798D"))
    canvas.drawString(20 * mm, 10 * mm, "Lou Còdi Workshop · Mode d’emploi")
    canvas.drawRightString(190 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def cover(title: str, subtitle: str, version: str = "Édition 2026") -> list:
    logo = Image(str(LOGO), width=30 * mm, height=30 * mm)
    logo.hAlign = "CENTER"
    return [
        Spacer(1, 22 * mm),
        logo,
        Spacer(1, 8 * mm),
        Paragraph(title, styles["CoverTitle"]),
        Paragraph(subtitle, styles["CoverSub"]),
        Spacer(1, 13 * mm),
        Table(
            [[Paragraph(version, styles["BodyLC"]), Paragraph("loucodi.fr", styles["BodyLC"])]],
            colWidths=[65 * mm, 65 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("BOX", (0, 0), (-1, -1), 0.8, BLUE),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]),
        ),
        Spacer(1, 18 * mm),
        Paragraph("Un outil local, clair et modulaire pour produire, organiser et relier vos contenus.", styles["CoverSub"]),
        PageBreak(),
    ]


GUIDES = {
    "guide-lou-codi-workshop.pdf": {
        "title": "Lou Còdi Workshop",
        "subtitle": "Le principe général et la porte d’entrée vers tous les studios",
        "sections": [
            ("Le principe", ["Lou Còdi Workshop réunit dans une seule application des outils spécialisés. Chaque vignette ouvre un studio sans vous imposer un parcours unique.", "Les traitements principaux restent locaux : vos fichiers ne sont pas envoyés à un serveur Lou Còdi. Les services Google ne sont sollicités que lorsque vous choisissez une fonction Google."]),
            ("Les cinq espaces de travail", ["<b>PDF Studio</b> : convertir, regrouper, réordonner et habiller des PDF.", "<b>Document Studio</b> : créer et mettre en page des documents, dessins et schémas.", "<b>Optimisation de découpe</b> : placer des pièces et réduire les chutes.", "<b>Lou Còdi Code Lab</b> : apprendre et expérimenter le code.", "<b>Lou Còdi Espace</b> : relier fichiers, Drive, courriels, pages web et albums Photos."]),
            ("Démarrer", ["Ouvrez Workshop, choisissez la vignette correspondant à votre besoin puis utilisez <b>Aide</b> pour ouvrir le guide dédié.", "Le bouton <b>Contact</b> ouvre le formulaire officiel de loucodi.fr. Les modules grisés ne sont pas installés dans votre configuration."]),
            ("Repères utiles", ["Enregistrez vos projets dans un dossier sauvegardé.", "Vérifiez toujours le document final avant diffusion.", "Pour les comptes Google, l’autorisation est accordée par compte et conservée sur chaque ordinateur jusqu’à révocation."]),
        ],
    },
    "guide-pdf-studio.pdf": {
        "title": "PDF Studio",
        "subtitle": "Convertir, assembler, organiser et habiller des fichiers PDF",
        "sections": [
            ("Choisir le bon outil", ["<b>PDF vers Office</b> extrait le texte vers Word et les tableaux vers Excel.", "<b>Documents vers PDF</b> convertit des documents bureautiques et des images, seuls ou par lots.", "<b>Organiser les PDF</b> fusionne, extrait, réordonne ou fait pivoter des pages.", "<b>Habillage PDF</b> ajoute filigranes, en-têtes et pieds de page avec aperçu."]),
            ("Flux conseillé", ["Conservez l’original.", "Ajoutez les fichiers et placez-les dans l’ordre voulu.", "Choisissez un dossier de sortie explicite.", "Lancez le traitement puis contrôlez visuellement le PDF obtenu."]),
            ("À savoir", ["Une conversion PDF vers Office restitue la structure au mieux, mais un PDF n’est pas un fichier Word natif.", "Pour un lot important, testez d’abord deux ou trois fichiers représentatifs.", "Le contenu reste sur votre ordinateur pendant les opérations locales."]),
        ],
    },
    "guide-document-studio.pdf": {
        "title": "Document Studio",
        "subtitle": "Créer des documents, dessins, schémas et mises en page",
        "sections": [
            ("Ce que vous pouvez créer", ["Pages composées de texte, images, tableaux, liens, formes, masques et éléments de dessin.", "Documents multipages avec modèles, signature et export PDF.", "Annotations, mesures et schémas visuels adaptés à la formation ou au terrain."]),
            ("Méthode de travail", ["Créez ou ouvrez un projet <b>.loucodi-document</b>.", "Ajoutez les éléments, positionnez-les et contrôlez la hiérarchie visuelle.", "Enregistrez souvent le projet modifiable.", "Exportez en PDF, puis vérifiez toutes les pages avant envoi."]),
            ("Courriel et Google", ["L’envoi Google ouvre sa propre authentification : Lou Còdi ne connaît pas votre mot de passe.", "Vous pouvez choisir un compte personnel ou professionnel enregistré, puis sélectionner vos contacts et groupes.", "Le document exporté reste accessible indépendamment du projet source."]),
        ],
    },
    "guide-optimisation-decoupe.pdf": {
        "title": "Optimisation de découpe",
        "subtitle": "Placer les pièces, calculer les coupes et limiter les chutes",
        "sections": [
            ("Préparer le calcul", ["Indiquez les dimensions des plaques ou panneaux disponibles.", "Saisissez les pièces et leurs quantités.", "Réglez l’épaisseur du trait de coupe et autorisez ou non la rotation.", "Ajoutez les chutes réutilisables lorsque leur format est connu."]),
            ("Optimiser et contrôler", ["Lancez l’optimisation puis examinez chaque planche proposée.", "Contrôlez le sens matière, les marges de sécurité et les contraintes réelles de la machine.", "Utilisez le résultat comme plan de préparation : l’opérateur conserve la décision finale."]),
            ("Bonnes pratiques", ["Mesurez les stocks réels avant de valider.", "N’assimilez pas le trait de coupe à une marge de sécurité.", "Identifiez les chutes conservées pour un prochain calcul."]),
        ],
    },
    "guide-code-lab.pdf": {
        "title": "Lou Còdi Code Lab",
        "subtitle": "Comprendre, essayer et modifier Python, JavaScript, HTML, CSS et JSON",
        "sections": [
            ("Une zone d’expérimentation", ["L’éditeur propose plusieurs onglets, une coloration syntaxique et des exercices progressifs.", "Les modes assisté et autonome permettent de choisir le niveau d’accompagnement.", "Les ressources et quiz aident à comprendre un extrait avant de le transformer."]),
            ("Parcours conseillé", ["Choisissez un exercice ou ouvrez un fichier de code.", "Lisez l’objectif et repérez les zones à modifier.", "Procédez par petites étapes et enregistrez une copie.", "Testez le résultat dans un environnement adapté au langage."]),
            ("Prudence", ["Ne lancez pas un code dont vous ne comprenez pas l’origine ou les effets.", "Ne collez jamais de mot de passe, jeton ou donnée personnelle dans un exemple partagé.", "L’assistance peut expliquer ou proposer ; vous gardez la maîtrise de l’exécution."]),
        ],
    },
    "guide-codi-espace.pdf": {
        "title": "Lou Còdi Espace",
        "subtitle": "Rassembler fichiers, Drive, courriels, liens et albums Google Photos",
        "sections": [
            ("Le rôle d’un espace", ["Un espace représente une affaire, un projet, un examen ou un dossier de travail. Il conserve des liens et des repères sans dupliquer inutilement tous les contenus.", "Les fichiers déposés peuvent être envoyés vers le dossier Drive lié. Les courriels, pages web et albums Photos restent des liens ouvrables."]),
            ("Ajouter et classer", ["Déposez un fichier, un dossier ou une URL dans la fenêtre, utilisez le presse-papiers, ou capturez la page courante avec l’extension Chrome.", "Les icônes distinguent Gmail, Google Sheets, Google Docs, Drive, Photos, fichiers locaux et liens web.", "Ajoutez des tags, recherchez, triez les colonnes ou déplacez manuellement les lignes. Ctrl permet une sélection multiple."]),
            ("Installer l’extension sur un autre ordinateur", ["Copiez puis décompressez le dossier <b>Lou Còdi Capture</b> sur l’ordinateur.", "Dans Chrome, ouvrez <b>chrome://extensions</b>, activez <b>Mode développeur</b>, puis <b>Charger l’extension non empaquetée</b>.", "Sélectionnez le dossier décompressé contenant <b>manifest.json</b>, puis épinglez l’extension.", "Sous Linux, le petit service Lou Còdi Capture doit aussi fonctionner. La future distribution Linux l’installera automatiquement."]),
            ("Comptes, Photos et sauvegarde", ["Choisissez le compte Google associé à l’espace. Chaque ordinateur conserve ses propres autorisations.", "<b>Archiver l’album Photos</b> télécharge l’archive préparée par Google vers le dossier que vous choisissez, par exemple un dossier synchronisé avec un NAS.", "Un espace ne peut être supprimé que lorsqu’il est vide : retirez d’abord ses ressources et son lien Drive."]),
        ],
    },
    "guide-gcode-workshop.pdf": {
        "title": "G-code Workshop",
        "subtitle": "Préparer le futur module de lecture et de contrôle des programmes d’usinage",
        "sections": [
            ("État du module", ["G-code Workshop apparaît aujourd’hui comme un module à venir dans le lanceur. Il ne faut pas le confondre avec Lou Còdi Code Lab.", "Ce guide décrit le périmètre prévu. Les commandes seront documentées une par une dès que l’interface sera effectivement développée et testée."]),
            ("Fonctions envisagées", ["Ouvrir et visualiser un fichier G-code sans l’exécuter sur une machine.", "Repérer les déplacements rapides, avances, changements d’outil, origines et unités.", "Signaler les instructions inconnues ou potentiellement dangereuses.", "Simuler la trajectoire et produire une fiche de contrôle avant transfert."]),
            ("Sécurité", ["Aucun programme ne devra être envoyé automatiquement à une machine.", "La simulation logicielle ne remplacera jamais les limites, origines, bridages et contrôles physiques.", "Le post-processeur et le dialecte G-code devront être explicitement sélectionnés."]),
        ],
    },
}


BUTTON_REFERENCE = {
    "guide-lou-codi-workshop.pdf": [
        ("En-tête du Workshop", [
            ("Langue", "Change la langue de l’interface puis reconstruit l’écran d’accueil."),
            ("Aide", "Ouvre un menu regroupant les guides, l’enregistrement du logiciel, la confidentialité, les informations À propos et le contact."),
            ("Enregistrement du logiciel", "Enregistre gratuitement cette installation. Une même clé peut enregistrer jusqu’à trois ordinateurs."),
            ("Confidentialité", "Affiche et modifie le choix relatif aux mesures d’usage anonymes."),
            ("À propos", "Affiche la version, l’identité du logiciel et les informations essentielles."),
            ("Contact", "Ouvre le formulaire officiel de loucodi.fr."),
        ]),
        ("Vignettes", [
            ("Ouvrir le module", "Ouvre le studio correspondant dans la fenêtre de travail."),
            ("Aide", "Ouvre directement la rubrique du manuel correspondant à la vignette."),
            ("Contact", "Ouvre le formulaire officiel de loucodi.fr."),
            ("Module non installé", "Indique que le composant n’est pas présent dans cette distribution."),
            ("Découvrir le module", "Présente un module connu mais non accessible avec la configuration actuelle."),
        ]),
    ],
    "guide-pdf-studio.pdf": [
        ("Écran PDF Studio", [
            ("PDF vers Office", "Ouvre la conversion vers Word ou l’extraction des tableaux vers Excel."),
            ("Documents vers PDF", "Ouvre la conversion de documents et d’images en PDF."),
            ("Organiser les PDF", "Ouvre la fusion, l’extraction, la rotation et le réordonnancement des pages."),
            ("Habillage PDF", "Ouvre l’ajout de filigranes, en-têtes et pieds de page."),
        ]),
        ("PDF vers Office", [
            ("Ajouter des PDF…", "Ajoute un ou plusieurs PDF à la file de conversion."),
            ("Retirer", "Retire les fichiers sélectionnés de la file sans supprimer les originaux."),
            ("Tout effacer", "Vide la file de conversion."),
            ("Parcourir…", "Choisit le dossier qui recevra les fichiers convertis."),
            ("Convertir", "Lance la conversion avec le format et les options sélectionnés."),
            ("Ouvrir les résultats", "Ouvre le dossier contenant les fichiers produits."),
        ]),
        ("Documents vers PDF", [
            ("Ajouter des documents…", "Ajoute des documents bureautiques ou des images à convertir."),
            ("Retirer / Tout effacer", "Modifie la file d’attente sans toucher aux fichiers sources."),
            ("Parcourir…", "Choisit le dossier de sortie."),
            ("Créer le PDF", "Lance la conversion ou l’assemblage selon les options affichées."),
        ]),
        ("Organiser les PDF", [
            ("Ajouter des PDF…", "Importe toutes les pages des PDF sélectionnés."),
            ("Page blanche", "Insère une page vierge dans le montage."),
            ("Monter / Descendre", "Déplace la ou les pages sélectionnées dans l’ordre final."),
            ("Dupliquer", "Crée une copie des pages sélectionnées dans le montage."),
            ("Rotation 90°", "Fait pivoter les pages sélectionnées d’un quart de tour."),
            ("Supprimer", "Retire les pages du montage, sans modifier les PDF originaux."),
            ("Annuler / Rétablir", "Revient sur la dernière modification ou la réapplique."),
            ("Tout vider", "Efface le montage courant après confirmation éventuelle."),
            ("Parcourir…", "Choisit l’emplacement du nouveau PDF."),
            ("Créer le PDF", "Produit le PDF dans l’ordre affiché."),
            ("Ouvrir le résultat", "Ouvre le PDF final avec l’application du système."),
        ]),
        ("Habillage PDF", [
            ("Choisir un PDF…", "Sélectionne le document à décorer."),
            ("Choisir… / Parcourir…", "Sélectionne une image, une ressource ou le fichier de sortie selon la zone."),
            ("Actualiser l’aperçu", "Recalcule l’aperçu avec les réglages actuels."),
            ("Valider et exporter", "Applique l’habillage à toutes les pages concernées et crée un nouveau PDF."),
            ("Ouvrir le résultat", "Ouvre le fichier exporté."),
            ("Rotation droite / gauche", "Ajuste l’orientation de l’élément sélectionné."),
            ("− / + / Ajuster / Élargir", "Modifie le zoom ou le cadrage de l’aperçu."),
            ("Ajouter avec ces coordonnées", "Crée un élément aux coordonnées indiquées."),
            ("Mettre à jour", "Enregistre les modifications de l’élément sélectionné."),
            ("Supprimer", "Retire l’élément d’habillage sélectionné."),
        ]),
    ],
    "guide-document-studio.pdf": [
        ("Fichier et pages", [
            ("Nouveau / Ouvrir / Enregistrer / Enregistrer sous", "Crée, ouvre ou sauvegarde le projet modifiable .loucodi-document."),
            ("Exporter en PDF", "Produit un PDF indépendant du projet source."),
            ("Ajouter / Dupliquer / Supprimer une page", "Modifie la structure multipage du document."),
            ("Appliquer aux pages", "Étend un réglage aux pages choisies."),
            ("Page entière / Largeur de page", "Adapte le zoom de travail à la page ou à sa largeur."),
            ("− / +", "Réduit ou augmente le zoom."),
        ]),
        ("Insertion et contenu", [
            ("Texte / Image / Tableau / Forme / Lien", "Insère le type d’objet choisi sur la page active."),
            ("Modifier le contenu", "Édite le texte ou les propriétés principales de l’objet sélectionné."),
            ("Insérer dans la zone", "Place le contenu importé dans la zone définie."),
            ("Appliquer", "Valide les réglages du panneau courant."),
            ("Annuler", "Ferme le dialogue ou abandonne la modification en cours."),
        ]),
        ("Dessin technique et mesures", [
            ("Appliquer au triangle", "Applique les dimensions ou contraintes au triangle sélectionné."),
            ("Appliquer les coordonnées", "Positionne l’objet avec les valeurs numériques saisies."),
            ("Distance / orientation", "Mesure une distance et l’orientation entre deux points."),
            ("Cote avec lignes de rappel", "Crée une cote complète entre deux points."),
            ("Coter le cercle sélectionné", "Ajoute une cote de diamètre ou de rayon."),
            ("Calculer l’aire du contour", "Calcule la surface d’un contour fermé."),
            ("Angle intérieur", "Mesure l’angle défini par trois points."),
            ("Construire un triangle rectangle", "Construit un triangle à partir des mesures indiquées."),
            ("Étalonner l’échelle du plan", "Définit la correspondance entre distance affichée et distance réelle."),
        ]),
        ("Polices, courriel et impression", [
            ("Utiliser la police", "Applique la police sélectionnée."),
            ("Installer une police…", "Installe une police locale après validation."),
            ("Chercher une police proche", "Ouvre une recherche Google Fonts dans le navigateur."),
            ("+ Compte / Configurer Google", "Ajoute un compte Google ou ouvre sa configuration."),
            ("Contacts et groupes Google…", "Ouvre le sélecteur de destinataires."),
            ("Ajouter / Tout décocher / Retirer les décochés / Valider", "Compose et corrige la liste des destinataires."),
            ("Enregistrer ce courrier… / Supprimer", "Mémorise ou supprime un modèle de message."),
            ("Enregistrer cette signature…", "Mémorise la signature courante."),
            ("Enregistrer les réglages", "Conserve les préférences d’envoi."),
            ("Imprimer", "Ouvre le flux d’impression du document."),
        ]),
    ],
    "guide-optimisation-decoupe.pdf": [
        ("Stock matière", [
            ("Ajouter au stock", "Ajoute une plaque ou une chute avec ses dimensions et sa quantité."),
            ("Disponible", "Marque la matière comme utilisable pour le prochain calcul."),
            ("Utilisée", "Indique que la plaque a déjà été consommée."),
            ("Chute inutilisable", "Conserve la trace de la chute sans la proposer à l’optimiseur."),
            ("Vider mon magasin", "Efface la liste du stock après confirmation. Cette action ne supprime aucun fichier."),
        ]),
        ("Pièces et calcul", [
            ("Ajouter la pièce", "Ajoute la pièce, ses dimensions, sa quantité et ses options de rotation."),
            ("Retirer", "Retire les pièces sélectionnées de la demande."),
            ("Tout vider", "Vide la liste des pièces à placer."),
            ("Calculer le plan de découpe", "Lance l’optimisation avec le stock, le trait de coupe et les rotations autorisées."),
        ]),
        ("Lecture du résultat", [
            ("Planches", "Chaque vue correspond à une plaque utilisée par la solution."),
            ("Pièces colorées", "Les rectangles identifient les pièces, leur orientation et leur repère."),
            ("Chutes", "Les zones restantes permettent d’identifier les chutes potentiellement réutilisables."),
        ]),
    ],
    "guide-code-lab.pdf": [
        ("Navigation dans le parcours", [
            ("Précédente / Suivante", "Passe à l’étape précédente ou suivante de l’exercice."),
            ("Vérifier", "Contrôle la réponse ou le code selon les critères de l’exercice."),
            ("Afficher un indice", "Affiche une aide progressive sans remplacer la réflexion."),
            ("Ouvrir le parcours sélectionné", "Charge le parcours choisi dans la zone d’apprentissage."),
        ]),
        ("Assistance", [
            ("Générer un parcours avec ChatGPT", "Prépare une demande structurée pour produire un parcours pédagogique."),
            ("Importer la réponse", "Transforme la réponse obtenue en parcours utilisable dans Code Lab."),
            ("Vérifier ma réponse", "Compare la réponse saisie à l’objectif pédagogique."),
            ("Expliquer avec ChatGPT", "Prépare une demande d’explication du code ou de l’erreur sélectionnée."),
        ]),
        ("Éditeur", [
            ("Nouveau / Ouvrir / Enregistrer", "Gère les fichiers de code sans publier ni exécuter automatiquement leur contenu."),
            ("Onglets", "Permettent de travailler sur plusieurs fichiers ou exemples."),
            ("Langage", "Adapte la coloration et les repères à Python, JavaScript, HTML, CSS ou JSON."),
        ]),
    ],
    "guide-codi-espace.pdf": [
        ("Espaces et arborescence", [
            ("+ Nouvel espace", "Crée un espace de premier niveau."),
            ("+ Sous-espace", "Crée un niveau sous l’espace sélectionné, par exemple Personnel > Casa Rosa > Albums photo > Paramet."),
            ("Supprimer l’espace", "Supprime uniquement un espace vide, sans ressource, sans lien Drive et sans sous-espace."),
            ("Classer l’espace", "Replace l’espace à la racine d’un groupe Personnel, Professionnel ou personnalisé."),
            ("Glisser-déplacer dans l’arborescence", "Range un espace sous un autre espace ou dans un groupe, avec protection contre les cycles."),
        ]),
        ("Ajout et synchronisation", [
            ("+ Ajouter une ressource", "Ouvre le formulaire de création manuelle d’un lien, fichier ou dossier."),
            ("Ajouter le presse-papiers", "Analyse l’adresse ou le chemin actuellement copié."),
            ("Lier un dossier Drive", "Associe l’espace au dossier Google Drive indiqué."),
            ("Actualiser Drive", "Recharge la liste du dossier lié sans dupliquer les fichiers."),
            ("+ Compte", "Ajoute ou renouvelle l’autorisation d’un compte Google."),
        ]),
        ("Ressources", [
            ("Ouvrir", "Ouvre la ressource avec l’application ou le service approprié."),
            ("Modifier les tags", "Ajoute ou retire des mots-clés issus du dictionnaire partagé."),
            ("Renommer", "Change le titre affiché dans l’espace sans renommer l’original."),
            ("Actualiser les infos", "Tente de récupérer le titre et les correspondants depuis Google."),
            ("↑ / ↓", "Déplace la sélection dans l’ordre manuel."),
            ("Déplacer vers…", "Déplace une ou plusieurs ressources vers un autre espace sans ressaisie."),
            ("Clic droit > Déplacer", "Ouvre la même arborescence de destination depuis la liste."),
            ("Retirer de l’espace", "Retire le lien de l’espace sans supprimer le fichier ou le message d’origine."),
        ]),
        ("Albums Photos et NAS", [
            ("Dossier albums NAS", "Mémorise, pour cet espace et cet ordinateur, le dossier local ou synchronisé avec le NAS."),
            ("Archiver l’album Photos", "Ouvre l’album, repère le ZIP téléchargé puis l’extrait vers le dossier NAS mémorisé."),
            ("Parcourir ailleurs…", "Choisit un ZIP situé hors du dossier Téléchargements."),
            ("Utiliser cette archive", "Lance l’import sécurisé du ZIP sélectionné."),
            ("Manifeste", "Lou Còdi conserve la liste, les empreintes et les métadonnées lisibles des fichiers archivés."),
        ]),
        ("Recherche, tri et extension", [
            ("Rechercher", "Filtre les titres, tags et adresses de l’espace courant."),
            ("Dictionnaire des tags", "Filtre et réutilise les tags existants."),
            ("En-têtes de colonnes", "Trie par titre, correspondant, type, date, tags ou compte."),
            ("Extension Lou Còdi Capture", "Ajoute la page courante à l’espace choisi depuis Chrome."),
        ]),
    ],
    "guide-gcode-workshop.pdf": [
        ("Commandes prévues - non encore disponibles", [
            ("Ouvrir un G-code", "Chargera un fichier en lecture seule pour analyse."),
            ("Choisir le dialecte", "Sélectionnera explicitement la famille de commandes attendue."),
            ("Analyser", "Relèvera unités, origines, vitesses, outils et instructions inconnues."),
            ("Simuler", "Affichera la trajectoire sans envoyer de commande à une machine."),
            ("Rapport de contrôle", "Produira une fiche de vérification avant utilisation en atelier."),
        ]),
    ],
}


def build(filename: str, data: dict) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT / filename),
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=22 * mm,
        title=data["title"],
        author="Lou Còdi",
        subject="Mode d’emploi Lou Còdi Workshop",
    )
    story = cover(data["title"], data["subtitle"])
    story.append(Paragraph("Mode d’emploi", styles["H1LC"]))
    for heading, paragraphs in data["sections"]:
        block = [Paragraph(heading, styles["H2LC"])]
        if heading in {"Flux conseillé", "Méthode de travail", "Parcours conseillé", "Installer l’extension sur un autre ordinateur"}:
            block.append(steps(paragraphs))
        elif len(paragraphs) >= 3:
            block.append(bullets(paragraphs))
        else:
            block.extend(Paragraph(text, styles["BodyLC"]) for text in paragraphs)
        story.append(KeepTogether(block))
    references = BUTTON_REFERENCE.get(filename, [])
    if references:
        story.append(PageBreak())
        story.append(Paragraph("Référence détaillée des boutons et actions", styles["H1LC"]))
        story.append(Paragraph("Les libellés peuvent varier légèrement selon le système ou la version, mais l’action décrite reste la même.", styles["NoteLC"]))
        for heading, rows in references:
            story.append(Paragraph(heading, styles["H2LC"]))
            table_data = [
                [Paragraph("Bouton ou action", styles["BodyLC"]), Paragraph("Effet détaillé", styles["BodyLC"])]
            ]
            table_data.extend([
                [Paragraph(f"<b>{label}</b>", styles["BodyLC"]), Paragraph(description, styles["BodyLC"])]
                for label, description in rows
            ])
            story.append(Table(
                table_data,
                colWidths=[49 * mm, 111 * mm],
                repeatRows=1,
                splitByRow=1,
                style=TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B9C8D8")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]),
            ))
            story.append(Spacer(1, 4 * mm))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Besoin d’aide ? Consultez <link href='https://loucodi.fr/mode-emploi.html' color='#2368AF'>loucodi.fr/mode-emploi.html</link> ou utilisez le bouton Contact du Workshop.", styles["NoteLC"]))
    doc.build(story, onFirstPage=page, onLaterPages=page)


if __name__ == "__main__":
    for name, guide in GUIDES.items():
        build(name, guide)
    print(f"{len(GUIDES)} guides créés dans {OUTPUT}")
