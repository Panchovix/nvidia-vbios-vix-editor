"""Immutable offline edits, dry-run manifests, and no-overwrite publication."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import tempfile
import time
from ..rom import BiosImage, VbiosError
from ..rom.blackwell import BlackwellRom, LPWR_TABLES, PERF_CF_CONTROLLERS as PERF_CF_TABLE, PERF_CF_POLICIES
from ..rom.image import backend, inspect_image
from ..rom.tables import checksum_tail
from .registry import (registry, power, input_current, output_ocp, slot_power, power_thresholds, fans, fan_zero_rpm,
                       fan_zero_rpm_temperatures, connector_power, connector_sum_power, evaluated_vmin, rail_follow_ov,
                       fixed_voltage, dram_offset_points, gpc_curve_offset, max_operating_temperature,
                       factory_clocks, perf_cf_controllers, lpwr_features, VMIN_SEMANTICS, FOLLOW_OV_SEMANTICS,
                       FIXED_SEMANTICS, DRAM_POINT_SEMANTICS, GPC_CURVE_SEMANTICS, MAX_TEMP_SEMANTICS,
                       FACTORY_OFFSET_SEMANTICS, ADVANCED_SEMANTICS, PERF_CF_CONTROLLERS, fxp_percent)

# Reviewed resolvers whose bindings are canonical for range and joint checks.
REVIEWED_RESOLVERS = (power, input_current, output_ocp, slot_power, power_thresholds, fans, fan_zero_rpm,
                      fan_zero_rpm_temperatures, connector_power, connector_sum_power, evaluated_vmin, rail_follow_ov,
                      fixed_voltage, dram_offset_points, gpc_curve_offset, max_operating_temperature, factory_clocks,
                      perf_cf_controllers, lpwr_features)
# Fields that change otherwise preserved rail bytes, each only through its reviewed binding:
# the evaluated VMIN equation, the XOC-style NVVDD REL/ALT selectors and the fixed Ada/Turing
# REL/ALT values.
RAIL_EXCEPTIONS = (VMIN_SEMANTICS, FOLLOW_OV_SEMANTICS, FIXED_SEMANTICS)
# Layout fields whose bytes no other check rereads through the canonical parser: only the
# reviewed complete binding (offsets, encoding, scale and layout) may write them.
COMPLETE_BINDING_SEMANTICS = RAIL_EXCEPTIONS + (DRAM_POINT_SEMANTICS, GPC_CURVE_SEMANTICS, MAX_TEMP_SEMANTICS,
                                                 FACTORY_OFFSET_SEMANTICS) + ADVANCED_SEMANTICS
# GB20x Advanced section: the objects of its tables (BIT P offset -> object), which change only at
# the bytes the canonical Advanced bindings declare.
ADVANCED_OBJECTS = {0xA8: PERF_CF_TABLE[-1], 0xAC: PERF_CF_POLICIES[-1],
                    **{pointer: owner for pointer, owner, *_ in LPWR_TABLES.values()}}
# The only requests that may change otherwise preserved power-row values:
# canonical key -> preserved row attribute it may change. 'linked_limit' is
# the opaque policy7 copy of the 12 V input limit, limited to its own bytes.
PRESERVATION_EXCEPTIONS = {'power_min_w': 'minimum_raw', 'power_default_w': 'default_raw',
                           'input_current_rated_ma': 'default_raw',
                           'nvvdd_output_ocp_rated_ma': 'default_raw', 'msvdd_output_ocp_rated_ma': 'default_raw',
                           'slot_power_rated_w': 'default_raw', 'board_fixed_rated_w': 'default_raw',
                           'slot_current_threshold_rated_ma': 'default_raw',
                           'nvvdd_power_threshold_rated_w': 'default_raw',
                           'input_current_policy7_limit_ma': 'linked_limit',
                           # Ampere/Turing external connector policies, numbered in power-row order, and
                           # their sum (Ampere).
                           **{f'connector_{n}_power_rated_w': 'default_raw' for n in range(1, 5)},
                           'connector_sum_power_rated_w': 'default_raw',
                           **{f'connector_{n}_current_threshold_rated_ma': 'default_raw' for n in range(1, 5)}}
# Fields bound to a top-level override profile -> its (policy, field) entries.
# The tail of the first Ada/Ampere data image (the clock programming table's image) on most
# corpus images: x86 filler (cs: mov eax, eax) and then the checksum byte; others end with a
# tail checksum_tail accepts.
X86_FILLER_TAIL = bytes.fromhex('2e8bc0') * 6 + b'\x8b'
TOP_PROFILE_ENTRIES = {'power_max_w': {(2, 'maximum'), (7, 'maximum'), (8, 'maximum')},
                       'power_default_w': {(8, 'default')}, 'board_fixed_rated_w': {(2, 'default'), (7, 'default')},
                       'input_current_max_ma': {(9, 'maximum')}, 'input_current_rated_ma': {(9, 'default')}}


@dataclass(frozen=True)
class EditResult:
    image: BiosImage
    manifest: dict

    @property
    def blob(self):
        return self.image.blob

    def to_dict(self):
        return dict(self.manifest)


def _amount(value, key):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise VbiosError('INVALID_VALUE', f'{key} requires a finite number')
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise VbiosError('INVALID_VALUE', f'{key} requires a finite number') from exc
    if not amount.is_finite():
        raise VbiosError('INVALID_VALUE', f'{key} requires a finite number')
    return amount


def _within(amount, lo, hi):
    return not ((lo is not None and amount < Decimal(str(lo))) or (hi is not None and amount > Decimal(str(hi))))


def _number(value, binding, *, joint=False):
    """Encode one value; joint requests defer partner-dependent bounds to the result."""
    key, desc = binding.descriptor['key'], binding.descriptor
    amount = _amount(value, key)
    bounds = desc['bounds']
    lo, hi = ((bounds['encoding_minimum'], bounds['encoding_maximum']) if joint else
              (bounds['minimum'], bounds['maximum']))
    if not _within(amount, lo, hi):
        raise VbiosError('OUT_OF_BOUNDS', f'{key} exceeds supported bounds', details={'field': key, 'bounds': desc['bounds']})
    stored = amount * binding.scale
    if stored != stored.to_integral_value():
        raise VbiosError('UNREPRESENTABLE_VALUE', f'{key} is not exact in stored units')
    value = int(stored)
    try:
        encoded = struct.pack(binding.encoding, value)
        decoded = struct.unpack(binding.encoding, encoded)[0]
    except (OverflowError, struct.error) as exc:
        raise VbiosError('UNREPRESENTABLE_VALUE', f'{key} does not fit its encoding') from exc
    if not math.isfinite(decoded) or decoded != value:
        raise VbiosError('UNREPRESENTABLE_VALUE', f'{key} is not exact in its encoding')
    return encoded, decoded


def _reviewed(image, parser):
    result = {}
    for resolver in REVIEWED_RESOLVERS:
        try:
            result.update((b.descriptor['key'], b) for b in resolver(image, parser))
        except VbiosError:
            continue
    return result


def _same(left, right):
    return ((left.offsets, left.encoding, left.scale, left.layout) ==
            (right.offsets, right.encoding, right.scale, right.layout))


def _profile_pairs(profile):
    values = {(e['policy'], e['field']): e['value_raw'] for e in profile['entries']}
    return {policy: (values[(policy, 'default')], values[(policy, 'maximum')])
            for policy, name in values if name == 'default' and (policy, 'maximum') in values}


def _ranges(before, after):
    ranges = []
    for at, (a, b) in enumerate(zip(before, after)):
        if a == b:
            continue
        if ranges and ranges[-1][1] == at:
            ranges[-1][1] += 1
        else:
            ranges.append([at, at + 1])
    return [dict(start=a, end_exclusive=b, before=before[a:b].hex(), after=after[a:b].hex())
            for a, b in ranges]


def edit(image, changes, *, dry_run=False, field_registry=None):
    if not isinstance(image, BiosImage):
        raise VbiosError('INVALID_IMAGE', 'edit requires an immutable BiosImage')
    if not isinstance(changes, dict):
        raise VbiosError('INVALID_CHANGES', 'changes must be an object mapping field keys to values')
    parser = backend(image)
    if not parser.integrity()['valid']:
        raise VbiosError('INTEGRITY_FAILED', 'source integrity failed; refusing edits')
    selected_registry = registry if field_registry is None else field_registry
    if not hasattr(selected_registry, 'bindings'):
        raise VbiosError('INVALID_FIELD_EVIDENCE', 'field_registry must provide bindings')
    bindings, diagnostics = selected_registry.bindings(image, parser)
    available = {b.descriptor['key']: b for b in bindings}
    # Reviewed bindings supply the bounds of their keys; a custom resolver or
    # alias cannot relax them. Only a canonical request with identical encoding
    # and complete offsets enables a narrowly scoped preservation exception.
    reviewed = _reviewed(image, parser)
    canonical = {key: reviewed[key] for key in changes
                 if key in available and key in reviewed and _same(available[key], reviewed[key])}
    # No extension binding with a reviewed key, whatever its offsets or
    # encoding, can unlock a field the reviewed resolver marks read-only.
    for key in changes:
        if key in available and key in reviewed and not reviewed[key].descriptor['editable']:
            raise VbiosError('FIELD_READ_ONLY', f'{key} is read-only', details={'field': reviewed[key].descriptor})
    # A field that depends on a switch (depends_on, the Advanced section) changes only while the
    # switch has the required value, stored or requested in the same edit; its stored value may
    # always be requested again.
    for key in changes:
        dependency = reviewed[key].descriptor.get('depends_on') if key in available and key in reviewed else None
        if not dependency or _amount(changes[key], key) == Decimal(str(reviewed[key].descriptor['current'])):
            continue
        switch = dependency['field']
        stored = reviewed[switch].descriptor['current'] if switch in reviewed else None
        value = changes.get(switch, stored)
        if value is None or _amount(value, switch) != Decimal(str(dependency['value'])):
            raise VbiosError('DEPENDENT_FIELD_DISABLED', f"{key} changes only while {switch} is "
                             f"{dependency['value']}; set {switch} to {dependency['value']} in the same edit",
                             details={'field': key, 'bounds': None, 'depends_on': dict(dependency)})
    # A channel count adds or removes per-channel fan fields, changes the limits every extra
    # curve has to fit and the policy entries fan_zero_rpm covers: change it and the fan
    # limits, curves or zero-RPM flag and temperatures in separate edits.
    per_channel = sorted(k for k in changes if k in reviewed and
                         ({'fan_channel', 'fan_policy'} & set(reviewed[k].descriptor) or k == 'fan_zero_rpm'))
    if 'fan_channels' in changes and per_channel:
        raise VbiosError('SEPARATE_EDIT_REQUIRED', 'change fan_channels and the fan limits, curves or zero-RPM flag '
                         'in separate edits', details={'fields': ['fan_channels'] + per_channel})
    # Moving the REL/ALT selectors changes which equation the voltage fields bind.
    voltages = sorted(k for k in changes if k in available and available[k].descriptor.get('units') == 'mV')
    if 'nvvdd_rel_alt_follow_ov' in changes and voltages:
        raise VbiosError('SEPARATE_EDIT_REQUIRED', 'change nvvdd_rel_alt_follow_ov and the voltage fields in separate '
                         'edits', details={'fields': ['nvvdd_rel_alt_follow_ov'] + voltages})
    for key in changes:
        if (key in available and key in reviewed and
                reviewed[key].descriptor['value_semantics'] in COMPLETE_BINDING_SEMANTICS and key not in canonical):
            raise VbiosError('INVALID_FIELD_EVIDENCE', f'{key} must use the reviewed complete binding')
    exceptions = {}
    for key, attribute in PRESERVATION_EXCEPTIONS.items():
        if key in changes and key in available:
            if key not in canonical:
                raise VbiosError('INVALID_FIELD_EVIDENCE', f'{key} must use the reviewed complete binding')
            exceptions.setdefault(attribute, set()).update(canonical[key].descriptor['policy_indices'])
    # Partners requested together (for example default and maximum) are
    # checked against the reviewed bounds of the joint result after building.
    groups = {}
    for key, binding in canonical.items():
        if binding.descriptor.get('ordering_group'):
            groups.setdefault(binding.descriptor['ordering_group'], set()).add(key)
    joint = {key for keys in groups.values() if len(keys) > 1 for key in keys}
    target, writes, edits, allowed = bytearray(image.blob), [], [], set()
    for key, value in changes.items():
        if key not in available:
            raise VbiosError('UNKNOWN_FIELD', f'unrecognized or unvalidated field {key!r}', details={'diagnostics': diagnostics})
        binding = available[key]
        if not binding.descriptor['editable']:
            raise VbiosError('FIELD_READ_ONLY', f'{key} is read-only', details={'field': binding.descriptor})
        if not binding.descriptor['evidence'] or not binding.offsets or not binding.encoding or binding.scale <= 0:
            raise VbiosError('INVALID_FIELD_EVIDENCE', f'{key} lacks complete encoding/format evidence')
        encoded, decoded = _number(value, canonical.get(key, binding), joint=key in joint)
        chunks = [encoded] * len(binding.offsets)
        if binding.layout:
            # A layout field writes its own bytes per offset for each allowed value.
            chunks = dict(binding.layout).get(decoded)
            if chunks is None or len(chunks) != len(binding.offsets) or any(len(c) != len(encoded) for c in chunks):
                raise VbiosError('OUT_OF_BOUNDS', f'{key} has no stored layout for {decoded}',
                                 details={'field': key, 'bounds': binding.descriptor['bounds']})
        for at, encoded in zip(binding.offsets, chunks):
            size = len(encoded)
            if isinstance(parser, BlackwellRom):
                parser.write_owner(at, size)
            else:
                # All writes must be the same relative field in each structurally
                # validated duplicate chain. Extension resolvers cannot select
                # archive records outside a chain.
                primary_at = at
                for chain in parser.chains:
                    if chain[0]['start'] <= at and at + size <= chain[-1]['end']:
                        primary_at = parser.legacy['start'] + at - chain[0]['start']
                        break
                parser.owner(primary_at, size)
            field_bytes = set(range(at, at + size))
            if allowed & field_bytes:
                raise VbiosError('CONFLICTING_FIELDS', 'requested fields overlap; choose one unit representation')
            allowed.update(field_bytes)
            old = struct.unpack_from(binding.encoding, image.blob, at)[0]
            target[at:at + size] = encoded
            writes.append((at, at + size))
            if target[at:at + size] != image.blob[at:at + size]:
                written = struct.unpack(binding.encoding, encoded)[0] if binding.layout else decoded
                # A layout writes raw table bytes, not the field's value.
                edits.append(dict(field=key, offset=at, before=old, after=written,
                                  stored_units='layout byte' if binding.layout else
                                  binding.descriptor.get('stored_units', binding.descriptor['units'])))
    touched_objects = []
    repairs = []
    if edits:
        if isinstance(parser, BlackwellRom):
            for obj in parser.objects:
                if not any(a < obj['data'] + obj['size'] and obj['data'] < b for a, b in writes):
                    continue
                at = obj['hash_offset']
                target[at:at + 48] = hashlib.sha384(target[obj['data']:obj['data'] + obj['size']]).digest()
                allowed.update(range(at, at + 48))
                touched_objects.append(obj['id'])
                repairs.append(dict(kind='object_sha384', offset=at, object_id=obj['id']))
            directory = parser.directory
            at = directory['digest_offset']
            target[at:at + 48] = hashlib.sha384(target[directory['header']:directory['data_base']]).digest()
            allowed.update(range(at, at + 48))
            repairs.append(dict(kind='directory_sha384', offset=at))
            # Legacy-image writes (write_owner proved a valid legacy directory) repair
            # every legacy object they touch, its directory digest and the legacy checksum.
            legacy = [o for o in parser.legacy_objects if any(a < o['data'] + o['size'] and o['data'] < b
                                                              for a, b in writes)]
            for obj in legacy:
                at = obj['hash_offset']
                target[at:at + 48] = hashlib.sha384(target[obj['data']:obj['data'] + obj['size']]).digest()
                allowed.update(range(at, at + 48))
                repairs.append(dict(kind='object_sha384', offset=at, object_id=obj['id'], directory='legacy'))
            if legacy:
                directory = parser.legacy_directory
                at = directory['digest_offset']
                target[at:at + 48] = hashlib.sha384(target[directory['header']:directory['data_base']]).digest()
                allowed.update(range(at, at + 48))
                repairs.append(dict(kind='directory_sha384', offset=at, directory='legacy'))
        regions = list(parser.image_regions)
        if isinstance(parser, BlackwellRom) and any(parser.legacy['start'] <= a < parser.legacy['end'] for a, _ in writes):
            regions.append((parser.legacy['start'], parser.legacy['end']))
        for start, end in regions:
            if not any(a < end and start < b for a, b in writes) and not any(start <= at < end for at in allowed):
                continue
            if isinstance(parser, BlackwellRom):
                if any(o['data'] <= end - 1 < o['data'] + o['size'] for o in parser.objects + parser.legacy_objects):
                    raise VbiosError('UNSUPPORTED_CHECKSUM_LAYOUT', 'checksum overlaps a hashed object')
            else:
                # The tail is read from the source; a field may write neither it nor the checksum byte.
                tail = checksum_tail(parser.blob, end, parser.family)
                if tail is None and parser.blob[end - 20:end - 1] == X86_FILLER_TAIL:
                    tail = len(X86_FILLER_TAIL)
                if tail is None:
                    raise VbiosError('UNSUPPORTED_CHECKSUM_LAYOUT', 'data image lacks reviewed checksum padding')
                if any(at in allowed for at in range(end - 1 - tail, end - 1)):
                    raise VbiosError('CONFLICTING_FIELDS', 'explicit field overlaps the checksum padding')
            if end - 1 in allowed:
                raise VbiosError('CONFLICTING_FIELDS', 'explicit field overlaps the checksum byte')
            target[end - 1] = (target[end - 1] - sum(target[start:end])) & 255
            allowed.add(end - 1)
            repairs.append(dict(kind='additive_checksum', offset=end - 1))
    output = BiosImage(bytes(target), image.name, image.source_sha256, image.source_path)
    rebuilt = backend(output)
    if not rebuilt.integrity()['valid']:
        raise VbiosError('INTEGRITY_FAILED', 'edited image failed full integrity validation')
    if (rebuilt.pci_images != parser.pci_images or rebuilt.directory != parser.directory or
            rebuilt.objects != parser.objects or rebuilt.tokens != parser.tokens):
        raise VbiosError('IDENTITY_CHANGED', 'edit changed structural identity')
    if isinstance(parser, BlackwellRom):
        if (rebuilt.legacy_directory, rebuilt.legacy_objects) != (parser.legacy_directory, parser.legacy_objects):
            raise VbiosError('IDENTITY_CHANGED', 'edit changed the legacy object directory')
        if parser.legacy_valid() and not rebuilt.legacy_valid():
            raise VbiosError('INTEGRITY_FAILED', 'edited image failed legacy directory validation')
    ranges = _ranges(image.blob, output.blob)
    if any(at not in allowed for r in ranges for at in range(r['start'], r['end_exclusive'])):
        raise VbiosError('UNDECLARED_CHANGE', 'edit changed bytes outside declared fields/integrity bytes')
    # A profile bound at the top level of the selection table (ASUS XOC) must
    # stay bound through the same chain, so later edits keep the same targets.
    from ..rom.errors import FormatError
    source_top = parser.top_power_profile() if isinstance(parser, BlackwellRom) else None
    if source_top is not None:
        try:
            rebuilt.matching_power_profiles()
        except FormatError:
            source_top = None  # a broken power or profile table is reported below, as on other images
    if source_top is not None:
        try:
            target_top = rebuilt.selected_top_profile()
        except FormatError as exc:
            entry = (exc.details.get('policy'), exc.details.get('field'))
            key = next((k for k, entries in TOP_PROFILE_ENTRIES.items() if entry in entries), None)
            key = key if key in changes else next((k for k in sorted(changes) if k in TOP_PROFILE_ENTRIES), key)
            details = {'field': key, 'bounds': None, 'profile': source_top['index'],
                       'joint_fields': sorted(joint or changes)}
            if exc.details.get('ordering'):
                raise VbiosError('OUT_OF_BOUNDS', f'{key} violates the minimum/default/maximum ordering of the '
                                 'joint result', details=details) from None
            reason = ('it would equal the base table and become a matching profile; keep at least one of its values '
                      'below the base table' if source_top['index'] in
                      {p['index'] for p in rebuilt.matching_power_profiles()} else str(exc))
            raise VbiosError('OUT_OF_BOUNDS', 'override profile %d would no longer be the profile selected at the '
                             'top level: %s' % (source_top['index'], reason), details=details) from None
        if target_top['index'] != source_top['index']:
            raise VbiosError('PRESERVED_FIELD_CHANGED', 'the top-level override profile must stay the same')
    # A voltage value moves the bounds of the reviewed voltage fields (VMIN below REL, a fixed REL <= ALT), so
    # with a voltage field in the request every requested reviewed voltage field is checked against the result
    # too, and every other one that was editable must stay so: outside its new range it turns read-only.
    checked, kept = set(joint), set()
    if voltages:
        checked |= {key for key, b in canonical.items() if b.descriptor['units'] == 'mV'}
        kept = {key for key, b in reviewed.items()
                if key not in changes and b.descriptor['units'] == 'mV' and b.descriptor['editable']}
    if checked or kept:
        # A reviewed resolver refuses a result whose minimum/default/maximum
        # ordering is broken, so a missing binding is also out of bounds.
        after_reviewed = _reviewed(output, rebuilt)
        for key in sorted(checked):
            after = after_reviewed.get(key)
            bounds = after.descriptor['bounds'] if after is not None else None
            if (bounds is None or not _within(_amount(changes[key], key), bounds['minimum'], bounds['maximum']) or
                    key not in joint and not after.descriptor['editable']):
                # A field read-only in the result may keep no range to report.
                raise VbiosError('OUT_OF_BOUNDS', f'{key} violates the minimum/default/maximum ordering of the joint result',
                                 details={'field': key, 'bounds': bounds if bounds and bounds['minimum'] is not None
                                          else None, 'joint_fields': sorted(checked)})
        for key in sorted(kept):
            if key not in after_reviewed or not after_reviewed[key].descriptor['editable']:
                raise VbiosError('OUT_OF_BOUNDS', f'{key} would be outside its range in the result; change it in the '
                                 'same edit', details={'field': key, 'bounds': None,
                                                       'joint_fields': sorted(set(changes) | {key})})
    try:
        source_rows = parser.power_rows()
    except FormatError:
        source_rows = None
    if source_rows is not None:
        try:
            target_rows = rebuilt.power_rows()
        except FormatError as exc:
            raise VbiosError('PRESERVED_FIELD_CHANGED', 'edit invalidated a recognized power table') from exc
    if source_rows is not None:
        if len(source_rows) != len(target_rows):
            raise VbiosError('PRESERVED_FIELD_CHANGED', 'power policy count must be preserved')
        minimum_indices = exceptions.get('minimum_raw', set())
        default_indices = exceptions.get('default_raw', set())
        linked_bytes = {at for key, binding in canonical.items()
                        if PRESERVATION_EXCEPTIONS.get(key) == 'linked_limit'
                        for start in binding.offsets for at in range(start, start + 4)}
        if ([r['default_raw'] for i, r in enumerate(source_rows) if i not in default_indices] !=
                [r['default_raw'] for i, r in enumerate(target_rows) if i not in default_indices]):
            raise VbiosError('FACTORY_DEFAULT_CHANGED', 'power factory/rated defaults must be preserved')
        table = parser.pointer('P', 0x2C)
        header_size, stride = image.blob[table + 1:table + 3]
        if image.blob[table:table + header_size] != output.blob[table:table + header_size]:
            raise VbiosError('PRESERVED_FIELD_CHANGED', 'power table header identity must be preserved')
        for index, (left, right) in enumerate(zip(source_rows, target_rows)):
            if index not in minimum_indices and left['minimum_raw'] != right['minimum_raw']:
                raise VbiosError('PRESERVED_FIELD_CHANGED', 'unrequested power minima must be preserved')
            changeable = ({'maximum_raw'} | ({'minimum_raw'} if index in minimum_indices else set()) |
                          ({'default_raw'} if index in default_indices else set()))
            fixed_left = {k: v for k, v in left.items() if k not in changeable}
            fixed_right = {k: v for k, v in right.items() if k not in changeable}
            if fixed_left != fixed_right:
                raise VbiosError('PRESERVED_FIELD_CHANGED', 'power row identity must be preserved')
            # Protect opaque row fields too, including current/rated semantics
            # not exposed as typed fields. Maxima remain available to reviewed
            # extension bindings; minima and rated defaults have only the
            # canonical exceptions.
            row = left['offset']
            maximum_at = row + 21 if isinstance(parser, BlackwellRom) else left['maximum_offset']
            row_allowed = set(range(maximum_at, maximum_at + 4))
            if index in minimum_indices:
                minimum_at = row + 13 if isinstance(parser, BlackwellRom) else maximum_at - 8
                row_allowed.update(range(minimum_at, minimum_at + 4))
            if index in default_indices:
                default_at = row + 17 if isinstance(parser, BlackwellRom) else maximum_at - 4
                row_allowed.update(range(default_at, default_at + 4))
            row_allowed.update(at for at in linked_bytes if row <= at < row + stride)
            if any(image.blob[at] != output.blob[at] and at not in row_allowed
                   for at in range(row, row + stride)):
                raise VbiosError('PRESERVED_FIELD_CHANGED', 'unrequested power row bytes must be preserved')
            if (0 <= left['minimum_raw'] <= left['default_raw'] <= left['maximum_raw'] and
                    not 0 <= right['minimum_raw'] <= right['default_raw'] <= right['maximum_raw']):
                raise VbiosError('PRESERVED_FIELD_CHANGED', 'power minimum/default/maximum ordering must be preserved')
        # Matching max/default overrides are unchanged by a floor-only edit.
        # Profile defaults stay immutable through aliases; only the canonical
        # rated-default bindings may change their own matching-profile entries.
        default_offsets = {at for key, binding in canonical.items()
                           if PRESERVATION_EXCEPTIONS.get(key) == 'default_raw' for at in binding.offsets}
        try:
            source_profiles = parser.power_profiles()
        except FormatError:
            source_profiles = None
        if source_profiles is not None:
            try:
                target_profiles = rebuilt.power_profiles()
            except FormatError as exc:
                raise VbiosError('PRESERVED_FIELD_CHANGED', 'edit invalidated recognized power profiles') from exc
            changeable = lambda e: e['field'] == 'maximum' or e['value_offset'] in default_offsets
            profile_fixed = lambda profiles: [dict(p, entries=[{k: v for k, v in e.items()
                if k != 'value_raw' or not changeable(e)} for e in p['entries']]) for p in profiles]
            if profile_fixed(source_profiles) != profile_fixed(target_profiles):
                raise VbiosError('PRESERVED_FIELD_CHANGED', 'power profile defaults and selectors must be preserved')
            # Profiles matching the base stay matching, and no profile may end up
            # with a policy default above its maximum, whatever bound each edit.
            if not ({p['index'] for p in parser.matching_power_profiles()} <=
                    {p['index'] for p in rebuilt.matching_power_profiles()}):
                raise VbiosError('PRESERVED_FIELD_CHANGED', 'matching override profiles must stay matching')
            for before, after in zip(source_profiles, target_profiles):
                for policy, (default, maximum) in _profile_pairs(before).items():
                    if default <= maximum and not _profile_pairs(after)[policy][0] <= _profile_pairs(after)[policy][1]:
                        raise VbiosError('OUT_OF_BOUNDS', 'override profile default must not exceed its maximum',
                                         details={'profile': after['index'], 'policy': policy})
            profile_table = parser.profile_table() if hasattr(parser, 'profile_table') else (
                parser.pointer('P', 0xF4) if parser.tokens['P']['size'] >= 0xF8 else None)
            if profile_table is not None:
                profile_allowed = {at for p in source_profiles for e in p['entries'] if changeable(e)
                                   for at in range(e['value_offset'], e['value_offset'] + 4)}
                if any(image.blob[at] != output.blob[at] and at not in profile_allowed
                       for at in range(profile_table, profile_table + 0xFE + 16 * 0x49)):
                    raise VbiosError('PRESERVED_FIELD_CHANGED', 'power profile metadata and opaque bytes must be preserved')
    # Clock rows keep their identity, and every range that contained a zero
    # offset still contains it, including simultaneous minimum/maximum edits.
    # An Ampere or Turing range stored as 0..0 reads as disabled (read-only), so an
    # edit may not collapse a wider one to 0..0: it could not be reverted.
    try:
        source_clocks = parser.clock_ranges()
    except FormatError:
        source_clocks = None
    if source_clocks is not None:
        try:
            target_clocks = rebuilt.clock_ranges()
        except FormatError as exc:
            raise VbiosError('PRESERVED_FIELD_CHANGED', 'edit invalidated a recognized clock table') from exc
        identity = lambda rows: [{k: v for k, v in r.items() if k not in ('minimum_mhz', 'maximum_mhz')} for r in rows]
        if identity(source_clocks) != identity(target_clocks):
            raise VbiosError('PRESERVED_FIELD_CHANGED', 'clock row identity must be preserved')
        for left, right in zip(source_clocks, target_clocks):
            if left['minimum_mhz'] <= 0 <= left['maximum_mhz'] and not right['minimum_mhz'] <= 0 <= right['maximum_mhz']:
                raise VbiosError('OUT_OF_BOUNDS', 'clock offset ranges must keep minimum <= 0 <= maximum',
                                 details={'clock_row': right['row'], 'domain': right['domain']})
            family = getattr(parser, 'family', None)
            if (family in ('ampere', 'turing') and (left['minimum_mhz'], left['maximum_mhz']) != (0, 0)
                    and (right['minimum_mhz'], right['maximum_mhz']) == (0, 0)):
                article = 'an Ampere' if family == 'ampere' else 'a Turing'
                raise VbiosError('OUT_OF_BOUNDS', f'{article} clock offset range must not collapse to '
                                 '0..0 (it would read as disabled and become read-only)',
                                 details={'clock_row': right['row'], 'domain': right['domain']})
    # Only the canonical REL/ALT follow-OV field moves the NVVDD REL and ALT selectors.
    moved = ({('NVVDD', 'REL'), ('NVVDD', 'ALT')} if any(b.descriptor['value_semantics'] == FOLLOW_OV_SEMANTICS
                                                         for b in canonical.values()) else set())
    # Only the canonical fixed REL/ALT fields change an equation's constant (with its clamp maximum).
    fixed_bytes = {at for binding in canonical.values() if binding.descriptor['value_semantics'] == FIXED_SEMANTICS
                   for start in binding.offsets for at in range(start, start + 4)}
    try:
        source_rails = parser.rail_limits()
    except FormatError:
        source_rails = None
    if source_rails is not None:
        try:
            target_rails = rebuilt.rail_limits()
        except FormatError as exc:
            raise VbiosError('PRESERVED_FIELD_CHANGED', 'edit invalidated a recognized rail table') from exc
        if len(source_rails) != len(target_rails):
            raise VbiosError('PRESERVED_FIELD_CHANGED', 'editing rail identity is unsupported')
        for source_rail, target_rail in zip(source_rails, target_rails):
            if (source_rail['rail_name_inferred'], 'REL') in moved:
                continue  # the declared selector bytes alone changed; its old equation is checked below
            # The coefficient bytes are compared instead, except a declared fixed-value constant.
            values = ('output_maximum_uv', 'equation_coefficients')
            source_fixed = {k: v for k, v in source_rail.items() if k not in values}
            target_fixed = {k: v for k, v in target_rail.items() if k not in values}
            at = source_rail['maximum_offset'] + 4
            if source_fixed != target_fixed or any(image.blob[i] != output.blob[i] and i not in fixed_bytes
                                                   for i in range(at, at + 12)):
                raise VbiosError('PRESERVED_FIELD_CHANGED', 'rail minima, identity and equation coefficients must be preserved')
    # All recognized extended equations preserve selectors, boot values and the
    # entire expression payload except the explicitly editable maximum float.
    # This covers constant/other equation kinds without interpreting their bytes
    # as quadratic coefficients and catches changes through shared references.
    if metadata_family := getattr(parser, 'family', None):
        extended_roles = metadata_family in ('ada', 'ampere', 'turing')
    else:
        extended_roles = isinstance(parser, BlackwellRom)
    if extended_roles:
        try:
            source_roles = parser.rail_equations()
        except FormatError:
            source_roles = None
        if source_roles is not None:
            try:
                target_roles = rebuilt.rail_equations()
            except FormatError as exc:
                raise VbiosError('PRESERVED_FIELD_CHANGED', 'edit invalidated extended rail selectors') from exc
            if len(source_roles) != len(target_roles):
                raise VbiosError('PRESERVED_FIELD_CHANGED', 'rail role identity changed')
            for left, right in zip(source_roles, target_roles):
                left_fixed = {k: v for k, v in left.items() if k != 'output_maximum_uv'}
                right_fixed = {k: v for k, v in right.items() if k != 'output_maximum_uv'}
                if (left['logical_rail_id'], left['role']) not in moved and left_fixed != right_fixed:
                    raise VbiosError('PRESERVED_FIELD_CHANGED', 'role selectors, boot and equation minima must be preserved')
                at = left['equation_offset']
                if at is not None:
                    width = left['equation_size']
                    if any(image.blob[i] != output.blob[i] and i not in fixed_bytes
                           for i in (*range(at, at + 7), *range(at + 11, at + width))):
                        raise VbiosError('PRESERVED_FIELD_CHANGED', 'equation expression bytes must be preserved')
            # Turing: no field writes the equation the boot voltage selector (1x row byte 8) picks.
            for item in parser.rail_boot_equations() if hasattr(parser, 'rail_boot_equations') else ():
                at, width = item['equation_offset'], item['equation_size']
                if image.blob[at:at + width] != output.blob[at:at + width]:
                    raise VbiosError('PRESERVED_FIELD_CHANGED', 'the boot voltage equation bytes must be preserved',
                                     details={'rail': item['logical_rail_id']})
    # The rail table (legacy image; Ada/Ampere/Turing: of every chain) changes only at the REL/ALT selector
    # bytes of the canonical follow-OV binding; the role checks above cover its selectors and boot values again.
    try:
        rail, length = parser.rail_table()
        tables = [rail] if isinstance(parser, BlackwellRom) else parser.copy_offsets(rail, length)
    except FormatError:
        tables, length = [], 0
    follow = {at for binding in canonical.values() if binding.descriptor['value_semantics'] == FOLLOW_OV_SEMANTICS
              for start in binding.offsets for at in range(start, start + struct.calcsize(binding.encoding))}
    if any(image.blob[i] != output.blob[i] and i not in follow for start in tables for i in range(start, start + length)):
        raise VbiosError('PRESERVED_FIELD_CHANGED', 'rail table bytes must be preserved')
    # The evaluated VMIN selector stays, and its equation changes only at the floats
    # the canonical *_vmin_mv binding declares (GB20x minimum, maximum and value;
    # Ada/Ampere clamp minimum and maximum).
    try:
        source_vmin = parser.rail_vmin() if hasattr(parser, 'rail_vmin') else None
    except FormatError:
        source_vmin = None
    if source_vmin is not None:
        try:
            target_vmin = rebuilt.rail_vmin()
        except FormatError as exc:
            raise VbiosError('PRESERVED_FIELD_CHANGED', 'edit invalidated the evaluated VMIN selectors') from exc
        vmin_bytes = {at for binding in canonical.values() if binding.descriptor['value_semantics'] == VMIN_SEMANTICS
                      for start in binding.offsets for at in range(start, start + 4)}
        for left, right in zip(source_vmin, target_vmin):
            at = left['equation_offset']
            if (left['selector_raw'], at) != (right['selector_raw'], right['equation_offset']) or left['pinned'] and any(
                    image.blob[i] != output.blob[i] and i not in vmin_bytes for i in range(at, at + left['equation_size'])):
                raise VbiosError('PRESERVED_FIELD_CHANGED', 'the evaluated VMIN selector and equation bytes must be '
                                 'preserved', details={'rail': left['logical_rail_id']})
    # The GPC curve root equation and the VFE slot of its offset (linked or first unused) change only
    # at the bytes the canonical gpc_curve_offset_mhz binding declares, in every chain.
    try:
        source_curve = parser.gpc_curve() if hasattr(parser, 'gpc_curve') else None
    except FormatError:
        source_curve = None
    if source_curve is not None:
        curve_bytes = {at for binding in canonical.values() if binding.descriptor['value_semantics'] == GPC_CURVE_SEMANTICS
                       for start in binding.offsets for at in range(start, start + struct.calcsize(binding.encoding))}
        size, starts = source_curve['size'], (source_curve['root_offset'], source_curve['slot_offset'])
        if not isinstance(parser, BlackwellRom):
            starts = [copy for at in starts for copy in parser.copy_offsets(at, size)]
        if any(image.blob[i] != output.blob[i] and i not in curve_bytes for start in starts for i in range(start, start + size)):
            raise VbiosError('PRESERVED_FIELD_CHANGED', 'the GPC curve root and offset slot bytes must be preserved')
    # The per-fan-channel tables change only through the reviewed fan fields,
    # and only at the bytes their bindings declare: the PWM frequency bytes,
    # the channel list/enable bytes, the row limits of the active channels,
    # the points of the enabled curves, the policy entry flag bytes (0x32)
    # fan_zero_rpm covers and the zero RPM temperature pairs (bytes 30..33) of
    # the enabled entries. They must still decode and agree afterwards. Tables
    # that do not decode or agree accept no change at all.
    regions = parser.fan_regions() if hasattr(parser, 'fan_regions') else []
    if regions:
        try:
            source_fans = parser.fan_coolers()
        except FormatError:
            source_fans = None
        fan_allowed = set()
        if source_fans is not None:
            try:
                target_fans = rebuilt.fan_coolers()
            except FormatError as exc:
                raise VbiosError('PRESERVED_FIELD_CHANGED', 'edit invalidated recognized fan tables') from exc
            names = ('offset', 'policy_offset', 'mapping_offset', 'control_offset', 'speed_offset')
            if target_fans is None or any(target_fans[k] != source_fans[k] for k in names):
                raise VbiosError('PRESERVED_FIELD_CHANGED', 'edit invalidated recognized fan tables')
            for key in changes:
                binding = canonical.get(key)
                if binding is not None and binding.descriptor.get('value_semantics', '').startswith('stored-fan-'):
                    size = struct.calcsize(binding.encoding)
                    fan_allowed.update(at for start in binding.offsets for at in range(start, start + size))
        if any(image.blob[at] != output.blob[at] and at not in fan_allowed
               for start, size in regions for at in range(start, start + size)):
            raise VbiosError('PRESERVED_FIELD_CHANGED', 'fan table bytes must be preserved')
    # GB20x: the object holding the thermal policy table (0x1b) and the one holding the factory
    # clock record (0x26) change only at the bytes the canonical max_operating_temp_c and
    # factory_gpc_offset_mhz bindings declare, whatever the field registry, decoded or not.
    if isinstance(parser, BlackwellRom):
        for semantics, pointer, owner, noun in ((MAX_TEMP_SEMANTICS, 0x50, 0x1B, 'thermal policy table'),
                                                (FACTORY_OFFSET_SEMANTICS, 0x98, 0x26, 'factory clock record')):
            try:
                obj = parser.object_for(parser.pointer('P', pointer))
            except FormatError:
                continue
            if obj['id'] != owner:
                continue
            declared = {at for binding in canonical.values() if binding.descriptor['value_semantics'] == semantics
                        for start in binding.offsets for at in range(start, start + struct.calcsize(binding.encoding))}
            if any(image.blob[at] != output.blob[at] and at not in declared
                   for at in range(obj['data'], obj['data'] + obj['size'])):
                raise VbiosError('PRESERVED_FIELD_CHANGED', f'{noun} bytes must be preserved')
        # The objects of the PERF_CF and LPWR tables change only at the bytes the canonical Advanced
        # bindings declare (on the RTX PRO 4000 SFF object 0x60 also covers the policy table header).
        declared = {at for binding in canonical.values() if binding.descriptor['value_semantics'] in ADVANCED_SEMANTICS
                    for start in binding.offsets for at in range(start, start + struct.calcsize(binding.encoding))}
        for pointer, owner in ADVANCED_OBJECTS.items():
            try:
                at = parser.pointer('P', pointer)
            except FormatError:
                continue
            for obj in parser.objects:
                if obj['id'] == owner and obj['data'] <= at < obj['data'] + obj['size'] and any(
                        image.blob[i] != output.blob[i] and i not in declared
                        for i in range(obj['data'], obj['data'] + obj['size'])):
                    raise VbiosError('PRESERVED_FIELD_CHANGED', f'object {owner:#x} bytes (PERF_CF or LPWR table) '
                                     'must be preserved')
        # PERF_CF: a reviewed utilization controller whose target was below its jump threshold keeps it so.
        try:
            source_cf, target_cf = parser.perf_cf(), rebuilt.perf_cf()
        except FormatError:
            source_cf = target_cf = None
        if source_cf is not None and target_cf is not None:
            for index, part, *_ in PERF_CF_CONTROLLERS:
                left, right = (t['controllers']['entries'][index] for t in (source_cf, target_cf))
                if (fxp_percent(left['target_raw']) < fxp_percent(left['jump_raw']) and
                        not fxp_percent(right['target_raw']) < fxp_percent(right['jump_raw'])):
                    keys = [k for k in (f'perf_cf_{part}_target_pct', f'perf_cf_{part}_jump_pct') if k in changes]
                    raise VbiosError('OUT_OF_BOUNDS', f'the {part} utilization target must stay below its jump '
                                     'threshold', details={'field': keys[0] if keys else None, 'bounds': None,
                                                           'joint_fields': sorted(keys)})
    before, after = inspect_image(image), inspect_image(output)
    if before['versions'] != after['versions']:
        raise VbiosError('IDENTITY_CHANGED', 'editing BIOS identity is unsupported')
    # Independent post-reparse validation checks the requested field value and
    # preserves every unrequested known field (and all unmentioned raw bytes).
    after_bindings, _ = selected_registry.bindings(output, rebuilt)
    before['fields'] = [dict(b.descriptor) for b in bindings]
    after['fields'] = [dict(b.descriptor) for b in after_bindings]
    by_after = {f['key']: f for f in after['fields']}
    for key, value in changes.items():
        if (key not in by_after or by_after[key]['current'] is None or
                Decimal(str(by_after[key]['current'])) != Decimal(str(value))):
            raise VbiosError('POSTCONDITION_FAILED', f'{key} did not survive format reparse')
    before_fields = {f['key']: f for f in before['fields']}
    affected_fields = [dict(field=key, before=before_fields[key]['current'], after=value['current'],
                            units=value['units'], requested=key in changes)
                       for key, value in by_after.items() if key in before_fields and
                       before_fields[key]['current'] != value['current']]
    rated_changes = sorted({e['field'] for e in edits if PRESERVATION_EXCEPTIONS.get(e['field']) == 'default_raw'})
    manifest = dict(schema_version=1, operation='plan' if dry_run else 'edit',
                    source=image.name, source_sha256=image.sha256, original_source_sha256=image.source_sha256,
                    output_sha256=output.sha256, size=len(output.blob), pci_device=after['pci_device'],
                    format=after['format'], requested={key: str(value) for key, value in changes.items()},
                    edits=edits, affected_fields=affected_fields, integrity_repairs=repairs, changed_object_ids=sorted(touched_objects),
                    changed_bytes=sum(r['end_exclusive'] - r['start'] for r in ranges), byte_ranges=ranges,
                    before={'fields': before['fields'], 'sha256': image.sha256},
                    after={'fields': after['fields'], 'sha256': output.sha256}, integrity=after['integrity'],
                    preservation={'factory_defaults': not rated_changes, 'changed_rated_defaults': rated_changes,
                                  'identity_and_unknown_bytes': True,
                                  'temperature_coefficients': True, 'archive_tail': True},
                    runtime_validation={'new_edit_hardware_tested': False,
                                        'source_hardware_tested': None},
                    cryptographic_signatures='not verified or regenerated')
    return EditResult(output, manifest)


def plan(image, changes, *, field_registry=None):
    """Fully build and verify staged bytes and a manifest, without filesystem I/O."""
    return edit(image, changes, dry_run=True, field_registry=field_registry)


def _save(result, path, *, manifest=None):
    """Publish complete bytes and optional JSON using exclusive hard links.

    Existing destinations, symlinks, source paths, and hard-link aliases are
    refused. If JSON publication fails, only our newly linked ROM is rolled back.
    """
    if isinstance(result, EditResult):
        image, manifest = result.image, result.manifest if manifest is None else manifest
    elif isinstance(result, BiosImage):
        image = result
    else:
        raise VbiosError('INVALID_IMAGE', 'save requires BiosImage or EditResult')
    try:
        output = Path(path)
    except (TypeError, ValueError) as exc:
        raise VbiosError('INVALID_PATH', 'output must be a filesystem path') from exc
    report = output.with_name(output.name + '.json') if manifest is not None else None
    paths = [output] + ([] if report is None else [report])
    if image.source_path and Path(image.source_path).resolve() in [p.resolve() for p in paths]:
        raise VbiosError('SOURCE_OVERWRITE', 'output must not overwrite the source ROM')
    for p in paths:
        if p.exists() or p.is_symlink():
            raise VbiosError('OUTPUT_EXISTS', f'refusing to overwrite {p}')
    # Editing retains the original file provenance across staged operations.
    if image.source_path:
        try:
            actual = hashlib.sha256(Path(image.source_path).read_bytes()).hexdigest()
        except OSError as exc:
            raise VbiosError('IO_ERROR', f'cannot verify original source: {exc}') from exc
        if actual != image.source_sha256:
            raise VbiosError('SOURCE_CHANGED', 'original source changed since load')
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.vbios-save-', dir=output.parent) as tmp:
            rom = Path(tmp) / 'image'
            with rom.open('wb') as stream:
                stream.write(image.blob)
                stream.flush()
                os.fsync(stream.fileno())
            if report is not None:
                text = Path(tmp) / 'manifest'
                with text.open('w', encoding='utf-8') as stream:
                    json.dump(dict(manifest, output=str(output)), stream, indent=2, allow_nan=False)
                    stream.write('\n')
                    stream.flush()
                    os.fsync(stream.fileno())
            created = []
            try:
                created.append(_publish(rom, output, image.blob))
                if report is not None:
                    created.append(_publish(text, report, text.read_bytes()))
                for item in created:
                    item.close()
            except BaseException as exc:
                _raise_if_left(exc, [item.path for item in reversed(created) if not item.remove()])
                raise
    except FileExistsError as exc:
        kept = getattr(exc, 'incomplete', None)
        raise VbiosError('OUTPUT_EXISTS', f'refusing to overwrite {exc.filename}'
                         + (f'; could not remove the incomplete {kept}' if kept else '')) from exc
    except (OSError, TypeError, ValueError) as exc:
        raise VbiosError('IO_ERROR', f'cannot save ROM: {exc}') from exc
    return {'schema_version': 1, 'output': str(output), 'sha256': image.sha256,
            'manifest': None if report is None else str(report)}


_WINDOWS = os.name == 'nt'  # open files cannot be removed; others cannot remove ours


class _Created:
    """A file this save published: an exclusive copy (open until closed) or a hard link."""

    def __init__(self, path, data, source):
        self.path, self.data, self.source = path, data, source
        self.handle = self.stat = None

    def ours(self, content=True):
        """Whether path is still this file and, with content, holds exactly its bytes.

        An open copy is provably ours (POSIX keeps its inode; Windows lets nobody
        else delete or rename it); a closed copy and a hard link are compared with
        the identity recorded at close and with the private temporary source.
        """
        if self.handle is not None:
            same = _WINDOWS or os.path.samestat(os.fstat(self.handle.fileno()), os.lstat(self.path))
        else:
            same = os.path.samestat(self.stat or os.stat(self.source), os.lstat(self.path))
        return same and (not content or Path(self.path).read_bytes() == self.data)

    def close(self):
        """Close an exclusive copy; the file is closed even when this raises."""
        if self.handle is not None:
            handle, self.handle = self.handle, None
            self.stat = os.fstat(handle.fileno())
            handle.close()

    def remove(self, content=True):
        """Remove the file while it is still ours; False only when ours but not removed."""
        try:
            ours = self.ours(content)
        except FileNotFoundError:
            ours = False
        except OSError:
            ours = None
        if ours and not _WINDOWS and self.handle is not None:
            removed = _unlink(self.path)  # POSIX: unlink while the open file pins the inode
            self._close_quietly()
            return removed
        self._close_quietly()  # Windows cannot remove a file that is still open
        if ours is None:
            return False
        return _unlink(self.path) if ours else True

    def _close_quietly(self):
        try:
            self.close()
        except Exception:
            pass  # the handle is closed; a failed flush of a discarded copy does not matter


def _publish(source, target, data):
    """Create target from source without overwriting anything; return it as _Created.

    A hard link publishes the complete file at once. Without hard links (FAT/exFAT
    drives, some network shares) target is an exclusive copy kept open until the
    save closes it. A copy that fails is removed before the error is raised.
    """
    created = _Created(target, data, source)
    try:
        os.link(source, target)
        return created
    except FileExistsError:
        raise
    except OSError:
        pass
    with open(source, 'rb') as stream:
        created.handle = open(target, 'xb')
        try:
            shutil.copyfileobj(stream, created.handle)
            created.handle.flush()
            os.fsync(created.handle.fileno())
        except BaseException as exc:
            _raise_if_left(exc, [] if created.remove(content=False) else [target])
            raise
    return created


def _unlink(path):
    # Windows scanners may hold a new file briefly; retry before giving up.
    for attempt in range(5 if _WINDOWS else 1):
        try:
            os.unlink(path)
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            if attempt < 4 and _WINDOWS:
                time.sleep(0.1)
        except OSError:
            break
    return False


def _raise_if_left(exc, left):
    """Name the files this save created but could not remove in the error."""
    if not left or not isinstance(exc, OSError):
        return
    paths = ', '.join(str(path) for path in left)
    if isinstance(exc, FileExistsError):  # stays OUTPUT_EXISTS for the path that existed
        error = FileExistsError(exc.errno, exc.strerror, exc.filename)
        error.incomplete = paths
        raise error from exc
    raise OSError(exc.errno, f'{exc.strerror or exc}; could not remove the incomplete {paths}') from exc


def normalize_manifest(source, result, representation, source_label):
    """Manifest of a normalize export: the source image, the exported payload and how to re-verify it."""
    note = 'Transport export only. Deployment must bind and verify the original archival board identity.'
    if representation in ('ada-relocated-v2', 'ampere-relocated-v1'):
        recognized = 'do not' if representation == 'ada-relocated-v2' else 'may not'
        note = ('Experimental, not hardware validated. Verified only while exporting from the source ROM; '
                f'inspect and verify {recognized} recognize this payload, so re-run normalize on the source to '
                're-verify. ' + note)
    elif representation == 'turing-e0-end-v1':
        note = ('Experimental, not hardware validated. The chain ends at its last data image: the type-0x70 image '
                'and the bytes after it are dropped and two last-image flags are set. ' + note)
    return dict(schema_version=1, operation='normalize', representation=representation,
                source=str(source_label), source_sha256=source.sha256, source_size=len(source.blob),
                output_sha256=result.sha256, output_size=len(result.blob),
                archival_identity_checked=False, note=note)


def save(result, path, *, manifest=None):
    """Publish without overwrite; normalize filesystem failures to API errors."""
    try:
        return _save(result, path, manifest=manifest)
    except VbiosError:
        raise
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        raise VbiosError('IO_ERROR', f'cannot save ROM: {exc}') from exc
