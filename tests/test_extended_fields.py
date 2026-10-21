"""Extended offline fields: synthetic public images and opt-in reference ROMs."""
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nvidia_vbios.editor import edit, plan
from nvidia_vbios.rom import from_bytes, inspect_image, load, VbiosError
from nvidia_vbios.rom.image import backend
from test_rom_formats import synthetic_blackwell, synthetic_rom


def repair_fixture(blob):
    """Rehash/checksum a generated test image after shaping its known fields."""
    parsed = backend(from_bytes(blob))
    for obj in parsed.objects:
        blob[obj['hash_offset']:obj['hash_offset'] + 48] = hashlib.sha384(
            blob[obj['data']:obj['data'] + obj['size']]).digest()
    d = parsed.directory
    blob[d['digest_offset']:d['digest_offset'] + 48] = hashlib.sha384(
        blob[d['header']:d['data_base']]).digest()
    for p in parsed.pci_images + parsed.extended_images:
        blob[p['end'] - 1] = (blob[p['end'] - 1] - sum(blob[p['start']:p['end']])) & 255
    return bytes(blob)


def extended_fixture(*, absent_alt=False, shared=False, high_index=False, unknown_equation=False):
    blob = bytearray(synthetic_blackwell())
    original = backend(from_bytes(blob))
    if high_index:
        # Extend actual image/object boundaries, without a fixed-size parser pin.
        blob = blob[:28160] + bytearray(8192) + blob[28160:]
        p = original.extended_images[0]
        struct.pack_into('<H', blob, p['npds'] + 16, (p['size'] + 8192) // 512)
        vfe_owner = next(o for o in original.objects if o['id'] == 0x14)
        struct.pack_into('<I', blob, vfe_owner['header'] + 8, vfe_owner['size'] + 8192)
        blob[p['end'] - 1] = 0
    parsed = backend(from_bytes(blob))
    rail, vfe = parsed.pointer('P', 0x68), parsed.pointer('P', 0x20)
    base = vfe + blob[vfe + 1] + blob[vfe + 2] * blob[vfe + 3]
    for i in range(2):
        row = rail + 5 + 65 * i
        selectors = (0, 1, 2, 3) if i == 0 else ((263, 264, 266, 265) if high_index else (4, 5, 6, 7))
        if shared and i == 0:
            selectors = (0, 1, 0, 3)
        for role, index, offset in zip(('REL', 'ALT', 'OV', 'VMIN'), selectors, (13, 15, 17, 33)):
            struct.pack_into('<H', blob, row + offset, 0xFFFF if absent_alt and role == 'ALT' else index)
            at = base + 25 * index
            blob[at:at + 25] = bytes(25)
            blob[at:at + 3] = bytes((1, 0xFF, 0xFF))
            minimum, maximum = (-20000, -10000) if role == 'ALT' else (900000, 1000000)
            struct.pack_into('<ff', blob, at + 3, minimum, maximum)
            struct.pack_into('<fff', blob, at + 11, 1200000, -1000, 0)
            blob[at + 23] = 2
        struct.pack_into('<I', blob, row + 25, 800000 if i == 0 else 1000000)
    if unknown_equation:
        # A common-looking output prefix with an unreviewed equation kind is read-only.
        blob[base + 25] = 0xFE
    rows = parsed.power_rows()
    for i, index in enumerate((13, 14)):
        at = rows[index]['offset']
        blob[at:at + 102] = bytes(102)
        blob[at] = 7
        struct.pack_into('<I', blob, at + 1, 1)
        blob[at + 5] = 13 if i == 0 else 12
        struct.pack_into('<I', blob, at + 6, 1)
        rated = 90000 if i == 0 else 60000
        struct.pack_into('<III', blob, at + 13, 1, rated, rated)
        blob[at + 32:at + 37] = bytes((0, i, i, 11 + i, 11 + i))
    return repair_fixture(blob)


LINKED_ROW7 = {1: 72, 2: 1, 6: 1, 33: 9, 37: 128, 41: 54, 50: 255, 54: 1, 57: 1}


def set_device(blob, device):
    """Rewrite the PCI, chip and directory identity of a synthetic Blackwell image."""
    parsed = backend(from_bytes(bytes(blob)))
    struct.pack_into('<H', blob, parsed.legacy['pcir'] + 6, device)
    struct.pack_into('<I', blob, parsed.directory['header'] + 12, device)
    struct.pack_into('<H', blob, parsed.meta['pcir'] + 6, device & 0xFF80)
    struct.pack_into('<H', blob, parsed.extended_images[0]['npds'] + 6, device & 0xFF80)


def sff_fixture(*, device=0x2C33, unit=0, monitor=1):
    """Input fixture on the SFF identity with the reviewed row19 slot-power shape."""
    blob = bytearray(input_fixture(device=device))
    at = backend(from_bytes(bytes(blob))).power_rows()[19]['offset']
    blob[at:at + 102] = bytes(102)
    for offset, value in {0: 2, 1: unit, 5: monitor, 6: 1, 33: 10, 34: 10}.items():
        blob[at + offset] = value
    struct.pack_into('<III', blob, at + 13, 1, 66000, 66000)
    return repair_fixture(blob)


def input_fixture(*, unit=1, monitor=9, device=None, extra=None, linked=True, minimum=1, profiles=1):
    """Shape row9 like the reviewed 12 V input policy, keeping the profile matching.

    Row 7 gets the reviewed linked-limit shape unless linked is false. With
    profiles=0 the override profile is cleared; with 2 it is duplicated.
    """
    blob = bytearray(extended_fixture())
    if device is not None:
        set_device(blob, device)
    parsed = backend(from_bytes(bytes(blob)))
    rows = parsed.power_rows()
    at = rows[9]['offset']
    blob[at:at + 102] = bytes(102)
    blob[at:at + 2] = bytes((11, unit))
    blob[at + 5:at + 7] = bytes((monitor, 1))
    struct.pack_into('<III', blob, at + 13, minimum, 80000, 80000)
    if extra is not None:
        blob[at + extra] = 1
    if linked:
        row7 = rows[7]['offset']
        for offset, value in LINKED_ROW7.items():
            blob[row7 + offset] = value
        struct.pack_into('<I', blob, row7 + 61, 80000)
    profile = parsed.power_profiles()[0]
    for entry in profile['entries']:
        if entry['policy'] == 9:
            struct.pack_into('<I', blob, entry['value_offset'], 80000)
    if profiles == 0:
        blob[profile['offset']:profile['offset'] + 0x49] = bytes(0x49)
    elif profiles == 2:
        blob[profile['offset'] + 0x49:profile['offset'] + 0x92] = blob[profile['offset']:profile['offset'] + 0x49]
    return repair_fixture(blob)


def changed_bytes_within(test, image, result, offsets, width=4):
    allowed = {at for start in offsets for at in range(start, start + width)}
    for repair in result.manifest['integrity_repairs']:
        count = 48 if 'sha384' in repair['kind'] else 1
        allowed.update(range(repair['offset'], repair['offset'] + count))
    test.assertLessEqual({i for i, (a, b) in enumerate(zip(image.blob, result.blob)) if a != b}, allowed)


def custom_registry(key, offsets, *, encoding='<I', scale=1000, bounds=None, include=()):
    """One extension binding over reviewed bytes, used to probe the guards."""
    from decimal import Decimal
    from nvidia_vbios.editor import Binding, FieldRegistry
    custom = FieldRegistry()
    for resolver in include:
        custom.register(resolver)

    @custom.register
    def probe(image, parser):
        current = Decimal(struct.unpack_from(encoding, image.blob, offsets[0])[0]) / scale
        descriptor = dict(key=key, label='probe', type='number', units='probe', current=float(current),
                          bounds=bounds or {'minimum': -100000, 'maximum': 100000}, editable=True,
                          evidence=[{'kind': 'synthetic-test'}])
        return [Binding(descriptor, tuple(offsets), encoding, Decimal(scale))]
    return custom


def descriptors(image):
    return {f['key']: f for f in inspect_image(image)['fields']}


def curve_step(field):
    """A fan curve point one stored step away (1/32 C, 1 RPM or 1 %): up, or down at its upper bound."""
    step = Decimal(1) / 32 if field['units'] == 'C' else Decimal(1)
    current = Decimal(str(field['current']))
    return current + step if current + step <= Decimal(str(field['bounds']['maximum'])) else current - step


class ExtendedFieldTests(unittest.TestCase):
    def test_full_u16_selectors_bounds_and_separate_namespaces(self):
        image = from_bytes(extended_fixture(high_index=True))
        fields = descriptors(image)
        for role, index in (('rel', 263), ('alt', 264), ('ov', 266), ('vmin', 265)):
            field = fields[f'msvdd_{role}_equation_max_mv']
            self.assertEqual(field['selector']['raw'], index)
            self.assertEqual(field['selector']['width_bits'], 16)
            # The rail INFO VMIN slot is shown but never edited (see test_rail_vmin).
            self.assertEqual(field['editable'], role != 'vmin')
            if role == 'vmin':
                continue
            self.assertEqual(field['capability']['vbios']['writable'], 'verified')
            self.assertEqual(field['capability']['runtime']['writable'], 'unknown')
            self.assertEqual(field['capability']['runtime']['persistence'], 'unknown')
            self.assertIsNone(field['capability']['runtime']['evaluated_value'])
        ocp = fields['msvdd_output_ocp_max_ma']
        self.assertEqual(ocp['rail_identity']['logical_rail_id'], 'MSVDD')
        self.assertEqual(ocp['rail_identity']['api_rail_index'], 1)
        self.assertEqual(ocp['rail_identity']['power_monitor_rail_id'], 16)
        self.assertEqual(ocp['rail_identity']['vbios_policy_index'], 14)
        self.assertEqual(ocp['monitor']['index'], 12)
        self.assertEqual(ocp['policy_types'], {'vbios': 7, 'rm': 18, 'api': 19})
        json.dumps(inspect_image(image), allow_nan=False)

    def test_declared_bytes_hash_repairs_other_policies_and_curves_preserved(self):
        image = from_bytes(extended_fixture(high_index=True))
        source = backend(image)
        result = edit(image, {'msvdd_ov_equation_max_mv': 1100, 'nvvdd_output_ocp_max_ma': 100000})
        target = backend(result.image)
        self.assertTrue(target.integrity()['valid'])
        self.assertEqual(target.power_rows()[9], source.power_rows()[9])
        for i in range(20):
            before, after = source.power_rows()[i], target.power_rows()[i]
            self.assertEqual(before['minimum_raw'], after['minimum_raw'])
            self.assertEqual(before['default_raw'], after['default_raw'])
            if i != 13:
                self.assertEqual(before, after)
        records = source.rail_equations()
        selected = next(r for r in records if r['logical_rail_id'] == 'MSVDD' and r['role'] == 'OV')
        write_offsets = [selected['maximum_offset'], source.power_rows()[13]['offset'] + 21]
        allowed = {at for start in write_offsets for at in range(start, start + 4)}
        for repair in result.manifest['integrity_repairs']:
            count = 48 if 'sha384' in repair['kind'] else 1
            allowed.update(range(repair['offset'], repair['offset'] + count))
        changes = {i for i, (a, b) in enumerate(zip(image.blob, result.blob)) if a != b}
        self.assertLessEqual(changes, allowed)
        for record in records:
            at = record['equation_offset']
            self.assertEqual(image.blob[at + 11:at + 25], result.blob[at + 11:at + 25])
        self.assertEqual(source.objects, target.objects)
        self.assertEqual(source.pci_images, target.pci_images)
        self.assertEqual(image.blob[-23:], result.blob[-23:])

    def test_shared_equations_report_side_effects_and_conflicting_requests(self):
        image = from_bytes(extended_fixture(shared=True))
        field = descriptors(image)['nvvdd_ov_equation_max_mv']
        self.assertEqual({x['role'] for x in field['shared_references']}, {'OV', 'REL'})
        result = edit(image, {'nvvdd_ov_equation_max_mv': 1100})
        affected = {x['field']: x for x in result.manifest['affected_fields']}
        for key in ('nvvdd_rel_equation_max_mv', 'nvvdd_rel_max_mv'):
            self.assertEqual(affected[key]['after'], 1100)
            self.assertFalse(affected[key]['requested'])
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'nvvdd_ov_equation_max_mv': 1100, 'nvvdd_rel_equation_max_mv': 1100})
        self.assertEqual(exc.exception.code, 'CONFLICTING_FIELDS')
        self.assertFalse(descriptors(image)['nvvdd_rel_max_mv']['ui_visible'])

    def test_absent_unknown_and_signed_equation_are_distinct(self):
        absent = from_bytes(extended_fixture(absent_alt=True))
        field = descriptors(absent)['msvdd_alt_equation_max_mv']
        self.assertIsNone(field['current'])
        self.assertEqual(field['selector']['raw'], 65535)
        self.assertTrue(field['selector']['absent'])
        self.assertEqual(field['capability']['vbios']['writable'], 'unsupported')
        unknown = from_bytes(extended_fixture(unknown_equation=True))
        field = descriptors(unknown)['nvvdd_alt_equation_max_mv']
        self.assertFalse(field['editable'])
        self.assertEqual(field['capability']['vbios']['writable'], 'unknown')
        signed = from_bytes(extended_fixture())
        result = edit(signed, {'nvvdd_alt_equation_max_mv': -5})
        field = descriptors(result.image)['nvvdd_alt_equation_max_mv']
        self.assertEqual(field['current'], -5)
        self.assertTrue(field['unit_metadata']['storage_signed'])
        self.assertEqual(field['runtime_offset'], {'units': 'uV', 'type': 'int32', 'signed': True,
                                                   'current': None, 'writable': 'unknown'})

    def test_ocp_floor_shape_unit_gate_and_unknown_row9(self):
        image = from_bytes(extended_fixture())
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'nvvdd_output_ocp_max_ma': 89999})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        self.assertEqual(descriptors(image)['nvvdd_output_ocp_max_ma']['bounds']['minimum'], 90000)
        blob = bytearray(image.blob)
        parsed = backend(image)
        # Type7 alone is insufficient: unit discriminator and immutable row shape matter.
        blob[parsed.power_rows()[13]['offset'] + 1] = 0
        bad = from_bytes(repair_fixture(blob))
        field = descriptors(bad)['nvvdd_output_ocp_max_ma']
        self.assertFalse(field['editable'])
        self.assertIsNone(field['current'])
        self.assertEqual(field['raw_bounds']['units'], 'unknown')
        with self.assertRaises(VbiosError) as exc:
            edit(bad, {'nvvdd_output_ocp_max_ma': 100000})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')
        self.assertEqual(descriptors(image)['input_policy_9_max_raw']['units'], 'unknown')
        self.assertFalse(descriptors(image)['ocp_limit_a']['editable'])

    def test_unknown_rel_kind_is_readonly_for_canonical_and_legacy_keys(self):
        image = from_bytes(extended_fixture())
        parsed = backend(image)
        role = next(r for r in parsed.rail_equations() if r['logical_rail_id'] == 'NVVDD' and r['role'] == 'REL')
        blob = bytearray(image.blob)
        blob[role['equation_offset']] = 0xFE
        unknown = from_bytes(repair_fixture(blob))
        for key in ('nvvdd_rel_max_mv', 'nvvdd_rel_equation_max_mv'):
            self.assertFalse(descriptors(unknown)[key]['editable'])
            self.assertEqual(descriptors(unknown)[key]['capability']['vbios']['writable'], 'unknown')
            with self.assertRaises(VbiosError) as exc:
                edit(unknown, {key: 1100})
            self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')

    def test_extension_cannot_change_new_role_expression_payload(self):
        from decimal import Decimal
        from nvidia_vbios.editor import Binding, FieldRegistry
        image = from_bytes(extended_fixture())
        custom = FieldRegistry()
        @custom.register
        def forbidden(image, parser):
            role = next(r for r in parser.rail_equations() if r['logical_rail_id'] == 'NVVDD' and r['role'] == 'VMIN')
            at = role['equation_offset'] + 11
            current = struct.unpack_from('<f', image.blob, at)[0]
            descriptor = dict(key='coefficient', label='test', type='number', units='raw', current=current,
                              bounds={'minimum': 0, 'maximum': 2000000}, editable=True,
                              evidence=[{'kind': 'synthetic-test'}])
            return [Binding(descriptor, (at,), '<f', Decimal(1))]
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'coefficient': 1000000}, field_registry=custom)
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')

    def test_ada_capabilities_never_claim_runtime_applied(self):
        image = from_bytes(synthetic_rom(copies=2))
        result = plan(image, {'power_max_w': 100, 'nvvdd_rel_equation_max_mv': 1100})
        fields = descriptors(result.image)
        self.assertEqual(fields['power_max_w']['current'], 100)
        self.assertEqual(fields['power_max_w']['capability']['runtime']['applied'], 'unknown')
        self.assertFalse(result.manifest['runtime_validation']['new_edit_hardware_tested'])
        # VMIN (rail byte 11) is a fixed-point equation: selector shown, value unknown.
        self.assertEqual(fields['nvvdd_vmin_equation_max_mv']['capability']['vbios']['writable'], 'unknown')
        self.assertIsNone(fields['nvvdd_vmin_equation_max_mv']['current'])
        self.assertEqual(fields['nvvdd_vmin_selector_index']['current'], 3)
        self.assertEqual(fields['nvvdd_alt_equation_max_mv']['capability']['vbios']['writable'], 'unsupported')
        self.assertEqual((fields['nvvdd_ov_equation_max_mv']['current'], fields['nvvdd_ov_equation_max_mv']['editable'],
                          fields['nvvdd_ov_equation_max_mv']['equation_kind']), (1200, False, 'constant'))
        self.assertFalse(fields['msvdd_rel_max_mv']['editable'])


class ClockRangeTests(unittest.TestCase):
    """Experimental GB20x clock offset ranges beyond the validated DRAM ceiling."""

    def test_named_domains_are_signed_experimental_and_unit_explicit(self):
        image = from_bytes(synthetic_blackwell())
        fields = descriptors(image)
        expected = {'gpc_offset_max_mhz': (3000, 'MHz', 0, 32767),
                    'gpc_offset_min_mhz': (-1000, 'MHz', -32768, 0),
                    'memory_offset_min_mhz': (-2000, 'MHz', -65536, 0),
                    'dram_min_table_mhz': (-1000, 'table MHz', -32768, 0)}
        for domain in ('xbar', 'sys', 'vid'):
            expected[f'{domain}_max_table_mhz'] = (3000, 'table MHz', 0, 32767)
            expected[f'{domain}_min_table_mhz'] = (-1000, 'table MHz', -32768, 0)
        for key, (current, units, lo, hi) in expected.items():
            with self.subTest(key=key):
                field = fields[key]
                self.assertEqual((field['current'], field['units']), (current, units))
                self.assertEqual((field['bounds']['minimum'], field['bounds']['maximum']), (lo, hi))
                self.assertTrue(field['editable'] and field['experimental'])
                self.assertTrue(field['unit_metadata']['storage_signed'])
                self.assertEqual(field['stored_units'], 'table MHz')
        self.assertEqual(fields['dram_min_table_mhz']['alias_of'], 'memory_offset_min_mhz')
        self.assertEqual(fields['gpc_offset_max_mhz']['clock_domain'], 'GPC')
        self.assertNotIn('experimental', fields['memory_offset_max_mhz'])
        json.dumps(inspect_image(image), allow_nan=False)

    def test_simultaneous_range_edits_touch_only_their_rows(self):
        image = from_bytes(synthetic_blackwell())
        source = backend(image)
        changes = {'gpc_offset_max_mhz': 2500, 'gpc_offset_min_mhz': -2000, 'xbar_max_table_mhz': 1500,
                   'vid_min_table_mhz': -1500, 'memory_offset_min_mhz': -4000}
        result = edit(image, changes)
        target = backend(result.image)
        rows = {r['domain']: (r['minimum_mhz'], r['maximum_mhz']) for r in target.clock_ranges()}
        self.assertEqual(rows['GPC'], (-2000, 2500))
        self.assertEqual(rows['XBAR'], (-1000, 1500))
        self.assertEqual(rows['DRAM'], (-2000, 3000))
        self.assertEqual(rows['SYS'], (-1000, 3000))
        self.assertEqual(rows['VID'], (-1500, 3000))
        self.assertEqual(source.clock_ranges()[5:], target.clock_ranges()[5:])
        self.assertEqual(source.power_rows(), target.power_rows())
        named = {r['domain']: r for r in source.clock_ranges()}
        offsets = [named['GPC']['maximum_offset'], named['GPC']['minimum_offset'], named['XBAR']['maximum_offset'],
                   named['VID']['minimum_offset'], named['DRAM']['minimum_offset']]
        changed_bytes_within(self, image, result, offsets, width=2)
        self.assertEqual(result.manifest['changed_object_ids'], [3])
        reverted = edit(result.image, {'gpc_offset_max_mhz': 3000, 'gpc_offset_min_mhz': -1000,
                                       'xbar_max_table_mhz': 3000, 'vid_min_table_mhz': -1000,
                                       'dram_min_table_mhz': -1000})
        self.assertEqual(reverted.blob, image.blob)

    def test_ranges_keep_zero_and_units_are_exact(self):
        image = from_bytes(synthetic_blackwell())
        cases = (({'gpc_offset_min_mhz': 1}, 'OUT_OF_BOUNDS'), ({'gpc_offset_max_mhz': -1}, 'OUT_OF_BOUNDS'),
                 ({'gpc_offset_max_mhz': 32768}, 'OUT_OF_BOUNDS'), ({'sys_min_table_mhz': -32769}, 'OUT_OF_BOUNDS'),
                 ({'memory_offset_min_mhz': -4001}, 'UNREPRESENTABLE_VALUE'),
                 ({'memory_offset_min_mhz': -4000, 'dram_min_table_mhz': -2000}, 'CONFLICTING_FIELDS'))
        for changes, code in cases:
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual(exc.exception.code, code)

    def test_extension_cannot_move_a_range_past_zero(self):
        image = from_bytes(synthetic_blackwell())
        gpc = backend(image).clock_ranges()[0]
        custom = custom_registry('probe', (gpc['minimum_offset'],), encoding='<h', scale=1)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'probe': 100}, field_registry=custom)
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_unrecognized_ampere_clock_table_keeps_memory_read_only(self):
        blob = bytearray(synthetic_rom(family='ampere'))
        clocks = backend(from_bytes(bytes(blob))).pointer('C', 8)
        blob[clocks + 6] = 2  # not the GV HAL
        image = backend(from_bytes(bytes(blob)))
        for start, end in image.image_regions:
            blob[end - 1] = (blob[end - 1] - sum(blob[start:end])) & 255
        fields = descriptors(from_bytes(bytes(blob)))
        self.assertFalse(any(key.startswith(('gpc_offset', 'xbar_', 'sys_', 'vid_')) or
                             key in ('memory_offset_min_mhz', 'dram_min_table_mhz') for key in fields))
        self.assertFalse(fields['memory_offset_max_mhz']['editable'])


