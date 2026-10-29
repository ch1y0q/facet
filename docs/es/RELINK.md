# Volver a vincular una foto ausente tras un traslado explícito

`python database.py --relink-photos` actualiza las rutas de la base de datos de Facet después de que hayas movido los archivos tú mismo. Nunca mueve, copia, elimina ni edita originales o sidecars, y nunca contacta con Immich. Es un comando de mantenimiento sin conexión.

Antes de aplicar un plan:

- Detén el visor, los escáneres y los editores de archivos externos.
- Haz una copia de seguridad de la base de datos.
- Revisa el plan.

Aplicar toma el bloqueo de biblioteca de Facet. Si hay otro trabajo de biblioteca en marcha, termina con el código de salida 75 y no cambia nada; un bloqueo inutilizable termina con el código 1. La vista previa es de solo lectura y no toma ningún bloqueo. El bloqueo solo cubre trabajos de un mismo host.

> **Advertencia:** Facet no guarda ningún hash de los bytes del archivo original, así que no puede demostrar que el archivo nuevo sea el que se movió. Cada plan indica `original_bytes_unknown`; `phash` y las firmas de rostros manuales no demuestran identidad. El SHA-256 del destino solo identifica el archivo que previsualizaste. Aplicar afirma que has comprobado tú mismo la coincidencia. Una afirmación errónea asocia anotaciones existentes a la imagen equivocada.

No se admite mover ni renombrar un directorio completo cuando el directorio padre antiguo ya no existe. No vuelvas a crear directorios padre vacíos para eludir esta comprobación.

## Previsualizar, revisar y luego aplicar

Crea una lista JSON con rutas absolutas canónicas exactas. Cada origen debe estar ya en Facet. Cada destino debe existir como imagen y no debe tener todavía una fila de foto:

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
# Vista previa de solo lectura de la base de datos; crea un artefacto de revisión privado (0600) y exclusivo.
python database.py --relink-photos --db library.db --config scoring_config.json \
  --mapping moved.json --plan-out relink-plan.json

# Inspecciona en relink-plan.json cada ruta antigua/nueva, la etiqueta de identidad de bytes desconocidos, el hash del destino y las
# dimensiones, las referencias, los acompañantes y la política de visibilidad.
# Sustituye REVIEWED_PLAN_ID por el plan_id exacto de ese artefacto tras revisarlo.
python database.py --relink-photos --db library.db --config scoring_config.json \
  --apply-plan relink-plan.json --ack-plan REVIEWED_PLAN_ID \
  --acknowledge-unverified-identity
