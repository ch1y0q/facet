# Volver a vincular una foto ausente tras un traslado explícito

`python database.py --relink-photos` actualiza las rutas ya existentes en la base de datos de Facet después de que hayas movido los archivos tú mismo. Nunca mueve, copia, elimina ni edita originales o archivos sidecar, ni contacta con Immich. Es un comando de mantenimiento sin conexión para el operador con acceso a la base de datos y a las carpetas configuradas. Detén primero el visor, los escáneres y los editores de archivos externos; haz una copia de seguridad de la base de datos y revisa el plan antes de aplicarlo.

Aplicar mantiene el bloqueo de mantenimiento de la biblioteca de Facet durante toda la escritura en la base de datos. Otro trabajo de la biblioteca provoca el código de salida 75 sin cambios en la base de datos ni en los medios; un bloqueo inutilizable provoca el código 1. La vista previa sigue siendo de solo lectura y no toma ningún bloqueo de biblioteca. Este bloqueo coordina trabajos en un único host; los requisitos sin conexión siguen aplicándose a otros hosts y a editores externos.

La base de datos existente no tiene ningún hash criptográfico de los bytes del archivo original. `phash` y las firmas en escala de grises de los rostros manuales no demuestran identidad byte a byte. Por eso cada plan indica `original_bytes_unknown`. El SHA-256 del destino solo identifica el archivo nuevo que se previsualizó. Aplicar afirma explícitamente que has identificado por tu cuenta el archivo movido correcto; nunca es una coincidencia verificada automáticamente. Una afirmación errónea puede asociar anotaciones existentes a la imagen equivocada.

Mover o renombrar un directorio completo queda fuera de este modo acotado cuando el directorio padre antiguo ya no existe. Los directorios ausentes no permiten distinguir un traslado intencionado de un almacenamiento sin conexión. No vuelvas a crear directorios padre vacíos para eludir esta comprobación.

## Previsualizar, revisar y luego aplicar

Crea una lista JSON con rutas absolutas canónicas exactas. Un origen ausente debe estar ya registrado en Facet; un destino debe existir como imagen y no debe tener todavía una fila de foto:

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

# Inspecciona en relink-plan.json cada ruta antigua/nueva, la etiqueta de identidad de bytes desconocidos, el hash del destino, las
# dimensiones, las referencias, los acompañantes y la política de visibilidad.
# Sustituye REVIEWED_PLAN_ID por el plan_id exacto de ese artefacto tras revisarlo.
python database.py --relink-photos --db library.db --config scoring_config.json \
  --apply-plan relink-plan.json --ack-plan REVIEWED_PLAN_ID \
  --acknowledge-unverified-identity
