"""Import the editable values of chosen sections from another ROM of the same family, through edit()."""
import re
from decimal import Decimal

from ..rom import VbiosError
from .api import edit
from .sections import IMPORT_SECTION_NAMES, field_section, technical_field_keys

# The sections one ROM can give another: 'other' holds no editable field, and the Advanced section
# (PERF_CF and LPWR tuning) is never copied between ROMs.
IMPORT_SECTIONS = IMPORT_SECTION_NAMES
NOTE = ('Values are copied as stored numbers, not adapted to this board: fan speeds, power and current limits and '
        "voltage limits from another board can exceed this board's hardware (fans rated for a lower speed, fewer "
        'power connectors, another power stage or GPU), and a clock offset from another board may not be stable '
        'on this one.')
# Descriptor attributes that must agree for a key to mean the same quantity in both ROMs: a memory point is
# numbered among its own ROM's memory levels, a notebook board power is the TGP the platform requests, and a
# voltage value is read from an equation of its type (and of its sharing, _equations).
IDENTITY = ('units', 'memory_mhz', 'notebook_tgp', 'equation_type')
# The fan channel count describes this board's fans: never copied.
BOARD_KEYS = frozenset(('fan_channels',))
# The GB20x maximum operating temperature: each product has its own. Never copied, and never listed as
# unchanged, so a value typed here stays.
PRODUCT_KEYS = frozenset(('max_operating_temp_c',))
# One fan curve: the fan limits and each point's temperature, speed and level (three ordering groups in the editor).
FAN_CURVE = re.compile(r'fan_(\d+_(min|max)_(rpm|pct)|(\d+|extra_\d+)_curve_\d+_(temp_c|rpm|pct))')
# Copies of one limit that the editor keeps as separate fields.
LINKED = {'input_current_policy7_limit_ma': 'input-current-12v'}
# Reasons that leave a value of this ROM that differs from the donor's: the rest of its set stays too.
HOLDING = frozenset(('opt_in', 'read_only', 'read_only_in_donor', 'read_only_in_target', 'different_meaning',
                     'out_of_bounds'))


def _set(field):
    """The dependent set whose values come whole from one ROM: the fan curve, an ordering group (a minimum, rated
    value and maximum) or a linked copy; None for an independent field."""
    if FAN_CURVE.fullmatch(field['key']):
        return 'fan-curve'
    return LINKED.get(field['key']) or field.get('ordering_group')


def _unit(field):
    """The fields one edit must carry together: every voltage field (each bounds the others), else its set or the
    field alone."""
    if field.get('units') == 'mV':
        return 'voltage'
    return _set(field) or field['key']


def _blame(exc, unit_of):
    """The unit an editor refusal names by its field; None when it names none."""
    key = exc.details.get('field') if isinstance(exc.details, dict) else None
    return unit_of.get(key) if isinstance(key, str) else None


def _equations(report):
    """Key -> the keys on the same VFE equation. REL and ALT that follow OV share its equation, so their values are
    another quantity than in a ROM where each has its own."""
    hidden, shared = technical_field_keys(report), {}
    for f in report['fields']:
        if f.get('equation_offset') is not None and f['key'] not in hidden:
            shared.setdefault(f['equation_offset'], set()).add(f['key'])
    return {key: frozenset(keys) for keys in shared.values() for key in keys}


UNRECOGNIZED = (None, '', 'unknown')


def _identity(image, report):
    return dict(file=image.name, sha256=image.sha256, pci_device=report.get('pci_device'),
                family=(report.get('architecture') or {}).get('family'), format=report.get('format'),
                versions=report.get('versions', []))


def _kind(identity):
    if identity['family'] in UNRECOGNIZED:
        return 'not a recognized ROM'
    return f"{identity['family']} ({identity['format'] or 'unrecognized format'})"


def _amount(field):
    return None if field is None or field.get('current') is None else Decimal(str(field['current']))


