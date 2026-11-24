# YoClipeo

Convierte videos largos en clips verticales para TikTok, Reels y Shorts. Corre en tu PC con Windows: transcribe, elige los momentos con IA, encuadra, pone subtítulos y exporta. Sin marca de agua y sin cuenta.

[![Descargas](https://img.shields.io/github/downloads/luisolisd/yoclipeo/total?label=descargas&color=E8704F)](https://github.com/luisolisd/yoclipeo/releases) [☕ Invítame un café](https://ko-fi.com/luisolisd)

## Qué necesitas
- Windows 10 u 11 de 64 bits.
- [Python 3.11](https://www.python.org/downloads/release/python-3119/) de 64 bits («Windows installer (64-bit)»). Marca «Add python.exe to PATH» al instalarlo.
- Espacio en disco: cerca de 1.2 GB para el programa y su modelo de voz (unos 3.5 GB más con las librerías de NVIDIA y su modelo de voz) y el que pidan tus videos. Un directo de 8 horas en 1080p puede pesar 30 GB.
- Opcional: una GPU NVIDIA para transcribir más rápido.
- Opcional: [Ollama](https://ollama.com) para que la IA elija los momentos sin internet ni costo.

## Instalar
1. Descarga el ZIP de [la última versión](https://github.com/luisolisd/yoclipeo/releases/latest) y extráelo en una carpeta.
2. Doble clic en **`Instalar YoClipeo.bat`**. Crea su propio entorno en `.venv` y no toca otros programas.
3. Doble clic en **`Iniciar YoClipeo.bat`**. Se abre http://127.0.0.1:8765. Cierra la ventana negra para apagarlo.

Con el primer video se baja el modelo de voz: unos 500 MB en el procesador, o 1.6 GB con GPU NVIDIA.

Si Windows avisa que el archivo viene de internet, revisa que lo bajaste de este repositorio antes de aceptar. Los `.bat` se pueden abrir con el Bloc de notas.

### Que la IA elija los momentos
En **Ajustes** puedes usar:
- **IA local (Ollama):** instálalo y en Ajustes agrega un modelo. Te dice cuánto pesa y cómo iría en tu PC antes de bajarlo. Con 4 GB de GPU, `qwen3.5:4b` va bien.
- **Otro servidor local:** LM Studio, llama.cpp, Jan, KoboldCpp, GPT4All o vLLM, con API compatible con OpenAI.
- **Claude (API):** con tu propia API key. Se paga aparte.
- **Reglas:** sin IA. Elige por pausas y frases con gancho.

En «Automático» usa lo primero que encuentre listo: Claude, otro servidor, Ollama o reglas.

## Qué hace
- **Entrada:** un archivo, la ruta de un video de tu PC o un enlace de YouTube, Kick, Twitch, TikTok, Drive o Zoom.
- **Directos:** YouTube en vivo (lo que ya pasó, lo que viene o seguirlo por horas) y Kick en vivo (esperar a que termine o bajar lo que va).
- **Transcripción** palabra a palabra en español, inglés, portugués, francés, italiano o detección automática.
- **Clips** con titular, descripción, hashtags, potencial y motivo.
- **Encuadre:** vertical siguiendo a quien habla, apilado, cámara y juego, video entero con fondo desenfocado o dos videos sincronizados.
- **Subtítulos:** karaoke o dinámico, con zooms, emojis y quitar silencios.
- **Marca:** tus logos o stickers en los clips.
- **Exportar:** 1080p, 720p, 480p o MP3.
- **Publicar en YouTube:** ahora, oculto, en privado o programado, uno o varios clips.
- **Predeterminados** generales y por carpeta.

## Cómo se usa
1. Pulsa **Nuevo** y pega un enlace o elige un video.
2. Espera el análisis. En **Cola** se ve el avance.
3. Abre el proyecto: el mapa muestra dónde está cada clip. Un clic en el mapa reproduce ese momento; arrastra para marcar un tramo y crear un clip a mano.
4. En el editor cambia el titular, los subtítulos, el encuadre o el corte. Con iPhone o Android ves cómo queda en YouTube, TikTok y Reels, y te avisa si algo se tapa.
5. Exporta. Los archivos quedan en `data\projects\<id>\exportados`.
6. Si conectaste tu canal, publícalo desde **Salida** o selecciona varios clips y prográmalos.

## Publicar en YouTube (opcional)
YouTube solo acepta subidas de programas registrados en Google. Cada persona registra el suyo: es gratis, se hace una vez y no hay que programar nada. Así nadie comparte claves, y el límite diario de subidas es solo tuyo.

1. Entra al [modo personal de Google](https://console.cloud.google.com/auth/overview/personal) con la misma cuenta de tu canal. Crea un proyecto nuevo por ti.
2. En tipo de aplicación elige **App de escritorio**, acepta los términos y pulsa **Continuar**.
3. Pulsa **Descargar JSON** en ese momento: después Google ya no muestra la clave completa.
4. Con ese proyecto elegido arriba, abre [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com) y pulsa **Habilitar**.
5. En YoClipeo, **Ajustes → YouTube**, elige ese archivo y pulsa **Conectar con YouTube**. Deja marcados los dos permisos.

No hace falta marca, dominio ni publicar la app. Solo funciona con la cuenta de Google que la creó; si sale `client_user_mismatch`, entraste con otra.

No compartas ese archivo. Te sugerimos subir el primer clip en privado para revisar cómo queda. Cada envío pide confirmación. Varios clips se suben en el orden del video. Guarda tus hashtags favoritos para ponerlos con un clic.

**Listas de reproducción (opcional):** para agregar tus videos a una lista, pulsa **Activar listas**. Google pide un permiso más amplio, administrar tu cuenta de YouTube; con él solo se leen tus listas y se agregan los videos que subas desde aquí.

Para quitar el permiso, pulsa **Desconectar** en Ajustes o entra a [tu cuenta de Google](https://myaccount.google.com/permissions).

Al publicar aplican los [Términos de YouTube](https://www.youtube.com/t/terms) y la [política de privacidad de Google](https://policies.google.com/privacy).

## Tus datos
- Todo queda en la carpeta `data`: videos, proyectos, ajustes y claves. **No la compartas ni la subas.**
- El guion sale de tu PC solo si eliges Claude o un servidor que esté en otro equipo.
- Un clip sube a YouTube solo si conectas tu canal y lo confirmas. El permiso se guarda cifrado con tu cuenta de Windows y no pasa por ningún otro servidor.
- El programa escucha únicamente en tu PC (127.0.0.1).
- Para avisarte de versiones nuevas consulta este repositorio cada 10 minutos. No manda nada tuyo, y se apaga en Ajustes, «Acerca de».

## Problemas comunes
- **«Falta una DLL» al instalar:** instala [Microsoft Visual C++ Redistributable x64](https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist).
- **Un enlace dejó de bajar:** los sitios cambian seguido. Actualiza con `.venv\Scripts\python.exe -m pip install -U yt-dlp`.
- **Va lento:** copiar y transcribir usan todo el procesador. Baja en 720p los videos de más de una hora. En Ajustes se ve qué pasó la prueba en tu equipo.
- **Se cerró a medio análisis:** al abrirlo continúa solo. La copia de vista previa ya hecha no se repite. La transcripción tampoco, si ya había terminado.
- **La PC se suspende:** en esperas y videos largos debe quedar encendida y sin suspenderse.

## Actualizar
Cuando hay una versión nueva aparece el botón **Actualizar** abajo a la izquierda, arriba del de claro u oscuro. Te dice qué cambió, la descarga de aquí, la instala y vuelve a abrir sola. Si está procesando, descargando o exportando algo, espera a que termine. Si la versión nueva no abre, regresa a la anterior.

Para eso hay que abrirlo con `Iniciar YoClipeo.bat`. Tus videos, proyectos, modelos y ajustes no se tocan.

**Desde la 1.2.1**, que todavía no trae el botón: descarga el ZIP, ciérralo, copia su contenido encima sin borrar `data` y abre `Instalar YoClipeo.bat` otra vez.

## Uso responsable
Baja y publica solo contenido tuyo o con permiso, y respeta las reglas de cada plataforma.

## Licencias de terceros
Las letras y el detector de caras conservan la suya: [assets/LICENCIAS.md](assets/LICENCIAS.md).

## Aviso
Desarrollado por luisolisd.

Gratis. Prohibida su venta.

Los cambios de cada versión están en [CAMBIOS.md](CAMBIOS.md).
