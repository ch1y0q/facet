# Volver a vincular fotos movidas

`python database.py --relink-photos` cambia solo las rutas de fotos ya indexadas después de moverlas manualmente. Detén visor, escáneres y editores externos; guarda una copia de la base. No mueve, modifica ni elimina originales o acompañantes, ni contacta con Immich.

La aplicación mantiene el bloqueo de mantenimiento de Facet durante toda la escritura de la base de datos. Otro trabajo de biblioteca provoca el código 75 sin cambios en la base ni en los archivos; un bloqueo inutilizable provoca el código 1. La vista previa sigue siendo de solo lectura y no toma el bloqueo. Este bloqueo coordina trabajos en un solo equipo; los requisitos de trabajo sin conexión siguen vigentes para otros equipos y editores externos.

La base no prueba la identidad de los bytes del original ausente: cada plan indica `original_bytes_unknown`. SHA-256 identifica solo el destino revisado. Verifica la identidad independientemente antes de las dos confirmaciones; una asociación incorrecta puede adjuntar anotaciones a otra imagen.

Las rutas deben ser absolutas, nativas y canónicas, sin enlaces simbólicos, dentro de raíces configuradas. El original debe faltar pero su carpeta padre debe existir y ser legible. Se rechazan carpetas enteras desaparecidas porque podrían estar desconectadas. No recrees carpetas vacías para eludirlo. Una carpeta legible no prueba el montaje; `source_mount_status=not_verified` requiere verificación independiente.

La vista previa no escribe en la base. Revisa el plan guardado; aplicar comprueba otra vez archivos, hashes, dimensiones conocidas, anotaciones, esquema, inodo y permisos dentro de una transacción SQLite. Un conflicto revierte todo el lote. No bloquea otros programas. El plan se crea exclusivamente con POSIX0600 y contiene rutas privadas.

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

Los IDs, notas/Keep/GPS, etiquetas, rostros/personas, UUID manuales, comparaciones, preferencias, álbumes fijos y vectores mantienen sus asociaciones. Todos los rectángulos manuales necesitan revisión y guardado explícitos. El historial conserva rutas antiguas y puede dejar de admitir reversión; se invalidan revisiones privadas. No se reescriben filtros inteligentes, claves lógicas de grupos, registros históricos ni estado Immich.

Declara acompañantes con rutas anterior/nueva y `kind`: `sidecar_full` para `photo.ext.xmp`, `sidecar_basename` para `photo.xmp`, `sidecar_facet` para `photo.ext.facet.xmp`, `raw` para RAW no indexado del mismo nombre base. Un RAW indexado requiere entrada principal propia; RAW/JPEG indexados se vinculan juntos en un plan. Sus bytes no cambian; no se descubren acompañantes ausentes desconocidos.

El modo multiusuario exige `--user` y la misma visibilidad para todos antes/después. Se rechazan raíces vacías/inaccesibles, path_mapping, originales presentes, destinos registrados, archivos/inodos duplicados, ambigüedades de mayúsculas/Unicode/doble extensión, varios RAW, acompañantes no declarados y cambios de formato. Límites:100 fotos,300 archivos,512MiB por archivo,2GiB total,2MiB JSON. Reduce el lote si procede.
