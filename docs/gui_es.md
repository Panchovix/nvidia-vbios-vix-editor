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
   combinado. En un portátil, Dynamic Boost pide el límite de potencia en uso mientras
   funciona y el techo solo lo acota; las herramientas de monitoreo muestran el techo
   guardado, así que subir solo el techo por lo general no sube el límite en uso (en una
   RTX 5090 Laptop GPU, con el techo subido de 175 a 225 W y también la potencia por
   defecto al arrancar, siguió en 175 W). La ventana lo indica en las ROM de las RTX 5080
   y 5090 Laptop GPU.
   Los valores de corriente de entrada de 12 V son valores guardados de
   la política, no corrientes seguras garantizadas; los límites del conector, del
   slot y de los cables siguen aplicando. **Temperatura máxima de funcionamiento**
   (Blackwell, Ada, Ampere y Turing, en la tarjeta Potencia; experimental, sin probar en
   hardware) es el límite de temperatura que el driver informa como temperatura máxima de
   funcionamiento de la GPU (en `nvidia-smi`, la temperatura actual más T.Limit, según lo
   comprobado en tarjetas de escritorio): baja hasta 40 °C y sube hasta 3 °C sobre el
   valor de fábrica del producto (90 °C en una RTX 5090 o RTX 4090, 93 °C en una RTX
   3090, 89 °C en una RTX 2080 Ti), en pasos de
   1/32 °C, y es de solo lectura en las ROM estilo XOC, donde ese límite está desactivado
   o no existe. Un valor más bajo debería hacer que el driver baje los clocks antes, y uno
   más alto deja menos margen térmico. Las ROM de la RTX 5080 y 5090 Laptop GPU guardan además
   un segundo límite del mismo tipo (87 °C) cuyo papel no se rastreó, así que ahí subir el
   valor puede no tener efecto. En las ROM de portátil Ampere y Ada es de solo lectura:
   guardan un límite más bajo del mismo tipo (89 °C) y no se sabe cuál alcanza primero la
   GPU. **Mostrar campos avanzados (estilo XOC)**
   (desmarcada por defecto) muestra campos opcionales como la potencia nominal de
   las políticas fijas 2/7, el **TGP base del portátil** experimental de las RTX 5080 y
   5090 Laptop GPU (un valor guardado que podría ser la base a la que Dynamic Boost le suma
   su boost; sin probar), en Ada y Blackwell el límite de potencia del conector de
   alimentación auxiliar (**Canal de potencia de conector 1**, experimental: en una placa con un
   solo conector de 8 pines lo más probable es que frene ese conector en unos 150 W aunque el
   límite de potencia de la placa sea más alto; un conector PCIe de 8 pines admite 150 W, y pasar
   de lo que admiten el conector y su cable pone en riesgo el cable, el conector y la fuente, lo
   que es decisión tuya; los límites de potencia de la placa, del slot y de corriente de entrada
   de 12 V siguen vigentes; la fila lo indica), los umbrales de hardware (corriente del slot; en
   Ampere y Turing la corriente de los conectores; en Ada la potencia de salida
   NVVDD y la corriente de entrada de 12 V, rotulada "umbral"), el límite de
   corriente de salida NVVDD de Turing y Ampere (en Ampere puede ser lo que limita
   un portátil por debajo de un techo de potencia subido; sin probar, y el VRM se
   dimensionó para el valor de fábrica), los voltajes fijos REL/ALT de Turing y, en
   Blackwell y Ada, **REL y ALT de NVVDD siguen a OV** (un interruptor: activado
   da el límite de voltaje plano estilo XOC; guárdalo solo y conserva la imagen
   original para volver atrás) y, en Blackwell, Ada y Ampere, **Parada de
   ventiladores en reposo** (un interruptor para los bits que permiten que los
   ventiladores se detengan en reposo, probado en hardware en una RTX 5090, no en Ada,
   Ampere ni en la RTX PRO 6000 Max-Q; experimental). En las tarjetas blower que no
   guardan valores de parada (RTX PRO 6000 Max-Q, RTX 5000 y 6000 Ada, serie RTX A) el
   interruptor escribe además los valores que NVIDIA guarda en otra de sus tarjetas, y
   desactivarlo en esa copia escribe de vuelta los bytes de fábrica; unas notas bajo el
   interruptor nombran esa tarjeta y los riesgos: ninguna tarjeta blower sale de
   fábrica con la parada activada, lo más probable es que un blower parado no mueva
   aire por la tarjeta, incluidas la memoria y las etapas de potencia, hasta que la
   tarjeta pase el umbral superior, rearrancar un blower desde 0 RPM no está probado,
   y en equipos con varias GPU juntas puede acumularse calor y el ventilador puede
   pararse y arrancar en ciclos. En cualquier otra ROM que viene de fábrica con la
   parada desactivada (todas las RTX PRO y las de la serie RTX A, algunas GeForce
   Ampere) una nota da los mismos riesgos para una tarjeta con ventilador blower.
   Donde el interruptor dejaría las entradas de los canales de ventilador con el bit 4
   de su byte de flags apagado (la RTX PRO 6000 Workstation y Max-Q y las tarjetas
   blower de arriba), una nota dice que ninguna ROM de fábrica usa la parada con
   esa forma de flags y que no está probado si los ventiladores se detienen. Donde una
   entrada guarda el mismo umbral inferior y superior (la RTX 3060 8GB, 40 °C), una
   nota dice que no hay histéresis, así que los ventiladores pueden pararse y arrancar
   a menudo cerca de esa temperatura, y que bajes ese umbral inferior unos grados. Una
   herramienta de ventiladores que mantiene el control manual deja los ventiladores
   girando diga lo que diga el interruptor. Una ROM cuyas entradas de ventilador no
   coinciden (una RTX 3060) muestra el campo de solo lectura como Mixto. En una copia
   donde el interruptor escribió valores de parada, desactivarlo y cambiar sus
   umbrales se guardan por separado. Los **umbrales inferior y superior de la parada
   en reposo** de cada ventilador y curva adicional (Blackwell, Ada y Ampere) son las
   dos temperaturas guardadas junto a esos bits: lo más probable es que los
   ventiladores se detengan bajo el inferior y arranquen sobre el superior, y en una
   RTX 5080 subir el superior los mantuvo detenidos por debajo. El umbral superior
   llega como mucho al punto 1 de la misma curva de ventilador. Con la parada
   activada, un punto 1 por debajo del umbral superior, o activar la parada con un
   umbral superior por encima del punto 1, se rechaza y la fila que hay que cambiar
   indica su rango permitido; cámbialos juntos (en una RTX 3090, activar la parada
   requiere bajar ambos umbrales superiores a 51,90625 °C, su punto 1, o menos). Donde
   el umbral inferior está en el punto 1 o por encima (las curvas adicionales de una
   RTX 3080, la RTX 3050, algunas ROM de RTX 4090) su fila también se marca: bájalo por
   debajo del umbral superior en la misma edición. Una cantidad mayor de **Canales de
   ventilador** que activa un ventilador guardado cuyo umbral superior está por encima
   de su punto 1 con la parada activada se rechaza: desactiva la parada y guarda,
   cambia la cantidad en esa copia y luego activa la parada con ese umbral más bajo
   (en la RTX 3060 cuyas entradas no coinciden la cantidad no se puede subir). En Ada y
   Ampere los umbrales se pueden editar donde se puede el interruptor, y ahí no están
   probados en hardware; experimental.
   Los valores ya escritos se conservan al marcar **Mostrar campos avanzados (estilo
   XOC)**. Los campos 0/1 de solo lectura muestran Activado o Desactivado. **Multiplicador
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
   mínimo aplicado en runtime siguen siendo desconocidos. Algunas ROM Ada (una
   imagen MSI RTX 4090) eligen sus límites de potencia según los pines de
   detección del cable de 16 pines. Ahí el techo de potencia de la placa y la
   potencia por defecto al arrancar también escriben el perfil del nivel más alto,
   y los niveles más bajos mantienen sus propios límites y fijan los valores
   mínimos aceptados (experimental, sin probar en hardware). Las notas bajo las
   filas dicen que el nivel más alto probablemente es un cable de 600 W
   (deducido), que pasar de 600 W es decisión tuya y que el umbral de corriente de
   entrada de 12 V (unos 576 W a 12 V en esa ROM, un campo avanzado) puede limitar
   antes, así que conviene subirlo también.
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
(overclock del fabricante)** y el **Offset de memoria de fábrica (overclock del
fabricante)** (Blackwell, Ada, Ampere y Turing; experimentales, sin probar en hardware; se
muestran sin los campos avanzados) son el overclock de fábrica que el fabricante de la placa
guarda en la ROM (de +15 a +195 MHz en el núcleo en las ROM con OC de fábrica revisadas; un
offset de memoria solo en dos ROM de RTX 20). El offset GPC acepta de -500 a +500 MHz y el de
memoria de -5000 a +5000 MHz, en MHz enteros. El offset de memoria está en el clock de memoria
que muestran `nvidia-smi` y MSI Afterburner (7000 MHz en GDDR6 de 14 Gbps); nvidia-settings, que
muestra la tasa de transferencia, y las filas de techo y piso del offset de memoria usan el doble
de ese número, que la fila también muestra (de -5000 a +5000 MHz aquí son de -10000 a +10000 MHz
allí). En una ROM que no guarda overclock de fábrica (ROM Founders Edition, de referencia, de
estación de trabajo y de portátil) el campo muestra 0, y un valor distinto de 0 lo activa, algo
que no se probó en esas ROM (la fila lo indica); 0 apaga el offset como lo guardan esas ROM, así
que devuelve sus bytes originales, incluso desde una copia guardada.
Un valor negativo baja el clock, valores lejos del de fábrica pueden volver inestable
la tarjeta o impedir que arranque, y no se comprobó si el offset de una herramienta se suma al
de fábrica o lo reemplaza. El **Clock boost nominal de fábrica**, en la lista de solo lectura,
queda como está guardado. Con los campos avanzados,
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
de canales y cambia los límites, las curvas o la parada en reposo en la copia. Una
cantidad menor deja en gris las filas de los ventiladores que apaga (la copia los guarda,
pero apagados) y la lista de cambios muestra sus valores como "no se usa"; un valor escrito
en esas filas vuelve cuando la cantidad enciende otra vez su ventilador. Una cantidad
mayor muestra los valores guardados de los ventiladores que enciende. Ada y
Ampere no heredan esa conversión. Los techos de
salida OCP revisados se expresan en mA, pero editarlos no demuestra que el firmware
los aplique. Un techo de ecuación REL/ALT/OV tampoco es un voltaje evaluado ni
un offset runtime. **Voltaje mínimo (VMIN)** (experimental) es el valor guardado de la
ecuación que el driver evalúa como VMIN; en Ada el driver le suma sus términos
encadenados (+90 mV en una RTX 2000 Ada), así que el valor llega hasta el REL más
bajo menos lo máximo que esos términos pueden sumar (753 mV en esa placa). El
techo de solo lectura del "slot VMIN de la info del riel" es otra ecuación y no
fija el VMIN. Donde cada chip fija su propio VMIN (un árbol de ecuaciones sobre valores
de fusibles y la temperatura: RTX PRO 6000 y PRO 4000, RTX 5060 Ti, RTX 5080 Laptop GPU,
MSVDD de la RTX 5090 y varias tarjetas Ampere y Ada) la fila empieza vacía y dice
"Original: por chip"; un valor fija el VMIN en ese valor para todo chip y temperatura (en
Ada los términos encadenados después siguen sumando lo suyo). Es experimental y no está
probado en hardware: un valor por debajo del VMIN de fábrica del chip puede volver
inestables el reposo y las cargas ligeras, y el driver podría mantener su VMIN de
fábrica. En una copia guardada así aparece el interruptor **VMIN fijo**, y desactivarlo
escribe de vuelta los bytes de fábrica; guarda ese cambio y un valor nuevo en copias
separadas. En las ROM 95.02.3C de la RTX 4090 una constante de 15 mV que fija el
piso de voltaje del reloj de memoria enlaza la ecuación de VMIN; ahí un VMIN nuevo
primero copia esa ecuación a un slot VFE libre, así el piso de la memoria mantiene su
valor de fábrica y un VMIN más bajo solo se nota con la memoria en reposo a 405 MHz;
uno más alto se nota con cualquier reloj de memoria solo por encima de 826 mV
(deducido, sin medir). Sus notas lo dicen, y también que ninguna tarjeta Ada ha usado
una ecuación agregada por el editor: el override podría no cargar o el driver podría
no iniciar, y quitar el override devuelve la tarjeta a como estaba. El valor de
fábrica restaura los bytes originales. Ahí el VMIN y el offset de la curva GPC se
guardan en copias separadas, porque ambos usan ese slot. En las imágenes Ada cuyo
REL o ALT es una constante (la imagen más nueva de la RTX 4090, 4080, RTX 4000 Ada;
ALT en la 4080 SUPER, 4070 Ti SUPER y 4060),
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
reloj, Corriente y protección, y Ventiladores, la sección plegada **Avanzado**, y
al final los campos de solo lectura en una sección plegada. Si una parte de la imagen usa una disposición que el editor aún no
admite (por ejemplo, las tablas de ventiladores de algunas imágenes), la tarjeta
correspondiente avisa que algunos de sus campos no se muestran; el título aparece aunque
no quede ningún campo. La barra de cambios queda siempre visible. Tab recorre los controles. Los errores muestran códigos
estables del backend; los hashes y mensajes se pueden seleccionar y copiar.

