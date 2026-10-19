# Turing (experimental)

[English](turing.md) | Español

Las GPUs Turing (TU102, TU104, TU106, TU116 y TU117: GeForce RTX 20 y GTX 16, TITAN RTX, Quadro RTX y la serie T)
las reconocen el editor y ambos cargadores, **de forma experimental**. Una RTX 2080 Ti (BIOS ROG Matrix) ya corrió
imágenes editadas con el cargador de Windows (driver 617.70). Una potencia de la tarjeta de 500 W más 250 W por
conector se cargó y la tarjeta llegó a unos 458 W bajo carga: el limitador de potencia dejó de activarse y se
activaron los de voltaje (Reliability Voltage, Max Operating Voltage). Con solo la potencia de la tarjeta se
detenía cerca de 300 W, porque las filas de cada conector seguían en sus valores de fábrica. Nada más de lo que
sigue está probado en hardware. Si tienes una tarjeta Turing, la guía del final nos dice qué funciona.

## Qué hace el editor

Todos los campos Turing están marcados como experimentales. Los marcados como *avanzados* aparecen al marcar
**Mostrar campos avanzados (estilo XOC)**.

- **Potencia de la tarjeta**: `power_max_w` (techo), `power_default_w` (valor por defecto al arrancar) y
  `power_min_w` (mínimo).
- **Límites de potencia por entrada** (imágenes de escritorio y workstation): `slot_power_max_w` /
  `slot_power_rated_w` para el slot PCIe, y `connector_N_power_max_w` / `connector_N_power_rated_w` para cada
  canal de medición de un conector externo de 12 V (dos en la mayoría de las RTX 20, uno en las GTX 1660,
  1660 SUPER, 1660 Ti y 1650 SUPER, tres en la imagen Galax HOF XOC de la RTX 2080 Ti, que deja el tercero en
  143/167 W mientras los demás están en 2000 W).
- **Umbrales de corriente** (avanzados): `slot_current_threshold_*_ma` y `connector_N_current_threshold_*_ma`,
  los umbrales de sobrecorriente por hardware del slot y de cada canal de conector.
- **Límite de corriente de salida NVVDD** (avanzado): `nvvdd_output_ocp_max_ma` / `nvvdd_output_ocp_rated_ma`.
  Protege el VRM del núcleo de la GPU; su significado exacto en Turing no se conoce.
- **Voltaje mínimo**: `nvvdd_vmin_mv`, la ecuación que la tabla del riel indica como límite VMIN. No se sabe
  cómo se relaciona en Turing con el voltaje que informa el driver.
- **Voltajes fijos REL y ALT** (avanzados): `nvvdd_rel_fixed_mv` y `nvvdd_alt_fixed_mv`, los valores constantes
  de los límites de voltaje REL y ALT (1068,75 y 1093,75 mV en la mayoría de las tarjetas), los mismos campos que
  en Ada. Cada uno va desde su valor guardado hasta OV (1125 mV, solo lectura), con REL como máximo igual a ALT:
  sube primero ALT, o ambos a la vez. Ambos se mantienen además como mínimo en el voltaje de arranque y en VMIN
  más lo que suman sus ecuaciones encadenadas. La edición conserva el valor guardado en la ecuación, así que la
  copia puede volver exactamente al original. No se sabe si la tarjeta corre entonces a más voltaje: la curva VF
  y los demás límites siguen aplicando, y más voltaje significa más calor, más potencia y más desgaste. La imagen
  Galax HOF XOC apunta REL y ALT a la ecuación de OV (REL = ALT = OV = 1125 mV); ahí el editor muestra esos
  valores como solo lectura, también los campos fijos, y deja VMIN editable. En una imagen de fábrica, poner ALT
  y REL fijos en 1125 mV en una misma edición da los mismos valores evaluados (sin probar en hardware Turing).
- **Rangos de offset de reloj**: `gpc_offset_max_mhz` / `gpc_offset_min_mhz` (núcleo) y `memory_offset_max_mhz` /
  `memory_offset_min_mhz`, los rangos que puede usar una herramienta de overclock. Por sí solos no cambian los
  relojes.
- **Ventiladores**: `fan_pwm_frequency_hz`, los límites de velocidad (RPM) y de nivel (%, avanzados) de cada
  ventilador y los puntos de su curva.
- **Solo lectura**: el límite de voltaje OV (1125 mV), los campos de ecuación y de selector de REL/ALT/OV, el
  voltaje de arranque y la cantidad de canales de ventilador.
