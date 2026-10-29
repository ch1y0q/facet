# Ricollegare una foto mancante dopo uno spostamento esplicito

`python database.py --relink-photos` aggiorna i percorsi nel database di Facet dopo che avete spostato i file personalmente. Non sposta, copia, elimina né modifica mai originali o sidecar e non contatta mai Immich. È un comando di manutenzione offline.

Prima di applicare un piano:

- Arrestate il viewer, le scansioni e gli editor di file esterni.
- Eseguite un backup del database.
- Rivedete il piano.

L'applicazione acquisisce il blocco della libreria di Facet. Se è in corso un altro lavoro sulla libreria, termina con il codice di uscita 75 senza modificare nulla; un blocco inutilizzabile produce il codice 1. L'anteprima è in sola lettura e non acquisisce alcun blocco. Il blocco copre solo i lavori su un singolo host.

> **Avvertenza:** Facet non memorizza alcun hash dei byte del file originale, quindi non può provare che il nuovo file sia quello spostato. Ogni piano riporta `original_bytes_unknown`; `phash` e le firme dei volti manuali non provano l'identità. Lo SHA-256 della destinazione identifica soltanto il file mostrato in anteprima. Applicare afferma che avete verificato personalmente la corrispondenza. Un'affermazione errata associa annotazioni esistenti all'immagine sbagliata.

Spostare o rinominare un'intera directory non è supportato quando la vecchia directory padre non esiste più. Non ricreate directory padre vuote per aggirare questo controllo.

## Anteprima, revisione, poi applicazione

Create un elenco JSON di percorsi assoluti canonici esatti. Ogni sorgente deve essere già in Facet. Ogni destinazione deve esistere come immagine e non deve avere ancora una riga di foto:

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

# Controllate in relink-plan.json ogni percorso vecchio/nuovo, l'etichetta di identità a byte ignoti, l'hash della destinazione, le
# dimensioni, i riferimenti, i file compagni e i criteri di visibilità.
# Sostituite REVIEWED_PLAN_ID con il plan_id esatto di quell'artefatto dopo la revisione.
python database.py --relink-photos --db library.db --config scoring_config.json \
  --apply-plan relink-plan.json --ack-plan REVIEWED_PLAN_ID \
  --acknowledge-unverified-identity
