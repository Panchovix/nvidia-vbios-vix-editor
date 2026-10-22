"""GTK-free localized presentation of public field descriptors."""
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

# Sections and visibility are shared with the import from another ROM; the GUI imports them from here too.
from ..editor.sections import (ADVANCED_SECTION, SECTION_NAMES, SECTIONS, field_section,  # noqa: F401
                               opt_in_field_keys, technical_field_keys)
from ..editor.registry import (FACTORY_BOOST_REASON, FACTORY_OFFSET_DISABLED_REASON, FACTORY_OFFSET_FRACTION_REASON,
                               LPWR_GR_RG_UNRECOGNIZED_REASON, LPWR_GR_RG_UNREVIEWED_REASON, LPWR_MIXED_REASON,
                               LPWR_TIME_SWITCH_REASON,
                               MAX_TEMP_DISABLED_REASON, MAX_TEMP_UNEQUAL_REASON, MAX_TEMP_UNRECOGNIZED_REASON,
                               PERF_CF_CONTROLLER_UNRECOGNIZED_REASON, PERF_CF_POLICY_UNRECOGNIZED_REASON)
from ..rom.memory import PROFILE_COLUMNS, TIMING_FIELDS
from .i18n import Messages

FIELD_KEYS = frozenset(('power_min_w', 'power_max_w', 'nvvdd_rel_max_mv', 'msvdd_rel_max_mv',
                        'dram_max_table_mhz', 'memory_offset_max_mhz',
                        'current_limit_a', 'ocp_limit_a', 'power_default_w',
                        'input_current_rated_ma', 'input_current_max_ma',
                        'gpc_offset_max_mhz', 'gpc_offset_min_mhz',
                        'memory_offset_min_mhz', 'dram_min_table_mhz',
                        'input_current_policy7_limit_ma', 'slot_power_rated_w', 'slot_power_max_w',
                        'board_fixed_rated_w', 'fan_pwm_frequency_hz', 'fan_channels', 'nvvdd_rel_alt_follow_ov',
                        'fan_zero_rpm',
                        'slot_current_threshold_rated_ma', 'slot_current_threshold_max_ma',
                        'nvvdd_power_threshold_rated_w', 'nvvdd_power_threshold_max_w',
                        'connector_sum_power_max_w', 'connector_sum_power_rated_w', 'gpc_curve_offset_mhz',
                        'factory_gpc_offset_mhz', 'factory_rated_boost_mhz', 'max_operating_temp_c',
                        # Advanced section (GB20x PERF_CF and LPWR).
                        'perf_cf_util_policy', 'lpwr_gr_power_gating', 'lpwr_mscg', 'lpwr_nvdec_gating',
                        'lpwr_nvenc_gating', 'lpwr_ofa_gating', 'lpwr_nvjpg_gating', 'lpwr_difr',
                        'lpwr_difr_dfpr_idle_ms', 'lpwr_difr_sw_asr_idle_us', 'lpwr_difr_cg_idle_us',
                        'lpwr_gr_rail_gating', 'lpwr_gr_rail_gating_idle_us'))