class PowerDefaultTests(unittest.TestCase):
    """Boot default (rated) TGP: canonical binding only, joint ordering checks."""

    def test_rated_default_changes_base_row_and_matching_profile_only(self):
        image = from_bytes(synthetic_blackwell())
        source = backend(image)
        field = descriptors(image)['power_default_w']
        self.assertEqual((field['current'], field['bounds']['minimum'], field['bounds']['maximum']), (70, 30, 100))
        self.assertTrue(field['experimental'])
        self.assertEqual(field['policy_indices'], [8])
        result = edit(image, {'power_default_w': 90})
        target = backend(result.image)
        for i, (before, after) in enumerate(zip(source.power_rows(), target.power_rows())):
            self.assertEqual(after, dict(before, default_raw=90000) if i == 8 else before)
        entries = {(e['policy'], e['field']): e['value_raw'] for e in target.power_profiles()[0]['entries']}
        self.assertEqual(entries[(8, 'default')], 90000)
        self.assertEqual({k: v for k, v in entries.items() if k != (8, 'default')},
                         {(p, f): 100000 if f == 'maximum' else 70000 for p, f in entries if (p, f) != (8, 'default')})
        self.assertEqual([p['index'] for p in target.matching_power_profiles()], [0])
        default_entry = next(e for e in source.power_profiles()[0]['entries'] if (e['policy'], e['field']) == (8, 'default'))
        changed_bytes_within(self, image, result, [source.power_rows()[8]['offset'] + 17, default_entry['value_offset']])
        self.assertEqual(edit(result.image, {'power_default_w': 70}).blob, image.blob)

    def test_joint_requests_are_validated_on_the_result(self):
        image = from_bytes(synthetic_blackwell())
        result = edit(image, {'power_default_w': 150, 'power_max_w': 160})
        rows = backend(result.image).power_rows()
        self.assertEqual([(rows[i]['default_raw'], rows[i]['maximum_raw']) for i in (2, 7, 8)],
                         [(70000, 160000), (70000, 160000), (150000, 160000)])
        self.assertEqual(edit(image, {'power_min_w': 75, 'power_default_w': 80}).manifest['integrity']['valid'], True)
        self.assertEqual(backend(edit(image, {'power_default_w': 20, 'power_min_w': 10}).image).power_rows()[8]
                         ['minimum_raw'], 10000)
        for changes in ({'power_default_w': 101}, {'power_default_w': 20}, {'power_default_w': 150, 'power_max_w': 140},
                        {'power_min_w': 80, 'power_default_w': 75}, {'power_default_w': 60, 'power_max_w': 65}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_aliases_and_custom_bindings_cannot_change_rated_defaults(self):
        from nvidia_vbios.editor.registry import power
        image = from_bytes(synthetic_blackwell())
        source = backend(image)
        canonical = next(b for b in power(image, source) if b.descriptor['key'] == 'power_default_w')
        row2_default = source.power_rows()[2]['offset'] + 17
        cases = ((custom_registry('power_default_w', canonical.offsets[:1]), {'power_default_w': 90}, 'INVALID_FIELD_EVIDENCE'),
                 (custom_registry('alias', canonical.offsets), {'alias': 90}, 'FACTORY_DEFAULT_CHANGED'),
                 (custom_registry('alias', (row2_default,), include=(power,)), {'power_default_w': 90, 'alias': 90},
                  'FACTORY_DEFAULT_CHANGED'),
                 (custom_registry('power_default_w', canonical.offsets), {'power_default_w': 101}, 'OUT_OF_BOUNDS'),
                 (custom_registry('alias', canonical.offsets[1:], include=(power,)), {'power_max_w': 120, 'alias': 90},
                  'PRESERVED_FIELD_CHANGED'))
        for custom, changes, code in cases:
            with self.subTest(changes=changes, code=code), self.assertRaises(VbiosError) as exc:
                edit(image, changes, field_registry=custom)
            self.assertEqual(exc.exception.code, code)

    def test_ada_rated_default_is_written_in_every_duplicate_chain(self):
        image = from_bytes(synthetic_rom(copies=2))
        field = descriptors(image)['power_default_w']
        self.assertEqual((field['current'], field['bounds']['minimum'], field['bounds']['maximum']), (70, 30, 70))
        result = edit(image, {'power_default_w': 50})
        self.assertTrue(result.manifest['integrity']['valid'])
        self.assertEqual(len(result.manifest['edits']), 2)
        target = backend(result.image)
        rows = target.power_rows()
        tgp = rows[target.tgp_index]
        self.assertEqual((tgp['minimum_raw'], tgp['default_raw'], tgp['maximum_raw']), (30000, 50000, 70000))
        joint = backend(edit(image, {'power_default_w': 90, 'power_max_w': 100}).image)
        rows = joint.power_rows()
        self.assertEqual(rows[joint.tgp_index]['default_raw'], 90000)


class InputCurrentTests(unittest.TestCase):
    """Row9 12 V board input-current policy, separate from output OCP."""

    def test_reviewed_row9_exposes_separate_milliamp_fields(self):
        image = from_bytes(input_fixture())
        fields = descriptors(image)
        self.assertNotIn('input_policy_9_max_raw', fields)
        rated, ceiling = fields['input_current_rated_ma'], fields['input_current_max_ma']
        self.assertEqual((rated['current'], rated['bounds']['minimum'], rated['bounds']['maximum']), (80000, 1, 80000))
        self.assertEqual((ceiling['current'], ceiling['bounds']['minimum']), (80000, 80000))
        for field in (rated, ceiling):
            self.assertEqual((field['units'], field['stored_units']), ('mA', 'mA'))
            self.assertTrue(field['editable'] and field['experimental'])
            self.assertEqual(field['policy_types'], {'vbios': 11, 'rm': 30, 'api': 25})
            self.assertEqual(field['monitor'], {'index': 9, 'class': 8})
            self.assertNotIn('rail_identity', field)
        self.assertEqual(fields['nvvdd_output_ocp_max_ma']['rail_identity']['vbios_policy_index'], 13)
        self.assertFalse(fields['current_limit_a']['editable'])
        self.assertIn('input_current_*_ma', fields['current_limit_a']['reason'])
        json.dumps(inspect_image(image), allow_nan=False)

    def test_rated_and_ceiling_edit_base_row_and_matching_profile(self):
        image = from_bytes(input_fixture())
        source = backend(image)
        result = edit(image, {'input_current_rated_ma': 100000, 'input_current_max_ma': 120000})
        target = backend(result.image)
        for i, (before, after) in enumerate(zip(source.power_rows(), target.power_rows())):
            self.assertEqual(after, dict(before, default_raw=100000, maximum_raw=120000) if i == 9 else before)
        entries = {(e['policy'], e['field']): e['value_raw'] for e in target.power_profiles()[0]['entries']}
        self.assertEqual((entries[(9, 'default')], entries[(9, 'maximum')]), (100000, 120000))
        self.assertEqual([p['index'] for p in target.matching_power_profiles()], [0])
        self.assertEqual(source.output_ocp_policies(), target.output_ocp_policies())
        row = source.power_rows()[9]['offset']
        profile = {(e['policy'], e['field']): e['value_offset'] for e in source.power_profiles()[0]['entries']}
        changed_bytes_within(self, image, result, [row + 17, row + 21, profile[(9, 'default')], profile[(9, 'maximum')]])
        self.assertEqual(backend(edit(image, {'input_current_rated_ma': 50000}).image).power_rows()[9]['default_raw'], 50000)
        for changes in ({'input_current_rated_ma': 90000}, {'input_current_max_ma': 70000},
                        {'input_current_rated_ma': 0}, {'input_current_rated_ma': 130000, 'input_current_max_ma': 120000}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_unreviewed_row9_shape_or_alias_stays_read_only(self):
        image = from_bytes(input_fixture(unit=0))
        fields = descriptors(image)
        self.assertFalse(any(key.startswith('input_current_') for key in fields))
        self.assertEqual(fields['input_policy_9_max_raw']['units'], 'unknown')
        self.assertFalse(fields['input_policy_9_max_raw']['editable'])
        self.assertIn('per-policy', fields['current_limit_a']['reason'])
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'input_current_rated_ma': 50000})
        self.assertEqual(exc.exception.code, 'UNKNOWN_FIELD')
        reviewed = from_bytes(input_fixture())
        row = backend(reviewed).power_rows()[9]['offset']
        with self.assertRaises(VbiosError) as exc:
            edit(reviewed, {'alias': 50}, field_registry=custom_registry('alias', (row + 17,)))
        self.assertEqual(exc.exception.code, 'FACTORY_DEFAULT_CHANGED')

    def test_labels_mark_new_fields_experimental_in_both_languages(self):
        from nvidia_vbios.gui.i18n import Messages
        from nvidia_vbios.gui.presentation import field_label, technical_field_keys
        report = inspect_image(from_bytes(input_fixture()))
        keys = ('power_default_w', 'input_current_rated_ma', 'input_current_max_ma', 'gpc_offset_max_mhz',
                'gpc_offset_min_mhz', 'memory_offset_min_mhz', 'xbar_max_table_mhz', 'vid_min_table_mhz',
                'dram_min_table_mhz', 'input_current_policy7_limit_ma')
        fields = {f['key']: f for f in report['fields']}
        for language in ('en', 'es'):
            for key in keys:
                with self.subTest(language=language, key=key):
                    self.assertIn('experimental', field_label(fields[key], language))
        self.assertEqual(field_label(fields['sys_min_table_mhz'], 'es'), Messages('es')('field.clock_domain_min', domain='SYS'))
        self.assertIn('dram_min_table_mhz', technical_field_keys(report))
        self.assertNotIn('memory_offset_min_mhz', technical_field_keys(report))


class InputCurrentGateTests(unittest.TestCase):
    """Row9/row7 recognition gates and the scope of the rated-default exception."""

    def test_row9_needs_template_reviewed_device_and_order(self):
        cases = {'monitor': dict(monitor=3), 'extra byte': dict(extra=40), 'unit': dict(unit=0),
                 'device': dict(device=0x2BB5), 'order': dict(minimum=90000),
                 'max-q template on 5090 id': dict(monitor=2)}
        for name, options in cases.items():
            with self.subTest(case=name):
                image = from_bytes(input_fixture(**options))
                fields = descriptors(image)
                self.assertFalse(any(key.startswith('input_current_') for key in fields))
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'input_current_rated_ma': 50000})
                self.assertEqual(exc.exception.code, 'UNKNOWN_FIELD')
        maxq = descriptors(from_bytes(input_fixture(device=0x2BB4, monitor=2)))
        self.assertEqual(maxq['input_current_rated_ma']['monitor'], {'index': 2, 'class': 8})
        self.assertTrue(maxq['input_current_rated_ma']['editable'])

    def test_policy7_linked_limit_is_a_separate_canonical_field(self):
        from nvidia_vbios.editor.registry import input_current
        image = from_bytes(input_fixture())
        source = backend(image)
        field = descriptors(image)['input_current_policy7_limit_ma']
        self.assertEqual((field['current'], field['units'], field['references_policy']), (80000, 'mA', 9))
        self.assertTrue(field['editable'] and field['experimental'])
        self.assertEqual((field['bounds']['minimum'], field['policy_indices']), (1, [7]))
        at = source.power_rows()[7]['offset'] + 61
        result = edit(image, {'input_current_policy7_limit_ma': 160000})
        target = backend(result.image)
        self.assertEqual(struct.unpack_from('<I', result.blob, at)[0], 160000)
        self.assertEqual(source.power_rows(), target.power_rows())
        self.assertEqual(source.power_profiles(), target.power_profiles())
        changed_bytes_within(self, image, result, [at])
        self.assertEqual(descriptors(result.image)['input_current_policy7_limit_ma']['current'], 160000)
        self.assertEqual(edit(result.image, {'input_current_policy7_limit_ma': 80000}).blob, image.blob)
        keys = ('input_current_rated_ma', 'input_current_max_ma', 'input_current_policy7_limit_ma')
        combined = descriptors(edit(image, dict.fromkeys(keys, 100000)).image)
        self.assertEqual([combined[key]['current'] for key in keys], [100000] * 3)
        self.assertNotIn('input_current_policy7_limit_ma', descriptors(from_bytes(input_fixture(linked=False))))
        blob = bytearray(image.blob)
        blob[source.power_rows()[7]['offset'] + 33] = 8
        self.assertNotIn('input_current_policy7_limit_ma', descriptors(from_bytes(repair_fixture(blob))))
        cases = ((None, {'input_current_policy7_limit_ma': 0}, 'OUT_OF_BOUNDS'),
                 (custom_registry('alias', (at,), scale=1), {'alias': 90000}, 'PRESERVED_FIELD_CHANGED'),
                 (custom_registry('input_current_policy7_limit_ma', (at + 4,), scale=1),
                  {'input_current_policy7_limit_ma': 90000}, 'INVALID_FIELD_EVIDENCE'),
                 (custom_registry('alias', (at + 4,), scale=1, include=(input_current,)),
                  {'input_current_policy7_limit_ma': 90000, 'alias': 5}, 'PRESERVED_FIELD_CHANGED'))
        for custom, changes, code in cases:
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes, field_registry=custom)
            self.assertEqual(exc.exception.code, code)

    def test_rated_exception_covers_only_row9(self):
        from nvidia_vbios.editor.registry import input_current
        image = from_bytes(input_fixture())
        source = backend(image)
        self.assertEqual(descriptors(image)['input_current_rated_ma']['policy_indices'], [9])
        row13_rated = source.power_rows()[13]['offset'] + 17
        custom = custom_registry('alias', (row13_rated,), scale=1, include=(input_current,))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'input_current_rated_ma': 50000, 'alias': 50000}, field_registry=custom)
        self.assertEqual(exc.exception.code, 'FACTORY_DEFAULT_CHANGED')
        bare = from_bytes(input_fixture(profiles=0))
        row9_rated = backend(bare).power_rows()[9]['offset'] + 17
        custom = custom_registry('alias', (row9_rated,), scale=1, include=(input_current,))
        with self.assertRaises(VbiosError) as exc:
            edit(bare, {'input_current_max_ma': 90000, 'alias': 50000}, field_registry=custom)
        self.assertEqual(exc.exception.code, 'FACTORY_DEFAULT_CHANGED')
        entry = next(e for e in source.power_profiles()[0]['entries'] if (e['policy'], e['field']) == (9, 'default'))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'alias': 50000}, field_registry=custom_registry('alias', (entry['value_offset'],), scale=1))
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')

    def test_unmatched_profiles_hide_input_fields(self):
        blob = bytearray(input_fixture())
        parsed = backend(from_bytes(bytes(blob)))
        entry = next(e for e in parsed.power_profiles()[0]['entries'] if (e['policy'], e['field']) == (2, 'maximum'))
        struct.pack_into('<I', blob, entry['value_offset'], 90000)
        image = from_bytes(repair_fixture(blob))
        report = inspect_image(image)
        fields = {f['key']: f for f in report['fields']}
        self.assertFalse(any(key.startswith('input_current_') for key in fields))
        self.assertIn('no complete override profile matches the base policy',
                      [d.get('message') for d in report['diagnostics']])
        self.assertIn('per-policy', fields['current_limit_a']['reason'])
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'input_current_rated_ma': 50000})
        self.assertEqual(exc.exception.code, 'UNKNOWN_FIELD')


class ProfileAndManifestGuardTests(unittest.TestCase):
    """Matching profiles stay matching and ordered; manifests report rated changes."""

    def test_only_matching_profiles_follow_the_base(self):
        blob = bytearray(input_fixture(profiles=2))
        parsed = backend(from_bytes(bytes(blob)))
        second = parsed.power_profiles()[1]
        entry = next(e for e in second['entries'] if (e['policy'], e['field']) == (8, 'default'))
        struct.pack_into('<I', blob, entry['value_offset'], 65000)
        image = from_bytes(repair_fixture(blob))
        source = backend(image)
        self.assertEqual([p['index'] for p in source.matching_power_profiles()], [0])
        result = edit(image, {'power_default_w': 90, 'input_current_rated_ma': 70000, 'power_max_w': 120})
        target = backend(result.image)
        self.assertEqual(source.power_profiles()[1], target.power_profiles()[1])
        values = {(e['policy'], e['field']): e['value_raw'] for e in target.power_profiles()[0]['entries']}
        self.assertEqual((values[(8, 'default')], values[(9, 'default')], values[(8, 'maximum')]), (90000, 70000, 120000))
        self.assertEqual([p['index'] for p in target.matching_power_profiles()], [0])

    def test_extension_cannot_unmatch_or_invert_a_profile(self):
        from nvidia_vbios.editor.registry import power
        image = from_bytes(input_fixture(profiles=2))
        source = backend(image)
        maximum = next(e for e in source.power_profiles()[0]['entries'] if (e['policy'], e['field']) == (8, 'maximum'))
        custom = custom_registry('alias', (maximum['value_offset'],), include=(power,))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'power_default_w': 95, 'alias': 90}, field_registry=custom)
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')
        partial = custom_registry('input_current_max_ma', (source.power_rows()[9]['offset'] + 21,), scale=1)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'input_current_max_ma': 90000}, field_registry=partial)
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')

    def test_manifest_reports_changed_rated_defaults(self):
        image = from_bytes(input_fixture())
        changed = edit(image, {'power_default_w': 90, 'input_current_rated_ma': 50000}).manifest['preservation']
        self.assertFalse(changed['factory_defaults'])
        self.assertEqual(changed['changed_rated_defaults'], ['input_current_rated_ma', 'power_default_w'])
        kept = edit(image, {'power_max_w': 120, 'power_default_w': 70}).manifest['preservation']
        self.assertTrue(kept['factory_defaults'])
        self.assertEqual(kept['changed_rated_defaults'], [])


