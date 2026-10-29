# Primeros pasos

> 🌐 [English](../GETTING_STARTED.md) · [Français](../fr/GETTING_STARTED.md) · [Deutsch](../de/GETTING_STARTED.md) · [Italiano](../it/GETTING_STARTED.md) · **Español** · [Português](../pt/GETTING_STARTED.md) · [简体中文](../zh/GETTING_STARTED.md)

Tienes un lote nuevo de fotos y quieres una selección curada. Esta página recorre seis
pasos — importar, agrupar fotos parecidas, enseñar tu gusto, descartar, etiquetar,
exportar — y enlaza a los detalles de cada uno.

![Recorrido por la galería de Facet](../screenshots/walkthrough.gif)

## Antes de empezar

### 1. Define una contraseña de edición

Una instalación nueva es de **solo lectura**. Para editar (valoraciones, descarte, caras, álbumes, tags, escaneo),
define `viewer.edition_password` en `scoring_config.json` y reinicia el visor (la configuración no se recarga en caliente).

Con el `docker-compose.yml` incluido, la imagen genera una contraseña en el primer arranque
y la muestra una sola vez:

```bash
docker compose logs facet
```

Después inicia sesión como editor desde la galería. Detalles: [Modo de un solo usuario](VIEWER.md#modo-de-un-solo-usuario-predeterminado) y [Ajustes de Docker que puedes cambiar](INSTALLATION.md#ajustes-de-docker-que-puedes-cambiar).

![Inicio de sesión de edición](../screenshots/getting-started-edition-login.jpg)

### 2. Elige una forma de instalar

Docker es la ruta más corta en Windows, macOS y Linux; una instalación nativa es para quien
prefiere no usar contenedores. [¿Qué instalación me conviene?](INSTALLATION.md#qué-instalación-me-conviene)
incluye la tabla.

Dos cosas hacen tropezar a la gente con los contenedores:

- **Configuración y propiedad de los archivos.** El contenedor se ejecuta como uid 1000, que
  Podman sin root asigna a un subuid del host, así que los archivos que crea en `./facet-config`
  pueden no pertenecer a tu usuario. Consulta
  [Propiedad del archivo en el contenedor](INSTALLATION.md#propiedad-del-archivo-en-el-contenedor).
- **Las rutas son las del contenedor, no las del host.** Escaneas `/data/photos`, no
  `~/Pictures`. Consulta [Semántica de rutas en contenedores](DEPLOYMENT.md#semántica-de-rutas-en-contenedores).

### 3. ¿Sin GPU? No hay problema

Todo funciona con el perfil de CPU `legacy`, solo que más lento. Consulta
[Sin tarjeta gráfica](INSTALLATION.md#sin-tarjeta-gráfica) y
[¿Qué perfil se ajusta a mi hardware?](INSTALLATION.md#qué-perfil-se-ajusta-a-mi-hardware).

### 4. Cuida la memoria

Un contenedor con límite de memoria puede ser terminado a mitad de un escaneo con los perfiles
más grandes. Revisa
[Límites de memoria del contenedor](DEPLOYMENT.md#límites-de-memoria-del-contenedor) antes de limitar uno; en
un Mac consulta [Memoria en un Mac](INSTALLATION.md#memoria-en-un-mac).

## El flujo de trabajo

### Paso 1: Importar imágenes

Coloca tus fotos en la carpeta a la que apunta Facet (JPEG, HEIF/HEIC, PNG y los formatos RAW
habituales — consulta los [tipos de archivo admitidos](README.md#tipos-de-archivo-admitidos)) y
escanéala. Puedes hacerlo desde la terminal ([Escaneo](COMMANDS.md#escaneo)) o desde el
navegador:

- Define `viewer.features.show_scan_button` como `true` (viene desactivado).
- Un solo usuario: necesitas una contraseña de edición **y** haber iniciado sesión como editor.
  Multiusuario: necesitas el rol de superadministrador.
- Añade la carpeta a `viewer.scan_directories` para que el lanzador tenga algo que elegir.

Un botón **Escanear fotos nuevas** aparece entonces al final de la cabecera (barra inferior en
pantallas pequeñas). Consulta [Activador de escaneo](VIEWER.md#activador-de-escaneo). El primer escaneo
descarga los modelos de IA una sola vez ([Primera ejecución](INSTALLATION.md#primera-ejecución-qué-esperar)).

![Botón de escaneo al final de la cabecera](../screenshots/getting-started-scan-button.jpg)

### Paso 2: Encontrar duplicados, ráfagas y fotos parecidas

Facet agrupa por sí solo los fotogramas de ráfaga, los casi duplicados, los bracketing de
exposición y las panorámicas, y la galería **oculta la mayor parte de un conjunto por defecto**
para que veas un solo representante. Si el número de fotos te parece menor de lo esperado, son
los interruptores de ocultación, no archivos que faltan — consulta
[Opciones de visualización](VIEWER.md#opciones-de-visualización) y [Filtros predeterminados](VIEWER.md#filtros-predeterminados).
Para ver un conjunto completo lado a lado, abre [Fotos similares](VIEWER.md#fotos-similares) o el cuarto oscuro de
[Descarte](VIEWER.md#descarte); los conjuntos que deben permanecer enteros se describen en
[Panorámicas y bracketing de exposición](VIEWER.md#panorámicas-y-bracketing-de-exposición).

![Descarte de ráfagas](../screenshots/burst-culling.jpg)

### Paso 3: Enseñar a Facet cuál prefieres

Cada elección que haces al descartar, y cada decisión A/B en el modo de comparación, es una
señal. Facet aprende de ellas un ranking personal y lo expone como **Mis gustos**
([My Taste](VIEWER.md#my-taste)). Elige "esta gana a aquella" en el
[Modo de comparación por pares](VIEWER.md#modo-de-comparación-por-pares), o simplemente descarta — la
pantalla de [Descarte](VIEWER.md#descarte) registra tus conservadas y rechazadas. El clasificador se
reentrena solo tras suficientes elecciones nuevas, y únicamente cuando haces una pausa
([Reentrenamiento automático](CONFIGURATION.md#reentrenamiento-automático)).

![Comparar dos fotos](../screenshots/getting-started-teach.jpg)

### Paso 4: Descartar lo que no quieres

Rechaza fotos mientras descartas, o selecciona un conjunto y actúa sobre él
([Selección múltiple y acciones masivas](VIEWER.md#selección-múltiple-y-acciones-masivas)):
[Conservar % superior](VIEWER.md#conservar-el-n-superior), [Descartar a carpeta](VIEWER.md#descartar-a-carpeta) o
[Eliminar](VIEWER.md#eliminar).

- **Descartar a carpeta** muestra una simulación hasta que lo apliques.
- **Eliminar** envía los archivos a la papelera del sistema, y solo cuando `viewer.cull.allow_trash` está activado (desactivado por defecto).
- **[Deshacer](VIEWER.md#deshacer)** cubre los cambios de marcas y las confirmaciones de descarte, no los traslados ni las eliminaciones de archivos.
- **Los destinos** se limitan a tus directorios de escaneo más `viewer.export.allowed_target_dirs`
  ([Destinos de exportación y descarte](CONFIGURATION.md#destinos-de-exportación-y-descarte)).

Para descartar desde la terminal: [Descartar una sesión desde la terminal](COMMANDS.md#descartar-una-sesión-desde-la-terminal).

Las fotos que eliminas fuera de Facet dejan su fila en la base de datos hasta que ejecutes la limpieza de
[Mantenimiento de la base de datos](COMMANDS.md#mantenimiento-de-la-base-de-datos).

![Acciones masivas sobre una selección](../screenshots/getting-started-discard.jpg)

### Paso 5: Añadir tags y metadatos a las elegidas

Facet etiqueta las fotos automáticamente. Añade **tus propios tags** en la vista de detalle de la foto o desde las
acciones masivas. Los tags manuales sobreviven a los reescaneos, funcionan en filtros y búsqueda, y se ocultan en
los enlaces compartidos. Consulta [Tags manuales](VIEWER.md#tags-manuales) y
[Tags manuales y palabras clave XMP](INTEROP.md#tags-manuales-y-palabras-clave-xmp). Para llevar valoraciones
y palabras clave a Lightroom, Capture One, digiKam o darktable, consulta [Interoperabilidad](INTEROP.md)
(esto necesita [exiftool](INSTALLATION.md#exiftool) para incrustar).

![Tags manuales en la vista de detalle](../screenshots/getting-started-manual-tags.jpg)

### Paso 6: Exportar la selección curada

Pon tus elegidas en un álbum y exporta desde allí, o usa
[Exportación al editor](VIEWER.md#exportación-al-editor) para pasarlas a un editor, o
[Descartar a carpeta](VIEWER.md#descartar-a-carpeta) para copiar las elegidas a una carpeta. Se aplica la
misma lista de destinos permitidos que en el paso 4
([Destinos de exportación y descarte](CONFIGURATION.md#destinos-de-exportación-y-descarte)).

![Exportar a un editor](../screenshots/getting-started-export.jpg)

## Siguientes pasos

[Visor](VIEWER.md) para cada función de la galería, [Comandos](COMMANDS.md) para la terminal,
[Puntuación](SCORING.md) para ajustar qué cuenta como una buena foto, y
[Despliegue](DEPLOYMENT.md) para un NAS o un servidor compartido.
