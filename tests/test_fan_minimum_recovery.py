"""Recover an otherwise recognized RPM minimum above its enabled speed-table value."""
import struct
import unittest
from test_ada_fields import patched
from test_extended_fields import descriptors
from test_rom_formats import synthetic_rom
from nvidia_vbios.editor import edit
from nvidia_vbios.rom import from_bytes, VbiosError
from nvidia_vbios.rom.image import backend
from nvidia_vbios.gui.i18n import Messages


def conflicting_image():
    blob = synthetic_rom(copies=2, fans=2)
    for row in backend(from_bytes(blob)).fan_coolers()['rows']:
        blob = patched(blob, row['offset'] + 14, struct.pack('<HH', 3000, 6000))
        blob = patched(blob, row['policy_offset'] + 20, struct.pack('<H', 4500))
        blob = patched(blob, row['policy_offset'] + 24, struct.pack('<H', 5500))
        blob = patched(blob, row['policy_offset'] + 28, struct.pack('<H', 6000))
    return from_bytes(blob)


class FanMinimumRecoveryTests(unittest.TestCase):
    def test_conflicting_minimum_allows_corrective_decrease(self):
        image = conflicting_image()
        fields = descriptors(image)
        self.assertTrue(fields['fan_1_min_rpm']['editable'])
        self.assertEqual(fields['fan_1_min_rpm']['bounds']['maximum'], 2295)
        for value in (1500, 2000, 2295):
            with self.subTest(value=value):
                result = edit(image, {'fan_1_min_rpm': value})
                self.assertEqual(descriptors(result.image)['fan_1_min_rpm']['current'], value)
                self.assertEqual(descriptors(result.image)['fan_2_min_rpm']['current'], 3000)
                self.assertTrue(backend(result.image).integrity()['valid'])
        self.assertTrue(fields['fan_1_min_rpm']['experimental'])

    def test_joint_edit_cannot_bypass_corrective_range(self):
        image = conflicting_image()
        for changes in ({'fan_1_min_rpm': 2500},
                        {'fan_1_min_rpm': 2500, 'fan_2_min_rpm': 2000}):
            with self.subTest(changes=changes):
                with self.assertRaises(VbiosError) as error:
                    edit(image, changes)
                self.assertEqual(error.exception.code, 'OUT_OF_BOUNDS')
        result = edit(image, {'fan_1_min_rpm': 2000, 'fan_1_min_pct': 15})
        fields = descriptors(result.image)
        self.assertEqual(fields['fan_1_min_pct']['current'], 15)
        self.assertEqual(fields['fan_1_min_rpm']['current'], 2000)

    def test_untouched_channel_stays_byte_identical_in_both_banks(self):
        image = conflicting_image()
        parser = backend(image)
        row = parser.fan_coolers()['rows'][1]
        result = edit(image, {'fan_1_min_rpm': 1500, 'fan_1_min_pct': 15})
        for chain in parser.chains:
            bias = chain[0]['start'] - parser.chains[0][0]['start']
            for key, size in (('offset', 26), ('policy_offset', 51), ('mapping_offset', 5),
                              ('control_offset', 13), ('speed_offset', 6)):
                at = row[key] + bias
                with self.subTest(bank=bias, table=key):
                    self.assertEqual(result.blob[at:at + size], image.blob[at:at + size])

    def test_recovery_requires_only_the_speed_table_conflict(self):
        image = conflicting_image()
        row = backend(image).fan_coolers()['rows'][0]
        for offset, data in ((row['policy_offset'] + 20, struct.pack('<H', 2500)),
                             (row['offset'] + 16, struct.pack('<H', 5000))):
            with self.subTest(offset=offset):
                broken = from_bytes(patched(image.blob, offset, data))
                self.assertFalse(descriptors(broken)['fan_1_min_rpm']['editable'])

    def test_malformed_curve_stays_read_only(self):
        image = conflicting_image()
        row = backend(image).fan_coolers()['rows'][0]
        broken = from_bytes(patched(image.blob, row['policy_offset'] + 24, struct.pack('<H', 4000)))
        self.assertFalse(descriptors(broken)['fan_1_min_rpm']['editable'])

    def test_valid_minimum_still_round_trips(self):
        image = from_bytes(synthetic_rom(copies=2, fans=2))
        result = edit(image, {'fan_1_min_rpm': 900})
        self.assertEqual(edit(result.image, {'fan_1_min_rpm': 1000}).blob, image.blob)

    def test_advice_is_localized(self):
        for language in ('en', 'es'):
            messages = Messages(language)
            self.assertTrue(messages('fan.minimum_level_advice'))
            self.assertIn('2295', messages('fan.minimum_recovery', current=3000, maximum=2295))