# The PERF_CF controller fields of the Advanced section, per clock domain.
PERF_CF_KEY = re.compile(r'perf_cf_(gpc|dram|vid)_(target_pct|jump_pct|hysteresis_down|hysteresis_up)')
# Ampere/Turing external 12 V connector-channel power policies, numbered in power-row order
# (a sense channel, not a physical connector: one connector may span several), and the
# current hardware threshold on the same channel.
CONNECTOR_KEY = re.compile(r'connector_(\d+)_power_(max|rated)_w')
CONNECTOR_CURRENT_KEY = re.compile(r'connector_(\d+)_current_threshold_(max|rated)_ma')
# Per-channel fan limits, numbered from 1 like the fan channels; stored curve points, of a
# channel or of an extra curve (numbered from 1 in policy entry order).
FAN_KEY = re.compile(r'fan_(\d+)_(min|max)_(rpm|pct)')
FAN_CURVE_KEY = re.compile(r'fan_(\d+|extra_(\d+))_curve_(\d)_(temp_c|rpm|pct)')
# The zero RPM temperature pair of a channel's or an extra curve's policy entry.
FAN_ZERO_RPM_TEMP_KEY = re.compile(r'fan_(\d+|extra_(\d+))_zero_rpm_(low|high)_temp_c')
# Whether a memory offset moves a stored intermediate memory level (numbered from the lowest).
MEMORY_POINT_KEY = re.compile(r'memory_point_(\d+)_follows_offset')
REASON_KEYS = {
    'generic OCP mapping unknown; reviewed per-rail output ceilings use *_output_ocp_max_ma': 'reason.generic_ocp',
    'generic current mapping unknown; the reviewed 12 V input policy uses input_current_*_ma': 'reason.generic_input',
    'experimental: policy7 limit linked to the 12 V input policy; it may cap the input current; not hardware-tested; '
    'stored value, not a hardware-safe current rating':
        'reason.linked_input',
    'per-policy units/semantics require independent evidence': 'reason.policy',
    'no validated OCP field mapping': 'reason.ocp',
    'memory domain and MHz/table conversion need independent validation': 'reason.memory_conversion',
    'Ada/Ampere memory units and editor variant lack validated evidence': 'reason.memory',
    'this recognized single-rail layout exposes only logic/NVVDD': 'reason.single_rail',
    'rail name mapping and voltage edit variant lack independent validation': 'reason.rail',
    'domain identity and MHz conversion are unvalidated': 'reason.clock',
    'Same field as the MHz control; edit that control.': 'table_alias',
    'Equivalent representation; use the main control.': 'field_alias',
    "no other fan channel layout is stored in this table, or a stored channel's limits do not hold the extra fan "
    'curves': 'reason.fan_layout',
    MAX_TEMP_DISABLED_REASON: 'reason.max_temp_disabled',
    MAX_TEMP_UNEQUAL_REASON: 'reason.max_temp_unequal',
    MAX_TEMP_UNRECOGNIZED_REASON: 'reason.max_temp_unrecognized',
    FACTORY_OFFSET_DISABLED_REASON: 'reason.factory_offset_disabled',
    FACTORY_OFFSET_FRACTION_REASON: 'reason.factory_offset_fraction',
    FACTORY_BOOST_REASON: 'reason.factory_boost',
    PERF_CF_POLICY_UNRECOGNIZED_REASON: 'reason.perf_cf_policy',
    PERF_CF_CONTROLLER_UNRECOGNIZED_REASON: 'reason.perf_cf_controller',
    LPWR_MIXED_REASON: 'reason.lpwr_mixed',
    LPWR_GR_RG_UNREVIEWED_REASON: 'reason.lpwr_gr_rg_unreviewed',
    LPWR_GR_RG_UNRECOGNIZED_REASON: 'reason.lpwr_gr_rg_unrecognized',
    LPWR_TIME_SWITCH_REASON: 'reason.lpwr_time_switch',
}


