# Relier une photo manquante après un déplacement explicite

`python database.py --relink-photos` met à jour les chemins déjà enregistrés dans la base Facet après un déplacement de fichiers que vous avez effectué vous-même. Il ne déplace, ne copie, ne supprime ni ne modifie jamais les originaux ou les fichiers annexes, et ne contacte jamais Immich. C’est une commande de maintenance hors ligne, destinée à l’opérateur qui a accès à la base de données et aux dossiers configurés. Arrêtez d’abord le viewer, les scans et les éditeurs de fichiers externes ; sauvegardez la base et examinez le plan avant de l’appliquer.

L’application conserve le verrou de maintenance de la photothèque de Facet pendant toute l’écriture en base. Un autre travail sur la photothèque entraîne le code de sortie 75 sans modifier ni la base ni les médias ; un verrou inutilisable entraîne le code 1. L’aperçu reste en lecture seule et ne prend aucun verrou. Ce verrou coordonne les travaux sur un seul hôte ; les exigences hors ligne restent valables pour les autres hôtes et les éditeurs externes.

La base existante ne contient aucune empreinte cryptographique des octets du fichier original. `phash` et les signatures en niveaux de gris des visages manuels ne prouvent pas l’identité octet par octet. Chaque plan indique donc `original_bytes_unknown`. Le SHA-256 de la cible identifie seulement le nouveau fichier qui a été prévisualisé. Appliquer revient à affirmer explicitement que vous avez identifié par ailleurs le bon fichier déplacé ; ce n’est jamais une correspondance vérifiée automatiquement. Une affirmation erronée peut attacher des annotations existantes à la mauvaise image.

Déplacer ou renommer un dossier entier sort de ce mode borné lorsque l’ancien parent n’existe plus. Un dossier manquant ne permet pas de distinguer un déplacement volontaire d’un stockage hors ligne. Ne recréez pas de parents vides pour contourner ce contrôle.

## Prévisualiser, examiner, puis appliquer

Créez une liste JSON de chemins absolus canoniques exacts. Une source manquante doit déjà être enregistrée dans Facet ; une destination doit exister en tant qu’image et ne doit pas encore avoir de ligne photo :

```json
[
  {
    "old": "/photos/before/portrait.jpg",
    "new": "/photos/after/portrait-renamed.jpg",
    "companions": [
      {
        "old": "/photos/before/portrait.jpg.xmp",
        "new": "/photos/after/portrait-renamed.jpg.xmp",
        "kind": "sidecar_full"
      }
    ]
  }
]
```

```sh
# Aperçu en lecture seule de la base ; crée un plan à examiner privé (0600) et exclusif.
python database.py --relink-photos --db library.db --config scoring_config.json \
  --mapping moved.json --plan-out relink-plan.json

# Examinez dans relink-plan.json chaque ancien/nouveau chemin, l’étiquette d’identité à octets inconnus, l’empreinte de la cible, les
# dimensions, les références, les accompagnants et la politique de visibilité.
# Remplacez REVIEWED_PLAN_ID par le plan_id exact de ce fichier après examen.
python database.py --relink-photos --db library.db --config scoring_config.json \
  --apply-plan relink-plan.json --ack-plan REVIEWED_PLAN_ID \
  --acknowledge-unverified-identity
```

Le mode multi-utilisateur exige aussi `--user alice` dans les deux commandes. C’est un sélecteur de portée pour l’opérateur, et non un remplacement du contrôle d’accès du système ni une API authentifiée. Les deux chemins doivent être visibles pour cet utilisateur, et l’ensemble de **tous** les utilisateurs pouvant voir la photo doit rester identique. Les déplacements d’un espace privé vers un espace partagé, ou tout autre déplacement entre utilisateurs, sont refusés. Les deux chemins doivent se trouver dans des dossiers de scan, d’utilisateur ou partagés explicitement configurés. Une configuration de racines vide, des racines inaccessibles et `viewer.path_mapping` sont refusés ; cet outil initial ne prend en charge que les chemins natifs canoniques.

L’application revérifie l’intégralité du plan examiné dans une seule transaction d’écriture SQLite. Des fichiers cibles, des lignes de photos, des annotations, un schéma, un inode de base ou une politique de visibilité modifiés exigent un nouvel aperçu. Un lot en échec annule toutes ses écritures en base. Une application réussie affiche un reçu contenant l’ID du plan. Aucun nouvel ID d’actif logique ni aucune correspondance d’UUID distant n’est enregistré.

## Ce qui suit la photo

Les rowids des photos, notes/Keep/GPS, tags, ID de visages/personnes et UUID manuels, comparaisons, scores appris, préférences par utilisateur, remplacements, appartenances fixes aux albums, couvertures et choix clients, instantanés d’extraction et vecteurs d’embedding conservent leurs associations. Les clés étrangères existantes vers photos sont découvertes à partir du schéma réel ; une nouvelle colonne de chemin non enregistrée est refusée plutôt qu’orpheline en silence. Les statistiques dérivées sont invalidées ; l’état d’entraînement durable est conservé.

