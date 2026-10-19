# Agentes de IA (MCP)

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · **Español** · [Português](../pt/AGENTS.md) · [简体中文](../zh/AGENTS.md)

Facet puede actuar como servidor [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), de modo que un asistente de IA como Claude Code pueda buscar e inspeccionar tu biblioteca con los mismos filtros que la galería. Expone nueve herramientas de lectura que no cambian nada en tu biblioteca, más nueve herramientas `ui_*` que mueven la pestaña del navegador que ya tienes abierta (página, filtros, selección) y nunca escriben datos de la biblioteca.

## Activarlo

El endpoint está **desactivado por defecto**. Pon `viewer.mcp.enabled` a `true` en `scoring_config.json` (ver [Endpoint de agentes (MCP)](CONFIGURATION.md#endpoint-de-agentes-mcp)) y reinicia el visor, o recarga la configuración. Mientras esté desactivado, `/mcp` y todas las rutas `/api/mcp/*` responden 404.

El endpoint es `POST /mcp` en el puerto del visor: Streamable HTTP, sin estado, respuestas JSON simples. `GET` responde 405. Solo el puente de pestaña, `/api/mcp/bridge`, es un WebSocket; consulta [Controlar tu pestaña abierta](#controlar-tu-pestaña-abierta).

## Crear un token

Lo más sencillo es el navegador. Con `viewer.mcp.enabled` activado, abre el menú de la cuenta y elige **Conectar un asistente**. En **Crear un token**, escribe un **Nombre** y elige **Lo que el asistente puede hacer**: **Solo leer y pilotar**, más **Actuar como yo** o **Edición completa** si tu sesión tiene ese nivel (un token no puede superar a la sesión que lo crea). Haz clic en **Crear token**: el token aparece una sola vez en **Tu nuevo token**, así que cópialo ahora. **Tokens de acceso** lista tus tokens con su último uso y permite revocar uno. **Añadirlo a Claude Code** muestra el comando de Claude Code listo para pegar (véase más abajo), y **Esta pestaña** indica si esta pestaña está conectada y, por tanto, los asistentes pueden controlarla. La lista de niveles se limita a lo que el servidor concederá: una instalación abierta solo ofrece **Solo leer y pilotar**, **Actuar como yo** aparece solo en instalaciones multiusuario y **Edición completa** solo en una sesión de edición. Tras crear el token, el cuadro indica el nivel realmente concedido ("Acceso concedido: {level}").

Alternativa por script (curl):

Un asistente se autentica con un token personal que empieza por `fct_`. Crea uno con una petición autenticada (el token se devuelve **una sola vez**; Facet solo guarda su hash SHA-256):

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "claude-code", "level": "readonly"}'
```

La respuesta incluye el texto en claro en `token`. `GET /api/mcp/tokens` lista tus tokens (nunca el secreto) y `DELETE /api/mcp/tokens/{id}` revoca uno. Un superadmin puede listar los tokens de todos los propietarios con `?all=1` y revocar cualquiera. Cada propietario puede tener como máximo 20 tokens activos (más allá, 412). Estas rutas rechazan las credenciales de un agente, así que un asistente nunca puede crear, listar ni revocar tokens.

## Conectar Claude Code

```bash
claude mcp add --transport http facet http://localhost:5000/mcp --header "Authorization: Bearer fct_YOUR_TOKEN"
```

Las herramientas aparecen entonces como `mcp__facet__search_photos` y así sucesivamente. Usa HTTPS cuando el visor sea accesible más allá de tu propio equipo, ya que el token viaja en una cabecera en cada llamada.

## Niveles de permiso

Un token se crea con un nivel concedido: `readonly`, `user` o `edition`. El nivel **efectivo** se recalcula en cada llamada como el menor entre el del token y el actual de su propietario:

- Instalaciones con contraseña única: `user` se limita a `readonly` al crearlo, porque ese modo no tiene nivel intermedio. Un token `edition` exige una sesión de edición y solo funciona mientras no cambie la contraseña de edición.
- Instalaciones multiusuario: el token `edition` de un usuario que luego pierde el rol baja a `user`; un ascenso nunca eleva un token por encima de su nivel concedido.
- Instalaciones abiertas (sin contraseña): los tokens son siempre `readonly` y pertenecen a un propietario compartido `_anonymous`.

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
| `status` | Quién es el token, su nivel efectivo y las banderas del servidor |

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
- Una herramienta solo llega a las pestañas del propietario del token. Con una única contraseña todas las sesiones son el mismo usuario; en una instalación abierta cada pestaña pertenece al usuario compartido `_anonymous`.
- Con varias pestañas abiertas se usa la que tuvo el foco más recientemente y el campo `tab` del resultado lo indica. Pasa `tab_id` (lo lista `status`) para elegir otra.
- Una pestaña rechaza lo que su cuenta no puede hacer (por ejemplo `/culling` para una cuenta sin edición) y la herramienta devuelve ese rechazo.
- Lo que devuelve una pestaña no es de fiar: se limitan la profundidad y la longitud de cadenas y listas, y todo queda acotado por `max_bytes`.
- Errores: `no_tab` (ninguna pestaña conectada, o puente desactivado), `tab_timeout` (sin respuesta en `call_timeout_s`) y `tab_outdated` (la pestaña abierta no conoce la herramienta; recarga la página tras actualizar Facet).
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

Aparte del endpoint `/mcp`, una pestaña con sesión iniciada ofrece también las mismas herramientas `ui_*` a los agentes que viven en el propio navegador, mediante la API W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) (`navigator.modelContext`). Un asistente nativo del navegador ve así exactamente las herramientas listadas arriba, las ejecuta en la pestaña que estás mirando y no necesita token.

- **Solo en contexto seguro.** Facet registra las herramientas únicamente con HTTPS o en `localhost`. Con HTTP simple no se ofrecen y el cuadro **Conectar un asistente** lo indica; la conexión con token anterior sigue funcionando.
- Se registran cuando `viewer.mcp.enabled` es true y has iniciado sesión, y se retiran al cerrar sesión.
- Las herramientas hacen lo mismo, limitadas por el mismo nivel de cuenta, que en la tabla anterior.

## Resultados, límites y errores

Cada resultado es un sobre JSON: `{"ok": true, "data": ...}` o `{"ok": false, "error": "<code>", "message": "..."}`. Los listados devuelven `data.rows` (un conjunto compacto y fijo de campos por foto) más `total`.

- **Topes:** como máximo `max_rows` filas y `max_bytes` bytes serializados. Las últimas filas se descartan y se marca `truncated: true`. Un resultado sin filas que supere `max_bytes` pasa a ser un error `too_large`.
- **Límite de frecuencia:** `rate_per_min` llamadas por minuto y token (existe un presupuesto aparte, `write_rate_per_min`, para las llamadas de escritura). Superado: `rate_limited` con `retry_after_s`. Diez intentos bearer fallidos por minuto desde una dirección dan 429.
- **Códigos de error:** `forbidden_level` (endpoint desactivado, token no válido o nivel insuficiente), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`.
- **Códigos HTTP en la entrada:** 401 por token ausente o desconocido, 403 por una petición de navegador de otro origen, 404 cuando está desactivado.

## Notas de seguridad

- Los pies de foto, etiquetas, nombres de archivo, rutas y nombres de álbumes y personas vienen de tu biblioteca y pueden contener texto escrito para manipular a un asistente (inyección de prompts). Cada herramienta lleva la marca `facet/untrusted_content` e indica al modelo que los trate como datos. No des a un asistente que también lee contenido no fiable un modo de actuar sobre lo que encuentre aquí.
- Los tokens no caducan nunca. Revoca los que ya no uses.
- Los registros guardan el id del token, la herramienta, el resultado y el número de filas, nunca los argumentos ni el token.

## Limitaciones conocidas

- En una instalación abierta (sin contraseña), cualquiera que alcance el visor puede crear y revocar los tokens `_anonymous` compartidos. Define una contraseña antes de activar el endpoint en una red. El puente de pestaña amplía este riesgo: un cliente que no sea un navegador puede enviar un `Origin` inventado y un token nulo, registrar una pestaña `_anonymous` con el foco, responder a las llamadas `ui_*` con los datos que quiera y expulsar pestañas reales mediante el límite de 8 pestañas.
- Los límites de frecuencia y los contadores de autenticaciones fallidas viven en memoria en cada proceso; con `viewer.py --workers N` cada worker cuenta por separado.
- El registro de pestañas vive en memoria en un solo proceso. Usa un único worker (`viewer.py --workers 1`, el valor por defecto) si dependes de las herramientas `ui_*`; con varios workers una llamada puede llegar a un proceso que no conoce tu pestaña y responder `no_tab`.
- Un usuario puede tener como máximo 8 pestañas conectadas; abrir una novena cierra la más antigua.
