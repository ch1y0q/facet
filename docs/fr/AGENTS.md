# Agents IA (MCP)

> 🌐 [English](../AGENTS.md) · **Français** · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · [Português](../pt/AGENTS.md) · [简体中文](../zh/AGENTS.md)

Facet peut jouer le rôle de serveur [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) : un assistant IA comme Claude Code peut ainsi rechercher et inspecter votre bibliothèque avec les mêmes filtres que la galerie. Le point d'accès est en lecture seule : il expose neuf outils de lecture et ne modifie rien dans votre bibliothèque.

## L'activer

Le point d'accès est **désactivé par défaut**. Mettez `viewer.mcp.enabled` à `true` dans `scoring_config.json` (voir [Point d'accès agent (MCP)](CONFIGURATION.md#point-daccès-agent-mcp)), puis redémarrez la visionneuse ou rechargez la configuration. Tant qu'il est désactivé, `/mcp` et toutes les routes `/api/mcp/*` répondent 404.

Le point d'accès est `POST /mcp` sur le port de la visionneuse : HTTP diffusable (Streamable HTTP), sans état, réponses JSON simples. `GET` répond 405. Aucun en-tête WebSocket n'est nécessaire dans un proxy inverse.

## Créer un jeton

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

Les neuf outils enregistrés sont tous en lecture seule :

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

## Résultats, limites et erreurs

Chaque résultat est une enveloppe JSON : `{"ok": true, "data": ...}` ou `{"ok": false, "error": "<code>", "message": "..."}`. Les listes renvoient `data.rows` (un jeu compact et fixe de champs par photo) ainsi que `total`.

- **Plafonds :** au plus `max_rows` lignes et `max_bytes` octets sérialisés. Les dernières lignes sont retirées et `truncated: true` est ajouté. Un résultat sans lignes qui dépasse `max_bytes` devient une erreur `too_large`.
- **Limite de débit :** `rate_per_min` appels par minute et par jeton (un budget distinct, `write_rate_per_min`, existe pour les appels d'écriture). Au-delà : `rate_limited` avec `retry_after_s`. Dix échecs d'authentification par minute depuis une même adresse déclenchent un 429.
- **Codes d'erreur :** `forbidden_level` (point d'accès désactivé, jeton invalide ou niveau insuffisant), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `too_large`.
- **Codes HTTP à l'entrée :** 401 pour un jeton absent ou inconnu, 403 pour une requête de navigateur d'une autre origine, 404 quand le point d'accès est désactivé.

## Notes de sécurité

- Les légendes, étiquettes, noms de fichiers, chemins et noms d'albums ou de personnes viennent de votre bibliothèque et peuvent contenir du texte écrit pour manipuler un assistant (injection de prompt). Chaque outil est marqué `facet/untrusted_content` et demande au modèle de les traiter comme des données. Ne donnez pas à un assistant qui lit aussi du contenu non fiable le moyen d'agir sur ce qu'il trouve ici.
- Les jetons n'expirent jamais. Révoquez ceux que vous n'utilisez plus.
- Les journaux consignent l'identifiant du jeton, l'outil, le résultat et le nombre de lignes, jamais les arguments ni le jeton.

## Limites connues

- Sur une installation ouverte (sans mot de passe), toute personne qui peut joindre la visionneuse peut créer et révoquer les jetons `_anonymous` partagés. Définissez un mot de passe avant d'activer le point d'accès sur un réseau.
- Les limites de débit et les compteurs d'échecs d'authentification vivent en mémoire dans chaque processus ; avec `viewer.py --workers N`, chaque worker compte séparément.
- `viewer.mcp.bridge` est lu par l'outil `status`, mais rien d'autre ne l'utilise pour l'instant.
