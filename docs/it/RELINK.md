# Ricollegare una foto mancante dopo uno spostamento esplicito

`python database.py --relink-photos` aggiorna i percorsi già presenti nel database Facet dopo che avete spostato i file personalmente. Non sposta, copia, elimina né modifica mai originali o file sidecar e non contatta Immich. È un comando di manutenzione offline per l’operatore che ha accesso al database e alle cartelle configurate. Arrestate prima viewer, scansioni ed editor di file esterni; eseguite un backup del database e rivedete il piano prima di applicarlo.

L’applicazione mantiene il blocco di manutenzione della libreria di Facet per tutta la scrittura nel database. Un altro lavoro sulla libreria produce il codice di uscita 75 senza modificare database o media; un blocco inutilizzabile produce il codice 1. L’anteprima resta in sola lettura e non acquisisce alcun blocco della libreria. Questo blocco coordina i lavori su un solo host; i requisiti offline restano validi per gli altri host e gli editor esterni.

Il database esistente non contiene alcun hash crittografico dei byte del file originale. `phash` e le firme in scala di grigi dei volti manuali non provano l’identità byte per byte. Ogni piano riporta quindi `original_bytes_unknown`. Lo SHA-256 della destinazione identifica soltanto il nuovo file mostrato in anteprima. Applicare afferma esplicitamente che avete identificato in modo indipendente il file spostato corretto; non è mai una corrispondenza verificata automaticamente. Un’affermazione errata può associare annotazioni esistenti all’immagine sbagliata.

Spostare o rinominare un’intera directory esula da questa modalità limitata quando la vecchia directory padre non esiste più. Le directory mancanti non permettono di distinguere uno spostamento intenzionale da un archivio offline. Non ricreate directory padre vuote per aggirare questo controllo.

## Anteprima, revisione, poi applicazione

Create un elenco JSON con percorsi assoluti canonici esatti. Una sorgente mancante deve essere già registrata in Facet; una destinazione deve esistere come immagine e non deve avere ancora una riga di foto:

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
# Anteprima del database in sola lettura; crea un artefatto di revisione privato (0600) ed esclusivo.
python database.py --relink-photos --db library.db --config scoring_config.json \
  --mapping moved.json --plan-out relink-plan.json

# Controllate in relink-plan.json ogni percorso vecchio/nuovo, l’etichetta di identità a byte ignoti, l’hash della destinazione, le
# dimensioni, i riferimenti, i file compagni e i criteri di visibilità.
# Sostituite REVIEWED_PLAN_ID con il plan_id esatto di quell’artefatto dopo la revisione.
python database.py --relink-photos --db library.db --config scoring_config.json \
  --apply-plan relink-plan.json --ack-plan REVIEWED_PLAN_ID \
  --acknowledge-unverified-identity
