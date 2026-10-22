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
   slot y de los cables siguen aplicando. **Temperatura máxima de funcionamiento**
   (Blackwell, en la tarjeta Potencia; experimental, sin probar en hardware) es el
   límite de temperatura que el driver informa como temperatura máxima de
   funcionamiento de la GPU (en `nvidia-smi`, la temperatura actual más T.Limit): baja
   hasta 40 °C y sube hasta 3 °C sobre el valor de fábrica del producto (90 °C en una
   RTX 5090, 88 °C en una RTX 5080), en pasos de 1/32 °C, y es de solo lectura en las
   ROM estilo XOC, donde ese límite está desactivado. Un valor más bajo debería hacer que
   el driver baje los clocks antes, y uno más alto deja menos margen térmico. La ROM de la
   RTX 5080 Laptop GPU guarda además un segundo límite del mismo tipo (87 °C) cuyo papel no
   se rastreó, así que ahí subir el valor puede no tener efecto. **Mostrar campos avanzados (estilo XOC)**
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
(la mitad); el offset del núcleo es igual en ambas. El **Offset GPC de fábrica
(overclock del fabricante)** (Blackwell; experimental, sin probar en hardware; se muestra
sin los campos avanzados) es el overclock de fábrica que el fabricante de la placa guarda
en la ROM (de +30 a +195 MHz en las ROM con OC de fábrica revisadas); acepta de -500 a +500
MHz en MHz enteros, solo en las ROM que lo guardan, y es de solo lectura en las demás (ROM
Founders Edition, de referencia, de portátil y RTX PRO). Un valor negativo baja el clock,
valores lejos del de fábrica pueden volver inestable la tarjeta, y no se comprobó si el
offset GPC de una herramienta se suma a este o lo reemplaza. El **Clock boost nominal de
fábrica**, en la lista de solo lectura, queda como está guardado. Con los campos avanzados,
el **Offset de la curva GPC** (Blackwell, Ada y Ampere; experimental, sin probar en
hardware; de -500 a +500 MHz) debería desplazar la curva VF de fábrica del núcleo esa
cantidad de MHz en todos los voltajes, en cada arranque y debajo del offset de
cualquier herramienta; 0 devuelve los bytes de fábrica. No es el offset GPC de fábrica:
en una ROM con OC de fábrica se aplican los dos. **El
clock de memoria de N MHz sigue el offset de memoria** (Blackwell, Ada y Ampere;
experimental) buscaba que un offset de memoria negativo también moviera un nivel de
memoria intermedio, en vez de que la memoria cayera a un clock de reposo bajo él; en la
única tarjeta probada (una RTX 3050 Laptop GPU) no lo logró. La representación de tabla
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
copia, `Ctrl+R` restablece, `Ctrl+I` importa desde otra ROM y `Ctrl+Q` cierra. La
ventana (760×920 por defecto) es
de una sola columna: tarjeta del dispositivo, luego Potencia, Voltaje, Offsets de
reloj, Corriente y protección, y Ventiladores, en Blackwell la sección plegada **Avanzado**, y
al final los campos de solo lectura en una sección plegada. Si una parte de la imagen usa una disposición que el editor aún no
admite (por ejemplo, las tablas de ventiladores de algunas imágenes), la tarjeta
correspondiente avisa que algunos de sus campos no se muestran; el título aparece aunque
no quede ningún campo. La barra de cambios queda siempre visible. Tab recorre los controles. Los errores muestran códigos
estables del backend; los hashes y mensajes se pueden seleccionar y copiar.

**Avanzado: controladores de rendimiento y ahorro en reposo** (Blackwell; plegada, después
de Ventiladores y antes de los campos de solo lectura; todos los campos son experimentales y
sin probar en hardware) tiene dos grupos, cada uno en su tarjeta. En **Controladores de
clocks**, el interruptor **Política de clocks por utilización** y, para los clocks GPC, DRAM
y VID, el **objetivo de utilización** y el **umbral de salto** (porcentaje entero; de 10 %
hasta 1 % bajo el umbral de salto, y del objetivo + 1 % hasta 100 %; para subir el objetivo
hasta o por encima del umbral guardado, sube también el umbral en la misma edición) y la
**histéresis de bajada** y **de subida** (en muestras, la de bajada de 0,5x a 4x la de
fábrica y la de subida de 1 a 4). Ajustan cómo el driver sube y baja los clocks según la
carga: un objetivo más bajo sube el clock antes con carga parcial, con más consumo y calor.
No está probado que el driver use esta tabla en Blackwell. En **Ahorro en reposo**, los
interruptores **Power gating de GR**, **Clock gating del sistema de memoria, MSCG**, **Power
gating de NVDEC/NVENC/OFA/NVJPG**, **Ahorro de energía con imagen fija, DIFR** y, en la RTX
PRO 4000 SFF y la RTX 5080 Laptop GPU, **Rail gating de GR**, cada uno en **De fábrica**
(como viene) o **Desactivado**, y los **tiempos de reposo de DIFR** y **del rail gating de
GR** (ms o µs, el rail gating de GR en pasos de 10 µs, de 0,5x a 4x los de fábrica). Se
espera que solo actúen en reposo o con carga ligera (es una inferencia). Desactivado gasta un
poco más en reposo y puede evitar tirones o parpadeos en reposo; tiempos de reposo muy cortos
pueden causar tirones o, rara vez, pantalla negra en reposo. Un valor que depende de un
interruptor (los valores de los controladores de la política de utilización, un tiempo de
reposo de su función) queda en gris, con el motivo, mientras ese interruptor está apagado,
también si lo apagas antes de guardar; un valor escrito ahí vuelve al guardado, y al volver a
activar el interruptor se puede editar de nuevo. Esta sección no depende de **Mostrar campos
avanzados (estilo XOC)**, e **Importar desde ROM…** nunca la copia.

