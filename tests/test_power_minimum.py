"""Offline floor edits: reviewed offsets, preservation and fail-closed evidence."""
from decimal import Decimal
import json
from pathlib import Path
import struct
import tempfile
import unittest

from test_rom_formats import synthetic_blackwell, synthetic_rom
from test_extended_fields import repair_fixture
from nvidia_vbios.editor import Binding, FieldRegistry, edit, plan
from nvidia_vbios.editor.registry import power
from nvidia_vbios.rom import VbiosError, from_bytes, inspect_image
from nvidia_vbios.rom.image import backend


def fields(image):
    return {f['key']: f for f in inspect_image(image)['fields']}


def table_repair(blob):
    parser = backend(from_bytes(blob))
    for start, end in parser.image_regions:
        blob[end - 1] = (blob[end - 1] - sum(blob[start:end])) & 255
    return bytes(blob)


class PowerMinimumTests(unittest.TestCase):
    def test_floor_descriptors_units_bounds_and_runtime_unknown(self):
        for blob, indices in ((synthetic_rom(), [2]), (synthetic_rom(family='ampere'), [2]),
                              (synthetic_blackwell(), [8])):
            with self.subTest(indices=indices, size=len(blob)):
                floor = fields(from_bytes(blob))['power_min_w']
                self.assertTrue(floor['editable'])
                self.assertEqual(floor['current'], 30)
                self.assertEqual(floor['bounds']['minimum'], 1)
                self.assertEqual(floor['bounds']['maximum'], 70)
                self.assertEqual(floor['factory_default'], 70)
                self.assertEqual(floor['policy_indices'], indices)
                self.assertEqual(floor['unit_metadata']['stored_symbol'], 'mW')
                self.assertEqual(floor['unit_metadata']['storage_encoding'], '<I')
                self.assertEqual(floor['capability']['runtime']['applied'], 'unknown')
                self.assertIn('base TGP' if indices == [8] else 'header-indexed', floor['format_scope'])

    def test_exact_minimum_edits_roundtrip_and_independent_byte_allowlist(self):
        for blob in (synthetic_rom(copies=2), synthetic_rom(family='ampere', copies=2),
                     synthetic_blackwell(shared_objects=True)):
            image = from_bytes(blob)
            source = backend(image)
            canonical = next(b for b in power(image, source) if b.descriptor['key'] == 'power_min_w')
            result = edit(image, {'power_min_w': '1.001'})
            target = backend(result.image)
            with self.subTest(format=inspect_image(image)['format']):
                self.assertEqual(image.blob, blob)
                self.assertEqual(fields(result.image)['power_min_w']['current'], 1.001)
                self.assertTrue(result.manifest['integrity']['valid'])
                self.assertEqual(source.power_profiles(), target.power_profiles())
                indices = canonical.descriptor['policy_indices']
                for index, (before, after) in enumerate(zip(source.power_rows(), target.power_rows())):
                    expected = dict(before, minimum_raw=1001) if index in indices else before
                    self.assertEqual(expected, after)
                allowed = {at for offset in canonical.offsets for at in range(offset, offset + 4)}
                for obj in source.objects:
                    if any(obj['data'] <= offset < obj['data'] + obj['size'] for offset in canonical.offsets):
                        allowed.update(range(obj['hash_offset'], obj['hash_offset'] + 48))
                if source.directory:
                    at = source.directory['digest_offset']
                    allowed.update(range(at, at + 48))
                allowed.update(end - 1 for start, end in source.image_regions)
                changed = {at for at, (before, after) in enumerate(zip(blob, result.blob)) if before != after}
                self.assertTrue(changed <= allowed)
                self.assertEqual(edit(result.image, {'power_min_w': 30}).blob, blob)
                self.assertEqual(plan(image, {'power_min_w': 1}).blob, edit(image, {'power_min_w': 1}).blob)
                self.assertEqual(edit(image, {'power_min_w': 30}).blob, blob)
                json.dumps(result.manifest, allow_nan=False)

    def test_minimum_and_maximum_transaction_preserves_order_and_defaults(self):
        for blob in (synthetic_rom(), synthetic_rom(family='ampere'), synthetic_blackwell()):
            image = from_bytes(blob)
            result = edit(image, {'power_min_w': 70, 'power_max_w': 150})
            after = fields(result.image)
            self.assertEqual(after['power_min_w']['current'], 70)
            self.assertEqual(after['power_max_w']['current'], 150)
            self.assertTrue(result.manifest['preservation']['factory_defaults'])
            for row in backend(result.image).power_rows():
                self.assertLessEqual(row['minimum_raw'], row['default_raw'])
                self.assertLessEqual(row['default_raw'], row['maximum_raw'])

    def test_minimum_number_validation(self):
        for value, code in ((True, 'INVALID_VALUE'), ('nan', 'INVALID_VALUE'), ('inf', 'INVALID_VALUE'),
                            (0.999, 'OUT_OF_BOUNDS'), (70.001, 'OUT_OF_BOUNDS'),
                            ('1.0001', 'UNREPRESENTABLE_VALUE')):
            with self.subTest(value=value), self.assertRaises(VbiosError) as exc:
                edit(from_bytes(synthetic_blackwell()), {'power_min_w': value})
            self.assertEqual(exc.exception.code, code)

    def test_header_index_is_used_and_zero_factory_minimum_is_inspectable(self):
        blob = bytearray(synthetic_rom(copies=2))
        source = backend(from_bytes(blob))
        table = source.pointer('P', 0x2C)
        for offset in source.copy_offsets(table + 10, 1):
            blob[offset] = 1
        minimum = source.power_rows()[1]['maximum_offset'] - 8
        for offset in source.copy_offsets(minimum, 4):
            struct.pack_into('<I', blob, offset, 0)
        image = from_bytes(table_repair(blob))
        self.assertEqual(fields(image)['power_min_w']['current'], 0)
        result = edit(image, {'power_min_w': 1})
        before, after = backend(image).power_rows(), backend(result.image).power_rows()
        self.assertEqual(after[1], dict(before[1], minimum_raw=1000))
        self.assertEqual(after[2], before[2])

    def test_blackwell_disagreement_invalid_order_and_profiles_fail_closed(self):
        for fault in ('maxima', 'order', 'mismatch', 'partial', 'duplicate', 'unknown-selector', 'unknown-profile'):
            blob = bytearray(synthetic_blackwell())
            source = backend(from_bytes(blob))
            entry = source.power_profiles()[0]['offset'] + 1
            if fault == 'maxima':
                struct.pack_into('<I', blob, source.power_rows()[2]['offset'] + 21, 90000)
            elif fault == 'order':
                struct.pack_into('<I', blob, source.power_rows()[8]['offset'] + 13, 80000)
            elif fault == 'mismatch':
                struct.pack_into('<I', blob, entry + 5, 90000)
            elif fault == 'partial':
                blob[entry] = 0
            elif fault == 'duplicate':
                blob[entry + 9 + 1:entry + 9 + 5] = blob[entry + 1:entry + 5]
            elif fault == 'unknown-selector':
                struct.pack_into('<I', blob, entry + 1, 2 | 2 << 8)
            else:
                # Preserve the complete matching profile and add another with an unknown selector.
                unknown = source.power_profiles()[0]['offset'] + 0x49
                blob[unknown:unknown + 0x49] = blob[unknown - 0x49:unknown]
                struct.pack_into('<I', blob, unknown + 2, 2 | 2 << 8)
            image = from_bytes(repair_fixture(blob))
            with self.subTest(fault=fault):
                self.assertNotIn('power_min_w', fields(image))
                self.assertTrue(inspect_image(image)['diagnostics'])
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {'power_min_w': 1})
                self.assertEqual(exc.exception.code, 'UNKNOWN_FIELD')

    def test_distinct_blackwell_policy_minima_and_defaults_are_preserved(self):
        blob = bytearray(synthetic_blackwell())
        source = backend(from_bytes(blob))
        for index in (2, 7):
            struct.pack_into('<II', blob, source.power_rows()[index]['offset'] + 13, 1, 80000)
        for entry in source.power_profiles()[0]['entries']:
            if entry['policy'] in (2, 7) and entry['field'] == 'default':
                struct.pack_into('<I', blob, entry['value_offset'], 80000)
        image = from_bytes(repair_fixture(blob))
        source = backend(image)
        self.assertEqual(fields(image)['power_min_w']['bounds']['maximum'], 70)
        self.assertEqual(fields(image)['power_max_w']['bounds']['minimum'], 80)
        self.assertEqual(edit(image, {'power_min_w': 30}).blob, image.blob)
        result = edit(image, {'power_min_w': 1})
        target = backend(result.image)
        for index in (2, 7):
            self.assertEqual(source.power_rows()[index], target.power_rows()[index])
        self.assertEqual(target.power_rows()[8], dict(source.power_rows()[8], minimum_raw=1000))
        self.assertEqual(source.power_profiles(), target.power_profiles())
        self.assertEqual(edit(result.image, {'power_min_w': 30}).blob, image.blob)

    def test_empty_profiles_are_supported_but_nonempty_ada_profiles_are_not(self):
        blob = bytearray(synthetic_blackwell())
        source = backend(from_bytes(blob))
        at = source.power_profiles()[0]['offset']
        blob[at:at + 0x49] = bytes(0x49)
        result = edit(from_bytes(repair_fixture(blob)), {'power_min_w': 1})
        self.assertEqual(backend(result.image).power_profiles(), [])
        blob = bytearray(synthetic_rom())
        source = backend(from_bytes(blob))
        blob[source.pointer('P', 0xF4) + 0xFE] = 1
        image = from_bytes(table_repair(blob))
        self.assertNotIn('power_min_w', fields(image))
        with self.assertRaises(VbiosError):
            edit(image, {'power_min_w': 1})

    def test_custom_registry_and_aliases_cannot_bypass_preserved_power_bytes(self):
        for family in ('ada', 'blackwell'):
            image = from_bytes(synthetic_blackwell() if family == 'blackwell' else synthetic_rom(copies=2))
            for fault in ('minimum-alias', 'default-alias', 'minimum-spoof', 'relaxed-bounds', 'other-row', 'opaque', 'profile-default'):
                if family == 'ada' and fault == 'profile-default':
                    continue
                custom = FieldRegistry()
                @custom.register
                def forbidden(image, parser):
                    original = next(b for b in power(image, parser) if b.descriptor['key'] == 'power_min_w')
                    rows = parser.power_rows()
                    key, offsets = 'alias', original.offsets
                    if fault == 'default-alias':
                        offsets = tuple(at + 4 for at in original.offsets)
                    elif fault == 'minimum-spoof':
                        key, offsets = 'power_min_w', (original.offsets[0] + 4,)
                    elif fault == 'relaxed-bounds':
                        key = 'power_min_w'
                    elif fault in ('other-row', 'opaque'):
                        at = rows[0]['offset'] + (13 if family == 'blackwell' else 2) + (20 if fault == 'opaque' else 0)
                        offsets = (at,) if family == 'blackwell' else tuple(parser.copy_offsets(at, 4))
                    elif fault == 'profile-default':
                        offsets = (next(e['value_offset'] for e in parser.power_profiles()[0]['entries'] if e['field'] == 'default'),)
                    desc = dict(original.descriptor, key=key, current=struct.unpack_from('<I', image.blob, offsets[0])[0] / 1000,
                                bounds={'minimum': 0, 'maximum': 10000})
                    return [Binding(desc, offsets, '<I', Decimal(1000))]
                key = 'power_min_w' if fault in ('minimum-spoof', 'relaxed-bounds') else 'alias'
                with self.subTest(family=family, fault=fault), self.assertRaises(VbiosError) as exc:
                    edit(image, {key: 0.5 if fault == 'relaxed-bounds' else 60 if fault == 'default-alias' else 1}, field_registry=custom)
                self.assertEqual(exc.exception.code,
                    'INVALID_FIELD_EVIDENCE' if fault == 'minimum-spoof' else
                    'OUT_OF_BOUNDS' if fault == 'relaxed-bounds' else
                    'FACTORY_DEFAULT_CHANGED' if fault == 'default-alias' else 'PRESERVED_FIELD_CHANGED')

    def test_cli_and_gui_controller_accept_floor_and_preview_in_both_languages(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from nvidia_vbios import cli
        from nvidia_vbios.gui.controller import Controller
        from nvidia_vbios.gui.presentation import field_label, primary_preview
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.rom'
            source.write_bytes(synthetic_blackwell())
            out = StringIO()
            with redirect_stdout(out):
                code = cli.main(['edit', str(source), '--set', 'power_min_w=1', '--set', 'power_max_w=150', '--dry-run'])
            self.assertEqual(code, 0)
            report = json.loads(out.getvalue())
            self.assertEqual(report['result']['requested']['power_min_w'], '1')
            controller = Controller()
            controller.open(source)
            staged = controller.stage({'power_min_w': '1', 'power_max_w': '150'})
            self.assertEqual({left['key'] for left, _ in primary_preview(staged)}, {'power_min_w', 'power_max_w'})
            floor = fields(staged.proposal.image)['power_min_w']
            self.assertEqual(field_label(floor), 'Board power floor')
            self.assertEqual(field_label(floor, 'es'), 'Piso de potencia de la placa')
            self.assertEqual(source.read_bytes(), controller.document.original.blob)


if __name__ == '__main__':
    unittest.main()