class ReviewRegressionTests(unittest.TestCase):
    """Cases found by an adversarial review."""

    def test_ada_rated_exception_covers_only_the_tgp_row(self):
        from nvidia_vbios.editor.registry import power
        image = from_bytes(synthetic_rom(copies=2))
        parser = backend(image)
        rows = parser.power_rows()
        self.assertEqual(descriptors(image)['power_default_w']['policy_indices'], [parser.tgp_index])
        other = next(i for i in range(len(rows)) if i != parser.tgp_index)
        custom = custom_registry('alias', tuple(parser.copy_offsets(rows[other]['offset'] + 6, 4)), include=(power,))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'power_default_w': 50, 'alias': 40}, field_registry=custom)
        self.assertEqual(exc.exception.code, 'FACTORY_DEFAULT_CHANGED')

    def test_three_board_power_partners_are_checked_together(self):
        image = from_bytes(synthetic_blackwell())
        rows = backend(edit(image, {'power_min_w': 80, 'power_default_w': 120, 'power_max_w': 150}).image).power_rows()
        self.assertEqual((rows[8]['minimum_raw'], rows[8]['default_raw'], rows[8]['maximum_raw']), (80000, 120000, 150000))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'power_min_w': 130, 'power_default_w': 120, 'power_max_w': 150})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_clock_post_checks_cover_maximum_side_and_identity(self):
        image = from_bytes(synthetic_blackwell())
        gpc = backend(image).clock_ranges()[0]
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'probe': -100}, field_registry=custom_registry('probe', (gpc['maximum_offset'],), encoding='<h', scale=1))
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        descriptor = gpc['minimum_offset'] + 6
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'probe': 0x44}, field_registry=custom_registry('probe', (descriptor,), encoding='<H', scale=1))
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')

    def test_new_fields_cite_third_party_research_nvml_capture_and_experimental_reasons(self):
        fields = descriptors(from_bytes(input_fixture()))
        for key in ('power_default_w', 'input_current_rated_ma', 'input_current_max_ma', 'gpc_offset_max_mhz',
                    'memory_offset_min_mhz', 'xbar_min_table_mhz', 'input_current_policy7_limit_ma'):
            with self.subTest(key=key):
                third = [e for e in fields[key]['evidence'] if e['kind'] == 'third-party-research']
                self.assertEqual(len(third), 1)
                self.assertEqual(third[0]['source'], 'independent GB202 research (see acknowledgements)')
                if fields[key]['editable']:
                    self.assertTrue(fields[key]['reason'].startswith('experimental:'))
        def apis(key):
            return {e.get('api') for e in fields[key]['evidence']}
        self.assertIn('nvmlDeviceGetPowerManagementDefaultLimit', apis('power_default_w'))
        self.assertIn('nvmlDeviceGetGpcClkMinMaxVfOffset', apis('gpc_offset_min_mhz'))
        self.assertIn('nvmlDeviceGetMemClkMinMaxVfOffset', apis('memory_offset_min_mhz'))
        capture = next(e for e in fields['power_default_w']['evidence'] if e.get('api'))
        self.assertEqual((capture['source'], capture['set_tested']), ('read-only NVML capture', False))

    def test_evidence_names_no_capture_files_dates_or_hashes(self):
        # Evidence cites public labels; capture files, their hashes and dates stay out of the output.
        private_keys = {'date', 'sha256', 'permission', 'transport_source', 'transport_sha256',
                        'runtime_source', 'runtime_sha256', 'type_map_sha256'}
        private_text = re.compile(r'\b20\d\d-\d\d-\d\d\b|[\w-]\.(json|rom)\b')
        images = (synthetic_rom(), synthetic_rom(family='ampere'), input_fixture(), single_rail_fixture(),
                  notebook_fixture(), synthetic_blackwell(shared_objects=True, power_topology=True, fans=True))
        for blob in images:
            for field in inspect_image(from_bytes(blob))['fields']:
                for evidence in field['evidence']:
                    with self.subTest(key=field['key'], kind=evidence['kind']):
                        self.assertFalse(private_keys & set(evidence))
                        self.assertFalse([v for v in evidence.values()
                                          if isinstance(v, str) and private_text.search(v)])

    def test_gui_controller_stages_user_requested_ranges_and_input_pair(self):
        import tempfile
        from nvidia_vbios.gui.controller import Controller, controls
        from nvidia_vbios.gui.presentation import primary_preview
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.rom'
            source.write_bytes(input_fixture())
            controller = Controller()
            document = controller.open(source)
            editable = {f['key'] for f in controls(document.report) if f['editable']}
            self.assertNotIn('dram_min_table_mhz', editable)
            self.assertIn('input_current_policy7_limit_ma', editable)
            staged = controller.stage({'memory_offset_min_mhz': '-4000', 'gpc_offset_min_mhz': '-2000'})
            self.assertEqual({a['key'] for a, b in primary_preview(staged)}, {'memory_offset_min_mhz', 'gpc_offset_min_mhz'})
            staged = controller.stage({'input_current_rated_ma': '100000', 'input_current_max_ma': '100000'})
            self.assertEqual({a['key'] for a, b in primary_preview(staged)}, {'input_current_rated_ma', 'input_current_max_ma'})


def unmatched_second_profile():
    """Two profiles; profile 1 differs from the base in its (8, default) entry only."""
    blob = bytearray(input_fixture(profiles=2))
    second = backend(from_bytes(bytes(blob))).power_profiles()[1]
    entry = next(e for e in second['entries'] if (e['policy'], e['field']) == (8, 'default'))
    struct.pack_into('<I', blob, entry['value_offset'], 65000)
    return from_bytes(repair_fixture(blob))


def profile_entry(parser, index, policy, name):
    profile = next(p for p in parser.power_profiles() if p['index'] == index)
    return next(e for e in profile['entries'] if (e['policy'], e['field']) == (policy, name))


class GuardCoverageTests(unittest.TestCase):
    """Pins each guard by its own message (mutation recheck)."""

    def assertRefused(self, image, changes, custom, code, message):
        with self.assertRaises(VbiosError) as exc:
            edit(image, changes, field_registry=custom)
        self.assertEqual((exc.exception.code, str(exc.exception)), (code, message))

    def test_unmatched_profile_cannot_be_inverted_or_change_defaults(self):
        image = unmatched_second_profile()
        parser = backend(image)
        maximum = profile_entry(parser, 1, 8, 'maximum')['value_offset']
        self.assertRefused(image, {'alias': 60}, custom_registry('alias', (maximum,)), 'OUT_OF_BOUNDS',
                           'override profile default must not exceed its maximum')
        for policy in (8, 9):
            with self.subTest(policy=policy):
                at = profile_entry(parser, 1, policy, 'default')['value_offset']
                self.assertRefused(image, {'alias': 50}, custom_registry('alias', (at,), scale=1000 if policy == 8 else 1),
                                   'PRESERVED_FIELD_CHANGED', 'power profile defaults and selectors must be preserved')
        at = profile_entry(parser, 0, 9, 'default')['value_offset']
        self.assertRefused(image, {'alias': 50000}, custom_registry('alias', (at,), scale=1),
                           'PRESERVED_FIELD_CHANGED', 'power profile defaults and selectors must be preserved')

    def test_linked_limit_bytes_need_the_canonical_request_and_row7(self):
        from nvidia_vbios.editor.registry import input_current
        image = from_bytes(input_fixture())
        rows = backend(image).power_rows()
        message = 'unrequested power row bytes must be preserved'
        self.assertRefused(image, {'alias': 90000},
                           custom_registry('alias', (rows[7]['offset'] + 61,), scale=1, include=(input_current,)),
                           'PRESERVED_FIELD_CHANGED', message)
        self.assertRefused(image, {'input_current_policy7_limit_ma': 90000, 'alias': 7},
                           custom_registry('alias', (rows[6]['offset'] + 61,), scale=1, include=(input_current,)),
                           'PRESERVED_FIELD_CHANGED', message)

    def test_row_shapes_pin_every_identity_byte(self):
        image = from_bytes(input_fixture())
        rows = backend(image).power_rows()
        for row, positions, key in ((7, (2, 12, 41, 70, 101), 'input_current_policy7_limit_ma'),
                                    (9, (2, 12, 30, 70, 101), 'input_current_rated_ma')):
            for position in positions:
                with self.subTest(row=row, position=position):
                    blob = bytearray(image.blob)
                    blob[rows[row]['offset'] + position] ^= 0x40
                    fields = descriptors(from_bytes(repair_fixture(blob)))
                    self.assertNotIn(key, fields)

    def test_clock_layout_switch_is_an_identity_change(self):
        from decimal import Decimal
        from nvidia_vbios.editor import Binding, FieldRegistry
        image = from_bytes(synthetic_blackwell())
        rows = backend(image).clock_ranges()
        sff = ((12, 12), (16, 16), (8, 11), (14, 14), (13, 13), (15, 15), (21, 25), (0, 7), (17, 20))
        custom = FieldRegistry()

        @custom.register
        def layout(image, parser):
            result = []
            for row in rows:
                at = row['minimum_offset'] - 2
                descriptor = dict(key=f"ids_{row['row']}", label='probe', type='number', units='raw',
                                  current=struct.unpack_from('<H', image.blob, at)[0],
                                  bounds={'minimum': 0, 'maximum': 65535}, editable=True,
                                  evidence=[{'kind': 'synthetic-test'}])
                result.append(Binding(descriptor, (at,), '<H', Decimal(1)))
            return result
        changes = {f"ids_{row['row']}": first | last << 8 for row, (first, last) in zip(rows, sff)}
        self.assertRefused(image, changes, custom, 'PRESERVED_FIELD_CHANGED', 'clock row identity must be preserved')

    def test_ranges_that_never_held_zero_do_not_block_other_edits(self):
        blob = bytearray(synthetic_blackwell())
        row5 = backend(from_bytes(bytes(blob))).clock_ranges()[5]
        struct.pack_into('<h', blob, row5['minimum_offset'], 100)
        image = from_bytes(repair_fixture(blob))
        result = edit(image, {'gpc_offset_max_mhz': 2000})
        self.assertEqual(backend(result.image).clock_ranges()[5]['minimum_mhz'], 100)

    def test_evidence_and_texts_are_pinned(self):
        from nvidia_vbios.editor.registry import INPUT_CURRENT_EVIDENCE, THIRD_PARTY_EVIDENCE
        from nvidia_vbios.gui.i18n import Messages
        from nvidia_vbios.gui.presentation import read_only_reason
        fields = descriptors(from_bytes(input_fixture()))
        for key in ('power_default_w', 'gpc_offset_max_mhz', 'memory_offset_min_mhz'):
            capture = [e for e in fields[key]['evidence'] if e['kind'] == 'read-only-nvml-correlation']
            self.assertEqual([(e['source'], e['set_tested']) for e in capture],
                             [('read-only NVML capture', False)])
        relations = {key: next(e['relation'] for e in fields[key]['evidence'] if e.get('api'))
                     for key in ('gpc_offset_min_mhz', 'memory_offset_min_mhz', 'power_default_w')}
        self.assertEqual(relations, {'gpc_offset_min_mhz': 'NVML MHz = table MHz',
                                     'memory_offset_min_mhz': 'NVML MHz = 2 * table MHz',
                                     'power_default_w': 'NVML default power limit = stored TGP rated value'})
        self.assertEqual(THIRD_PARTY_EVIDENCE,
                         {'kind': 'third-party-research', 'source': 'independent GB202 research (see acknowledgements)',
                          'use': 'cross-check only; structural parsing and writers are independent'})
        self.assertIn('rows9-14', INPUT_CURRENT_EVIDENCE['units_basis'])
        for key in ('input_current_rated_ma', 'input_current_max_ma', 'input_current_policy7_limit_ma'):
            self.assertIn('not a hardware-safe current rating', fields[key]['reason'])
        for language in ('en', 'es'):
            text = Messages(language)
            self.assertEqual(read_only_reason(fields['current_limit_a'], language), text('reason.generic_input'))
            self.assertEqual(read_only_reason(fields['input_current_policy7_limit_ma'], language), text('reason.linked_input'))
        self.assertEqual(Messages()('factory', value=70, units='W'), 'Rated default in this ROM: 70 W.')
        self.assertNotIn('preservado', Messages('es')('factory', value=70, units='W'))


class OutputOcpRatedTests(unittest.TestCase):
    """Rated output OCP (rows13/14 +17), the value enforced from boot."""

    def test_rated_fields_are_canonical_and_joint_with_the_ceiling(self):
        image = from_bytes(extended_fixture())
        source = backend(image)
        fields = descriptors(image)
        for rail, row, rated in (('nvvdd', 13, 90000), ('msvdd', 14, 60000)):
            with self.subTest(rail=rail):
                field = fields[f'{rail}_output_ocp_rated_ma']
                self.assertEqual((field['current'], field['bounds']['minimum'], field['bounds']['maximum']), (rated, 1, rated))
                self.assertEqual((field['units'], field['policy_indices']), ('mA', [row]))
                self.assertTrue(field['editable'] and field['experimental'])
                self.assertIn('boot OCP is the rated value', fields[f'{rail}_output_ocp_max_ma']['reason'])
        result = edit(image, {'nvvdd_output_ocp_rated_ma': 80000})
        target = backend(result.image)
        for i, (before, after) in enumerate(zip(source.power_rows(), target.power_rows())):
            self.assertEqual(after, dict(before, default_raw=80000) if i == 13 else before)
        changed_bytes_within(self, image, result, [source.power_rows()[13]['offset'] + 17])
        self.assertEqual(result.manifest['preservation']['changed_rated_defaults'], ['nvvdd_output_ocp_rated_ma'])
        joint = backend(edit(image, {'msvdd_output_ocp_rated_ma': 100000, 'msvdd_output_ocp_max_ma': 120000}).image)
        self.assertEqual((joint.power_rows()[14]['default_raw'], joint.power_rows()[14]['maximum_raw']), (100000, 120000))
        for changes in ({'nvvdd_output_ocp_rated_ma': 100000}, {'nvvdd_output_ocp_rated_ma': 0},
                        {'nvvdd_output_ocp_rated_ma': 130000, 'nvvdd_output_ocp_max_ma': 120000}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_aliases_cannot_change_rated_ocp(self):
        from nvidia_vbios.editor.registry import output_ocp
        image = from_bytes(extended_fixture())
        rows = backend(image).power_rows()
        nvvdd, msvdd = rows[13]['offset'] + 17, rows[14]['offset'] + 17
        cases = ((custom_registry('alias', (nvvdd,), scale=1), {'alias': 80000}, 'FACTORY_DEFAULT_CHANGED'),
                 (custom_registry('alias', (msvdd,), scale=1, include=(output_ocp,)),
                  {'nvvdd_output_ocp_rated_ma': 80000, 'alias': 50000}, 'FACTORY_DEFAULT_CHANGED'),
                 (custom_registry('nvvdd_output_ocp_rated_ma', (nvvdd + 4,), scale=1),
                  {'nvvdd_output_ocp_rated_ma': 80000}, 'INVALID_FIELD_EVIDENCE'))
        for custom, changes, code in cases:
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes, field_registry=custom)
            self.assertEqual(exc.exception.code, code)

    def test_unrecognized_ocp_rows_offer_no_rated_field(self):
        blob = bytearray(extended_fixture())
        blob[backend(from_bytes(bytes(blob))).power_rows()[13]['offset'] + 1] = 0
        fields = descriptors(from_bytes(repair_fixture(blob)))
        self.assertNotIn('nvvdd_output_ocp_rated_ma', fields)
        self.assertIn('msvdd_output_ocp_rated_ma', fields)


class SlotPowerTests(unittest.TestCase):
    """Row19 PCIe slot power policy, recognized only on the reviewed SFF shape."""

    def test_sff_slot_power_is_a_joint_rated_and_ceiling_pair(self):
        image = from_bytes(sff_fixture())
        source = backend(image)
        fields = descriptors(image)
        rated, ceiling = fields['slot_power_rated_w'], fields['slot_power_max_w']
        self.assertEqual((rated['current'], rated['bounds']['maximum'], ceiling['bounds']['minimum']), (66, 66, 66))
        self.assertEqual((rated['units'], rated['stored_units'], rated['policy_indices']), ('W', 'mW', [19]))
        self.assertTrue(rated['experimental'] and ceiling['experimental'] and rated['editable'])
        result = edit(image, {'slot_power_rated_w': 90, 'slot_power_max_w': 100})
        target = backend(result.image)
        for i, (before, after) in enumerate(zip(source.power_rows(), target.power_rows())):
            self.assertEqual(after, dict(before, default_raw=90000, maximum_raw=100000) if i == 19 else before)
        row = source.power_rows()[19]['offset']
        changed_bytes_within(self, image, result, [row + 17, row + 21])
        self.assertEqual(edit(result.image, {'slot_power_rated_w': 66, 'slot_power_max_w': 66}).blob, image.blob)
        for changes, code in (({'slot_power_rated_w': 90}, 'OUT_OF_BOUNDS'), ({'slot_power_max_w': 60}, 'OUT_OF_BOUNDS'),
                              ({'slot_power_rated_w': 65.0001}, 'UNREPRESENTABLE_VALUE')):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual(exc.exception.code, code)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'alias': 90}, field_registry=custom_registry('alias', (row + 17,)))
        self.assertEqual(exc.exception.code, 'FACTORY_DEFAULT_CHANGED')

    def test_slot_power_needs_the_sff_identity_and_shape(self):
        for options in (dict(device=0x2B85), dict(unit=1), dict(monitor=2)):
            with self.subTest(options=options):
                fields = descriptors(from_bytes(sff_fixture(**options)))
                self.assertFalse(any(key.startswith('slot_power_') for key in fields))
        image = from_bytes(sff_fixture())
        row = backend(image).power_rows()[19]['offset']
        for position in (2, 6, 12, 33, 40, 101):
            with self.subTest(position=position):
                blob = bytearray(image.blob)
                blob[row + position] ^= 0x40
                self.assertFalse(any(key.startswith('slot_power_') for key in descriptors(from_bytes(repair_fixture(blob)))))

    def test_rated_fields_need_decodable_profiles(self):
        blob = bytearray(sff_fixture())
        parsed = backend(from_bytes(bytes(blob)))
        entry = parsed.power_profiles()[0]['entries'][0]
        struct.pack_into('<I', blob, entry['value_offset'] - 4, 13 | 1 << 8)
        image = from_bytes(repair_fixture(blob))
        fields = descriptors(image)
        for key in ('nvvdd_output_ocp_rated_ma', 'msvdd_output_ocp_rated_ma', 'slot_power_rated_w', 'slot_power_max_w'):
            with self.subTest(key=key):
                self.assertFalse(fields[key]['editable'])
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'nvvdd_output_ocp_rated_ma': 1000})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')
        rows = backend(image).power_rows()
        for key, at, scale in (('nvvdd_output_ocp_rated_ma', rows[13]['offset'] + 17, 1),
                               ('slot_power_rated_w', rows[19]['offset'] + 17, 1000),
                               ('slot_power_max_w', rows[19]['offset'] + 21, 1000)):
            # Identical copies and non-canonical variants (signed encoding) are both refused.
            for encoding in ('<I', '<i'):
                with self.subTest(extension=key, encoding=encoding), self.assertRaises(VbiosError) as exc:
                    edit(image, {key: 100}, field_registry=custom_registry(key, (at,), encoding=encoding, scale=scale))
                self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')
        self.assertTrue(edit(image, {'probe': 100}, field_registry=custom_registry(
            'probe', (rows[19]['offset'] + 21,), scale=1000)).manifest['integrity']['valid'])
        self.assertFalse(any(key.startswith('slot_power_') for key in descriptors(from_bytes(input_fixture()))))

    def test_labels_mark_ocp_rated_and_slot_power_experimental(self):
        from nvidia_vbios.gui.presentation import field_label
        fields = descriptors(from_bytes(sff_fixture()))
        for language in ('en', 'es'):
            for key in ('nvvdd_output_ocp_rated_ma', 'msvdd_output_ocp_rated_ma', 'slot_power_rated_w', 'slot_power_max_w'):
                with self.subTest(language=language, key=key):
                    self.assertIn('experimental', field_label(fields[key], language))


class FixedPolicyRatedTests(unittest.TestCase):
    """Opt-in rated value of fixed board policies 2/7, as XOC-style images raise it."""

    def test_opt_in_field_writes_rows_2_7_and_matching_profile_defaults(self):
        from nvidia_vbios.gui.presentation import field_label, opt_in_field_keys
        image = from_bytes(synthetic_blackwell())
        source = backend(image)
        report = inspect_image(image)
        field = {f['key']: f for f in report['fields']}['board_fixed_rated_w']
        self.assertEqual((field['current'], field['bounds']['minimum'], field['bounds']['maximum']), (70, 30, 100))
        self.assertTrue(field['opt_in'] and field['experimental'] and field['editable'])
        self.assertEqual((field['policy_indices'], field['ordering_group']), ([2, 7], 'board-power'))
        # The XOC-style REL/ALT selector field is opt-in too (read-only here: no legacy directory).
        self.assertEqual(opt_in_field_keys(report), {'board_fixed_rated_w', 'nvvdd_rel_alt_follow_ov'})
        for language in ('en', 'es'):
            self.assertIn('XOC', field_label(field, language))
        result = edit(image, {'board_fixed_rated_w': 90})
        target = backend(result.image)
        for i, (before, after) in enumerate(zip(source.power_rows(), target.power_rows())):
            self.assertEqual(after, dict(before, default_raw=90000) if i in (2, 7) else before)
        values = {(e['policy'], e['field']): e['value_raw'] for e in target.power_profiles()[0]['entries']}
        self.assertEqual((values[(2, 'default')], values[(7, 'default')], values[(8, 'default')]), (90000, 90000, 70000))
        self.assertEqual([p['index'] for p in target.matching_power_profiles()], [0])
        self.assertEqual(result.manifest['preservation']['changed_rated_defaults'], ['board_fixed_rated_w'])
        profile = {(e['policy'], e['field']): e['value_offset'] for e in source.power_profiles()[0]['entries']}
        changed_bytes_within(self, image, result, [source.power_rows()[2]['offset'] + 17, source.power_rows()[7]['offset'] + 17,
                                                   profile[(2, 'default')], profile[(7, 'default')]])

    def test_joint_with_ceiling_and_guards(self):
        from nvidia_vbios.editor.registry import power
        image = from_bytes(synthetic_blackwell())
        rows = backend(edit(image, {'board_fixed_rated_w': 150, 'power_max_w': 150}).image).power_rows()
        self.assertEqual([(rows[i]['default_raw'], rows[i]['maximum_raw']) for i in (2, 7, 8)],
                         [(150000, 150000), (150000, 150000), (70000, 150000)])
        rows = backend(edit(image, {'board_fixed_rated_w': 80, 'power_max_w': 85}).image).power_rows()
        self.assertEqual((rows[2]['default_raw'], rows[2]['maximum_raw']), (80000, 85000))
        for changes in ({'board_fixed_rated_w': 150}, {'board_fixed_rated_w': 150, 'power_max_w': 140},
                        {'board_fixed_rated_w': 20}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        row2 = backend(image).power_rows()[2]['offset'] + 17
        row7 = backend(image).power_rows()[7]['offset'] + 17
        cases = ((custom_registry('board_fixed_rated_w', (row2, row7)), {'board_fixed_rated_w': 90}, 'INVALID_FIELD_EVIDENCE'),
                 (custom_registry('alias', (row7,)), {'alias': 90}, 'FACTORY_DEFAULT_CHANGED'),
                 (custom_registry('alias', (backend(image).power_rows()[8]['offset'] + 17,), include=(power,)),
                  {'board_fixed_rated_w': 90, 'alias': 60}, 'FACTORY_DEFAULT_CHANGED'))
        for custom, changes, code in cases:
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes, field_registry=custom)
            self.assertEqual(exc.exception.code, code)

    def test_unequal_rows_or_non_blackwell_offer_no_field(self):
        blob = bytearray(synthetic_blackwell())
        parsed = backend(from_bytes(bytes(blob)))
        struct.pack_into('<I', blob, parsed.power_rows()[7]['offset'] + 17, 60000)
        entry = next(e for e in parsed.power_profiles()[0]['entries'] if (e['policy'], e['field']) == (7, 'default'))
        struct.pack_into('<I', blob, entry['value_offset'], 60000)
        self.assertNotIn('board_fixed_rated_w', descriptors(from_bytes(repair_fixture(blob))))
        for family in ('ada', 'ampere'):
            self.assertNotIn('board_fixed_rated_w', descriptors(from_bytes(synthetic_rom(family=family))))


