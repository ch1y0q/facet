# Agenti IA (MCP)

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · [Deutsch](../de/AGENTS.md) · **Italiano** · [Español](../es/AGENTS.md) · [Português](../pt/AGENTS.md) · [简体中文](../zh/AGENTS.md)

Facet può fungere da server [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), così un assistente IA compatibile con MCP può cercare e ispezionare la tua libreria con gli stessi filtri della galleria. Espone nove strumenti di lettura che non modificano nulla nella libreria e nove strumenti `ui_*` che muovono la scheda del browser già aperta (pagina, filtri, selezione) e non scrivono mai dati della libreria. I token autorizzati possono anche [modificare la libreria](#modificare-la-libreria) (valutazioni, indicatori, tag, album, selezione ed eliminazione) e usare la [camera oscura](#camera-oscura-gruppi-di-selezione).

## Attivarlo

L'endpoint è **disattivato per impostazione predefinita**. Imposta `viewer.mcp.enabled` su `true` in `scoring_config.json` (vedi [Endpoint agente (MCP)](CONFIGURATION.md#endpoint-agente-mcp)) e riavvia il viewer, oppure ricarica la configurazione. Finché è disattivato, `/mcp` e ogni route `/api/mcp/*` rispondono 404. Senza `viewer.password` l'installazione è considerata aperta, anche se `viewer.edition_password` è impostata: i suoi token possono essere solo `readonly`.

L'endpoint è `POST /mcp` sulla porta del viewer: Streamable HTTP, senza stato, risposte JSON semplici. `GET` risponde 405. Solo il ponte della scheda, `/api/mcp/bridge`, è un WebSocket; vedi [Controllare la scheda aperta](#controllare-la-scheda-aperta).

## Creare un token

Il modo più semplice è il browser. Con `viewer.mcp.enabled` attivo, apri il menu dell'account e scegli **Collega un assistente**. Inserisci un **Nome**, scegli **Cosa può fare l'assistente**: **Solo lettura e controllo**, più **Agisci come me** o **Modifica completa** se la tua sessione ha quel livello (un token non può superare la sessione che lo crea), e fai clic su **Crea token**. La finestra mostra poi **Incolla questo nel tuo assistente** con un prompt già pronto che contiene il token. Viene mostrato una sola volta: fai clic su **Copia il prompt**, incollalo nel tuo assistente e fai clic su **Fatto**. **Gestisci i token (N)** elenca i tuoi token con l'ultimo utilizzo e permette di revocarne uno, e una riga di stato indica se questa scheda è connessa e quindi controllabile dagli assistenti. L'elenco dei livelli si limita a ciò che il server concederà: un'installazione aperta offre solo **Solo lettura e controllo**, **Agisci come me** compare solo sulle installazioni multiutente e **Modifica completa** solo in una sessione di modifica. Il prompt indica il livello effettivamente concesso.

Alternativa da script (curl):

Un assistente si autentica con un token personale che inizia con `fct_`. Creane uno con una richiesta autenticata (il token viene restituito **una sola volta**; Facet conserva solo il suo hash SHA-256):

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "my-assistant", "level": "readonly"}'
```

La risposta contiene il testo in chiaro in `token`. `GET /api/mcp/tokens` elenca i tuoi token (mai il segreto) e `DELETE /api/mcp/tokens/{id}` ne revoca uno. Un superadmin può elencare i token di tutti i proprietari con `?all=1` e revocarne qualsiasi. Ogni proprietario può avere al massimo 20 token attivi (oltre, 412). Queste route rifiutano (403) le credenziali di un agente, quindi un assistente non può mai creare, elencare o revocare token.

## Collegare il tuo assistente

Il prompt generato dalla finestra contiene tutto ciò di cui un assistente compatibile con MCP ha bisogno: il nome del server `facet`, l'URL (`http://<host>/mcp`), il trasporto (Streamable HTTP), l'intestazione `Authorization: Bearer fct_...`, il livello di accesso concesso e una chiamata allo strumento `status` per confermare la connessione. Incollalo nel tuo assistente, oppure aggiungi tu stesso quel server al client MCP che usi. Usa HTTPS quando il viewer è raggiungibile oltre la tua macchina, perché il token viaggia in un'intestazione a ogni chiamata.