**Memoria (solo lectura)**, una sección plegada después de los campos de solo lectura,
muestra las tablas de memoria de las imágenes Turing, Ampere, Ada y Blackwell (`nvbios
memory` entrega el mismo informe en JSON, ver la [API del editor](editor-api.md)). Se lee
en segundo plano la primera vez que se abre. Lista las configuraciones de memoria (strap →
columna, fabricante, código de tipo; solo el tipo 9 tiene nombre, GDDR6) y, por columna,
la entrada de timings de cada banda que contiene un clock de memoria de fábrica (todas
las bandas sobre 0 MHz cuando el editor no lee los clocks de fábrica de la ROM, como en Turing) con
sus valores decodificados en ciclos del controlador: tRC, tRAS y tRP van marcados como "inferidos"
(sus nombres salen de patrones de bytes, no de documentación de NVIDIA), tRFC como
"probable", CL y tWR como "tentativos". Las columnas con las mismas entradas comparten
un título; una columna que la tabla de clocks de memoria no tiene se lista con una nota.
La configuración que usa una tarjeta la fija la placa, no la ROM. En
Blackwell también muestra el perfil de entrenamiento de memoria de la placa del objeto
0x89 como una etiqueta y una huella: datos de arranque por placa sin decodificar,
probablemente entrenamiento de la interfaz de memoria. Una diferencia ahí no significa
que una BIOS sea más rápida, y solo tiene efecto al flashear la ROM completa; el
override no puede aplicarlo. **Bytes en bruto** lista todas las bandas con sus bytes,
las entradas de timings que seleccionan las bandas, el hash de cada tabla y los bytes del
perfil. **Comparar con otra ROM…** lee una segunda ROM en segundo plano e indica, por
sección, si hay diferencias (el número de entradas o campos del perfil distintos, cuyo
significado se desconoce), nunca cuál es mejor. Las líneas de configuraciones, bandas y
timings comparan las entradas en uso; la línea de tablas compara cada byte de cada tabla
y nombra las tablas con diferencias. Nada en esta sección edita, prepara ni guarda
cambios, y la comparación no toca la ROM abierta, la lista de cambios ni el guardado.

**Importar desde ROM…** (en la barra de cambios) copia valores de otra ROM de la misma familia
a la ROM abierta, por ejemplo los ajustes de ventiladores de otra placa: elige la ROM, marca las
secciones (Potencia, Voltaje, Offsets de reloj, Corriente y protección, Ventiladores; nunca la
sección Avanzado de Blackwell) y, si quieres, los campos avanzados estilo XOC (desmarcados por
defecto). La otra ROM se lee en
segundo plano. Cada valor distinto que esta ROM puede tomar se escribe en su fila como si lo
hubieras escrito tú: aparece en la lista de cambios, se verifica como cualquier otro valor, y
escribir de nuevo el valor original o **Restablecer cambios** lo deshace. Un valor que habías
escrito en una sección elegida donde ambas ROM coinciden vuelve al valor que ambas tienen. No se escribe nada
hasta **Guardar copia…**, y los valores pendientes de otras secciones se mantienen.

Los campos relacionados vienen completos de la otra ROM o no vienen: un mínimo, un valor nominal
y un máximo; una curva de ventilador (los límites de los ventiladores y la temperatura, la
velocidad y el nivel de cada punto); el límite de entrada de 12 V y su copia en la política 7.
Si uno de ellos difiere pero queda fuera, por ejemplo un nivel de curva que es un campo avanzado
que no incluiste, los demás también se retienen. Un valor que el editor rechaza queda fuera
junto con los valores de los que depende (esos campos relacionados, o todos los voltajes). Luego
el diálogo indica cuántos valores se importaron y lista los campos que quedaron fuera con su
motivo: no está en una de las ROM, es de solo lectura, en la otra ROM es otra magnitud (otras
unidades, otro nivel de memoria, otro esquema de potencia de notebook o de placa, u otra
ecuación de voltaje, como REL y ALT que siguen a OV), está fuera del rango de esta ROM, es un
campo avanzado no incluido, se retiene junto con campos relacionados, o el editor lo rechazó.
Los campos de solo lectura en ambas ROM solo se listan cuando retienen campos relacionados. La
cantidad de canales de ventilador describe los ventiladores de la placa y nunca se copia, y
tampoco se copia la **Temperatura máxima de funcionamiento** de Blackwell (cada producto tiene la
suya); un valor que escribiste en ella se mantiene. El **Offset GPC de fábrica** de Blackwell
viene con los Offsets de reloj cuando ambas ROM guardan uno. Si la otra ROM no guarda ninguno
(por ejemplo, una ROM Founders Edition), esta ROM conserva el suyo, y una ROM que no guarda
ninguno nunca recibe uno. Una
ROM de otra familia de GPU o de otro formato (por ejemplo un `.bin` del loader) se rechaza; otro producto de la misma familia (otro ID de dispositivo
PCI) se permite con un aviso. `nvbios import` hace lo mismo desde la línea de comandos (ver la
[API del editor](editor-api.md)).

**Los valores se copian como números almacenados, sin adaptarlos a esta placa.** Los límites de
velocidad de los ventiladores, los de potencia o corriente y los de voltaje de otra placa pueden
superar lo que soporta el hardware de esta placa, por ejemplo ventiladores para una velocidad
menor o un solo conector 12V-2x6 donde la otra placa tiene más conectores de alimentación o etapas
de potencia más robustas. Un offset GPC de fábrica de otra placa puede no ser estable en esta.
Revisa cada valor importado en la lista de cambios antes de guardar.

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