class SingleRailLayoutTests(unittest.TestCase):
    """One-row (NVVDD only) rail table and 1-byte clock sub-entries, as on the Workstation."""

    def test_single_rail_exposes_nvvdd_and_reports_msvdd_absent(self):
        image = from_bytes(synthetic_blackwell(rails=1, clock_subsize=1))
        report = inspect_image(image)
        fields = {f['key']: f for f in report['fields']}
        self.assertEqual(report['diagnostics'], [])
        for key in ('nvvdd_rel_max_mv', 'nvvdd_rel_equation_max_mv', 'memory_offset_max_mhz', 'gpc_offset_max_mhz'):
            self.assertTrue(fields[key]['editable'], key)
        self.assertIn('structural-row-comparison', [e['kind'] for e in fields['nvvdd_rel_equation_max_mv']['evidence']])
        self.assertFalse(any(key.startswith('msvdd_') and key != 'msvdd_rel_max_mv' and 'ocp' not in key
                             for key in fields))
        self.assertFalse(fields['msvdd_rel_max_mv']['editable'])
        self.assertEqual(fields['msvdd_rel_max_mv']['reason'], 'this recognized single-rail layout exposes only logic/NVVDD')
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'msvdd_rel_max_mv': 1100})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')
        result = edit(image, {'nvvdd_rel_max_mv': 1100, 'memory_offset_max_mhz': 10000})
        self.assertTrue(result.manifest['integrity']['valid'])
        dram = backend(image).clock_ranges()[2]
        self.assertEqual(dram['maximum_offset'], 11776 + 13 + 18 * 2 + 5)
        self.assertEqual(struct.unpack_from('<h', result.blob, dram['maximum_offset'])[0], 5000)
        self.assertEqual(descriptors(result.image)['nvvdd_rel_max_mv']['current'], 1100)

    def test_single_rail_needs_header_byte_and_known_clock_subsize(self):
        blob = bytearray(synthetic_blackwell(rails=1))
        rail = backend(from_bytes(bytes(blob))).pointer('P', 0x68)
        blob[rail + 4] = 1
        fields = descriptors(from_bytes(repair_fixture(blob)))
        self.assertNotIn('nvvdd_rel_max_mv', fields)
        self.assertNotIn('nvvdd_rel_equation_max_mv', fields)
        self.assertNotIn('memory_offset_max_mhz', descriptors(from_bytes(synthetic_blackwell(clock_subsize=3))))
        split = descriptors(from_bytes(synthetic_blackwell()))
        self.assertTrue(split['msvdd_rel_max_mv']['editable'])
        self.assertIn('msvdd_rel_equation_max_mv', split)

    def test_workstation_identity_needs_the_reviewed_row9_template(self):
        fields = descriptors(from_bytes(input_fixture(device=0x2BB1)))
        self.assertTrue(fields['input_current_rated_ma']['editable'])
        self.assertTrue(fields['input_current_policy7_limit_ma']['editable'])
        self.assertNotIn('input_current_rated_ma', descriptors(from_bytes(input_fixture(device=0x2BB1, monitor=2))))


SINGLE_RAIL_ROW13 = {0: 7, 1: 1, 5: 26, 6: 1, 35: 11, 36: 11}
SINGLE_RAIL_ROW14 = {0: 7, 1: 1, 5: 26, 6: 1, 34: 1, 35: 12, 36: 12, 41: 1}


def single_rail_fixture(*, device=0x2D04, rails=1, channel=None, power_device=None, monitor=26, slot_row=None):
    """Single-rail image with the NVVDD channel chain and the row13/14 shapes of the 5060 Ti."""
    from nvidia_vbios.rom.blackwell import NVVDD_CHANNEL, NVVDD_POWER_DEVICE
    blob = bytearray(synthetic_blackwell(rails=rails, clock_subsize=1, power_topology=True))
    set_device(blob, device)
    parsed = backend(from_bytes(bytes(blob)))
    rows = parsed.power_rows()
    for index, shape in ((13, SINGLE_RAIL_ROW13), (14, SINGLE_RAIL_ROW14)):
        at = rows[index]['offset']
        blob[at:at + 102] = bytes(102)
        for offset, value in shape.items():
            blob[at + offset] = value
        blob[at + 5] = monitor
        struct.pack_into('<III', blob, at + 13, 1, 170000 if index == 13 else 5001000, 5001000)
    at = parsed.pointer('P', 0x3C) + 0x11 + 0x1A * 26
    blob[at:at + 0x1A] = NVVDD_CHANNEL if channel is None else channel
    at = parsed.pointer('P', 0x28) + 0x18 + 0x19 * 9
    blob[at:at + 0x19] = NVVDD_POWER_DEVICE if power_device is None else power_device
    if slot_row is not None:
        # Same immutable shape as the GET-reviewed SFF row 19 slot policy.
        at = rows[slot_row]['offset']
        blob[at:at + 102] = bytes(102)
        for offset, value in {0: 2, 5: 1, 6: 1, 33: 10, 34: 10}.items():
            blob[at + offset] = value
        struct.pack_into('<III', blob, at + 13, 0, 66000, 66000)
    return repair_fixture(blob)


