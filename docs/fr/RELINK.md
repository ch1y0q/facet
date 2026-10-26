# Relier une photo déplacée

`python database.py --relink-photos` modifie uniquement les chemins de photos déjà indexées après un déplacement manuel. Arrêtez viewer, scans et éditeurs externes ; sauvegardez la base. Aucun fichier original ou annexe n’est déplacé, écrit ou supprimé, et Immich n’est jamais contacté.

L’application conserve le verrou de maintenance de Facet pendant toute l’écriture en base. Un autre travail sur la photothèque entraîne le code 75 sans modifier la base ni les médias ; un verrou inutilisable entraîne le code 1. L’aperçu reste en lecture seule et ne prend aucun verrou. Ce verrou coordonne les travaux sur un seul hôte ; les conditions hors ligne restent nécessaires pour les autres hôtes et éditeurs externes.

La base ne prouve pas l’identité octet par octet de l’original absent : chaque plan indique `original_bytes_unknown`. SHA-256 identifie seulement la nouvelle cible examinée. Vérifiez vous-même l’identité avant les deux confirmations ; une mauvaise correspondance peut attacher les annotations à une autre image.

Les chemins doivent être absolus, natifs et canoniques, sans lien symbolique, dans les racines configurées. L’ancien fichier doit manquer mais son parent doit exister et être lisible. Un dossier entier disparu est refusé : il pourrait être hors ligne. Ne recréez pas un parent vide pour contourner ce contrôle. Un dossier lisible ne prouve pas le montage ; `source_mount_status=not_verified` exige une vérification indépendante.

La prévisualisation lit la base sans écrire, puis le plan enregistré doit être examiné. L’application revérifie fichiers, empreintes, dimensions connues, annotations, schéma, inode de base et politique dans une transaction SQLite ; tout conflit annule le lot. Le système de fichiers n’est pas verrouillé, d’où l’arrêt des autres processus. Le plan est créé exclusivement en mode0600 POSIX et contient des chemins privés.

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
python database.py --relink-photos --db library.db --config scoring_config.json \
  --mapping moved.json --plan-out relink-plan.json
python database.py --relink-photos --db library.db --config scoring_config.json \
  --apply-plan relink-plan.json --ack-plan REVIEWED_PLAN_ID \
  --acknowledge-unverified-identity
```

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

Les identifiants de lignes, notes/Keep/GPS, tags, visages/personnes, UUID manuels, comparaisons, préférences, albums fixes et vecteurs conservent leurs liens. Tous les rectangles manuels demandent une révision et un enregistrement explicites dans l’éditeur. Les actions historiques gardent leurs anciens chemins et peuvent ne plus être réversibles ; les révisions privées sont invalidées. Filtres d’albums intelligents, clés de groupes logiques, journaux historiques et état Immich ne sont pas réécrits.

Déclarez les accompagnants avec ancien/nouveau chemin et `kind` : `sidecar_full` pour `photo.ext.xmp`, `sidecar_basename` pour `photo.xmp`, `sidecar_facet` pour `photo.ext.facet.xmp`, `raw` pour un RAW non indexé de même nom de base. Un RAW indexé exige sa propre entrée principale ; RAW et JPEG indexés se déplacent ensemble dans le même plan. Les octets des accompagnants restent inchangés. Les accompagnants disparus inconnus ne peuvent pas être découverts.

Le mode multi-utilisateur exige `--user` et une visibilité identique pour tous les utilisateurs avant/après. Racines vides/inaccessibles et path_mapping sont refusés, comme copies avec source présente, destination déjà indexée, fichiers/inodes dupliqués, ambiguïtés casse/Unicode/double extension, RAW multiples, annexes non déclarées et changements de format. Limites :100 photos,300 fichiers,512MiB par fichier,2GiB au total,2MiB de JSON. Réduisez le lot si nécessaire.
