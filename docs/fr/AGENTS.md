# Agents IA (MCP)

> 🌐 [English](../AGENTS.md) · **Français** · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · [Português](../pt/AGENTS.md) · [简体中文](../zh/AGENTS.md)

Facet peut jouer le rôle de serveur [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) : un assistant IA comme Claude Code peut ainsi rechercher et inspecter votre bibliothèque avec les mêmes filtres que la galerie. Il expose neuf outils de lecture qui ne modifient rien dans votre bibliothèque et neuf outils `ui_*` qui pilotent l'onglet du navigateur que vous avez déjà ouvert (page, filtres, sélection) et n'écrivent jamais de données de la bibliothèque. Les jetons qui y sont autorisés peuvent aussi [modifier des éléments](#modifier-la-bibliothèque) (notes, indicateurs, étiquettes, albums, tri et suppression) et piloter la [chambre noire](#chambre-noire-groupes-de-tri).

## L'activer

Le point d'accès est **désactivé par défaut**. Mettez `viewer.mcp.enabled` à `true` dans `scoring_config.json` (voir [Point d'accès agent (MCP)](CONFIGURATION.md#point-daccès-agent-mcp)), puis redémarrez la visionneuse ou rechargez la configuration. Tant qu'il est désactivé, `/mcp` et toutes les routes `/api/mcp/*` répondent 404. Sans `viewer.password`, l'installation est considérée comme ouverte, même si `viewer.edition_password` est défini : ses jetons ne peuvent être que `readonly`.

Le point d'accès est `POST /mcp` sur le port de la visionneuse : HTTP diffusable (Streamable HTTP), sans état, réponses JSON simples. `GET` répond 405. Seul le pont d'onglet, `/api/mcp/bridge`, est un WebSocket ; voir [Piloter votre onglet ouvert](#piloter-votre-onglet-ouvert).

## Créer un jeton

Le plus simple passe par le navigateur. Avec `viewer.mcp.enabled` activé, ouvrez le menu du compte et choisissez **Connecter un assistant**. Sous **Créer un jeton**, saisissez un **Nom** et choisissez **Ce que l'assistant peut faire** : **Lecture et pilotage uniquement**, plus **Agir à ma place** ou **Édition complète** si votre session détient ce niveau (un jeton ne peut pas dépasser la session qui le crée). Cliquez sur **Créer le jeton** : le jeton n'apparaît qu'une fois sous **Votre nouveau jeton**, copiez-le donc tout de suite. **Jetons d'accès** liste vos jetons avec leur dernière utilisation et permet d'en révoquer un. **Ajouter à Claude Code** affiche la commande Claude Code prête à coller (voir plus bas), et **Cet onglet** indique si cet onglet est connecté, donc pilotable par les assistants. La liste des niveaux se limite à ce que le serveur accordera : une installation ouverte ne propose que **Lecture et pilotage uniquement**, **Agir à ma place** n'apparaît que sur les installations multi-utilisateurs et **Édition complète** seulement dans une session d'édition. Après la création, la boîte indique le niveau réellement accordé (« Accès accordé : {level} »).

Alternative par script (curl) :

Un assistant s'authentifie avec un jeton personnel commençant par `fct_`. Créez-en un avec une requête authentifiée (le jeton n'est renvoyé qu'**une seule fois** ; Facet ne conserve que son empreinte SHA-256) :

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "claude-code", "level": "readonly"}'
```

La réponse contient le jeton en clair dans `token`. `GET /api/mcp/tokens` liste vos jetons (jamais le secret) et `DELETE /api/mcp/tokens/{id}` en révoque un. Un superadmin peut lister les jetons de tous les propriétaires avec `?all=1` et en révoquer n'importe lequel. Chaque propriétaire peut détenir au plus 20 jetons actifs (412 au-delà). Ces routes refusent (403) les identifiants d'un agent : un assistant ne peut donc jamais créer, lister ni révoquer de jetons.

## Connecter Claude Code

```bash
claude mcp add --transport http facet http://localhost:5000/mcp --header "Authorization: Bearer fct_YOUR_TOKEN"
```

Les outils apparaissent ensuite sous les noms `mcp__facet__search_photos`, etc. Utilisez HTTPS dès que la visionneuse est accessible au-delà de votre machine, car le jeton transite dans un en-tête à chaque appel.

## Niveaux d'autorisation

Un jeton est créé avec un niveau accordé : `readonly`, `user` ou `edition`. Le niveau **effectif** est recalculé à chaque appel : c'est le plus bas entre le niveau du jeton et le niveau actuel de son propriétaire :

- Installations à mot de passe unique : `user` est ramené à `readonly` à la création, car ce mode n'a pas de niveau intermédiaire. Un jeton `edition` exige une session d'édition et ne fonctionne que tant que le mot de passe d'édition ne change pas.
- Installations multi-utilisateurs : le jeton `edition` d'un utilisateur rétrogradé passe à `user` ; une promotion n'élève jamais un jeton au-dessus de son niveau accordé.
- Installations ouvertes (aucun `viewer.password`, même si `viewer.edition_password` est défini) : les jetons sont toujours `readonly` et appartiennent à un propriétaire partagé `_anonymous`.
- Les installations à mot de passe unique n'ont pas de niveau `user` : le niveau effectif est `edition` ou `readonly`, donc les outils marqués `user` dans [Modifier la bibliothèque](#modifier-la-bibliothèque) exigent aussi un jeton `edition`. Un outil `user` appelé avec un jeton de niveau inférieur répond `forbidden_level` en précisant qu'il exige `edition`.
- Chaque outil a son propre niveau minimal, vérifié avant toute lecture ou écriture ; un jeton plus bas reçoit `forbidden_level`.

Un jeton devient invalide dès que les identifiants de son propriétaire changent : mot de passe de la visionneuse ou d'édition en mode mot de passe unique, mot de passe du propriétaire en mode multi-utilisateur, ou suppression de son compte. Il reçoit alors une réponse 401 à l'entrée.

## Outils

Les neuf outils de données sont en lecture seule :

| Outil | Rôle |
|------|--------------|
| `search_photos` | Filtre et trie la bibliothèque comme la galerie, en appliquant les masquages par défaut de la visionneuse sauf si le filtre les précise (renvoie `hidden_summary`) |
| `semantic_search` | Trouve des photos par le sens, ou par les mots des légendes avec `scope: "text"` |
| `get_photo` | Détail complet d'une photo à partir de son chemin (sans l'histogramme) |
| `similar_photos` | Photos similaires à une photo, par plongement visuel ou par couleur |
| `filter_options` | Le vocabulaire accepté par un filtre : appareils, objectifs, étiquettes, personnes, motifs, catégories, moments narratifs, types d'indésirables, plages de métriques |
| `list_persons` | Personnes reconnues, filtrables par nom |
| `list_albums` | Albums visibles par le propriétaire du jeton |
| `library_stats` | Taille de la bibliothèque, décomptes par type et aperçu des scores |
| `status` | Identité du jeton, son niveau effectif et les réglages du serveur et les onglets ouverts qu'il peut piloter |

Dans tout objet de filtres, `show_rejected` est un booléen : `true` ne liste que les photos rejetées, `false` ou son absence donne la liste normale.

## Piloter votre onglet ouvert

En plus des outils de données, le serveur liste toujours neuf outils `ui_*` qui agissent sur l'onglet Facet que vous avez ouvert dans un navigateur : ils changent de page, modifient les filtres ou la sélection et relisent ce que vous voyez. Ils n'écrivent jamais de données de la bibliothèque, un jeton `readonly` suffit donc.

| Outil | Ce qu'il fait |
|-------|---------------|
| `ui_navigate` | Aller à une page (galerie, personnes, albums, statistiques, ...) |
| `ui_set_gallery_filters` | Fusionner un correctif dans les filtres et le tri de la galerie (`null` retire un filtre, `replace: true` repart de zéro) |
| `ui_get_gallery_view` | Route, filtres actifs, total des résultats, premiers chemins de photos visibles et nombre de photos sélectionnées |
| `ui_open_photo` | Ouvrir une photo |
| `ui_select_photos` | Sélectionner des `paths` explicites, ou toute la vue filtrée avec `select_view: true`, en mode `replace`, `add` ou `remove` |
| `ui_clear_selection` | Vider la sélection |
| `ui_get_selection` | Le `scope` (`paths` ou `view`) et le `count`, avec les `paths` ou, pour une vue, les `filters` et `excluded_paths` |
| `ui_next_page` | Charger la page suivante de la galerie |
| `ui_show_culling_group` | Ouvrir la chambre noire sur un groupe, identifié par `(type, group_id)` (comptes édition) |

Fonctionnement :

- Tant que vous êtes connecté et que `viewer.mcp.enabled` et `viewer.mcp.bridge` valent `true`, chaque onglet Facet ouvre un WebSocket de même origine vers `/api/mcp/bridge` et s'authentifie avec votre session dans son premier message. Le pont est actif par défaut ; mettez `viewer.mcp.bridge` à `false` pour le désactiver, et les outils `ui_*` répondent alors par une erreur explicite.
- Un outil n'atteint que les onglets du propriétaire du jeton. Avec un mot de passe unique, toutes les sessions forment le même utilisateur ; sur une installation ouverte, chaque onglet appartient à l'utilisateur partagé `_anonymous`, y compris les connexions en mode édition.
- Chaque onglet porte le niveau de la session qui l'a ouvert, et un jeton ne pilote que les onglets de niveau égal ou supérieur au sien : un jeton `edition` n'utilise jamais un onglet connecté avec une simple session de consultation, alors qu'un jeton `readonly` peut piloter un onglet `edition`. Avec un mot de passe unique, un jeton est aussi borné par la session qui l'a créé : un jeton créé depuis une session de consultation ne pilote que les onglets de consultation, jamais l'onglet d'édition (un jeton antérieur à cette règle est borné à son propre niveau). Un onglet ne peut être remplacé que par un onglet de niveau égal ou supérieur : une session de consultation qui réutilise le `tab_id` d'un onglet d'édition est refusée avec 4409, et au-delà du plafond d'onglets par utilisateur, l'onglet de plus bas niveau part en premier. `status` ne liste que les onglets que le jeton peut piloter. `status` indique aussi `out_of_reach_tabs`, le nombre d'onglets ouverts que ce jeton ne peut pas piloter.
- Si plusieurs onglets sont ouverts, le dernier à avoir eu le focus est utilisé et le champ `tab` du résultat l'indique. Passez `tab_id` (listé par `status`) pour en choisir un autre.
- Un onglet refuse ce que son compte n'a pas le droit de faire (par exemple `/culling` pour un compte sans édition) et l'outil renvoie ce refus.
- Ce qu'un onglet renvoie n'est pas fiable : la profondeur, la longueur des chaînes et des listes sont bornées, et le tout est plafonné par `max_bytes`.
- Erreurs : `no_tab` (aucun onglet connecté, ou pont désactivé), `tab_timeout` (pas de réponse sous `call_timeout_s`) et `tab_outdated` (l'onglet ouvert ne connaît pas l'outil ; rechargez la page après une mise à jour de Facet).
- Le pont accepte d'abord la WebSocket puis la refuse par un code de fermeture et non par un statut HTTP : 4404 quand le point d'accès ou le pont est désactivé (l'onglet reste alors déconnecté jusqu'au rechargement de la page), 4403 quand l'en-tête `Origin` est absent ou non autorisé, 4401 pour une session absente ou rejetée.
- Un proxy inverse doit transmettre la mise à niveau WebSocket pour `/api/mcp/bridge` ; voir [Déploiement](DEPLOYMENT.md). S'il réécrit l'en-tête `Host`, indiquez l'origine publique dans `viewer.mcp.allowed_origins` (par exemple `["https://photos.example.com"]`), car l'origine de la page doit correspondre à l'hôte ou figurer dans la liste.
- Le registre des onglets est propre à chaque processus : le pont exige un seul worker (la valeur par défaut).

En complément :

- `ui_set_gallery_filters` vous amène d'abord à la galerie si une autre page est ouverte, puis applique le patch. Il refuse en bloc (`invalid_input`) un patch qui nomme un filtre que l'onglet ne sait pas piloter ; utilisez `search_photos` pour ceux-là.
- `ui_get_gallery_view`, `ui_next_page` et `ui_select_photos` avec `select_view` exigent que la galerie (ou un album) soit la page ouverte, sinon ils répondent `no_active_view` ; appelez d'abord `ui_navigate` vers `/`. Donnez à `ui_select_photos` exactement l'un de `paths` et `select_view`.
- `no_tab` signifie aussi qu'aucun onglet Facet n'est ouvert : ouvrez Facet dans un navigateur et connectez-vous. **Cet onglet** dans la boîte **Connecter un assistant** affiche l'état de la connexion, avec l'identifiant de l'onglet.
- Un onglet cesse de se reconnecter dès que sa session est rejetée (reconnectez-vous), et attend votre retour sur lui lorsqu'un autre de vos onglets a pris la place.
- Le pont d'onglet ne se connecte que si le serveur le déclare disponible (le point d'accès est activé et `viewer.mcp.bridge` vaut true) ; pont désactivé, les onglets ne se connectent pas du tout.
- `ui_set_gallery_filters` refuse un nom de filtre inconnu avec `invalid_input`, ainsi qu'un patch donnant à la fois `category` et `type`, ou à la fois `person` et `person_id`. Il ne propose que les filtres que la galerie sait afficher ; utilisez `search_photos` pour les autres.
- `ui_navigate` n'ouvre que les pages statiques de l'application : la page de connexion, les pages partagées, les URL externes et les chemins inconnus sont refusés (`invalid_input`), et les pages réservées à l'édition sont refusées à une session sans édition.
- `ui_select_photos` en mode `remove` sous une sélection de toute la vue ignore les chemins hors de la vue chargée et les liste dans `not_in_view` dans le résultat.

## WebMCP dans la page (agents du navigateur)

Indépendamment du point d'accès `/mcp`, un onglet connecté propose aussi les mêmes outils `ui_*` aux agents qui vivent dans le navigateur lui-même, via l'API W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) (`document.modelContext`). Un assistant natif du navigateur voit donc exactement les outils listés plus haut, les exécute dans l'onglet que vous regardez et n'a besoin d'aucun jeton.

- **Contexte sécurisé uniquement.** Facet n'enregistre les outils qu'en HTTPS ou sur `localhost`. En HTTP simple ils ne sont pas proposés et la boîte **Connecter un assistant** le signale ; la connexion par jeton ci-dessus continue de fonctionner.
- Enregistrés quand `viewer.mcp.enabled` vaut true et que vous êtes connecté, retirés à la déconnexion.
- L'objet est `document.modelContext` (l'ancien alias `navigator.modelContext` n'est pas fourni). C'est un polyfill, installé seulement si le navigateur n'en a pas de natif, et il ne peut pas être désinstallé : il peut exister avant votre connexion sans aucun outil Facet, et reste après la déconnexion avec une liste d'outils vide.
- Les outils font les mêmes choses, bornées par le même niveau de compte, que dans le tableau ci-dessus.

## Modifier la bibliothèque

Les outils d'écriture figurent à côté des outils de lecture dans la même liste `/mcp`. Chacun passe par les routes `/api` de la visionneuse, de sorte que les protections de la route s'appliquent toujours, et chacun est décompté du budget `write_rate_per_min`. Le niveau est le plus bas niveau effectif autorisé à appeler l'outil (voir [Niveaux d'autorisation](#niveaux-dautorisation)).

| Outil | Niveau | Ce qu'il fait | Plafonds |
|-------|--------|---------------|----------|
| `set_rating` | `user` | Définit la note en étoiles (0-5) de photos | 50 chemins |
| `set_favorite` | `user` | Marque ou démarque des photos comme favorites (marquer retire le rejet) | 50 chemins |
| `set_rejected` | `user` | Rejette ou annule le rejet de photos (rejeter retire la note et le favori) | 50 chemins |
| `batch_set_rating` | `edition` | Définit la note de nombreuses photos | 1000 chemins, ou `filters` |
| `batch_set_favorite` | `edition` | Marque de nombreuses photos comme favorites | 1000 chemins, ou `filters` |
| `batch_set_rejected` | `edition` | Rejette de nombreuses photos | 1000 chemins, ou `filters` |
| `add_tags` | `edition` | Ajoute des étiquettes manuelles (séparées des étiquettes IA) | 10 étiquettes ; 1000 chemins, ou `filters` |
| `remove_tags` | `edition` | Retire des étiquettes manuelles | 10 étiquettes ; 1000 chemins, ou `filters` |
| `create_album` | `edition` | Crée un album vide (non idempotent : deux appels, deux albums) | |
| `album_add_photos` | `edition` | Ajoute des photos à un album (celles déjà présentes sont ignorées) | 1000 chemins |
| `album_remove_photos` | `edition` | Retire des photos d'un album ; les photos ne sont pas touchées | 1000 chemins |
| `junk_list` | `readonly` | Liste les candidates du tri des ratés, éventuellement d'un seul `kind` | 100 par page |
| `junk_reject` | `edition` | Rejette les candidates du tri des ratés (comme `batch_set_rejected`) | 1000 chemins |
| `junk_clear` | `edition` | Conserve des candidates : les marque comme évaluées et saines pour qu'elles quittent la file | 50 chemins |
| `cull_apply` | `edition` | Copie les photos à conserver, ou déplace ou met à la corbeille les rejetées ([aperçu puis confirmation](#actions-destructives--aperçu-puis-confirmation)) | 10000 chemins, ou `filters` |
| `delete_photos` | `edition` | Met les fichiers à la corbeille et supprime leurs lignes de la bibliothèque ([aperçu puis confirmation](#actions-destructives--aperçu-puis-confirmation)) | 1000 chemins |

- **Les outils `user` exigent un jeton d'édition sur une installation à mot de passe unique**, qui n'a pas de niveau intermédiaire (voir [Niveaux d'autorisation](#niveaux-dautorisation)).
- **Sémantique d'affectation.** Les outils par photo lisent l'état actuel et n'écrivent qu'une différence, donc répéter un appel est sans danger ; chaque chemin indique `changed` ou `already`. Ils traitent un chemin à la fois et s'arrêtent au premier `library_busy`, `outcome_unknown` ou `forbidden_level`, en rapportant `affected`, les `results` par chemin et `not_attempted`. Les outils par lot appliquent le même état.
- **Choisir les photos.** Les outils par lot, d'étiquettes et `cull_apply` prennent SOIT `paths` SOIT `filters` (l'objet de filtres de `search_photos`), plus une liste `exclude` facultative. Une cible `filters` doit s'accompagner de `expected_count`, le nombre de correspondances des filtres avant application de `exclude` (le `total` de `search_photos`). Facet recompte d'abord les filtres et n'écrit rien si les nombres diffèrent (`invalid_input`, avec `actual_count`).
- **À qui appartient l'état.** Les notes, favoris et rejets sont ceux du propriétaire du jeton.
- **Fichiers ignorés.** Quand `cull_apply` ou `delete_photos` renvoie une liste `skipped` non vide, le résultat contient aussi un `skipped_reason` : ces chemins de la bibliothèque n'ont aucun fichier lisible sur le disque (manquant, déplacé ou hors des répertoires analysés) et rien n'a été fait pour eux.

### Actions destructives : aperçu puis confirmation

`cull_apply` (`copy_keeps`, `move_rejects`, `trash_rejects`) et `delete_photos` portent l'indicateur `destructiveHint` et s'exécutent en simulation sauf appel avec `dry_run: false`.

1. La simulation ne modifie rien et liste les fichiers qu'elle copierait, déplacerait ou mettrait à la corbeille (les longues listes sont tronquées à `max_rows`, avec un `<key>_count`). Pour `move_rejects`, `trash_rejects` et `delete_photos`, elle renvoie aussi une valeur `confirm`, valable `confirm_expires_in_s` (5 minutes) et pour un seul usage.
2. L'appel réel (`dry_run: false`) doit transmettre ce `confirm`. Facet recalcule l'ensemble de fichiers et les options et les compare à ceux pour lesquels la valeur a été émise. Si quelque chose a changé, la valeur est annulée et l'appel répond `confirmation_required` : refaites une simulation.
3. `copy_keeps` n'a pas besoin de `confirm` : il n'écrit que des copies. Il commence quand même par une simulation par défaut.

La valeur `confirm` est liée au jeton, à l'action et à l'ensemble exact de fichiers plus les options. Elle vit en mémoire dans un seul processus : un redémarrage supprime toutes les valeurs en attente.

**Pratique recommandée :** montrez toujours à l'utilisateur le résumé de la simulation (nombres et liste de fichiers) et obtenez son accord explicite avant l'appel `dry_run: false`. Ne confirmez jamais de votre propre initiative.

- `move_rejects` et `trash_rejects` n'agissent que sur les photos que le propriétaire a rejetées ; les autres sont signalées comme `excluded_by_state`. Les fichiers RAW et `.xmp` compagnons (`include_companions`) et les autres images d'un bracketing ou d'un panorama (`include_sequence_siblings`) ne sont pas touchés sauf si vous l'activez.
- `delete_photos` envoie les fichiers à la corbeille du système et **supprime leurs lignes de la bibliothèque** : les scores, étiquettes et notes ne sont pas récupérables, même si les fichiers le sont.
- **Prérequis.** `trash_rejects` et `delete_photos` exigent `viewer.cull.allow_trash` à `true` (par défaut `false` ; l'appel est refusé sinon). Le `target_dir` de `copy_keeps` et `move_rejects` doit se trouver dans un emplacement d'export autorisé : `viewer.export.allowed_target_dirs` plus vos répertoires d'analyse (voir [Destinations d'export et de tri](CONFIGURATION.md#destinations-dexport-et-de-tri)).

## Chambre noire (groupes de tri)

Les outils de la chambre noire reprennent la page `/culling`. Tous exigent le niveau `edition`, y compris ceux qui ne font que lister.

| Outil | Ce qu'il fait |
|-------|---------------|
| `list_culling_groups` | Liste les groupes (`burst`, `similar`, `scene`, `bracket`, `panorama`, `hdr_panorama`) avec leurs photos et scores, triables et limités par album ou plage de dates |
| `culling_profiles` | Les préréglages de tri adaptés au genre et celui par défaut |
| `suggest_culling_profile` | Nomme le préréglage adapté à un album ou à une plage de prise de vue |
| `keeper_hints` | Indications par photo « un meilleur cliché existe dans cette rafale » pour jusqu'à 100 chemins (vides si aucune tête de classement n'est entraînée) |
| `auto_cull` | Tri automatique d'un périmètre sous un budget de photos à conserver : aperçu d'abord, puis application avec la valeur `confirm` |
| `confirm_culling_groups` | Confirme jusqu'à 20 groupes : conserve leurs `keep_paths`, rejette le reste de leurs `paths` |

- **Un groupe est identifié par le couple `(type, group_id)`**, jamais par `group_id` seul : les identifiants des groupes similaires sont décalés lors de la fusion avec les rafales.
- **Le `group_by: "all"` par défaut ne renvoie que les rafales et les groupes similaires.** Demandez explicitement `scene`, `bracket`, `panorama` ou `hdr_panorama`.
- **Une page est réduite pour tenir dans `max_bytes` en raccourcissant la liste `photos` de chaque groupe, jamais en retirant des groupes.** `photo_count` reste la vraie taille, `photos_truncated` signale un groupe dont la liste a été coupée et `has_more` indique si une autre page suit.
- **Les bracketings, panoramas et panoramas HDR sont conservés entiers.** Dans `confirm_culling_groups`, `keep_paths` doit égaler `paths` pour ces types (sinon `invalid_input`), et `auto_cull` ne les scinde jamais.
- **Un `keep_paths` vide rejette toutes les images du groupe.** Le premier appel répond alors `confirmation_required` avec une valeur `confirm` ; montrez-le à l'utilisateur, puis répétez l'appel avec cette valeur. Si un lot s'arrête sur `forbidden_level`, `library_busy` ou `rate_limited`, les groupes déjà traités sont rapportés.
- **`auto_cull` fait un aperçu par défaut** et renvoie la répartition conservation/rejet par groupe plus une valeur `confirm` (seulement si quelque chose serait rejeté). L'application recalcule le plan et le refuse avec `confirmation_required` s'il a changé depuis l'aperçu ou s'il est trop grand pour être confirmé en un seul ensemble (réduisez-le avec `album_id`, `date_from` et `date_to`, ou `group_by`). Les images rejetées alimentent le classeur personnel comme un tri manuel.
- Appelez `ui_show_culling_group` pour montrer un groupe à l'utilisateur dans son onglet ouvert (voir [Piloter votre onglet ouvert](#piloter-votre-onglet-ouvert)).

## Résultats, limites et erreurs

Chaque résultat est une enveloppe JSON : `{"ok": true, "data": ...}` ou `{"ok": false, "error": "<code>", "message": "..."}`. Les listes renvoient `data.rows` (un jeu compact et fixe de champs par photo) ainsi que `total`.

- **Plafonds :** au plus `max_rows` lignes et `max_bytes` octets sérialisés. Les dernières lignes sont retirées et `truncated: true` est ajouté. Un résultat sans lignes qui dépasse `max_bytes` devient une erreur `too_large`.
- **Limite de débit :** `rate_per_min` appels par minute et par jeton pour la lecture. Les outils d'écriture puisent dans un budget distinct, `write_rate_per_min` (30 par défaut), si bien que les recherches n'affament pas les écritures, et inversement ; la simulation de `cull_apply` et de `delete_photos` compte comme une écriture, l'aperçu d'`auto_cull` comme une lecture. Au-delà : `rate_limited` avec `retry_after_s`. Dix échecs d'authentification par minute depuis une même adresse déclenchent un 429.
- **Codes d'erreur :** `forbidden_level` (point d'accès désactivé, jeton invalide ou niveau insuffisant), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `confirmation_required`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`.
- **Les codes récents :** `confirmation_required` (un appel destructif n'a pas de valeur `confirm` valide pour cet ensemble exact : refaites une simulation, montrez le résultat à l'utilisateur, puis réessayez), `outcome_unknown` (une écriture a expiré ou la connexion a été coupée, elle a donc pu avoir lieu ou non : relisez l'état avant de réessayer, ne réessayez jamais à l'aveugle), `library_busy` (la bibliothèque est occupée par une autre tâche : réessayez dans un instant).
- **Codes HTTP à l'entrée :** 401 pour un jeton absent ou inconnu, 403 pour une requête de navigateur d'une autre origine ou pour les identifiants d'un agent sur `/api/mcp/tokens`, 404 quand le point d'accès est désactivé. Le pont d'onglet répond par des codes de fermeture.

## Notes de sécurité

- Les légendes, étiquettes, noms de fichiers, chemins et noms d'albums ou de personnes viennent de votre bibliothèque et peuvent contenir du texte écrit pour manipuler un assistant (injection de prompt). Chaque outil est marqué `facet/untrusted_content` et demande au modèle de les traiter comme des données. Ne donnez pas à un assistant qui lit aussi du contenu non fiable le moyen d'agir sur ce qu'il trouve ici.
- Les jetons n'expirent jamais. Révoquez ceux que vous n'utilisez plus.
- Les journaux consignent l'identifiant du jeton, l'outil, le résultat et le nombre de lignes, jamais les arguments ni le jeton.

## Limites connues

- Sur une installation ouverte (sans mot de passe), toute personne qui peut joindre la visionneuse peut créer et révoquer les jetons `_anonymous` partagés. Définissez un mot de passe avant d'activer le point d'accès sur un réseau. Le pont d'onglet aggrave ce risque : un client hors navigateur peut envoyer une `Origin` inventée et un jeton nul, enregistrer un onglet `_anonymous` ayant le focus, répondre aux appels `ui_*` avec les données de son choix et évincer de vrais onglets via la limite de 8 onglets.
- Les limites de débit et les compteurs d'échecs d'authentification vivent en mémoire dans chaque processus ; avec `viewer.py --workers N`, chaque worker compte séparément.
- Le registre des onglets vit en mémoire dans un seul processus. Utilisez un seul worker (`viewer.py --workers 1`, la valeur par défaut) si vous vous appuyez sur les outils `ui_*` ; avec plusieurs workers, un appel peut atteindre un processus qui ignore votre onglet et répondre `no_tab`.
- Un utilisateur peut avoir au plus 8 onglets connectés ; en ouvrir un neuvième ferme le plus ancien.
