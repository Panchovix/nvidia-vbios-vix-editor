"""Field sections and visibility shared by the GUI and the import from another ROM (no GTK)."""

FAN_CURVE_UNITS = ('temp_c', 'rpm', 'pct')
# Vertical layout: section order, and field order inside each section.
SECTIONS = (
    ('power', ('power_max_w', 'power_default_w', 'power_min_w', 'board_fixed_rated_w',
               'slot_power_max_w', 'slot_power_rated_w') +
              tuple(f'connector_{n}_power_{side}_w' for n in range(1, 5) for side in ('max', 'rated')) +
              ('connector_sum_power_max_w', 'connector_sum_power_rated_w',
               'nvvdd_power_threshold_max_w', 'nvvdd_power_threshold_rated_w', 'max_operating_temp_c')),
    ('voltage', ('nvvdd_rel_equation_max_mv', 'nvvdd_rel_max_mv', 'nvvdd_rel_fixed_mv', 'nvvdd_alt_fixed_mv',
                 'nvvdd_ov_equation_max_mv', 'nvvdd_vmin_mv', 'nvvdd_vmin_equation_max_mv', 'nvvdd_alt_equation_max_mv',
                 'nvvdd_rel_alt_follow_ov',
                 'msvdd_rel_equation_max_mv', 'msvdd_rel_max_mv', 'msvdd_ov_equation_max_mv', 'msvdd_vmin_mv',
                 'msvdd_vmin_equation_max_mv', 'msvdd_alt_equation_max_mv')),
    ('clocks', ('factory_gpc_offset_mhz', 'factory_rated_boost_mhz', 'gpc_curve_offset_mhz', 'gpc_offset_max_mhz',
                'gpc_offset_min_mhz', 'memory_offset_max_mhz', 'memory_offset_min_mhz',
                'xbar_max_table_mhz', 'xbar_min_table_mhz', 'sys_max_table_mhz', 'sys_min_table_mhz',
                'vid_max_table_mhz', 'vid_min_table_mhz') +
               tuple(f'memory_point_{k}_follows_offset' for k in range(1, 8))),
    ('current', ('input_current_rated_ma', 'input_current_max_ma', 'input_current_policy7_limit_ma',
                 'nvvdd_output_ocp_rated_ma', 'nvvdd_output_ocp_max_ma',
                 'msvdd_output_ocp_rated_ma', 'msvdd_output_ocp_max_ma', 'slot_current_threshold_rated_ma',
                 'slot_current_threshold_max_ma') +
                tuple(f'connector_{n}_current_threshold_{side}_ma' for n in range(1, 5) for side in ('rated', 'max'))),
    # Each channel's limits, then its curve points; then the extra curves; then zero RPM and
    # its temperature pairs.
    ('fans', ('fan_channels', 'fan_pwm_frequency_hz') +
             tuple(key for n in range(1, 5) for key in
                   tuple(f'fan_{n}_{side}_{unit}' for unit in ('rpm', 'pct') for side in ('max', 'min')) +
                   tuple(f'fan_{n}_curve_{k}_{unit}' for k in (1, 2, 3) for unit in FAN_CURVE_UNITS)) +
             tuple(f'fan_extra_{m}_curve_{k}_{unit}' for m in range(1, 8) for k in (1, 2, 3)
                   for unit in FAN_CURVE_UNITS) + ('fan_zero_rpm',) +
             tuple(f'fan_{n}_zero_rpm_{side}_temp_c' for n in range(1, 5) for side in ('low', 'high')) +
             tuple(f'fan_extra_{m}_zero_rpm_{side}_temp_c' for m in range(1, 8) for side in ('low', 'high'))),
    # GB20x PERF_CF controllers (the utilization policy switch, then per clock domain its target,
    # jump threshold and hysteresis counts) and LPWR idle power features (each switch, then its idle
    # times). Shown last, collapsed; never imported from another ROM.
    ('advanced', ('perf_cf_util_policy',) +
                 tuple(f'perf_cf_{domain}_{kind}' for domain in ('gpc', 'dram', 'vid')
                       for kind in ('target_pct', 'jump_pct', 'hysteresis_down', 'hysteresis_up')) +
                 ('lpwr_gr_power_gating', 'lpwr_mscg', 'lpwr_nvdec_gating', 'lpwr_nvenc_gating', 'lpwr_ofa_gating',
                  'lpwr_nvjpg_gating', 'lpwr_difr', 'lpwr_difr_dfpr_idle_ms', 'lpwr_difr_sw_asr_idle_us',
                  'lpwr_difr_cg_idle_us', 'lpwr_gr_rail_gating', 'lpwr_gr_rail_gating_idle_us')),
)
ADVANCED_SECTION = 'advanced'
# 'other' collects unknown keys; the Advanced section comes after it.
SECTION_NAMES = tuple(name for name, _ in SECTIONS if name != ADVANCED_SECTION) + ('other', ADVANCED_SECTION)
# The sections one ROM can give another: not 'other' (no editable field) nor the Advanced section.
IMPORT_SECTION_NAMES = tuple(name for name in SECTION_NAMES if name not in ('other', ADVANCED_SECTION))


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