**Avanzado: controladores de rendimiento y ahorro en reposo** (Blackwell, Ada, Ampere y
Turing; plegada, después de Ventiladores y antes de los campos de solo lectura; todos los
campos son experimentales y sin probar en hardware) tiene dos grupos, cada uno en su tarjeta. En **Controladores de
clocks**, el interruptor **Política de clocks por utilización** y, para los clocks GPC, DRAM
y VID, el **objetivo de utilización** y el **umbral de salto** (porcentaje entero; de 10 %
hasta 1 % bajo el umbral de salto, y del objetivo + 1 % hasta 100 %; para subir el objetivo
hasta o por encima del umbral guardado, sube también el umbral en la misma edición) y la
**histéresis de bajada** y **de subida** (en muestras, la de bajada de 0,5x a 4x la de
fábrica y la de subida de 1 a 4). Ajustan cómo el driver sube y baja los clocks según la
carga: un objetivo más bajo sube el clock antes con carga parcial, con más consumo y calor.
No está probado que el driver use esta tabla en ninguna de estas tarjetas. En **Ahorro en
reposo**, los interruptores que tiene la ROM, cada uno en **De fábrica** (como viene) o
**Desactivado**: **Power gating de GR** y **Clock gating del sistema de memoria, MSCG** en
todas las familias, **Power gating de NVDEC/NVENC/OFA/NVJPG** en Blackwell, **Ahorro de
energía con imagen fija, DIFR** en Blackwell y en las Ada que lo traen activado, y **Rail
gating de GR** donde viene activado (entre las ROM revisadas, la RTX PRO 4000 SFF, las RTX
5080 y 5090 Laptop GPU y las GA102 RTX 3080/3090, RTX A4500..A6000 y A40); y los **tiempos de
reposo de DIFR** y **del rail gating de GR** (ms o µs, el rail gating de GR en pasos de 10 µs,
de 0,5x a 4x los de fábrica). Cuando las entradas de un interruptor se ven iguales vengan
apagadas de fábrica o apagadas después (rail gating de GR, DIFR en Ada, power gating de GR y
MSCG en Turing) y el editor no revisó el producto, el interruptor cubre las entradas que la
ROM activa, y su fila lo indica: una copia guardada con **Desactivado** ya no muestra ese
interruptor, así que guarda la ROM original para volver a **De fábrica**. Una entrada que el
editor no reconoce deja el interruptor de solo lectura, con el motivo. Se espera que
solo actúen en reposo o con carga ligera (es una inferencia). Desactivado gasta un
poco más en reposo y puede evitar tirones o parpadeos en reposo; tiempos de reposo muy cortos
pueden causar tirones o, rara vez, pantalla negra en reposo. Un valor que depende de un
interruptor (los valores de los controladores de la política de utilización, un tiempo de
reposo de su función) queda en gris, con el motivo, mientras ese interruptor está apagado,
también si lo apagas antes de guardar; un valor escrito ahí muestra el guardado mientras
tanto, y al volver a activar el interruptor se puede editar de nuevo con el valor escrito.
Esta sección no depende de **Mostrar campos avanzados (estilo XOC)**, e **Importar desde
ROM…** nunca la copia.

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
sección Avanzado) y, si quieres, los campos avanzados estilo XOC (desmarcados por
defecto). La otra ROM se lee en
segundo plano. Cada valor distinto que esta ROM puede tomar se escribe en su fila como si lo
hubieras escrito tú: aparece en la lista de cambios, se verifica como cualquier otro valor, y
escribir de nuevo el valor original o **Restablecer cambios** lo deshace. Un valor que habías
escrito en una sección elegida donde ambas ROM coinciden vuelve al valor que ambas tienen. No se escribe nada
hasta **Guardar copia…**, y los valores pendientes de otras secciones se mantienen.