class SingleRailPowerTests(unittest.TestCase):
    """Power rows of single-rail images, accepted by structure without saved GET."""

    def test_single_rail_nvvdd_ocp_follows_the_reviewed_channel_chain(self):
        image = from_bytes(single_rail_fixture())
        fields = descriptors(image)
        for key in ('nvvdd_output_ocp_max_ma', 'nvvdd_output_ocp_rated_ma'):
            self.assertTrue(fields[key]['editable'], key)
            self.assertEqual(fields[key]['evidence'][0]['kind'], 'structural-row-comparison')
            self.assertFalse(fields[key]['evidence'][0]['runtime_get'])
        self.assertEqual(fields['nvvdd_output_ocp_rated_ma']['current'], 170000)
        self.assertFalse(fields['msvdd_output_ocp_max_ma']['editable'])
        self.assertEqual(fields['msvdd_output_ocp_max_ma']['reason'],
                         'this recognized single-rail layout exposes only logic/NVVDD')
        self.assertNotIn('msvdd_output_ocp_rated_ma', fields)
        result = edit(image, {'nvvdd_output_ocp_rated_ma': 250000})
        self.assertTrue(result.manifest['integrity']['valid'])
        row = backend(image).power_rows()[13]['offset']
        changed_bytes_within(self, image, result, [row + 17])
        self.assertEqual(backend(result.image).power_rows()[13]['default_raw'], 250000)
        self.assertEqual(backend(image).power_rows()[14], backend(result.image).power_rows()[14])

    def test_channel_device_identity_and_rail_count_gate_the_template(self):
        from nvidia_vbios.rom.blackwell import NVVDD_CHANNEL, NVVDD_POWER_DEVICE
        cases = {'channel provider': dict(channel=NVVDD_CHANNEL[:14] + bytes([10]) + NVVDD_CHANNEL[15:]),
                 'disabled channel': dict(channel=bytes([0]) + NVVDD_CHANNEL[1:]),
                 'power device': dict(power_device=NVVDD_POWER_DEVICE[:5] + bytes([0x21]) + NVVDD_POWER_DEVICE[6:]),
                 'reviewed split-rail id': dict(device=0x2C02),
                 'unlisted id': dict(device=0x2D05),
                 'two rails': dict(rails=2),
                 'monitor': dict(monitor=27)}
        for name, options in cases.items():
            with self.subTest(case=name):
                fields = descriptors(from_bytes(single_rail_fixture(**options)))
                self.assertFalse(fields['nvvdd_output_ocp_max_ma']['editable'])
                self.assertNotIn('nvvdd_output_ocp_rated_ma', fields)
                with self.assertRaises(VbiosError):
                    edit(from_bytes(single_rail_fixture(**options)), {'nvvdd_output_ocp_rated_ma': 200000})

    def test_power_channel_and_device_tables_are_gated(self):
        from nvidia_vbios.rom.errors import FormatError
        blob = single_rail_fixture()
        parser = backend(from_bytes(blob))
        self.assertTrue(parser.nvvdd_channel_chain(26))
        self.assertFalse(parser.nvvdd_channel_chain(40))
        for method, indices in ((parser.power_channel, (-1, 32)), (parser.power_device, (-1, 11))):
            for index in indices:
                with self.subTest(method=method.__name__, index=index), self.assertRaises(FormatError):
                    method(index)

        def mutated(change):
            b = bytearray(blob)
            change(b)
            return descriptors(from_bytes(repair_fixture(b)))
        tables = {oid: next(o for o in parser.objects if o['id'] == oid) for oid in (0x16, 0x12)}
        cases = {
            'channel header': lambda b: b.__setitem__(parser.pointer('P', 0x3C) + 3, 0x21),
            'device header': lambda b: b.__setitem__(parser.pointer('P', 0x28) + 1, 0x17),
            'channel owner id': lambda b: struct.pack_into('<I', b, tables[0x16]['header'], 0x56),
            'device owner id': lambda b: struct.pack_into('<I', b, tables[0x12]['header'], 0x52),
            'channel table outside its object': lambda b: struct.pack_into('<I', b, tables[0x16]['header'] + 8, 100),
            'device table outside its object': lambda b: struct.pack_into('<I', b, tables[0x12]['header'] + 8, 100),
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                fields = mutated(change)
                self.assertFalse(fields['nvvdd_output_ocp_max_ma']['editable'])
                self.assertNotIn('nvvdd_output_ocp_rated_ma', fields)

    def test_structural_fields_never_claim_a_saved_get(self):
        fields = descriptors(from_bytes(single_rail_fixture(slot_row=18)))
        for key in ('nvvdd_output_ocp_rated_ma', 'slot_power_rated_w', 'slot_power_max_w'):
            with self.subTest(key=key):
                self.assertEqual(fields[key]['evidence'][0]['kind'], 'structural-row-comparison')
                self.assertNotIn('row19', fields[key]['version_metadata']['format_variant'])
        for key in ('nvvdd_output_ocp_rated_ma', 'slot_power_rated_w'):
            self.assertNotIn('saved GET current = rated', fields[key]['reason'])
            self.assertIn('no saved GET', fields[key]['reason'])
        sff = descriptors(from_bytes(sff_fixture()))
        self.assertIn('saved GET current = rated', sff['slot_power_rated_w']['reason'])
        self.assertEqual(sff['slot_power_rated_w']['evidence'][0]['kind'], 'saved-get-policy-correlation')
        # Row 9 alone is accepted; the structural note mentions row 7 only when it matches.
        unlinked = descriptors(from_bytes(input_fixture(device=0x2D04, linked=False)))
        self.assertNotIn('input_current_policy7_limit_ma', unlinked)
        self.assertNotIn('row 7', unlinked['input_current_rated_ma']['evidence'][0]['observation'])
        linked = descriptors(from_bytes(input_fixture(device=0x2D04)))
        self.assertIn('row 7', linked['input_current_rated_ma']['evidence'][0]['observation'])

    def test_new_ids_need_their_row9_template_and_the_5060ti_slot_row18(self):
        self.assertTrue(descriptors(from_bytes(input_fixture(device=0x2D04)))['input_current_rated_ma']['editable'])
        maxq_shape = descriptors(from_bytes(input_fixture(device=0x2F04, monitor=2)))
        self.assertTrue(maxq_shape['input_current_rated_ma']['editable'])
        self.assertEqual(maxq_shape['input_current_policy7_limit_ma']['evidence'][0]['kind'], 'structural-row-comparison')
        self.assertNotIn('input_current_rated_ma', descriptors(from_bytes(input_fixture(device=0x2F04))))
        self.assertNotIn('input_current_rated_ma', descriptors(from_bytes(input_fixture(device=0x2D04, monitor=2))))
        image = from_bytes(single_rail_fixture(slot_row=18))
        fields = descriptors(image)
        self.assertEqual(fields['slot_power_rated_w']['policy_indices'], [18])
        self.assertEqual(fields['slot_power_rated_w']['vbios_policy_index'], 18)
        result = edit(image, {'slot_power_rated_w': 70, 'slot_power_max_w': 75})
        self.assertEqual(backend(result.image).power_rows()[18]['default_raw'], 70000)
        self.assertEqual(backend(image).power_rows()[19], backend(result.image).power_rows()[19])
        self.assertNotIn('slot_power_rated_w', descriptors(from_bytes(single_rail_fixture(slot_row=18, device=0x2F04))))
        self.assertNotIn('slot_power_rated_w', descriptors(from_bytes(single_rail_fixture(slot_row=19))))


NOTEBOOK_ROW13 = {0: 7, 1: 1, 5: 27, 6: 1, 35: 11, 36: 11}
NOTEBOOK_ROW14 = {0: 7, 1: 1, 5: 28, 6: 1, 33: 1, 34: 1, 35: 12, 36: 12}


def notebook_fixture(*, device=0x2C59, header=(0xFF, 0xFF, 2), row8_type=0, profiles=False, chain=True,
                     dram_descriptor=0x1182, fan_enable=0):
    """Notebook image: TGP in row 2, empty rows 7/8, the Max-Q rows 13/14 and channels 27/28, no GPU fans."""
    from nvidia_vbios.rom.blackwell import OUTPUT_CHAINS
    blob = bytearray(synthetic_blackwell(power_topology=True, fans=True))
    set_device(blob, device)
    parsed = backend(from_bytes(bytes(blob)))
    rows = parsed.power_rows()
    at = parsed.pointer('P', 0x2C)
    blob[at + 21:at + 24] = bytes(header)
    for index in (7, 8):
        blob[rows[index]['offset']] = row8_type if index == 8 else 0
        struct.pack_into('<III', blob, rows[index]['offset'] + 13, 0, 0, 0)
    struct.pack_into('<III', blob, rows[2]['offset'] + 13, 5000, 80000, 175000)
    for index, shape, rated in ((13, NOTEBOOK_ROW13, 180000), (14, NOTEBOOK_ROW14, 60000)):
        at = rows[index]['offset']
        blob[at:at + 102] = bytes(102)
        for offset, value in shape.items():
            blob[at + offset] = value
        struct.pack_into('<III', blob, at + 13, 1, rated, rated)
    for monitor, rail in ((27, 'NVVDD'), (28, 'MSVDD')):
        channel, power_device = OUTPUT_CHAINS[rail]
        at = parsed.pointer('P', 0x3C) + 0x11 + 0x1A * monitor
        blob[at:at + 0x1A] = channel if chain else bytes(0x1A)
        at = parsed.pointer('P', 0x28) + 0x18 + 0x19 * channel[14]
        blob[at:at + 0x19] = power_device
    if not profiles:
        profile = parsed.power_profiles()[0]
        blob[profile['offset']:profile['offset'] + 0x49] = bytes(0x49)
    clocks = parsed.pointer('C', 8)
    struct.pack_into('<H', blob, clocks + 13 + 21 * 2 + 9, dram_descriptor)
    table = parsed.fan_coolers()
    blob[table['offset'] + 4:table['offset'] + 8] = b'\xff' * 4
    for row in table['rows']:
        for key in ('offset', 'policy_offset', 'mapping_offset', 'control_offset', 'speed_offset'):
            blob[row[key]] = 0
    blob[table['rows'][0]['policy_offset']] = fan_enable
    return repair_fixture(blob)


class NotebookLayoutTests(unittest.TestCase):
    """RTX 5080 Laptop layout: TGP in row 2, Max-Q output OCP rows, no GPU fans; no saved GET."""

    def test_notebook_power_ocp_clock_and_no_fans(self):
        image = from_bytes(notebook_fixture())
        report = inspect_image(image)
        self.assertEqual(report['diagnostics'], [])
        fields = {f['key']: f for f in report['fields']}
        self.assertEqual([fields[k]['current'] for k in ('power_min_w', 'power_default_w', 'power_max_w')], [5, 80, 175])
        for key in ('power_min_w', 'power_default_w', 'power_max_w', 'nvvdd_output_ocp_rated_ma',
                    'msvdd_output_ocp_rated_ma', 'msvdd_rel_equation_max_mv', 'memory_offset_max_mhz'):
            self.assertTrue(fields[key]['editable'], key)
        self.assertEqual(fields['power_default_w']['policy_indices'], [2])
        self.assertIn('Dynamic Boost', fields['power_max_w']['reason'])
        self.assertEqual([e['kind'] for e in fields['power_max_w']['evidence']],
                         ['structural-row-comparison', 'owner-nvidia-smi-reading'])
        self.assertEqual((fields['nvvdd_output_ocp_rated_ma']['current'], fields['msvdd_output_ocp_rated_ma']['current']),
                         (180000, 60000))
        for key in ('nvvdd_output_ocp_rated_ma', 'msvdd_output_ocp_max_ma'):
            self.assertEqual(fields[key]['evidence'][0]['format'], 'GB20x notebook rows13/14 type7; monitors 27/28')
            self.assertFalse(fields[key]['evidence'][0]['runtime_get'])
        self.assertIn('no saved GET', fields['msvdd_output_ocp_rated_ma']['reason'])
        self.assertNotIn('board_fixed_rated_w', fields)
        self.assertNotIn('input_current_rated_ma', fields)
        self.assertFalse(any(key.startswith('fan_') for key in fields))
        self.assertIsNone(backend(image).fan_coolers())
        changes = {'power_max_w': 250, 'power_default_w': 175, 'nvvdd_output_ocp_rated_ma': 250000,
                   'nvvdd_output_ocp_max_ma': 250000}
        result = edit(image, changes)
        self.assertTrue(result.manifest['integrity']['valid'])
        source, target = backend(image).power_rows(), backend(result.image).power_rows()
        changed_bytes_within(self, image, result, [source[2]['offset'] + 17, source[2]['offset'] + 21,
                                                   source[13]['offset'] + 17, source[13]['offset'] + 21])
        after = descriptors(result.image)
        for key, value in changes.items():
            self.assertEqual(after[key]['current'], value)
        self.assertEqual((target[2]['minimum_raw'], target[14]), (5000, source[14]))

    def test_layout_header_rows_profiles_and_id_gate_the_fields(self):
        for name, options in {'desktop header': dict(header=(0xFF, 8, 0xFF)), 'row 8 TGP': dict(row8_type=12),
                              'override profile': dict(profiles=True)}.items():
            with self.subTest(case=name):
                fields = descriptors(from_bytes(notebook_fixture(**options)))
                self.assertNotIn('power_max_w', fields)
                self.assertNotIn('nvvdd_output_ocp_rated_ma', fields if name != 'override profile' else {})
        for name, options in {'unlisted id': dict(device=0x2C58), 'channel chain': dict(chain=False)}.items():
            with self.subTest(case=name):
                fields = descriptors(from_bytes(notebook_fixture(**options)))
                self.assertTrue(fields['power_max_w']['editable'])
                self.assertFalse(fields['nvvdd_output_ocp_max_ma']['editable'])
                self.assertNotIn('msvdd_output_ocp_rated_ma', fields)

    def test_dram_flag_and_empty_fan_list_are_narrow(self):
        from nvidia_vbios.rom.errors import FormatError
        image = from_bytes(notebook_fixture(dram_descriptor=0x1043))
        with self.assertRaises(FormatError):
            backend(image).clock_ranges()
        report = inspect_image(from_bytes(notebook_fixture(fan_enable=1)))
        self.assertIn('unrecognized fan channel list', [d['message'] for d in report['diagnostics']])


class DramPointTests(unittest.TestCase):
    """The DRAM entries of a clock programming table (structure.dram_points)."""

    @staticmethod
    def table(points, version=0x40):
        # 8-byte header (version, header size, entry size 3, count), then flag byte + u16 MHz per entry.
        blob = bytearray((version, 8, 3, len(points) + 1, 0, 0, 0, 0))
        blob += bytes(3)  # an unrelated entry 0
        for flags, mhz in points:
            blob += bytes((flags,)) + struct.pack('<H', mhz)
        return bytes(blob)

    def test_reviewed_shape_and_refusals(self):
        from nvidia_vbios.rom.errors import FormatError
        from nvidia_vbios.rom.structure import dram_points
        stock = [(0x03, 405), (0x03, 810), (0x03, 5501), (0x13, 6001)]
        result = dram_points(self.table(stock), 0, 1, 4, 0x40)
        self.assertEqual([(p['index'], p['flags'], p['mhz']) for p in result['points']],
                         [(1, 0x03, 405), (2, 0x03, 810), (3, 0x03, 5501), (4, 0x13, 6001)])
        self.assertEqual((result['points'][0]['offset'], result['size']), (11, 8 + 3 * 5))
        self.assertEqual(len(dram_points(self.table(stock, 0x50), 0, 1, 4, 0x50)['points']), 4)
        bad = {'version': (self.table(stock), 0x50),
               'other flag byte': (self.table([(0x03, 405), (0x03, 810), (0x01, 5501), (0x13, 6001)]), 0x40),
               'not rising': (self.table([(0x03, 405), (0x03, 810), (0x03, 6001), (0x13, 5501)]), 0x40),
               'idle level with the bit': (self.table([(0x03, 405), (0x13, 810), (0x13, 5501), (0x13, 6001)]), 0x40),
               'bit not on a top run': (self.table([(0x03, 405), (0x03, 810), (0x13, 5501), (0x03, 6001)]), 0x40),
               'no level with the bit': (self.table([(0x03, 405), (0x03, 810), (0x03, 5501), (0x03, 6001)]), 0x40)}
        for name, (blob, version) in bad.items():
            with self.subTest(case=name), self.assertRaises(FormatError):
                dram_points(blob, 0, 1, 4, version)
        # A table that claims more entries (or a header) than the image holds is refused, not read past.
        long = bytearray(self.table(stock))
        long[3] = 12
        for name, (blob, at) in {'entries past the end': (bytes(long), 0),
                                 'header past the end': (bytes(4), 0)}.items():
            with self.subTest(case=name), self.assertRaises(FormatError):
                dram_points(blob, at, 1, 4, 0x40)

    def test_synthetic_images_offer_no_memory_level_field(self):
        # The synthetic images store no clock programming table: no field and no diagnostic.
        for image in (from_bytes(synthetic_blackwell(fans=True)), from_bytes(synthetic_rom(copies=2, fans=2)),
                      from_bytes(synthetic_rom(family='ampere', fans=2))):
            report = inspect_image(image)
            self.assertFalse([f['key'] for f in report['fields'] if f['key'].startswith('memory_point_')])
            self.assertFalse([d for d in report['diagnostics'] if d.get('resolver') == 'dram_offset_points'])


class FanCoolerTests(unittest.TestCase):
    """Fan channels across the cooler, policy and mapping tables, and the PWM frequency."""

    def table(self, blob):
        return backend(from_bytes(bytes(blob))).fan_coolers()

    def coolers(self, blob):
        table = self.table(blob)
        return table['offset'], [r['offset'] for r in table['rows']]

    ENABLES = ('offset', 'policy_offset', 'mapping_offset', 'control_offset', 'speed_offset')

    def channel_bytes(self, blob):
        t = self.table(blob)
        return (bytes(blob[t['offset'] + 4:t['offset'] + 8]),) + tuple(
            [blob[r[k]] for r in t['rows']] for k in self.ENABLES)

    def test_channels_and_pwm_frequency(self):
        image = from_bytes(synthetic_blackwell(fans=True))
        fields = descriptors(image)
        channels, pwm = fields['fan_channels'], fields['fan_pwm_frequency_hz']
        # Rows 0/1 active, row 2 a stored idle channel, row 3 a placeholder: at most 3.
        self.assertEqual((channels['current'], channels['editable'], channels['bounds']['minimum'],
                          channels['bounds']['maximum'], channels['fan_rows']), (2, True, 1, 3, [0, 1, 2]))
        self.assertEqual((pwm['current'], pwm['units'], pwm['editable'], pwm['experimental']), (27000, 'Hz', True, True))
        self.assertEqual((pwm['bounds']['minimum'], pwm['bounds']['maximum'], pwm['fan_rows']), (21000, 28000, [0, 1, 2]))
        self.assertEqual([e['kind'] for e in pwm['evidence']],
                         ['structural-table', 'read-only-nvml-correlation', 'third-party-tool-reading'])
        at, rows = self.coolers(image.blob)
        result = edit(image, {'fan_pwm_frequency_hz': 25000})
        self.assertTrue(result.manifest['integrity']['valid'])
        changed_bytes_within(self, image, result, [r + 11 for r in rows[:3]], width=2)
        self.assertEqual([r['pwm_frequency_hz'] for r in self.table(result.blob)['rows']], [25000, 25000, 25000, 27000])
        for value, code in ((20999, 'OUT_OF_BOUNDS'), (28001, 'OUT_OF_BOUNDS'), ('25000.5', 'UNREPRESENTABLE_VALUE')):
            with self.subTest(value=value), self.assertRaises(VbiosError) as exc:
                edit(image, {'fan_pwm_frequency_hz': value})
            self.assertEqual(exc.exception.code, code)

    def zero_rpm_fixture(self, flags=None, *, stop=True, entries=None):
        """The fan fixture with flag bytes (channel entries, extra curves) on the policy entries the field writes
        (zero_rpm_offsets), or on the given ones; stop=False empties their fan-stop parameters as the RTX PRO
        6000 Max-Q does."""
        blob = bytearray(synthetic_blackwell(fans=True))
        t = self.table(blob)
        covered = t['rows'][:3] + t['extra_curves']
        for e in covered if entries is None else [e for e in covered if e['index'] in entries]:
            if flags is not None:
                blob[e['flag_offset']] = flags[e['index'] >= len(t['rows'])]
            if not stop:
                struct.pack_into('<HH', blob, e['policy_offset'] + 30, 0, 0)
                blob[e['policy_offset'] + 46] = 0xFF
        return from_bytes(repair_fixture(blob))

    def zero_rpm_offsets(self, blob):
        # Channels 0/1, the stored third channel a larger count enables and the enabled curves 4/5.
        t = self.table(blob)
        return [r['flag_offset'] for r in t['rows'][:3]] + [c['flag_offset'] for c in t['extra_curves']]

    def test_zero_rpm_flag_covers_enabled_entries_and_round_trips(self):
        image = from_bytes(synthetic_blackwell(fans=True))
        field = descriptors(image)['fan_zero_rpm']
        # Channels 0/1, the stored third channel a larger count enables (as the PWM frequency covers
        # it) and the enabled curves 4/5 past the cooler rows; every flag byte holds 0.
        self.assertEqual((field['current'], field['units'], field['editable'], field['experimental'], field['opt_in'],
                          field['fan_entries']), (0, 'flag', True, True, True, [0, 1, 2, 4, 5]))
        self.assertEqual((field['bounds']['minimum'], field['bounds']['maximum']), (0, 1))
        self.assertEqual([e['kind'] for e in field['evidence']],
                         ['static-firmware-analysis', 'structural-table', 'static-driver-analysis',
                          'idle-fan-behavior-correlation', 'hardware-test'])
        # Not a curve point: curve selections and the fan_policy key stay with the curves.
        self.assertNotIn('fan_policy', field)
        offsets = self.zero_rpm_offsets(image.blob)
        on = edit(image, {'fan_zero_rpm': 1})
        self.assertTrue(on.manifest['integrity']['valid'])
        changed_bytes_within(self, image, on, offsets, width=1)
        self.assertEqual([on.blob[at] for at in offsets], [0x06] * len(offsets))
        t = self.table(on.blob)
        self.assertEqual([r['flag_byte'] for r in t['rows']] + [c['flag_byte'] for c in t['extra_curves']],
                         [6, 6, 6, 0, 6, 6])
        self.assertEqual(descriptors(on.image)['fan_zero_rpm']['current'], 1)
        self.assertEqual(edit(on.image, {'fan_zero_rpm': 0}).blob, image.blob)
        self.assertEqual(edit(image, {'fan_zero_rpm': 0}).manifest['changed_bytes'], 0)
        for value in (2, -1):
            with self.subTest(value=value), self.assertRaises(VbiosError) as exc:
                edit(image, {'fan_zero_rpm': value})
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        # The other flag bits stay: the RTX PRO bytes 0x11/0x01 become the GeForce 0x17/0x07 and back.
        pro = self.zero_rpm_fixture((0x11, 0x01))
        self.assertEqual(descriptors(pro)['fan_zero_rpm']['current'], 0)
        on = edit(pro, {'fan_zero_rpm': 1})
        self.assertEqual([on.blob[at] for at in offsets], [0x17, 0x17, 0x17, 0x07, 0x07])
        self.assertEqual(edit(on.image, {'fan_zero_rpm': 0}).blob, pro.blob)
        # Bit 0 clear, as on the XOC-class images: 0x16/0x06 clears to 0x10/0x00.
        xoc = self.zero_rpm_fixture((0x16, 0x06))
        off = edit(xoc, {'fan_zero_rpm': 0})
        self.assertEqual([off.blob[at] for at in offsets], [0x10, 0x10, 0x10, 0x00, 0x00])
        self.assertEqual(edit(off.image, {'fan_zero_rpm': 1}).blob, xoc.blob)

    def test_zero_rpm_read_only_when_enabled_entries_disagree(self):
        image = self.zero_rpm_fixture((0x07, 0x07), entries=(0,))  # only channel 0 sets both bits
        field = descriptors(image)['fan_zero_rpm']
        self.assertEqual((field['current'], field['editable'], field['opt_in']), (None, False, True))
        self.assertIn('disagree', field['reason'])
        for value in (0, 1):
            with self.subTest(value=value), self.assertRaises(VbiosError) as exc:
                edit(image, {'fan_zero_rpm': value})
            self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')

    def test_zero_rpm_read_only_with_one_bit_alone(self):
        # GSP-RM decodes bits 1 and 2 separately; some Ampere images store 0x13/0x03 (bit 1 alone).
        for flags in ((0x13, 0x03), (0x15, 0x05), (0x17, 0x03)):
            with self.subTest(flags=flags):
                image = self.zero_rpm_fixture(flags)
                field = descriptors(image)['fan_zero_rpm']
                self.assertEqual((field['current'], field['editable']), (None, False))
                self.assertIn('only one of bits 1 and 2', field['reason'])
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'fan_zero_rpm': 0})
                self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')

    def test_zero_rpm_one_needs_the_fan_stop_parameters(self):
        # The RTX PRO 6000 Max-Q: 0x01 on every enabled entry, zero temperatures and 0xff at byte 46.
        maxq = self.zero_rpm_fixture((0x01, 0x01), stop=False)
        field = descriptors(maxq)['fan_zero_rpm']
        self.assertEqual((field['current'], field['editable'], field['bounds']['maximum']), (0, False, None))
        self.assertIn('RTX PRO 6000 Max-Q', field['reason'])
        with self.assertRaises(VbiosError) as exc:
            edit(maxq, {'fan_zero_rpm': 1})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')
        # One entry without them is enough to withhold 1: zero, falling or 0xff-marked parameters.
        blob = synthetic_blackwell(fans=True)
        extra = self.table(blob)['extra_curves'][1]['policy_offset']
        third = self.table(blob)['rows'][2]['policy_offset']
        for name, at, value in (('temperatures zero', extra + 30, bytes(4)),
                                ('temperatures falling', extra + 30, struct.pack('<HH', 50 * 32, 43 * 32)),
                                ('byte 46', extra + 46, b'\xff'), ('stored third channel', third + 30, bytes(4))):
            with self.subTest(case=name):
                image = from_bytes(repair_fixture(bytearray(blob[:at] + value + blob[at + len(value):])))
                self.assertFalse(descriptors(image)['fan_zero_rpm']['editable'])
        # Set bits can still be cleared there; the copy then offers nothing.
        stopped = self.zero_rpm_fixture((0x07, 0x07), stop=False)
        field = descriptors(stopped)['fan_zero_rpm']
        self.assertEqual((field['current'], field['editable']), (1, True))
        off = edit(stopped, {'fan_zero_rpm': 0})
        self.assertEqual(descriptors(off.image)['fan_zero_rpm']['editable'], False)

    def test_channel_count_and_zero_rpm_are_separate_edits(self):
        image = from_bytes(synthetic_blackwell(fans=True))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_channels': 3, 'fan_zero_rpm': 1})
        self.assertEqual((exc.exception.code, exc.exception.details['fields']),
                         ('SEPARATE_EDIT_REQUIRED', ['fan_channels', 'fan_zero_rpm']))
        # The channel count first: the stored third channel's entry stays in the field.
        three = edit(image, {'fan_channels': 3})
        field = descriptors(three.image)['fan_zero_rpm']
        self.assertEqual((field['current'], field['editable'], field['fan_entries']), (0, True, [0, 1, 2, 4, 5]))
        on = edit(three.image, {'fan_zero_rpm': 1})
        offsets = self.zero_rpm_offsets(three.blob)
        changed_bytes_within(self, three.image, on, offsets, width=1)
        self.assertEqual([on.blob[at] for at in offsets], [0x06] * 5)
        self.assertEqual(edit(on.image, {'fan_zero_rpm': 0}).blob, three.blob)
        # The other order gives the same bytes: the third channel's entry already took the bits.
        early = edit(image, {'fan_zero_rpm': 1})
        late = edit(early.image, {'fan_channels': 3})
        self.assertEqual(late.blob, on.blob)
        self.assertNotIn('fan_zero_rpm', [a['field'] for a in late.manifest['affected_fields']])
        # Lowering the count leaves the entries as they are, so the field still covers the third channel.
        lower = edit(on.image, {'fan_channels': 2})
        self.assertEqual(lower.blob, early.blob)
        self.assertEqual(descriptors(lower.image)['fan_zero_rpm']['fan_entries'], [0, 1, 2, 4, 5])
        # A stored third channel whose bits differ from the enabled entries leaves the field read-only.
        mixed = self.zero_rpm_fixture((0x17, 0x07), entries=(0, 1, 4, 5))
        field = descriptors(mixed)['fan_zero_rpm']
        self.assertEqual((field['current'], field['editable']), (1, False))
        self.assertIn('larger channel count', field['reason'])
        with self.assertRaises(VbiosError) as exc:
            edit(mixed, {'fan_zero_rpm': 0})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')

    def test_extensions_cannot_rewrite_the_flag_bytes(self):
        from nvidia_vbios.editor import FieldRegistry
        from nvidia_vbios.editor.registry import fan_zero_rpm
        image = from_bytes(synthetic_blackwell(fans=True))
        t = self.table(image.blob)
        reviewed = fan_zero_rpm(image, backend(image))[0]
        probes = {'enabled entry flag': (t['rows'][0]['flag_offset'],), 'inactive entry flag': (t['rows'][2]['flag_offset'],),
                  'byte before the flag': (t['rows'][0]['flag_offset'] - 1,)}
        for name, offsets in probes.items():
            with self.subTest(probe=name), self.assertRaises(VbiosError) as exc:
                edit(image, {'probe': 6}, field_registry=custom_registry('probe', offsets, encoding='<B', scale=1,
                                                                         bounds={'minimum': 0, 'maximum': 255}))
            self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')
        # The reviewed key over fewer offsets is not canonical, so its bytes are refused.
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_zero_rpm': 6}, field_registry=custom_registry(
                'fan_zero_rpm', reviewed.offsets[:1], encoding='<B', scale=1, bounds={'minimum': 0, 'maximum': 255}))
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')
        # A canonical zero RPM request does not make the neighboring byte writable.
        both = FieldRegistry()
        both.register(fan_zero_rpm)
        both.register(custom_registry('probe', (t['rows'][0]['flag_offset'] - 1,), encoding='<B', scale=1,
                                      bounds={'minimum': 0, 'maximum': 255})._resolvers[0])
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_zero_rpm': 1, 'probe': 1}, field_registry=both)
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')

    TEMPS = ('fan_1', 'fan_2', 'fan_extra_1', 'fan_extra_2')

    def test_zero_rpm_temperatures_cover_enabled_entries_and_round_trip(self):
        image = from_bytes(synthetic_blackwell(fans=True))
        t = self.table(image.blob)
        fields = descriptors(image)
        keys = [f'{p}_zero_rpm_{side}_temp_c' for p in self.TEMPS for side in ('low', 'high')]
        # Channels 0/1 and the curves 4/5: not the stored third channel, nor the placeholder.
        self.assertEqual(sorted(k for k in fields if '_zero_rpm_' in k), sorted(keys))
        low, high = fields['fan_1_zero_rpm_low_temp_c'], fields['fan_1_zero_rpm_high_temp_c']
        self.assertEqual((low['current'], low['bounds']['minimum'], low['bounds']['maximum'], low['units'],
                          low['editable'], low['experimental'], low['opt_in'], low['fan_policy'], low['fan_channel']),
                         (43.0, 0.03125, 49.96875, 'C', True, True, True, 0, 0))
        self.assertEqual((high['current'], high['bounds']['minimum'], high['bounds']['maximum']),
                         (50.0, 43.03125, 110.0))
        self.assertEqual(low['ordering_group'], high['ordering_group'])
        self.assertNotEqual(low['ordering_group'], fields['fan_2_zero_rpm_low_temp_c']['ordering_group'])
        extra = fields['fan_extra_2_zero_rpm_low_temp_c']
        self.assertEqual((extra['fan_policy'], extra['fan_rows']), (5, [0, 1]))
        self.assertNotIn('fan_channel', extra)
        self.assertEqual([e['kind'] for e in low['evidence']],
                         ['static-firmware-analysis', 'structural-table', 'hardware-test'])
        # One word per field, in 1/32 C; the other bytes of the entry (flags, byte 46, curves) stay.
        pair = t['rows'][0]['policy_offset'] + 30
        result = edit(image, {'fan_1_zero_rpm_high_temp_c': 60})
        self.assertTrue(result.manifest['integrity']['valid'])
        changed_bytes_within(self, image, result, [pair + 2], width=2)
        self.assertEqual(struct.unpack_from('<HH', result.blob, pair), (43 * 32, 60 * 32))
        self.assertEqual(descriptors(result.image)['fan_1_zero_rpm_low_temp_c']['bounds']['maximum'], 59.96875)
        self.assertEqual(edit(result.image, {'fan_1_zero_rpm_high_temp_c': 50}).blob, image.blob)
        exact = edit(image, {'fan_1_zero_rpm_low_temp_c': '43.03125'})
        self.assertEqual(struct.unpack_from('<H', exact.blob, pair)[0], 43 * 32 + 1)
        # Both words of the pair move together past the stored values; the curves 4/5 alone, too.
        both = edit(image, {'fan_1_zero_rpm_low_temp_c': 55, 'fan_1_zero_rpm_high_temp_c': 60})
        changed_bytes_within(self, image, both, [pair], width=4)
        self.assertEqual(struct.unpack_from('<HH', both.blob, pair), (55 * 32, 60 * 32))
        self.assertEqual(edit(both.image, {'fan_1_zero_rpm_low_temp_c': 43, 'fan_1_zero_rpm_high_temp_c': 50}).blob,
                         image.blob)
        curve = t['extra_curves'][1]['policy_offset'] + 30
        extras = edit(image, {'fan_extra_2_zero_rpm_low_temp_c': 65, 'fan_extra_2_zero_rpm_high_temp_c': 75})
        changed_bytes_within(self, image, extras, [curve], width=4)
        for request, code in (({'fan_1_zero_rpm_low_temp_c': 0}, 'OUT_OF_BOUNDS'),
                              ({'fan_1_zero_rpm_low_temp_c': 50}, 'OUT_OF_BOUNDS'),
                              ({'fan_1_zero_rpm_low_temp_c': 55}, 'OUT_OF_BOUNDS'),
                              ({'fan_1_zero_rpm_high_temp_c': 43}, 'OUT_OF_BOUNDS'),
                              ({'fan_1_zero_rpm_high_temp_c': '110.03125'}, 'OUT_OF_BOUNDS'),
                              ({'fan_1_zero_rpm_low_temp_c': 50, 'fan_1_zero_rpm_high_temp_c': 50}, 'OUT_OF_BOUNDS'),
                              ({'fan_1_zero_rpm_low_temp_c': 60, 'fan_1_zero_rpm_high_temp_c': 55}, 'OUT_OF_BOUNDS'),
                              ({'fan_1_zero_rpm_low_temp_c': 0, 'fan_1_zero_rpm_high_temp_c': 50}, 'OUT_OF_BOUNDS'),
                              ({'fan_1_zero_rpm_low_temp_c': '43.01'}, 'UNREPRESENTABLE_VALUE')):
            with self.subTest(request=request), self.assertRaises(VbiosError) as exc:
                edit(image, request)
            self.assertEqual(exc.exception.code, code)

    def test_zero_rpm_temperatures_keep_the_flag_bits(self):
        # Zero RPM off (RTX PRO bytes) keeps its pairs editable, and an edit leaves the flags as they are.
        for flags in ((0x11, 0x01), (0x17, 0x07)):
            with self.subTest(flags=flags):
                image = self.zero_rpm_fixture(flags)
                state = descriptors(image)['fan_zero_rpm']['current']
                result = edit(image, {'fan_2_zero_rpm_high_temp_c': 60})
                offsets = self.zero_rpm_offsets(image.blob)
                self.assertEqual([result.blob[at] for at in offsets], [image.blob[at] for at in offsets])
                self.assertEqual(descriptors(result.image)['fan_zero_rpm']['current'], state)
        # Bits that disagree leave the flag read-only; the pairs stay editable and the bits are not normalized.
        mixed = self.zero_rpm_fixture((0x07, 0x07), entries=(0,))
        result = edit(mixed, {'fan_1_zero_rpm_high_temp_c': 60})
        offsets = self.zero_rpm_offsets(mixed.blob)
        self.assertEqual([result.blob[at] for at in offsets], [mixed.blob[at] for at in offsets])

    def test_zero_rpm_temperatures_only_where_stored(self):
        # The RTX PRO 6000 Max-Q stores 0/0 and 0xff at byte 46: nothing is synthesized.
        maxq = self.zero_rpm_fixture((0x01, 0x01), stop=False)
        self.assertFalse([k for k in descriptors(maxq) if k.endswith('_temp_c') and '_zero_rpm_' in k])
        blob = synthetic_blackwell(fans=True)
        t = self.table(blob)
        extra = t['extra_curves'][0]['policy_offset']
        for name, at, value in (('temperatures zero', extra + 30, bytes(4)),
                                ('temperatures equal', extra + 30, struct.pack('<HH', 50 * 32, 50 * 32)),
                                ('temperatures falling', extra + 30, struct.pack('<HH', 50 * 32, 43 * 32)),
                                ('byte 46', extra + 46, b'\xff')):
            with self.subTest(case=name):
                image = from_bytes(repair_fixture(bytearray(blob[:at] + value + blob[at + len(value):])))
                keys = {k for k in descriptors(image) if '_zero_rpm_' in k}
                self.assertEqual(keys, {f'{p}_zero_rpm_{side}_temp_c' for p in ('fan_1', 'fan_2', 'fan_extra_2')
                                        for side in ('low', 'high')})
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'fan_extra_1_zero_rpm_low_temp_c': 40})
                self.assertEqual(exc.exception.code, 'UNKNOWN_FIELD')
        # An upper temperature above 110 C keeps the pair visible but read-only.
        at = t['rows'][0]['policy_offset'] + 32
        hot = from_bytes(repair_fixture(bytearray(blob[:at] + struct.pack('<H', 111 * 32) + blob[at + 2:])))
        fields = descriptors(hot)
        self.assertEqual([(fields[f'fan_1_zero_rpm_{side}_temp_c']['current'],
                           fields[f'fan_1_zero_rpm_{side}_temp_c']['editable']) for side in ('low', 'high')],
                         [(43.0, False), (111.0, False)])
        self.assertIn('above 110 C', fields['fan_1_zero_rpm_high_temp_c']['reason'])
        with self.assertRaises(VbiosError) as exc:
            edit(hot, {'fan_1_zero_rpm_high_temp_c': 100})
        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')
        # The synthetic Ada image stores no pair: nothing is synthesized there either.
        ada = descriptors(from_bytes(synthetic_rom(copies=2, fans=2)))
        self.assertFalse([k for k in ada if '_zero_rpm_' in k])

    def test_channel_count_and_zero_rpm_temperatures_are_separate_edits(self):
        image = from_bytes(synthetic_blackwell(fans=True))
        for key in ('fan_1_zero_rpm_high_temp_c', 'fan_extra_1_zero_rpm_high_temp_c'):
            with self.subTest(key=key), self.assertRaises(VbiosError) as exc:
                edit(image, {'fan_channels': 3, key: 60})
            self.assertEqual((exc.exception.code, exc.exception.details['fields']),
                             ('SEPARATE_EDIT_REQUIRED', ['fan_channels', key]))
        # The stored third channel's pair shows once it is enabled, with its own stored bytes.
        three = edit(image, {'fan_channels': 3})
        fields = descriptors(three.image)
        self.assertEqual((fields['fan_3_zero_rpm_low_temp_c']['current'],
                          fields['fan_3_zero_rpm_high_temp_c']['current']), (43.0, 50.0))
        edited = edit(three.image, {'fan_3_zero_rpm_high_temp_c': 60})
        pair = self.table(three.blob)['rows'][2]['policy_offset'] + 30
        changed_bytes_within(self, three.image, edited, [pair + 2], width=2)

    def test_extensions_cannot_rewrite_the_zero_rpm_temperatures(self):
        from nvidia_vbios.editor import FieldRegistry
        from nvidia_vbios.editor.registry import fan_zero_rpm_temperatures
        image = from_bytes(synthetic_blackwell(fans=True))
        t = self.table(image.blob)
        pair = t['rows'][0]['policy_offset'] + 30
        probes = {'enabled entry lower': (pair,), 'inactive entry lower': (t['rows'][2]['policy_offset'] + 30,),
                  'byte 46': (t['rows'][0]['policy_offset'] + 46,)}
        for name, offsets in probes.items():
            with self.subTest(probe=name), self.assertRaises(VbiosError) as exc:
                edit(image, {'probe': 1}, field_registry=custom_registry('probe', offsets, encoding='<B', scale=1,
                                                                         bounds={'minimum': 0, 'maximum': 255}))
            self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')
        # The reviewed key over another entry's bytes is not canonical, so its bytes are refused.
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_1_zero_rpm_high_temp_c': 60}, field_registry=custom_registry(
                'fan_1_zero_rpm_high_temp_c', (t['rows'][1]['policy_offset'] + 32,), encoding='<H', scale=32,
                bounds={'minimum': 0, 'maximum': 110}))
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')
        # A canonical pair request does not make byte 46 writable.
        both = FieldRegistry()
        both.register(fan_zero_rpm_temperatures)
        both.register(custom_registry('probe', (t['rows'][0]['policy_offset'] + 46,), encoding='<B', scale=1,
                                      bounds={'minimum': 0, 'maximum': 255})._resolvers[0])
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_1_zero_rpm_high_temp_c': 60, 'probe': 1}, field_registry=both)
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')

    def test_channel_count_writes_all_three_tables_and_round_trips(self):
        image = from_bytes(synthetic_blackwell(fans=True))
        t = self.table(image.blob)
        three = edit(image, {'fan_channels': 3})
        self.assertEqual(self.channel_bytes(three.blob), (bytes((0, 1, 2, 0xFF)), [2, 2, 2, 0]) + ([1, 1, 1, 0],) * 4)
        row2 = t['rows'][2]
        changed_bytes_within(self, image, three, [t['offset'] + 6] + [row2[k] for k in self.ENABLES], width=1)
        self.assertEqual([(e['after'], e['stored_units']) for e in three.manifest['edits']],
                         [(2, 'layout byte'), (2, 'layout byte')] + [(1, 'layout byte')] * 4)
        self.assertEqual(three.manifest['affected_fields'][0]['after'], 3)
        one = edit(three.image, {'fan_channels': 1})
        self.assertEqual(self.channel_bytes(one.blob), (bytes((0, 0xFF, 0xFF, 0xFF)), [2, 0, 0, 0]) + ([1, 0, 0, 0],) * 4)
        self.assertEqual(edit(one.image, {'fan_channels': 2}).blob, image.blob)
        both = edit(image, {'fan_channels': 3, 'fan_pwm_frequency_hz': 25000})
        self.assertEqual([r['pwm_frequency_hz'] for r in self.table(both.blob)['rows']][:3], [25000] * 3)
        for value in (0, 4):
            with self.subTest(value=value), self.assertRaises(VbiosError) as exc:
                edit(image, {'fan_channels': value})
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_only_stored_channels_can_be_enabled(self):
        blob = bytearray(synthetic_blackwell(fans=True))
        t = self.table(blob)
        row = {r['index']: r for r in t['rows']}

        def copy_row0(b, i):
            b[row[i]['offset'] + 4:row[i]['offset'] + 6] = bytes((0x3D, 2))
            b[row[i]['offset'] + 10] = 0x09

        def store(b, i):
            b[row[i]['offset'] + 4:row[i]['offset'] + 6] = bytes((0x20 + i, 2))
            b[row[i]['offset'] + 10] = 0x20 + i
            b[row[i]['policy_offset'] + 1] = 1
            b[row[i]['mapping_offset'] + 1] = i
            b[row[i]['control_offset'] + 2] = i
            b[row[i]['control_offset'] + 5] = 0x30 | 1 << i
            b[row[i]['speed_offset'] + 1] = i
        cases = {'row 2 copies row 0': (lambda b: copy_row0(b, 2), 2),
                 'row 2 other frequency': (lambda b: b.__setitem__(slice(row[2]['offset'] + 11, row[2]['offset'] + 14),
                                                                   (25000).to_bytes(3, 'little')), 2),
                 'row 2 byte 13': (lambda b: b.__setitem__(row[2]['offset'] + 13, 1), 2),
                 'row 2 mapping names row 0': (lambda b: b.__setitem__(row[2]['mapping_offset'] + 1, 0), 2),
                 'row 2 placeholder policy': (lambda b: b.__setitem__(row[2]['policy_offset'] + 1, 0), 2),
                 'row 2 control names another channel': (lambda b: b.__setitem__(row[2]['control_offset'] + 2, 0xFF), 2),
                 'row 2 control mask': (lambda b: b.__setitem__(row[2]['control_offset'] + 5, 0x06), 2),
                 'row 2 placeholder speed entry': (lambda b: b.__setitem__(row[2]['speed_offset'] + 1, 0xFF), 2),
                 # A gap stops the scan: row 3 stays off even when it is stored.
                 'gap before a stored row 3': (lambda b: (copy_row0(b, 2), store(b, 3)), 2),
                 # A row equal to an idle earlier row is not a new channel.
                 'row 3 copies idle row 2': (lambda b: (store(b, 3), b.__setitem__(slice(row[3]['offset'] + 4, row[3]['offset'] + 6),
                                                                                    bytes((0xFB, 2))),
                                                        b.__setitem__(row[3]['offset'] + 10, 0xFA)), 3),
                 'stored row 3': (lambda b: store(b, 3), 4),
                 # The extra curves serve every active channel: row 2's limits must hold them.
                 'row 2 maximum below the extra curves': (lambda b: struct.pack_into('<H', b, row[2]['offset'] + 16, 3400), 2),
                 'row 2 level minimum above the extra curves': (lambda b: b.__setitem__(row[2]['offset'] + 2, 30), 2)}
        for name, (change, most) in cases.items():
            with self.subTest(case=name):
                b = bytearray(blob)
                change(b)
                image = from_bytes(repair_fixture(b))
                self.assertEqual(descriptors(image)['fan_channels']['bounds']['maximum'], most)
                with self.assertRaises(VbiosError):
                    edit(image, {'fan_channels': most + 1})
        # Extra curves edited past the stored idle row keep it off, and past a cleared row keep it cleared.
        image = from_bytes(bytes(blob))
        top = {'fan_extra_1_curve_3_rpm': 4000, 'fan_extra_2_curve_3_rpm': 4000}
        wide = edit(image, dict(top, fan_1_max_rpm=4000, fan_2_max_rpm=4000)).image
        one = edit(edit(image, {'fan_channels': 1}).image, dict(top, fan_1_max_rpm=4000)).image
        for edited, count, code in ((wide, 3, 'OUT_OF_BOUNDS'), (one, 2, 'FIELD_READ_ONLY')):
            with self.subTest(count=count), self.assertRaises(VbiosError) as exc:
                edit(edited, {'fan_channels': count})
            self.assertEqual(exc.exception.code, code)

    def test_single_channel_without_stored_channels_is_read_only(self):
        blob = bytearray(synthetic_blackwell(fans=True))
        t = self.table(blob)
        b = bytearray(blob)
        b[t['offset'] + 5] = 0xFF
        for r in t['rows'][1:]:
            b[r['offset']] = b[r['policy_offset']] = b[r['mapping_offset']] = 0
            b[r['control_offset']] = b[r['speed_offset']] = 0
            b[r['mapping_offset'] + 1] = 0
        single = descriptors(from_bytes(repair_fixture(b)))['fan_channels']
        self.assertEqual((single['current'], single['editable']), (1, False))
        self.assertEqual(single['reason'], "no other fan channel layout is stored in this table, or a stored channel's "
                                           'limits do not hold the extra fan curves')

    def test_tables_lists_and_shared_values_gate_the_fields(self):
        blob = synthetic_blackwell(fans=True)
        t = self.table(blob)
        at, rows = t['offset'], t['rows']

        def only_row0(b):
            for k in self.ENABLES:
                b[rows[1][k]] = 0
        absent = {'version': lambda b: b.__setitem__(at, 0x11),
                  'row size': lambda b: b.__setitem__(at + 2, 0x1B),
                  'policy header': lambda b: b.__setitem__(t['policy_offset'] + 3, 0x0C),
                  'mapping header': lambda b: b.__setitem__(t['mapping_offset'] + 2, 6),
                  'list not from zero': lambda b: (only_row0(b), b.__setitem__(slice(at + 4, at + 8), bytes((1, 0xFF, 0xFF, 0xFF)))),
                  # Only row 1 active, consistently in all three tables: still refused.
                  'list starts at row 1': lambda b: (b.__setitem__(slice(at + 4, at + 8), bytes((1, 0xFF, 0xFF, 0xFF))),
                                                     [b.__setitem__(rows[0][k], 0) for k in self.ENABLES]),
                  'list gap': lambda b: (only_row0(b), b.__setitem__(slice(at + 4, at + 8), bytes((0, 0xFF, 1, 0xFF)))),
                  # An empty list with every enable cleared is the notebook's "no GPU fans" (NotebookLayoutTests).
                  'empty list, a row enabled': lambda b: (only_row0(b), b.__setitem__(slice(at + 4, at + 8), b'\xff' * 4)),
                  'enabled row not listed': lambda b: b.__setitem__(rows[2]['offset'], 2),
                  'listed row disabled': lambda b: b.__setitem__(rows[1]['offset'], 0),
                  'policy enable disagrees': lambda b: b.__setitem__(rows[2]['policy_offset'], 1),
                  'mapping enable disagrees': lambda b: b.__setitem__(rows[1]['mapping_offset'], 0),
                  'active mapping names another row': lambda b: b.__setitem__(rows[1]['mapping_offset'] + 1, 0),
                  'active placeholder policy': lambda b: b.__setitem__(rows[1]['policy_offset'] + 1, 0),
                  'control enable disagrees': lambda b: b.__setitem__(rows[2]['control_offset'], 1),
                  'speed enable disagrees': lambda b: b.__setitem__(rows[1]['speed_offset'], 0),
                  'active control not stored': lambda b: b.__setitem__(rows[1]['control_offset'] + 5, 0x31),
                  'active speed not stored': lambda b: b.__setitem__(rows[1]['speed_offset'] + 1, 0xFF),
                  'control header': lambda b: b.__setitem__(t['control_offset'] + 2, 0x0E),
                  'speed header': lambda b: b.__setitem__(t['speed_offset'] + 3, 5)}
        for name, change in absent.items():
            with self.subTest(case=name):
                b = bytearray(blob)
                change(b)
                report = inspect_image(from_bytes(repair_fixture(b)))
                self.assertFalse(any(f['key'].startswith('fan_') for f in report['fields']))
                self.assertTrue(any(d.get('resolver') == 'fans' for d in report['diagnostics']))
        read_only = {'unequal frequencies': lambda b: b.__setitem__(slice(rows[1]['offset'] + 11, rows[1]['offset'] + 14),
                                                                   (25000).to_bytes(3, 'little')),
                     'byte 13 on every active row': lambda b: [b.__setitem__(r['offset'] + 13, 1) for r in rows[:2]]}
        for name, change in read_only.items():
            with self.subTest(case=name):
                b = bytearray(blob)
                change(b)
                fields = descriptors(from_bytes(repair_fixture(b)))
                self.assertFalse(fields['fan_pwm_frequency_hz']['editable'])
                self.assertFalse(fields['fan_channels']['editable'])
                self.assertEqual(fields['fan_channels']['current'], 2)
        b = bytearray(blob)
        for r in rows:
            b[r['offset'] + 11:r['offset'] + 14] = (30000).to_bytes(3, 'little')
        fields = descriptors(from_bytes(repair_fixture(b)))
        self.assertFalse(fields['fan_pwm_frequency_hz']['editable'])
        self.assertTrue(fields['fan_channels']['editable'])
        for oid in (0x1D, 0x1E, 0x20, 0x80, 0x83):
            with self.subTest(owner=oid):
                owner = next(o for o in backend(from_bytes(blob)).objects if o['id'] == oid)
                b = bytearray(blob)
                struct.pack_into('<I', b, owner['header'], oid + 0x40)
                self.assertFalse(any(f['key'].startswith('fan_') for f in inspect_image(from_bytes(repair_fixture(b)))['fields']))
        self.assertFalse(any(f['key'].startswith('fan_') for f in descriptors(from_bytes(synthetic_blackwell())).values()))

    def test_extensions_cannot_rewrite_or_relax_the_fan_tables(self):
        from decimal import Decimal
        from nvidia_vbios.editor import Binding, FieldRegistry
        from nvidia_vbios.editor.registry import fans
        image = from_bytes(synthetic_blackwell(fans=True))
        t = self.table(image.blob)
        at, rows = t['offset'], [r['offset'] for r in t['rows']]
        r2 = t['rows'][2]
        probes = {'row 0 enable': ((rows[0],), '<B', 0), 'row 3 enable': ((rows[3],), '<B', 2),
                  'header list': ((at + 7,), '<B', 3), 'header version': ((at,), '<B', 0x11),
                  'row 0 byte 13': ((rows[0] + 13,), '<B', 1), 'inactive row 3 frequency': ((rows[3] + 11,), '<H', 1000),
                  'row 0 speed maximum': ((rows[0] + 16,), '<H', 9999), 'row 1 level minimum': ((rows[1] + 2,), '<B', 10),
                  'inactive row 3 speed minimum': ((rows[3] + 14,), '<H', 900),
                  'policy enable': ((r2['policy_offset'],), '<B', 1), 'policy curve': ((r2['policy_offset'] + 20,), '<B', 9),
                  'mapping enable': ((r2['mapping_offset'],), '<B', 1), 'mapping row': ((r2['mapping_offset'] + 1,), '<B', 0),
                  'control enable': ((r2['control_offset'],), '<B', 1), 'control other': ((r2['control_offset'] + 9,), '<B', 7),
                  'speed enable': ((r2['speed_offset'],), '<B', 1), 'speed value': ((r2['speed_offset'] + 2,), '<H', 999)}
        for name, (offsets, encoding, value) in probes.items():
            with self.subTest(probe=name), self.assertRaises(VbiosError) as exc:
                edit(image, {'probe': value}, field_registry=custom_registry('probe', offsets, encoding=encoding, scale=1,
                                                                             bounds={'minimum': 0, 'maximum': 65535}))
            self.assertIn(exc.exception.code, ('PRESERVED_FIELD_CHANGED', 'POSTCONDITION_FAILED'))
        reviewed = {b.descriptor['key']: b for b in fans(image, backend(image))}
        pwm, channels = reviewed['fan_pwm_frequency_hz'], reviewed['fan_channels']
        # The reviewed key with relaxed bounds keeps the reviewed band.
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_pwm_frequency_hz': 1000}, field_registry=custom_registry(
                'fan_pwm_frequency_hz', pwm.offsets, encoding='<H', scale=1, bounds={'minimum': 0, 'maximum': 65535}))
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        # The reviewed key over other offsets is not canonical, so its bytes are refused.
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_pwm_frequency_hz': 22000}, field_registry=custom_registry(
                'fan_pwm_frequency_hz', pwm.offsets[:1], encoding='<H', scale=1, bounds={'minimum': 0, 'maximum': 65535}))
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')
        # A canonical PWM request does not make byte 13 writable.
        both = FieldRegistry()
        both.register(fans)
        both.register(custom_registry('probe', (rows[0] + 13,), encoding='<B', scale=1,
                                      bounds={'minimum': 0, 'maximum': 255})._resolvers[0])
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_pwm_frequency_hz': 25000, 'probe': 1}, field_registry=both)
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')
        # A channel limit with relaxed bounds still may not cut into the stored curve.
        limit = reviewed['fan_1_min_rpm']
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_1_min_rpm': 2000}, field_registry=custom_registry(
                'fan_1_min_rpm', limit.offsets, encoding='<H', scale=1, bounds={'minimum': 0, 'maximum': 65535}))
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        # Over the maximum's bytes it is not canonical, so those bytes are refused.
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_1_min_rpm': 900}, field_registry=custom_registry(
                'fan_1_min_rpm', (rows[0] + 16,), encoding='<H', scale=1, bounds={'minimum': 0, 'maximum': 65535}))
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')
        # A curve point with relaxed bounds still may not pass its neighbors or limits.
        point = reviewed['fan_1_curve_3_rpm']
        for value in (3600, 2100):
            with self.subTest(value=value), self.assertRaises(VbiosError) as exc:
                edit(image, {'fan_1_curve_3_rpm': value}, field_registry=custom_registry(
                    'fan_1_curve_3_rpm', point.offsets, encoding='<H', scale=1, bounds={'minimum': 0, 'maximum': 65535}))
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        # Over another point's bytes it is not canonical, so those bytes are refused.
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_1_curve_3_rpm': 3000}, field_registry=custom_registry(
                'fan_1_curve_3_rpm', reviewed['fan_1_curve_2_rpm'].offsets, encoding='<H', scale=1,
                bounds={'minimum': 0, 'maximum': 65535}))
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')
        # A canonical limit does not make other curve bytes writable.
        curve = FieldRegistry()
        curve.register(fans)
        curve.register(custom_registry('probe', (t['rows'][0]['policy_offset'] + 20,), encoding='<H', scale=1,
                                       bounds={'minimum': 0, 'maximum': 65535})._resolvers[0])
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_1_min_rpm': 900, 'probe': 900}, field_registry=curve)
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')

        def layout_registry(layout, key='fan_channels', offsets=channels.offsets):
            custom = FieldRegistry()

            @custom.register
            def probe(image, parser):
                return [Binding(dict(channels.descriptor, key=key), tuple(offsets), '<B', Decimal(1), tuple(layout))]
            return custom
        # Same key, offsets, encoding and scale but another layout: not canonical.
        forged = tuple((value, tuple(bytes((7,)) if 4 <= i < 6 else chunk for i, chunk in enumerate(chunks)))
                       for value, chunks in channels.layout)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_channels': 2}, field_registry=layout_registry(forged))
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')
        # Malformed data-only layouts are refused before writing.
        three = dict(channels.layout)[3]
        for name, layout in {'value missing': tuple((v, c) for v, c in channels.layout if v != 3),
                             'too few chunks': ((3, three[:-1]),), 'wide chunk': ((3, (b'\x00\x01',) + three[1:]),)}.items():
            with self.subTest(layout=name), self.assertRaises(VbiosError) as exc:
                edit(image, {'probe_layout': 3}, field_registry=layout_registry(layout, key='probe_layout'))
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_inconsistent_or_unrecognized_fan_tables_accept_no_change(self):
        blob = bytearray(synthetic_blackwell(fans=True))
        t = self.table(blob)
        r0 = t['rows'][0]
        sources = {'mapping disagrees': lambda b: b.__setitem__(t['rows'][2]['mapping_offset'], 1),
                   'cooler version': lambda b: b.__setitem__(t['offset'], 0x11),
                   'policy header': lambda b: b.__setitem__(t['policy_offset'] + 1, 5),
                   'speed header': lambda b: b.__setitem__(t['speed_offset'] + 2, 7)}
        probes = {'cooler PWM': (r0['offset'] + 11, '<H', 1000), 'cooler list': (t['offset'] + 6, '<B', 2),
                  'policy entry': (r0['policy_offset'] + 20, '<B', 9), 'speed entry': (r0['speed_offset'] + 2, '<H', 999)}
        for source, change in sources.items():
            b = bytearray(blob)
            change(b)
            image = from_bytes(repair_fixture(b))
            self.assertTrue(image.report['integrity']['valid'])
            self.assertFalse(any(f['key'].startswith('fan_') for f in descriptors(image).values()))
            for name, (offset, encoding, value) in probes.items():
                with self.subTest(source=source, probe=name), self.assertRaises(VbiosError) as exc:
                    edit(image, {'probe': value}, field_registry=custom_registry(
                        'probe', (offset,), encoding=encoding, scale=1, bounds={'minimum': 0, 'maximum': 65535}))
                self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')

    def test_only_counts_that_can_be_undone_are_offered(self):
        blob = bytearray(synthetic_blackwell(fans=True))
        t = self.table(blob)
        r1 = t['rows'][1]
        cases = {name: (lambda b, at=r1[name]: b.__setitem__(at, 3)) for name in self.ENABLES}
        cases['row 1 copies row 0'] = lambda b: (b.__setitem__(slice(r1['offset'] + 4, r1['offset'] + 6), bytes((0x3D, 2))),
                                                  b.__setitem__(r1['offset'] + 10, 0x09))
        # Cleared, row 1 could not come back: its maximum is below the extra curves (as on the RTX 4080 Super).
        cases['row 1 below the extra curves'] = lambda b: struct.pack_into('<H', b, r1['offset'] + 16, 3400)
        for name, change in cases.items():
            with self.subTest(case=name):
                b = bytearray(blob)
                change(b)
                image = from_bytes(repair_fixture(b))
                channels = descriptors(image)['fan_channels']
                self.assertEqual((channels['bounds']['minimum'], channels['bounds']['maximum']), (2, 3))
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'fan_channels': 1})
                self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
                self.assertEqual(edit(edit(image, {'fan_channels': 3}).image, {'fan_channels': 2}).blob, image.blob)
        self.assertEqual(descriptors(from_bytes(bytes(blob)))['fan_channels']['bounds']['minimum'], 1)

    def test_read_only_reasons_follow_the_table_not_the_integrity(self):
        blob = bytearray(synthetic_blackwell(fans=True))
        clock = next(o for o in backend(from_bytes(bytes(blob))).objects if o['id'] == 3)
        blob[clock['data'] + clock['size'] - 1] ^= 1
        fields = descriptors(from_bytes(bytes(blob)))
        for key in ('fan_pwm_frequency_hz', 'fan_channels', 'fan_1_min_rpm', 'fan_2_max_rpm', 'fan_1_min_pct',
                    'fan_1_curve_2_temp_c', 'fan_extra_2_curve_3_rpm'):
            self.assertFalse(fields[key]['editable'])
            self.assertTrue(fields[key]['reason'].startswith('experimental:'), fields[key]['reason'])

    def test_channel_limits_stop_at_the_stored_curves(self):
        image = from_bytes(synthetic_blackwell(fans=True))
        fields = descriptors(image)
        rows = [r['offset'] for r in self.table(image.blob)['rows']]
        # Rows 0/1: 1050..3500 RPM and 20..100 %; their curves and entries 4/5 span exactly that.
        expected = {'min_rpm': (1050, 0, 1050, True), 'max_rpm': (3500, 3500, 32767, True),
                    'min_pct': (20, 0, 20, True), 'max_pct': (100, 100, 100, True)}
        for n in (1, 2):
            for name, (current, low, high, editable) in expected.items():
                with self.subTest(channel=n, field=name):
                    f = fields[f'fan_{n}_{name}']
                    self.assertEqual((f['current'], f['bounds']['minimum'], f['bounds']['maximum'], f['editable']),
                                     (current, low, high, editable))
                    speed = name.endswith('rpm')
                    self.assertEqual((f['units'], f['experimental'], f['fan_channel'], f['fan_rows'], bool(f.get('opt_in'))),
                                     ('RPM' if speed else '%', True, n - 1, [n - 1], not speed))
                    self.assertEqual(f['ordering_group'], f"fan-{'speed' if speed else 'level'}")
                    self.assertEqual(f['value_semantics'], 'stored-fan-%s-%s' % (
                        'minimum' if name.startswith('min') else 'maximum', 'speed' if speed else 'level'))
        self.assertTrue(all(fields[k]['reason'].startswith('experimental:') for k in ('fan_1_max_pct', 'fan_1_max_rpm')))
        # The driver percent maps linearly: 30 % runs at the row minimum, 100 % at the row maximum.
        minimum_reason = fields['fan_1_min_rpm']['reason']
        self.assertIn("the driver's 30 % setting matched the unchanged 1050 RPM minimum", minimum_reason)
        self.assertIn('1050-1110 RPM; what held that floor is unknown', minimum_reason)
        self.assertIn('linearly down to 30 % at the minimum', fields['fan_1_max_rpm']['reason'])
        self.assertEqual(fields['fan_2_max_rpm']['bounds']['encoding_maximum'], 32767)
        self.assertEqual([e['kind'] for e in fields['fan_1_min_rpm']['evidence']][:2],
                         ['structural-table', 'read-only-nvml-correlation'])
        self.assertFalse(any(key.startswith(('fan_3_', 'fan_4_')) for key in fields))
        # Each limit writes only its own bytes and reverts byte for byte.
        for key, value, at, width in (('fan_1_min_rpm', 900, rows[0] + 14, 2), ('fan_2_max_rpm', 4000, rows[1] + 16, 2),
                                      ('fan_2_min_pct', 15, rows[1] + 2, 1)):
            with self.subTest(key=key):
                result = edit(image, {key: value})
                self.assertTrue(result.manifest['integrity']['valid'])
                changed_bytes_within(self, image, result, [at], width=width)
                self.assertEqual(descriptors(result.image)[key]['current'], value)
                self.assertEqual(result.manifest['edits'][0]['stored_units'], fields[key]['units'])
                self.assertEqual(edit(result.image, {key: fields[key]['current']}).blob, image.blob)
        # A limit may not cut into the curve or leave its encoding range.
        for key, value, code in (('fan_1_min_rpm', 1051, 'OUT_OF_BOUNDS'), ('fan_1_max_rpm', 3499, 'OUT_OF_BOUNDS'),
                                 ('fan_1_max_rpm', 32768, 'OUT_OF_BOUNDS'), ('fan_2_min_pct', 21, 'OUT_OF_BOUNDS'),
                                 ('fan_1_min_rpm', -1, 'OUT_OF_BOUNDS'), ('fan_1_min_rpm', '900.5', 'UNREPRESENTABLE_VALUE'),
                                 ('fan_1_max_pct', 99, 'OUT_OF_BOUNDS')):
            with self.subTest(key=key, value=value), self.assertRaises(VbiosError) as exc:
                edit(image, {key: value})
            self.assertEqual(exc.exception.code, code)
        # Partners requested together are checked on the joint result.
        both = edit(image, {'fan_1_min_rpm': 500, 'fan_1_max_rpm': 32767})
        changed_bytes_within(self, image, both, [rows[0] + 14], width=4)
        # From limits past the curve, each one may also move back in as far as the curve.
        narrowed = descriptors(edit(both.image, {'fan_1_min_rpm': 1000, 'fan_1_max_rpm': 4000}).image)
        self.assertEqual([narrowed[k]['current'] for k in ('fan_1_min_rpm', 'fan_1_max_rpm')], [1000, 4000])
        for key, value in (('fan_1_min_rpm', 1051), ('fan_1_max_rpm', 3499)):
            with self.subTest(key=key, value=value), self.assertRaises(VbiosError) as exc:
                edit(both.image, {key: value})
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_1_min_rpm': 6000, 'fan_1_max_rpm': 5000})
        self.assertEqual((exc.exception.code, exc.exception.details['field'], exc.exception.details['joint_fields']),
                         ('OUT_OF_BOUNDS', 'fan_1_max_rpm', ['fan_1_max_rpm', 'fan_1_min_rpm']))

    def test_channel_count_and_limits_are_separate_edits(self):
        image = from_bytes(synthetic_blackwell(fans=True))
        t = self.table(image.blob)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_channels': 3, 'fan_2_max_rpm': 4000, 'fan_1_min_pct': 15})
        self.assertEqual((exc.exception.code, exc.exception.details['fields']),
                         ('SEPARATE_EDIT_REQUIRED', ['fan_channels', 'fan_1_min_pct', 'fan_2_max_rpm']))
        # The PWM frequency combines with the limits.
        both = edit(image, {'fan_pwm_frequency_hz': 25000, 'fan_2_max_rpm': 4000})
        changed_bytes_within(self, image, both, [r['offset'] + 11 for r in t['rows'][:3]] + [t['rows'][1]['offset'] + 16],
                             width=2)
        # Lowering the count drops channel 2's limits; raising it again restores its edited bytes.
        lowered = edit(both.image, {'fan_channels': 1})
        self.assertFalse(any(key.startswith('fan_2_') for key in descriptors(lowered.image)))
        self.assertEqual(edit(lowered.image, {'fan_channels': 2}).blob, both.blob)
        # Raising to three offers the stored third row's own limits.
        three = descriptors(edit(image, {'fan_channels': 3}).image)
        self.assertEqual((three['fan_3_min_rpm']['current'], three['fan_3_max_rpm']['editable']), (1050, True))

    def test_limits_outside_the_reviewed_shape_are_read_only(self):
        blob = synthetic_blackwell(fans=True)
        t = self.table(blob)
        row, policy = t['rows'][0]['offset'], t['rows'][0]['policy_offset']
        extra = t['policy_offset'] + 4 + 0x33 * 4  # entry 4, enabled past the cooler rows
        pack = lambda fmt, at, *values: (lambda b: struct.pack_into(fmt, b, at, *values))

        def above_ceilings(b):  # every curve of channel 1 starts above 32767 RPM and 100 %, the maximums higher still
            pack('<H', row + 16, 40000)(b)
            pack('<B', row + 3, 200)(b)
            for at in (policy, extra, extra + 0x33):
                pack('<3B', at + 14, 150, 160, 170)(b)
                for k, rpm in enumerate((33000, 34000, 35000)):
                    pack('<H', at + 20 + 4 * k, rpm)(b)
        cases = {'speed minimum above maximum':(pack('<HH', row + 14, 3500, 1050),
                                                 {'fan_1_min_rpm': False, 'fan_1_max_rpm': False, 'fan_1_min_pct': True}),
                 'curve below the speed minimum': (pack('<H', row + 14, 1100), {'fan_1_min_rpm': False, 'fan_1_max_rpm': True}),
                 'curve above the speed maximum': (pack('<H', row + 16, 3400), {'fan_1_min_rpm': True, 'fan_1_max_rpm': False}),
                 'speed maximum above 32767': (pack('<H', row + 16, 40000), {'fan_1_min_rpm': True, 'fan_1_max_rpm': False}),
                 'level maximum above 100': (pack('<B', row + 3, 101), {'fan_1_min_pct': True, 'fan_1_max_pct': False}),
                 'curve speeds not ascending': (pack('<H', policy + 24, 1000),
                                                {'fan_1_min_rpm': False, 'fan_1_max_rpm': False, 'fan_1_min_pct': False,
                                                 'fan_2_min_rpm': True}),
                 'curve temperatures not ascending': (pack('<H', policy + 22, 40 * 32),
                                                      {'fan_1_min_rpm': False, 'fan_1_min_pct': False, 'fan_2_max_rpm': True}),
                 'curve levels not ascending': (pack('<B', policy + 15, 10), {'fan_1_min_pct': False, 'fan_1_max_rpm': False}),
                 # A curve that is not the channel's own still has to fit: only the maximum stops.
                 'extra curve above the speed maximum': (pack('<H', extra + 28, 3600),
                                                         {'fan_1_min_rpm': True, 'fan_1_max_rpm': False,
                                                          'fan_2_min_rpm': True, 'fan_2_max_rpm': False}),
                 'last extra curve above the speed maximum': (pack('<H', extra + 0x33 + 28, 3600),
                                                              {'fan_1_min_rpm': True, 'fan_1_max_rpm': False}),
                 # The minimum may not rise past the ceiling with the curves either.
                 'curves above the ceilings': (above_ceilings, {'fan_1_min_rpm': False, 'fan_1_max_rpm': False,
                                                                'fan_1_min_pct': False, 'fan_1_max_pct': False}),
                 'disabled extra curve':(lambda b: (pack('<H', extra + 28, 3600)(b), b.__setitem__(extra, 0)),
                                          {'fan_1_max_rpm': True, 'fan_2_max_rpm': True})}
        for name, (change, editable) in cases.items():
            with self.subTest(case=name):
                b = bytearray(blob)
                change(b)
                fields = descriptors(from_bytes(repair_fixture(b)))
                for key, expected in editable.items():
                    f = fields[key]
                    self.assertEqual(f['editable'], expected, key)
                    self.assertTrue(f['reason'].startswith('experimental:') if expected else
                                    f['reason'] == 'fan row or policy curves hold values outside the reviewed shape', key)
                    self.assertTrue(all(isinstance(f['bounds'][k], int) for k in ('minimum', 'maximum')), key)
                    if not expected:
                        with self.assertRaises(VbiosError) as exc:
                            edit(from_bytes(repair_fixture(b)), {key: f['current']})
                        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')


    def test_curve_points_stay_between_their_neighbors_and_limits(self):
        image = from_bytes(synthetic_blackwell(fans=True))
        t = self.table(image.blob)
        fields = descriptors(image)
        # Channel curves 50/55/60 C, the extra ones (entries 4/5) 93/98/103 C; 1050/2200/3500 RPM and 20/50/100 %
        # inside rows 0/1 (1050..3500 RPM, 20..100 %).
        expected = {'fan_1_curve_1_temp_c': (50, 0, 54.96875), 'fan_1_curve_2_temp_c': (55, 50.03125, 59.96875),
                    'fan_2_curve_3_temp_c': (60, 55.03125, 110), 'fan_extra_2_curve_1_temp_c': (93, 0, 97.96875),
                    'fan_1_curve_1_rpm': (1050, 1050, 2200), 'fan_1_curve_2_rpm': (2200, 1050, 3500),
                    'fan_extra_1_curve_3_rpm': (3500, 2200, 3500), 'fan_2_curve_1_pct': (20, 20, 50),
                    'fan_extra_1_curve_3_pct': (100, 50, 100)}
        for key, (current, low, high) in expected.items():
            with self.subTest(key=key):
                f = fields[key]
                self.assertEqual((f['current'], f['bounds']['minimum'], f['bounds']['maximum'], f['editable']),
                                 (current, low, high, True))
                unit = key.rsplit('_', 1)[1] if not key.endswith('temp_c') else 'temp_c'
                noun = {'temp_c': 'temperature', 'rpm': 'speed', 'pct': 'level'}[unit]
                self.assertEqual((f['units'], f['stored_units'], f['ordering_group'], f['bounds']['encoding_maximum'],
                                  f['value_semantics'], f['experimental'], bool(f.get('opt_in'))),
                                 ({'temp_c': 'C', 'rpm': 'RPM', 'pct': '%'}[unit],
                                  {'temp_c': '1/32 C', 'rpm': 'RPM', 'pct': '%'}[unit], f'fan-{noun}',
                                  {'temp_c': 110, 'rpm': 32767, 'pct': 100}[unit], f'stored-fan-curve-{noun}', True,
                                  unit == 'pct'))
                extra = key.startswith('fan_extra_')
                self.assertEqual((f.get('fan_channel'), f['fan_rows'], f['fan_policy']),
                                 (None, [0, 1], 3 + int(key[10])) if extra else (int(key[4]) - 1, [int(key[4]) - 1],
                                                                                 int(key[4]) - 1))
        self.assertFalse(any(key.startswith(('fan_3_curve', 'fan_extra_3')) for key in fields))
        # Each point writes only its own bytes, in 1/32 C for temperatures, and reverts byte for byte.
        own, extra = t['rows'][0]['policy_offset'], t['extra_curves'][1]['policy_offset']
        for key, value, at, fmt, stored in (('fan_1_curve_3_temp_c', '60.5', own + 26, '<H', 1936),
                                            ('fan_1_curve_3_temp_c', 110, own + 26, '<H', 3520),
                                            ('fan_extra_2_curve_1_rpm', 1100, extra + 20, '<H', 1100),
                                            ('fan_1_curve_2_pct', 60, own + 15, '<B', 60)):
            with self.subTest(key=key, value=value):
                result = edit(image, {key: value})
                changed_bytes_within(self, image, result, [at], width=struct.calcsize(fmt))
                self.assertEqual(struct.unpack_from(fmt, result.blob, at)[0], stored)
                self.assertEqual(result.manifest['edits'][0]['stored_units'], fields[key]['stored_units'])
                self.assertEqual(edit(result.image, {key: fields[key]['current']}).blob, image.blob)
        for changes, code in (({'fan_1_curve_3_temp_c': '60.01'}, 'UNREPRESENTABLE_VALUE'),
                              ({'fan_1_curve_3_temp_c': '110.03125'}, 'OUT_OF_BOUNDS'),
                              # Temperatures rise strictly: an equal neighbor is refused, alone or jointly.
                              ({'fan_1_curve_2_temp_c': 50}, 'OUT_OF_BOUNDS'),
                              ({'fan_1_curve_1_temp_c': 52, 'fan_1_curve_2_temp_c': 52}, 'OUT_OF_BOUNDS'),
                              ({'fan_1_curve_1_rpm': 1000}, 'OUT_OF_BOUNDS'), ({'fan_1_curve_3_pct': 101}, 'OUT_OF_BOUNDS'),
                              # A joint request may not leave an unrequested neighbor behind.
                              ({'fan_1_curve_2_rpm': 3600, 'fan_1_max_rpm': 4000}, 'OUT_OF_BOUNDS'),
                              ({'fan_1_curve_3_temp_c': 54, 'fan_1_curve_1_temp_c': 40}, 'OUT_OF_BOUNDS')):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual(exc.exception.code, code)
        self.assertEqual(exc.exception.details['field'], 'fan_1_curve_3_temp_c')
        # Speeds and levels may repeat; a joint edit moves two points together.
        flat = edit(image, {'fan_1_curve_1_rpm': 2200, 'fan_1_curve_2_temp_c': 59, 'fan_1_curve_3_temp_c': '59.03125'})
        self.assertEqual(descriptors(flat.image)['fan_1_curve_2_rpm']['bounds']['minimum'], 2200)

    def test_lowering_a_maximum_takes_the_curve_points_above_it(self):
        from nvidia_vbios.editor.registry import registry
        image = from_bytes(synthetic_blackwell(fans=True))
        t = self.table(image.blob)
        bindings = {b.descriptor['key']: b for b in registry.bindings(image, backend(image))[0]}
        top = ['fan_1_curve_3_rpm', 'fan_extra_1_curve_3_rpm', 'fan_extra_2_curve_3_rpm']
        # Alone, or with the channel's own curve only, the maximum stops at the extra curves (3500 RPM).
        for changes in ({'fan_1_max_rpm': 3000}, {'fan_1_max_rpm': 3000, 'fan_1_curve_3_rpm': 3000}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual((exc.exception.code, exc.exception.details['field'],
                              exc.exception.details['bounds']['minimum']), ('OUT_OF_BOUNDS', 'fan_1_max_rpm', 3500))
        lowered = edit(image, dict({'fan_1_max_rpm': 3000}, **{key: 3000 for key in top}))
        changed_bytes_within(self, image, lowered, [bindings[k].offsets[0] for k in ['fan_1_max_rpm'] + top], width=2)
        after = descriptors(lowered.image)
        self.assertEqual([after[k]['current'] for k in ['fan_1_max_rpm', 'fan_2_max_rpm'] + top], [3000, 3500] + [3000] * 3)
        self.assertEqual(after['fan_1_max_rpm']['bounds']['minimum'], 3000)
        # Extra curves serve both channels: their points now stop at channel 1's maximum.
        self.assertEqual(after['fan_extra_1_curve_3_rpm']['bounds']['maximum'], 3000)
        self.assertEqual(edit(lowered.image, dict({'fan_1_max_rpm': 3500}, **{key: 3500 for key in top})).blob, image.blob)
        # The enabled speed-table value (2300 RPM) stops the maximum, with or without the curves.
        with self.assertRaises(VbiosError) as exc:
            edit(image, dict({'fan_1_max_rpm': 2250}, **{key: 2250 for key in top}))
        self.assertEqual((exc.exception.code, exc.exception.details['bounds']['minimum']), ('OUT_OF_BOUNDS', 2300))
        # Below a lower speed value, every point above the new maximum moves with it.
        blob = bytearray(image.blob)
        struct.pack_into('<H', blob, t['rows'][0]['speed_offset'] + 2, 1500)
        slow = from_bytes(repair_fixture(blob))
        middle = ['fan_1_curve_2_rpm', 'fan_extra_1_curve_2_rpm', 'fan_extra_2_curve_2_rpm']
        capped = edit(slow, dict({'fan_1_max_rpm': 2000}, **{key: 2000 for key in top + middle}))
        self.assertEqual(backend(capped.image).fan_coolers()['rows'][0]['rpm_maximum'], 2000)
        # A point flush with its neighbor and its limit has no room alone, but the same keys undo the cap in one edit.
        flush = descriptors(capped.image)['fan_1_curve_3_rpm']
        self.assertEqual((flush['editable'], flush['bounds']['minimum'], flush['bounds']['maximum']), (True, 2000, 2000))
        with self.assertRaises(VbiosError) as exc:
            edit(capped.image, {'fan_1_curve_3_rpm': 2100})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        self.assertEqual(edit(capped.image, dict({'fan_1_max_rpm': 3500}, **{key: 3500 for key in top},
                                                 **{key: 2200 for key in middle})).blob, slow.blob)
        with self.assertRaises(VbiosError) as exc:
            edit(slow, dict({'fan_1_max_rpm': 2000}, **{key: 2000 for key in top}))
        self.assertEqual(exc.exception.details['field'], 'fan_1_curve_3_rpm')
        # A level maximum of 100 under curves that reach 100 % lowers the same way, and reverts in one edit.
        levels = {'fan_1_max_pct': 90, 'fan_1_curve_3_pct': 90, 'fan_extra_1_curve_3_pct': 90,
                  'fan_extra_2_curve_3_pct': 90}
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_1_max_pct': 90})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        quieter = edit(image, levels)
        changed_bytes_within(self, image, quieter, [bindings[k].offsets[0] for k in levels], width=1)
        self.assertEqual(edit(quieter.image, {key: 100 for key in levels}).blob, image.blob)

    def test_channel_count_and_curves_are_separate_edits(self):
        image = from_bytes(synthetic_blackwell(fans=True))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_channels': 3, 'fan_1_curve_1_temp_c': 51, 'fan_extra_1_curve_2_rpm': 2100})
        self.assertEqual((exc.exception.code, exc.exception.details['fields']),
                         ('SEPARATE_EDIT_REQUIRED', ['fan_channels', 'fan_1_curve_1_temp_c', 'fan_extra_1_curve_2_rpm']))
        # Lowering the count leaves the extra curves to the remaining channel.
        lowered = descriptors(edit(image, {'fan_channels': 1}).image)
        self.assertEqual(lowered['fan_extra_1_curve_1_rpm']['fan_rows'], [0])
        self.assertFalse(any(key.startswith('fan_2_') for key in lowered))

    def test_curve_points_outside_the_reviewed_shape_are_read_only(self):
        blob = synthetic_blackwell(fans=True)
        t = self.table(blob)
        own, extra = t['rows'][0]['policy_offset'], t['extra_curves'][0]['policy_offset']
        pack = lambda fmt, at, *values: (lambda b: struct.pack_into(fmt, b, at, *values))
        shape = 'fan row or policy curves hold values outside the reviewed shape'
        cases = {'equal temperatures': (pack('<H', own + 22, 50 * 32),
                                        {'fan_1_curve_1_temp_c': shape, 'fan_1_curve_3_pct': shape,
                                         'fan_1_max_rpm': shape, 'fan_2_curve_1_temp_c': None}),
                 'temperature above 110 C': (pack('<H', own + 26, 111 * 32), {'fan_1_curve_2_rpm': shape}),
                 # An extra curve has to fit every active channel: only its top point leaves channel 2's maximum.
                 'extra curve above a channel maximum': (pack('<H', t['rows'][1]['offset'] + 16, 3400),
                                                         {'fan_extra_1_curve_3_rpm': shape, 'fan_extra_1_curve_2_rpm': None,
                                                          'fan_1_curve_3_rpm': None, 'fan_2_max_rpm': shape}),
                 # Speeds may repeat: a point flush with its neighbor and limit stays editable (lo == hi).
                 'equal speeds at the minimum': (pack('<H', own + 24, 1050),
                                                 {'fan_1_curve_1_rpm': None, 'fan_1_curve_2_rpm': None}),
                 'extra levels not ascending': (pack('<B', extra + 15, 10), {'fan_extra_1_curve_1_temp_c': shape,
                                                                            'fan_extra_2_curve_1_temp_c': None}),
                 'speed minimum above maximum': (pack('<HH', t['rows'][0]['offset'] + 14, 3500, 1050),
                                                 {'fan_1_curve_2_rpm': shape, 'fan_1_curve_2_temp_c': shape})}
        for name, (change, reasons) in cases.items():
            with self.subTest(case=name):
                b = bytearray(blob)
                change(b)
                image = from_bytes(repair_fixture(b))
                fields = descriptors(image)
                for key, reason in reasons.items():
                    f = fields[key]
                    self.assertEqual(f['editable'], reason is None, key)
                    self.assertTrue(f['reason'].startswith('experimental:') if reason is None else f['reason'] == reason,
                                    key)
                    self.assertTrue(all(isinstance(f['bounds'][k], (int, float)) for k in ('minimum', 'maximum')))
                    if reason:
                        with self.assertRaises(VbiosError) as exc:
                            edit(image, {key: f['current']})
                        self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')
        # A stored top point above the containment does not widen its neighbor's range (RTX 4080 Super).
        b = bytearray(blob)
        struct.pack_into('<H', b, t['rows'][1]['offset'] + 16, 3400)
        image = from_bytes(repair_fixture(b))
        middle = descriptors(image)['fan_extra_1_curve_2_rpm']
        self.assertEqual((middle['editable'], middle['bounds']['minimum'], middle['bounds']['maximum']), (True, 1050, 3400))
        for changes in ({'fan_extra_1_curve_2_rpm': 3500},
                        {'fan_extra_1_curve_2_rpm': 3450, 'fan_extra_2_curve_2_rpm': 3500}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual((exc.exception.code, exc.exception.details['field']),
                             ('OUT_OF_BOUNDS', 'fan_extra_1_curve_2_rpm'))
        # A row maximum above the 32767 RPM ceiling does not lift the top point past it.
        b = bytearray(blob)
        struct.pack_into('<H', b, t['rows'][0]['offset'] + 16, 40000)
        image = from_bytes(repair_fixture(b))
        point = descriptors(image)['fan_1_curve_3_rpm']
        self.assertEqual((point['editable'], point['bounds']['minimum'], point['bounds']['maximum']), (True, 2200, 32767))
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'fan_1_curve_3_rpm': 33000})
        self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')