def field_label(field, language='en'):
    text = Messages(language)
    key = field['key']
    if key in ('input_current_rated_ma', 'input_current_max_ma') and field.get('policy_class') == 'hardware-threshold':
        # Ada stores the 12 V input limit as two class-5 hardware threshold rows.
        return text('field.input_threshold_' + key[len('input_current_'):])
    if key in FIELD_KEYS:
        return text('field.' + key)
    # An opt-in output current limit (Turing row 13) or fixed voltage (Turing) is shown with the
    # advanced fields.
    advanced = '_advanced' if field.get('opt_in') else ''
    for rail in ('nvvdd', 'msvdd'):
        if key == f'{rail}_output_ocp_max_ma':
            return text('field.output_ocp' + advanced, rail=rail.upper())
        if key == f'{rail}_output_ocp_rated_ma':
            return text('field.output_ocp_rated' + advanced, rail=rail.upper())
        if key == f'{rail}_vmin_mv':
            return text('field.vmin', rail=rail.upper())
        if key == f'{rail}_vmin_equation_max_mv':
            # The rail INFO VMIN slot; the evaluated VMIN is {rail}_vmin_mv.
            return text('field.vmin_slot', rail=rail.upper())
        for role in ('rel', 'alt', 'ov'):
            if key == f'{rail}_{role}_equation_max_mv':
                return text('field.equation', role=role.upper(), rail=rail.upper())
            if key == f'{rail}_{role}_fixed_mv':
                return text('field.fixed' + advanced, role=role.upper(), rail=rail.upper())
    match = CONNECTOR_KEY.fullmatch(key)
    if match:
        return text('field.connector_power_' + match.group(2), connector=match.group(1))
    match = CONNECTOR_CURRENT_KEY.fullmatch(key)
    if match:
        return text('field.connector_current_threshold_' + match.group(2), connector=match.group(1))
    match = FAN_KEY.fullmatch(key)
    if match:
        return text(f'field.fan_{match.group(2)}_{match.group(3)}', fan=match.group(1))
    match = FAN_CURVE_KEY.fullmatch(key)
    if match:
        owner, extra, point, unit = match.groups()
        if extra:
            return text(f'field.fan_extra_curve_{unit}', curve=extra, point=point)
        return text(f'field.fan_curve_{unit}', fan=owner, point=point)
    match = FAN_ZERO_RPM_TEMP_KEY.fullmatch(key)
    if match:
        owner, extra, side = match.groups()
        if extra:
            return text(f'field.fan_extra_zero_rpm_{side}_temp_c', curve=extra)
        return text(f'field.fan_zero_rpm_{side}_temp_c', fan=owner)
    match = PERF_CF_KEY.fullmatch(key)
    if match:
        return text('field.perf_cf_' + match.group(2), domain=match.group(1).upper())
    if MEMORY_POINT_KEY.fullmatch(key) and field.get('memory_mhz') is not None:
        return text('field.memory_point_follows_offset', mhz=field['memory_mhz'])
    for domain in ('xbar', 'sys', 'vid'):
        for side in ('max', 'min'):
            if key == f'{domain}_{side}_table_mhz':
                return text('field.clock_domain_' + side, domain=domain.upper())
    return field.get('label', key)


def read_only_reason(field, language='en'):
    text = Messages(language)
    reason = field.get('reason')
    if reason in REASON_KEYS:
        return text(REASON_KEYS[reason])
    # Unmapped evidence stays in English (the JSON manifest keeps it). Avoid pretending
    # to translate an arbitrary extension's backend explanation.
    return reason if language == 'en' and reason else text('reason.generic')


def advanced_group(field):
    """The group of an Advanced section row, which the GUI shows in its own card under its own heading:
    'advanced_perf' for the PERF_CF policy and controllers, 'advanced_lpwr' for the LPWR switches and idle times."""
    return 'advanced_perf' if field['key'].startswith('perf_cf_') else 'advanced_lpwr'


def dependency_reason(field, fields, language='en'):
    """Why a field that depends on a switch (depends_on) is greyed out while the switch is off; None otherwise.

    fields maps keys to descriptors; the switch is named by its row title.
    """
    dependency = field.get('depends_on')
    if not dependency:
        return None
    switch = fields.get(dependency['field'])
    name = row_title(switch, language)[0] if switch else dependency['field']
    stock = bool(switch and switch.get('switch') == 'stock-off')
    return Messages(language)('reason.depends_on_stock' if stock else 'reason.depends_on', switch=name)


