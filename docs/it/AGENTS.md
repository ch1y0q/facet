# Agenti IA (MCP)

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · [Deutsch](../de/AGENTS.md) · **Italiano** · [Español](../es/AGENTS.md) · [Português](../pt/AGENTS.md) · [简体中文](../zh/AGENTS.md)

Facet può fungere da server [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), così un assistente IA come Claude Code può cercare e ispezionare la tua libreria con gli stessi filtri della galleria. L'endpoint è di sola lettura: espone nove strumenti di lettura e non modifica nulla nella tua libreria.

## Attivarlo

L'endpoint è **disattivato per impostazione predefinita**. Imposta `viewer.mcp.enabled` su `true` in `scoring_config.json` (vedi [Endpoint agente (MCP)](CONFIGURATION.md#endpoint-agente-mcp)) e riavvia il viewer, oppure ricarica la configurazione. Finché è disattivato, `/mcp` e ogni route `/api/mcp/*` rispondono 404.

L'endpoint è `POST /mcp` sulla porta del viewer: Streamable HTTP, senza stato, risposte JSON semplici. `GET` risponde 405. In un reverse proxy non servono intestazioni WebSocket.

## Creare un token

Un assistente si autentica con un token personale che inizia con `fct_`. Creane uno con una richiesta autenticata (il token viene restituito **una sola volta**; Facet conserva solo il suo hash SHA-256):

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "claude-code", "level": "readonly"}'
```

La risposta contiene il testo in chiaro in `token`. `GET /api/mcp/tokens` elenca i tuoi token (mai il segreto) e `DELETE /api/mcp/tokens/{id}` ne revoca uno. Un superadmin può elencare i token di tutti i proprietari con `?all=1` e revocarne qualsiasi. Ogni proprietario può avere al massimo 20 token attivi (oltre, 412). Queste route rifiutano le credenziali di un agente, quindi un assistente non può mai creare, elencare o revocare token.

## Collegare Claude Code

```bash
claude mcp add --transport http facet http://localhost:5000/mcp --header "Authorization: Bearer fct_YOUR_TOKEN"
```

Gli strumenti compaiono poi come `mcp__facet__search_photos` e così via. Usa HTTPS quando il viewer è raggiungibile oltre la tua macchina, perché il token viaggia in un'intestazione a ogni chiamata.

## Livelli di autorizzazione

Un token viene creato con un livello concesso: `readonly`, `user` o `edition`. Il livello **effettivo** è ricalcolato a ogni chiamata come il più basso tra quello del token e quello attuale del suo proprietario:

- Installazioni con password unica: `user` è limitato a `readonly` alla creazione, perché questa modalità non ha un livello intermedio. Un token `edition` richiede una sessione di edizione e funziona solo finché la password di edizione non cambia.
- Installazioni multiutente: il token `edition` di un utente poi retrocesso scende a `user`; una promozione non porta mai un token oltre il livello concesso.
- Installazioni aperte (nessuna password): i token sono sempre `readonly` e appartengono a un proprietario condiviso `_anonymous`.

Un token decade automaticamente quando cambiano le credenziali del suo proprietario: la password del viewer o di edizione in modalità password unica, la password del proprietario in modalità multiutente, oppure l'eliminazione del suo account. Riceve allora un 401 all'ingresso.

## Strumenti

Tutti e nove gli strumenti registrati sono di sola lettura:

| Strumento | Cosa fa |
|------|--------------|
| `search_photos` | Filtra e ordina la libreria come la galleria, applicando i nascondimenti predefiniti del viewer salvo che il filtro li imposti (riporta `hidden_summary`) |
| `semantic_search` | Trova foto per significato, o per parole nelle didascalie con `scope: "text"` |
| `get_photo` | Dettaglio completo di una foto dal suo percorso (senza istogramma) |
| `similar_photos` | Foto simili a una foto, per embedding visivo o per colore |
| `filter_options` | Il vocabolario accettato da un filtro: fotocamere, obiettivi, tag, persone, pattern, categorie, momenti narrativi, tipi di scarto, intervalli delle metriche |
| `list_persons` | Persone riconosciute, filtrabili per nome |
| `list_albums` | Album visibili al proprietario del token |
| `library_stats` | Dimensione della libreria, conteggi per tipo e panoramica dei punteggi |
| `status` | Chi è il token, il suo livello effettivo e i flag del server |

## Risultati, limiti ed errori

Ogni risultato è una busta JSON: `{"ok": true, "data": ...}` oppure `{"ok": false, "error": "<code>", "message": "..."}`. Gli elenchi restituiscono `data.rows` (un insieme compatto e fisso di campi per foto) più `total`.

- **Tetti:** al massimo `max_rows` righe e `max_bytes` byte serializzati. Le ultime righe vengono scartate e si imposta `truncated: true`. Un risultato senza righe che supera `max_bytes` diventa un errore `too_large`.
- **Limite di frequenza:** `rate_per_min` chiamate al minuto per token (esiste un budget separato, `write_rate_per_min`, per le chiamate di scrittura). Oltre: `rate_limited` con `retry_after_s`. Dieci tentativi bearer falliti al minuto da un indirizzo danno 429.
- **Codici di errore:** `forbidden_level` (endpoint disattivato, token non valido o livello insufficiente), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `too_large`.
- **Codici HTTP all'ingresso:** 401 per token mancante o sconosciuto, 403 per una richiesta di browser da un'altra origine, 404 quando è disattivato.

## Note di sicurezza

- Didascalie, tag, nomi di file, percorsi e nomi di album e persone provengono dalla tua libreria e possono contenere testo scritto per manipolare un assistente (prompt injection). Ogni strumento è marcato `facet/untrusted_content` e dice al modello di trattarli come dati. Non dare a un assistente che legge anche contenuti non attendibili un modo per agire su ciò che trova qui.
- I token non scadono mai. Revoca quelli che non usi più.
- I log registrano l'id del token, lo strumento, l'esito e il numero di righe, mai gli argomenti né il token.

## Limitazioni note

- Su un'installazione aperta (senza password), chiunque raggiunga il viewer può creare e revocare i token `_anonymous` condivisi. Imposta una password prima di attivare l'endpoint su una rete.
- I limiti di frequenza e i contatori di autenticazioni fallite stanno in memoria in ciascun processo; con `viewer.py --workers N` ogni worker conta separatamente.
- `viewer.mcp.bridge` è letto dallo strumento `status`, ma per ora nient'altro lo usa.
