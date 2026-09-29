# Enlaces de YouTube

Pegar un enlace de YouTube y que Lexa descargue el vídeo a una carpeta propia,
lo meta en la cola y deje recortarlo con el editor que ya existe.

Tercera y última función de la versión 2.0, después del recorte por tramos y de
recoger los archivos añadidos mientras ya se está procesando.

## Lo que obliga YouTube hoy

Tres hechos, medidos el 28 de septiembre de 2026, que deciden el diseño entero:

**El vídeo ya no se descarga sin ejecutar JavaScript.** YouTube firma las URL de
los formatos con código que hay que correr; sin un motor de JavaScript la
descarga devuelve `HTTP 403: Forbidden`. El audio solo sí baja sin motor, pero
esa puerta está en vías de cerrarse: yt-dlp ya avisa de que la extracción sin
motor está obsoleta.

**El vídeo y el audio vienen separados.** YouTube dejó de servir formatos
«progresivos» —imagen y sonido en un archivo— en la mayoría de vídeos. Hay que
bajar dos archivos y unirlos.

**El códec por defecto no sirve.** Pidiendo el mejor vídeo a 480p, YouTube
entrega AV1, que ni PyAV ni el reproductor de Windows abren. Hay que pedir H.264
explícitamente.

## Decisiones

### El motor de JavaScript: QuickJS, dentro de Lexa

yt-dlp acepta cuatro motores. Pesan muy distinto:

| Motor | Tamaño | Sirve |
|---|---|---|
| QuickJS (`qjs.exe`) | 2,15 MB | sí |
| Deno | 42,6 MB comprimido | sí, es el de serie en yt-dlp |
| Node | ~80 MB | sí |
| Bun | ~90 MB | sí |

QuickJS resuelve el reto igual que los demás y cabe de sobra: Lexa pasa de 18 MB
a unos 20 MB, así que se sigue pasando por RAR sin pensarlo.

`qjs.exe` no vive en el repositorio. `build_exe.py` lo descarga de la publicación
fijada de quickjs-ng y comprueba su SHA-256 antes de empaquetarlo, igual que el
actualizador comprueba lo que se descarga. Corriendo desde el código fuente, si
falta, se baja la primera vez a `%LOCALAPPDATA%\Lexa\bin`.

Si el motor no está y no se puede descargar, Lexa no se rompe: avisa y baja solo
el audio, que es lo que de todos modos se transcribe.

### Unir las pistas: PyAV, no ffmpeg

yt-dlp une las dos pistas llamando a `ffmpeg`, que los usuarios de Lexa no
tienen. PyAV sí trae ffmpeg compilado dentro, así que Lexa hace la unión por su
cuenta: copia los paquetes de los dos archivos a un `.mp4` nuevo sin recodificar.
Tarda 0,2 s en un vídeo de diez minutos.

Para que yt-dlp nunca intente unir nada por su cuenta, los dos formatos se piden
en **dos llamadas separadas**. Si se piden juntos, yt-dlp busca ffmpeg en el
sistema; en la máquina de desarrollo lo encuentra —está instalado por winget— y
todo parece funcionar, pero en un equipo limpio fallaría. Dos llamadas eliminan
esa diferencia.

### Formatos

```
vídeo:  bestvideo[ext=mp4][vcodec^=avc1][height<=480]
audio:  bestaudio[ext=m4a]/bestaudio
```

H.264 a 480p porque el vídeo aquí solo sirve para reconocer por dónde vas al
recortar; más resolución solo engorda el archivo temporal. Un vídeo de diez
minutos ocupa 38 MB.

### Audio o vídeo, lo elige el usuario

Interruptor nuevo en los ajustes, «Descargar también el vídeo», encendido por
defecto. Apagado baja solo el audio: un vídeo de diez minutos pasa de 38 MB a
10 MB y de seis segundos a dos. En el editor de recorte se sigue viendo la onda,
el reloj y se sigue escuchando; lo único que falta es la imagen.

### Dónde caen las descargas

`%LOCALAPPDATA%\Lexa\youtube`, junto a los modelos. No en la carpeta del sistema
para temporales: son archivos grandes que conviene poder encontrar y borrar. Un
botón en los ajustes vacía la carpeta y dice cuánto liberó.

## Cómo se usa

Botón «Pegar enlace» junto a «Elegir archivos». Abre un cuadro pequeño con el
campo ya relleno si lo que hay en el portapapeles parece un enlace de YouTube.
Soltar un enlace arrastrado desde el navegador sobre la zona de archivos hace lo
mismo; hoy se ignora, porque solo se aceptan archivos locales.

Las descargas van en un hilo aparte, de una en una. Pegar tres enlaces seguidos
los encola: cada uno entra en la cola de transcripción en cuanto termina de
bajar, y si Lexa ya está transcribiendo, lo recoge al acabar con el archivo en
curso —eso ya funciona desde la versión anterior—. El progreso se cuenta en el
registro de actividad.

## Reparto

- **`core/youtube.py`** (nuevo): reconocer el enlace, consultar título y
  duración, descargar, unir con PyAV, asegurar el motor de JavaScript.
- **`core/paths.py`**: `youtube_dir()` y `bin_dir()`.
- **`core/models.py`**: `AppConfig.youtube_video`.
- **`ui/youtube_dialog.py`** (nuevo): el cuadro de pegar el enlace.
- **`ui/left_panel.py`**: el botón y aceptar enlaces soltados.
- **`ui/main_window.py`**: el hilo de descarga y la entrega a la cola.
- **`ui/right_panel.py`**: el interruptor y el botón de vaciar.
- **`build_exe.py`**: bajar y empaquetar `qjs.exe`.

## Errores

Cada uno con su mensaje, porque «no se pudo descargar» no ayuda a nadie:

- Enlace que no es de YouTube.
- Vídeo privado, borrado o restringido por edad.
- Sin conexión.
- El motor de JavaScript no está y no se pudo bajar: se sigue con solo audio.
- Retransmisión en directo: no se acepta, no tiene final.
- Descarga cancelada por el usuario.

## Lo que se prueba

- Reconocer enlaces: `youtube.com/watch`, `youtu.be`, `shorts`, con parámetros
  de más, y rechazar lo que no es de YouTube.
- Consulta, descarga en los dos modos y unión, contra un vídeo real con licencia
  libre.
- Que el resultado tenga las dos pistas, dure lo que debe y lo abran tanto PyAV
  como el cargador de audio de Lexa.
- Que el archivo entre en la cola y se pueda recortar como cualquier otro.
- Que sin motor de JavaScript se caiga a solo audio en vez de reventar.
- Que las dieciocho baterías anteriores sigan en verde.

## Lo que no se hace

Listas de reproducción, canales enteros, subtítulos de YouTube, elegir
resolución, ni otros sitios además de YouTube.

## Aviso

yt-dlp se rompe cada pocas semanas cuando YouTube cambia algo, y descargar
vídeos va contra las condiciones de uso de YouTube. Lexa lo ofrece como
herramienta para transcribir lo que el usuario decida; mantenerlo al día
significa actualizar yt-dlp de vez en cuando.