def summed_cap_notes(field, fields, language='en'):
    """One note per row that caps a sum of power channels adding this field's (Ampere connector) channel.

    Channels are named by their connector numbers when every one has a connector field.
    The row shares the field's class and unit (mW or mA), shown as W or A.
    """
    text = Messages(language)
    connectors = {f['power_channel']: f['connector'] for f in fields if 'connector' in f and 'power_channel' in f}
    own = {i for f in fields if f['key'] == 'connector_sum_power_rated_w' for i in f.get('policy_indices', ())}
    notes = []
    for cap in field.get('summed_cap_rows', ()):
        channels = cap['summed_channels']
        named = all(c in connectors for c in channels)
        note = text('summed_cap.connectors' if named else 'summed_cap.channels', row=cap['row'],
                    channels=', '.join(str(connectors[c] if named else c) for c in channels),
                    rated=number(Decimal(cap['rated']) / 1000), maximum=number(Decimal(cap['maximum']) / 1000),
                    units=display_units(field))
        notes.append(note + (' ' + text('summed_cap.raise') if cap['row'] in own else ''))
    return notes


def fan_curve_hint(field, fields, values, language='en'):
    """Explain curve points blocking a fan limit, using all pending stored values.

    The report already associates each curve with its fan rows, including shared
    extra curves. This is guidance only: the backend still validates the edit and
    may also constrain it by the opposite limit, encoding or stored speed.
    """
    match = FAN_KEY.fullmatch(field.get('key', ''))
    channel = field.get('fan_channel')
    if match is None or channel is None:
        return ''
    amount = parse_number(values.get(field['key'], field.get('current')))
    if amount is None:
        return ''
    bounds = field.get('bounds', {})
    lower = parse_number(bounds.get('encoding_minimum'))
    upper = parse_number(bounds.get('encoding_maximum'))
    if lower is not None and amount < lower or upper is not None and amount > upper:
        return ''  # Curve edits cannot fix an unencodable limit.
    side, unit = match.group(2, 3)
    blocked = []
    for curve in fields:
        point = FAN_CURVE_KEY.fullmatch(curve.get('key', ''))
        if (point is None or point.group(4) != unit or
                channel not in curve.get('fan_rows', ())):
            continue
        value = parse_number(values.get(curve['key'], curve.get('current')))
        if value is not None and (value < amount if side == 'min' else value > amount):
            blocked.append((curve, value))
    if not blocked:
        return ''
    text = Messages(language)
    readonly = [curve for curve, _ in blocked if not curve.get('editable')]
    if readonly:
        return text('fan_curve_readonly_hint', points='; '.join(row_title(c, language)[0] for c in readonly))
    bound = (min if side == 'min' else max)(value for _, value in blocked)
    return text('fan_curve_' + side + '_hint', value=number(to_display(field, bound)),
                units=display_units(field), points='; '.join(row_title(c, language)[0] for c, _ in blocked))


# Resolvers whose fields all sit in one section. When one fails on an image (a layout
# the editor does not support; report diagnostics), that section says some of its fields
# are missing. Other diagnostics (an unpadded image, an unrecognized one) leave no note:
# their fields stay listed read-only with a reason, or the window shows none. The voltage
# resolver only adds hidden aliases of the REL equation ceilings, so its failure alone
# (an Ada REL compare expression) hides nothing.
RESOLVER_SECTIONS = {'equation_roles': 'voltage', 'evaluated_vmin': 'voltage',
                     'fixed_voltage': 'voltage', 'rail_follow_ov': 'voltage',
                     'power': 'power', 'slot_power': 'power', 'connector_power': 'power',
                     'connector_sum_power': 'power', 'output_ocp': 'current', 'input_current': 'current',
                     'memory': 'clocks', 'fans': 'fans', 'fan_zero_rpm': 'fans', 'fan_zero_rpm_temperatures': 'fans',
                     'dram_offset_points': 'clocks', 'gpc_curve_offset': 'clocks',
                     'max_operating_temperature': 'power', 'factory_clocks': 'clocks',
                     'perf_cf_controllers': 'advanced', 'lpwr_features': 'advanced'}


def unsupported_notes(report, language='en'):
    """{section: note} for the sections a failed resolver left incomplete."""
    text = Messages(language)
    return {RESOLVER_SECTIONS[d['resolver']]: text('section.unsupported') for d in report.get('diagnostics', ())
            if d.get('resolver') in RESOLVER_SECTIONS}


