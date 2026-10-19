# Agentes de IA (MCP)

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · **Español** · [Português](../pt/AGENTS.md) · [简体中文](../zh/AGENTS.md)

Facet puede actuar como servidor [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), de modo que un asistente de IA como Claude Code pueda buscar e inspeccionar tu biblioteca con los mismos filtros que la galería. El endpoint es de solo lectura: expone nueve herramientas de lectura y no cambia nada en tu biblioteca.

## Activarlo

El endpoint está **desactivado por defecto**. Pon `viewer.mcp.enabled` a `true` en `scoring_config.json` (ver [Endpoint de agentes (MCP)](CONFIGURATION.md#endpoint-de-agentes-mcp)) y reinicia el visor, o recarga la configuración. Mientras esté desactivado, `/mcp` y todas las rutas `/api/mcp/*` responden 404.

El endpoint es `POST /mcp` en el puerto del visor: Streamable HTTP, sin estado, respuestas JSON simples. `GET` responde 405. En un proxy inverso no hacen falta cabeceras WebSocket.

## Crear un token

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

Las nueve herramientas registradas son de solo lectura:

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

## Resultados, límites y errores

Cada resultado es un sobre JSON: `{"ok": true, "data": ...}` o `{"ok": false, "error": "<code>", "message": "..."}`. Los listados devuelven `data.rows` (un conjunto compacto y fijo de campos por foto) más `total`.

- **Topes:** como máximo `max_rows` filas y `max_bytes` bytes serializados. Las últimas filas se descartan y se marca `truncated: true`. Un resultado sin filas que supere `max_bytes` pasa a ser un error `too_large`.
- **Límite de frecuencia:** `rate_per_min` llamadas por minuto y token (existe un presupuesto aparte, `write_rate_per_min`, para las llamadas de escritura). Superado: `rate_limited` con `retry_after_s`. Diez intentos bearer fallidos por minuto desde una dirección dan 429.
- **Códigos de error:** `forbidden_level` (endpoint desactivado, token no válido o nivel insuficiente), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `too_large`.
- **Códigos HTTP en la entrada:** 401 por token ausente o desconocido, 403 por una petición de navegador de otro origen, 404 cuando está desactivado.

## Notas de seguridad

- Los pies de foto, etiquetas, nombres de archivo, rutas y nombres de álbumes y personas vienen de tu biblioteca y pueden contener texto escrito para manipular a un asistente (inyección de prompts). Cada herramienta lleva la marca `facet/untrusted_content` e indica al modelo que los trate como datos. No des a un asistente que también lee contenido no fiable un modo de actuar sobre lo que encuentre aquí.
- Los tokens no caducan nunca. Revoca los que ya no uses.
- Los registros guardan el id del token, la herramienta, el resultado y el número de filas, nunca los argumentos ni el token.

## Limitaciones conocidas

- En una instalación abierta (sin contraseña), cualquiera que alcance el visor puede crear y revocar los tokens `_anonymous` compartidos. Define una contraseña antes de activar el endpoint en una red.
- Los límites de frecuencia y los contadores de autenticaciones fallidas viven en memoria en cada proceso; con `viewer.py --workers N` cada worker cuenta por separado.
- `viewer.mcp.bridge` lo lee la herramienta `status`, pero por ahora nada más lo usa.
