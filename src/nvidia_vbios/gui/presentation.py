"""GTK-free localized presentation of public field descriptors."""
from decimal import Decimal, InvalidOperation
import re

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
                        'connector_sum_power_max_w', 'connector_sum_power_rated_w'))
# Ampere/Turing external 12 V connector-channel power policies, numbered in power-row order
# (a sense channel, not a physical connector: one connector may span several), and the
# current hardware threshold on the same channel.
CONNECTOR_KEY = re.compile(r'connector_(\d+)_power_(max|rated)_w')
CONNECTOR_CURRENT_KEY = re.compile(r'connector_(\d+)_current_threshold_(max|rated)_ma')
# Per-channel fan limits, numbered from 1 like the fan channels; stored curve points, of a
# channel or of an extra curve (numbered from 1 in policy entry order).
FAN_KEY = re.compile(r'fan_(\d+)_(min|max)_(rpm|pct)')
FAN_CURVE_KEY = re.compile(r'fan_(\d+|extra_(\d+))_curve_(\d)_(temp_c|rpm|pct)')
FAN_CURVE_UNITS = ('temp_c', 'rpm', 'pct')
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
                     'memory': 'clocks', 'fans': 'fans', 'fan_zero_rpm': 'fans'}


def unsupported_notes(report, language='en'):
    """{section: note} for the sections a failed resolver left incomplete."""
    text = Messages(language)
    return {RESOLVER_SECTIONS[d['resolver']]: text('section.unsupported') for d in report.get('diagnostics', ())
            if d.get('resolver') in RESOLVER_SECTIONS}


# Read-only placeholders with no VBIOS row behind them: the generic input current and OCP
# limits (every family) and the MSVDD ceiling of a single-rail layout. Read as missing
# limits, they stay out of the window while their value is unknown; the JSON keeps them.
PLACEHOLDER_KEYS = frozenset(('current_limit_a', 'ocp_limit_a', 'msvdd_rel_max_mv'))


def technical_field_keys(report):
    """Keep equivalent aliases, raw selector bookkeeping and unknown placeholders in details."""
    fields = report.get('fields', [])
    keys = {f['key'] for f in fields}
    hidden = {f['key'] for f in fields if f.get('alias_of') in keys or
              f.get('value_semantics') in ('selector-index', 'stored-boot-voltage', 'unknown') or
              (f['key'] in PLACEHOLDER_KEYS and f.get('current') is None and not f.get('editable'))}
    if any(f['key'] == 'memory_offset_max_mhz' and f['editable'] for f in fields):
        hidden.add('dram_max_table_mhz')
    return hidden


def opt_in_field_keys(report):
    """Fields shown only after the user opts in (XOC-style advanced fields)."""
    return {f['key'] for f in report.get('fields', []) if f.get('opt_in')}


def primary_preview(document):
    hidden = technical_field_keys(document.report)
    return [(before, after) for before, after in document.preview if before['key'] not in hidden]


# Vertical layout: section order, and field order inside each section.
SECTIONS = (
    ('power', ('power_max_w', 'power_default_w', 'power_min_w', 'board_fixed_rated_w',
               'slot_power_max_w', 'slot_power_rated_w') +
              tuple(f'connector_{n}_power_{side}_w' for n in range(1, 5) for side in ('max', 'rated')) +
              ('connector_sum_power_max_w', 'connector_sum_power_rated_w',
               'nvvdd_power_threshold_max_w', 'nvvdd_power_threshold_rated_w')),
    ('voltage', ('nvvdd_rel_equation_max_mv', 'nvvdd_rel_max_mv', 'nvvdd_rel_fixed_mv', 'nvvdd_alt_fixed_mv',
                 'nvvdd_ov_equation_max_mv', 'nvvdd_vmin_mv', 'nvvdd_vmin_equation_max_mv', 'nvvdd_alt_equation_max_mv',
                 'nvvdd_rel_alt_follow_ov',
                 'msvdd_rel_equation_max_mv', 'msvdd_rel_max_mv', 'msvdd_ov_equation_max_mv', 'msvdd_vmin_mv',
                 'msvdd_vmin_equation_max_mv', 'msvdd_alt_equation_max_mv')),
    ('clocks', ('gpc_offset_max_mhz', 'gpc_offset_min_mhz', 'memory_offset_max_mhz', 'memory_offset_min_mhz',
                'xbar_max_table_mhz', 'xbar_min_table_mhz', 'sys_max_table_mhz', 'sys_min_table_mhz',
                'vid_max_table_mhz', 'vid_min_table_mhz')),
    ('current', ('input_current_rated_ma', 'input_current_max_ma', 'input_current_policy7_limit_ma',
                 'nvvdd_output_ocp_rated_ma', 'nvvdd_output_ocp_max_ma',
                 'msvdd_output_ocp_rated_ma', 'msvdd_output_ocp_max_ma', 'slot_current_threshold_rated_ma',
                 'slot_current_threshold_max_ma') +
                tuple(f'connector_{n}_current_threshold_{side}_ma' for n in range(1, 5) for side in ('rated', 'max'))),
    # Each channel's limits, then its curve points; then the extra curves; then zero RPM.
    ('fans', ('fan_channels', 'fan_pwm_frequency_hz') +
             tuple(key for n in range(1, 5) for key in
                   tuple(f'fan_{n}_{side}_{unit}' for unit in ('rpm', 'pct') for side in ('max', 'min')) +
                   tuple(f'fan_{n}_curve_{k}_{unit}' for k in (1, 2, 3) for unit in FAN_CURVE_UNITS)) +
             tuple(f'fan_extra_{m}_curve_{k}_{unit}' for m in range(1, 8) for k in (1, 2, 3)
                   for unit in FAN_CURVE_UNITS) + ('fan_zero_rpm',)),
)
SECTION_NAMES = tuple(name for name, _ in SECTIONS) + ('other',)
# Windows tools such as MSI Afterburner show the stored table value: half of
# the NVML/Linux memory offset, the same value for the core (observed on hardware).
WINDOWS_SCALE = {'memory_offset_max_mhz': Decimal('0.5'), 'memory_offset_min_mhz': Decimal('0.5')}
_EXPERIMENTAL = re.compile(r'(?:\s*\(experimental\)|,\s*experimental(?=\)))')


def field_section(field):
    """Section id for a field; unknown keys fall back by unit."""
    key = field['key']
    for section, keys in SECTIONS:
        if key in keys:
            return section
    if key.endswith('_mv'):
        return 'voltage'
    if key.endswith('_mhz'):
        return 'clocks'
    if key.endswith('_w'):
        return 'power'
    if key.endswith('_ma') or key.endswith('_a'):
        return 'current'
    return 'other'


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
    """Row text of a display value: On/Off for a 0/1 flag field, else number(value)."""
    if field.get('units') == 'flag' and value is not None and value in (0, 1):
        return Messages(language)('flag_on' if value else 'flag_off')
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
                 'channels': ('', Decimal(1)), 'flag': ('', Decimal(1)), 'C': ('°C', Decimal(1))}


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
