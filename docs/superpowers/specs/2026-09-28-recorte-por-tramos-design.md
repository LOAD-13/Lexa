# Recorte por tramos

Especificación 1 de 3 del camino hacia Lexa 2.0. Las otras dos —descarga desde
YouTube y proceso de varios a la vez— van en documentos aparte, porque tocan
partes distintas y pueden soltarse por separado. La de YouTube desemboca en
esta: descarga a temporal, el archivo entra en la cola y se recorta aquí.

## El problema

Hoy Lexa transcribe el archivo entero o nada. Para sacar cinco minutos de una
clase de una hora hay que transcribir la hora, esperar, y buscar el trozo a
mano en el texto. Con los tiempos medidos en CPU (2,3× tiempo real), eso son
veintiséis minutos de espera para aprovechar cinco.

## Qué se construye

Un selector de tramos con forma de onda y reproductor, accesible desde cada
archivo de la cola. Sin tramos marcados, todo se comporta exactamente como
hoy.

```
┌──────────────────────────────────────────────────────────┐
│  clase.mp4                                  00:00 / 17:46│
│  ┌────────────────────────────────────────────────────┐  │
│  │                    [ vídeo ]                       │  │
│  └────────────────────────────────────────────────────┘  │
│  ▂▅█▇▃▁▂▆█▅▃▂▁▄▇█▆▄▂▁▃▅▇█▆▃▁▂▄▆█▇▅▃▂▁▃▅▇█▆▄▂▁▂▄▆█▇▅▃▂▁  │
│  └──[███ tramo 1 ███]──────────────[██ tramo 2 ██]────┘  │
│                                                          │
│  ▶ ⏸   0.5× 0.75× 1× 1.5× 2×      ▶ Solo lo seleccionado │
│                                                          │
│  Tramo 1   03:12 → 08:40   (5:28)                    ✕   │
│  Tramo 2   40:05 → 45:19   (5:14)                    ✕   │
│                                                          │
│  Se transcribirán 10:42 de 17:46     [Cancelar]  [Aplicar]│
└──────────────────────────────────────────────────────────┘
```

## Interacción

Sin botón de modo: el gesto decide qué se hace.

| Gesto | Efecto |
|---|---|
| Clic sin arrastrar | El cursor de reproducción salta ahí |
| Arrastrar en zona libre | Crea un tramo |
| Arrastrar un borde | Redimensiona ese lado |
| Arrastrar por dentro | Mueve el tramo entero, conservando duración |

**Umbral de 4 píxeles** antes de considerar que hay arrastre. Sin él, cada clic
con pulso tembloroso crea un tramo minúsculo y la herramienta se vuelve
antipática. Por lo mismo, al soltar se descartan los tramos de menos de 0,3 s.

**Zona de agarre de 6 píxeles** en los bordes, con el puntero cambiando a ↔
para que se vea que se va a redimensionar y no a crear otro tramo encima.

Mientras se arrastra, un rótulo junto al cursor muestra `03:12 → 05:40 (2:28)`.

**Teclado:** espacio reproduce y pausa, Supr borra el tramo seleccionado,
Ctrl+Z deshace el último cambio sobre los tramos.

**Velocidades:** 0,5× / 0,75× / 1× / 1,5× / 2×.

### Ajuste a los silencios

Al soltar un borde, si hay un punto de poca energía a menos de 0,25 s, el corte
se pega ahí. Cortar a ojo casi siempre parte una palabra por la mitad.

Se calcula desde la envolvente de la onda que ya se dibuja, **no desde el VAD**:
ese filtro ya demostró que en audios comprimidos o de sala marca como silencio
tramos que son voz, y un ajuste basado en él llevaría los cortes justo a donde
no debe.

Se anula manteniendo **Alt** al soltar.

## Arquitectura

```
ui/left_panel.py     botón «Recortar» en cada archivo de la cola
        ↓
ui/trimmer.py        ventana modal: reproductor, controles, lista de tramos
        ↓
ui/waveform.py       widget de onda: dibujo, gestos, ajuste a silencios
        ↓
core/models.py       FileItem.ranges: list[tuple[float, float]]
        ↓
core/worker.py       pasa los tramos al motor y remapea los tiempos
        ↓
core/engines/media.py   load_audio(path, ranges) decodifica solo esos tramos
```

### `media.load_audio(path, ranges=None)`

Con tramos, decodifica solo esos y los concatena. Usa el `seek` de PyAV: cortar
del minuto 40 no cuesta decodificar los 40 anteriores.

### `media.map_time(t, ranges)`

Convierte un instante del audio concatenado al instante equivalente en el
archivo original.

### Widget de onda

Los picos salen de reducir el PCM ya decodificado a ~2.000 columnas. La
envolvente resultante sirve para dibujar y para el ajuste a silencios.

## Decisiones

**Las marcas de tiempo se mapean al archivo original.** Al recortar 40:05→45:19,
el primer segmento dice 40:05 y no 00:00. Así un SRT generado desde un recorte
sigue cuadrando con el vídeo completo. Lo contrario sería una trampa silenciosa.

**La clave de caché incluye los tramos.** Sin eso, recortar un archivo ya
procesado devolvería la transcripción entera de la vez anterior. Es el mismo
fallo que se evitó al meter el diccionario en la clave.

**El reproductor lleva red de seguridad.** QMediaPlayer usa los códecs de
Windows y puede no abrir un mkv o un webm que Lexa sí transcribe. Cuando falle,
en lugar de un recuadro negro se muestran fotogramas extraídos con PyAV —que
abre todo lo que Lexa acepta— y el audio se sigue oyendo. Coste en el paquete:
2,5 MB de DLL más 0,9 MB de plugins.

## Fuera de alcance

- Zoom en la línea de tiempo. Con 17 minutos sobre 900 píxeles cada píxel es un
  segundo, suficiente para marcar «del 3:12 al 8:40». El zoom obliga a scroll,
  dos sistemas de coordenadas y recalcular la onda; se añade si al usarlo se
  echa de menos de verdad.
- Unir trozos de archivos distintos, filtros de audio, exportar el vídeo
  recortado. Eso es un editor, y no es lo que se quiere.

## Pruebas

Condición de entrada: las 14 baterías actuales siguen en verde. La prioridad es
no romper lo que ya funciona.

Nuevas:

1. Decodificar tramos devuelve exactamente el audio esperado, comprobado contra
   el recorte hecho a mano sobre el audio completo.
2. Los tiempos de los segmentos se mapean al archivo original.
3. La clave de caché cambia con los tramos y no con nada más.
4. Tramos invertidos, solapados, fuera de rango o de duración cero se
   normalizan al aplicarlos.
5. Sin tramos, el resultado es idéntico byte a byte al de hoy.
6. El widget de onda distingue clic de arrastre con el umbral, agarra bordes,
   mueve tramos y ajusta a los silencios.
7. La ventana monta, reproduce y responde sin pantalla.