def top_profile_fixture(*, stage1_type=1, stage2_target=7, top_code_power=600000, mutate=None):
    """XOC-like profile table: no profile matches the base, stage 1 code 3 -> 600 W -> profile 7.

    Base rows 2/7/8 are 30/100/100 W (rated = maximum, as on the XOC) and row 9 is
    80 A. Profile 0 holds 60 W
    maxima, 60/50 W defaults and 40 A; profile 7 holds 90 W maxima, 90/80 W
    defaults and 60 A. mutate(blob, parsed) may change it before rehashing.
    """
    blob = bytearray(input_fixture())
    parsed = backend(from_bytes(bytes(blob)))
    for i in (2, 7, 8):
        struct.pack_into('<I', blob, parsed.power_rows()[i]['offset'] + 17, 100000)
    low = parsed.power_profiles()[0]
    row = low['offset']
    blob[row + 7 * 0x49:row + 8 * 0x49] = blob[row:row + 0x49]
    for entry in low['entries']:
        for profile, values in ((0, {'maximum': 60000, 2: 60000, 7: 60000, 8: 50000, 9: 40000}),
                                (7, {'maximum': 90000, 2: 90000, 7: 90000, 8: 80000, 9: 60000})):
            if entry['field'] == 'maximum':
                value = values[9] if entry['policy'] == 9 else values['maximum']
            else:
                value = values[entry['policy']]
            struct.pack_into('<I', blob, entry['value_offset'] + profile * 0x49, value)
    at = parsed.pointer('P', 0xF4)
    blob[at + 0x0A:at + 0x0F] = bytes((stage1_type, 8, 0, 0, 0))
    for j, (power, code) in enumerate(((0, 0), (0, 1), (450000, 2), (top_code_power, 3))):
        struct.pack_into('<BBIB', blob, at + 0x0F + 7 * j, 1, 0xFF, power, code)
    blob[at + 0x47:at + 0x4C] = bytes((2, 0, 0, 0, 0))
    for j, (target, power) in enumerate(((0, 450000), (stage2_target, 600000))):
        struct.pack_into('<BBIB', blob, at + 0x4C + 7 * j, 1, target, power, j)
    if mutate is not None:
        mutate(blob, backend(from_bytes(bytes(blob))))
    return from_bytes(repair_fixture(blob))