def import_fields(target, donor, sections, *, include_opt_in=False, dry_run=False):
    """(report, result): the donor's values of the editable fields in `sections` that differ in target.

    Both images must be of the same family and format; another device of the family only adds a
    warning. Fields hidden as aliases or placeholders are not considered, nor opt-in fields unless
    include_opt_in, nor the fan channel count or the maximum operating temperature (BOARD_KEYS,
    PRODUCT_KEYS). A field is proposed when it is editable in both images, means the same quantity
    in both and its donor value is inside the target's bounds, checked as edit() checks them: the
    encoding bounds when partners of its ordering group are proposed with it, else its own. A
    dependent set (_set) comes whole from the donor: when one of its fields differs but is left
    out, the others are held back. The proposal goes through edit() as one request, so the
    cross-field checks see the final set; a unit the editor refuses (_unit) is dropped whole and
    reported, never applied in part. result is the verified EditResult of the applied values, or
    None when none is applied; report lists them (`changes`, `applied`), every `skipped` field with
    its reason, the `unchanged` keys (editable here, equal in both) and `warnings`.
    """
    sections = [sections] if isinstance(sections, str) else list(dict.fromkeys(sections))
    unknown = [name for name in sections if name not in IMPORT_SECTIONS]
    if not sections or unknown:
        raise VbiosError('INVALID_SECTIONS', 'choose sections among ' + ', '.join(IMPORT_SECTIONS),
                         details={'sections': unknown, 'allowed': list(IMPORT_SECTIONS)})
    ours_report, theirs_report = target.report, donor.report
    ours, theirs = _identity(target, ours_report), _identity(donor, theirs_report)
    if ours['family'] in UNRECOGNIZED or (ours['family'], ours['format']) != (theirs['family'], theirs['format']):
        raise VbiosError('FAMILY_MISMATCH', 'import needs a ROM of the same family and format: this ROM is '
                         f'{_kind(ours)}, the donor is {_kind(theirs)}', details={'target': ours, 'donor': theirs})
    warnings = []
    if ours['pci_device'] != theirs['pci_device']:
        warnings.append(dict(code='DIFFERENT_DEVICE', message=f"the donor is another product of this family (PCI "
                             f"{theirs['pci_device']}; this ROM: PCI {ours['pci_device']}); its values were set for "
                             'that product'))
    our_fields = {f['key']: f for f in ours_report['fields']}
    their_fields = {f['key']: f for f in theirs_report['fields']}
    hidden = technical_field_keys(ours_report) | technical_field_keys(theirs_report)
    equations = _equations(ours_report), _equations(theirs_report)
    order = {key: i for i, key in enumerate(dict.fromkeys([*our_fields, *their_fields]))}
    proposal, entries, left, unchanged = {}, {}, [], []
    for key in order:
        mine, other = our_fields.get(key), their_fields.get(key)
        field = mine or other
        section = field_section(field)
        if key in hidden or section not in sections:
            continue
        opted_out = not include_opt_in and any(f.get('opt_in') for f in (mine, other) if f)
        editable = [f is not None and f['editable'] for f in (mine, other)]
        both = mine is not None and other is not None
        same = both and (all(mine.get(name) == other.get(name) for name in IDENTITY) and
                         equations[0].get(key) == equations[1].get(key))
        if both and _amount(mine) == _amount(other):
            if same and editable[0] and not opted_out and key not in PRODUCT_KEYS:
                unchanged.append(key)
            continue
        if (opted_out or not any(editable)) and not both:
            continue                    # an advanced or read-only field one ROM lacks
        entries[key] = dict(field=key, section=section, label=field.get('label', key), units=field['units'],
                            target=mine and mine['current'], donor=other and other['current'])
        if opted_out:
            reason = 'opt_in'
        elif not any(editable):
            reason = 'read_only'        # listed only when it holds back its set
        elif other is None:
            reason = 'absent_in_donor'
        elif mine is None:
            reason = 'absent_in_target'
        elif key in BOARD_KEYS:
            reason = 'board_specific'
        elif key in PRODUCT_KEYS:
            reason = 'product_specific'
        elif not editable[1] or other['current'] is None:
            reason = 'read_only_in_donor'
        elif not editable[0]:
            reason = 'read_only_in_target'
        elif not same:
            reason = 'different_meaning'
        else:
            proposal[key] = other['current']
            continue
        left.append(dict(entries[key], reason=reason))

    def set_of(key):
        return next((name for name in (_set(f) for f in (our_fields.get(key), their_fields.get(key)) if f) if name),
                    None)
    held, holding = [], set()

    def hold(entries_left):
        """Hold back the proposed fields of each set that a field left out for a HOLDING reason belongs to."""
        holders = {}
        for entry in entries_left:
            if entry['reason'] in HOLDING and set_of(entry['field']):
                holders.setdefault(set_of(entry['field']), []).append(entry['field'])
        for key in [key for key in proposal if set_of(key) in holders]:
            held.append(dict(entries[key], reason='held_back', partners=holders[set_of(key)]))
            holding.update(holders[set_of(key)])
            del proposal[key]
    hold(left)
    groups = [our_fields[key].get('ordering_group') for key in proposal]
    out = []
    for key in list(proposal):
        group, bounds = our_fields[key].get('ordering_group'), our_fields[key]['bounds']
        joint = group and groups.count(group) > 1
        low, high = ((bounds.get('encoding_minimum'), bounds.get('encoding_maximum')) if joint else
                     (bounds['minimum'], bounds['maximum']))
        after = Decimal(str(proposal[key]))
        if low is not None and after < Decimal(str(low)) or high is not None and after > Decimal(str(high)):
            out.append(dict(entries[key], reason='out_of_bounds', bounds=dict(minimum=low, maximum=high)))
            del proposal[key]
    hold(out)
    unit_of = {key: _unit(f) for key, f in our_fields.items()}
    units = {}
    for key, value in proposal.items():
        units.setdefault(unit_of[key], {})[key] = value

    def attempt(names):
        return edit(target, {key: value for name in names for key, value in units[name].items()}, dry_run=dry_run)
    pending, result, refused = list(units), None, []
    while pending:
        try:
            result = attempt(pending)
            break
        except VbiosError as exc:
            blamed = _blame(exc, unit_of)
            if blamed in pending:
                pending.remove(blamed)
                refused.append((blamed, exc))
                continue
            # A refusal that names no unit: keep, in order, each unit the editor accepts with those before it.
            kept = []
            for name in pending:
                try:
                    result = attempt(kept + [name])
                    kept.append(name)
                except VbiosError as error:
                    refused.append((name, error))
            pending = kept
            break
    skipped = [entry for entry in left + out if entry['reason'] != 'read_only' or entry['field'] in holding] + held
    skipped += [dict(entries[key], reason='refused', code=exc.code, message=str(exc))
                for name, exc in refused for key in units[name]]
    applied = sorted((key for name in pending for key in units[name]), key=order.get) if result else []
    report = dict(schema_version=1, target=ours, donor=theirs, sections=sections, include_opt_in=bool(include_opt_in),
                  changes={key: proposal[key] for key in applied}, applied=[entries[key] for key in applied],
                  skipped=sorted(skipped, key=lambda e: order[e['field']]), unchanged=unchanged, warnings=warnings,
                  note=NOTE)
    return report, result
