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
   eléctricos seguros.
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
   las políticas fijas 2/7 y los umbrales de hardware de Ada (corriente del slot,
   potencia de salida NVVDD y, en Ada, la corriente de entrada de 12 V, rotulada
   "umbral"); los valores ya escritos se conservan al marcarla. **Multiplicador
   de shunt (x)** (1 = desactivado, hasta 10) es solo informativo: en las filas de
   potencia de la tarjeta, potencia/corriente del slot PCIe y corriente de entrada
   de 12 V agrega una nota con el límite real en una tarjeta con shunt mod,
   aproximadamente el valor guardado por el multiplicador, suponiendo el mismo
   factor en todos los shunts de entrada de 12 V. Los límites de salida
   NVVDD/MSVDD los mide el VRM y no se escalan; no se escribe nada en la ROM. El
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
(la mitad); el offset del núcleo es igual en ambas. La representación de tabla
queda en `nvbios fields`. Las corrientes guardadas en mA (entrada de 12 V y OCP de
salida) se muestran y escriben en A, con hasta tres decimales; la GUI las convierte
de forma exacta y el backend, la CLI y el manifiesto siguen en mA. La frecuencia
PWM de los ventiladores se muestra y escribe en kHz de la misma forma; la tarjeta
Ventiladores también permite cambiar la cantidad de canales de ventilador. Ada y Ampere no heredan esa conversión. Los techos de
salida OCP revisados se expresan en mA, pero editarlos no demuestra que el firmware
los aplique. Un techo de ecuación REL/ALT/OV/VMIN tampoco es un voltaje evaluado ni
un offset runtime. La GUI guarda el archivo completo y no normaliza los bancos
implícitamente. Los formatos desconocidos o no editables permiten sólo inspección.
Las firmas criptográficas no se verifican ni regeneran.

Atajos: `Ctrl+O` abre, `Ctrl+Enter` verifica al momento, `Ctrl+S` guarda una
copia, `Ctrl+R` restablece y `Ctrl+Q` cierra. La ventana (760×920 por defecto) es
de una sola columna: tarjeta del dispositivo, luego Potencia, Voltaje, Offsets de
reloj, Corriente y protección, y Ventiladores, y al final los campos de solo lectura en una
sección plegada. La barra de cambios queda siempre visible. Tab recorre los controles. Los errores muestran códigos
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