```

In modalità multiutente, aggiungete `--user alice` a entrambi i comandi. Seleziona l'ambito di quale utente controllare; non è un controllo degli accessi. Regole:

- Entrambi i percorsi devono essere visibili a quell'utente.
- L'insieme di **tutti** gli utenti che possono vedere la foto deve restare identico. Gli spostamenti da privato a condiviso e gli altri spostamenti tra utenti vengono rifiutati.
- Entrambi i percorsi devono trovarsi in directory di scansione, utente o condivise configurate esplicitamente.
- La configurazione di radici vuota, le radici inaccessibili e `viewer.path_mapping` vengono rifiutati. Sono supportati solo percorsi nativi canonici.

L'applicazione ricontrolla l'intero piano in un'unica transazione del database. Se file di destinazione, righe di foto, annotazioni, schema, file del database o visibilità sono cambiati, eseguite una nuova anteprima. Un lotto non riuscito annulla tutte le sue scritture nel database. Un'applicazione riuscita stampa una ricevuta con l'ID del piano.

## Ciò che segue la foto

Queste voci mantengono la propria associazione con la foto:

- ID delle foto, valutazioni, Keep e GPS
- tag, volti, ID delle persone e UUID dei volti manuali
- confronti, punteggi appresi e preferenze per utente
- override, appartenenze fisse agli album, copertine e scelte dei clienti
- snapshot di estrazione ed embedding vettoriali
- valori dei gruppi di raffiche, duplicati e sequenze

Le statistiche derivate vengono invalidate; lo stato di addestramento resta.

Ciò che non cambia:

- La **cronologia di annullamento** conserva i vecchi percorsi. Una voce per il vecchio percorso potrebbe non comparire più o non essere più ripristinabile dopo il ricollegamento.
- I **rettangoli manuali dei volti** vengono conservati ma contrassegnati `relink_unverified`. Aprite l'editor e salvate ogni rettangolo rispetto al nuovo fotogramma prima che possa essere esportato o sopprimere rilevamenti.
- Lo stato di invio e di attesa di **Immich** resta invariato; nessuna valutazione, album o UUID remoto viene ricollegato. Controllate personalmente la mappatura remota prima di sincronizzare.
- La **cronologia dei fallimenti di scansione, i filtri degli album intelligenti e le chiavi dei gruppi di sequenze** non vengono riscritti.

## File compagni espliciti e rifiuti

Elencate personalmente i file compagni; lo strumento non può trovare file RAW o XMP scomparsi dalla vecchia directory. Tipi di file compagni:

| Tipo | File |
|---|---|
| `sidecar_full` | `photo.ext.xmp` |
| `sidecar_basename` | `photo.xmp` |
| `sidecar_facet` | `photo.ext.facet.xmp` |
| `raw` | coppia RAW nella stessa directory e con lo stesso nome base |

Queste regole verificano la relazione dichiarata; non provano l'identità. Una foto RAW indicizzata richiede una propria voce di primo livello perché le sue annotazioni siano conservate. I file compagni esistenti vengono sottoposti a hash e lasciati intatti. Un elenco di file compagni vuoto non prova che non ne esistessero.

Facet rifiuta:

- sidecar o file compagni RAW non elencati nella destinazione, inclusi i pacchetti di ripiego di Facet e le varianti di maiuscole/minuscole
- più candidati RAW o proprietà XMP ambigue, ad es. `IMG.CR2` + `IMG.CR2.jpg` + `IMG.CR2.xmp`, oppure `IMG.CR2` + `IMG.CR2.facet.jpg` + `IMG.CR2.facet.xmp`, e collisioni di nomi base, di maiuscole/minuscole o Unicode
- copie in cui il vecchio originale è ancora presente
- directory padre vecchie mancanti o illeggibili
- destinazioni che hanno già foto o righe dipendenti
- mappature ripetute, contenuti di foto o inode di destinazione duplicati
- rinominazioni solo di maiuscole/minuscole o solo Unicode, link simbolici e cambi di estensione o formato
- una destinazione decodificata le cui dimensioni differiscono da quelle memorizzate, quando queste sono note

Non viene eseguita alcuna ricerca per similarità o nome file.

Limiti per lotto: 100 foto, 300 file nominati, 512 MiB per file, 2 GiB in totale e 2 MiB per il JSON in ingresso o il piano. Dividete il lotto se ne raggiungete uno. La scrittura nel database è atomica, ma altre applicazioni possono comunque toccare i file, ed è per questo che il lavoro deve essere eseguito offline.

> **Avvertenza:** Una directory leggibile non prova che l'archiviazione sia montata. Un volume non montato può sembrare una cartella vuota. Il piano riporta `source_mount_status: not_verified`; confermate che ogni sorgente sia stata davvero spostata prima di confermare l'identità. Il comando non rileva ogni condizione di volume offline.

I file del piano contengono percorsi completi privati e l'ambito utente. `--plan-out` li crea in modo esclusivo con modalità 0600 su POSIX.

| Opzione | Scopo |
|---|---|
| `--db` | Database esistente |
| `--config` | Configurazione risolta |
| `--user` | Utente configurato obbligatorio in modalità multiutente |
| `--mapping` | Mappature JSON vecchio/nuovo esplicite; modalità anteprima |
| `--plan-out` | Crea un nuovo file di piano privato; non sovrascrive mai |
| `--apply-plan` | Applica un piano rivisto in precedenza |
| `--ack-plan` | Digest esatto del piano rivisto |
| `--acknowledge-unverified-identity` | Asserzione esplicita nonostante i byte originali ignoti |
