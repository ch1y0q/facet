# Relier une photo manquante après un déplacement explicite

`python database.py --relink-photos` met à jour les chemins de la base Facet après un déplacement de fichiers que vous avez effectué vous-même. Il ne déplace, ne copie, ne supprime ni ne modifie jamais les originaux ou les fichiers annexes, et ne contacte jamais Immich. C’est une commande de maintenance hors ligne.

Avant d’appliquer un plan :

- Arrêtez le viewer, les scans et les éditeurs de fichiers externes.
- Sauvegardez la base de données.
- Examinez le plan.

L’application prend le verrou de la photothèque de Facet. Si un autre travail sur la photothèque est en cours, elle se termine avec le code 75 sans rien modifier ; un verrou inutilisable donne le code 1. L’aperçu est en lecture seule et ne prend aucun verrou. Ce verrou ne couvre que les travaux d’un seul hôte.

> **Avertissement :** Facet ne stocke aucune empreinte des octets du fichier original ; il ne peut donc pas prouver que le nouveau fichier est celui qui a été déplacé. Chaque plan indique `original_bytes_unknown` ; `phash` et les signatures de visages manuels ne prouvent pas l’identité. Le SHA-256 de la cible identifie seulement le fichier que vous avez prévisualisé. Appliquer revient à affirmer que vous avez vérifié la correspondance vous-même. Une affirmation erronée attache des annotations existantes à la mauvaise image.

Déplacer ou renommer un dossier entier n’est pas pris en charge lorsque l’ancien parent n’existe plus. Ne recréez pas de parents vides pour contourner ce contrôle.

## Prévisualiser, examiner, puis appliquer

Créez une liste JSON de chemins absolus canoniques exacts. Chaque source doit déjà être dans Facet. Chaque destination doit exister en tant qu’image et ne doit pas encore avoir de ligne photo :

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

En mode multi-utilisateur, ajoutez `--user alice` aux deux commandes. Cela sélectionne la portée à vérifier ; ce n’est pas un contrôle d’accès. Règles :

- Les deux chemins doivent être visibles pour cet utilisateur.
- L’ensemble de **tous** les utilisateurs pouvant voir la photo doit rester identique. Les déplacements d’un espace privé vers un espace partagé, ou tout autre déplacement entre utilisateurs, sont refusés.
- Les deux chemins doivent se trouver dans des dossiers de scan, d’utilisateur ou partagés explicitement configurés.
- Une configuration de racines vide, des racines inaccessibles et `viewer.path_mapping` sont refusés. Seuls les chemins natifs canoniques sont pris en charge.

L’application revérifie tout le plan dans une seule transaction de base de données. Si des fichiers cibles, des lignes de photos, des annotations, le schéma, le fichier de base ou la visibilité ont changé, lancez un nouvel aperçu. Un lot en échec annule toutes ses écritures en base. Une application réussie affiche un reçu contenant l’ID du plan.

## Ce qui suit la photo

Ces éléments conservent leur association avec la photo :

- ID de photos, notes, Keep et GPS
- tags, visages, ID de personnes et UUID de visages manuels
- comparaisons, scores appris et préférences par utilisateur
- remplacements, appartenances fixes aux albums, couvertures et choix clients
- instantanés d’extraction et vecteurs d’embedding
- valeurs de groupes de rafales, de doublons et de séquences

Les statistiques dérivées sont invalidées ; l’état d’entraînement est conservé.

Ce qui ne change pas :

- **L’historique d’annulation** conserve ses anciens chemins. Une entrée qui désigne l’ancien chemin peut ne plus apparaître ni pouvoir être annulée après la reliaison.
- **Les rectangles de visages manuels** sont conservés mais marqués `relink_unverified`. Ouvrez l’éditeur et enregistrez chaque rectangle par rapport au nouveau cadre avant qu’il puisse être exporté ou supprimer des détections.
- **Immich** : l’état d’envoi et d’attente reste tel quel ; aucune note, aucun album ni aucun UUID distant n’est relié. Vérifiez vous-même la correspondance distante avant de synchroniser.
- **L’historique des échecs de scan, les filtres des albums intelligents et les clés de groupes de séquences** ne sont pas réécrits.

## Accompagnants explicites et refus

Listez les accompagnants vous-même : l’outil ne peut pas trouver les fichiers RAW ou XMP disparus de l’ancien dossier. Types d’accompagnants :

| Type | Fichier |
|---|---|
| `sidecar_full` | `photo.ext.xmp` |
| `sidecar_basename` | `photo.xmp` |
| `sidecar_facet` | `photo.ext.facet.xmp` |
| `raw` | paire RAW de même dossier et même nom de base |

Ces règles vérifient la relation déclarée ; elles ne prouvent pas l’identité. Une photo RAW indexée exige sa propre entrée de premier niveau afin que ses annotations soient conservées. Les accompagnants existants sont hachés et laissés intacts. Une liste d’accompagnants vide ne prouve pas qu’il n’y en avait aucun.

Facet refuse :

- les fichiers annexes ou RAW non listés à la destination, y compris les paquets de repli Facet et les variantes de casse
- plusieurs RAW candidats ou une propriété XMP ambiguë, par ex. `IMG.CR2` + `IMG.CR2.jpg` + `IMG.CR2.xmp`, ou `IMG.CR2` + `IMG.CR2.facet.jpg` + `IMG.CR2.facet.xmp`, ainsi que les collisions de noms de base, de casse ou d’Unicode
- les copies dont l’ancien original est toujours présent
- les anciens parents manquants ou illisibles
- les destinations qui ont déjà des lignes de photo ou des lignes dépendantes
- les correspondances répétées, les contenus de photos ou inodes cibles en double
- les renommages limités à la casse ou à l’Unicode, les liens symboliques, et les changements d’extension ou de format
- une cible décodée dont les dimensions diffèrent de celles stockées, lorsqu’elles sont connues

Aucune recherche par similarité ou par nom de fichier n’est exécutée.

Limites par lot : 100 photos, 300 fichiers nommés, 512 MiB par fichier, 2 GiB au total, et 2 MiB pour le JSON d’entrée ou le plan. Scindez le lot si vous en atteignez une. L’écriture en base est atomique, mais d’autres applications peuvent encore toucher aux fichiers, d’où l’exigence d’exécution hors ligne.

> **Avertissement :** Un dossier lisible ne prouve pas que le stockage est monté. Un volume non monté peut ressembler à un dossier vide. Le plan indique `source_mount_status: not_verified` ; confirmez que chaque source a bien été déplacée avant de confirmer l’identité. La commande ne détecte pas toutes les situations de volume hors ligne.

Les fichiers de plan contiennent des chemins complets privés et la portée utilisateur. `--plan-out` les crée de façon exclusive avec le mode 0600 sous POSIX.

| Option | Rôle |
|---|---|
| `--db` | Base existante |
| `--config` | Configuration résolue |
| `--user` | Utilisateur configuré obligatoire en mode multi-utilisateur |
| `--mapping` | JSON des anciens/nouveaux chemins ; prévisualisation |
| `--plan-out` | Créer un plan privé sans écraser |
| `--apply-plan` | Appliquer un plan examiné |
| `--ack-plan` | Empreinte exacte du plan examiné |
| `--acknowledge-unverified-identity` | Confirmation explicite malgré les octets d’origine inconnus |
