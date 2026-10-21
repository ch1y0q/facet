# Agents IA (MCP)

> 🌐 [English](../AGENTS.md) · **Français** · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · [Português](../pt/AGENTS.md) · [简体中文](../zh/AGENTS.md)

Facet peut jouer le rôle de serveur [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) : un assistant IA compatible MCP peut ainsi rechercher et inspecter votre bibliothèque avec les mêmes filtres que la galerie. Il expose treize outils de lecture qui ne modifient rien dans votre bibliothèque et douze outils `ui_*` qui pilotent l'onglet du navigateur que vous avez déjà ouvert (page, filtres, sélection) et n'écrivent jamais de données de la bibliothèque. Les jetons qui y sont autorisés peuvent aussi [modifier des éléments](#modifier-la-bibliothèque) (notes, indicateurs, étiquettes, albums, tri et suppression) et piloter la [chambre noire](#chambre-noire-groupes-de-tri).

## L'activer

Le point d'accès est **activé par défaut**. Pour le désactiver, mettez `viewer.mcp.enabled` à `false` dans `scoring_config.json` (voir [Point d'accès agent (MCP)](CONFIGURATION.md#point-daccès-agent-mcp)), puis redémarrez la visionneuse ou rechargez la configuration ; `/mcp` et toutes les routes `/api/mcp/*` répondent alors 404. Sans `viewer.password`, l'installation est considérée comme ouverte, même si `viewer.edition_password` est défini : ses jetons ne peuvent être que `readonly`. Sur une installation ouverte, le point d'accès ne sert qu'une clé anonyme en lecture seule, qui n'accorde rien que l'`/api` ouverte n'accorde déjà.

Le point d'accès est `POST /mcp` sur le port de la visionneuse : HTTP diffusable (Streamable HTTP), sans état, réponses JSON simples. `GET` répond 405. Seul le pont d'onglet, `/api/mcp/bridge`, est un WebSocket ; voir [Piloter votre onglet ouvert](#piloter-votre-onglet-ouvert).

## Créer un jeton

Le plus simple passe par le navigateur. Avec `viewer.mcp.enabled` activé, ouvrez le menu du compte et choisissez **Connecter un assistant**. Saisissez un **Nom**, choisissez **Ce que l'assistant peut faire** : **Lecture et pilotage uniquement**, plus **Agir à ma place** ou **Édition complète** si votre session détient ce niveau (un jeton ne peut pas dépasser la session qui le crée), puis cliquez sur **Créer le jeton**. La boîte affiche alors **Collez ceci dans votre assistant** avec une invite toute prête qui contient le jeton. Elle n'est affichée qu'une fois : cliquez sur **Copier l'invite**, collez-la dans votre assistant, puis cliquez sur **Terminé**. **Gérer les jetons (N)** liste vos jetons avec leur dernière utilisation et permet d'en révoquer un, et une ligne d'état indique si cet onglet est connecté, donc pilotable par les assistants. La liste des niveaux se limite à ce que le serveur accordera : une installation ouverte ne propose que **Lecture et pilotage uniquement**, **Agir à ma place** n'apparaît que sur les installations multi-utilisateurs et **Édition complète** seulement dans une session d'édition. L'invite indique le niveau réellement accordé.

Alternative par script (curl) :

Un assistant s'authentifie avec un jeton personnel commençant par `fct_`. Créez-en un avec une requête authentifiée (le jeton n'est renvoyé qu'**une seule fois** ; Facet ne conserve que son empreinte SHA-256) :

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "my-assistant", "level": "readonly"}'
```

La réponse contient le jeton en clair dans `token`. `GET /api/mcp/tokens` liste vos jetons (jamais le secret) et `DELETE /api/mcp/tokens/{id}` en révoque un. Un superadmin peut lister les jetons de tous les propriétaires avec `?all=1` et en révoquer n'importe lequel. Chaque propriétaire peut détenir au plus 20 jetons actifs (412 au-delà). Ces routes refusent (403) les identifiants d'un agent : un assistant ne peut donc jamais créer, lister ni révoquer de jetons.

## Connecter votre assistant

L'invite générée par la boîte contient tout ce dont un assistant compatible MCP a besoin : le nom du serveur `facet`, l'URL (`http://<hôte>/mcp`), le transport (Streamable HTTP), l'en-tête `Authorization: Bearer fct_...`, le niveau d'accès accordé et un appel à l'outil `status` pour confirmer la connexion. Collez-la dans votre assistant, ou ajoutez vous-même ce serveur au client MCP que vous utilisez. Utilisez HTTPS dès que la visionneuse est accessible au-delà de votre machine, car le jeton transite dans un en-tête à chaque appel.

## Niveaux d'autorisation

Un jeton est créé avec un niveau accordé : `readonly`, `user` ou `edition`. Le niveau **effectif** est recalculé à chaque appel : c'est le plus bas entre le niveau du jeton et le niveau actuel de son propriétaire :

- Installations à mot de passe unique : `user` est ramené à `readonly` à la création, car ce mode n'a pas de niveau intermédiaire. Un jeton `edition` exige une session d'édition et ne fonctionne que tant que le mot de passe d'édition ne change pas.
- Installations multi-utilisateurs : le jeton `edition` d'un utilisateur rétrogradé passe à `user` ; une promotion n'élève jamais un jeton au-dessus de son niveau accordé.
- Installations ouvertes (aucun `viewer.password`, même si `viewer.edition_password` est défini) : les jetons sont toujours `readonly` et appartiennent à un propriétaire partagé `_anonymous`.
- Les installations à mot de passe unique n'ont pas de niveau `user` : le niveau effectif est `edition` ou `readonly`, donc les outils marqués `user` dans [Modifier la bibliothèque](#modifier-la-bibliothèque) exigent aussi un jeton `edition`. Un outil `user` appelé avec un jeton de niveau inférieur répond `forbidden_level` en précisant qu'il exige `edition`.
- Chaque outil a son propre niveau minimal, vérifié avant toute lecture ou écriture ; un jeton plus bas reçoit `forbidden_level`.

Un jeton devient invalide dès que les identifiants de son propriétaire changent : mot de passe de la visionneuse ou d'édition en mode mot de passe unique, mot de passe du propriétaire en mode multi-utilisateur, ou suppression de son compte. Il reçoit alors une réponse 401 à l'entrée.

## Outils

Les treize outils de données sont en lecture seule :

| Outil | Rôle |
|------|--------------|
| `search_photos` | Filtre et trie la bibliothèque comme la galerie, en appliquant les masquages par défaut de la visionneuse (clignements, rafales, doublons, bracketings, panoramas, rejetées) sauf si le filtre les précise (renvoie `hidden_summary`). Affiché par défaut dans votre onglet ouvert (voir plus bas) ; `fields` ajoute n'importe quelle colonne de photo |
| `semantic_search` | Trouve des photos par le sens, ou par les mots des légendes avec `scope: "text"` (non affiché dans l'onglet). `filters` restreignent la recherche comme ceux de la galerie, et chaque ligne porte sa `similarity`. |
| `get_photo` | Détail complet d'une photo à partir de son chemin (sans l'histogramme) |
| `get_thumbnail` | Voir une photo : sa miniature comme partie image (`size` de 160 à 640, 512 par défaut). Une taille plus petite est utilisée si le JPEG dépasserait `viewer.mcp.max_image_bytes` ; `too_large` si aucune ne tient |
| `contact_sheet` | Voir 1 à 16 photos en une grille numérotée (`columns` de 2 à 4, plus grand côté 1024). La partie texte liste `legend` (numéro de case vers chemin, dans l'ordre demandé) et `unavailable` (cases laissées vides car la photo est absente ou non visible) |
| `possible_faces` | Visages qui ressemblent à une personne reconnue : similarité cosinus au centroïde de la personne, meilleurs d'abord, même modèle d'embedding uniquement. `scope` vaut `unassigned` (défaut), `other_persons` ou `all` ; `min_similarity` vaut 0,30 par défaut ; `limit` jusqu'à 100. Une analyse de plus de 192000 visages est refusée (`too_large`) : restreignez avec `scope`, `path_prefix`, `date_from` ou `date_to`. Les photos s'affichent dans votre onglet. `candidates` est le nombre de visages du périmètre que vous pouvez voir, avant la vérification de la dimension d'embedding ; `faces_scanned` est le nombre de lignes réellement évaluées. |
| `similar_photos` | Photos similaires à une photo, par plongement visuel ou par couleur ; `min_similarity` (0 à 1) fixe le seuil |
| `filter_options` | Le vocabulaire accepté par un filtre : appareils, objectifs, étiquettes, personnes, motifs, catégories, moments narratifs, types d'indésirables, plages de métriques |
| `list_persons` | Personnes reconnues, filtrables par nom |
| `list_albums` | Albums visibles par le propriétaire du jeton |
| `library_stats` | Statistiques de la bibliothèque : `kind` choisit l'aperçu de la taille et des scores (par défaut) ou n'importe quelle donnée de la page Statistiques (voir plus bas) |
| `status` | Identité du jeton, son niveau effectif et les réglages du serveur et les onglets ouverts qu'il peut piloter |
| `available_actions` | Les tâches qui s'appliquent maintenant à votre onglet ouvert et à ce jeton, chacune avec ses outils ; les outils au-dessus du niveau du jeton ne sont pas listés |

Dans tout objet de filtres, `show_rejected` est un booléen : `true` ne liste que les photos rejetées, `false` ou son absence donne la liste normale.

## Les résultats s'affichent dans votre onglet

- `search_photos`, `semantic_search` et `similar_photos` acceptent `show` (`true` par défaut). Après une recherche réussie sur la première page, le serveur applique la même requête à l'onglet Facet ouvert, en remplaçant ses filtres : vous voyez ce que l'assistant a trouvé sans avoir à le demander. On indique aux assistants de ne jamais demander s'il faut ouvrir ou afficher les résultats ; `show: false` sert aux sondages intermédiaires et aux décomptes, et la dernière recherche affichée est celle que vous voyez.
- Le résultat porte `shown_in_tab` : `{"applied": true, "tab_id", "keys", "total"}`, ou `{"applied": false, "reason"}` où la raison est `no_tab`, `bridge_disabled`, `tab_outdated`, `tab_timeout` (l'onglet peut encore l'appliquer), `forbidden`, `page_not_first`, `empty_result`, `unsupported_filters` (avec `keys`) ou `invalid_combination`. Un affichage raté ne fait jamais échouer la recherche. Passez `tab_id` pour choisir un onglet. Toutes les raisons : `error` (l'affichage lui-même a échoué), `bridge_disabled`, `page_not_first`, `empty_result`, `invalid_combination`, `unsupported_filters` (avec `keys` ; pour `semantic_search` ce sont `scope` ou `threshold`, un seuil supérieur à 0,5 que le curseur de la barre latérale ne peut pas exprimer) et les codes renvoyés par le pont d'onglet (`no_tab`, `tab_outdated`, `tab_timeout`, `forbidden`, `invalid_input`, `upstream_error`). L'onglet pagine lui-même : pour une recherche sémantique il peut afficher plus de lignes que l'assistant n'en a reçu. Quand des lignes sont raccourcies, `next_page` (avec `suggested_per_page`) désigne la page qui continue exactement après la dernière ligne renvoyée ou, si les pages ne peuvent pas l'exprimer, `next_offset` la donne comme décalage en lignes.
- Seule la première page est affichée (l'onglet pagine lui-même au défilement), et un résultat vide n'est pas affiché : vous gardez votre vue précédente. Une recherche utilisant des filtres que la barre latérale de la galerie ne propose pas (`exclude_tags`, `require_tags`, `is_silhouette`, `junk_kind`, `narrative_moment`, `min_rating`, `min_aggregate`, `show_rejected: true`) n'est pas appliquée partiellement, et `semantic_search` avec `scope: "text"` n'est pas affichée non plus.
- Un affichage quitte `/culling`, `/compare` et `/photo` pour la galerie, efface une sélection de toute la vue et, sur une page d'album, revient d'abord à la galerie : les filtres enregistrés d'un album ne sont donc jamais écrasés. Une recherche dont le décompte alimente l'`expected_count` d'un outil d'écriture doit utiliser `show: false`.
- `ui_show_photos` épingle une liste exacte de photos : la galerie les affiche dans votre ordre jusqu'à ce qu'un changement de filtre remplace la liste. `ui_get_context` indique si une liste épinglée est affichée. Les champs optionnels `groups` (un numéro de groupe par chemin) et `marks` (`keep` ou `remove` par chemin) annotent les photos épinglées : chaque carte affiche une pastille « Groupe n » et un badge Conserver/Retirer sur lequel vous pouvez cliquer pour l'inverser, et une légende en pastilles compte les groupes, les Conserver et les Retirer. Vos inversions restent dans l'onglet jusqu'à ce que la liste soit vidée, et `ui_get_context.review` les renvoie sous la forme `{keep, remove}` (jusqu'à 1000 chemins chacun) pour que l'assistant tienne compte de vos modifications.
- **Dates.** Les outils de tri (`auto_cull`, `list_culling_groups`, `suggest_culling_profile`) et les groupes de la chambre noire de `cull_report` acceptent une date ISO (`2026-06-01`), une date-heure ISO (`2026-06-01T08:30:00` ou avec une espace) ou la forme EXIF (`2026:06:01 08:30:00`) ; un `date_to` sans heure couvre toute la journée. Les outils au jour près (`library_stats`, `possible_faces`, les décomptes de `cull_report`) n'acceptent qu'une date et refusent une heure avec `invalid_input`.
- Les lignes portent l'appareil, l'objectif, l'ouverture, la vitesse, les ISO, la focale et `is_monochrome`. `fields` (sur les trois outils de recherche) ajoute toute autre colonne de photo, hors données d'image et de plongements, par exemple `leading_lines_score` ; `learned_score` n'est rempli que pour un tri sur ce score. Quand le plafond d'octets raccourcit les lignes, le résultat ajoute `returned` (et `next_offset` ou `suggested_per_page`).
- `library_stats` accepte `kind` (`overview` par défaut : taille, décomptes par type et aperçu des scores). L'aperçu contient un `basis` qui indique ce que compte chaque total : `total_photos` ignore les bascules de masquage et inclut les photos rejetées, tandis que `type_counts` applique les bascules de masquage et ignore les filtres de date et de catégorie. Les autres valeurs sont en lecture seule et renvoient les données de la page Statistiques ; les longues listes sont coupées à 50 entrées avec `truncated: true` :

| Valeur de kind | Données |
|------|------|
| `score_distribution`, `top_cameras`, `categories`, `gear`, `stats_settings`, `timeline`, `correlations` | Les panneaux de la page Statistiques ; ils acceptent `date_from`, `date_to` et `category`. `correlations` accepte aussi `x`, `y` (liste séparée par des virgules), `group_by` et `min_samples` |
| `category_breakdown`, `category_weights`, `category_correlations`, `category_overlap` | Statistiques par catégorie (sans paramètre) |
| `timeline_dates`, `timeline_months` | Nombre de photos par jour ou par mois ; elles exigent `year` (`timeline_dates` accepte aussi `month`) |
| `timeline_years` | Nombre de photos par année |

## Piloter votre onglet ouvert

En plus des outils de données, le serveur liste toujours douze outils `ui_*` qui agissent sur l'onglet Facet que vous avez ouvert dans un navigateur : ils changent de page, modifient les filtres ou la sélection et relisent ce que vous voyez. Ils n'écrivent jamais de données de la bibliothèque, un jeton `readonly` suffit donc.

| Outil | Ce qu'il fait |
|-------|---------------|
| `ui_navigate` | Aller à une page (galerie, personnes, albums, statistiques, ...) |
| `ui_set_gallery_filters` | Fusionner un correctif dans les filtres et le tri de la galerie (`null` retire un filtre, `replace: true` repart de zéro) |
| `ui_get_gallery_view` | Route, filtres actifs, total des résultats, premiers chemins de photos visibles et nombre de photos sélectionnées |
| `ui_get_context` | La page ouverte (route), l'état de la galerie (total, nombre chargé, présence d'une liste épinglée), le nombre de photos sélectionnées et les `actions` qui s'appliquent ici à votre jeton |
| `ui_open_photo` | Ouvrir une photo |
| `ui_show_photos` | Affiche exactement ces `paths` (jusqu'à 200) dans cet ordre comme liste de la galerie ; les inaccessibles reviennent dans `missing`. Tout changement de filtre remplace la liste. Les champs optionnels `groups` et `marks` (une entrée par chemin) numérotent les photos et marquent chacune Conserver ou Retirer ; vous pouvez inverser un marquage sur la carte et `ui_get_context.review` renvoie vos choix |
| `ui_select_photos` | Sélectionner des `paths` explicites, ou toute la vue filtrée avec `select_view: true`, en mode `replace`, `add` ou `remove` |
| `ui_clear_selection` | Vider la sélection |
| `ui_get_selection` | Le `scope` (`paths` ou `view`) et le `count`, avec les `paths` ou, pour une vue, les `filters` et `excluded_paths` |
| `ui_next_page` | Charger la page suivante de la galerie |
| `ui_show_culling_group` | Ouvrir la chambre noire sur un groupe, identifié par `(type, group_id)` (comptes édition) |
| `ui_show_comparison` | Ouvrir la page de comparaison par paires, éventuellement sur une catégorie et une stratégie ; elle ne fait qu'ouvrir la page, c'est vous qui choisissez les gagnants |

Fonctionnement :

- Tant que vous êtes connecté et que `viewer.mcp.enabled` et `viewer.mcp.bridge` valent `true`, chaque onglet Facet ouvre un WebSocket de même origine vers `/api/mcp/bridge` et s'authentifie avec votre session dans son premier message. Le pont est actif par défaut ; mettez `viewer.mcp.bridge` à `false` pour le désactiver, et les outils `ui_*` répondent alors par une erreur explicite.
- `ui_get_context` lit la page ouverte, l'état de la galerie, le nombre de photos sélectionnées et les `actions` qui s'appliquent à cette page et à ce jeton ; `available_actions` répond à la même question côté serveur pour votre onglet ouvert. Les outils au-dessus du niveau du jeton ne sont pas listés.
- Un outil n'atteint que les onglets du propriétaire du jeton. Avec un mot de passe unique, toutes les sessions forment le même utilisateur ; sur une installation ouverte, chaque onglet appartient à l'utilisateur partagé `_anonymous`, y compris les connexions en mode édition.
- Chaque onglet porte le niveau de la session qui l'a ouvert, et un jeton ne pilote que les onglets de niveau égal ou supérieur au sien : un jeton `edition` n'utilise jamais un onglet connecté avec une simple session de consultation, alors qu'un jeton `readonly` peut piloter un onglet `edition`. Avec un mot de passe unique, un jeton est aussi borné par la session qui l'a créé : un jeton créé depuis une session de consultation ne pilote que les onglets de consultation, jamais l'onglet d'édition (un jeton antérieur à cette règle est borné à son propre niveau). Sur une installation ouverte, un jeton est aussi borné au niveau consultation : il ne pilote que les onglets de consultation, jamais un onglet `edition`. Un onglet ne peut être remplacé que par un onglet de niveau égal ou supérieur : une session de consultation qui réutilise le `tab_id` d'un onglet d'édition est refusée avec 4409, et au-delà du plafond d'onglets par utilisateur, l'onglet de plus bas niveau part en premier. `status` ne liste que les onglets que le jeton peut piloter. `status` indique aussi `out_of_reach_tabs`, le nombre d'onglets ouverts que ce jeton ne peut pas piloter.
- Si plusieurs onglets sont ouverts, le dernier à avoir eu le focus est utilisé et le champ `tab` du résultat l'indique. Passez `tab_id` (listé par `status`) pour en choisir un autre.
- Un onglet refuse ce que son compte n'a pas le droit de faire (par exemple `/culling` pour un compte sans édition) et l'outil renvoie ce refus.
- Ce qu'un onglet renvoie n'est pas fiable : la profondeur, la longueur des chaînes et des listes sont bornées, et le tout est plafonné par `max_bytes`.
- Erreurs : `no_tab` (aucun onglet connecté, ou pont désactivé), `tab_timeout` (pas de réponse sous `call_timeout_s`) et `tab_outdated` (l'onglet ouvert ne connaît pas l'outil ; rechargez la page après une mise à jour de Facet).
- Le pont accepte d'abord la WebSocket puis la refuse par un code de fermeture et non par un statut HTTP : 4404 quand le point d'accès ou le pont est désactivé (l'onglet reste alors déconnecté jusqu'au rechargement de la page), 4403 quand l'en-tête `Origin` est absent ou non autorisé, 4401 pour une session absente ou rejetée.
- Un proxy inverse doit transmettre la mise à niveau WebSocket pour `/api/mcp/bridge` ; voir [Déploiement](DEPLOYMENT.md). S'il réécrit l'en-tête `Host`, indiquez l'origine publique dans `viewer.mcp.allowed_origins` (par exemple `["https://photos.example.com"]`), car l'origine de la page doit correspondre à l'hôte ou figurer dans la liste.
- Le registre des onglets est propre à chaque processus : le pont exige un seul worker (la valeur par défaut).

En complément :

- `ui_set_gallery_filters` vous amène d'abord à la galerie si une autre page est ouverte, puis applique le patch. Il refuse en bloc (`invalid_input`) un patch qui nomme un filtre que l'onglet ne sait pas piloter ; utilisez `search_photos` pour ceux-là. Sur une page d'album, tout changement revient d'abord à la galerie (pas seulement `replace: true`) : les filtres enregistrés de l'album ne sont pas écrasés et le périmètre de l'album est abandonné. L'outil accepte aussi `semantic_query`, `semantic_threshold` (0 à 0,5), `similar_to`, `similarity_mode` et `min_similarity` (0 à 1) ; `similar_to` et `semantic_query` ne se combinent pas.
- `ui_get_gallery_view`, `ui_next_page` et `ui_select_photos` avec `select_view` exigent que la galerie (ou un album) soit la page ouverte, sinon ils répondent `no_active_view` ; appelez d'abord `ui_navigate` vers `/`. Donnez à `ui_select_photos` exactement l'un de `paths` et `select_view`.
- `no_tab` signifie aussi qu'aucun onglet Facet n'est ouvert : ouvrez Facet dans un navigateur et connectez-vous. La ligne d'état de la boîte **Connecter un assistant** indique si cet onglet est connecté ; l'outil `status` liste les onglets ouverts et leurs identifiants.
- Un onglet cesse de se reconnecter dès que sa session est rejetée (reconnectez-vous), et attend votre retour sur lui lorsqu'un autre de vos onglets a pris la place.
- Le pont d'onglet ne se connecte que si le serveur le déclare disponible (le point d'accès est activé et `viewer.mcp.bridge` vaut true) ; pont désactivé, les onglets ne se connectent pas du tout.
- `ui_set_gallery_filters` refuse un nom de filtre inconnu avec `invalid_input`, ainsi qu'un patch donnant à la fois `category` et `type`, ou à la fois `person` et `person_id`. Il ne propose que les filtres que la galerie sait afficher ; utilisez `search_photos` pour les autres.
- `ui_navigate` n'ouvre que les pages statiques de l'application : la page de connexion, les pages partagées, les URL externes et les chemins inconnus sont refusés (`invalid_input`), et les pages réservées à l'édition sont refusées à une session sans édition.
- `ui_select_photos` en mode `remove` sous une sélection de toute la vue ignore les chemins hors de la vue chargée et les liste dans `not_in_view` dans le résultat.

## WebMCP dans la page (agents du navigateur)

Indépendamment du point d'accès `/mcp`, un onglet connecté propose aussi les mêmes outils `ui_*` aux agents qui vivent dans le navigateur lui-même, via l'API W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) (`document.modelContext`). Un assistant natif du navigateur voit donc exactement les outils listés plus haut, les exécute dans l'onglet que vous regardez et n'a besoin d'aucun jeton.

- **Contexte sécurisé uniquement.** Facet n'enregistre les outils qu'en HTTPS ou sur `localhost`. En HTTP simple, les outils dans la page ne sont pas proposés ; la connexion par jeton ci-dessus continue de fonctionner.
- Enregistrés quand `viewer.mcp.enabled` vaut true et que vous êtes connecté, retirés à la déconnexion.
- L'objet est `document.modelContext` (l'ancien alias `navigator.modelContext` n'est pas fourni). C'est un polyfill, installé seulement si le navigateur n'en a pas de natif, et il ne peut pas être désinstallé : il peut exister avant votre connexion sans aucun outil Facet, et reste après la déconnexion avec une liste d'outils vide.
- Les outils font les mêmes choses, bornées par le même niveau de compte, que dans le tableau ci-dessus.
- Un agent de navigateur lit la même liste `actions` via `ui_get_context`.
- **Outils de bibliothèque dans la page.** L'onglet propose aussi les outils propres au serveur (recherche, notes, étiquettes, albums, chambre noire, rapports) via `GET /api/mcp/inpage_tools` (la liste, avec le schéma de chaque outil, son `required_level` et le `level` actuel de la session) et `POST /api/mcp/call` (`{tool, arguments, selection_snapshot?}`). Ils s'exécutent avec votre session connectée, par le même enveloppeur que `/mcp` : niveaux, aperçus, valeurs `confirm` et limites de débit se comportent donc à l'identique. Un outil en échec renvoie une enveloppe `ok: false` normale (HTTP 200) ; un appel renvoie aussi `changed` (photos écrites).
- **Niveau.** Le niveau est le plus bas entre celui de votre connexion et votre rôle actuel, relu à chaque appel : un compte rétrogradé perd aussitôt les écritures et un compte supprimé est refusé (401). Sous le seuil d'un outil, la réponse est `forbidden_level` (« This session's level is readonly; set_rating needs edition: unlock edition in Facet »). Sur une installation à mot de passe unique, une session qui écrit doit avoir déverrouillé l'édition.
- **Qui peut appeler.** Uniquement une personne connectée. Le jeton `/mcp` d'un agent est refusé sur ces routes (403), tout comme une `Origin` étrangère ; un cookie seul n'authentifie jamais. Chaque appel porte un en-tête `X-Facet-Agent-Session` (1 à 64 lettres, chiffres, `_` ou `-` ; absent ou mal formé, il répond 400). Il distingue les onglets : une valeur `confirm` émise pour un onglet est refusée à un autre ; c'est la page qui le choisit, il sépare mais n'authentifie pas.
- **Ce qui est exclu.** Les outils d'image (`get_thumbnail`, `contact_sheet`) et `available_actions` (utilisez `ui_get_context`). L'argument `show` d'un outil est toujours désactivé, car l'onglet est l'appelant, et `tab_id` est refusé. `status` ne renvoie que les versions du serveur et du contrat d'interface. `target: "selection"` utilise le `selection_snapshot` envoyé par la page (ce que `ui_get_selection` a renvoyé) et donne `invalid_input` sans lui. Les actions destructrices suivent toujours `viewer.mcp.allow_destructive`.
- **Goût.** Comme toute écriture d'assistant, un appel d'outil fait depuis la page n'enregistre jamais de comparaisons et n'arme jamais le réentraînement.
- **Interrupteur.** `viewer.mcp.inpage_tools` (`true` par défaut) désactive les deux routes (404) et met `features.mcp_inpage` à faux dans `/api/auth/status` ; `viewer.mcp.enabled: false` les désactive aussi.

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
| `assign_faces` | `edition` | Déplace des visages vers une personne ; ceux qu'une autre personne possède sont laissés tels quels sauf `allow_reassign`, et le résultat liste ce qui a été ignoré | 50 ids de visage |
| `set_caption` | `edition` | Définit la légende d'une photo (sémantique d'ensemble ; une légende inchangée revient en `already`) | 1 photo, 2000 caractères |
| `export_metadata` | `edition` | Écrit des sidecars XMP à côté des fichiers | 100 chemins, ou `filters`, ou `target` |
| `junk_list` | `readonly` | Liste les candidates du tri des ratés, éventuellement d'un seul `kind` | 100 par page |
| `junk_reject` | `edition` | Rejette les candidates du tri des ratés (comme `batch_set_rejected`) | 1000 chemins |
| `junk_clear` | `edition` | Conserve des candidates : les marque comme évaluées et saines pour qu'elles quittent la file | 50 chemins |
| `cull_apply` | `edition` | Copie les photos à conserver, ou déplace ou met à la corbeille les rejetées ([aperçu puis confirmation](#actions-destructives--aperçu-puis-confirmation)) | 10000 chemins, ou `filters` |
| `delete_photos` | `edition` | Met les fichiers à la corbeille et supprime leurs lignes de la bibliothèque ([aperçu puis confirmation](#actions-destructives--aperçu-puis-confirmation)) | 1000 chemins |

- **Les outils `user` exigent un jeton d'édition sur une installation à mot de passe unique**, qui n'a pas de niveau intermédiaire (voir [Niveaux d'autorisation](#niveaux-dautorisation)).
- **Sémantique d'affectation.** Les outils par photo lisent l'état actuel et n'écrivent qu'une différence, donc répéter un appel est sans danger ; chaque chemin indique `changed` ou `already`. Ils traitent un chemin à la fois et s'arrêtent au premier `library_busy`, `outcome_unknown` ou `forbidden_level`, en rapportant `affected`, les `results` par chemin et `not_attempted`. Les outils par lot appliquent le même état.
- **Choisir les photos.** Les outils par lot, d'étiquettes et `cull_apply` prennent SOIT `paths` SOIT `filters` (l'objet de filtres de `search_photos`), plus une liste `exclude` facultative. Une cible `filters` doit s'accompagner de `expected_count`, le nombre de correspondances des filtres avant application de `exclude` (le `total` de `search_photos`). Facet recompte d'abord les filtres et n'écrit rien si les nombres diffèrent (`invalid_input`, avec `actual_count`). Les masquages par défaut de la visionneuse (y compris les photos rejetées) s'appliquent à `filters` exactement comme dans `search_photos`, donc son `total` est l'`expected_count`. Les photos rejetées sont donc masquées d'une cible `filters` : pour `move_rejects` et `trash_rejects`, passez `show_rejected` (ou `hide_rejected: false`) à `search_photos` ET à `cull_apply` ; `copy_keeps` n'a besoin de rien de plus.
- **À qui appartient l'état.** Les notes, favoris et rejets sont ceux du propriétaire du jeton.
- **Fichiers ignorés.** Quand `cull_apply` ou `delete_photos` renvoie une liste `skipped` non vide, le résultat contient aussi un `skipped_reason` : ces chemins de la bibliothèque n'ont aucun fichier lisible sur le disque (manquant, déplacé ou hors des répertoires analysés) et rien n'a été fait pour eux.
- **Les photos sélectionnées par l'utilisateur.** Là où un outil prend `paths`, `target: "selection"` utilise la sélection de l'onglet ouvert (`tab_id` choisit l'onglet). Une sélection modifiée entre l'aperçu et la confirmation répond `invalid_input` avec `selection_changed`, une sélection trop grande pour la réponse de l'onglet répond `too_large`, et `delete_photos` relit la sélection à la confirmation.
- **Légendes et exports.** `set_caption` ne stocke que le texte. La légende n'est pas ré-encodée : la recherche sémantique de légendes continue de trouver l'ancien texte jusqu'à un nouveau ré-encodage, et l'export incrémental vers la base de la visionneuse conserve une légende existante quand celle de la source est vide, si bien qu'une légende effacée peut revenir avec un export ou un scan ultérieur. `export_metadata` attend jusqu'à 180 secondes, rapporte `written`, `skipped` et `errors` avec le premier message d'erreur dans `first_error`, et refuse d'écrire avec exiftool 13.23 à 13.27.
- **Visages.** `assign_faces` ignore, et liste, les visages manquants, déjà sur cette personne, possédés par une autre personne (sauf `allow_reassign`), d'un autre modèle d'embedding ou d'une personne masquée ; `assigned_count` est ce qui a réellement bougé.

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

## Corrections et données de référence

- **Corrections** (`edition`). `override_sequence` (`kind` : `panorama`, `bracket`, `hdr_panorama` ou `suppress` ; au moins 2 chemins sauf pour `suppress`) et `clear_sequence_override` enregistrent une correction appliquée à la prochaine passe de détection (le résultat indique `pending`). `override_category` et `clear_category_override` définissent ou suppriment une catégorie persistante qui survit aux nouveaux scans et conserve le contexte de notation.
- **Comparer des images** (`readonly`). `group_compare` compare les images d'un groupe de tri (jusqu'à 12 chemins) `by: "faces"` (par image : nombre de visages, clignements, yeux ouverts le plus faible, meilleur sourire, `best_path_by_eyes`) ou `by: "subjects"` (netteté et importance du sujet, `sharpest_path`). C'est un conseil, pas une décision. `cull_report` résume un périmètre en un appel : total, conservées, rejetées, favorites, notées, non examinées, ce que les bascules de masquage cacheraient, indésirables, faibles scores, meilleures images et, avec un jeton edition, les premiers groupes de la chambre noire. Les raisons se recoupent. Il contient un `basis` qui indique les filtres que respecte chaque décompte (les bascules de masquage ne s'appliquent pas aux décomptes).
- **Goût.** `comparison_status` (`edition`) indique combien de comparaisons par paires vous avez faites et dans quelle mesure elles couvrent la bibliothèque. Aucun outil ne soumet, ne modifie ni ne supprime de comparaison : la réponse à une paire est votre propre clic. Les écritures d'un assistant (notes, rejets, confirmations de la chambre noire, `auto_cull`) n'enregistrent jamais de comparaison et n'arment jamais le réentraînement automatique ; la même action faite par vous dans la galerie le fait toujours. Les notes, favoris et rejets qu'un assistant a écrits sont aussi exclus des paires d'entraînement du classeur personnel quand il est reconstruit à partir de vos notes ; ils comptent de nouveau dès que vous notez vous-même cette photo. Cette trace est conservée dans sa propre table et n'est jamais exportée.
- **Scans.** `start_scan` et `scan_status` (`edition`) lancent et suivent un scan des répertoires configurés. Ils ne sont listés que si `viewer.features.show_scan_button` est actif et que l'installation est verrouillée (une clé superadmin en mode multi-utilisateur). Un scan est additif et refusé tant qu'une autre tâche tourne (`conflict`). La synchronisation avec Immich reste en ligne de commande.
- **Ressources.** Outre les outils, le serveur liste cinq ressources `facet://` en lecture seule : `facet://categories`, `facet://tags`, `facet://persons`, `facet://filters` (chaque filtre de recherche avec son domaine de valeurs, plus les plages de métriques) et `facet://scoring-contexts`. Chacune est lue comme le propriétaire de la clé voit la bibliothèque, limitée à 200 lignes et 32 Kio (`truncated` l'indique).
- **Choisir ce qui est listé.** `viewer.mcp.tool_profile` vaut `full` (par défaut) ou `core` : `core` ne liste qu'un ensemble de 11 outils pour les petits modèles (`status`, `search_photos`, `semantic_search`, `get_photo`, `filter_options`, `library_stats`, `ui_show_photos`, `set_rating`, `set_favorite`, `set_rejected`, `album_add_photos`). Cela ne change que la liste, jamais ce qu'une clé peut appeler. `viewer.mcp.allow_destructive` (`false` par défaut) conditionne `delete_photos` (non listé si désactivé), les actions `move_rejects` et `trash_rejects` de `cull_apply`, et `assign_faces` avec `allow_reassign` ; un appel refusé répond `feature_disabled`. Les outils que le niveau d'un jeton ne peut pas appeler ne sont pas listés non plus.
- **Deux codes d'erreur de plus.** `feature_disabled` : la route est désactivée par une clé de configuration, que le message nomme. `conflict` : la bibliothèque est occupée par une tâche incompatible avec celle-ci (par exemple un scan déjà en cours).

## Prompts

Le serveur propose aussi cinq prompts prêts à l'emploi, listés par `prompts/list` et filtrés selon le niveau du jeton. Un prompt ne nomme que des outils que le jeton peut appeler, et un outil destructif seulement derrière son essai à blanc et sa confirmation. Chaque appel compte dans la limite de lecture et est journalisé par nom, jamais avec ses arguments.

| Prompt | Arguments | Ce qu'il demande à l'assistant |
|--------|-----------|--------------------------------|
| `find_photo` | `description` | Trouver une photo à partir d'une description et l'afficher |
| `cull_shoot` | `scope_hint` | Passer en revue une séance, proposer quoi rejeter et, une fois que vous avez décidé, enregistrer vos décisions avec `confirm_culling_groups` ; déplacer ou mettre à la corbeille n'arrive qu'après un essai à blanc et votre confirmation |
| `build_album` | `theme`, `album_name` | Réunir les photos correspondantes dans un nouvel album |
| `tag_people` | `person` | Trouver les visages qui ressemblent à une personne et assigner ceux que vous confirmez |
| `teach_taste` | `category` | Ouvrir la page de comparaison par paires dans votre onglet et suivre le nombre de comparaisons faites ; la réponse à chaque paire reste toujours votre propre clic |

## Chambre noire (groupes de tri)

Les outils de la chambre noire reprennent la page `/culling`. Tous exigent le niveau `edition`, y compris ceux qui ne font que lister.

| Outil | Ce qu'il fait |
|-------|---------------|
| `list_culling_groups` | Liste les groupes (`burst`, `similar`, `scene`, `bracket`, `panorama`, `hdr_panorama`) avec leurs photos et scores, triables et limités par album ou plage de dates |
| `culling_profiles` | Les préréglages de tri adaptés au genre et celui par défaut |
| `suggest_culling_profile` | Nomme le préréglage adapté à un album ou à une plage de prise de vue |
| `keeper_hints` | Indications par photo « un meilleur cliché existe dans cette rafale » pour jusqu'à 100 chemins (vides si aucune tête de classement n'est entraînée) |
| `auto_cull` | Tri automatique d'un périmètre sous un budget de photos à conserver : aperçu du plan page par page, puis application avec la valeur `confirm` |
| `confirm_culling_groups` | Confirme jusqu'à 20 groupes : conserve leurs `keep_paths`, rejette le reste de leurs `paths` |

- **Un groupe est identifié par le couple `(type, group_id)`**, jamais par `group_id` seul : les identifiants des groupes similaires sont décalés lors de la fusion avec les rafales.
- **Le `group_by: "all"` par défaut ne renvoie que les rafales et les groupes similaires.** Demandez explicitement `scene`, `bracket`, `panorama` ou `hdr_panorama`.
- **Une page est réduite pour tenir dans `max_bytes` en raccourcissant la liste `photos` de chaque groupe, jamais en retirant des groupes.** `photo_count` reste la vraie taille, `photos_truncated` signale un groupe dont la liste a été coupée et `has_more` indique si une autre page suit.
- **Les bracketings, panoramas et panoramas HDR sont conservés entiers.** Dans `confirm_culling_groups`, `keep_paths` doit égaler `paths` pour ces types (sinon `invalid_input`), et `auto_cull` ne les scinde jamais.
- **Un `keep_paths` vide rejette toutes les images du groupe.** Le premier appel répond alors `confirmation_required` avec une valeur `confirm` ; montrez-le à l'utilisateur, puis répétez l'appel avec cette valeur. Si un lot s'arrête sur `forbidden_level`, `library_busy` ou `rate_limited`, les groupes déjà traités sont rapportés.
- **`auto_cull` fait un aperçu par défaut** et renvoie la répartition conservation/rejet par groupe plus une valeur `confirm` (seulement si quelque chose serait rejeté). Chaque appel planifie tout le périmètre et le renvoie par pages de groupes entiers (200 photos au plus par page) : répétez l'appel avec `cursor` égal au `next_cursor` précédent jusqu'à ce qu'il vaille `null`. Chaque ligne porte son `number` dans tout le plan et les totaux couvrent le plan complet. Triez une plage de dates entière en UN appel, jamais mois par mois.
- **Un seul `confirm` couvre tout le plan** (valable 300 s, à usage unique). L'application recalcule le plan et le refuse avec `confirmation_required` s'il a changé depuis l'aperçu. Les rejets faits par un assistant n'alimentent jamais le classeur personnel, contrairement au même tri fait par vous dans la galerie.
- **Surcharges.** `keep_paths` et `remove_paths` (jusqu'à 1000 chacun ; typiquement les listes `review` de `ui_get_context`) modifient des images isolées du plan. Passez les mêmes surcharges à l'essai à blanc qui émet le `confirm` et à l'application. Les chemins absents du plan sont ignorés et signalés dans `ignored_overrides` ; retirer une image d'un bracketing, d'un panorama ou d'un panorama HDR, laisser un groupe sans image conservée ou citer un chemin dans les deux listes est refusé avec `invalid_input`, en nommant les chemins ou les groupes.
- **`scope_dependent_kinds`** nomme les types de groupes (`similar`, `scene`) dont la composition dépend de la plage de dates ou du lot de candidats, avec une note invitant à trier toute la plage en un appel. Les rafales, bracketings et panoramas ne changent pas avec la plage.
- **`show`** (`true` par défaut, avec `tab_id`). Lors d'un essai à blanc, la page courante est épinglée dans votre onglet ouvert avec des numéros de groupe et des marquages Conserver/Retirer, et le résultat contient `shown_in_tab`. Inversez les marquages sur les cartes ; l'assistant les lit avec `ui_get_context.review`. Un affichage en échec ne fait jamais échouer l'appel.
- Appelez `ui_show_culling_group` pour montrer un groupe à l'utilisateur dans son onglet ouvert (voir [Piloter votre onglet ouvert](#piloter-votre-onglet-ouvert)).

## Résultats, limites et erreurs

Chaque résultat est une enveloppe JSON : `{"ok": true, "data": ...}` ou `{"ok": false, "error": "<code>", "message": "..."}`. Les listes renvoient `data.rows` (un jeu compact et fixe de champs par photo) ainsi que `total`. Un résultat de recherche porte aussi `shown_in_tab`, et un résultat raccourci par le plafond d'octets porte `returned`.

- **Plafonds :** au plus `max_rows` lignes et `max_bytes` octets sérialisés. Les dernières lignes sont retirées et `truncated: true` est ajouté. Un résultat sans lignes qui dépasse `max_bytes` devient une erreur `too_large`.
- **Images :** `get_thumbnail` et `contact_sheet` renvoient une partie image avant la partie JSON. L'image est plafonnée par `max_image_bytes` (262144 par défaut), pas par `max_bytes`. Le texte visible dans une image est une donnée, jamais une instruction.
- **Analyse de visages :** `possible_faces` lit au plus 192000 visages et peut attendre jusqu'à 120 secondes ; au-delà, il répond `too_large`.
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
