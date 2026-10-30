"""Immutable per-window messages; never consult or mutate process locale."""
from dataclasses import dataclass
from types import MappingProxyType

MESSAGES_EN = MappingProxyType({'window_title': 'NVIDIA VBIOS — File editor',
 'open': 'Open ROM…',
 'app_title': 'NVIDIA VBIOS Editor',
 'no_file': 'No ROM open',
 'welcome': 'Open a ROM to start. Saving always creates a new copy; the original file is never modified.',
 'section.power': 'Power',
 'section.voltage': 'Voltage',
 'section.clocks': 'Clock offsets',
 'section.current': 'Current and protection',
 'section.other': 'Other',
 'section.fans': 'Fans',
 'field.fan_pwm_frequency_hz': 'Fan PWM frequency (experimental)',
 'field.fan_channels': 'Fan channels (experimental)',
 'field.fan_zero_rpm': 'Fan zero RPM (advanced, experimental)',
 'reason.fan_layout': "This table stores no other fan channel layout, or a stored channel's maximums sit below the "
                       'extra fan curves.',
 'field.fan_min_rpm': 'Fan {fan} minimum speed (experimental)',
 'field.fan_max_rpm': 'Fan {fan} maximum speed (experimental)',
 'field.fan_min_pct': 'Fan {fan} minimum level (advanced, experimental)',
 'field.fan_max_pct': 'Fan {fan} maximum level (advanced, experimental)',
 'field.fan_curve_temp_c': 'Fan {fan} curve point {point} temperature (experimental)',
 'field.fan_curve_rpm': 'Fan {fan} curve point {point} speed (experimental)',
 'field.fan_curve_pct': 'Fan {fan} curve point {point} level (advanced, experimental)',
 'field.fan_extra_curve_temp_c': 'Extra fan curve {curve} point {point} temperature (experimental)',
 'field.fan_extra_curve_rpm': 'Extra fan curve {curve} point {point} speed (experimental)',
 'field.fan_extra_curve_pct': 'Extra fan curve {curve} point {point} level (advanced, experimental)',
 'field.fan_zero_rpm_low_temp_c': 'Fan {fan} zero RPM lower threshold (advanced, experimental)',
 'field.fan_zero_rpm_high_temp_c': 'Fan {fan} zero RPM upper threshold (advanced, experimental)',
 'field.fan_extra_zero_rpm_low_temp_c': 'Extra fan curve {curve} zero RPM lower threshold (advanced, experimental)',
 'field.fan_extra_zero_rpm_high_temp_c': 'Extra fan curve {curve} zero RPM upper threshold (advanced, experimental)',
 'field.memory_point_follows_offset': 'Memory clock {mhz} MHz follows the memory offset (advanced, experimental)',
 'field.gpc_curve_offset_mhz': 'GPC curve offset (advanced, experimental)',
 'field.factory_gpc_offset_mhz': 'Factory GPC offset (vendor overclock, experimental)',
 'field.factory_memory_offset_mhz': 'Factory memory offset (vendor overclock, experimental)',
 'field.factory_rated_boost_mhz': 'Factory rated boost clock',
 'field.max_operating_temp_c': 'Max operating temperature (experimental)',
 'section.advanced': 'Advanced: performance controllers and idle power',
 'section.advanced_note': ('Blackwell, Ada, Ampere and Turing. Experimental and not tested on hardware. The '
                           'utilization policy and its controllers decide how the driver raises and lowers the GPC, '
                           'memory (DRAM) and video (VID) clocks with load. It is not proven that the driver uses '
                           'this table on any of these cards. A lower target raises the clocks sooner, with more power '
                           'and heat. The idle power switches leave a power-saving feature as shipped (Stock) or turn '
                           'it off (Off), and they are expected to act only at idle or light load. Idle power saving '
                           'lists only the features the ROM ships turned on. Off uses a little more power at idle, '
                           'and very short idle times can cause stutter or, rarely, a black screen at idle. A value '
                           'that depends on a switch is greyed out while that switch is off. This section is shown '
                           'with or without Show advanced XOC-style fields, and Import from ROM… never copies it.'),
 'section.advanced_perf': 'Clock controllers',
 'section.advanced_lpwr': 'Idle power saving',
 'field.perf_cf_util_policy': 'Utilization clock policy (experimental)',
 'field.perf_cf_target_pct': '{domain} utilization target (experimental)',
 'field.perf_cf_jump_pct': '{domain} jump threshold (experimental)',
 'field.perf_cf_hysteresis_down': '{domain} clock-down hysteresis (samples, experimental)',
 'field.perf_cf_hysteresis_up': '{domain} clock-up hysteresis (samples, experimental)',
 'field.lpwr_gr_power_gating': 'GR power gating (experimental)',
 'field.lpwr_mscg': 'Memory system clock gating, MSCG (experimental)',
 'field.lpwr_nvdec_gating': 'NVDEC power gating (experimental)',
 'field.lpwr_nvenc_gating': 'NVENC power gating (experimental)',
 'field.lpwr_ofa_gating': 'OFA power gating (experimental)',
 'field.lpwr_nvjpg_gating': 'NVJPG power gating (experimental)',
 'field.lpwr_difr': 'DIFR idle display power saving (experimental)',
 'field.lpwr_difr_dfpr_idle_ms': 'DIFR DFPR idle time (experimental)',
 'field.lpwr_difr_sw_asr_idle_us': 'DIFR SW-ASR idle time (experimental)',
 'field.lpwr_difr_cg_idle_us': 'DIFR clock gating idle time (experimental)',
 'field.lpwr_gr_rail_gating': 'GR rail gating (experimental)',
 'field.lpwr_gr_rail_gating_idle_us': 'GR rail gating idle time (10 µs steps, experimental)',
 'section.readonly': 'Read-only fields ({count})',
 'section.voltage_note': ('REL and OV are equation ceilings; a fixed REL or ALT voltage sets the value of a constant '
                          'equation, and a fixed REL stays at or below ALT: to raise it further, raise ALT in the same '
                          'edit. VMIN edits a stored value; chained equations may change the effective minimum.'),
 'section.unsupported': 'Some fields in this section are not shown: this VBIOS uses a layout the editor does not '
                        'support yet.',
 'badge.experimental': 'experimental',
 'memory.title': 'Memory (read-only)',
 'memory.note': ("Decoded from the ROM's tables. 'Inferred' names come from byte patterns, not NVIDIA documentation. "
                 'Which configuration your card uses is set by the board.'),
 'memory.loading': 'Reading the memory tables…',
 'memory.unrecognized': 'Memory tables not recognized: {reason}',
 'memory.section_unrecognized': '{section}: not recognized ({reason})',
 'memory.configurations': 'Memory configurations',
 'memory.configuration': 'Strap {strap} → column {column} · {vendor} · type {type}',
 'memory.type_guess': '{code} (probably {name})',
 'memory.vendor_code': 'vendor {code}',
 'memory.timings': 'Timing entries, in controller cycles',
 'memory.stock_bands': 'Bands holding the stock memory clocks; Raw bytes lists every band.',
 'memory.all_bands': 'The stock memory clocks are not read for this ROM; every band is shown.',
 'memory.column': 'Strap {straps} → column {column} · {vendor}',
 'memory.no_entries': 'No timing entry in these bands.',
 'memory.outside_table': 'Not in the memory clock table (columns 0–{last}).',
 'memory.band': 'Band (MHz)',
 'memory.entry': 'Entry',
 'memory.stock': 'stock {points}',
 'memory.confidence.inferred': 'inferred',
 'memory.confidence.probable': 'probable',
 'memory.confidence.tentative': 'tentative',
 'memory.profile': 'Board memory-training profile (object 0x89): tag {tag} · fingerprint {fingerprint}',
 'memory.profile_note': ('Undecoded per-board boot data, probably memory-interface training. A difference does not '
                         'mean one BIOS is faster. It only takes effect by flashing the whole ROM; the override cannot '
                         'apply it.'),
 'memory.profile_unrecognized': 'Board memory-training profile not recognized: {reason}',
 'memory.raw': 'Raw bytes',
 'memory.compare': 'Compare with another ROM…',
 'memory.compare_dialog': 'Choose a ROM to compare',
 'memory.comparing': 'Comparing the memory tables…',
 'memory.compared': 'Compared with {file}: identical or different only, never better or worse.',
 'memory.compare_failed': 'Comparison failed: {message}',
 'memory.section.configurations': 'Memory configurations',
 'memory.section.bands': 'Memory clock bands',
 'memory.section.timings': 'Timing entries',
 'memory.section.tables': 'Memory tables (SHA-256)',
 'memory.section.board_profile': 'Board memory-training profile',
 'memory.identical': '{section}: identical',
 'memory.differs': '{section}: differs',
 'memory.differs_entries': '{section}: differs (entries: {count})',
 'memory.differs_tables': '{section}: differs ({tables})',
 'memory.differs_fields': '{section}: differs, meaning unknown (fields: {count})',
 'memory.differs_unknown': '{section}: differs, meaning unknown',
 'memory.unavailable': '{section}: not recognized in one or both ROMs',
 'memory.table.memory_configurations': 'memory configurations',
 'memory.table.memory_clock_bands': 'memory clock bands',
 'memory.table.timings': 'timings',
 'memory.table.training': 'training',
 'memory.table.training_patterns': 'training patterns',
 'memory.table.memory_data': 'memory data',
 'import': 'Import from ROM…',
 'import.dialog': 'Choose a ROM to import values from',
 'import.title': 'Import from another ROM',
 'import.from': 'Copy values from {file} into the open ROM. Sections:',
 'import.opt_in': 'Also import the advanced XOC-style fields',
 'import.note': ('Values are copied as stored numbers, not adapted to this board: fan speeds, power and current '
                 "limits and voltage limits from another board can exceed what this board's fans, power connectors, "
                 'power stages or GPU are rated for, and a clock offset from another board may not be stable on '
                 'this one. They become pending changes: check them in the change list before saving.'),
 'import.accept': 'Import',
 'import.close': 'Close',
 'import.reading': 'Reading the other ROM…',
 'import.applied': 'Imported from {file} as pending changes: {count}.',
 'import.nothing': 'Nothing imported from {file}.',
 'import.different_device': ('The other ROM is for another product of this family (PCI {donor}; this ROM: PCI '
                             '{target}). Its values were set for that product.'),
 'import.unchanged': 'Already equal in both ROMs: {count}.',
 'import.skipped': 'Not imported: {count}.',
 'import.opt_in_hint': ('Some fields go with advanced fields that differ; import again with the advanced fields '
                        'to take them.'),
 'import.stale': 'The open ROM changed; nothing was imported.',
 'import.failed': 'Import failed: {message}',
 'import.reason.absent_in_donor': 'not in the other ROM',
 'import.reason.absent_in_target': 'not in this ROM',
 'import.reason.read_only_in_donor': 'read-only in the other ROM',
 'import.reason.per_chip_in_donor': 'set per chip in the other ROM, not stored as a number',
 'import.reason.read_only_in_target': 'read-only in this ROM',
 'import.reason.read_only': 'read-only in both ROMs',
 'import.reason.opt_in': 'advanced field, not included',
 'import.reason.board_specific': "this board's fan count; never copied",
 'import.reason.product_specific': "this product's own temperature limit; never copied",
 'import.reason.different_meaning': ('another quantity in the other ROM (other units, memory level, power layout or '
                                     'voltage equation)'),
 'import.reason.held_back': 'goes with related fields that are not imported: {fields}',
 'import.reason.held_back_many': 'go with related fields that are not imported: {fields}',
 'import.more': '{fields} and {count} more',
 'import.reason.out_of_bounds': "outside this ROM's range ({minimum} to {maximum} {units})",
 'import.reason.refused': 'refused by the editor: {message} [{code}]',
 'changes_heading': 'Changes',
 'live_none': 'No changes yet. Edit a value and the preview updates here.',
 'live_checking': 'Checking changes…',
 'live_ok': 'Changes verified: {count} · copy integrity OK · {bytes} bytes',
 'live_same': 'No differences from the original.',
 'change.not_used': 'not used',
 'unexpected': 'Unexpected error in the editor window, please report it: {message} [{code}]',
 'not_a_number': 'Enter a number',
 'order_hint': 'Breaks the floor ≤ rated ≤ ceiling order of its group',
 'order_hint_voltage': 'Breaks the VMIN < REL floor ≤ REL ≤ ALT order; change these values together',
 'order_hint_fan': 'Fan limits and curve points must stay within their allowed ranges; change related values together',
 'zero_rpm_hint': ('With zero RPM on, the upper threshold may not be above point 1 of the same fan curve; '
                   'change them together'),
 'zero_rpm_lower_hint': ('This lower threshold is at or above point 1 of its fan curve; set it below the upper '
                         'threshold in the same edit'),
 'zero_rpm_channels_hint': ('A larger count turns on a stored fan whose zero RPM upper threshold is above point 1 of '
                            'its curve. Turn zero RPM off and save; on that copy change the count and save; then '
                            'turn zero RPM on with that threshold lowered'),
 'zero_rpm_channels_locked_hint': ('A larger count turns on a stored fan whose zero RPM upper threshold is above point '
                                   '1 of its curve, and zero RPM is read-only in this ROM, so the count cannot be '
                                   'raised'),
 'fan_curve_min_hint': ("This fan's curve has points below this minimum (down to {value} {units}). "
                        'Raise those points in the same edit: {points}.'),
 'fan_curve_max_hint': ('Fan curves have points above this maximum (up to {value} {units}). '
                        'Lower those points in the same edit: {points}.'),
 'fan_curve_readonly_hint': ('Some blocking curve points are read-only in this image: {points}. '
                             'Keep the fan limit within their range.'),
 'out_of_range': 'Value out of range',
 'range_min': 'Minimum: {minimum} {units}',
 'fix_fields': 'Fix the fields marked in red.',
 'live_failure': '{message} [{code}]',
 'windows_short': 'Afterburner: {value} MHz',
 'range_hint': 'Allowed: {minimum} to {maximum} {units}',
 'windows_equivalent': 'Windows (MSI Afterburner): {value} MHz',
 'linux_short': 'nvidia-settings: {value} MHz',
 'linux_equivalent': 'As in MSI Afterburner · Linux (nvidia-settings): {value} MHz',
 'factory_offset_on': 'turns on a factory offset that is off in this ROM (not tested on such ROMs)',
 'copy_note': 'Saving creates a new ROM + JSON manifest. Not validated on hardware.',
 'license_note': ('NVIDIA VBIOS Vix Editor {version} · Copyright (C) 2026 panchovix · '
                  'Free software under the GNU GPL v3 or later, with NO WARRANTY. License and source code: '
                  'https://github.com/Panchovix/nvidia-vbios-vix-editor'),
 'save': 'Save Copy…',
 'heading': 'File editor · Saving creates a copy',
 'open_prompt': 'Open a ROM to inspect its identity and format.',
 'rel_notice': 'REL: equation ceiling, not effective voltage.',
 'fields_heading': 'Fields · values and units',
 'preview_heading': 'Preview · original → copy',
 'no_changes': 'No staged changes.',
 'stage': 'Stage and verify',
 'reset': 'Reset changes',
 'ready_help': 'Ready. Ctrl+O open · Ctrl+S save copy · Ctrl+R reset · the preview updates as you type',
 'saved': 'Copy saved: {output}\nManifest: {manifest}',
 'saved_loader': 'For the VBIOS loaders, load this file instead of the copy: {output}',
 'saved_loader_failed': 'No file for the VBIOS loaders: {reason}',
 'saved_loader_other_failed': 'The other file for the VBIOS loaders was not saved: {reason}',
 'saved_loader_alternative': ('If the loaded file does not apply the edit, try this one instead '
                              '(experimental): {output}'),
 'verified': 'Preview verified. Save Copy creates ROM + JSON manifest without overwriting files.',
 'loaded': 'ROM loaded. Offline editing; this copy has not been validated on hardware.',
 'loading': 'Reading and inspecting ROM…',
 'all_files': 'All files',
 'open_dialog': 'Open ROM for offline editing',
 'open_accept': 'Open',
 'save_accept': 'Save Copy',
 'cancel': 'Cancel',
 'file_options': 'File options',
 'theme': 'Theme',
 'theme.auto': 'System',
 'theme.light': 'Light',
 'theme.dark': 'Dark',
 'open_builtin': 'Open with built-in picker…',
 'save_builtin': 'Save with built-in picker…',
 'open_path': 'Open by path…',
 'save_path': 'Save copy by path…',
 'path_label': 'File path',
 'path_hint': 'Type a path on the computer running the editor, also over SSH. Absolute paths and ~/ are supported.',
 'path_error': 'Enter a local filesystem path, not a URL.',
 'cli_theme': 'Theme: auto follows the Windows app mode (elsewhere, the desktop); light or dark',
 'cli_file_dialog': 'File picker: auto uses the built-in picker over SSH; system uses the desktop dialog',
 'local_file': 'Choose a local file.',
 'save_dialog': 'Save new copy + JSON manifest',
 'stale_dialog': 'The ROM or preview changed. Choose the destination again.',
 'preview_first': 'Stage the current preview before saving.',
 'new_destination': 'Choose a new local destination.',
 'saving': 'Saving copy and manifest without overwriting…',
 'dirty': 'Values changed: Stage and verify to update the preview.',
 'staging': 'Building and verifying preview…',
 'reset_done': 'Changes reset to the immutable original.',
 'unknown': 'Unknown',
 'flag_on': 'On',
 'flag_off': 'Off',
 'flag_mixed': 'Mixed (on for some fan entries)',
 'flag_stock': 'Stock',
 'unknown_version': 'unknown',
 'unrecognized': 'unrecognized',
 'format': 'Format: {format}',
 'integrity': 'Integrity: {summary}',
 'integrity_verified': 'Verified',
 'integrity_failed': 'FAILED',
 'integrity_unknown': 'Unknown (partial inspection only)',
 'no_fields': 'This format exposes no validated editable fields.',
 'readonly': 'Read-only',
 'original': 'Original: {value} {units}',
 'factory': 'Rated default in this ROM: {value} {units}.',
 'static_ceiling': 'Static ceiling; it does not represent effective voltage.',
 'copy_integrity': 'Copy integrity: verified',
 'not_hardware_tested': 'New copy validated on hardware: no',
 'unchanged_preview': 'No staged changes. Stage and verify also allows an exact copy of an '
                      'editable format.',
 'table_alias': 'Same field in table units (the scale Windows tools show); read-only.',
 'field_alias': 'Alias of the main control; read-only.',
 'failure': '{message} [{code}]',
 'failure_generic': 'Operation failed',
 'cli_description': 'Offline NVIDIA VBIOS graphical editor',
 'cli_rom': 'Optional local ROM',
 'cli_language': 'Interface language (default: en; independent of host locale)',
 'missing_gtk': 'GUI requires GTK4 and Python PyGObject (gi): {error}',
 'field.power_min_w': 'Board power floor',
 'field.power_max_w': 'Board power ceiling',
 'field.nvvdd_rel_max_mv': 'NVVDD REL ceiling',
 'field.msvdd_rel_max_mv': 'MSVDD REL ceiling',
 'field.dram_max_table_mhz': 'Memory offset ceiling (table)',
 'field.memory_offset_max_mhz': 'Memory offset ceiling',
 'field.current_limit_a': 'Input current limit',
 'field.ocp_limit_a': 'Overcurrent protection (OCP)',
 'field.output_ocp': '{rail} output OCP current ceiling',
 'field.output_ocp_rated': '{rail} output OCP current limit, rated (experimental)',
 'field.output_ocp_advanced': '{rail} output current limit ceiling (advanced, experimental)',
 'field.output_ocp_rated_advanced': '{rail} output current limit, rated (advanced, experimental)',
 'field.slot_power_rated_w': 'PCIe slot power limit, rated (experimental)',
 'field.slot_power_max_w': 'PCIe slot power ceiling (experimental)',
 'field.board_fixed_rated_w': 'Fixed board policies 2/7 rated power (advanced, XOC-style, experimental)',
 'field.notebook_base_tgp_w': 'Notebook base TGP (experimental)',
 'field.slot_current_threshold_rated_ma': 'PCIe slot current threshold, rated (advanced, experimental)',
 'field.slot_current_threshold_max_ma': 'PCIe slot current threshold ceiling (advanced, experimental)',
 'field.nvvdd_power_threshold_rated_w': 'NVVDD output power threshold, rated (advanced, experimental)',
 'field.nvvdd_power_threshold_max_w': 'NVVDD output power threshold ceiling (advanced, experimental)',
 'field.connector_power_max': 'Connector power channel {connector} ceiling (experimental)',
 'field.connector_power_rated': 'Connector power channel {connector} limit, rated (experimental)',
 'field.connector_power_max_advanced': 'Connector power channel {connector} ceiling (advanced, experimental)',
 'field.connector_power_rated_advanced': 'Connector power channel {connector} limit, rated (advanced, experimental)',
 'connector_input.rating': 'This limit caps the power drawn through the auxiliary power connector. The ROM does not '
                           'store the connector type: a PCIe 8-pin connector is rated for 150 W, a 12V-2x6 (16-pin) '
                           'cable for the level its sense pins report. Going past what the connector and its cable are '
                           'rated for puts the cable, the connector and the power supply at risk. That is your call.',
 'connector_input.limits': 'The board power limit and, where the board stores them, the PCIe slot limit and the 12 V '
                           'input current limit or threshold still apply and may limit next, so raise them together '
                           'where needed. Not tested on hardware.',
 'connector_input.threshold': 'Row {row} also holds a {amps} A current threshold on this connector input (about '
                              '{watts} W at 12 V). It cannot be edited here and may hold the connector first.',
 'field.connector_sum_power_max_w': 'Connector power sum ceiling (experimental)',
 'field.connector_sum_power_rated_w': 'Connector power sum limit, rated (experimental)',
 'summed_cap.connectors': 'Row {row} also caps the sum of connector power channels {channels} at {rated} {units} '
                          'rated / {maximum} {units} maximum and may bind first: raising this limit alone may have '
                          'no effect.',
 'summed_cap.channels': 'Row {row} also caps the sum of power channels {channels} at {rated} {units} rated / '
                        '{maximum} {units} maximum and may bind first: raising this limit alone may have no effect.',
 'summed_cap.raise': 'Raise the connector power sum limits too.',
 'sense_profiles.levels': 'This ROM sets its power limits from the 16-pin cable sense pins. This value applies at the '
                          'top level, most likely a {watts} W cable (inferred, not tested). Lower levels keep their '
                          'own limits.',
 'sense_profiles.past_top': 'Going past {watts} W is more than that cable is rated for. That is your call.',
 'notebook.ceiling': 'On a laptop, Dynamic Boost requests the running power limit at runtime and this ceiling only '
                     'caps it. Monitoring tools show this stored ceiling, so raising it alone usually does not raise '
                     'the running limit. On one RTX 5090 Laptop GPU the running limit went from 175 to about 185 W '
                     'with the ceiling, the boot default and Notebook base TGP (under Show advanced XOC-style fields, '
                     'where the ROM has it) raised together to 190, 110 and 165 W. The ceiling alone, or with only '
                     'one of the other two, left it at 175 W. To raise the running limit, raise the three together. '
                     "Other laptops are not tested, and the laptop's VRM, cooling and power adapter were sized for "
                     'the stock limit.',
 'notebook.default': 'To raise the running limit on a laptop, raise this boot default together with the ceiling and '
                     'Notebook base TGP (under Show advanced XOC-style fields, where the ROM has it), by as many '
                     'watts as you raise the base TGP. On one RTX 5090 Laptop GPU, 110 W here (from 95 W) with the '
                     'base TGP raised from 150 to 165 W and a 190 W ceiling took the running limit from 175 to about '
                     '185 W. A raised boot default and ceiling without the base TGP left it at 175 W.',
 'notebook.base_tgp': 'Tested on one RTX 5090 Laptop GPU, where it behaved like the base TGP that Dynamic Boost adds '
                      'its boost to and raised the running limit only together with the ceiling and the boot '
                      'default. With 165 W here (from 150 W), a 190 W ceiling and a 110 W boot default (from 95 W) '
                      'the running limit went from 175 to about 185 W, while the same base TGP and ceiling with the '
                      'stock boot default left it at 175 W. To raise the running limit, raise the three together, '
                      'the boot default by as many watts as you raise this value. The ceiling still caps the result. '
                      'When you change it, it has to stay between the boot default and the ceiling. To go above the '
                      'ceiling, raise the ceiling with it in the same edit. A copy saved with the ceiling below it or '
                      'the boot default above it does not show this field but keeps its stored value, and the field '
                      "comes back once they are moved back. Other laptops are not tested. The laptop's VRM, cooling "
                      'and power adapter were sized for the stock limit, and a battery that drains while plugged in '
                      'under full CPU and GPU load means the adapter falls short.',
 'lpwr.enabled_entries': ('This product is not among the reviewed ones, so this switch covers the entries this '
                          'ROM enables. A copy saved with Off no longer shows the switch, since an entry shipped '
                          'disabled looks the same as one turned off: keep the original ROM to go back to Stock.'),
 'output_ocp.ampere': ('Not tested on hardware. A power cap below the board power ceiling may come from this current '
                       'limit, though it is not known whether the GPU enforces it. It likely protects the core VRM, '
                       'which was sized for the stock value. Raising it is your call, and small steps are safer.'),
 'sense_profiles.input_current': 'The 12 V input current threshold (rated {amps} A, about {watts} W at 12 V) may '
                                 'limit first. Raise it too, under Show advanced XOC-style fields.',
 'vmin_clone.memory': 'On this ROM the memory clock voltage floor keeps its stock value. A lower VMIN shows only while '
                      'the memory runs at its lowest clock ({mhz} MHz, single-monitor idle). A higher VMIN shows at '
                      'every memory clock only above {floor} mV (stock VMIN + {constant} mV). Up to that it also '
                      'shows only at that lowest clock.',
 'vmin_tree.tree': 'The stock VMIN of this ROM is set per chip from fused values and changes with temperature, so '
                   'the ROM stores no single value. A value here fixes VMIN at that value for every chip and '
                   'temperature.',
 'vmin_tree.step': 'Blackwell drivers round VMIN up to a 5 mV step.',
 'vmin_tree.per_chip': 'The stock base value of this VMIN is set per chip from a fused value ({low} to {high} mV), so '
                       'the ROM stores no single value. A value here fixes that base value. The terms chained after '
                       'it still add their part for each chip and temperature.',
 'vmin_tree.risk': 'Not tested on hardware. A value below the stock VMIN of this chip can make idle and light-load '
                   'states unstable, and a higher one raises the idle voltage and power. The driver might also keep '
                   'the stock VMIN. Removing the override brings the card back, and turning "Fixed VMIN" off on a '
                   'saved copy writes the stock bytes back.',
 'vmin_tree.switch': 'On while the value above fixes VMIN. Off writes the stock bytes back, so VMIN follows the chip '
                     'again. Save this change and a new VMIN value in separate copies.',
 'reason.vmin_fixed_stock': 'Off: VMIN is the stock value of each chip. Type a value in the minimum voltage row to fix '
                            'it.',
 'original_per_chip': 'Original: per chip (not stored in the ROM)',
 'per_chip_value': 'per chip',
 'vmin_clone.risk': 'Not tested on hardware. A VMIN other than the stock value adds a VFE equation to the ROM, and '
                    'no Ada card has run an equation added by the editor yet. The override might not load or the '
                    'driver might fail to start. Removing the override brings the card back.',
 'fan_stop.template': ('This blower board stores no fan-stop values. On also writes the values NVIDIA stores on '
                       'the {donor} ROM (zero RPM thresholds {pairs} °C); Off on such a copy writes the stock bytes '
                       'back.'),
 'fan_stop.blower': ('No blower card ships with fan stop on. A stopped blower most likely moves no air through the '
                     'card, memory and power stages included, until the card passes the upper threshold. Restarting '
                     'a blower from 0 RPM is untested, and dense multi-GPU builds can see heat soak and stop/start '
                     'cycling. Not tested on hardware on this board.'),
 'fan_stop.off': ('This ROM ships with zero RPM off. If the card has a blower fan, a stopped fan most likely moves no '
                  'air through the card, memory and power stages included, until it passes the upper threshold. '
                  'Restarting a blower from 0 RPM is untested, and dense multi-GPU builds can see heat soak and '
                  'stop/start cycling.'),
 'fan_stop.bit4': ('With zero RPM on, the fan channel entries of this ROM hold bits 1 and 2 with bit 4 clear, a flag '
                   'form no shipped ROM runs zero RPM with; whether the fans stop is untested.'),
 'fan_stop.flat': ('"{field}" equals the upper threshold ({value} °C): with zero RPM on there is no hysteresis, so '
                   'the fans may stop and start often around that temperature. Set it a few degrees lower.'),
 'fan_stop.copy': ('This ROM also keeps a copy of the fan {fan} settings, most likely unused; the editor changes both '
                   'the same way.'),
 'fan_stop.untested': 'Not tested on hardware on Ada or Ampere cards.',
 'fan_stop.manual': 'A fan tool that holds manual control keeps the fans running.',
 'field.connector_current_threshold_rated': 'Connector channel {connector} current threshold, rated (advanced, '
                                            'experimental)',
 'field.connector_current_threshold_max': 'Connector channel {connector} current threshold ceiling (advanced, '
                                          'experimental)',
 'show_advanced': 'Show advanced XOC-style fields',
 'shunt_multiplier': 'Shunt multiplier (x)',
 'shunt_help': 'Display only: the VBIOS keeps the values in the fields. Assumes the same multiplier on every '
               '12\u00a0V input shunt (connector and PCIe slot). NVVDD/MSVDD output limits are measured by the VRM, '
               'not by the shunts, and are not scaled.',
 'shunt_real': 'About {value} {units} real with a x{factor} shunt',
 'field.equation': '{rail} {role} equation ceiling',
 'field.rel_floor': '{rail} REL floor',
 'field.vmin': '{rail} minimum voltage (VMIN, experimental)',
 'field.vmin_fixed': '{rail} fixed VMIN (experimental)',
 'field.vmin_slot': '{rail} rail INFO VMIN-slot equation ceiling (not the evaluated VMIN)',
 'field.fixed': '{rail} {role} fixed voltage (experimental)',
 'field.fixed_advanced': '{rail} {role} fixed voltage (advanced, experimental)',
 'field.nvvdd_rel_alt_follow_ov': 'NVVDD REL and ALT follow OV (XOC-style flat voltage limit; advanced, experimental)',
 'field.nvvdd_rel_alt_follow_ov_mv': 'NVVDD flat voltage (REL = ALT = OV)',
 'field.power_default_w': 'Boot default board power (experimental)',
 'field.input_current_rated_ma': '12 V input current limit, rated (experimental)',
 'field.input_current_max_ma': '12 V input current ceiling (experimental)',
 'field.input_threshold_rated_ma': '12 V input current threshold, rated (advanced, experimental)',
 'field.input_threshold_max_ma': '12 V input current threshold ceiling (advanced, experimental)',
 'field.gpc_offset_max_mhz': 'Core (GPC) offset ceiling (experimental)',
 'field.gpc_offset_min_mhz': 'Core (GPC) offset floor (experimental)',
 'field.memory_offset_min_mhz': 'Memory offset floor (experimental)',
 'field.dram_min_table_mhz': 'Memory offset floor (table, experimental)',
 'field.input_current_policy7_limit_ma': 'Policy 7 limit linked to 12 V input (experimental)',
 'field.clock_domain_max': '{domain} offset ceiling (experimental)',
 'field.clock_domain_min': '{domain} offset floor (experimental)',
 'reason.generic_ocp': 'Generic OCP policy is unvalidated; known ceilings are shown per output '
                       'rail.',
 'reason.linked_input': 'Policy 7 stores a limit linked to the 12 V input policy; it may cap the input '
                        'current. Not tested on hardware; not a hardware-safe current rating.',
 'reason.generic_input': 'Generic input-current placeholder; the reviewed 12 V input policy is '
                         'shown as separate mA fields.',
 'reason.policy': 'The units and meaning of this policy are unvalidated.',
 'reason.ocp': 'The OCP field location is unvalidated.',
 'reason.memory_conversion': 'The memory domain and its MHz conversion are unvalidated.',
 'reason.memory': 'Memory units and this editing variant are unvalidated.',
 'reason.single_rail': 'This single-rail format exposes only NVVDD.',
 'reason.rail': 'Rail identity and its editing variant are unvalidated.',
 'reason.clock': 'The clock domain and its MHz conversion are unvalidated.',
 'reason.max_temp_disabled': ('The thermal policy holding this limit is disabled in this ROM (as on XOC-style '
                               'ROMs), so the value is not applied. The editor does not enable it.'),
 'reason.max_temp_unequal': ('The three stored temperatures of this limit differ in this ROM; the editor only writes '
                             'them together.'),
 'reason.max_temp_unrecognized': 'This thermal policy entry does not have the layout of the reviewed ROMs.',
 'reason.max_temp_no_policy': ('This ROM names no max operating temperature policy (as on XOC-style ROMs), so none '
                               'is applied. The editor does not add one.'),
 'reason.max_temp_lower_limit': ('This ROM also stores a lower temperature limit of the same kind, as Ampere and '
                                 'Ada laptop ROMs do, and it is not known which one limits the GPU first. The editor '
                                 'keeps both as stored.'),
 'reason.factory_offset_fraction': ('The stored factory offset is not a whole number of MHz, unlike every reviewed '
                                    'ROM. The driver uses it truncated to whole MHz; the editor keeps it as stored.'),
 'reason.factory_unreviewed': ('The factory overclock record or the clock table of this ROM does not have the layout '
                               'of the reviewed ROMs, so the editor keeps it as stored.'),
 'reason.factory_boost': ('Rated boost clock of the factory overclock. The driver writes it into a performance state '
                          'at boot; the editor keeps it as stored.'),
 'reason.depends_on': 'Turn on "{switch}" to change this value. While it is off, the stored value is kept.',
 'reason.depends_on_stock': 'Set "{switch}" to Stock to change this value. While it is Off, the stored value is kept.',
 'reason.fan_channel_off': ('Not used while the fan channel count is {count}: the copy keeps fan {fan} stored but '
                             'off, and a count of {fan} or more turns it on again.'),
 'reason.perf_cf_policy': ('The utilization policy entry of this ROM does not have the layout of the reviewed ROMs, '
                           'so neither it nor its controllers are editable.'),
 'reason.perf_cf_controller': 'This controller does not have the layout of the reviewed ROMs.',
 'reason.lpwr_mixed': ('Some entries of this feature are enabled and others are not in this ROM, unlike the reviewed '
                       'ROMs.'),
 'reason.lpwr_gr_rg_unrecognized': 'A GR rail gating entry of this ROM does not store the reviewed value.',
 'reason.lpwr_stock_unrecognized': 'An entry of this feature in this ROM does not store a reviewed value.',
 'reason.lpwr_table_unreviewed': ('This feature is enabled in this ROM, but none of the reviewed ROMs of this GPU '
                                  'family have this table.'),
 'reason.lpwr_time_switch': 'The switch of this idle time is read-only in this ROM.',
 'reason.fan_zero_rpm_mixed': ('Zero RPM is on for some fan entries of this ROM and off for others (bit 2 of '
                               'their flag byte differs), so neither On nor Off describes it, and the editor '
                               'changes neither.'),
 'reason.fan_zero_rpm_no_block': ('A fan entry of this ROM stores no fan-stop values the driver accepts (the '
                                  'third entry of the RTX A2000 stores zeros) and no reviewed template applies, '
                                  'so zero RPM cannot be turned on.'),
 'reason.fan_zero_rpm_temps_off': 'Zero RPM is read-only in this ROM, so its thresholds stay as stored.',
 'reason.fan_policy_copy': ('A disabled fan channel of this ROM keeps a copy of another fan\'s settings, most '
                            'likely unused, which the editor changes together with them; setting the channel count '
                            'would switch that copy off or turn its channel on, so the count stays as stored.'),
 'reason.fan_low_extra': ('This ROM stores an extra fan curve, used for every fan, in the entry of a second fan '
                          'channel that it disables; setting the channel count would switch that curve off or turn '
                          'its channel on, so the count stays as stored.'),
 'reason.follow_ov_clamp': ('REL and ALT follow OV in this ROM, so REL, ALT and OV share one voltage: set it in '
                            '"NVVDD flat voltage (REL = ALT = OV)", shown with the advanced fields.'),
 'reason.follow_ov_rel_clamp': ('REL follows OV in this ROM, so REL and OV share one voltage: set it in "NVVDD flat '
                                'voltage (REL = ALT = OV)", shown with the advanced fields.'),
 'reason.follow_ov_switch_off': ('Turn on "NVVDD REL and ALT follow OV", save the copy and open it to set this '
                                 'value.'),
 'reason.generic': 'Editing unavailable for this field.',
 'error.INVALID_IMAGE': 'Open a ROM first',
 'error.INVALID_CHANGES': 'Stage a verified preview before saving',
 'error.FIELD_READ_ONLY': 'This field is read-only',
 'error.CONFLICTING_FIELDS': 'Choose one representation of the field',
 'error.UNKNOWN_FIELD': 'This field is unknown or unvalidated',
 'error.INVALID_VALUE': 'Enter a valid finite number',
 'error.OUT_OF_BOUNDS': 'The value is outside the allowed range or breaks the minimum/default/maximum order',
 'error.UNREPRESENTABLE_VALUE': 'The value cannot be stored exactly in this format',
 'error.INTEGRITY_FAILED': 'ROM integrity checks failed',
 'error.SOURCE_OVERWRITE': 'Choose a destination different from the source',
 'error.SOURCE_CHANGED': 'The source changed since it was opened',
 'error.OUTPUT_EXISTS': 'The output or manifest already exists',
 'error.LOADER_OUTPUT_EXISTS': ('A -loader file for this name already exists, maybe from an earlier '
                                'copy: delete it or choose another name'),
 'error.IO_ERROR': 'Unable to read or write the file',
 'error.INVALID_PATH': 'Choose a valid local path',
 'error.UNSUPPORTED_ARCHITECTURE': 'This architecture supports inspection only',
 'error.UNSUPPORTED_FORMAT': 'This format supports inspection only',
 'error.FAMILY_MISMATCH': 'The other ROM is of another GPU family or format; import needs one of the same family',
 'error.DEPENDENT_FIELD_DISABLED': 'This value depends on a switch that is off; turn the switch on to change it',
 'error.ZERO_RPM_ABOVE_CURVE': ('With zero RPM on, a zero RPM upper threshold may not be above point 1 of its fan '
                                'curve; lower the threshold, with the lower threshold below it where needed, or keep '
                                'the point above it, in the same edit'),
 'error.SEPARATE_EDIT_REQUIRED': ('Save these changes in separate copies. The fan channel count goes before the '
                                  'fan limits, curves or zero RPM, and the REL/ALT follow OV setting before the '
                                  'voltages. On some RTX 4090 ROMs VMIN and the GPC curve offset also need separate '
                                  'saves, as do the NVVDD flat voltage and the GPC curve offset on some Blackwell '
                                  'ROMs, and so do zero RPM off and its thresholds on a copy where zero RPM wrote '
                                  'fan-stop values. Save one, then open the copy to change the rest'),
 'cli_usage': 'usage: ',
 'cli_positionals': 'positional arguments',
 'cli_options': 'options',
 'cli_help': 'Show this help message and exit'})


@dataclass(frozen=True)
class Messages:
    language: str = 'en'

    def __post_init__(self):
        if self.language not in ('en', 'es'):
            raise ValueError('GUI language must be en or es')

    @property
    def catalog(self):
        if self.language == 'es':
            from .messages_es import MESSAGES_ES
            return MESSAGES_ES
        return MESSAGES_EN

    def __call__(self, key, **values):
        return self.catalog[key].format(**values)

    def value(self, value):
        return self('unknown') if value is None else str(value)