```

La modalità multiutente richiede anche `--user alice` in entrambi i comandi. È un selettore di ambito per l’operatore, non un sostituto del controllo degli accessi del sistema operativo né un’API autenticata. Entrambi i percorsi devono essere visibili a quell’utente e l’insieme di **tutti** gli utenti che possono vedere la foto deve restare identico. Gli spostamenti da privato a condiviso o altri spostamenti tra utenti vengono rifiutati. Entrambi i percorsi devono trovarsi in directory di scansione, utente o condivise configurate esplicitamente. La configurazione di radici vuota, le radici inaccessibili e `viewer.path_mapping` vengono rifiutati; questo strumento iniziale supporta solo percorsi nativi canonici.

L’applicazione ricontrolla l’intero piano rivisto all’interno di un’unica transazione di scrittura SQLite. File di destinazione, righe di foto, annotazioni, schema, inode del database o criteri di visibilità modificati richiedono una nuova anteprima. Un lotto non riuscito annulla tutte le sue scritture nel database. Un’applicazione riuscita stampa una ricevuta con l’ID del piano. Non memorizza un nuovo ID di risorsa logica né una mappatura di UUID remoti.

## Ciò che segue la foto

Rowid delle foto, valutazioni/Keep/GPS, tag, ID di volti/persone e UUID manuali, confronti, punteggi appresi, preferenze per utente, override, appartenenze fisse agli album/copertine/scelte dei clienti, snapshot di estrazione ed embedding vettoriali mantengono le proprie associazioni. Le chiavi esterne esistenti verso photos vengono rilevate dallo schema reale; una nuova colonna di percorso non registrata viene rifiutata invece di restare orfana in silenzio. Le statistiche derivate vengono invalidate; lo stato di addestramento duraturo resta.

Le voci della cronologia di organizzazione conservano i payload dei percorsi storici originali. I trigger esistenti sulle modifiche di percorso fanno avanzare l’orologio delle revisioni e invalidano le cache di revisione private; una voce che si riferisce al vecchio percorso potrebbe non comparire più o non essere più disponibile per il ripristino dopo il ricollegamento. Il ricollegamento conserva i valori di annotazione e le associazioni correnti, ma non riscrive le azioni passate per renderle applicabili a un percorso diverso.

Tutti i rettangoli manuali vengono conservati ma richiedono una revisione sul nuovo percorso. La vecchia firma approssimativa non può provare i pixel dell’originale mancante. Un indicatore `relink_unverified` impedisce ai normali controlli di firma di cancellare questo stato di revisione; aprite l’editor e salvate esplicitamente ogni rettangolo rispetto al nuovo fotogramma prima che possa essere esportato o sopprimere rilevamenti. Gli ID di rettangoli e persone esistenti vengono conservati.

Lo stato di invio/in sospeso di Immich resta invariato: un’asserzione locale sul nome file non può verificare un’identità remota. Nessuna valutazione remota, cancellazione, appartenenza ad album o UUID viene ricollegata. Rivedete separatamente la mappatura remota prima di sincronizzare. I percorsi storici dei fallimenti di scansione restano storici; i predicati dei filtri degli album intelligenti e le chiavi dei gruppi logici di sequenze non vengono riscritti in silenzio. Le appartenenze statiche e i valori dei gruppi di sequenze/raffiche/duplicati restano intatti.

## File compagni espliciti e rifiuti

Elencate esplicitamente i file compagni; lo strumento non può scoprire file RAW/XMP non indicizzati scomparsi dalla vecchia directory. `sidecar_full` indica `photo.ext.xmp`, `sidecar_basename` indica `photo.xmp`, `sidecar_facet` indica `photo.ext.facet.xmp` e `raw` mantiene una coppia RAW esplicita nella stessa directory e con lo stesso nome base, compatibile con l’attuale selezione. Queste regole sui nomi file convalidano una relazione dichiarata; non provano l’identità dei file. Le foto RAW indicizzate richiedono una propria voce di ricollegamento di primo livello perché le loro annotazioni siano conservate.

Sidecar o file compagni RAW non elencati nella destinazione vengono rifiutati, inclusi i pacchetti di ripiego di Facet e le varianti di maiuscole/minuscole. Vengono rifiutati più candidati RAW e proprietà XMP ambigue, tra cui `IMG.CR2` + `IMG.CR2.jpg` + `IMG.CR2.xmp`, `IMG.CR2` + `IMG.CR2.facet.jpg` + `IMG.CR2.facet.xmp`, collisioni di nomi base e di maiuscole/minuscole o Unicode. Nessun file compagno viene assegnato al primo risultato trovato. I byte dei file compagni esistenti vengono sottoposti a hash, ricontrollati e lasciati intatti. I file compagni mancanti non elencati restano sconosciuti; non interpretate un elenco vuoto come prova che non ne esistessero.

Vengono rifiutate copie con il vecchio originale ancora presente, directory padre vecchie mancanti o illeggibili, foto di destinazione o righe dipendenti già esistenti, mappature ripetute, contenuti di foto o inode di destinazione duplicati, modifiche solo di maiuscole/minuscole o Unicode, link simbolici e cambi di estensione/formato. Le dimensioni canoniche memorizzate, se note, devono corrispondere alla destinazione decodificata. Non viene eseguita alcuna ricerca per similarità o nome file né alcuna riconciliazione automatica.

Limiti: 100 foto, 300 file nominati esplicitamente, 512 MiB per file, 2 GiB di byte di file in totale e 2 MiB di JSON in ingresso o di piano da rivedere. Riducete un lotto quando si raggiunge un limite. La transazione del database è atomica; il file system non è bloccato rispetto ad altre applicazioni, da qui il requisito offline. I test con fixture non dichiarano alcun ciclo completo con un’applicazione esterna reale o un server remoto.

Directory leggibili **non** provano che l’archiviazione sia montata. Un volume non montato può lasciare un punto di montaggio vuoto ma leggibile, indistinguibile da una directory davvero vuota dopo lo spostamento. Il piano riporta esplicitamente `source_mount_status: not_verified`; confermate in modo indipendente che ogni sorgente sia stata spostata e non semplicemente resa non disponibile prima di confermare l’identità. Il comando non rileva ogni condizione di volume offline. I piani da rivedere contengono percorsi completi privati e i criteri di ambito utente; `--plan-out` li crea in modo esclusivo con modalità 0600 su POSIX.

| Opzione | Scopo |
|---|---|
| `--db` | Base dati esistente |
| `--config` | Configurazione risolta |
| `--user` | Utente configurato obbligatorio in modalità multiutente |
| `--mapping` | Percorsi vecchio/nuovo JSON; anteprima |
| `--plan-out` | Creare un piano privato nuovo senza sovrascrivere |
| `--apply-plan` | Applicare un piano esaminato |
| `--ack-plan` | Hash esatto del piano esaminato |
| `--acknowledge-unverified-identity` | Conferma esplicita nonostante i byte originali ignoti |