```

En modo multiusuario, añade `--user alice` a ambos comandos. Selecciona el ámbito de qué usuario se comprueba; no es control de acceso. Reglas:

- Ambas rutas deben ser visibles para ese usuario.
- El conjunto de **todos** los usuarios que pueden ver la foto debe permanecer igual. Se rechazan los traslados de privado a compartido y otros traslados entre usuarios.
- Ambas rutas deben estar dentro de directorios de escaneo, de usuario o compartidos configurados explícitamente.
- Se rechazan la configuración de raíces en blanco, las raíces inaccesibles y `viewer.path_mapping`. Solo se admiten rutas nativas canónicas.

Aplicar vuelve a comprobar todo el plan en una única transacción de base de datos. Si cambiaron los archivos de destino, las filas de fotos, las anotaciones, el esquema, el archivo de la base de datos o la visibilidad, ejecuta una nueva vista previa. Un lote fallido revierte todas sus escrituras en la base de datos. Una aplicación correcta imprime un recibo con el ID del plan.

## Qué acompaña a la foto

Estos elementos conservan su asociación con la foto:

- ID de foto, valoraciones, Keep y GPS
- etiquetas, rostros, ID de personas y UUID manuales de rostros
- comparaciones, puntuaciones aprendidas y preferencias por usuario
- anulaciones, pertenencia fija a álbumes, portadas y selecciones de clientes
- instantáneas de extracción y vectores de embeddings
- valores de grupos de ráfagas, duplicados y secuencias

Las estadísticas derivadas se invalidan; el estado de entrenamiento se conserva.

Lo que no cambia:

- **El historial de deshacer** conserva sus rutas antiguas. Una entrada de la ruta antigua puede dejar de aparecer o de poder revertirse tras volver a vincular.
- **Los rectángulos manuales de rostros** se conservan pero se marcan como `relink_unverified`. Abre el editor y guarda cada rectángulo respecto al nuevo fotograma antes de que pueda exportarse o suprimir detecciones.
- **Immich**: el estado de envío y pendiente permanece como estaba; no se revincula ninguna valoración, álbum ni UUID remoto. Revisa tú mismo la asignación remota antes de sincronizar.
- **El historial de fallos de escaneo, los filtros de álbumes inteligentes y las claves de grupos de secuencias** no se reescriben.

## Acompañantes explícitos y rechazos

Indica los acompañantes tú mismo; la herramienta no puede encontrar archivos RAW o XMP que hayan desaparecido del directorio antiguo. Tipos de acompañante:

| Tipo | Archivo |
|---|---|
| `sidecar_full` | `photo.ext.xmp` |
| `sidecar_basename` | `photo.xmp` |
| `sidecar_facet` | `photo.ext.facet.xmp` |
| `raw` | par RAW del mismo directorio y nombre base |

Estas reglas validan la relación declarada; no demuestran identidad. Una foto RAW indexada necesita su propia entrada de nivel superior para conservar sus anotaciones. Los archivos acompañantes existentes se procesan con hash y no se modifican. Una lista de acompañantes vacía no demuestra que no existieran.

Facet rechaza:

- sidecars o acompañantes RAW no listados en el destino, incluidos los paquetes alternativos de Facet y las variantes de mayúsculas/minúsculas
- varios candidatos RAW o propiedad XMP ambigua, p. ej. `IMG.CR2` + `IMG.CR2.jpg` + `IMG.CR2.xmp`, o `IMG.CR2` + `IMG.CR2.facet.jpg` + `IMG.CR2.facet.xmp`, y las colisiones de nombre base, mayúsculas/minúsculas o Unicode
- copias en las que el original antiguo sigue presente
- directorios padre antiguos ausentes o ilegibles
- destinos que ya tienen filas de foto o dependientes
- asignaciones repetidas, contenido de foto duplicado o inodos de destino duplicados
- cambios solo de mayúsculas/minúsculas o solo de Unicode, enlaces simbólicos y cambios de extensión o formato
- un destino decodificado cuyas dimensiones difieren de las almacenadas, cuando estas se conocen

No se ejecuta ninguna búsqueda por similitud ni por nombre de archivo.

Límites por lote: 100 fotos, 300 archivos nombrados, 512 MiB por archivo, 2 GiB en total y 2 MiB para el JSON de entrada o el plan. Divide el lote si alcanzas alguno. La escritura en la base de datos es atómica, pero otras aplicaciones aún pueden tocar los archivos, y por eso el trabajo debe ejecutarse sin conexión.

> **Advertencia:** Un directorio legible no demuestra que el almacenamiento esté montado. Un volumen sin montar puede parecer una carpeta vacía. El plan indica `source_mount_status: not_verified`; confirma que cada origen se movió realmente antes de reconocer la identidad. El comando no detecta todas las condiciones de volumen sin conexión.

Los archivos de plan contienen rutas privadas completas y el ámbito de usuario. `--plan-out` los crea de forma exclusiva con modo 0600 en POSIX.

| Opción | Función |
|---|---|
| `--db` | Base de datos existente |
| `--config` | Configuración resuelta |
| `--user` | Usuario configurado obligatorio en modo multiusuario |
| `--mapping` | Rutas antigua/nueva en JSON; vista previa |
| `--plan-out` | Crear plan privado nuevo sin sobrescribir |
| `--apply-plan` | Aplicar un plan revisado |
| `--ack-plan` | Hash exacto del plan revisado |
| `--acknowledge-unverified-identity` | Confirmación explícita pese a bytes originales desconocidos |