## Livelli di autorizzazione

Un token viene creato con un livello concesso: `readonly`, `user` o `edition`. Il livello **effettivo** è ricalcolato a ogni chiamata come il più basso tra quello del token e quello attuale del suo proprietario:

- Installazioni con password unica: `user` è limitato a `readonly` alla creazione, perché questa modalità non ha un livello intermedio. Un token `edition` richiede una sessione di edizione e funziona solo finché la password di edizione non cambia.
- Installazioni multiutente: il token `edition` di un utente poi retrocesso scende a `user`; una promozione non porta mai un token oltre il livello concesso.
- Installazioni aperte (nessun `viewer.password`, anche se `viewer.edition_password` è impostata): i token sono sempre `readonly` e appartengono a un proprietario condiviso `_anonymous`.
- Le installazioni con password unica non hanno il livello `user`: il livello effettivo è `edition` o `readonly`, quindi gli strumenti contrassegnati `user` in [Modificare la libreria](#modificare-la-libreria) richiedono anch'essi un token `edition`. Uno strumento `user` chiamato con un token di livello inferiore risponde `forbidden_level`, indicando che serve `edition`.
- Ogni strumento ha il proprio livello minimo, verificato prima di qualsiasi lettura o scrittura; un token di livello inferiore riceve `forbidden_level`.

Un token decade automaticamente quando cambiano le credenziali del suo proprietario: la password del viewer o di edizione in modalità password unica, la password del proprietario in modalità multiutente, oppure l'eliminazione del suo account. Riceve allora un 401 all'ingresso.

## Strumenti

I nove strumenti dati sono di sola lettura:

| Strumento | Cosa fa |
|------|--------------|
| `search_photos` | Filtra e ordina la libreria come la galleria, applicando le esclusioni predefinite del visualizzatore salvo che il filtro le imposti (riporta `hidden_summary`). Mostrato per impostazione predefinita nella scheda aperta (vedi sotto); `fields` aggiunge qualsiasi colonna della foto |
| `semantic_search` | Trova foto per significato, o per parole nelle didascalie con `scope: "text"` (non mostrato nella scheda) |
| `get_photo` | Dettaglio completo di una foto dal suo percorso (senza istogramma) |
| `similar_photos` | Foto simili a una foto, per embedding visivo o per colore; `min_similarity` (da 0 a 1) imposta la soglia |
| `filter_options` | Il vocabolario accettato da un filtro: fotocamere, obiettivi, tag, persone, pattern, categorie, momenti narrativi, tipi di scarto, intervalli delle metriche |
| `list_persons` | Persone riconosciute, filtrabili per nome |
| `list_albums` | Album visibili al proprietario del token |
| `library_stats` | Statistiche della libreria: `kind` sceglie il riepilogo di dimensione e punteggi (predefinito) o qualsiasi dato della pagina Statistiche (vedi sotto) |
| `status` | Chi è il token, il suo livello effettivo e i flag del server e le schede aperte che può pilotare |

In ogni oggetto filtro, `show_rejected` è un booleano: `true` elenca solo le foto scartate, `false` o omesso dà l'elenco normale.

## I risultati compaiono nella tua scheda

- `search_photos`, `semantic_search` e `similar_photos` accettano `show` (predefinito `true`). Dopo una ricerca riuscita sulla prima pagina, il server applica la stessa query alla scheda Facet aperta, sostituendone i filtri: vedi ciò che l'assistente ha trovato senza dover chiedere. Agli assistenti si dice di non chiedere mai se aprire o mostrare i risultati; `show: false` serve per le sonde intermedie e i conteggi, e l'ultima ricerca mostrata è quella che vedi.
- Il risultato contiene `shown_in_tab`: `{"applied": true, "tab_id", "keys", "total"}`, oppure `{"applied": false, "reason"}` dove il motivo è `no_tab`, `bridge_disabled`, `tab_outdated`, `tab_timeout` (la scheda può ancora applicarla), `forbidden`, `page_not_first`, `empty_result`, `unsupported_filters` (con `keys`) o `invalid_combination`. Una visualizzazione fallita non fa mai fallire la ricerca. Passa `tab_id` per scegliere una scheda. Tutti i motivi: `error` (la visualizzazione stessa è fallita), `bridge_disabled`, `page_not_first`, `empty_result`, `invalid_combination`, `unsupported_filters` (con `keys`; per `semantic_search` sono `scope` o `threshold`, una soglia oltre 0,5 che il cursore della barra laterale non può esprimere) e i codici restituiti dal bridge della scheda (`no_tab`, `tab_outdated`, `tab_timeout`, `forbidden`, `invalid_input`, `upstream_error`). La scheda pagina da sola, quindi per una ricerca semantica può mostrare più righe di quelle ricevute dall'assistente. Quando le righe vengono accorciate, `next_page` (con `suggested_per_page`) indica la pagina che continua esattamente dopo l'ultima riga restituita oppure, se le pagine non possono esprimerlo, `next_offset` la dà come offset di riga.
- Viene mostrata solo la prima pagina (la scheda pagina da sola durante lo scorrimento) e un risultato vuoto non viene mostrato, così mantieni la vista precedente. Una ricerca con filtri per cui la barra laterale della galleria non ha un campo (`exclude_tags`, `require_tags`, `is_silhouette`, `junk_kind`, `narrative_moment`, `min_rating`, `min_aggregate`, `show_rejected: true`) non viene applicata parzialmente, e nemmeno `semantic_search` con `scope: "text"` viene mostrata.
- Una visualizzazione lascia `/culling`, `/compare` e `/photo` per la galleria, azzera una selezione dell'intera vista e, in una pagina di album, torna prima alla galleria, così i filtri salvati di un album non vengono mai sovrascritti. Una ricerca il cui conteggio alimenta `expected_count` di uno strumento di scrittura deve usare `show: false`.
- Le righe contengono fotocamera, obiettivo, apertura, tempo di posa, ISO, lunghezza focale e `is_monochrome`. `fields` (sui tre strumenti di ricerca) aggiunge qualsiasi altra colonna della foto tranne i dati di immagine e di embedding, ad esempio `leading_lines_score`; `learned_score` è valorizzato solo ordinando per esso. Quando il limite di byte accorcia le righe, il risultato aggiunge `returned` (e `next_offset` o `suggested_per_page`).
- `library_stats` accetta `kind` (predefinito `overview`: dimensione, conteggi per tipo e riepilogo dei punteggi). Gli altri valori sono di sola lettura e restituiscono i dati della pagina Statistiche; le liste lunghe sono tagliate a 50 voci con `truncated: true`:

| Valore di kind | Dati |
|------|------|
| `score_distribution`, `top_cameras`, `categories`, `gear`, `stats_settings`, `timeline`, `correlations` | I pannelli della pagina Statistiche; accettano `date_from`, `date_to` e `category`. `correlations` accetta anche `x`, `y` (elenco separato da virgole), `group_by` e `min_samples` |
| `category_breakdown`, `category_weights`, `category_correlations`, `category_overlap` | Statistiche per categoria (senza parametri) |
| `timeline_dates`, `timeline_months` | Numero di foto per giorno o per mese; richiedono `year` (`timeline_dates` accetta anche `month`) |
| `timeline_years` | Numero di foto per anno |

## Controllare la scheda aperta

Accanto agli strumenti dati, il server elenca sempre nove strumenti `ui_*` che agiscono sulla scheda Facet che hai aperto in un browser: cambiano pagina, modificano filtri o selezione e rileggono ciò che vedi. Non scrivono mai dati della libreria, quindi basta un token `readonly`.

| Strumento | Cosa fa |
|-----------|---------|
| `ui_navigate` | Andare a una pagina (galleria, persone, album, statistiche, ...) |
| `ui_set_gallery_filters` | Unire una modifica ai filtri e all'ordinamento della galleria (`null` rimuove un filtro, `replace: true` riparte da zero) |
| `ui_get_gallery_view` | Route, filtri attivi, totale dei risultati, primi percorsi di foto visibili e numero di foto selezionate |
| `ui_open_photo` | Aprire una foto |
| `ui_select_photos` | Selezionare `paths` espliciti, o l'intera vista filtrata con `select_view: true`, in modalità `replace`, `add` o `remove` |
| `ui_clear_selection` | Svuotare la selezione |
| `ui_get_selection` | Lo `scope` (`paths` o `view`) e il `count`, con i `paths` oppure, per una vista, i `filters` e gli `excluded_paths` |
| `ui_next_page` | Caricare la pagina successiva della galleria |
| `ui_show_culling_group` | Aprire la camera oscura su un gruppo, identificato da `(type, group_id)` (account edition) |

Come funziona:

- Finché sei connesso e `viewer.mcp.enabled` e `viewer.mcp.bridge` sono entrambi `true`, ogni scheda Facet apre un WebSocket della stessa origine verso `/api/mcp/bridge` e si autentica con la tua sessione nel primo messaggio. Il ponte è attivo per impostazione predefinita; imposta `viewer.mcp.bridge` su `false` per disattivarlo, e gli strumenti `ui_*` risponderanno con un errore esplicito.
- Uno strumento raggiunge solo le schede del proprietario del token. Con una password unica tutte le sessioni sono lo stesso utente; su un'installazione aperta ogni scheda appartiene all'utente condiviso `_anonymous`, comprese le sessioni edition.
- Ogni scheda porta il livello della sessione che l'ha aperta e un token pilota solo le schede di livello pari o superiore al proprio livello effettivo: un token `edition` non usa mai una scheda con sessione di sola consultazione, mentre un token `readonly` può pilotare una scheda `edition`. Con una password unica un token è inoltre limitato dalla sessione che lo ha creato: un token creato da una sessione di sola consultazione raggiunge solo le schede di consultazione, mai la scheda `edition` (un token precedente a questa regola è limitato al proprio livello). Una scheda può essere sostituita solo da una di livello pari o superiore: una sessione di sola consultazione che riusa il `tab_id` di una scheda `edition` viene rifiutata con 4409 e, oltre il limite di schede per utente, esce per prima la scheda di livello più basso. `status` elenca solo le schede che il token può pilotare. `status` riporta anche `out_of_reach_tabs`, il numero di schede aperte che questo token non può pilotare.
- Con più schede aperte viene usata l'ultima che ha avuto il focus e il campo `tab` del risultato lo indica. Passa `tab_id` (elencato da `status`) per sceglierne un'altra.
- Una scheda rifiuta ciò che il suo account non può fare (per esempio `/culling` per un account senza edition) e lo strumento restituisce quel rifiuto.
- Ciò che una scheda restituisce non è affidabile: profondità, lunghezza delle stringhe e delle liste sono limitate e il tutto è contenuto da `max_bytes`.
- Errori: `no_tab` (nessuna scheda collegata, o ponte disattivato), `tab_timeout` (nessuna risposta entro `call_timeout_s`) e `tab_outdated` (la scheda aperta non conosce lo strumento; ricarica la pagina dopo un aggiornamento di Facet).
- Il ponte accetta prima il WebSocket e poi lo rifiuta con un codice di chiusura anziché uno stato HTTP: 4404 se l'endpoint o il ponte è disattivato (la scheda resta allora disconnessa finché la pagina non viene ricaricata), 4403 se `Origin` manca o non è consentito, 4401 per una sessione mancante o rifiutata.
- Un reverse proxy deve inoltrare l'upgrade WebSocket per `/api/mcp/bridge`; vedi [Distribuzione](DEPLOYMENT.md). Se riscrive l'intestazione `Host`, indica l'origine pubblica in `viewer.mcp.allowed_origins` (per esempio `["https://photos.example.com"]`), perché l'origine della pagina deve corrispondere all'host o essere in elenco.
- Il registro delle schede è per processo, quindi il ponte richiede un solo worker (il valore predefinito).

In aggiunta:

- `ui_set_gallery_filters` porta prima alla galleria se è aperta un'altra pagina, poi applica la patch. Rifiuta per intero (`invalid_input`) una patch che nomina un filtro che la scheda non sa controllare; per quelli usa `search_photos`. In una pagina di album, `replace: true` torna prima alla galleria, così i filtri salvati dell'album non vengono sovrascritti. Accetta anche `semantic_query`, `semantic_threshold` (da 0 a 0,5), `similar_to`, `similarity_mode` e `min_similarity` (da 0 a 1); `similar_to` e `semantic_query` non si combinano.
- `ui_get_gallery_view`, `ui_next_page` e `ui_select_photos` con `select_view` richiedono che la galleria (o un album) sia la pagina aperta, altrimenti rispondono `no_active_view`; chiama prima `ui_navigate` verso `/`. Dai a `ui_select_photos` esattamente uno tra `paths` e `select_view`.
- `no_tab` significa anche che nessuna scheda Facet è aperta: apri Facet in un browser e accedi. La riga di stato nella finestra **Collega un assistente** mostra se questa scheda è connessa; lo strumento `status` elenca le schede aperte e i loro id.
- Una scheda smette di riconnettersi quando la sua sessione viene rifiutata (accedi di nuovo), e aspetta il tuo ritorno se un'altra tua scheda ha preso il suo posto.
- Il ponte della scheda si connette solo se il server lo dichiara disponibile (l'endpoint è attivo e `viewer.mcp.bridge` è true); con il ponte disattivato le schede non si connettono affatto.
- `ui_set_gallery_filters` rifiuta un nome di filtro sconosciuto con `invalid_input`, e anche una patch che indica sia `category` sia `type`, oppure sia `person` sia `person_id`. Offre solo i filtri che la galleria sa mostrare; per gli altri usa `search_photos`.
- `ui_navigate` apre solo le pagine statiche dell'app: pagina di accesso, pagine condivise, URL esterni e percorsi sconosciuti sono rifiutati (`invalid_input`), e le pagine riservate alla modifica sono rifiutate a una sessione senza modifica.
- `ui_select_photos` in modalità `remove` con una selezione dell'intera vista ignora i percorsi fuori dalla vista caricata e li elenca come `not_in_view` nel risultato.

## WebMCP nella pagina (agenti del browser)

Indipendentemente dall'endpoint `/mcp`, una scheda con accesso effettuato offre gli stessi strumenti `ui_*` anche agli agenti che vivono nel browser stesso, tramite l'API W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) (`document.modelContext`). Un assistente nativo del browser vede quindi esattamente gli strumenti elencati sopra, li esegue nella scheda che stai guardando e non richiede alcun token.

- **Solo contesto sicuro.** Facet registra gli strumenti solo su HTTPS o `localhost`. Su HTTP semplice gli strumenti nella pagina non vengono offerti; la connessione con token qui sopra continua a funzionare.
- Registrati quando `viewer.mcp.enabled` è true e hai effettuato l'accesso, rimossi all'uscita.
- L'oggetto è `document.modelContext` (il vecchio alias `navigator.modelContext` non è fornito). È un polyfill, installato solo se il browser non ne ha uno nativo, e non può essere disinstallato: può esistere prima dell'accesso senza alcuno strumento Facet e resta dopo l'uscita con un elenco di strumenti vuoto.
- Gli strumenti fanno le stesse cose, limitate dallo stesso livello di account, della tabella qui sopra.

## Modificare la libreria

Gli strumenti di scrittura stanno accanto a quelli di lettura nella stessa lista `/mcp`. Ciascuno passa dalle route `/api` del viewer, quindi le protezioni della route restano valide, e ciascuno viene conteggiato nel budget `write_rate_per_min`. Il livello è il più basso livello effettivo che può chiamare lo strumento (vedi [Livelli di autorizzazione](#livelli-di-autorizzazione)).

| Strumento | Livello | Cosa fa | Limiti |
|-----------|---------|---------|--------|
| `set_rating` | `user` | Imposta la valutazione a stelle (0-5) delle foto | 50 percorsi |
| `set_favorite` | `user` | Segna o toglie il preferito alle foto (segnare toglie lo scarto) | 50 percorsi |
| `set_rejected` | `user` | Scarta o annulla lo scarto delle foto (scartare rimuove valutazione e preferito) | 50 percorsi |
| `batch_set_rating` | `edition` | Imposta la valutazione di molte foto | 1000 percorsi, oppure `filters` |
| `batch_set_favorite` | `edition` | Segna molte foto come preferite | 1000 percorsi, oppure `filters` |
| `batch_set_rejected` | `edition` | Scarta molte foto | 1000 percorsi, oppure `filters` |
| `add_tags` | `edition` | Aggiunge tag manuali (separati dai tag IA) | 10 tag; 1000 percorsi, oppure `filters` |
| `remove_tags` | `edition` | Rimuove tag manuali | 10 tag; 1000 percorsi, oppure `filters` |
| `create_album` | `edition` | Crea un album vuoto (non idempotente: due volte crea due album) | |
| `album_add_photos` | `edition` | Aggiunge foto a un album (quelle già presenti sono ignorate) | 1000 percorsi |
| `album_remove_photos` | `edition` | Toglie foto da un album; le foto non sono toccate | 1000 percorsi |
| `junk_list` | `readonly` | Elenca i candidati della pulizia degli scarti, eventualmente di un solo `kind` | 100 per pagina |
| `junk_reject` | `edition` | Scarta i candidati della pulizia (come `batch_set_rejected`) | 1000 percorsi |
| `junk_clear` | `edition` | Conserva i candidati: li segna come valutati e a posto perché escano dalla coda | 50 percorsi |
| `cull_apply` | `edition` | Copia le foto da tenere, oppure sposta o cestina quelle scartate ([anteprima, poi conferma](#azioni-distruttive-anteprima-poi-conferma)) | 10000 percorsi, oppure `filters` |
| `delete_photos` | `edition` | Cestina i file ed elimina le loro righe dalla libreria ([anteprima, poi conferma](#azioni-distruttive-anteprima-poi-conferma)) | 1000 percorsi |

- **Gli strumenti `user` richiedono un token edition su un'installazione con password unica**, che non ha un livello intermedio (vedi [Livelli di autorizzazione](#livelli-di-autorizzazione)).
- **Semantica di impostazione.** Gli strumenti per singola foto leggono lo stato attuale e scrivono solo una differenza, quindi ripetere una chiamata è innocuo; ogni percorso riporta `changed` o `already`. Procedono un percorso alla volta e si fermano al primo `library_busy`, `outcome_unknown` o `forbidden_level`, riportando `affected`, i `results` per percorso e `not_attempted`. Gli strumenti batch impostano lo stesso stato.
- **Scegliere le foto.** Gli strumenti batch, dei tag e `cull_apply` accettano O `paths` O `filters` (l'oggetto filtri di `search_photos`), più un elenco `exclude` facoltativo. Un bersaglio `filters` deve avere `expected_count`, il numero di corrispondenze dei filtri prima di applicare `exclude` (il `total` di `search_photos`). Facet ricalcola prima i filtri e non scrive nulla se i numeri differiscono (`invalid_input`, con `actual_count`).
- **Di chi è lo stato.** Valutazioni, preferiti e scarti sono quelli del proprietario del token.
- **File saltati.** Quando `cull_apply` o `delete_photos` riporta una lista `skipped` non vuota, il risultato contiene anche un `skipped_reason`: questi percorsi della libreria non hanno alcun file leggibile su disco (mancante, spostato o fuori dalle cartelle analizzate) e per loro non è stato fatto nulla.

### Azioni distruttive: anteprima, poi conferma

`cull_apply` (`copy_keeps`, `move_rejects`, `trash_rejects`) e `delete_photos` sono contrassegnati `destructiveHint` e girano come simulazione se non chiamati con `dry_run: false`.

1. La simulazione non modifica nulla ed elenca i file che copierebbe, sposterebbe o cestinerebbe (le liste lunghe sono troncate a `max_rows`, con un `<key>_count`). Per `move_rejects`, `trash_rejects` e `delete_photos` restituisce anche un valore `confirm`, valido per `confirm_expires_in_s` (5 minuti) e per un solo uso.
2. La chiamata reale (`dry_run: false`) deve passare quel `confirm`. Facet ricalcola l'insieme di file e le opzioni e li confronta con quelli per cui il valore è stato emesso. Se qualcosa è cambiato, il valore è nullo e la chiamata risponde `confirmation_required`: rifai la simulazione.
3. `copy_keeps` non richiede `confirm`: scrive solo copie. Per impostazione predefinita parte comunque con una simulazione.

Il valore `confirm` è legato al token, all'azione e all'esatto insieme di file più le opzioni. Vive in memoria in un solo processo, quindi un riavvio scarta tutti i valori in sospeso.

**Pratica consigliata:** mostra sempre all'utente il riepilogo della simulazione (conteggi ed elenco dei file) e ottieni la sua approvazione esplicita prima della chiamata `dry_run: false`. Non confermare mai di propria iniziativa.

- `move_rejects` e `trash_rejects` agiscono solo sulle foto che il proprietario ha scartato; le altre sono riportate come `excluded_by_state`. I file RAW e `.xmp` associati (`include_companions`) e gli altri fotogrammi di un bracketing o di un panorama (`include_sequence_siblings`) non sono toccati se non lo attivi.
- `delete_photos` invia i file al cestino di sistema ed **elimina le loro righe dalla libreria**: punteggi, tag e valutazioni non sono recuperabili, anche se i file lo sono.
- **Prerequisiti.** `trash_rejects` e `delete_photos` richiedono `viewer.cull.allow_trash` impostato a `true` (predefinito `false`; altrimenti la chiamata è rifiutata). Il `target_dir` di `copy_keeps` e `move_rejects` deve trovarsi in una posizione di esportazione consentita: `viewer.export.allowed_target_dirs` più le tue directory di scansione (vedi [Destinazioni di esportazione e scarto](CONFIGURATION.md#destinazioni-di-esportazione-e-scarto)).

## Camera oscura (gruppi di selezione)

Gli strumenti della camera oscura rispecchiano la pagina `/culling`. Tutti richiedono il livello `edition`, anche quelli che si limitano a elencare.

| Strumento | Cosa fa |
|-----------|---------|
| `list_culling_groups` | Elenca i gruppi (`burst`, `similar`, `scene`, `bracket`, `panorama`, `hdr_panorama`) con foto e punteggi, ordinabili e limitabili per album o intervallo di date |
| `culling_profiles` | I preset di selezione per genere e quello predefinito |
| `suggest_culling_profile` | Indica il preset adatto a un album o a un intervallo di scatto |
| `keeper_hints` | Indicazioni per foto «in questa raffica esiste uno scatto migliore» per fino a 100 percorsi (vuote se nessuna testa di classificazione è addestrata) |
| `auto_cull` | Selezione automatica di un ambito con un budget di foto da tenere: prima l'anteprima, poi l'applicazione con il valore `confirm` |
| `confirm_culling_groups` | Conferma fino a 20 gruppi: tiene i loro `keep_paths`, scarta il resto dei `paths` |

- **Un gruppo è identificato dalla coppia `(type, group_id)`**, mai dal solo `group_id`: gli id dei gruppi simili sono traslati quando vengono uniti alle raffiche.
- **Il valore predefinito `group_by: "all"` restituisce solo raffiche e gruppi simili.** Richiedi esplicitamente `scene`, `bracket`, `panorama` o `hdr_panorama`.
- **Una pagina viene ridotta per stare in `max_bytes` accorciando l'elenco `photos` di ogni gruppo, mai eliminando gruppi.** `photo_count` resta la dimensione reale, `photos_truncated` segnala un gruppo con l'elenco tagliato e `has_more` indica se segue un'altra pagina.
- **Bracketing, panorami e panorami HDR si tengono interi.** In `confirm_culling_groups`, `keep_paths` deve coincidere con `paths` per questi tipi (altrimenti `invalid_input`), e `auto_cull` non li divide mai.
- **Un `keep_paths` vuoto scarta ogni fotogramma del gruppo.** La prima chiamata risponde allora `confirmation_required` con un valore `confirm`; mostralo all'utente, poi ripeti la chiamata con quel valore. Se un lotto si ferma su `forbidden_level`, `library_busy` o `rate_limited`, vengono riportati i gruppi già completati.
- **`auto_cull` mostra un'anteprima per impostazione predefinita** e restituisce la ripartizione tenere/scartare per gruppo più un valore `confirm` (solo se qualcosa verrebbe scartato). L'applicazione ricalcola il piano e lo rifiuta con `confirmation_required` se è cambiato dopo l'anteprima o se è troppo grande per essere confermato come un solo insieme (restringilo con `album_id`, `date_from` e `date_to`, oppure `group_by`). I fotogrammi scartati alimentano il classificatore personale come ogni selezione manuale.
- Chiama `ui_show_culling_group` per mostrare un gruppo all'utente nella sua scheda aperta (vedi [Controllare la scheda aperta](#controllare-la-scheda-aperta)).

## Risultati, limiti ed errori

Ogni risultato è una busta JSON: `{"ok": true, "data": ...}` oppure `{"ok": false, "error": "<code>", "message": "..."}`. Gli elenchi restituiscono `data.rows` (un insieme compatto e fisso di campi per foto) più `total`. Il risultato di una ricerca contiene anche `shown_in_tab`, e un risultato accorciato dal limite di byte contiene `returned`.

- **Tetti:** al massimo `max_rows` righe e `max_bytes` byte serializzati. Le ultime righe vengono scartate e si imposta `truncated: true`. Un risultato senza righe che supera `max_bytes` diventa un errore `too_large`.
- **Limite di frequenza:** `rate_per_min` chiamate al minuto per token per la lettura. Gli strumenti di scrittura attingono a un budget separato, `write_rate_per_min` (predefinito 30), così le ricerche non affamano le scritture e viceversa; la simulazione di `cull_apply` e `delete_photos` conta come scrittura, l'anteprima di `auto_cull` come lettura. Oltre: `rate_limited` con `retry_after_s`. Dieci tentativi bearer falliti al minuto dallo stesso indirizzo ricevono 429.
- **Codici di errore:** `forbidden_level` (endpoint disattivato, token non valido o livello troppo basso), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `confirmation_required`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`.
- **I codici più recenti:** `confirmation_required` (una chiamata distruttiva non ha un valore `confirm` valido per questo preciso insieme: rifai una simulazione, mostra il risultato all'utente, poi riprova), `outcome_unknown` (una scrittura è scaduta o la connessione è caduta, quindi può essere avvenuta o no: rileggi lo stato prima di riprovare, non ripetere mai alla cieca), `library_busy` (la libreria è occupata da un altro lavoro: riprova tra un istante).
- **Codici HTTP all'ingresso:** 401 per token mancante o sconosciuto, 403 per una richiesta di browser da un'altra origine o per le credenziali di un agente su `/api/mcp/tokens`, 404 quando è disattivato. Il ponte delle schede risponde invece con codici di chiusura.

## Note di sicurezza

- Didascalie, tag, nomi di file, percorsi e nomi di album e persone provengono dalla tua libreria e possono contenere testo scritto per manipolare un assistente (prompt injection). Ogni strumento è marcato `facet/untrusted_content` e dice al modello di trattarli come dati. Non dare a un assistente che legge anche contenuti non attendibili un modo per agire su ciò che trova qui.
- I token non scadono mai. Revoca quelli che non usi più.
- I log registrano l'id del token, lo strumento, l'esito e il numero di righe, mai gli argomenti né il token.

## Limitazioni note

- Su un'installazione aperta (senza password), chiunque raggiunga il viewer può creare e revocare i token `_anonymous` condivisi. Imposta una password prima di attivare l'endpoint su una rete. Il ponte della scheda amplia il rischio: un client non browser può inviare un `Origin` inventato e un token nullo, registrare una scheda `_anonymous` con il focus, rispondere alle chiamate `ui_*` con dati a sua scelta ed espellere schede reali tramite il limite di 8 schede.
- I limiti di frequenza e i contatori di autenticazioni fallite stanno in memoria in ciascun processo; con `viewer.py --workers N` ogni worker conta separatamente.
- Il registro delle schede vive in memoria in un solo processo. Usa un solo worker (`viewer.py --workers 1`, il valore predefinito) se ti affidi agli strumenti `ui_*`; con più worker una chiamata può raggiungere un processo che non conosce la tua scheda e rispondere `no_tab`.
- Un utente può avere al massimo 8 schede collegate; aprirne una nona chiude la più vecchia.