def primary_preview(document):
    hidden = technical_field_keys(document.report)
    return [(before, after) for before, after in document.preview if before['key'] not in hidden]


# Windows tools such as MSI Afterburner show the stored table value: half of
# the NVML/Linux memory offset, the same value for the core (observed on hardware).
WINDOWS_SCALE = {'memory_offset_max_mhz': Decimal('0.5'), 'memory_offset_min_mhz': Decimal('0.5')}
_EXPERIMENTAL = re.compile(r'(?:\s*\(experimental\)|,\s*experimental(?=\)))')


def section_order(fields):
    """Fields in display order: SECTIONS order first, then descriptor order."""
    rank = {key: i for _, keys in SECTIONS for i, key in enumerate(keys)}
    return sorted(fields, key=lambda f: (SECTION_NAMES.index(field_section(f)), rank.get(f['key'], len(rank) + 1)))


def row_title(field, language='en'):
    """Short row title and whether to show an experimental badge."""
    title = field_label(field, language)
    short = _EXPERIMENTAL.sub('', title).strip()
    return short, bool(field.get('experimental')) or short != title


# Every editable field fits in 32 bits with at most five decimals (1/32 C), so input
# outside these magnitudes is refused before any arithmetic or formatting.
LARGEST = Decimal('1e12')
SMALLEST = Decimal('1e-6')


def classify_number(text):
    """(Decimal, None) for usable input, else (None, 'not_a_number' or 'out_of_range')."""
    try:
        amount = Decimal(str(text).strip())
    except (InvalidOperation, ValueError):
        return None, 'not_a_number'
    if not amount.is_finite():
        return None, 'not_a_number'
    if amount and not SMALLEST <= amount.copy_abs() < LARGEST:
        return None, 'out_of_range'
    return amount, None


def parse_number(text):
    """Decimal for usable user text, or None."""
    return classify_number(text)[0]


def number(value):
    """Plain number text: 600 rather than 600.0; None stays None; never raises."""
    if value is None or isinstance(value, bool):
        return None if value is None else str(value)
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if not amount.is_finite() or (amount and not SMALLEST <= amount.copy_abs() < LARGEST):
        # Bounded scientific text for magnitudes no field can hold.
        return format(amount, '.6g') if amount.is_finite() else str(amount)
    if amount == amount.to_integral_value():
        return str(amount.quantize(Decimal(1)))
    return format(amount.normalize(), 'f')


def value_text(field, value, language='en'):
    """Row text of a display value: On/Off for a 0/1 flag field (Stock/Off for a stock-off switch), else
    number(value)."""
    if field.get('units') == 'flag' and value is not None and value in (0, 1):
        on = 'flag_stock' if field.get('switch') == 'stock-off' else 'flag_on'
        return Messages(language)(on if value else 'flag_off')
    return number(value)


def windows_value(field, value):
    """Value as Windows tools show it, when that scale differs; else None."""
    scale = WINDOWS_SCALE.get(field['key'])
    amount = parse_number(str(value)) if value is not None else None
    if scale is None or amount is None:
        return None
    return number(amount * scale)


# Rows show some stored units on a friendlier scale: table MHz as MHz, mA as A
# and Hz as kHz (exact: factor 0.001), and C as °C. The backend always receives stored units.
DISPLAY_UNITS = {'table MHz': ('MHz', Decimal(1)), 'mA': ('A', Decimal('0.001')), 'Hz': ('kHz', Decimal('0.001')),
                 'channels': ('', Decimal(1)), 'flag': ('', Decimal(1)), 'C': ('°C', Decimal(1)),
                 'us': ('µs', Decimal(1)), 'samples': ('', Decimal(1))}


def display_units(field):
    """Units as shown in rows."""
    return DISPLAY_UNITS.get(field.get('units'), (field.get('units'), None))[0]


