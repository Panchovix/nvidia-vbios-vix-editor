"""Runtime power limit switch (runtime_power_limit_unlock): the TGP index of a laptop power table header."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nvidia_vbios.editor import edit
from nvidia_vbios.editor.registry import RUNTIME_LIMIT_TURING_TESTED
from nvidia_vbios.editor.sections import field_section
from nvidia_vbios.rom import VbiosError, from_bytes, load
from nvidia_vbios.rom.blackwell import NOTEBOOK_TGP_ROW_PREFIX, BlackwellRom
from nvidia_vbios.rom.image import backend
from test_ada_fields import patched
from test_extended_fields import changed_bytes_within, custom_registry, descriptors, notebook_fixture
from test_rom_formats import synthetic_blackwell, synthetic_rom
from test_turing import synthetic_turing

KEY = 'runtime_power_limit_unlock'


def ampere_notebook(byte66=(1, 1)):
    """Ampere notebook header (bytes 10..13 ff ff ff 02); byte66 holds entry byte 66 of rows 0, 1, ... in turn. The
    default 1 in rows 0 and 1, as in row 0 of every Ampere laptop image, makes them class 17 for R525, so row 2 is its
    first class-1 row (without it the three rows are class 1)."""
    blob = synthetic_rom(family='ampere', copies=2, notebook=True)
    for row, value in zip(backend(from_bytes(blob)).power_rows(), byte66):
        blob = patched(blob, row['offset'] + 66, bytes((value,)))
    return blob


def slots(image):
    """Every copy of the TGP index: 3x header byte 10 in every chain, GB20x header byte 22."""
    parser = backend(image)
    at = parser.pointer('P', 0x2C)
    return [at + 22] if isinstance(parser, BlackwellRom) else parser.copy_offsets(at + 10, 1)


def others(image):
    """Every field descriptor but the switch."""
    return {key: field for key, field in descriptors(image).items() if key != KEY}


class RuntimeLimitTests(unittest.TestCase):
    @staticmethod
    def notebooks():
        return {'turing': synthetic_turing(notebook=True), 'ampere': ampere_notebook(), 'gb20x': notebook_fixture()}

    def test_offered_on_notebook_headers_only(self):
        for name, blob in self.notebooks().items():
            with self.subTest(name=name):
                field = descriptors(from_bytes(blob))[KEY]
                self.assertEqual((field['units'], field['current'], field['editable'], field['bounds']['minimum'],
                                  field['bounds']['maximum'], field['policy_indices']), ('flag', 0, True, 0, 1, [2]))
                self.assertTrue(field['opt_in'] and field['notebook_tgp'])
                # Tested on one Turing laptop: not experimental there, experimental on Ampere and GB20x.
                self.assertEqual(field.get('experimental', False), name != 'turing')
                self.assertEqual(field['reason'].startswith('experimental, opt-in: '), name != 'turing')
                self.assertEqual(field_section(field), 'power')
                reason = field['reason']
                # For more, the ceiling alone: the boot default is the slider's 100 % and may stay at stock.
                for part in ('nvidia-smi -pl', '0 writes 0xff back', 'later drivers refuse runtime power limit '
                             'changes on laptops', 'Dynamic Boost', 'the lowest request wins', 'a higher value has no '
                             'effect', 'until the driver loads again', 'on battery', 'raise power_max_w alone',
                             "power_default_w, 100 % on MSI Afterburner's slider", 'can stay at stock',
                             'capped by power_max_w too', 'sized for the stock limit'):
                    self.assertIn(part, reason)
                self.assertIn('no NVIDIA driver did this on GB20x' if name == 'gb20x' else 'through R525', reason)
                # Turing: the one laptop it ran on (an RTX 2070 Laptop GPU), and the stale signed hash list.
                self.assertTrue(reason.endswith(RUNTIME_LIMIT_TURING_TESTED if name == 'turing' else
                                                'not hardware-tested'))
                self.assertEqual([(e['kind'], e['set_tested']) for e in field['evidence']],
                                 [('firmware-static-analysis', False), ('structural-row-comparison', False)] +
                                 ([('hardware-test', True)] if name == 'turing' else []))
        for part in ('tested on hardware: on one RTX 2070 Laptop GPU (Windows driver 621.01, Windows loader)',
                     'at 64 % (73.6 W)',
                     'nothing above the stock 115 W was tried', 'signed hash list over this table is left stale'):
            self.assertIn(part, RUNTIME_LIMIT_TURING_TESTED)
        # Desktop headers name their TGP row already; the Ampere notebook header whose rows 0/1 R525 reads as class 1
        # (its fallback took row 0, not the D-notifier row), the GB20x notebook layout whose row 2 holds mA (row byte
        # 1 bit 0 set) and the Ada notebook header (left out) get no switch.
        for name, blob in (('turing desktop', synthetic_turing()), ('ampere desktop', synthetic_rom(family='ampere')),
                           ('ampere class-1 rows 0/1', ampere_notebook(byte66=())),
                           ('ada notebook', synthetic_rom(copies=2, notebook=True)),
                           ('gb20x desktop', synthetic_blackwell()),
                           ('gb20x row 2 in mA', notebook_fixture(base=150000, row2_prefix=bytes((1, 3)) +
                                                                  NOTEBOOK_TGP_ROW_PREFIX[2:]))):
            with self.subTest(name=name):
                fields = descriptors(from_bytes(blob))
                self.assertIn('power_max_w', fields)
                self.assertNotIn(KEY, fields)

    def test_r525_class_keeps_only_the_low_nibble_of_entry_byte_66(self):
        # R525 (like the 615 and 621 parsers) reads the class in 8 bits, so byte 66 = 0x10 adds nothing: rows 0/1
        # storing it stay class 1 (R525 took row 0, no switch), and row 2 storing it stays the first class-1 row.
        self.assertNotIn(KEY, descriptors(from_bytes(ampere_notebook(byte66=(0x10, 0x10)))))
        self.assertEqual(descriptors(from_bytes(ampere_notebook(byte66=(1, 1, 0x10))))[KEY]['current'], 0)

    def test_on_names_the_tgp_row_in_every_chain_and_off_restores_the_stock_bytes(self):
        for name, blob in self.notebooks().items():
            with self.subTest(name=name):
                image = from_bytes(blob)
                at = slots(image)
                self.assertEqual(len(at), 1 if name == 'gb20x' else 2)
                on = edit(image, {KEY: 1})
                self.assertEqual(sorted(e['offset'] for e in on.manifest['edits']), at)
                changed_bytes_within(self, image, on, at, width=1)
                self.assertEqual(({image.blob[i] for i in at}, {on.blob[i] for i in at}), ({0xFF}, {2}))
                # The copy still reads as the notebook layout: the same TGP row and every other field as before.
                self.assertEqual(descriptors(on.image)[KEY]['current'], 1)
                self.assertEqual(others(on.image), others(image))
                self.assertEqual(backend(on.image).power_rows(), backend(image).power_rows())
                self.assertEqual(edit(on.image, {KEY: 0}).blob, blob)
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {KEY: 2})
                self.assertEqual(exc.exception.code, 'OUT_OF_BOUNDS')

    def test_a_header_that_names_its_tgp_row_reads_as_switched_on(self):
        # The notebook layout with the TGP index filled in (3x byte 10 = 2 in every chain, GB20x byte 22 = 2) is the
        # copy the switch writes, and reads 1.
        stock = synthetic_turing(notebook=True)
        named = patched(stock, slots(from_bytes(stock))[0], b'\x02')
        self.assertEqual(descriptors(from_bytes(named))[KEY]['current'], 1)
        self.assertEqual(edit(from_bytes(stock), {KEY: 1}).blob, named)
        named = notebook_fixture(header=(0xFF, 2, 2))
        self.assertEqual(descriptors(from_bytes(named))[KEY]['current'], 1)
        self.assertEqual(edit(from_bytes(notebook_fixture()), {KEY: 1}).blob, named)
        self.assertEqual(edit(from_bytes(named), {KEY: 0}).blob, notebook_fixture())

    def test_with_the_board_power_fields_in_one_edit(self):
        for name, blob in self.notebooks().items():
            with self.subTest(name=name):
                image = from_bytes(blob)
                ceiling = descriptors(image)['power_max_w']['current']
                result = edit(image, {KEY: 1, 'power_max_w': ceiling + 10})
                after = descriptors(result.image)
                self.assertEqual((after[KEY]['current'], after['power_max_w']['current']), (1, ceiling + 10))
                self.assertEqual(edit(result.image, {KEY: 0, 'power_max_w': ceiling}).blob, blob)

    def test_only_the_canonical_switch_writes_the_power_table_header(self):
        image = from_bytes(synthetic_turing(notebook=True))
        at = slots(image)
        for key, code in (('probe', 'PRESERVED_FIELD_CHANGED'), (KEY, 'INVALID_FIELD_EVIDENCE')):
            with self.subTest(key=key):
                probe = custom_registry(key, at, encoding='<B', scale=1, bounds={'minimum': 0, 'maximum': 255})
                with self.assertRaises(VbiosError) as exc:
                    edit(image, {key: 2}, field_registry=probe)
                self.assertEqual(exc.exception.code, code)


if __name__ == '__main__':
    unittest.main()
