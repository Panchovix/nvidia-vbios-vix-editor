"""A fan speed minimum stored above the speed-table value can only come down (PR #39)."""
import struct
import unittest
from test_ada_fields import patched
from test_extended_fields import descriptors
from test_rom_formats import synthetic_rom
from nvidia_vbios.editor import edit
from nvidia_vbios.gui.presentation import fan_minimum_notes
from nvidia_vbios.rom import from_bytes, VbiosError
from nvidia_vbios.rom.image import backend


def conflicting_image():
    """Both channels at 3000-6000 RPM over a 2295 RPM speed value, curves 4500/5500/6000 RPM."""
    blob = synthetic_rom(copies=2, fans=2)
    for row in backend(from_bytes(blob)).fan_coolers()['rows']:
        blob = patched(blob, row['offset'] + 14, struct.pack('<HH', 3000, 6000))
        for k, rpm in enumerate((4500, 5500, 6000)):
            blob = patched(blob, row['policy_offset'] + 20 + 4 * k, struct.pack('<H', rpm))
    return from_bytes(blob)


class FanMinimumLowerOnlyTests(unittest.TestCase):
    def test_minimum_comes_down_to_the_speed_value_only(self):
        image = conflicting_image()
        field = descriptors(image)['fan_1_min_rpm']
        self.assertTrue(field['editable'])
        self.assertFalse(field.get('experimental'))
        self.assertEqual((field['bounds']['minimum'], field['bounds']['maximum']), (0, 2295))
        self.assertIn('speed-table value, so it can only be lowered', field['reason'])
        for value in (1500, 2295):
            result = edit(image, {'fan_1_min_rpm': value, 'fan_1_min_pct': 15})
            fields = descriptors(result.image)
            self.assertEqual((fields['fan_1_min_rpm']['current'], fields['fan_2_min_rpm']['current']), (value, 3000))
        for changes in ({'fan_1_min_rpm': 2500}, {'fan_1_min_rpm': 2500, 'fan_2_min_rpm': 2000}):
            with self.subTest(changes=changes), self.assertRaises(VbiosError) as error:
                edit(image, changes)
            self.assertEqual(error.exception.code, 'OUT_OF_BOUNDS')

    def test_other_shapes_stay_read_only(self):
        image = conflicting_image()
        row = backend(image).fan_coolers()['rows'][0]
        # Curve point 1 below the minimum, a maximum below the curve top.
        for at, data in ((row['policy_offset'] + 20, struct.pack('<H', 2500)),
                         (row['offset'] + 16, struct.pack('<H', 5000))):
            with self.subTest(at=at):
                self.assertFalse(descriptors(from_bytes(patched(image.blob, at, data)))['fan_1_min_rpm']['editable'])

    def test_gui_note_only_on_a_minimum_above_its_range(self):
        fields = descriptors(conflicting_image())
        for language in ('en', 'es'):
            self.assertIn('2295 RPM', fan_minimum_notes(fields['fan_1_min_rpm'], language)[0])
        self.assertEqual(fan_minimum_notes(fields['fan_1_min_pct']), [])
        self.assertEqual(fan_minimum_notes(descriptors(from_bytes(synthetic_rom(fans=2)))['fan_1_min_rpm']), [])


if __name__ == '__main__':
    unittest.main()