```

El modo multiusuario también exige `--user alice` en ambos comandos. Es un selector de ámbito para el operador, no un sustituto del control de acceso del sistema operativo ni una API autenticada. Ambas rutas deben ser visibles para ese usuario, y el conjunto de **todos** los usuarios que pueden ver la foto debe permanecer idéntico. Se rechazan los traslados de privado a compartido u otros traslados entre usuarios. Ambas rutas deben estar dentro de directorios de escaneo, de usuario o compartidos configurados explícitamente. Se rechazan la configuración de raíces en blanco, las raíces inaccesibles y `viewer.path_mapping`; esta herramienta inicial solo admite rutas nativas canónicas.

Aplicar vuelve a comprobar todo el plan revisado dentro de una única transacción de escritura de SQLite. Los archivos de destino, filas de fotos, anotaciones, esquema, inodo de la base de datos o política de visibilidad que hayan cambiado exigen una nueva vista previa. Un lote fallido revierte todas sus escrituras en la base de datos. Una aplicación correcta imprime un recibo con el ID del plan. No guarda un nuevo ID de activo lógico ni una asignación de UUID remoto.

## Qué acompaña a la foto

Los rowid de las fotos, valoraciones/Keep/GPS, etiquetas, ID de rostros/personas y UUID manuales, comparaciones, puntuaciones aprendidas, preferencias por usuario, anulaciones, pertenencias fijas a álbumes/portadas/selecciones de clientes, instantáneas de extracción y vectores de embeddings conservan sus asociaciones. Las claves foráneas existentes hacia photos se descubren a partir del esquema real; una nueva columna de ruta no registrada se rechaza en lugar de quedar huérfana en silencio. Las estadísticas derivadas se invalidan; el estado de entrenamiento duradero permanece.

Las entradas del historial de organización conservan sus cargas útiles de rutas históricas originales. Los disparadores existentes ante cambios de ruta avanzan el reloj de revisiones e invalidan las cachés de revisión privadas; una entrada que se refiera a la ruta antigua puede dejar de aparecer o de poder revertirse tras volver a vincular. Volver a vincular conserva los valores de anotación y las asociaciones actuales, pero no reescribe acciones pasadas para hacerlas aplicables a una ruta distinta.

Todos los rectángulos manuales se conservan, pero requieren revisión en la nueva ruta. La firma antigua y aproximada no puede demostrar los píxeles del original ausente. Un marcador `relink_unverified` impide que las comprobaciones de firma habituales borren ese estado de revisión; abre el editor y guarda explícitamente cada rectángulo respecto al nuevo fotograma antes de que pueda exportarse o suprimir detecciones. Se conservan los ID de rectángulos y de personas existentes.

El estado de envío/pendiente de Immich permanece sin cambios: una afirmación local sobre un nombre de archivo no puede verificar una identidad remota. No se revincula ninguna valoración remota, borrado, pertenencia a álbum ni UUID. Revisa por separado la asignación remota antes de sincronizar. Las rutas históricas de fallos de escaneo siguen siendo históricas; los predicados de filtros de álbumes inteligentes y las claves de grupos lógicos de secuencias no se reescriben en silencio. Las pertenencias estáticas y los valores de grupos de secuencias/ráfagas/duplicados permanecen intactos.

## Acompañantes explícitos y rechazos

Indica los acompañantes de forma explícita; la herramienta no puede descubrir archivos RAW/XMP no indexados que hayan desaparecido del directorio antiguo. `sidecar_full` significa `photo.ext.xmp`, `sidecar_basename` significa `photo.xmp`, `sidecar_facet` significa `photo.ext.facet.xmp` y `raw` conserva un par RAW indicado explícitamente, del mismo directorio y nombre base, compatible con la selección actual. Estas reglas de nombres validan una relación declarada; no demuestran la identidad de los archivos. Las fotos RAW indexadas necesitan su propia entrada de revinculación de nivel superior para conservar sus anotaciones.

Se rechazan los sidecars o acompañantes RAW no listados en el destino, incluidos los paquetes alternativos de Facet y las variantes de mayúsculas/minúsculas. Se rechazan varios candidatos RAW y la propiedad XMP ambigua, entre ellos `IMG.CR2` + `IMG.CR2.jpg` + `IMG.CR2.xmp`, `IMG.CR2` + `IMG.CR2.facet.jpg` + `IMG.CR2.facet.xmp`, y las colisiones de nombre base y de mayúsculas/minúsculas o Unicode. Ningún acompañante se asigna por primera coincidencia. Los bytes de los acompañantes existentes se procesan con hash, se vuelven a comprobar y no se modifican. Los acompañantes ausentes no listados siguen siendo desconocidos; no interpretes una lista vacía como prueba de que no existían.

Se rechazan las copias cuyo original antiguo sigue presente, los directorios padre antiguos ausentes o ilegibles, las fotos de destino o filas dependientes ya existentes, las asignaciones repetidas, los contenidos de fotos o inodos de destino duplicados, los cambios solo de mayúsculas/minúsculas o de Unicode, los enlaces simbólicos y los cambios de extensión o formato. Las dimensiones canónicas almacenadas, cuando se conocen, deben coincidir con el destino decodificado. No se ejecuta ninguna búsqueda por similitud o nombre de archivo ni conciliación automática.

Límites: 100 fotos, 300 archivos nombrados explícitamente, 512 MiB por archivo, 2 GiB de bytes de archivos en total y 2 MiB de JSON de entrada o de plan revisado. Reduce el lote cuando se alcance un límite. La transacción de la base de datos es atómica; el sistema de archivos no está bloqueado frente a otras aplicaciones, de ahí el requisito de trabajar sin conexión. Las pruebas con fixtures no afirman ningún recorrido completo con una aplicación externa real ni con un servidor remoto.

Los directorios legibles **no** demuestran que el almacenamiento esté montado. Un volumen sin montar puede dejar un punto de montaje vacío pero legible, indistinguible de un directorio realmente vacío tras el traslado. El plan indica explícitamente `source_mount_status: not_verified`; confirma de forma independiente que cada origen se movió y no que simplemente no está disponible antes de reconocer la identidad. El comando no detecta todas las condiciones de volumen sin conexión. Los planes revisables contienen rutas completas privadas y la política de ámbito de usuario; `--plan-out` los crea de forma exclusiva con modo 0600 en POSIX.

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
