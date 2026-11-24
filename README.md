# YoClipeo

Convierte videos largos en clips verticales para TikTok, Reels y Shorts. Corre en tu PC con Windows: transcribe, elige los momentos con IA, encuadra, pone subtítulos y exporta. Sin marca de agua y sin cuenta.

[☕ Invítame un café](https://ko-fi.com/luisolisd)

## Qué necesitas
- Windows 10 u 11 de 64 bits.
- [Python 3.11](https://www.python.org/downloads/release/python-3119/) de 64 bits («Windows installer (64-bit)»). Marca «Add python.exe to PATH» al instalarlo.
- Espacio en disco: cerca de 1.2 GB para el programa y su modelo de voz (unos 3.5 GB más con las librerías de NVIDIA y su modelo de voz) y el que pidan tus videos. Un directo de 8 horas en 1080p puede pesar 30 GB.
- Opcional: una GPU NVIDIA para transcribir más rápido.
- Opcional: [Ollama](https://ollama.com) para que la IA elija los momentos sin internet ni costo.

## Instalar
1. En [la página del proyecto](https://github.com/luisolisd/yoclipeo): **Code → Download ZIP**. Extrae el ZIP en una carpeta.
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
- **Predeterminados** generales y por carpeta.

## Cómo se usa
1. Pulsa **Nuevo** y pega un enlace o elige un video.
2. Espera el análisis. En **Cola** se ve el avance.
3. Abre el proyecto: el mapa muestra dónde está cada clip. Arrastra en el mapa para crear uno a mano.
4. En el editor cambia el titular, los subtítulos, el encuadre o el corte.
5. Exporta. Los archivos quedan en `data\projects\<id>\exportados`.

## Tus datos
- Todo queda en la carpeta `data`: videos, proyectos, ajustes y claves. **No la compartas ni la subas.**
- El guion sale de tu PC solo si eliges Claude o un servidor que esté en otro equipo.
- El programa escucha únicamente en tu PC (127.0.0.1).

## Problemas comunes
- **«Falta una DLL» al instalar:** instala [Microsoft Visual C++ Redistributable x64](https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist).
- **Un enlace dejó de bajar:** los sitios cambian seguido. Actualiza con `.venv\Scripts\python.exe -m pip install -U yt-dlp`.
- **Va lento:** copiar y transcribir usan todo el procesador. Baja en 720p los videos de más de una hora. En Ajustes se ve qué pasó la prueba en tu equipo.
- **Se cerró a medio análisis:** al abrirlo continúa solo. La copia de vista previa ya hecha no se repite; la transcripción sí.
- **La PC se suspende:** en esperas y videos largos debe quedar encendida y sin suspenderse.

## Actualizar
Descarga el ZIP nuevo desde [la página del proyecto](https://github.com/luisolisd/yoclipeo) y copia su contenido encima, sin borrar `data`. Después abre `Instalar YoClipeo.bat` otra vez.

## Uso responsable
Baja y publica solo contenido tuyo o con permiso, y respeta las reglas de cada plataforma.

## Licencias de terceros
Las letras y el detector de caras conservan la suya: [assets/LICENCIAS.md](assets/LICENCIAS.md).

## Aviso
Desarrollado por luisolisd.

Gratis. Prohibida su venta.

Los cambios de cada versión están en [CAMBIOS.md](CAMBIOS.md).