def set_profile_entry(index, policy, name, value):
    def mutate(blob, parsed):
        struct.pack_into('<I', blob, profile_entry(parsed, index, policy, name)['value_offset'], value)
    return mutate


class TopLevelProfileTests(unittest.TestCase):
    """ASUS XOC shape: fields bind to the profile the selection chain reaches at its top code."""

    def test_fields_bind_to_the_top_level_profile(self):
        image = top_profile_fixture()
        parser = backend(image)
        self.assertEqual(parser.matching_power_profiles(), [])
        self.assertEqual((parser.top_power_profile()['index'], parser.top_power_profile()['selection_power_raw']),
                         (7, 600000))
        fields = descriptors(image)
        expected = {'power_max_w': (90, 90, 100), 'power_default_w': (80, 50, 90), 'power_min_w': (30, 1, 80),
                    'board_fixed_rated_w': (90, 60, 90), 'input_current_max_ma': (60000, 60000, 80000),
                    'input_current_rated_ma': (60000, 40000, 60000)}
        for key, (current, low, high) in expected.items():
            with self.subTest(key=key):
                f = fields[key]
                self.assertEqual((f['current'], f['bounds']['minimum'], f['bounds']['maximum']), (current, low, high))
                if key != 'power_min_w':
                    self.assertTrue(f['experimental'])
                    self.assertEqual(f['bound_profile'], 7)
                    self.assertIn('override profile 7, reached at the top level of the ROM selection table',
                                  f['reason'])
                    self.assertIn('is preserved', f['reason'])
        self.assertEqual(fields['power_max_w']['base_values'], {'power_max_w': 100, 'power_default_w': 100})
        self.assertIn('the base table holds 80000 mA', fields['input_current_max_ma']['reason'])
        from nvidia_vbios.editor.registry import registry
        top = {e['value_offset'] for e in parser.top_power_profile()['entries']}
        offsets = {b.descriptor['key']: set(b.offsets) for b in registry.bindings(image, parser)[0]}
        for key in expected:
            with self.subTest(offsets=key):
                if key == 'power_min_w':
                    self.assertEqual(offsets[key], {parser.power_rows()[8]['offset'] + 13})
                else:
                    self.assertTrue(offsets[key] and offsets[key] <= top)

    def test_edits_write_only_the_bound_profile_and_revert(self):
        image = top_profile_fixture()
        parser = backend(image)
        top = parser.top_power_profile()
        changes = {'power_max_w': 100, 'board_fixed_rated_w': 95, 'power_default_w': 85,
                   'input_current_max_ma': 75000, 'input_current_rated_ma': 70000}
        result = edit(image, changes)
        changed_bytes_within(self, image, result, [e['value_offset'] for e in top['entries']])
        target = backend(result.image)
        self.assertEqual(target.power_rows(), parser.power_rows())
        self.assertEqual(target.top_power_profile()['values'],
                         {(2, 'maximum'): 100000, (7, 'maximum'): 100000, (8, 'maximum'): 100000,
                          (2, 'default'): 95000, (7, 'default'): 95000, (8, 'default'): 85000,
                          (9, 'maximum'): 75000, (9, 'default'): 70000})
        back = edit(result.image, {'power_max_w': 90, 'board_fixed_rated_w': 90, 'power_default_w': 80,
                                   'input_current_max_ma': 60000, 'input_current_rated_ma': 60000})
        self.assertEqual(back.blob, image.blob)
        self.assertEqual(edit(image, {'power_min_w': 40}).manifest['edits'][0]['offset'],
                         parser.power_rows()[8]['offset'] + 13)

    def test_values_above_the_base_or_unbinding_the_profile_are_refused(self):
        image = top_profile_fixture()
        for changes in ({'power_max_w': 101}, {'input_current_max_ma': 80001}, {'power_default_w': 49}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')
        refused = {
            'override profile 7 would no longer be the profile selected at the top level: override profile 0 '
            'policy 2 maximum exceeds the same entry of override profile 7':
                {'power_max_w': 55, 'board_fixed_rated_w': 55, 'power_default_w': 55},
            'override profile 7 would no longer be the profile selected at the top level: override profile 0 '
            'policy 9 maximum exceeds the same entry of override profile 7':
                {'input_current_max_ma': 30000, 'input_current_rated_ma': 30000},
            'override profile 7 would no longer be the profile selected at the top level: it would equal the base '
            'table and become a matching profile; keep at least one of its values below the base table':
                {'power_max_w': 100, 'board_fixed_rated_w': 100, 'power_default_w': 100,
                 'input_current_max_ma': 80000, 'input_current_rated_ma': 80000}}
        for message, changes in refused.items():
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual((exc.exception.code, str(exc.exception)), ('OUT_OF_BOUNDS', message))

    def test_guard_errors_name_the_field_and_metadata_names_the_binding(self):
        image = top_profile_fixture()
        fields = descriptors(image)
        self.assertIn('(code 3 -> 600 W; probably the highest 12V-2x6 sense level, inferred)',
                      fields['power_max_w']['reason'])
        for key in ('power_max_w', 'power_default_w', 'board_fixed_rated_w', 'input_current_max_ma'):
            self.assertTrue(fields[key]['version_metadata']['format_variant'].startswith(
                'GB20x override profile bound through selection stage 1'), key)
        self.assertNotIn('read-only-nvml-correlation', [e['kind'] for e in fields['power_default_w']['evidence']])
        self.assertEqual(fields['power_min_w']['version_metadata']['format_variant'],
                         'GB20x power v40 rows 2/7/8 and complete matching profiles')
        cases = (({'power_default_w': 95, 'power_max_w': 92}, 'power_default_w',
                  'power_default_w violates the minimum/default/maximum ordering of the joint result'),
                 ({'power_max_w': 55, 'board_fixed_rated_w': 55, 'power_default_w': 55}, 'power_max_w',
                  'override profile 7 would no longer be the profile selected at the top level: override profile 0 '
                  'policy 2 maximum exceeds the same entry of override profile 7'))
        for changes, key, message in cases:
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as exc:
                edit(image, changes)
            self.assertEqual((exc.exception.code, str(exc.exception), exc.exception.details['field']),
                             ('OUT_OF_BOUNDS', message, key))
        # A broken table header is reported as on images without a bound profile.
        at = backend(image).pointer('P', 0xF4)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'probe': 0x11}, field_registry=custom_registry(
                'probe', [at], encoding='<B', scale=1, bounds={'minimum': 0, 'maximum': 255}))
        self.assertEqual((exc.exception.code, str(exc.exception)),
                         ('PRESERVED_FIELD_CHANGED', 'edit invalidated recognized power profiles'))

    def test_rated_fields_are_capped_by_the_base_rated_values(self):
        def lower_base_rated(blob, parsed):
            rows = parsed.power_rows()
            for i, value in ((2, 95000), (7, 95000), (8, 85000), (9, 70000)):
                struct.pack_into('<I', blob, rows[i]['offset'] + 17, value)
        image = top_profile_fixture(mutate=lower_base_rated)
        self.assertEqual(backend(image).top_power_profile()['index'], 7)
        fields = descriptors(image)
        for key, high in (('power_default_w', 85), ('board_fixed_rated_w', 90), ('input_current_rated_ma', 60000)):
            self.assertEqual(fields[key]['bounds']['maximum'], high, key)
        self.assertEqual(edit(image, {'power_max_w': 100, 'board_fixed_rated_w': 95}).manifest['edits'][-1]['after'],
                         95000)
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'power_max_w': 100, 'board_fixed_rated_w': 96})
        self.assertEqual((exc.exception.details['field'], str(exc.exception)), ('board_fixed_rated_w',
                         'override profile 7 would no longer be the profile selected at the top level: '
                         'override profile 7 policy 2 default exceeds the base table'))

    def test_binding_needs_the_whole_selection_chain(self):
        variants = {
            'stages off': dict(stage1_type=0),
            'stage 2 points at profile 0': dict(stage2_target=0),
            'stage 2 points at a disabled profile': dict(stage2_target=5),
            'stage 1 top code gives 450 W': dict(top_code_power=450000),
            'stage 1 top code gives 0 W': dict(top_code_power=0),
            'another profile exceeds it': dict(mutate=set_profile_entry(0, 9, 'default', 70000)),
            'above the base': dict(mutate=set_profile_entry(7, 9, 'maximum', 90000)),
            'board maxima disagree': dict(mutate=set_profile_entry(7, 2, 'maximum', 95000)),
            'default above maximum': dict(mutate=set_profile_entry(7, 8, 'default', 95000)),
        }
        for name, options in variants.items():
            with self.subTest(name):
                image = top_profile_fixture(**options)
                self.assertIsNone(backend(image).top_power_profile())
                report = inspect_image(image)
                keys = {f['key'] for f in report['fields']}
                self.assertFalse(keys & {'power_max_w', 'power_default_w', 'input_current_max_ma'})
                self.assertIn('no complete override profile matches the base policy',
                              [d.get('message') for d in report['diagnostics']])
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'power_max_w': 95})
                self.assertEqual(exc.exception.code, 'UNKNOWN_FIELD')


if __name__ == '__main__':
    unittest.main()
