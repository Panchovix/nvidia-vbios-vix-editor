"""Runtime VFE layout document (`nvbios vfe-layout`, rom.vfe_layout) of synthetic GB20x images; the private corpus
class also checks every GB20x ROM of the corpus. The loader's layout store is in test_vfe_layout_store.py."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
from test_runtime_voltage_offsets import hooks_fixture, patched, tables
from nvidia_vbios import cli
from nvidia_vbios.editor import edit
from nvidia_vbios.rom import VbiosError, from_bytes, load
from nvidia_vbios.rom.blackwell import BlackwellRom
from nvidia_vbios.rom.image import backend
from nvidia_vbios.rom.vfe_layout import layout_bytes, layout_document, payload_layout

KEYS = ['schema_version', 'image_sha256', 'reference_variable', 'variable_bitmap_hex', 'equation_bitmap_hex', 'slots']
SLOT_KEYS = ['rail', 'field', 'wrapper', 'next', 'variable', 'min_uv', 'max_uv']
_FIXTURES = {}


def fixtures():
    """(stock, hooked) synthetic GB20x images (test_runtime_voltage_offsets.hooks_fixture), built once."""
    if not _FIXTURES:
        stock = hooks_fixture()
        _FIXTURES.update(stock=stock, hooked=edit(from_bytes(stock), {'runtime_voltage_offsets': 1}).blob)
    return _FIXTURES['stock'], _FIXTURES['hooked']


def bits(text):
    mask = bytes.fromhex(text)
    return [i for i in range(8 * len(mask)) if mask[i >> 3] >> (i & 7) & 1]


def check_document(test, blob, document):
    """The helper's v1 rules, checked against the image bytes located without the document builder."""
    test.assertEqual(list(document), KEYS)
    test.assertEqual(document['schema_version'], 'nvidia-runtime-vfe-layout/v1')
    test.assertEqual(document['image_sha256'], hashlib.sha256(blob).hexdigest())
    test.assertRegex(document['variable_bitmap_hex'], r'\A[0-9a-f]{64}\Z')
    test.assertRegex(document['equation_bitmap_hex'], r'\A[0-9a-f]{2048}\Z')
    variables, equations, count, _, _ = tables(blob)
    used_v = [i for i in range(255) if blob[variables + 29 * i]]
    used_e = [i for i in range(count) if blob[equations + 25 * i]]
    test.assertEqual((used_v, used_e), (list(range(len(used_v))), list(range(len(used_e)))))  # one free tail each
    var_bits, eq_bits = bits(document['variable_bitmap_hex']), bits(document['equation_bitmap_hex'])
    test.assertEqual((var_bits, eq_bits), (used_v, used_e))
    test.assertNotIn(255, var_bits)
    slots, reference = document['slots'], document['reference_variable']
    test.assertTrue(1 <= len(slots) <= 8)
    for s in slots:
        test.assertEqual(list(s), SLOT_KEYS)
        test.assertIn(s['rail'], ('NVVDD', 'MSVDD'))
        test.assertIn(s['field'], ('REL', 'ALT', 'OV', 'VMIN'))
        test.assertTrue(s['wrapper'] <= 0x1FFF and s['next'] <= 0x1FFF and s['wrapper'] != s['next'])
        test.assertTrue(s['variable'] < 0xFF and s['variable'] != reference)
        test.assertEqual((s['min_uv'], s['max_uv']), (-1250000, 1250000))
        test.assertTrue({s['wrapper'], s['next']} <= set(eq_bits) and s['variable'] in var_bits)
        e = blob[equations + 25 * s['wrapper']:equations + 25 * s['wrapper'] + 25]
        test.assertEqual((e[0], e[1], e[2] | e[24] << 8, e[23]), (1, s['variable'], s['next'], 2))
    test.assertIn(reference, var_bits)
    test.assertEqual(blob[variables + 29 * reference], 9)
    for key in ('variable', 'wrapper'):
        test.assertEqual(len({s[key] for s in slots}), len(slots))
    test.assertEqual(len({(s['rail'], s['field']) for s in slots}), len(slots))
    test.assertFalse({s['wrapper'] for s in slots} & {s['next'] for s in slots})


def hook_slots(image):
    hooks = backend(image).runtime_hooks()
    return hooks['reference'], [(s['rail'], s['role'], s['hook'], s['target'], s['variable']) for s in hooks['slots']]


def document_slots(document):
    return document['reference_variable'], [(s['rail'], s['field'], s['wrapper'], s['next'], s['variable'])
                                            for s in document['slots']]


def run_cli(args):
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        code = cli.main(args)
    return code, stream.getvalue()