def to_display(field, value):
    """Stored value on the row scale, as a Decimal; None when not a usable number."""
    amount = None if value is None else parse_number(str(value))
    if amount is None:
        return None
    return amount * DISPLAY_UNITS.get(field.get('units'), (None, Decimal(1)))[1]


def to_stored(field, text):
    """Typed row text back in stored units; text that is not a number passes through."""
    amount = parse_number(text)
    if amount is None:
        return text
    return number(amount / DISPLAY_UNITS.get(field.get('units'), (None, Decimal(1)))[1])


# A shunt mod lowers the 12 V input sense resistance, so the card reads power and
# current divided by its factor: a limit measured there allows about that many
# times more. These fields read the total board power (channel 0, the sum of the
# inputs), the 12 V input current, an external 12 V connector (Ampere, Turing; power
# or current) or their sum (Ampere) or the PCIe slot input. NVVDD/MSVDD output current
# and NVVDD output power are VRM sensors and are not scaled.
SHUNT_KEYS = frozenset(('power_min_w', 'power_default_w', 'power_max_w', 'board_fixed_rated_w',
                        'slot_power_rated_w', 'slot_power_max_w', 'input_current_rated_ma',
                        'input_current_max_ma', 'input_current_policy7_limit_ma',
                        'slot_current_threshold_rated_ma', 'slot_current_threshold_max_ma',
                        'connector_sum_power_max_w', 'connector_sum_power_rated_w') +
                       tuple(f'connector_{n}_power_{side}_w' for n in range(1, 5) for side in ('max', 'rated')) +
                       tuple(f'connector_{n}_current_threshold_{side}_ma' for n in range(1, 5)
                             for side in ('max', 'rated')))


def shunt_scaled(field):
    """True for limits measured through the 12 V input shunts."""
    return field['key'] in SHUNT_KEYS


def shunt_real(field, value, multiplier):
    """About the real amount a display value allows with this shunt multiplier, as text; else None."""
    amount = parse_number(str(value)) if value is not None else None
    if not shunt_scaled(field) or amount is None or multiplier <= 1:
        return None
    return number(round(amount * multiplier, 1))


def import_summary(report, fields, language='en'):
    """(line, kind) of an import from another ROM (an editor.import_fields report): how many values became
    pending changes, the warnings, how many were already equal and each skipped field with its reason; kind is
    'heading', 'warning' or 'detail'. fields maps the open ROM's keys to descriptors; a field it lacks is
    named by the other ROM's label."""
    text = Messages(language)
    name, count = Path(report['donor']['file']).name, len(report['applied'])
    skipped = {entry['field']: entry for entry in report['skipped']}

    def field_of(key):
        entry = skipped[key]
        return fields.get(key) or dict(key=key, label=entry['label'], units=entry['units'])

    def listed(keys):
        names = [row_title(field_of(key), language)[0] for key in keys]
        shown = '; '.join(names[:2])
        return text('import.more', fields=shown, count=len(names) - 2) if names[2:] else shown
    held = {}
    for entry in report['skipped']:
        if entry['reason'] == 'held_back':
            held.setdefault(tuple(entry['partners']), []).append(entry['field'])
    lines = [(text('import.applied', count=count, file=name) if count else text('import.nothing', file=name),
              'heading')]
    if any(w['code'] == 'DIFFERENT_DEVICE' for w in report['warnings']):
        lines.append((text('import.different_device', donor=report['donor']['pci_device'],
                           target=report['target']['pci_device']), 'warning'))
    if report['unchanged']:
        lines.append((text('import.unchanged', count=len(report['unchanged'])), 'detail'))
    if report['skipped']:
        lines.append((text('import.skipped', count=len(report['skipped'])), 'heading'))
    if any(skipped[key]['reason'] == 'opt_in' for entry in report['skipped'] for key in entry.get('partners', ())):
        lines.append((text('import.opt_in_hint'), 'detail'))
    for entry in report['skipped']:
        field = field_of(entry['field'])
        title = row_title(field, language)[0]
        if entry['reason'] == 'out_of_bounds':
            low, high = (number(to_display(field, entry['bounds'][side])) or '—' for side in ('minimum', 'maximum'))
            reason = text('import.reason.out_of_bounds', minimum=low, maximum=high, units=display_units(field))
        elif entry['reason'] == 'refused':
            code = entry['code']
            message = text('error.' + code) if 'error.' + code in text.catalog else entry['message']
            reason = text('import.reason.refused', message=message, code=code)
        elif entry['reason'] == 'held_back':
            # One line per set held back by the same fields, at its first field.
            subjects = held.pop(tuple(entry['partners']), None)
            if subjects is None:
                continue
            title = listed(subjects)
            reason = text('import.reason.held_back' if len(subjects) == 1 else 'import.reason.held_back_many',
                          fields=listed(entry['partners']))
        else:
            reason = text('import.reason.' + entry['reason'])
        lines.append((f'{title}: {reason}', 'detail'))
    return lines


