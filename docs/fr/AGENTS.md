# Agents IA (MCP)

> 🌐 [English](../AGENTS.md) · **Français** · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · [Português](../pt/AGENTS.md) · [简体中文](../zh/AGENTS.md)

Facet peut jouer le rôle de serveur [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) : un assistant IA comme Claude Code peut ainsi rechercher et inspecter votre bibliothèque avec les mêmes filtres que la galerie. Il expose neuf outils de lecture qui ne modifient rien dans votre bibliothèque, plus neuf outils `ui_*` qui pilotent l'onglet du navigateur que vous avez déjà ouvert (page, filtres, sélection) et n'écrivent jamais de données de la bibliothèque.

## L'activer

Le point d'accès est **désactivé par défaut**. Mettez `viewer.mcp.enabled` à `true` dans `scoring_config.json` (voir [Point d'accès agent (MCP)](CONFIGURATION.md#point-daccès-agent-mcp)), puis redémarrez la visionneuse ou rechargez la configuration. Tant qu'il est désactivé, `/mcp` et toutes les routes `/api/mcp/*` répondent 404.

Le point d'accès est `POST /mcp` sur le port de la visionneuse : HTTP diffusable (Streamable HTTP), sans état, réponses JSON simples. `GET` répond 405. Seul le pont d'onglet, `/api/mcp/bridge`, est un WebSocket ; voir [Piloter votre onglet ouvert](#piloter-votre-onglet-ouvert).

## Créer un jeton

Le plus simple passe par le navigateur. Avec `viewer.mcp.enabled` activé, ouvrez le menu du compte et choisissez **Connecter un assistant**. Sous **Créer un jeton**, saisissez un **Nom** et choisissez **Ce que l'assistant peut faire** : **Lecture et pilotage uniquement**, plus **Agir à ma place** ou **Édition complète** si votre session détient ce niveau (un jeton ne peut pas dépasser la session qui le crée). Cliquez sur **Créer le jeton** : le jeton n'apparaît qu'une fois sous **Votre nouveau jeton**, copiez-le donc tout de suite. **Jetons d'accès** liste vos jetons avec leur dernière utilisation et permet d'en révoquer un. **Ajouter à Claude Code** affiche la commande Claude Code prête à coller (voir plus bas), et **Cet onglet** indique si cet onglet est connecté, donc pilotable par les assistants. La liste des niveaux se limite à ce que le serveur accordera : une installation ouverte ne propose que **Lecture et pilotage uniquement**, **Agir à ma place** n'apparaît que sur les installations multi-utilisateurs et **Édition complète** seulement dans une session d'édition. Après la création, la boîte indique le niveau réellement accordé (« Accès accordé : {level} »).

Alternative par script (curl) :

Un assistant s'authentifie avec un jeton personnel commençant par `fct_`. Créez-en un avec une requête authentifiée (le jeton n'est renvoyé qu'**une seule fois** ; Facet ne conserve que son empreinte SHA-256) :

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "claude-code", "level": "readonly"}'
```

La réponse contient le jeton en clair dans `token`. `GET /api/mcp/tokens` liste vos jetons (jamais le secret) et `DELETE /api/mcp/tokens/{id}` en révoque un. Un superadmin peut lister les jetons de tous les propriétaires avec `?all=1` et en révoquer n'importe lequel. Chaque propriétaire peut détenir au plus 20 jetons actifs (412 au-delà). Ces routes refusent les identifiants d'un agent : un assistant ne peut donc jamais créer, lister ni révoquer de jetons.

## Connecter Claude Code

```bash
claude mcp add --transport http facet http://localhost:5000/mcp --header "Authorization: Bearer fct_YOUR_TOKEN"
```

Les outils apparaissent ensuite sous les noms `mcp__facet__search_photos`, etc. Utilisez HTTPS dès que la visionneuse est accessible au-delà de votre machine, car le jeton transite dans un en-tête à chaque appel.

## Niveaux d'autorisation

Un jeton est créé avec un niveau accordé : `readonly`, `user` ou `edition`. Le niveau **effectif** est recalculé à chaque appel : c'est le plus bas entre le niveau du jeton et le niveau actuel de son propriétaire :

- Installations à mot de passe unique : `user` est ramené à `readonly` à la création, car ce mode n'a pas de niveau intermédiaire. Un jeton `edition` exige une session d'édition et ne fonctionne que tant que le mot de passe d'édition ne change pas.
- Installations multi-utilisateurs : le jeton `edition` d'un utilisateur rétrogradé passe à `user` ; une promotion n'élève jamais un jeton au-dessus de son niveau accordé.
- Installations ouvertes (aucun mot de passe) : les jetons sont toujours `readonly` et appartiennent à un propriétaire partagé `_anonymous`.

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
| `status` | Identité du jeton, son niveau effectif et les réglages du serveur |

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
- Un outil n'atteint que les onglets du propriétaire du jeton. Avec un mot de passe unique, toutes les sessions forment le même utilisateur ; sur une installation ouverte, chaque onglet appartient à l'utilisateur partagé `_anonymous`.
- Si plusieurs onglets sont ouverts, le dernier à avoir eu le focus est utilisé et le champ `tab` du résultat l'indique. Passez `tab_id` (listé par `status`) pour en choisir un autre.
- Un onglet refuse ce que son compte n'a pas le droit de faire (par exemple `/culling` pour un compte sans édition) et l'outil renvoie ce refus.
- Ce qu'un onglet renvoie n'est pas fiable : la profondeur, la longueur des chaînes et des listes sont bornées, et le tout est plafonné par `max_bytes`.
- Erreurs : `no_tab` (aucun onglet connecté, ou pont désactivé), `tab_timeout` (pas de réponse sous `call_timeout_s`) et `tab_outdated` (l'onglet ouvert ne connaît pas l'outil ; rechargez la page après une mise à jour de Facet).
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

Indépendamment du point d'accès `/mcp`, un onglet connecté propose aussi les mêmes outils `ui_*` aux agents qui vivent dans le navigateur lui-même, via l'API W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) (`navigator.modelContext`). Un assistant natif du navigateur voit donc exactement les outils listés plus haut, les exécute dans l'onglet que vous regardez et n'a besoin d'aucun jeton.

- **Contexte sécurisé uniquement.** Facet n'enregistre les outils qu'en HTTPS ou sur `localhost`. En HTTP simple ils ne sont pas proposés et la boîte **Connecter un assistant** le signale ; la connexion par jeton ci-dessus continue de fonctionner.
- Enregistrés quand `viewer.mcp.enabled` vaut true et que vous êtes connecté, retirés à la déconnexion.
- Les outils font les mêmes choses, bornées par le même niveau de compte, que dans le tableau ci-dessus.

## Résultats, limites et erreurs

Chaque résultat est une enveloppe JSON : `{"ok": true, "data": ...}` ou `{"ok": false, "error": "<code>", "message": "..."}`. Les listes renvoient `data.rows` (un jeu compact et fixe de champs par photo) ainsi que `total`.

- **Plafonds :** au plus `max_rows` lignes et `max_bytes` octets sérialisés. Les dernières lignes sont retirées et `truncated: true` est ajouté. Un résultat sans lignes qui dépasse `max_bytes` devient une erreur `too_large`.
- **Limite de débit :** `rate_per_min` appels par minute et par jeton (un budget distinct, `write_rate_per_min`, existe pour les appels d'écriture). Au-delà : `rate_limited` avec `retry_after_s`. Dix échecs d'authentification par minute depuis une même adresse déclenchent un 429.
- **Codes d'erreur :** `forbidden_level` (point d'accès désactivé, jeton invalide ou niveau insuffisant), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`.
- **Codes HTTP à l'entrée :** 401 pour un jeton absent ou inconnu, 403 pour une requête de navigateur d'une autre origine, 404 quand le point d'accès est désactivé.

## Notes de sécurité

- Les légendes, étiquettes, noms de fichiers, chemins et noms d'albums ou de personnes viennent de votre bibliothèque et peuvent contenir du texte écrit pour manipuler un assistant (injection de prompt). Chaque outil est marqué `facet/untrusted_content` et demande au modèle de les traiter comme des données. Ne donnez pas à un assistant qui lit aussi du contenu non fiable le moyen d'agir sur ce qu'il trouve ici.
- Les jetons n'expirent jamais. Révoquez ceux que vous n'utilisez plus.
- Les journaux consignent l'identifiant du jeton, l'outil, le résultat et le nombre de lignes, jamais les arguments ni le jeton.

## Limites connues

- Sur une installation ouverte (sans mot de passe), toute personne qui peut joindre la visionneuse peut créer et révoquer les jetons `_anonymous` partagés. Définissez un mot de passe avant d'activer le point d'accès sur un réseau. Le pont d'onglet aggrave ce risque : un client hors navigateur peut envoyer une `Origin` inventée et un jeton nul, enregistrer un onglet `_anonymous` ayant le focus, répondre aux appels `ui_*` avec les données de son choix et évincer de vrais onglets via la limite de 8 onglets.
- Les limites de débit et les compteurs d'échecs d'authentification vivent en mémoire dans chaque processus ; avec `viewer.py --workers N`, chaque worker compte séparément.
- Le registre des onglets vit en mémoire dans un seul processus. Utilisez un seul worker (`viewer.py --workers 1`, la valeur par défaut) si vous vous appuyez sur les outils `ui_*` ; avec plusieurs workers, un appel peut atteindre un processus qui ignore votre onglet et répondre `no_tab`.
- Un utilisateur peut avoir au plus 8 onglets connectés ; en ouvrir un neuvième ferme le plus ancien.