Les entrées de l’historique d’organisation conservent leurs charges utiles de chemins historiques d’origine. Les déclencheurs existants sur les changements de chemin font avancer l’horloge de révision et invalident les caches de révision privés ; une entrée qui désigne l’ancien chemin peut ne plus apparaître ni pouvoir être annulée après la reliaison. La reliaison conserve les valeurs d’annotation et les associations actuelles, mais ne réécrit pas les actions passées pour les rendre applicables à un autre chemin.

Tous les rectangles manuels sont conservés mais exigent une révision sur le nouveau chemin. L’ancienne signature grossière ne peut pas prouver les pixels de l’original manquant. Un marqueur `relink_unverified` empêche les vérifications de signature ordinaires d’effacer cet état de révision ; ouvrez l’éditeur et enregistrez explicitement chaque rectangle par rapport au nouveau cadre avant qu’il puisse être exporté ou supprimer des détections. Les ID de rectangles et de personnes existants sont conservés.

L’état d’envoi/en attente d’Immich reste inchangé : une affirmation locale sur un nom de fichier ne peut pas vérifier une identité distante. Aucune note distante, aucun effacement, aucune appartenance à un album ni aucun UUID n’est relié. Examinez séparément la correspondance distante avant de synchroniser. Les chemins d’échecs de scan historiques restent historiques ; les prédicats de filtres des albums intelligents et les clés de groupes de séquences logiques ne sont pas réécrits en silence. Les appartenances statiques et les valeurs de groupes de séquences/rafales/doublons restent intactes.

## Accompagnants explicites et refus

Listez explicitement les accompagnants : l’outil ne peut pas découvrir les fichiers RAW/XMP non indexés disparus de l’ancien dossier. `sidecar_full` désigne `photo.ext.xmp`, `sidecar_basename` désigne `photo.xmp`, `sidecar_facet` désigne `photo.ext.facet.xmp`, et `raw` conserve une paire RAW de même dossier et même nom de base, fournie explicitement et compatible avec le tri actuel. Ces règles de noms valident une relation déclarée ; elles ne prouvent pas l’identité des fichiers. Les photos RAW indexées exigent leur propre entrée de reliaison de premier niveau afin que leurs annotations soient conservées.

Les fichiers annexes ou RAW non listés à la destination sont refusés, y compris les paquets de repli Facet et les variantes de casse. Les RAW multiples et les propriétés XMP ambiguës sont refusés, notamment `IMG.CR2` + `IMG.CR2.jpg` + `IMG.CR2.xmp`, `IMG.CR2` + `IMG.CR2.facet.jpg` + `IMG.CR2.facet.xmp`, ainsi que les collisions de noms de base et de casse/Unicode. Aucun accompagnant n’est attribué au premier résultat trouvé. Les octets des accompagnants existants sont hachés, revérifiés et laissés intacts. Les accompagnants manquants non listés restent inconnus ; ne considérez pas une liste vide comme la preuve qu’il n’y en avait aucun.

Sont refusés : les copies dont l’ancien original est toujours présent, les anciens parents manquants ou illisibles, les photos de destination ou lignes dépendantes déjà existantes, les correspondances répétées, les contenus de photos ou inodes cibles en double, les changements limités à la casse ou à l’Unicode, les liens symboliques et les changements d’extension ou de format. Lorsqu’elles sont connues, les dimensions canoniques stockées doivent correspondre à la cible décodée. Aucune recherche par similarité ou par nom de fichier, et aucune réconciliation automatique, n’est exécutée.

Limites : 100 photos, 300 fichiers explicitement nommés, 512 MiB par fichier, 2 GiB d’octets de fichiers au total et 2 MiB de JSON en entrée ou de plan à examiner. Réduisez le lot lorsqu’une limite est atteinte. La transaction de base est atomique ; le système de fichiers n’est pas verrouillé face aux autres applications, d’où l’exigence hors ligne. Aucun aller-retour avec une application externe réelle ou un serveur distant n’est revendiqué par les tests sur fixtures.

Des dossiers lisibles ne prouvent **pas** qu’un stockage est monté. Un volume non monté peut laisser un point de montage vide mais lisible, impossible à distinguer d’un dossier réellement vide après déplacement. Le plan indique explicitement `source_mount_status: not_verified` ; confirmez de façon indépendante que chaque source a été déplacée et non simplement rendue indisponible avant de confirmer l’identité. La commande ne détecte pas toutes les situations de volume hors ligne. Les plans à examiner contiennent des chemins complets privés et la politique de portée utilisateur ; `--plan-out` les crée de façon exclusive avec le mode 0600 sous POSIX.

| Option | Rôle |
|---|---|
| `--db` | Base existante |
| `--config` | Configuration résolue |
| `--user` | Utilisateur configuré obligatoire en mode multi-utilisateur |
| `--mapping` | JSON des anciens/nouveaux chemins ; prévisualisation |
| `--plan-out` | Créer un plan privé sans écraser |
| `--apply-plan` | Appliquer un plan examiné |
| `--ack-plan` | Empreinte exacte du plan examiné |
| `--acknowledge-unverified-identity` | Confirmation explicite malgré les octets d’origine inconnus |