class LayoutDocumentTests(unittest.TestCase):
    def setUp(self):
        self.stock, self.hooked = fixtures()

    def test_document_of_hooked_image(self):
        image = from_bytes(self.hooked)
        document = layout_document(image)
        check_document(self, self.hooked, document)
        self.assertEqual(document_slots(document), hook_slots(image))
        self.assertEqual(payload_layout(self.hooked), layout_bytes(document))
        self.assertEqual(json.loads(layout_bytes(document)), document)

    def test_images_without_hooks_or_not_gb20x_are_refused(self):
        with self.assertRaises(VbiosError) as caught:
            layout_document(from_bytes(self.stock))
        self.assertEqual(caught.exception.code, 'NO_RUNTIME_HOOKS')
        self.assertIsNone(payload_layout(self.stock))
        from test_rom_formats import synthetic_rom
        with self.assertRaises(VbiosError) as caught:
            layout_document(from_bytes(synthetic_rom()))
        self.assertEqual(caught.exception.code, 'UNSUPPORTED_ARCHITECTURE')
        self.assertIsNone(payload_layout(synthetic_rom()))
        self.assertIsNone(payload_layout(b'REVIEWED ROM payload'))

    def test_partial_hooks_and_gaps_are_refused(self):
        hooks = backend(from_bytes(self.hooked)).runtime_hooks()
        variables, equations, _, _, _ = tables(self.hooked)
        cases = {'NO_RUNTIME_HOOKS': patched(self.hooked, hooks['slots'][0]['variable_offset'], b'\x01'),
                 'VFE_LAYOUT_REFUSED': patched(self.hooked, variables + 29 * 254, b'\x01')}
        cases['VFE_LAYOUT_REFUSED '] = patched(self.hooked, equations + 25 * 2047, b'\x01')
        for code, blob in cases.items():
            with self.subTest(code), self.assertRaises(VbiosError) as caught:
                payload_layout(blob)
            self.assertEqual(caught.exception.code, code.strip())

    def test_every_rule_is_checked_again(self):
        report = backend(from_bytes(self.hooked)).runtime_hooks()

        def duplicate_role(r):
            r['slots'][1]['role'] = r['slots'][0]['role']

        def shared_variable(r):
            r['slots'][1].update(variable=r['slots'][0]['variable'], variable_offset=r['slots'][0]['variable_offset'])

        def wrapper_is_next(r):
            r['slots'][0]['target'] = r['slots'][1]['hook']

        def out_of_bounds(r):
            r['slots'][0].update(hook=0x2000, hook_offset=r['slots'][0]['hook_offset'] + 25 * (0x2000 - r['slots'][0]['hook']))
        mutations = [lambda r: r.update(reference=r['slots'][0]['variable']), lambda r: r.update(reference=None),
                     lambda r: r.update(slots=r['slots'] * 2), lambda r: r.update(slots=[]),
                     duplicate_role, shared_variable, wrapper_is_next, out_of_bounds]
        for index, mutate in enumerate(mutations):
            changed = copy.deepcopy(report)
            mutate(changed)
            with self.subTest(index), mock.patch.object(BlackwellRom, 'runtime_hooks', return_value=changed), \
                    self.assertRaises(VbiosError) as caught:
                layout_document(from_bytes(self.hooked))
            self.assertEqual(caught.exception.code, 'VFE_LAYOUT_REFUSED')

    def test_command_prints_writes_or_refuses(self):
        with tempfile.TemporaryDirectory() as directory:
            hooked, stock = Path(directory) / 'hooked.bin', Path(directory) / 'stock.bin'
            hooked.write_bytes(self.hooked)
            stock.write_bytes(self.stock)
            expected = layout_bytes(layout_document(from_bytes(self.hooked)))
            self.assertEqual(run_cli(['vfe-layout', str(hooked)]), (0, expected.decode()))
            output = Path(directory) / 'layout.json'
            output.write_text('old')
            code, text = run_cli(['vfe-layout', str(hooked), '--output', str(output)])
            self.assertEqual((code, json.loads(text)['result']),
                             (0, {'output': str(output), 'image_sha256': hashlib.sha256(self.hooked).hexdigest(),
                                  'slots': 8}))
            # chmod 0o644 on Windows only clears the read-only flag, which stat reports as 0o666.
            self.assertEqual((output.read_bytes(), stat.S_IMODE(output.stat().st_mode)),
                             (expected, 0o666 if os.name == 'nt' else 0o644))
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ['hooked.bin', 'layout.json', 'stock.bin'])
            code, text = run_cli(['vfe-layout', str(stock), '--output', str(Path(directory) / 'none.json')])
            report = json.loads(text)
            self.assertEqual((code, report['ok'], report['operation'], report['error']['code']),
                             (2, False, 'vfe-layout', 'NO_RUNTIME_HOOKS'))
            self.assertFalse((Path(directory) / 'none.json').exists())
            code, text = run_cli(['vfe-layout', str(hooked), '--output', str(hooked)])
            self.assertEqual((code, json.loads(text)['error']['code']), (2, 'INVALID_ARGUMENT'))
            self.assertEqual(hooked.read_bytes(), self.hooked)


    def test_printed_document_is_byte_exact(self):
        """The document goes to stdout as bytes: no CRLF where the text layer translates newlines (Windows), and the
        root or subcommand --json changes nothing."""
        with tempfile.TemporaryDirectory() as directory:
            hooked = Path(directory) / 'hooked.bin'
            hooked.write_bytes(self.hooked)
            expected = layout_bytes(layout_document(from_bytes(self.hooked)))
            for argv in (['vfe-layout', str(hooked)], ['--json', 'vfe-layout', str(hooked)],
                         ['vfe-layout', str(hooked), '--json']):
                raw = io.BytesIO()
                stream = io.TextIOWrapper(raw, encoding='ascii', newline='\r\n')
                with self.subTest(argv), contextlib.redirect_stdout(stream):
                    code = cli.main(argv)
                stream.flush()
                self.assertEqual((code, raw.getvalue()), (0, expected))


