# Ricollegare foto spostate

`python database.py --relink-photos` modifica solo i percorsi di foto già indicizzate dopo uno spostamento manuale. Ferma viewer, scanner ed editor esterni e salva una copia della base. Non sposta, modifica o elimina originali o file associati e non contatta Immich.

La base non prova l’identità dei byte dell’originale assente: ogni piano riporta `original_bytes_unknown`. SHA-256 identifica soltanto il nuovo file esaminato. Verifica autonomamente l’identità prima delle due conferme; una corrispondenza errata può collegare annotazioni alla foto sbagliata.

I percorsi devono essere assoluti, nativi e canonici, senza symlink, entro radici configurate. L’originale deve mancare ma la cartella padre deve esistere ed essere leggibile. Cartelle intere scomparse vengono rifiutate perché potrebbero essere offline. Non ricreare cartelle vuote per aggirare il controllo. Una cartella leggibile non prova il montaggio; `source_mount_status=not_verified` richiede verifica indipendente.

L’anteprima non scrive nella base. Esamina il piano salvato; applicare ricontrolla file, hash, dimensioni note, annotazioni, schema, inode e permessi in una transazione SQLite. Ogni conflitto annulla l’intero lotto. Gli altri programmi non sono bloccati. Il piano è creato esclusivamente con POSIX0600 e contiene percorsi privati.

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

ID, valutazioni/Keep/GPS, tag, volti/persone, UUID manuali, confronti, preferenze, album fissi e vettori conservano i collegamenti. Tutti i rettangoli manuali richiedono revisione e salvataggio espliciti. La cronologia mantiene i vecchi percorsi e potrebbe non essere più ripristinabile; le revisioni private sono invalidate. Filtri intelligenti, chiavi logiche dei gruppi, registri storici e stato Immich non vengono riscritti.

Dichiara i file associati con percorsi vecchio/nuovo e `kind`: `sidecar_full` per `photo.ext.xmp`, `sidecar_basename` per `photo.xmp`, `sidecar_facet` per `photo.ext.facet.xmp`, `raw` per RAW non indicizzato con la stessa base. Un RAW indicizzato richiede una propria voce principale; RAW/JPEG indicizzati vanno ricollegati nello stesso piano. I byte non cambiano; file associati scomparsi e sconosciuti non sono rilevabili.

Il multiutente richiede `--user` e visibilità identica per tutti prima/dopo. Si rifiutano radici vuote/inaccessibili, path_mapping, originali presenti, destinazioni già registrate, file/inode duplicati, ambiguità maiuscole/Unicode/doppie estensioni, RAW multipli, associati non dichiarati e cambi di formato. Limiti:100 foto,300 file,512MiB per file,2GiB totali,2MiB JSON. Riduci il lotto se necessario.
