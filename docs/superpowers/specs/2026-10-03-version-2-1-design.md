# Lexa 2.1

Tres cosas pedidas por quienes la usan: que cada transcripción se guarde en
cuanto está lista, que el equipo no se duerma a mitad del trabajo, y poder
comprimir imágenes y PDF a un tamaño concreto.

## 1. Cada archivo se guarda en cuanto termina

Hoy la exportación automática ocurre al terminar **todo** el lote. Quien deja
cinco audios y se va no tiene nada en disco hasta que acaba el último; si cierra
Lexa antes, pierde lo ya transcrito.

El worker ya avisa por archivo con `file_done`, y la ventana ya lo escucha. Ahí
se exporta ese archivo y se guarda la ruta en `FileItem.exported_path`.

La exportación de cierre salta los archivos que ya tienen ruta. Sin eso volvería
a escribirlos y, como el nombre se desambigua solo, dejaría `archivo (2).txt` y
`archivo (3).txt` por cada vuelta.

**Documento combinado.** Con `output_mode = "merged"` no se puede ir exportando
sobre la marcha: el documento único necesita todos los resultados. En ese modo
se mantiene la exportación al final, y el registro lo dice la primera vez para
que no parezca que la nueva forma de guardar no funciona.

## 2. La suspensión del equipo

Son dos problemas distintos, y el que más molesta no es el evidente.

### El equipo se duerme mientras Lexa trabaja

Transcribir no cuenta como actividad para Windows: sin ratón ni teclado, el
equipo se suspende a los quince minutos aunque esté a pleno rendimiento. Es
justo lo que hace quien deja una clase de dos horas y se va.

Mientras haya algo procesándose o descargándose, Lexa pide a Windows que no
suspenda el sistema, con `SetThreadExecutionState(ES_CONTINUOUS |
ES_SYSTEM_REQUIRED)`. La pantalla sí puede apagarse: se bloquea la suspensión
del sistema, no el ahorro de energía de la pantalla. Al terminar se suelta.

### Si se suspende igual, las cuentas se falsean

Con la tapa cerrada o por política de batería, el equipo se suspende de todas
formas. Y entonces aparece lo segundo: en Windows, `time.monotonic()` de Python
es `GetTickCount64`, que **sí cuenta el tiempo suspendido** (comprobado: las dos
lecturas coinciden al decimal).

Un archivo de tres minutos atravesado por dos horas de suspensión diría «2 h
03 m», el ritmo se desplomaría y el tiempo restante se dispararía.

`QueryUnbiasedInterruptTime` no cuenta la suspensión y está en `kernel32`, sin
dependencias nuevas. Pasan a usarlo las tres cuentas que miden trabajo:
`FileItem.elapsed` en `core/worker.py`, y el ritmo y el tiempo restante en
`ui/footer.py`.

Fuera de Windows se cae a `time.monotonic()`, que allí sí excluye la suspensión.

**Lo que no cambia:** la transcripción se reanuda sola, porque el proceso se
congela entero y continúa donde estaba. Las descargas de YouTube pierden la
conexión, y de eso ya se encargan los reintentos de la 2.0.

## 3. Comprimir imágenes y PDF

### Dónde vive

Modo nuevo en la barra superior: **Transcribir** y **Comprimir**. Cada uno con
su zona de arrastre, su lista y sus ajustes. Comprimir no es transcribir, y
mezclarlos obligaría a pasar una foto por el OCR solo para encogerla.

El modo elegido se recuerda entre sesiones.

### Cómo se comprime una imagen

Buscar solo la calidad no basta. Midiendo una foto de 2100×1400 y 506 KB contra
un objetivo de 75 KB:

| Escala | Calidad JPEG | Resultado |
|---|---|---|
| 100 % | 30 | 73 KB, con artefactos visibles |
| 75 % | 48 | 74 KB |
| 50 % | 78 | 74 KB, limpia |

Mismo peso, resultados muy distintos. Machacar la calidad a tamaño completo es
lo peor de las tres.

El procedimiento: bisección de la calidad entre 20 y 95 —seis pruebas— y, si
para llegar al objetivo hay que bajar de **calidad 70**, se reduce el tamaño en
pasos del 85 % y se vuelve a probar, hasta un mínimo de 320 px de lado. Se
devuelve la primera combinación que cumple el objetivo sin bajar de ese suelo
de calidad; si ninguna lo consigue, la que más se acerque, diciendo cuánto se
quedó.

**Transparencia.** JPEG no la tiene. Una imagen con canal alfa va a WebP, que sí
la conserva y comprime mejor que PNG. Pillow trae WebP compilado (comprobado).

### Cómo se comprime un PDF

Lo que pesa en un PDF son las imágenes de dentro. Con PyMuPDF se recorren, se
recomprimen con el mismo procedimiento y se vuelven a insertar.

Un PDF de solo texto ya es pequeño y no tiene nada que recomprimir: se deja
igual y se dice, en vez de dejar una copia idéntica sin explicación.

### El original no se toca

`foto.jpg` deja `foto (comprimido).jpg` al lado. Comprimir es con pérdida e
irreversible: si el resultado no convence, el original sigue ahí.

### La pantalla

Misma tarjeta redondeada y mismos componentes que el resto de Lexa. Arriba la
zona de arrastre; debajo la lista, con una fila por archivo que muestra el
tamaño de antes, el de después y lo que se ahorró; y el objetivo en KB con su
campo, 75 por defecto.

Se adapta al ancho y al alto como el resto: lo aprendido en la 2.0.1 vale aquí
—los mínimos que se declaran son los mínimos de verdad, no los cómodos— para
que nada se corte ni obligue a desplazar en una pantalla pequeña.

La compresión va en un hilo aparte, con su avance en la misma barra del pie.

## Reparto

- **`core/suspension.py`** (nuevo): el reloj que no cuenta lo dormido y la
  petición de no suspender.
- **`core/compress.py`** (nuevo): comprimir imágenes y PDF a un objetivo.
- **`core/worker.py`**: medir con el reloj nuevo.
- **`core/exporter.py`**: saltar lo ya exportado.
- **`core/models.py`**: `FileItem.exported_path`, `AppConfig.compress_target_kb`,
  `AppConfig.last_mode`.
- **`ui/footer.py`**: ritmo y tiempo restante con el reloj nuevo.
- **`ui/main_window.py`**: exportar por archivo, cambiar de modo, mantener
  despierto mientras trabaja.
- **`ui/title_bar.py`**: el conmutador de modo.
- **`ui/compress_panel.py`** (nuevo): la pantalla de comprimir.

## Lo que se prueba

- Que al terminar cada archivo queda su `.txt`, y que al cerrar el lote no se
  vuelve a escribir ni aparecen duplicados numerados.
- Que en modo combinado se sigue exportando al final, una sola vez.
- Que el reloj nuevo no cuenta un salto de suspensión y el de siempre sí.
- Que se pide no suspender al empezar y se suelta al terminar, también cuando el
  lote acaba con error o se detiene a mano.
- Comprimir imágenes reales a 75 KB: que se cumple el objetivo, que el original
  queda intacto, que la transparencia sobrevive y que un objetivo imposible se
  reporta en vez de fingir.
- Que la pantalla de comprimir cabe sin recortes ni desplazamiento a los anchos
  y altos de siempre.
- Que las 23 baterías anteriores siguen en verde.

## Lo que no se hace

Comprimir vídeo o audio, formatos de salida a elegir a mano, recorte o rotación
de imágenes, ni comprimir por lotes desde la línea de comandos.