- No todas las imágenes tienen todos los campos: las Max-Q y las de portátil no tienen filas de slot ni de
  conector ni ventilador controlado por la GPU; las GTX 1630 y 1650 tampoco tienen filas de slot ni de
  conector; la imagen ASUS RTX 2080 Ti XOC desactiva los umbrales de corriente y el límite NVVDD, así que ahí
  no tienen campo; la Quadro RTX 8000 guarda sus rangos de reloj como 0..0 (solo lectura); una imagen de RTX
  2080 no tiene el relleno de la suma de comprobación en la imagen que contiene la tabla de relojes, así que
  sus rangos de reloj son de solo lectura; las tablas de ventilador de la GTX 1650 SUPER no concuerdan y no
  dan campo de ventilador.
- Las tablas se decodifican por su estructura, comprobada en las 24 imágenes Turing examinadas (escritorio,
  portátil, Max-Q, Quadro, TITAN y dos imágenes XOC, de TU102 a TU117). El cambio se escribe en los dos bancos
  de la imagen y se repara la suma de comprobación de cada imagen tocada. Los límites mantienen el orden guardado
  (mínimo <= nominal <= máximo, una curva de ventilador dentro de sus límites); no son límites seguros para el
  hardware.
- Las imágenes Turing llevan una **lista firmada de resúmenes (digests) que cubre las tablas editadas**. El
  editor no puede actualizarla. En la RTX 2080 Ti de arriba el driver usó igualmente la potencia de la tarjeta
  y de los conectores editada; para las demás tablas no se sabe.
- Al guardar una copia Turing editada también se guardan dos archivos para los cargadores a su lado:
  - `<nombre>-loader.bin`: el primer banco de la copia, sin cambios. Carga este primero.
  - `<nombre>-loader-e0end.bin`: el mismo banco, terminado en su última imagen de datos. Se quita la imagen
    pequeña que va después, que contiene la lista de resúmenes, y la última imagen de datos recibe las marcas
    de última imagen que llevan ahí las imágenes Ampere y Ada. Desde la línea de comandos:
    `nvbios normalize editada.rom payload.bin --representation turing-e0-end-v1`.

  Ambos envían al firmware GSP 250-355 KB desde la imagen legacy, muy por debajo de los 512 KiB que lee
  (calculado por análisis estático de `gsp_tu10x.bin` 615.78.08, no en hardware). Los archivos son más
  grandes, 364-500 KB, porque conservan el prefijo del banco antes de la imagen legacy (unos 162 KiB en la
  mayoría de las tarjetas), que no se envía. Un archivo con el segundo banco borrado conserva bytes de la flash
  después de su cadena de imágenes y enviaría más de 512 KiB; en ese caso el editor guarda solo
  `<nombre>-loader-e0end.bin` y explica por qué. En la RTX 2080 Ti de arriba ambos archivos se cargaron con el
  cargador de Windows (comprobado leyendo de vuelta la VBIOS en uso).

**Si el driver rechaza un override, la GPU arranca con su VBIOS de fábrica.** No se escribe nada en la
tarjeta. En Linux el registro del kernel dice `rejected override at ... using stock VBIOS` cuando el cargador
lo rechaza. Cuando lo rechaza el propio firmware GSP, se espera que vuelva a la de fábrica sin avisar (análisis
estático, sin probar en Turing), así que revisa también los límites de potencia.

## Guía para probar

Usa una versión del cargador cuyo README mencione Turing; las anteriores rechazan las GPUs Turing. En Linux,
vuelve a ejecutar la configuración para que se recompile el módulo con los chips Turing.

1. **Antes de nada**, guarda los límites de fábrica: `nvidia-smi -q -d POWER > antes.txt`, y guarda la ROM
   de tu tarjeta (por ejemplo `nvflash --save original.rom`, o GPU-Z en Windows).
2. **Imagen sin modificar**: expórtala sin cambios, `nvbios normalize original.rom original-loader.bin`, y
   carga `original-loader.bin`. Reinicia (Linux) o reinicia la GPU (Windows). La tarjeta debería funcionar
   como antes, y en Linux `journalctl -k -b | grep vbios_override` debería mostrar
   `selected: ... staged for GSP`. Esto muestra que el cargador acepta el archivo y que la tarjeta arranca con
   él, no que el GSP lo use: el archivo sin modificar tiene los mismos bytes que la VBIOS de la tarjeta, así
   que en Windows **Verificar** da coincidencia en ambos casos. En Windows, carga también el archivo e0-end
   sin modificar (`nvbios normalize original.rom original-e0end.bin --representation turing-e0-end-v1`),
   reinicia la GPU y pulsa **Verificar**: ese archivo difiere de la VBIOS de la tarjeta (dos bytes de marcas,
   sin la imagen de tipo 0x70), así que `override-active` significa que el driver lo usa y
   `override-not-active` que no.