Los campos relacionados vienen completos de la otra ROM o no vienen: un mínimo, un valor nominal
y un máximo; una curva de ventilador (los límites de los ventiladores y la temperatura, la
velocidad y el nivel de cada punto); el límite de entrada de 12 V y su copia en la política 7.
Si uno de ellos difiere pero queda fuera, por ejemplo la potencia nominal de las políticas fijas
de la placa, un campo avanzado que no incluiste, los demás también se retienen. Los niveles de
una curva de ventilador también son campos avanzados, pero vienen con su curva aunque no marques
los campos avanzados: cada ROM empareja sus velocidades de ventilador con niveles ajustados para
sus propios ventiladores, así que las velocidades sin sus niveles harían girar los ventiladores a
velocidades distintas de las que indica la curva. Aparecen en la lista de cambios y quedan detrás
de **Mostrar campos avanzados (estilo XOC)**, que la importación activa solo cuando marcas los
campos avanzados y viene alguno de ellos. Un valor que el editor rechaza queda fuera junto con los
valores de los que depende (esos campos relacionados, o todos los voltajes). Con la parada en
reposo activada, una curva que empieza por debajo del umbral superior de parada en reposo de esta
ROM se rechaza salvo que vengan con ella los umbrales de la otra ROM, o su parada en reposo
desactivada, así que sin los campos avanzados el resumen te pide importar de nuevo con ellos. Luego
el diálogo indica cuántos valores se importaron y lista los campos que quedaron fuera con su
motivo: no está en una de las ROM, es de solo lectura, en la otra ROM es otra magnitud (otras
unidades, otro nivel de memoria, otro esquema de potencia de notebook o de placa, u otra
ecuación de voltaje, como REL y ALT que siguen a OV), está fuera del rango de esta ROM, es un
campo avanzado no incluido, se retiene junto con campos relacionados, o el editor lo rechazó.
Los campos de solo lectura en ambas ROM solo se listan cuando retienen campos relacionados. La
cantidad de canales de ventilador describe los ventiladores de la placa y nunca se copia, y
tampoco se copia la **Temperatura máxima de funcionamiento** (cada producto tiene la suya); un
valor que escribiste en ella se mantiene. El **Offset GPC de fábrica** y el **Offset de memoria
de fábrica** vienen con los Offsets de reloj. Si la otra ROM no guarda ninguno (por ejemplo, una
ROM Founders Edition), esta ROM recibe 0 MHz, y una ROM que no guarda ninguno toma el valor de la
otra ROM. Una
ROM de otra familia de GPU o de otro formato (por ejemplo un `.bin` del loader) se rechaza; otro producto de la misma familia (otro ID de dispositivo
PCI) se permite con un aviso. `nvbios import` hace lo mismo desde la línea de comandos (ver la
[API del editor](editor-api.md)).

**Los valores se copian como números almacenados, sin adaptarlos a esta placa.** Los límites de
velocidad de los ventiladores, los de potencia o corriente y los de voltaje de otra placa pueden
superar lo que soporta el hardware de esta placa, por ejemplo ventiladores para una velocidad
menor o un solo conector 12V-2x6 donde la otra placa tiene más conectores de alimentación o etapas
de potencia más robustas. Un offset GPC o de memoria de fábrica de otra placa puede no ser estable
en esta.
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
