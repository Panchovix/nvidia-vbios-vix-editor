# Interfaz gráfica offline

[English](gui.md) | Español

La GUI GTK4 utiliza la biblioteca pública `nvidia_vbios.editor`. Abre ROMs locales,
prepara los cambios en memoria y guarda una copia nueva junto con un manifiesto
JSON. No flashea, despliega ni activa una ROM, no recarga el driver y no cambia la
configuración de una GPU. No hace falta tener esa GPU instalada para inspeccionar
su ROM.

## Idioma y lanzamiento

El idioma predeterminado es inglés. Usa `--lang es` para español y `--lang en`
para inglés. Los identificadores de campo, las unidades y el formato JSON no
cambian con el idioma. La evidencia del backend se conserva en inglés en el
manifiesto JSON; `nvbios fields` la lista junto con los diagnósticos originales. Controles nativos del
escritorio o portal, como Cancelar, pueden usar el idioma del escritorio; los
títulos, filtros y botones de aceptación usan el idioma elegido para la aplicación.

Desde el repositorio, con un Python que disponga de PyGObject:

```sh
./nvbios gui --lang es
./nvbios gui --lang es /ruta/original.rom
```

Después de instalar el paquete, puedes utilizar cualquiera de los dos lanzadores:

```sh
nvbios gui --lang es /ruta/original.rom
nvbios-editor --lang es /ruta/original.rom
```

También puedes ejecutar el módulo si el paquete está disponible para ese Python:

```sh
python3 -m nvidia_vbios.gui --lang es /ruta/original.rom
```

La GUI necesita PyGObject (`gi`) y GTK 4.10 o posterior con sus datos de
introspección. Si un entorno virtual no encuentra `gi`, utiliza un Python
compatible que pueda acceder a esos paquetes. La biblioteca y la CLI siguen
funcionando sin las dependencias gráficas.

## Flujo de edición

1. **Abrir ROM…** carga un archivo local. La identidad, el formato y la integridad
   se obtienen de sus bytes; el nombre del archivo no selecciona el editor.
2. Introduce valores en los campos admitidos. Cada control indica su unidad y el
   valor original. Los hashes, rangos de codificación, selectores y aliases están
   en el manifiesto JSON y en `nvbios fields`. Esos rangos no son límites
   eléctricos seguros. Los marcadores genéricos de corriente de entrada y OCP
   (`current_limit_a`, `ocp_limit_a`) y el techo MSVDD de las imágenes de un solo
   riel tampoco se muestran mientras su valor es desconocido (ninguna fila de la
   VBIOS los respalda); `nvbios fields` los lista.
   **Piso de potencia de la placa** (`power_min_w`) acepta desde 1 W hasta el
   valor TGP nominal por defecto, en pasos exactos de 0,001 W. El **Techo de
   potencia de la placa** mantiene como mínimo los valores nominales por defecto.
   Los campos experimentales (potencia por defecto al arrancar, corriente de
   entrada de 12 V y rangos de offset de reloj) llevan una insignia. Cambia
   juntos los valores relacionados, como un nuevo valor por defecto y su techo:
   el orden mínimo <= por defecto <= máximo se comprueba sobre el resultado
   combinado. Los valores de corriente de entrada de 12 V son valores guardados de
   la política, no corrientes seguras garantizadas; los límites del conector, del
   slot y de los cables siguen aplicando. **Mostrar campos avanzados (estilo XOC)**
   (desmarcada por defecto) muestra campos opcionales como la potencia nominal de
   las políticas fijas 2/7, los umbrales de hardware (corriente del slot; en
   Ampere y Turing la corriente de los conectores; en Ada la potencia de salida
   NVVDD y la corriente de entrada de 12 V, rotulada "umbral"), el límite de
   corriente de salida NVVDD y los voltajes fijos REL/ALT de Turing y, en
   Blackwell y Ada, **REL y ALT de NVVDD siguen a OV** (un interruptor: activado
   da el límite de voltaje plano estilo XOC; guárdalo solo y conserva la imagen
   original para volver atrás) y, en Blackwell, **Parada de ventiladores en
   reposo** (un interruptor para los bits que permiten que los ventiladores se
   detengan en reposo, probado en hardware en una RTX 5090; experimental) y, en
   Blackwell, Ada y Ampere, los **umbrales inferior y superior de la parada en
   reposo** de cada ventilador y curva adicional (las dos temperaturas guardadas
   junto a esos bits; lo más probable es que los ventiladores se detengan bajo el
   inferior y arranquen sobre el superior; en una RTX 5080, subir el superior los
   mantuvo detenidos por debajo; en Ada y Ampere solo se pueden editar donde la
   parada en reposo está activa, y ahí no están probados en hardware;
   experimental); los valores ya escritos se
   conservan al marcarla. Los campos 0/1 de solo lectura muestran Activado o
   Desactivado. **Multiplicador
   de shunt (x)** (1 = desactivado, hasta 10) es solo informativo: en las filas de
   potencia de la tarjeta, potencia/corriente del slot PCIe, potencia/corriente de
   los conectores y corriente de entrada de 12 V agrega una nota con el límite real en una tarjeta con shunt mod,
   aproximadamente el valor guardado por el multiplicador, suponiendo el mismo
   factor en todos los shunts de entrada de 12 V. Los límites de salida
   NVVDD/MSVDD los mide el VRM y no se escalan; no se escribe nada en la ROM. En
   las imágenes Ampere donde otra fila de potencia también limita la suma de los
   canales de conector, cada fila de conector anota los valores nominal y máximo de
   esa fila; donde esa fila tiene un campo, sube también la **suma de potencia de
   conectores**. El
   OCP nominal de salida y la potencia del slot de la SFF también son
   experimentales: el valor nominal es el que el firmware aplica desde el arranque,
   así que bajarlo limita la tarjeta.
   En Blackwell, el piso modifica la fila TGP8 y conserva los mínimos distintos
   de las filas2/7; los perfiles reconocidos sólo reemplazan máximo y default.
   Ada/Ampere utilizan el índice TGP de la cabecera en cada cadena duplicada
   validada. Son límites guardados en la ROM; la aceptación por firmware y el
   mínimo aplicado en runtime siguen siendo desconocidos.
