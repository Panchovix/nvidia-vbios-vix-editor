"""Spanish GUI catalog, selected explicitly with --lang es."""

from types import MappingProxyType

MESSAGES_ES = MappingProxyType({'window_title': 'NVIDIA VBIOS — Editor de archivos',
 'open': 'Abrir ROM…',
 'app_title': 'Editor de VBIOS NVIDIA',
 'no_file': 'Ninguna ROM abierta',
 'welcome': 'Abre una ROM para empezar. Guardar siempre crea una copia nueva; el archivo original nunca se modifica.',
 'section.power': 'Potencia',
 'section.voltage': 'Voltaje',
 'section.clocks': 'Offsets de reloj',
 'section.current': 'Corriente y protección',
 'section.other': 'Otros',
 'section.fans': 'Ventiladores',
 'field.fan_pwm_frequency_hz': 'Frecuencia PWM de los ventiladores (experimental)',
 'field.fan_channels': 'Canales de ventilador (experimental)',
 'field.fan_zero_rpm': 'Parada de ventiladores en reposo (avanzado, experimental)',
 'reason.fan_layout': 'Esta tabla no guarda otra disposición de canales de ventilador, o los límites de un canal '
                       'guardado no contienen las curvas adicionales.',
 'field.fan_min_rpm': 'Velocidad mínima del ventilador {fan} (experimental)',
 'field.fan_max_rpm': 'Velocidad máxima del ventilador {fan} (experimental)',
 'field.fan_min_pct': 'Nivel mínimo del ventilador {fan} (avanzado, experimental)',
 'field.fan_max_pct': 'Nivel máximo del ventilador {fan} (avanzado, experimental)',
 'field.fan_curve_temp_c': 'Curva del ventilador {fan}, punto {point}: temperatura (experimental)',
 'field.fan_curve_rpm': 'Curva del ventilador {fan}, punto {point}: velocidad (experimental)',
 'field.fan_curve_pct': 'Curva del ventilador {fan}, punto {point}: nivel (avanzado, experimental)',
 'field.fan_extra_curve_temp_c': 'Curva adicional {curve}, punto {point}: temperatura (experimental)',
 'field.fan_extra_curve_rpm': 'Curva adicional {curve}, punto {point}: velocidad (experimental)',
 'field.fan_extra_curve_pct': 'Curva adicional {curve}, punto {point}: nivel (avanzado, experimental)',
 'field.fan_zero_rpm_low_temp_c': 'Ventilador {fan}, parada en reposo: umbral inferior (avanzado, experimental)',
 'field.fan_zero_rpm_high_temp_c': 'Ventilador {fan}, parada en reposo: umbral superior (avanzado, experimental)',
 'field.fan_extra_zero_rpm_low_temp_c': ('Curva adicional {curve}, parada en reposo: umbral inferior '
                                         '(avanzado, experimental)'),
 'field.fan_extra_zero_rpm_high_temp_c': ('Curva adicional {curve}, parada en reposo: umbral superior '
                                          '(avanzado, experimental)'),
 'field.memory_point_follows_offset': ('El clock de memoria de {mhz} MHz sigue el offset de memoria '
                                       '(avanzado, experimental)'),
 'field.gpc_curve_offset_mhz': 'Offset de la curva GPC (avanzado, experimental)',
 'field.factory_gpc_offset_mhz': 'Offset GPC de fábrica (overclock del fabricante, experimental)',
 'field.factory_memory_offset_mhz': 'Offset de memoria de fábrica (overclock del fabricante, experimental)',
 'field.factory_rated_boost_mhz': 'Clock boost nominal de fábrica',
 'field.max_operating_temp_c': 'Temperatura máxima de funcionamiento (experimental)',
 'section.advanced': 'Avanzado: controladores de rendimiento y ahorro en reposo',
 'section.advanced_note': ('Blackwell, Ada, Ampere y Turing. Experimental y sin probar en hardware. La política de '
                           'utilización y sus controladores deciden cómo el driver sube y baja los clocks GPC, de '
                           'memoria (DRAM) y de video (VID) según la carga. No está probado que el driver use esta '
                           'tabla en ninguna de estas tarjetas. Un objetivo más bajo sube los clocks antes, con más '
                           'consumo y calor. Los interruptores de ahorro en reposo dejan cada función como viene (De '
                           'fábrica) o la apagan (Desactivado), y deberían actuar solo en reposo o con carga ligera. '
                           'Ahorro en reposo muestra solo las funciones que la ROM trae activadas. Desactivado gasta '
                           'un poco más en reposo, y tiempos de reposo muy cortos pueden causar tirones o, rara vez, '
                           'pantalla negra en reposo. Un valor que depende de un interruptor queda en gris mientras '
                           'ese interruptor está apagado. Esta sección se muestra con o sin Mostrar campos avanzados '
                           '(estilo XOC), e Importar desde ROM… nunca la copia.'),
 'section.advanced_perf': 'Controladores de clocks',
 'section.advanced_lpwr': 'Ahorro en reposo',
 'field.perf_cf_util_policy': 'Política de clocks por utilización (experimental)',
 'field.perf_cf_target_pct': 'Objetivo de utilización {domain} (experimental)',
 'field.perf_cf_jump_pct': 'Umbral de salto {domain} (experimental)',
 'field.perf_cf_hysteresis_down': 'Histéresis de bajada {domain} (muestras, experimental)',
 'field.perf_cf_hysteresis_up': 'Histéresis de subida {domain} (muestras, experimental)',
 'field.lpwr_gr_power_gating': 'Power gating de GR (experimental)',
 'field.lpwr_mscg': 'Clock gating del sistema de memoria, MSCG (experimental)',
 'field.lpwr_nvdec_gating': 'Power gating de NVDEC (experimental)',
 'field.lpwr_nvenc_gating': 'Power gating de NVENC (experimental)',
 'field.lpwr_ofa_gating': 'Power gating de OFA (experimental)',
 'field.lpwr_nvjpg_gating': 'Power gating de NVJPG (experimental)',
 'field.lpwr_difr': 'Ahorro de energía con imagen fija, DIFR (experimental)',
 'field.lpwr_difr_dfpr_idle_ms': 'Tiempo de reposo DFPR de DIFR (experimental)',
 'field.lpwr_difr_sw_asr_idle_us': 'Tiempo de reposo SW-ASR de DIFR (experimental)',
 'field.lpwr_difr_cg_idle_us': 'Tiempo de reposo del clock gating de DIFR (experimental)',
 'field.lpwr_gr_rail_gating': 'Rail gating de GR (experimental)',
 'field.lpwr_gr_rail_gating_idle_us': 'Tiempo de reposo del rail gating de GR (pasos de 10 µs, experimental)',
 'section.readonly': 'Campos de solo lectura ({count})',
 'section.voltage_note': ('REL y OV son techos de ecuación; un voltaje fijo REL o ALT fija el valor de una ecuación '
                          'constante, y un REL fijo queda igual o por debajo de ALT: para subirlo más, sube ALT en la '
                          'misma edición. VMIN cambia un valor guardado; las ecuaciones encadenadas pueden cambiar el '
                          'mínimo efectivo.'),
 'section.unsupported': 'Algunos campos de esta sección no se muestran: esta VBIOS usa una disposición que el editor '
                        'aún no admite.',
 'badge.experimental': 'experimental',
 'memory.title': 'Memoria (solo lectura)',
 'memory.note': ('Decodificado de las tablas de la ROM. Los nombres "inferidos" salen de patrones de bytes, no de '
                 'documentación de NVIDIA. La configuración que usa tu tarjeta la fija la placa.'),
 'memory.loading': 'Leyendo las tablas de memoria…',
 'memory.unrecognized': 'Tablas de memoria no reconocidas: {reason}',
 'memory.section_unrecognized': '{section}: no se reconoce ({reason})',
 'memory.configurations': 'Configuraciones de memoria',
 'memory.configuration': 'Strap {strap} → columna {column} · {vendor} · tipo {type}',
 'memory.type_guess': '{code} (probablemente {name})',
 'memory.vendor_code': 'fabricante {code}',
 'memory.timings': 'Entradas de timings, en ciclos del controlador',
 'memory.stock_bands': 'Bandas que contienen los clocks de memoria de fábrica; Bytes en bruto lista todas las bandas.',
 'memory.all_bands': 'Los clocks de memoria de fábrica no se leen en esta ROM; se muestran todas las bandas.',
 'memory.column': 'Strap {straps} → columna {column} · {vendor}',
 'memory.no_entries': 'Sin entrada de timings en estas bandas.',
 'memory.outside_table': 'Fuera de la tabla de clocks de memoria (columnas 0–{last}).',
 'memory.band': 'Banda (MHz)',
 'memory.entry': 'Entrada',
 'memory.stock': 'fábrica {points}',
 'memory.confidence.inferred': 'inferido',
 'memory.confidence.probable': 'probable',
 'memory.confidence.tentative': 'tentativo',
 'memory.profile': ('Perfil de entrenamiento de memoria de la placa (objeto 0x89): etiqueta {tag} · '
                    'huella {fingerprint}'),
 'memory.profile_note': ('Datos de arranque por placa sin decodificar, probablemente entrenamiento de la interfaz de '
                         'memoria. Una diferencia no significa que una BIOS sea más rápida. Solo tiene efecto al '
                         'flashear la ROM completa; el override no puede aplicarlo.'),
 'memory.profile_unrecognized': 'Perfil de entrenamiento de memoria de la placa no reconocido: {reason}',
 'memory.raw': 'Bytes en bruto',
 'memory.compare': 'Comparar con otra ROM…',
 'memory.compare_dialog': 'Elige una ROM para comparar',
 'memory.comparing': 'Comparando las tablas de memoria…',
 'memory.compared': 'Comparado con {file}: solo indica si hay diferencias, nunca cuál es mejor o peor.',
 'memory.compare_failed': 'La comparación falló: {message}',
 'memory.section.configurations': 'Configuraciones de memoria',
 'memory.section.bands': 'Bandas de clock de memoria',
 'memory.section.timings': 'Entradas de timings',
 'memory.section.tables': 'Tablas de memoria (SHA-256)',
 'memory.section.board_profile': 'Perfil de entrenamiento de memoria de la placa',
 'memory.identical': '{section}: sin diferencias',
 'memory.differs': '{section}: con diferencias',
 'memory.differs_entries': '{section}: con diferencias (entradas: {count})',
 'memory.differs_tables': '{section}: con diferencias ({tables})',
 'memory.differs_fields': '{section}: con diferencias de significado desconocido (campos: {count})',
 'memory.differs_unknown': '{section}: con diferencias de significado desconocido',
 'memory.unavailable': '{section}: no se reconoce en una o ambas ROM',
 'memory.table.memory_configurations': 'configuraciones de memoria',
 'memory.table.memory_clock_bands': 'bandas de clock de memoria',
 'memory.table.timings': 'timings',
 'memory.table.training': 'entrenamiento',
 'memory.table.training_patterns': 'patrones de entrenamiento',
 'memory.table.memory_data': 'datos de memoria',
 'import': 'Importar desde ROM…',
 'import.dialog': 'Elige una ROM de la que importar valores',
 'import.title': 'Importar desde otra ROM',
 'import.from': 'Copiar valores de {file} a la ROM abierta. Secciones:',
 'import.opt_in': 'Importar también los campos avanzados (estilo XOC)',
 'import.note': ('Los valores se copian como números almacenados, sin adaptarlos a esta placa: las velocidades de '
                 'ventilador, los límites de potencia y corriente y los límites de voltaje de otra placa pueden '
                 'superar lo que soportan los ventiladores, los conectores de alimentación, las etapas de potencia o '
                 'la GPU de esta placa, y un offset de reloj de otra placa puede no ser estable en esta. Quedan como '
                 'cambios pendientes: revísalos en la lista de cambios antes de guardar.'),
 'import.accept': 'Importar',
 'import.close': 'Cerrar',
 'import.reading': 'Leyendo la otra ROM…',
 'import.applied': 'Importados de {file} como cambios pendientes: {count}.',
 'import.nothing': 'No se importó nada de {file}.',
 'import.different_device': ('La otra ROM es de otro producto de esta familia (PCI {donor}; esta ROM: PCI '
                             '{target}). Sus valores se fijaron para ese producto.'),
 'import.unchanged': 'Ya iguales en ambas ROM: {count}.',
 'import.skipped': 'No importados: {count}.',
 'import.opt_in_hint': ('Algunos campos van junto con campos avanzados que difieren; importa de nuevo con los '
                        'campos avanzados para traerlos.'),
 'import.stale': 'La ROM abierta cambió; no se importó nada.',
 'import.failed': 'La importación falló: {message}',
 'import.reason.absent_in_donor': 'no está en la otra ROM',
 'import.reason.absent_in_target': 'no está en esta ROM',
 'import.reason.read_only_in_donor': 'de solo lectura en la otra ROM',
 'import.reason.per_chip_in_donor': 'en la otra ROM se fija por chip, no se guarda como número',
 'import.reason.read_only_in_target': 'de solo lectura en esta ROM',
 'import.reason.read_only': 'de solo lectura en ambas ROM',
 'import.reason.opt_in': 'campo avanzado, no incluido',
 'import.reason.board_specific': 'cantidad de ventiladores de esta placa; nunca se copia',
 'import.reason.product_specific': 'límite de temperatura propio de este producto; nunca se copia',
 'import.reason.different_meaning': ('en la otra ROM es otra magnitud (otras unidades, otro nivel de memoria, otro '
                                     'esquema de potencia u otra ecuación de voltaje)'),
 'import.reason.held_back': 'va junto con campos relacionados que no se importan: {fields}',
 'import.reason.held_back_many': 'van junto con campos relacionados que no se importan: {fields}',
 'import.more': '{fields} y {count} más',
 'import.reason.out_of_bounds': 'fuera del rango de esta ROM ({minimum} a {maximum} {units})',
 'import.reason.refused': 'rechazado por el editor: {message} [{code}]',
 'changes_heading': 'Cambios',
 'live_none': 'Sin cambios. Edita un valor y la vista previa se actualiza aquí.',
 'live_checking': 'Verificando cambios…',
 'live_ok': 'Cambios verificados: {count} · integridad de la copia OK · {bytes} bytes',
 'live_same': 'Sin diferencias con el original.',
 'change.not_used': 'no se usa',
 'unexpected': 'Error inesperado en la ventana del editor, por favor repórtalo: {message} [{code}]',
 'not_a_number': 'Introduce un número',
 'order_hint': 'Rompe el orden mínimo ≤ nominal ≤ máximo de su grupo',
 'order_hint_voltage': 'Rompe el orden VMIN < REL ≤ ALT; cambia estos valores juntos',
 'order_hint_fan': ('Los límites y puntos de las curvas deben quedar dentro de sus rangos permitidos; '
                     'cambia los valores relacionados juntos'),
 'zero_rpm_hint': ('Con la parada en reposo activada, el umbral superior no puede quedar por encima del punto 1 '
                   'de la misma curva; cámbialos juntos'),
 'zero_rpm_lower_hint': ('Este umbral inferior está en el punto 1 de su curva o por encima; bájalo por debajo del '
                         'umbral superior en la misma edición'),
 'zero_rpm_channels_hint': ('Una cantidad mayor activa un ventilador guardado cuyo umbral superior de parada en reposo '
                            'está por encima del punto 1 de su curva. Desactiva la parada en reposo y guarda; en esa '
                            'copia cambia la cantidad y guarda; luego activa la parada en reposo con ese umbral más '
                            'bajo'),
 'zero_rpm_channels_locked_hint': ('Una cantidad mayor activa un ventilador guardado cuyo umbral superior de parada en '
                                   'reposo está por encima del punto 1 de su curva, y la parada en reposo es de solo '
                                   'lectura en esta ROM, así que la cantidad no se puede subir'),
 'fan_curve_min_hint': ('Las curvas tienen puntos por debajo de este mínimo (bajan hasta {value} {units}). '
                        'Sube esos puntos en la misma edición: {points}.'),
 'fan_curve_max_hint': ('Las curvas tienen puntos por encima de este máximo (llegan hasta {value} {units}). '
                        'Baja esos puntos en la misma edición: {points}.'),
 'fan_curve_readonly_hint': ('Algunos puntos que bloquean el cambio son de solo lectura en esta imagen: {points}. '
                             'Mantén el límite del ventilador dentro de su rango.'),
 'out_of_range': 'Valor fuera de rango',
 'range_min': 'Mínimo: {minimum} {units}',
 'fix_fields': 'Corrige los campos marcados en rojo.',
 'live_failure': '{message} [{code}]',
 'windows_short': 'Afterburner: {value} MHz',
 'range_hint': 'Permitido: {minimum} a {maximum} {units}',
 'windows_equivalent': 'En Windows (MSI Afterburner): {value} MHz',
 'linux_short': 'nvidia-settings: {value} MHz',
 'linux_equivalent': 'Como en MSI Afterburner · En Linux (nvidia-settings): {value} MHz',
 'factory_offset_on': 'activa un offset de fábrica que está apagado en esta ROM (sin probar en esas ROM)',
 'copy_note': 'Guardar crea una ROM nueva + manifiesto JSON. Sin validación en hardware.',
 'license_note': ('NVIDIA VBIOS Vix Editor {version} · Copyright (C) 2026 panchovix · '
                  'Software libre bajo la GNU GPL v3 o posterior, SIN GARANTÍA. Licencia y código fuente: '
                  'https://github.com/Panchovix/nvidia-vbios-vix-editor'),
 'save': 'Guardar copia…',
 'heading': 'Editor de archivos · Guardar crea una copia',
 'open_prompt': 'Abre una ROM para inspeccionar su identidad y formato.',
 'rel_notice': 'REL: techo de ecuación, no voltaje efectivo.',
 'fields_heading': 'Campos · valores y unidades',
 'preview_heading': 'Vista previa · original → copia',
 'no_changes': 'Sin cambios preparados.',
 'stage': 'Preparar y verificar',
 'reset': 'Restablecer cambios',
 'ready_help': 'Listo. Ctrl+O abrir · Ctrl+S guardar copia · Ctrl+R restablecer · la vista previa '
               'se actualiza mientras escribes',
 'saved': 'Copia guardada: {output}\nManifiesto: {manifest}',
 'saved_loader': 'Para los cargadores de VBIOS, carga este archivo en vez de la copia: {output}',
 'saved_loader_failed': 'Sin archivo para los cargadores de VBIOS: {reason}',
 'saved_loader_other_failed': 'El otro archivo para los cargadores de VBIOS no se guardó: {reason}',
 'saved_loader_alternative': ('Si el archivo cargado no aplica el cambio, prueba este en su lugar '
                              '(experimental): {output}'),
 'verified': 'Vista previa verificada. Guardar copia crea ROM + manifiesto JSON; no sobrescribe '
             'archivos.',
 'loaded': 'ROM cargada. Edición offline; sin validación de esta copia en hardware.',
 'loading': 'Leyendo e inspeccionando ROM…',
 'all_files': 'Todos los archivos',
 'open_dialog': 'Abrir ROM para edición offline',
 'open_accept': 'Abrir',
 'save_accept': 'Guardar copia',
 'cancel': 'Cancelar',
 'file_options': 'Opciones de archivo',
 'theme': 'Tema',
 'theme.auto': 'Sistema',
 'theme.light': 'Claro',
 'theme.dark': 'Oscuro',
 'open_builtin': 'Abrir con selector integrado…',
 'save_builtin': 'Guardar con selector integrado…',
 'open_path': 'Abrir por ruta…',
 'save_path': 'Guardar copia por ruta…',
 'path_label': 'Ruta del archivo',
 'path_hint': 'Escribe una ruta del equipo donde corre el editor, también al usar SSH. Se aceptan rutas absolutas y ~/.',
 'path_error': 'Introduce una ruta de archivo local, no una URL.',
 'cli_theme': 'Tema: auto sigue el modo de apps de Windows (en otros sistemas, el escritorio); light o dark',
 'cli_file_dialog': 'Selector: auto usa el integrado por SSH; system usa el diálogo del escritorio',
 'local_file': 'Selecciona un archivo local.',
 'save_dialog': 'Guardar copia nueva + manifiesto JSON',
 'stale_dialog': 'La ROM o vista previa cambió. Elige el destino de nuevo.',
 'preview_first': 'Prepara la vista previa actual antes de guardar.',
 'new_destination': 'Selecciona un destino local nuevo.',
 'saving': 'Guardando copia y manifiesto sin sobrescribir…',
 'dirty': 'Valores modificados: pulsa Preparar y verificar para actualizar la vista previa.',
 'staging': 'Construyendo y verificando vista previa…',
 'reset_done': 'Cambios restablecidos al original inmutable.',
 'unknown': 'Desconocido',
 'flag_on': 'Activado',
 'flag_off': 'Desactivado',
 'flag_mixed': 'Mixto (activado en algunas entradas de ventilador)',
 'flag_stock': 'De fábrica',
 'unknown_version': 'desconocida',
 'unrecognized': 'no reconocido',
 'format': 'Formato: {format}',
 'integrity': 'Integridad: {summary}',
 'integrity_verified': 'Verificada',
 'integrity_failed': 'FALLÓ',
 'integrity_unknown': 'Desconocida (solo inspección parcial)',
 'no_fields': 'Este formato no expone campos validados para edición.',
 'readonly': 'Solo lectura',
 'original': 'Original: {value} {units}',
 'factory': 'Valor por defecto nominal de esta ROM: {value} {units}.',
 'static_ceiling': 'Techo estático; no representa el voltaje efectivo.',
 'copy_integrity': 'Integridad de copia: verificada',
 'not_hardware_tested': 'Validación de nueva copia en hardware: no realizada',
 'unchanged_preview': 'Sin cambios preparados. Preparar y verificar también permite guardar una '
                      'copia exacta de un formato editable.',
 'table_alias': 'Mismo campo en unidades de tabla (la escala de las herramientas de Windows); solo lectura.',
 'field_alias': 'Alias del control principal; solo lectura.',
 'failure': '{message} [{code}]',
 'failure_generic': 'La operación falló',
 'cli_description': 'Editor gráfico offline de NVIDIA VBIOS',
 'cli_rom': 'ROM local opcional',
 'cli_language': 'Idioma de la interfaz (predeterminado: en; independiente del idioma del sistema)',
 'missing_gtk': 'La GUI requiere GTK4 y Python PyGObject (gi): {error}',
 'field.power_min_w': 'Piso de potencia de la placa',
 'field.power_max_w': 'Techo de potencia de la placa',
 'field.nvvdd_rel_max_mv': 'Techo REL de NVVDD',
 'field.msvdd_rel_max_mv': 'Techo REL de MSVDD',
 'field.dram_max_table_mhz': 'Techo de offset de memoria (tabla)',
 'field.memory_offset_max_mhz': 'Techo de offset de memoria',
 'field.current_limit_a': 'Límite de corriente de entrada',
 'field.ocp_limit_a': 'Protección contra sobrecorriente (OCP)',
 'field.output_ocp': 'Techo de corriente OCP de salida de {rail}',
 'field.output_ocp_rated': 'Límite de corriente OCP de salida de {rail}, nominal (experimental)',
 'field.output_ocp_advanced': 'Techo del límite de corriente de salida de {rail} (avanzado, experimental)',
 'field.output_ocp_rated_advanced': 'Límite de corriente de salida de {rail}, nominal (avanzado, experimental)',
 'field.slot_power_rated_w': 'Límite de potencia del slot PCIe, nominal (experimental)',
 'field.slot_power_max_w': 'Techo de potencia del slot PCIe (experimental)',
 'field.slot_current_threshold_rated_ma': 'Umbral de corriente del slot PCIe, nominal (avanzado, experimental)',
 'field.slot_current_threshold_max_ma': 'Techo del umbral de corriente del slot PCIe (avanzado, experimental)',
 'field.nvvdd_power_threshold_rated_w': 'Umbral de potencia de salida NVVDD, nominal (avanzado, experimental)',
 'field.nvvdd_power_threshold_max_w': 'Techo del umbral de potencia de salida NVVDD (avanzado, experimental)',
 'field.connector_power_max': 'Techo del canal de potencia de conector {connector} (experimental)',
 'field.connector_power_rated': 'Límite del canal de potencia de conector {connector}, nominal (experimental)',
 'field.connector_power_max_advanced': 'Techo del canal de potencia de conector {connector} (avanzado, experimental)',
 'field.connector_power_rated_advanced': ('Límite del canal de potencia de conector {connector}, nominal (avanzado, '
                                          'experimental)'),
 'connector_input.rating': 'Este límite acota la potencia que entra por el conector de alimentación auxiliar. La '
                           'ROM no guarda el tipo de conector: un conector PCIe de 8 pines admite 150 W, y un cable '
                           '12V-2x6 (16 pines), el nivel que indican sus pines de detección. Pasar de lo que admiten '
                           'el conector y su cable pone en riesgo el cable, el conector y la fuente. Es decisión tuya.',
 'connector_input.limits': 'El límite de potencia de la placa y, donde la placa los guarda, el límite del slot PCIe y '
                           'el límite o umbral de corriente de entrada de 12 V siguen vigentes y pueden limitar '
                           'después, así que súbelos juntos donde haga falta. Sin probar en hardware.',
 'connector_input.threshold': 'La fila {row} también guarda un umbral de corriente de {amps} A en esta entrada del '
                              'conector (unos {watts} W a 12 V). No se puede editar aquí y puede frenar el conector '
                              'antes.',
 'field.connector_sum_power_max_w': 'Techo de la suma de potencia de conectores (experimental)',
 'field.connector_sum_power_rated_w': 'Límite de la suma de potencia de conectores, nominal (experimental)',
 'summed_cap.connectors': 'La fila {row} también limita la suma de los canales de potencia de conector {channels} a '
                          '{rated} {units} nominal / {maximum} {units} máximo y puede actuar primero: subir solo este '
                          'límite puede no tener efecto.',
 'summed_cap.channels': 'La fila {row} también limita la suma de los canales de potencia {channels} a {rated} {units} '
                        'nominal / {maximum} {units} máximo y puede actuar primero: subir solo este límite puede no '
                        'tener efecto.',
 'summed_cap.raise': 'Sube también los límites de la suma de potencia de conectores.',
 'sense_profiles.levels': 'Esta ROM fija sus límites de potencia según los pines de detección del cable de 16 pines. '
                          'Este valor se aplica en el nivel más alto, probablemente un cable de {watts} W (deducido, '
                          'sin probar). Los niveles más bajos mantienen sus propios límites.',
 'sense_profiles.past_top': 'Pasar de {watts} W supera lo que admite ese cable. Es decisión tuya.',
 'notebook.ceiling': 'En un portátil, Dynamic Boost pide el límite de potencia en uso mientras funciona y este techo '
                     'solo lo acota. Las herramientas de monitoreo muestran este techo guardado, así que subir solo '
                     'el techo por lo general no sube el límite en uso. En una RTX 5090 Laptop GPU el límite en uso '
                     'pasó de 175 a unos 185 W con el techo, la potencia por defecto al arrancar y el TGP base del '
                     'portátil subidos juntos a 190, 110 y 165 W. Subir solo el techo, o el techo con uno solo de los '
                     'otros dos, lo dejó en 175 W. Para subir el límite en uso, sube los tres juntos. El TGP base del '
                     'portátil está en Mostrar campos avanzados (estilo XOC) cuando la ROM lo tiene. Otros portátiles '
                     'no se probaron, y el VRM, la refrigeración y el cargador del portátil se dimensionaron para el '
                     'límite de fábrica.',
 'notebook.default': 'Para subir el límite en uso en un portátil, sube esta potencia por defecto al arrancar junto con '
                     'el techo y el TGP base del portátil, tantos vatios como subas el TGP base. El TGP base está en '
                     'Mostrar campos avanzados (estilo XOC) cuando la ROM lo tiene. En una RTX 5090 Laptop GPU, con '
                     '110 W aquí (de 95 W), el TGP base subido de 150 a 165 W y un techo de 190 W, el límite en uso '
                     'pasó de 175 a unos 185 W. Subir la potencia por defecto al arrancar y el techo sin el TGP base '
                     'lo dejó en 175 W.',
 'notebook.base_tgp': 'Probado en una RTX 5090 Laptop GPU, donde se comportó como el TGP base al que Dynamic Boost '
                      'le suma su boost y subió el límite en uso solo junto con el techo y la potencia por defecto al '
                      'arrancar. Con 165 W aquí (de 150 W), un techo de 190 W y 110 W por defecto al arrancar (de 95 '
                      'W), el límite en uso pasó de 175 a unos 185 W, mientras que el mismo TGP base y el mismo techo '
                      'con la potencia por defecto de fábrica lo dejaron en 175 W. Para subir el límite en uso, sube '
                      'los tres juntos, la potencia por defecto al arrancar tantos vatios como subas este valor. El '
                      'techo sigue siendo el tope. Si lo cambias, tiene que quedar entre la potencia por defecto al '
                      'arrancar y el techo. Para pasar del techo, sube el techo junto con él en la misma edición. Una '
                      'copia guardada con el techo por debajo de este valor o la potencia por defecto al arrancar por '
                      'encima no muestra este campo pero conserva su valor guardado, y el campo vuelve al deshacer ese '
                      'cambio. Otros portátiles no se probaron. El VRM, la refrigeración y el cargador del portátil se '
                      'dimensionaron para el límite de fábrica, y si la batería se descarga enchufada con la CPU y la '
                      'GPU a plena carga, el cargador no alcanza.',
 'lpwr.enabled_entries': ('Este producto no está entre los revisados, así que este interruptor cubre las entradas '
                          'que esta ROM activa. Una copia guardada con Desactivado ya no muestra el interruptor, '
                          'porque una entrada que viene desactivada se ve igual que una apagada: guarda la ROM '
                          'original para volver a De fábrica.'),
 'output_ocp.ampere': ('Sin probar en hardware. Un tope de potencia por debajo del techo de potencia de la placa puede '
                       'venir de este límite de corriente, aunque no se sabe si la GPU lo aplica. Probablemente '
                       'protege el VRM del núcleo, que se dimensionó para el valor de fábrica. Subirlo queda a tu '
                       'criterio, y es más seguro hacerlo en pasos pequeños.'),
 'sense_profiles.input_current': 'El umbral de corriente de entrada de 12 V (nominal {amps} A, unos {watts} W a 12 V) '
                                 'puede limitar antes. Súbelo también, en Mostrar campos avanzados (estilo XOC).',
 'vmin_clone.memory': 'En esta ROM el piso de voltaje del reloj de memoria mantiene su valor de fábrica. Un VMIN más '
                      'bajo solo se nota mientras la memoria va a su reloj más bajo ({mhz} MHz, reposo con un monitor). '
                      'Un VMIN más alto se nota con cualquier reloj de memoria solo por encima de {floor} mV (VMIN de '
                      'fábrica + {constant} mV). Hasta ahí también se nota solo en ese reloj más bajo.',
 'vmin_tree.tree': 'El VMIN de fábrica de esta ROM se fija por chip a partir de valores de fusibles y cambia con la '
                   'temperatura, así que la ROM no guarda un valor único. Un valor aquí fija el VMIN en ese valor '
                   'para todo chip y temperatura.',
 'vmin_tree.step': 'Los drivers de Blackwell redondean el VMIN hacia arriba a pasos de 5 mV.',
 'vmin_tree.per_chip': 'El valor base de fábrica de este VMIN se fija por chip a partir de un valor de fusibles ({low} '
                       'a {high} mV), así que la ROM no guarda un valor único. Un valor aquí fija ese valor base. Los '
                       'términos encadenados después siguen sumando su parte según el chip y la temperatura.',
 'vmin_tree.risk': 'Sin probar en hardware. Un valor por debajo del VMIN de fábrica de este chip puede volver '
                   'inestables el reposo y las cargas ligeras, y uno más alto sube el voltaje y el consumo en reposo. '
                   'También puede que el driver mantenga el VMIN de fábrica. Quitar el override devuelve la tarjeta a '
                   'como estaba, y desactivar "VMIN fijo" en una copia guardada escribe de vuelta los bytes de '
                   'fábrica.',
 'vmin_tree.switch': 'Activado mientras el valor de arriba fija el VMIN. Desactivado escribe de vuelta los bytes de '
                     'fábrica, así el VMIN vuelve a seguir al chip. Guarda este cambio y un VMIN nuevo en copias '
                     'separadas.',
 'reason.vmin_fixed_stock': 'Desactivado: el VMIN es el de fábrica de cada chip. Escribe un valor en la fila del '
                            'voltaje mínimo para fijarlo.',
 'original_per_chip': 'Original: por chip (no está guardado en la ROM)',
 'per_chip_value': 'por chip',
 'vmin_clone.risk': 'Sin probar en hardware. Un VMIN distinto del de fábrica agrega una ecuación VFE a la ROM, y '
                    'ninguna tarjeta Ada ha usado todavía una ecuación agregada por el editor. El override podría no '
                    'cargar o el driver podría no iniciar. Quitar el override devuelve la tarjeta a como estaba.',
 'fan_stop.template': ('Esta tarjeta blower no guarda valores de parada. Activado escribe además los valores que '
                       'NVIDIA guarda en la ROM {donor} (umbrales de parada {pairs} °C); Desactivado en esa copia '
                       'escribe de vuelta los bytes de fábrica.'),
 'fan_stop.blower': ('Ninguna tarjeta blower sale de fábrica con la parada activada. Lo más probable es que un blower '
                     'parado no mueva aire por la tarjeta, incluidas la memoria y las etapas de potencia, hasta que '
                     'la tarjeta pase el umbral superior. Rearrancar un blower desde 0 RPM no está probado, y en '
                     'equipos con varias GPU juntas puede acumularse calor y el ventilador puede pararse y arrancar '
                     'en ciclos. Sin probar en hardware en esta tarjeta.'),
 'fan_stop.off': ('Esta ROM viene de fábrica con la parada en reposo desactivada. Si la tarjeta tiene un ventilador '
                  'blower, lo más probable es que un ventilador parado no mueva aire por la tarjeta, incluidas la '
                  'memoria y las etapas de potencia, hasta que pase el umbral superior. Rearrancar un blower desde 0 '
                  'RPM no está probado, y en equipos con varias GPU juntas puede acumularse calor y el ventilador '
                  'puede pararse y arrancar en ciclos.'),
 'fan_stop.bit4': ('Con la parada en reposo activada, las entradas de los canales de ventilador de esta ROM quedan con '
                   'los bits 1 y 2 activos y el bit 4 apagado, una forma de flags con la que ninguna ROM de fábrica '
                   'usa la parada en reposo; no está probado si los ventiladores se detienen.'),
 'fan_stop.flat': ('"{field}" es igual al umbral superior ({value} °C): con la parada en reposo activada no hay '
                   'histéresis, así que los ventiladores pueden pararse y arrancar a menudo cerca de esa temperatura. '
                   'Bájalo unos grados.'),
 'fan_stop.untested': 'Sin probar en hardware en tarjetas Ada ni Ampere.',
 'fan_stop.manual': 'Una herramienta de ventiladores que mantiene el control manual deja los ventiladores girando.',
 'field.connector_current_threshold_rated': ('Umbral de corriente del canal de conector {connector}, nominal '
                                             '(avanzado, experimental)'),
 'field.connector_current_threshold_max': ('Techo del umbral de corriente del canal de conector {connector} '
                                           '(avanzado, experimental)'),
 'field.board_fixed_rated_w': 'Potencia nominal de las políticas fijas 2/7 de la placa (avanzado, estilo XOC, '
                              'experimental)',
 'field.notebook_base_tgp_w': 'TGP base del portátil (experimental)',
 'show_advanced': 'Mostrar campos avanzados (estilo XOC)',
 'shunt_multiplier': 'Multiplicador de shunt (x)',
 'shunt_help': 'Solo informativo: la VBIOS guarda los valores de los campos. Supone el mismo multiplicador en '
               'todos los shunts de entrada de 12\u00a0V (conector y slot PCIe). Los límites de salida NVVDD/MSVDD '
               'los mide el VRM, no los shunts, y no se escalan.',
 'shunt_real': 'Unos {value} {units} reales con un shunt x{factor}',
 'field.equation': 'Techo de ecuación {role} de {rail}',
 'field.vmin': 'Voltaje mínimo (VMIN) de {rail} (experimental)',
 'field.vmin_fixed': 'VMIN fijo de {rail} (experimental)',
 'field.vmin_slot': 'Techo de la ecuación del slot VMIN de la info del riel {rail} (no es el VMIN evaluado)',
 'field.fixed': 'Voltaje fijo {role} de {rail} (experimental)',
 'field.fixed_advanced': 'Voltaje fijo {role} de {rail} (avanzado, experimental)',
 'field.nvvdd_rel_alt_follow_ov': ('REL y ALT de NVVDD siguen a OV (límite de voltaje plano estilo XOC; avanzado, '
                                   'experimental)'),
 'field.power_default_w': 'Potencia por defecto al arrancar (experimental)',
 'field.input_current_rated_ma': 'Límite de corriente de entrada de 12 V, nominal (experimental)',
 'field.input_current_max_ma': 'Techo de corriente de entrada de 12 V (experimental)',
 'field.input_threshold_rated_ma': 'Umbral de corriente de entrada de 12 V, nominal (avanzado, experimental)',
 'field.input_threshold_max_ma': 'Techo del umbral de corriente de entrada de 12 V (avanzado, experimental)',
 'field.gpc_offset_max_mhz': 'Techo de offset del núcleo (GPC) (experimental)',
 'field.gpc_offset_min_mhz': 'Piso de offset del núcleo (GPC) (experimental)',
 'field.memory_offset_min_mhz': 'Piso de offset de memoria (experimental)',
 'field.dram_min_table_mhz': 'Piso de offset de memoria (tabla, experimental)',
 'field.input_current_policy7_limit_ma': 'Límite de la política 7 ligado a la entrada de 12 V (experimental)',
 'field.clock_domain_max': 'Techo de offset de {domain} (experimental)',
 'field.clock_domain_min': 'Piso de offset de {domain} (experimental)',
 'reason.generic_ocp': 'La política OCP genérica no está validada; los techos conocidos se '
                       'muestran por riel de salida.',
 'reason.linked_input': 'La política 7 guarda un límite ligado a la política de entrada de 12 V; puede '
                        'limitar la corriente de entrada. Sin prueba en hardware; no es una corriente segura '
                        'garantizada.',
 'reason.generic_input': 'Marcador genérico de corriente de entrada; la política revisada de '
                         'entrada de 12 V se muestra en campos separados en mA.',
 'reason.policy': 'Las unidades y el significado de esta política no están validados.',
 'reason.ocp': 'La ubicación del campo OCP no está validada.',
 'reason.memory_conversion': 'El dominio de memoria y su conversión a MHz no están validados.',
 'reason.memory': 'Las unidades de memoria y esta variante de edición no están validadas.',
 'reason.single_rail': 'Este formato de un solo riel expone únicamente NVVDD.',
 'reason.rail': 'La identidad del riel y su variante de edición no están validadas.',
 'reason.clock': 'El dominio de reloj y su conversión a MHz no están validados.',
 'reason.max_temp_disabled': ('La política térmica que guarda este límite está desactivada en esta ROM (como en las '
                               'ROM estilo XOC), así que el valor no se aplica. El editor no la activa.'),
 'reason.max_temp_unequal': ('Las tres temperaturas guardadas de este límite difieren en esta ROM; el editor solo las '
                             'escribe juntas.'),
 'reason.max_temp_unrecognized': 'Esta entrada de política térmica no tiene el formato de las ROM revisadas.',
 'reason.max_temp_no_policy': ('Esta ROM no indica ninguna política de temperatura máxima de funcionamiento (como '
                               'las ROM estilo XOC), así que no se aplica ninguna. El editor no agrega una.'),
 'reason.max_temp_lower_limit': ('Esta ROM también guarda un límite de temperatura más bajo del mismo tipo, como las '
                                 'ROM de portátil Ampere y Ada, y no se sabe cuál limita primero a la GPU. El editor '
                                 'deja los dos como están guardados.'),
 'reason.factory_offset_fraction': ('El offset de fábrica guardado no es un número entero de MHz, a diferencia de '
                                    'todas las ROM revisadas. El driver lo usa truncado a MHz enteros; el editor lo '
                                    'deja como está guardado.'),
 'reason.factory_unreviewed': ('El registro del overclock de fábrica o la tabla de clocks de esta ROM no tiene el '
                               'formato de las ROM revisadas, así que el editor lo deja como está guardado.'),
 'reason.factory_boost': ('Clock boost nominal del overclock de fábrica. El driver lo escribe en un estado de '
                          'rendimiento al arrancar; el editor lo deja como está guardado.'),
 'reason.depends_on': ('Para cambiar este valor, activa el interruptor "{switch}". Mientras está apagado, se '
                       'mantiene el valor guardado.'),
 'reason.depends_on_stock': ('Para cambiar este valor, deja el interruptor "{switch}" en De fábrica. Mientras está en '
                             'Desactivado, se mantiene el valor guardado.'),
 'reason.fan_channel_off': ('No se usa mientras la cantidad de canales de ventilador sea {count}: la copia guarda el '
                             'ventilador {fan}, pero apagado, y con {fan} canales o más vuelve a encenderse.'),
 'reason.perf_cf_policy': ('La entrada de la política de utilización de esta ROM no tiene el formato de las ROM '
                           'revisadas, así que ni ella ni sus controladores son editables.'),
 'reason.perf_cf_controller': 'Este controlador no tiene el formato de las ROM revisadas.',
 'reason.lpwr_mixed': ('En esta ROM algunas entradas de esta función están activadas y otras no, a diferencia de las '
                       'ROM revisadas.'),
 'reason.lpwr_gr_rg_unrecognized': 'Una entrada del rail gating de GR de esta ROM no guarda el valor revisado.',
 'reason.lpwr_stock_unrecognized': 'Una entrada de esta función en esta ROM no guarda un valor revisado.',
 'reason.lpwr_table_unreviewed': ('Esta función está activada en esta ROM, pero ninguna de las ROM revisadas de esta '
                                  'familia de GPU tiene esta tabla.'),
 'reason.lpwr_time_switch': 'El interruptor de este tiempo de reposo es de solo lectura en esta ROM.',
 'reason.fan_zero_rpm_mixed': ('La parada en reposo está activada en algunas entradas de ventilador de esta ROM '
                               'y desactivada en otras (el bit 2 de su byte de flags difiere), así que ni '
                               'Activado ni Desactivado la describen, y el editor no cambia ninguno.'),
 'reason.fan_zero_rpm_no_block': ('Una entrada de ventilador de esta ROM no guarda valores de parada que el '
                                  'driver acepte (la tercera entrada de la RTX A2000 guarda ceros) y no hay una '
                                  'plantilla revisada, así que la parada en reposo no se puede activar.'),
 'reason.fan_zero_rpm_temps_off': ('La parada en reposo es de solo lectura en esta ROM, así que sus umbrales '
                                   'quedan como están guardados.'),
 'reason.generic': 'Edición no disponible para este campo.',
 'error.INVALID_IMAGE': 'Abre una ROM primero',
 'error.INVALID_CHANGES': 'Prepare una vista previa verificada antes de guardar',
 'error.FIELD_READ_ONLY': 'Este campo es de solo lectura',
 'error.CONFLICTING_FIELDS': 'Elige una sola representación del campo',
 'error.UNKNOWN_FIELD': 'Este campo es desconocido o no está validado',
 'error.INVALID_VALUE': 'Introduce un número finito válido',
 'error.OUT_OF_BOUNDS': 'El valor está fuera del rango permitido o rompe el orden mínimo/por defecto/máximo',
 'error.UNREPRESENTABLE_VALUE': 'El valor no se puede almacenar exactamente en este formato',
 'error.INTEGRITY_FAILED': 'Fallaron los controles de integridad de la ROM',
 'error.SOURCE_OVERWRITE': 'Elige un destino diferente del original',
 'error.SOURCE_CHANGED': 'El original cambió desde que se abrió',
 'error.OUTPUT_EXISTS': 'La copia o el manifiesto ya existe',
 'error.LOADER_OUTPUT_EXISTS': ('Ya existe un archivo -loader con este nombre, quizás de una copia '
                                'anterior: bórralo o elige otro nombre'),
 'error.IO_ERROR': 'No se pudo leer o escribir el archivo',
 'error.INVALID_PATH': 'Elige una ruta local válida',
 'error.UNSUPPORTED_ARCHITECTURE': 'Esta arquitectura sólo permite inspección',
 'error.UNSUPPORTED_FORMAT': 'Este formato sólo permite inspección',
 'error.FAMILY_MISMATCH': ('La otra ROM es de otra familia de GPU o de otro formato; importar requiere una de '
                           'la misma familia'),
 'error.DEPENDENT_FIELD_DISABLED': ('Este valor depende de un interruptor que está apagado; activa el interruptor '
                                    'para cambiarlo'),
 'error.ZERO_RPM_ABOVE_CURVE': ('Con la parada en reposo activada, un umbral superior no puede quedar por encima '
                                'del punto 1 de su curva de ventilador; baja el umbral, con el umbral inferior por '
                                'debajo de él si hace falta, o mantén el punto por encima, en la misma edición'),
 'error.SEPARATE_EDIT_REQUIRED': ('Guarda estos cambios en copias separadas. La cantidad de canales de ventilador '
                                  'va antes que los límites, las curvas o la parada en reposo de los ventiladores, y '
                                  'el ajuste REL/ALT siguen a OV antes que los voltajes. En algunas ROM de RTX 4090 el '
                                  'VMIN y el offset de la curva GPC también se guardan por separado, y lo mismo '
                                  'desactivar la parada en reposo y cambiar sus umbrales en una copia donde la parada '
                                  'escribió valores de parada. Guarda uno y luego abre la copia para cambiar el resto'),
 'cli_usage': 'uso: ',
 'cli_positionals': 'argumentos posicionales',
 'cli_options': 'opciones',
 'cli_help': 'Mostrar esta ayuda y salir'})
