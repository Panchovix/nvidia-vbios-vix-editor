# Turing (experimental, sin probar en hardware Turing)

[English](turing.md) | Español

Las GPUs Turing (TU102, TU104, TU106, TU116 y TU117: GeForce RTX 20 y GTX 16, TITAN RTX, Quadro RTX y la serie
T) las reconocen el editor y ambos cargadores, **de forma experimental**. Ninguna tarjeta Turing ha corrido
todavía una imagen editada: nada de lo que sigue está probado en hardware. Si tienes una, la prueba del final
nos dice si funciona.

## Qué hace el editor

- **Solo la potencia de la tarjeta**: `power_max_w` (techo), `power_default_w` (valor por defecto al arrancar)
  y `power_min_w` (mínimo), todos marcados como experimentales. Las tablas de voltaje, relojes y ventiladores
  tienen otro formato en Turing y no se decodifican: no tienen campo.
- La tabla de potencia se decodifica como la de Ampere en las 22 imágenes Turing examinadas (escritorio,
  portátil, Max-Q, Quadro y TITAN, de TU102 a TU117). El cambio se escribe en los dos bancos de la imagen y se
  repara la suma de comprobación de la imagen tocada. Los límites siguen las reglas de Ampere; no son límites
  seguros para el hardware.
- Las imágenes Turing llevan una **lista firmada de resúmenes (digests) que cubre la tabla de potencia**. El
  editor no puede actualizarla, y no se sabe si el driver la comprueba. Es la razón principal por la que un
  cambio podría no aplicarse.
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
  `<nombre>-loader-e0end.bin` y explica por qué.

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
5. Para volver atrás, quita el override con el cargador (Linux: **Quitar override** o
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
en cada paso y el cambio; `nvidia-smi -q -d POWER` antes y después de cada paso. En Linux también la línea
`vbios_override` del registro del kernel; en Windows el resultado de **Verificar** del cargador.