3. La vista previa es en vivo. Al escribir, la fila se marca y muestra original →
   nuevo valor, y la barra inferior lista los cambios al instante. Tras una pausa
   de 350 ms la copia se genera en memoria y se verifica en segundo plano; los
   campos siguen editables y los resultados de entradas anteriores se descartan.
   Un texto que no es número se marca en su fila y no se envía al backend; un valor
   fuera de rango marca su fila con el rango aceptado. `Ctrl+Enter` verifica al
   momento. Los coeficientes de temperatura y los valores de fábrica que no se
   pidieron cambiar se conservan. Guardar queda deshabilitado mientras las
   entradas difieran de la última copia verificada.
4. **Restablecer cambios** descarta la propuesta y vuelve a la imagen original
   inmutable.
5. **Guardar copia…** solicita un destino nuevo. Publica la ROM y
   `salida.rom.json`; rechaza archivos existentes, enlaces simbólicos, la entrada
   y una fuente que haya cambiado. Si falla el guardado, conserva la propuesta
   para reintentar.

Los offsets de memoria Blackwell reconocidos se editan en **MHz** en la escala
NVML/Linux, que es el doble del valor guardado en la tabla. Cada fila de memoria
muestra también el valor que ven las herramientas de Windows como MSI Afterburner
(la mitad); el offset del núcleo es igual en ambas. Con los campos avanzados, **El
clock de memoria de N MHz sigue el offset de memoria** (Blackwell, Ada y Ampere;
experimental, sin probar en hardware) debería hacer que un offset de memoria negativo
también mueva un nivel de memoria intermedio, en vez de que la memoria caiga a un clock
de reposo bajo él (el significado del bit que activa es inferido); baja también el piso del offset de memoria. La representación de tabla
queda en `nvbios fields`. Las corrientes guardadas en mA (entrada de 12 V y OCP de
salida) se muestran y escriben en A, con hasta tres decimales; la GUI las convierte
de forma exacta y el backend, la CLI y el manifiesto siguen en mA. La frecuencia
PWM de los ventiladores se muestra y escribe en kHz de la misma forma; la tarjeta
Ventiladores también permite cambiar la cantidad de canales de ventilador y, por
canal, la velocidad mínima y máxima en RPM, luego los tres puntos de la curva de
ventilador guardada del canal (temperatura en °C, velocidad en RPM) y al final las
curvas adicionales, que valen para todos los canales (todo experimental). Las
temperaturas avanzan de a 1/32 °C (`60.5` sirve, `60.01` no) y muestran decimales solo
cuando hacen falta. Un límite solo llega hasta las curvas guardadas: para bajar un
máximo por debajo de ellas, escribe el nuevo máximo y los puntos de curva que
quedan por encima, también los de las curvas adicionales, y se comprueban y guardan
juntos en una sola copia. Para subir un mínimo, sube también todos los puntos que
queden por debajo. Si una curva bloquea un límite, la fila nombra los puntos que
faltan por cambiar, incluidas las curvas adicionales, usando los valores escritos.
Por ejemplo, dos ventiladores y dos curvas adicionales que empiezan en 1000 RPM
requieren seis cambios para subir ambos mínimos a 1200 RPM: los dos mínimos y el
primer punto de las cuatro curvas. Ningún valor se ajusta automáticamente.
El nivel mínimo y máximo (%) de cada canal y los niveles
de las curvas aparecen con los campos avanzados. Guarda primero una nueva cantidad
de canales y cambia los límites, las curvas o la parada en reposo en la copia. Ada y
Ampere no heredan esa conversión. Los techos de
salida OCP revisados se expresan en mA, pero editarlos no demuestra que el firmware
los aplique. Un techo de ecuación REL/ALT/OV tampoco es un voltaje evaluado ni
un offset runtime. **Voltaje mínimo (VMIN)** (experimental) es el valor guardado de la
ecuación que el driver evalúa como VMIN; en Ada el driver le suma sus términos
encadenados (+90 mV en una RTX 2000 Ada), así que el valor llega hasta el REL más
bajo menos lo máximo que esos términos pueden sumar (753 mV en esa placa). El
techo de solo lectura del "slot VMIN de la info del riel" es otra ecuación y no
fija el VMIN. En las imágenes Ada cuyo REL o ALT es una constante (la imagen más
nueva de la RTX 4090, 4080, RTX 4000 Ada; ALT en la 4080 SUPER, 4070 Ti SUPER y 4060),
**Voltaje fijo REL/ALT de NVVDD** (experimental) fija ese valor, desde su mínimo de
clamp hasta el valor de OV (1200 mV), con REL como máximo igual a ALT: cambia ambos
juntos para subir REL por encima de ALT. Bajar REL por debajo de un VMIN subido
también requiere VMIN en la misma edición. Las imágenes Turing tienen la misma fila
entre los campos avanzados (REL 1068,75 mV y ALT 1093,75 mV en la mayoría de las
tarjetas, OV 1125 mV); ahí REL y ALT además se mantienen como mínimo en el voltaje de
arranque y en VMIN más sus términos encadenados, y VMIN puede subir por encima del REL
anterior si REL sube en la misma edición (VMIN más sus términos encadenados queda como
máximo en REL). La GUI guarda
el archivo completo y no normaliza los bancos
implícitamente. Los formatos desconocidos o no editables permiten sólo inspección.
Las firmas criptográficas no se verifican ni regeneran.