# Read-only memory view: text from a nvidia_vbios.rom.memory report or comparison.
MEMORY_SECTIONS = ('configurations', 'bands', 'timings', 'tables', 'board_profile')
MEMORY_TIMINGS = tuple(field[0] for field in TIMING_FIELDS)


def memory_vendor(item, language='en'):
    return item['vendor'] or Messages(language)('memory.vendor_code', code=item['vendor_code'])


def memory_configuration(item, language='en'):
    """'Strap 0 → column 0 · Samsung · type 0xd (probably GDDR7)': only type 9 has a name."""
    text = Messages(language)
    kind = item['type'] or (text('memory.type_guess', code=item['type_code'], name=item['type_guess'])
                            if item['type_guess'] else item['type_code'])
    return text('memory.configuration', strap=item['strap'], column=item['column'],
                vendor=memory_vendor(item, language), type=kind)


def memory_columns(report, language='en'):
    """(heading, rows, note) per group of configuration columns with the same rows; a row is (band, stock
    clocks, entry, decoded timing or None), and note says why a group has no rows.

    The rows are the bands that hold a stock DRAM clock when the report has those clocks, else every
    band with a maximum above 0 MHz; columns without a timing entry in them have no rows, and columns
    the memory clock table does not reach come last.
    """
    text = Messages(language)
    configurations = report['configurations'].get('items', [])
    bands_section = report['bands']
    stock = bool(bands_section.get('stock_points'))
    bands = [b for b in bands_section['items'] if (b['stock_points'] if stock else b['max_mhz'])]
    timings = {t['index']: t['decoded'] for t in report['timings'].get('items', ())}
    groups = {}
    for column in bands_section['columns']:
        rows = []
        for band in bands:
            index = band['timing_index'].get(str(column))
            points = (text('memory.stock', points=', '.join(map(str, band['stock_points'])))
                      if band['stock_points'] else '')
            rows.append((f"{band['min_mhz']}–{band['max_mhz']}", points, '—' if index is None else f'T{index:02x}',
                         timings.get(index)))
        rows = rows if any(row[2] != '—' for row in rows) else []
        note = None if rows else text('memory.no_entries')
        groups.setdefault(repr(rows), (rows, note, []))[2].append(column)
    if bands_section.get('outside_table'):
        groups['outside'] = ([], text('memory.outside_table', last=bands_section['column_count'] - 1),
                             bands_section['outside_table'])
    columns = []
    for rows, note, numbers in groups.values():
        users = [c for c in configurations if c['column'] in numbers]
        vendors = ', '.join(dict.fromkeys(memory_vendor(c, language) for c in users)) or text('unknown')
        columns.append((text('memory.column', column=', '.join(map(str, numbers)), vendor=vendors,
                             straps=', '.join(str(c['strap']) for c in users) or '—'), rows, note))
    return columns