3. **Cambio de límite de potencia**, la primera prueba real: en el editor, cambia un valor de potencia de
   forma visible (bajar el mínimo, `power_min_w`, es lo menos arriesgado; por ejemplo de 125 W a 100 W),
   guarda la copia, carga `<nombre>-loader.bin` y reinicia. Ejecuta `nvidia-smi -q -d POWER`: ¿Min (o Max,
   o Default) Power Limit muestra el valor nuevo?
4. **Si no cambia**, carga en su lugar `<nombre>-loader-e0end.bin` (el mismo cambio), reinicia y vuelve a
   comprobar.
5. **Subir la potencia** por encima del límite de fábrica requiere más que los campos de potencia de la
   tarjeta: cada entrada tiene su propio límite y, con los valores de fábrica, su suma queda cerca de la
   potencia máxima de fábrica (en la RTX 2080 Ti de arriba, los pasos 1 y 2 la llevaron de unos 300 W a 458 W).
   Un paso cada vez, probando bajo carga después de cada uno:
   1. `power_max_w` y `power_default_w` al objetivo, y `connector_N_power_rated_w` y
      `connector_N_power_max_w` de cada conector a más o menos el objetivo dividido por la cantidad de
      conectores (por ejemplo 500 W y 250 W en una RTX 2080 Ti de dos conectores).
   2. Deja el slot en sus valores de fábrica (63 W nominal y 74 W máximo en la RTX 2080 Ti). Si lo cambias,
      deja `slot_power_rated_w` en 66 W como mucho: el canal del slot mide solo los pines de 12 V, que la
      especificación PCIe CEM limita a 66 W (los 75 W del slot incluyen la línea de 3,3 V).
   3. Si la tarjeta sigue deteniéndose en la misma potencia: los umbrales de corriente avanzados de los
      conectores (`connector_N_current_threshold_*_ma`), solo donde el valor guardado sea menor que la nueva
      potencia del conector dividida por 12 V (250 W / 12 V son unos 20,8 A). No los bajes nunca; en la
      RTX 2080 Ti los 22,5 A nominales y 33,75 A máximos de fábrica ya cubren 250 W.
   4. Deja el límite de corriente NVVDD en su valor de fábrica salvo que un registro bajo carga muestre la
      corriente NVVDD cerca de él.

   Estos valores pueden superar el valor nominal de los conectores (150 W por cada 8 pines), de los cables y
   de la fuente de alimentación; el VRM y la refrigeración de la tarjeta siguen aplicando.
6. Para volver atrás, quita el override con el cargador (Linux: **Quitar override** o
   `nvbios system disable`; Windows: **Quitar reemplazo**).

**Si la tarjeta no arranca** (sin imagen, `nvidia-smi` falla): en Linux, elige tu entrada **normal** en el
menú de arranque, que no carga ningún override, y quita el override desde ahí (ver
[Si algo sale mal](https://github.com/Panchovix/nvidia-linux-vbios-vix-loader/blob/main/README_es.md#si-algo-sale-mal));
en Windows, arranca en modo seguro y pulsa **Quitar reemplazo** (ver
[Si la GPU no arranca](https://github.com/Panchovix/nvidia-windows-vbios-vix-loader/blob/main/README_es.md#si-la-gpu-no-arranca)).
Repórtalo también.

**Qué reportar** (un issue en el repositorio del editor): el modelo y el PCI ID de la GPU (Linux:
`lspci -nn | grep -i nvidia`; Windows: la lista de GPUs del cargador), la versión de la VBIOS
(`nvidia-smi -q | grep -i "VBIOS Version"`), la versión del driver y el sistema operativo; qué archivo cargaste
en cada paso y el cambio; `nvidia-smi -q -d POWER,CLOCK,PERFORMANCE` antes y después de cada paso, tomado **bajo
carga** (un juego o un benchmark a carga completa), cuyas `Clocks Event Reasons` (PerfCap) muestran qué limita a
la tarjeta. En Windows ayuda sobre todo un registro de HWiNFO bajo carga con la potencia de cada entrada (slot
PCIe, 8 pines #1 y #2), la corriente del núcleo de la GPU (NVVDD) y las razones de límite de rendimiento, además
del resultado de **Verificar** del cargador. En Linux también la línea `vbios_override` del registro del kernel.