Atajos: `Ctrl+O` abre, `Ctrl+Enter` verifica al momento, `Ctrl+S` guarda una
copia, `Ctrl+R` restablece y `Ctrl+Q` cierra. La ventana (760×920 por defecto) es
de una sola columna: tarjeta del dispositivo, luego Potencia, Voltaje, Offsets de
reloj, Corriente y protección, y Ventiladores, y al final los campos de solo lectura en una
sección plegada. Si una parte de la imagen usa una disposición que el editor aún no
admite (por ejemplo, las tablas de ventiladores de algunas imágenes), la tarjeta
correspondiente avisa que algunos de sus campos no se muestran; el título aparece aunque
no quede ningún campo. La barra de cambios queda siempre visible. Tab recorre los controles. Los errores muestran códigos
estables del backend; los hashes y mensajes se pueden seleccionar y copiar.

Consulta la [API del editor](editor-api.md) y los [campos ampliados](extended-fields.md)
para los formatos admitidos y sus límites de evidencia. Las pruebas y la
validación GTK sin escritorio se describen en la [guía técnica en inglés](gui.md).

## SSH / X11 con MobaXterm

Si el selector del escritorio no aparece en la pantalla reenviada, usa el
selector integrado en la propia aplicación:

```sh
nvbios gui --lang es --file-dialog builtin
nvbios gui --lang es --file-dialog builtin /ruta/original.rom
```

La opción predeterminada `--file-dialog auto` elige el integrado si detecta las
variables de una conexión SSH. En una sesión local mantiene el selector del
sistema. `--file-dialog system` permite elegir explícitamente este último.
El integrado evita pedir al portal del escritorio que abra el selector.

El menú **Opciones de archivo** ofrece también:

- **Abrir/Guardar con selector integrado…**, para navegar por las carpetas.
- **Abrir por ruta…** (`Ctrl+Shift+O`) y **Guardar copia por ruta…**
  (`Ctrl+Shift+S`), para escribir o pegar la ruta sin depender de un explorador.

Las rutas son las del **equipo Linux**, aunque veas las ventanas en Windows.
El diálogo de ruta acepta rutas absolutas, relativas y `~/`. También puedes
abrir una ROM pasándola al iniciar la GUI, como en el segundo ejemplo.

Guardar sigue exigiendo una vista previa verificada y un destino nuevo. Se crea
la ROM junto con su manifiesto JSON, se rechaza sobrescribir el original o un
archivo existente y no se aplican ajustes a las GPU.

Si hay problemas de renderizado en la ventana X11, puedes usar renderizado por
software para esa ejecución:

```sh
GDK_BACKEND=x11 GSK_RENDERER=cairo nvbios gui --lang es --file-dialog builtin
```

Se prueban ambos selectores en un display GTK Broadway aislado, incluidas la
cancelación y las protecciones al guardar. Esa prueba automática no equivale a
probar un servidor X concreto de Windows.