def memory_table(key, language='en'):
    """A compared table ('memory clock bands (0x0f)') with its name translated."""
    text = Messages(language)
    name, _, owner = key.partition(' (')
    message = 'memory.table.' + name.replace(' ', '_')
    title = text(message) if message in text.catalog else name
    return f'{title} ({owner}' if owner else title


def memory_comparison(result, language='en'):
    """(line, differs) per section of a memory comparison; identical or different, never better or worse."""
    text = Messages(language)
    lines = []
    for name in MEMORY_SECTIONS:
        section = result['sections'][name]
        title, status = text('memory.section.' + name), section['status']
        if status == 'not-applicable':
            continue
        if status in ('identical', 'unavailable'):
            line = text('memory.' + status, section=title)
        elif name == 'board_profile':
            line = (text('memory.differs_fields', section=title, count=section['fields']) if section.get('fields')
                    else text('memory.differs_unknown', section=title))
        elif name == 'tables':
            line = text('memory.differs_tables', section=title,
                        tables=', '.join(memory_table(key, language) for key in section['keys']))
        elif 'count' in section:
            line = text('memory.differs_entries', section=title, count=section['count'])
        else:
            line = text('memory.differs', section=title)
        lines.append((line, status == 'differs'))
    return lines


def memory_raw_text(report, language='en'):
    """Monospace dump: each table's offset, every configuration and band with its raw bytes (a band's
    sub-entries for the configurations' columns), the timing entries the bands select, the table hashes and
    the board profile bytes."""
    text, lines = Messages(language), []

    def spaced(raw):
        return ' '.join(raw[i:i + 2] for i in range(0, len(raw), 2))

    def heading(name):
        section = report[name]
        title = text('memory.section.' + name)
        lines.append(f"{title} @{section['offset']}" if section['status'] == 'recognized'
                     else f"{title}: {section.get('reason', section['status'])}")
        return section['status'] == 'recognized'
    if heading('configurations'):
        lines += [f"  {i['strap']} → {i['column']}: {spaced(i['raw'])}" for i in report['configurations']['items']]
    if heading('bands'):
        for b in report['bands']['items']:
            lines.append(f"  E{b['entry']} {b['min_mhz']}–{b['max_mhz']}: " +
                         ' '.join(f"{c}:{'--' if i is None else f'T{i:02x}'}" for c, i in b['timing_index'].items()))
            lines.append(f"    {spaced(b['raw'])}")
            lines += [f'    {c}: {spaced(raw)}' for c, raw in b['sub_entries'].items()]
        if report['bands'].get('outside_table'):
            lines.append(f"  {', '.join(map(str, report['bands']['outside_table']))}: " +
                         text('memory.outside_table', last=report['bands']['column_count'] - 1))
    if heading('timings'):
        lines += [f"  T{t['index']:02x} @{t['offset']}: {spaced(t['raw'])}" for t in report['timings']['items']]
    lines.append(text('memory.section.tables'))
    for t in report['tables']:
        owner = f" {t['object']}" if t['object'] else ''
        lines.append(f"  {t['table']}{owner} @{t['offset']} +{t['size']}: {t['sha256']}")
    profile = report['board_profile']
    if profile['status'] == 'recognized' and 'fields' in profile:
        lines.append(f"{text('memory.section.board_profile')} @{profile['offset']}: {spaced(profile['header'])}")
        lines.append('  ' + ', '.join(f'{name} @{at}' for name, at in profile['records'].items()))
        lines += [f"  +{f['offset']} {f['size']}: " + '  '.join(f'{name} {f[name]}' for name in PROFILE_COLUMNS)
                  for f in profile['fields']]
        lines += [f'  {name}: {spaced(raw)}' for name, raw in profile['index_lists'].items()]
        for part in ('arrays', 'flags'):
            value = profile[part]
            lines.append(f"  {part} @{value['offset']}: {value['values']}" if value['status'] == 'recognized'
                         else f"  {part}: {value['reason']}")
    elif profile['status'] == 'unrecognized':
        lines.append(f"{text('memory.section.board_profile')}: {profile['reason']}")
    return '\n'.join(lines)
