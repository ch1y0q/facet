# Agentes de IA (MCP)

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · **Español** · [Português](../pt/AGENTS.md) · [简体中文](../zh/AGENTS.md)

Facet puede actuar como servidor [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), de modo que un asistente de IA como Claude Code pueda buscar e inspeccionar tu biblioteca con los mismos filtros que la galería. Expone nueve herramientas de lectura que no cambian nada en tu biblioteca y nueve herramientas `ui_*` que mueven la pestaña del navegador que ya tienes abierta (página, filtros, selección) y nunca escriben datos de la biblioteca. Los tokens autorizados también pueden [modificar la biblioteca](#modificar-la-biblioteca) (valoraciones, indicadores, etiquetas, álbumes, descarte y borrado) y manejar el [cuarto oscuro](#cuarto-oscuro-grupos-de-descarte).

## Activarlo

El endpoint está **desactivado por defecto**. Pon `viewer.mcp.enabled` a `true` en `scoring_config.json` (ver [Endpoint de agentes (MCP)](CONFIGURATION.md#endpoint-de-agentes-mcp)) y reinicia el visor, o recarga la configuración. Mientras esté desactivado, `/mcp` y todas las rutas `/api/mcp/*` responden 404. Sin `viewer.password` la instalación se considera abierta, aunque `viewer.edition_password` esté definida: sus tokens solo pueden ser `readonly`.

El endpoint es `POST /mcp` en el puerto del visor: Streamable HTTP, sin estado, respuestas JSON simples. `GET` responde 405. Solo el puente de pestaña, `/api/mcp/bridge`, es un WebSocket; consulta [Controlar tu pestaña abierta](#controlar-tu-pestaña-abierta).

## Crear un token

Lo más sencillo es el navegador. Con `viewer.mcp.enabled` activado, abre el menú de la cuenta y elige **Conectar un asistente**. En **Crear un token**, escribe un **Nombre** y elige **Lo que el asistente puede hacer**: **Solo leer y pilotar**, más **Actuar como yo** o **Edición completa** si tu sesión tiene ese nivel (un token no puede superar a la sesión que lo crea). Haz clic en **Crear token**: el token aparece una sola vez en **Tu nuevo token**, así que cópialo ahora. **Tokens de acceso** lista tus tokens con su último uso y permite revocar uno. **Añadirlo a Claude Code** muestra el comando de Claude Code listo para pegar (véase más abajo), y **Esta pestaña** indica si esta pestaña está conectada y, por tanto, los asistentes pueden controlarla. La lista de niveles se limita a lo que el servidor concederá: una instalación abierta solo ofrece **Solo leer y pilotar**, **Actuar como yo** aparece solo en instalaciones multiusuario y **Edición completa** solo en una sesión de edición. Tras crear el token, el cuadro indica el nivel realmente concedido ("Acceso concedido: {level}").

Alternativa por script (curl):

Un asistente se autentica con un token personal que empieza por `fct_`. Crea uno con una petición autenticada (el token se devuelve **una sola vez**; Facet solo guarda su hash SHA-256):

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "claude-code", "level": "readonly"}'
```

La respuesta incluye el texto en claro en `token`. `GET /api/mcp/tokens` lista tus tokens (nunca el secreto) y `DELETE /api/mcp/tokens/{id}` revoca uno. Un superadmin puede listar los tokens de todos los propietarios con `?all=1` y revocar cualquiera. Cada propietario puede tener como máximo 20 tokens activos (más allá, 412). Estas rutas rechazan (403) las credenciales de un agente, así que un asistente nunca puede crear, listar ni revocar tokens.

## Conectar Claude Code

```bash
claude mcp add --transport http facet http://localhost:5000/mcp --header "Authorization: Bearer fct_YOUR_TOKEN"
```

Las herramientas aparecen entonces como `mcp__facet__search_photos` y así sucesivamente. Usa HTTPS cuando el visor sea accesible más allá de tu propio equipo, ya que el token viaja en una cabecera en cada llamada.

## Niveles de permiso

Un token se crea con un nivel concedido: `readonly`, `user` o `edition`. El nivel **efectivo** se recalcula en cada llamada como el menor entre el del token y el actual de su propietario:

- Instalaciones con contraseña única: `user` se limita a `readonly` al crearlo, porque ese modo no tiene nivel intermedio. Un token `edition` exige una sesión de edición y solo funciona mientras no cambie la contraseña de edición.
- Instalaciones multiusuario: el token `edition` de un usuario que luego pierde el rol baja a `user`; un ascenso nunca eleva un token por encima de su nivel concedido.
- Instalaciones abiertas (sin `viewer.password`, aunque `viewer.edition_password` esté definida): los tokens son siempre `readonly` y pertenecen a un propietario compartido `_anonymous`.
- Las instalaciones con contraseña única no tienen nivel `user`: el nivel efectivo es `edition` o `readonly`, así que las herramientas marcadas `user` en [Modificar la biblioteca](#modificar-la-biblioteca) también necesitan un token `edition`. Una herramienta `user` llamada con un token de nivel inferior responde `forbidden_level` indicando que necesita `edition`.
- Cada herramienta tiene su propio nivel mínimo, comprobado antes de leer o escribir nada; un token inferior recibe `forbidden_level`.

Un token deja de valer automáticamente cuando cambian las credenciales de su propietario: la contraseña del visor o de edición en modo contraseña única, la contraseña del propietario en modo multiusuario, o la eliminación de su cuenta. Recibe entonces un 401 en la entrada.

## Herramientas

Las nueve herramientas de datos son de solo lectura:

| Herramienta | Qué hace |
|------|--------------|
| `search_photos` | Filtra y ordena la biblioteca como la galería, aplicando los ocultamientos por defecto del visor salvo que el filtro los fije (informa `hidden_summary`) |
| `semantic_search` | Encuentra fotos por significado, o por palabras de los pies de foto con `scope: "text"` |
| `get_photo` | Detalle completo de una foto a partir de su ruta (sin el histograma) |
| `similar_photos` | Fotos parecidas a una foto, por embedding visual o por color |
| `filter_options` | El vocabulario que acepta un filtro: cámaras, objetivos, etiquetas, personas, patrones, categorías, momentos narrativos, tipos de descarte, rangos de métricas |
| `list_persons` | Personas reconocidas, filtrables por nombre |
| `list_albums` | Álbumes que puede ver el propietario del token |
| `library_stats` | Tamaño de la biblioteca, recuentos por tipo y resumen de puntuaciones |
| `status` | Quién es el token, su nivel efectivo y las banderas del servidor y las pestañas abiertas que puede manejar |

En cada objeto de filtros, `show_rejected` es un booleano: `true` lista solo las fotos descartadas, `false` u omitido da el listado normal.

## Controlar tu pestaña abierta

Junto a las herramientas de datos, el servidor siempre lista nueve herramientas `ui_*` que actúan sobre la pestaña de Facet que tienes abierta en un navegador: cambian de página, modifican los filtros o la selección y releen lo que ves. Nunca escriben datos de la biblioteca, así que basta un token `readonly`.

| Herramienta | Qué hace |
|-------------|----------|
| `ui_navigate` | Ir a una página (galería, personas, álbumes, estadísticas, ...) |
| `ui_set_gallery_filters` | Combinar un parche con los filtros y la ordenación de la galería (`null` quita un filtro, `replace: true` parte de cero) |
| `ui_get_gallery_view` | Ruta, filtros activos, total de resultados, las primeras rutas de fotos visibles y el número de fotos seleccionadas |
| `ui_open_photo` | Abrir una foto |
| `ui_select_photos` | Seleccionar `paths` explícitos, o toda la vista filtrada con `select_view: true`, en modo `replace`, `add` o `remove` |
| `ui_clear_selection` | Vaciar la selección |
| `ui_get_selection` | El `scope` (`paths` o `view`) y el `count`, con los `paths` o, en una vista, los `filters` y los `excluded_paths` |
| `ui_next_page` | Cargar la siguiente página de la galería |
| `ui_show_culling_group` | Abrir el cuarto oscuro en un grupo, identificado por `(type, group_id)` (cuentas de edición) |

Cómo funciona:

- Mientras tengas la sesión iniciada y `viewer.mcp.enabled` y `viewer.mcp.bridge` valgan `true`, cada pestaña de Facet abre un WebSocket del mismo origen hacia `/api/mcp/bridge` y se autentica con tu sesión en su primer mensaje. El puente está activo por defecto; pon `viewer.mcp.bridge` en `false` para desactivarlo y las herramientas `ui_*` responderán con un error claro.
- Una herramienta solo llega a las pestañas del propietario del token. Con una única contraseña todas las sesiones son el mismo usuario; en una instalación abierta cada pestaña pertenece al usuario compartido `_anonymous`, incluidos los inicios de sesión de edición.
- Cada pestaña lleva el nivel de la sesión que la abrió, y un token solo maneja pestañas de nivel igual o superior a su nivel efectivo: un token `edition` nunca usa una pestaña con una sesión de solo consulta, mientras que un token `readonly` sí puede manejar una pestaña `edition`. `status` lista solo las pestañas que el token puede manejar.
- Con varias pestañas abiertas se usa la que tuvo el foco más recientemente y el campo `tab` del resultado lo indica. Pasa `tab_id` (lo lista `status`) para elegir otra.
- Una pestaña rechaza lo que su cuenta no puede hacer (por ejemplo `/culling` para una cuenta sin edición) y la herramienta devuelve ese rechazo.
- Lo que devuelve una pestaña no es de fiar: se limitan la profundidad y la longitud de cadenas y listas, y todo queda acotado por `max_bytes`.
- Errores: `no_tab` (ninguna pestaña conectada, o puente desactivado), `tab_timeout` (sin respuesta en `call_timeout_s`) y `tab_outdated` (la pestaña abierta no conoce la herramienta; recarga la página tras actualizar Facet).
- El puente acepta primero el WebSocket y luego lo rechaza con un código de cierre en lugar de un estado HTTP: 4404 si el endpoint o el puente están desactivados, 4403 si falta `Origin` o no está permitido, 4401 por una sesión ausente o rechazada.
- Un proxy inverso debe reenviar la actualización a WebSocket para `/api/mcp/bridge`; consulta [Despliegue](DEPLOYMENT.md). Si reescribe la cabecera `Host`, indica el origen público en `viewer.mcp.allowed_origins` (por ejemplo `["https://photos.example.com"]`), porque el origen de la página debe coincidir con el host o figurar en la lista.
- El registro de pestañas es por proceso, así que el puente necesita un único worker (el valor por defecto).

Además:

- `ui_set_gallery_filters` te lleva primero a la galería si hay otra página abierta y después aplica el parche. Rechaza el parche entero (`invalid_input`) si nombra un filtro que la pestaña no sabe manejar; para esos usa `search_photos`.
- `ui_get_gallery_view`, `ui_next_page` y `ui_select_photos` con `select_view` necesitan que la galería (o un álbum) sea la página abierta; si no, responden `no_active_view`; llama antes a `ui_navigate` hacia `/`. Da a `ui_select_photos` exactamente uno de `paths` y `select_view`.
- `no_tab` también significa que no hay ninguna pestaña de Facet abierta: abre Facet en un navegador e inicia sesión. **Esta pestaña** en el cuadro **Conectar un asistente** muestra el estado de la conexión, con el id de la pestaña.
- Una pestaña deja de reconectarse cuando se rechaza su sesión (inicia sesión de nuevo) y espera a que vuelvas a ella si otra de tus pestañas tomó el relevo.
- El puente de la pestaña solo se conecta si el servidor lo declara disponible (el endpoint está activo y `viewer.mcp.bridge` es true); con el puente desactivado, las pestañas no se conectan en absoluto.
- `ui_set_gallery_filters` rechaza un nombre de filtro desconocido con `invalid_input`, y también un parche que dé a la vez `category` y `type`, o a la vez `person` y `person_id`. Solo ofrece los filtros que la galería puede mostrar; para los demás usa `search_photos`.
- `ui_navigate` abre solo las páginas estáticas de la aplicación: la página de inicio de sesión, las páginas compartidas, las URL externas y las rutas desconocidas se rechazan (`invalid_input`), y las páginas exclusivas de edición se rechazan a una sesión sin edición.
- `ui_select_photos` en modo `remove` con una selección de toda la vista ignora las rutas fuera de la vista cargada y las lista como `not_in_view` en el resultado.

## WebMCP en la página (agentes del navegador)

Aparte del endpoint `/mcp`, una pestaña con sesión iniciada ofrece también las mismas herramientas `ui_*` a los agentes que viven en el propio navegador, mediante la API W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) (`document.modelContext`). Un asistente nativo del navegador ve así exactamente las herramientas listadas arriba, las ejecuta en la pestaña que estás mirando y no necesita token.

- **Solo en contexto seguro.** Facet registra las herramientas únicamente con HTTPS o en `localhost`. Con HTTP simple no se ofrecen y el cuadro **Conectar un asistente** lo indica; la conexión con token anterior sigue funcionando.
- Se registran cuando `viewer.mcp.enabled` es true y has iniciado sesión, y se retiran al cerrar sesión.
- El objeto es `document.modelContext` (el alias obsoleto `navigator.modelContext` no se proporciona). Es un polyfill, instalado solo si el navegador no tiene uno nativo, y no se puede desinstalar: puede existir antes de iniciar sesión sin ninguna herramienta de Facet y permanece tras cerrar sesión con una lista de herramientas vacía.
- Las herramientas hacen lo mismo, limitadas por el mismo nivel de cuenta, que en la tabla anterior.

## Modificar la biblioteca

Las herramientas de escritura figuran junto a las de lectura en la misma lista `/mcp`. Cada una pasa por las rutas `/api` del visor, así que las protecciones de la ruta siguen aplicándose, y cada una cuenta contra el presupuesto `write_rate_per_min`. El nivel es el más bajo nivel efectivo que puede llamar a la herramienta (consulta [Niveles de permiso](#niveles-de-permiso)).

| Herramienta | Nivel | Qué hace | Límites |
|-------------|-------|----------|---------|
| `set_rating` | `user` | Fija la valoración en estrellas (0-5) de fotos | 50 rutas |
| `set_favorite` | `user` | Marca o desmarca fotos como favoritas (marcar quita el descarte) | 50 rutas |
| `set_rejected` | `user` | Descarta o anula el descarte de fotos (descartar quita la valoración y el favorito) | 50 rutas |
| `batch_set_rating` | `edition` | Fija la valoración de muchas fotos | 1000 rutas, o `filters` |
| `batch_set_favorite` | `edition` | Marca muchas fotos como favoritas | 1000 rutas, o `filters` |
| `batch_set_rejected` | `edition` | Descarta muchas fotos | 1000 rutas, o `filters` |
| `add_tags` | `edition` | Añade etiquetas manuales (aparte de las etiquetas de IA) | 10 etiquetas; 1000 rutas, o `filters` |
| `remove_tags` | `edition` | Quita etiquetas manuales | 10 etiquetas; 1000 rutas, o `filters` |
| `create_album` | `edition` | Crea un álbum vacío (no idempotente: dos veces crea dos álbumes) | |
| `album_add_photos` | `edition` | Añade fotos a un álbum (las ya presentes se ignoran) | 1000 rutas |
| `album_remove_photos` | `edition` | Quita fotos de un álbum; las fotos no se tocan | 1000 rutas |
| `junk_list` | `readonly` | Lista los candidatos de la limpieza de descartes, opcionalmente de un solo `kind` | 100 por página |
| `junk_reject` | `edition` | Descarta candidatos de la limpieza (igual que `batch_set_rejected`) | 1000 rutas |
| `junk_clear` | `edition` | Conserva candidatos: los marca como evaluados y limpios para que salgan de la cola | 50 rutas |
| `cull_apply` | `edition` | Copia las fotos que se conservan, o mueve o envía a la papelera las descartadas ([vista previa y confirmación](#acciones-destructivas-vista-previa-y-confirmación)) | 10000 rutas, o `filters` |
| `delete_photos` | `edition` | Envía los archivos a la papelera y borra sus filas de la biblioteca ([vista previa y confirmación](#acciones-destructivas-vista-previa-y-confirmación)) | 1000 rutas |

- **Las herramientas `user` necesitan un token de edición en una instalación con contraseña única**, que no tiene nivel intermedio (consulta [Niveles de permiso](#niveles-de-permiso)).
- **Semántica de asignación.** Las herramientas por foto leen el estado actual y solo escriben una diferencia, así que repetir una llamada es inofensivo; cada ruta informa `changed` o `already`. Procesan una ruta cada vez y se detienen en el primer `library_busy`, `outcome_unknown` o `forbidden_level`, informando `affected`, los `results` por ruta y `not_attempted`. Las herramientas por lotes fijan el mismo estado.
- **Elegir las fotos.** Las herramientas por lotes, de etiquetas y `cull_apply` aceptan O `paths` O `filters` (el objeto de filtros de `search_photos`), más una lista `exclude` opcional. Un destino `filters` debe llevar `expected_count`, el número de coincidencias de los filtros antes de aplicar `exclude` (el `total` de `search_photos`). Facet vuelve a contar primero los filtros y no escribe nada si los números difieren (`invalid_input`, con `actual_count`).
- **De quién es el estado.** Las valoraciones, favoritos y descartes son los del propietario del token.
- **Archivos omitidos.** Cuando `cull_apply` o `delete_photos` informa una lista `skipped` no vacía, el resultado incluye también un `skipped_reason`: esas rutas de la biblioteca no tienen ningún archivo legible en disco (falta, se movió o está fuera de los directorios analizados) y no se hizo nada con ellas.

### Acciones destructivas: vista previa y confirmación

`cull_apply` (`copy_keeps`, `move_rejects`, `trash_rejects`) y `delete_photos` llevan `destructiveHint` y se ejecutan como simulación salvo que se llamen con `dry_run: false`.

1. La simulación no cambia nada y lista los archivos que copiaría, movería o enviaría a la papelera (las listas largas se recortan a `max_rows`, con un `<key>_count`). Para `move_rejects`, `trash_rejects` y `delete_photos` devuelve además un valor `confirm`, válido durante `confirm_expires_in_s` (5 minutos) y para un solo uso.
2. La llamada real (`dry_run: false`) debe pasar ese `confirm`. Facet recalcula el conjunto de archivos y las opciones y los compara con aquellos para los que se emitió el valor. Si algo cambió, el valor queda anulado y la llamada responde `confirmation_required`: repite la simulación.
3. `copy_keeps` no necesita `confirm`: solo escribe copias. Aun así empieza por una simulación por defecto.

El valor `confirm` está ligado al token, a la acción y al conjunto exacto de archivos más las opciones. Vive en memoria en un solo proceso, así que un reinicio descarta todos los valores pendientes.

**Práctica recomendada:** muestra siempre al usuario el resumen de la simulación (recuentos y lista de archivos) y obtén su aprobación explícita antes de la llamada `dry_run: false`. No confirmes nunca por iniciativa propia.

- `move_rejects` y `trash_rejects` solo actúan sobre las fotos que el propietario descartó; las demás se informan como `excluded_by_state`. Los archivos RAW y `.xmp` acompañantes (`include_companions`) y los demás fotogramas de un bracketing o panorama (`include_sequence_siblings`) no se tocan salvo que lo actives.
- `delete_photos` envía los archivos a la papelera del sistema y **borra sus filas de la biblioteca**: las puntuaciones, etiquetas y valoraciones no se pueden recuperar, aunque los archivos sí.
- **Requisitos previos.** `trash_rejects` y `delete_photos` exigen `viewer.cull.allow_trash` en `true` (por defecto `false`; si no, la llamada se rechaza). El `target_dir` de `copy_keeps` y `move_rejects` debe estar en una ubicación de exportación permitida: `viewer.export.allowed_target_dirs` más tus directorios de análisis (consulta [Destinos de exportación y descarte](CONFIGURATION.md#destinos-de-exportación-y-descarte)).

## Cuarto oscuro (grupos de descarte)

Las herramientas del cuarto oscuro reflejan la página `/culling`. Todas exigen el nivel `edition`, también las que solo listan.

| Herramienta | Qué hace |
|-------------|----------|
| `list_culling_groups` | Lista los grupos (`burst`, `similar`, `scene`, `bracket`, `panorama`, `hdr_panorama`) con sus fotos y puntuaciones, ordenables y acotables por álbum o rango de fechas |
| `culling_profiles` | Los ajustes de descarte por género y el predefinido |
| `suggest_culling_profile` | Nombra el ajuste que encaja con un álbum o un rango de captura |
| `keeper_hints` | Pistas por foto «en esta ráfaga hay una toma mejor» para hasta 100 rutas (vacías si no hay cabeza de clasificación entrenada) |
| `auto_cull` | Descarte automático de un ámbito con un presupuesto de fotos a conservar: primero la vista previa, luego la aplicación con el valor `confirm` |
| `confirm_culling_groups` | Confirma hasta 20 grupos: conserva sus `keep_paths` y descarta el resto de sus `paths` |

- **Un grupo se identifica por el par `(type, group_id)`**, nunca solo por `group_id`: los ids de los grupos similares se desplazan al fusionarse con las ráfagas.
- **El valor por defecto `group_by: "all"` devuelve solo ráfagas y grupos similares.** Pide explícitamente `scene`, `bracket`, `panorama` o `hdr_panorama`.
- **Una página se recorta para caber en `max_bytes` acortando la lista `photos` de cada grupo, nunca eliminando grupos.** `photo_count` sigue siendo el tamaño real, `photos_truncated` marca un grupo cuya lista se cortó y `has_more` indica si sigue otra página.
- **Los bracketings, panoramas y panoramas HDR se conservan enteros.** En `confirm_culling_groups`, `keep_paths` debe ser igual a `paths` para estos tipos (si no, `invalid_input`), y `auto_cull` nunca los divide.
- **Un `keep_paths` vacío descarta todos los fotogramas del grupo.** La primera llamada responde entonces `confirmation_required` con un valor `confirm`; muéstraselo al usuario y repite la llamada con ese valor. Si un lote se detiene en `forbidden_level`, `library_busy` o `rate_limited`, se informan los grupos ya completados.
- **`auto_cull` hace una vista previa por defecto** y devuelve el reparto conservar/descartar por grupo más un valor `confirm` (solo si algo se descartaría). La aplicación recalcula el plan y lo rechaza con `confirmation_required` si cambió desde la vista previa o es demasiado grande para confirmarse como un solo conjunto (acótalo con `album_id`, `date_from` y `date_to`, o `group_by`). Los fotogramas descartados alimentan el clasificador personal como cualquier descarte manual.
- Llama a `ui_show_culling_group` para mostrar un grupo al usuario en su pestaña abierta (consulta [Controlar tu pestaña abierta](#controlar-tu-pestaña-abierta)).

## Resultados, límites y errores

Cada resultado es un sobre JSON: `{"ok": true, "data": ...}` o `{"ok": false, "error": "<code>", "message": "..."}`. Los listados devuelven `data.rows` (un conjunto compacto y fijo de campos por foto) más `total`.

- **Topes:** como máximo `max_rows` filas y `max_bytes` bytes serializados. Las últimas filas se descartan y se marca `truncated: true`. Un resultado sin filas que supere `max_bytes` pasa a ser un error `too_large`.
- **Límite de frecuencia:** `rate_per_min` llamadas por minuto y token para lectura. Las herramientas de escritura usan un presupuesto aparte, `write_rate_per_min` (30 por defecto), para que las búsquedas no dejen sin cupo a las escrituras ni al revés; la simulación de `cull_apply` y `delete_photos` cuenta como escritura, la vista previa de `auto_cull` como lectura. Superado: `rate_limited` con `retry_after_s`. Diez intentos bearer fallidos por minuto desde una misma dirección reciben 429.
- **Códigos de error:** `forbidden_level` (endpoint desactivado, token inválido o nivel insuficiente), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `confirmation_required`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`.
- **Los códigos más recientes:** `confirmation_required` (una llamada destructiva no tiene un valor `confirm` vigente para este conjunto exacto: repite la simulación, muestra el resultado al usuario y vuelve a intentarlo), `outcome_unknown` (una escritura agotó el tiempo o se cortó la conexión, así que puede haberse hecho o no: relee el estado antes de reintentar, nunca reintentes a ciegas), `library_busy` (la biblioteca está ocupada con otra tarea: reintenta en un momento).
- **Códigos HTTP en la entrada:** 401 por token ausente o desconocido, 403 por una petición de navegador de otro origen o por las credenciales de un agente en `/api/mcp/tokens`, 404 cuando está desactivado. El puente de pestañas responde con códigos de cierre.

## Notas de seguridad

- Los pies de foto, etiquetas, nombres de archivo, rutas y nombres de álbumes y personas vienen de tu biblioteca y pueden contener texto escrito para manipular a un asistente (inyección de prompts). Cada herramienta lleva la marca `facet/untrusted_content` e indica al modelo que los trate como datos. No des a un asistente que también lee contenido no fiable un modo de actuar sobre lo que encuentre aquí.
- Los tokens no caducan nunca. Revoca los que ya no uses.
- Los registros guardan el id del token, la herramienta, el resultado y el número de filas, nunca los argumentos ni el token.

## Limitaciones conocidas

- En una instalación abierta (sin contraseña), cualquiera que alcance el visor puede crear y revocar los tokens `_anonymous` compartidos. Define una contraseña antes de activar el endpoint en una red. El puente de pestaña amplía este riesgo: un cliente que no sea un navegador puede enviar un `Origin` inventado y un token nulo, registrar una pestaña `_anonymous` con el foco, responder a las llamadas `ui_*` con los datos que quiera y expulsar pestañas reales mediante el límite de 8 pestañas.
- Los límites de frecuencia y los contadores de autenticaciones fallidas viven en memoria en cada proceso; con `viewer.py --workers N` cada worker cuenta por separado.
- El registro de pestañas vive en memoria en un solo proceso. Usa un único worker (`viewer.py --workers 1`, el valor por defecto) si dependes de las herramientas `ui_*`; con varios workers una llamada puede llegar a un proceso que no conoce tu pestaña y responder `no_tab`.
- Un usuario puede tener como máximo 8 pestañas conectadas; abrir una novena cierra la más antigua.
