"""Turing (TU102-TU117): board power fields and loader payloads on generated images and reference ROMs."""
import contextlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nvidia_vbios.editor import edit, normalize_manifest
from nvidia_vbios.families import architecture
from nvidia_vbios.gui.controller import loader_messages, open_document, save_document, stage_document
from nvidia_vbios.rom import FormatError, VbiosError, from_bytes, inspect_image, load, normalize
from nvidia_vbios.rom.image import backend
from nvidia_vbios.rom.structure import image_chains, scan_images
from nvidia_vbios.rom.turing import npde

POWER = ['power_max_w', 'power_default_w', 'power_min_w']
E0_END = 'turing-e0-end-v1'
DESKTOP_CHANNELS = {0: '02 df 00 1b b7 00 00 10', 9: '02 f5 00 1b b7 00 00 10'}
NOTEBOOK_CHANNELS = {0: '02 f5 00 1b b7 00 00 10'}


def synthetic_turing(*, device=0x1F06, efi_image=True, notebook=False, header=0x2C, channels=None, tgp_channel=None,
                     limits=(125000, 175000, 200000), copies=2):
    """NVGI banks holding a generated Turing chain, then a type-0x70 image outside the banks.

    Chain: legacy [+ EFI] + E0 + E0 (not flagged last; its NPDE has a last-image byte) + a
    type-0x70 image flagged last. The second E0 image holds the power table 30/2c/42 (header
    0x27: 30/27/42) with the TGP row 2 (min/rated/max mW in limits) and the 20-entry power
    channel table; the board-total channel (class 2, rail 0xf5) is 9 on the desktop layout
    and 0 on the notebook one (header bytes 10..13 ff ff ff 02).
    """
    bank_size, prefix = 16384, 512
    images = [(2048, b'\x55\xaa', 0, device, 0x80 if not efi_image else 0)]
    images += [(512, b'\x55\xaa', 3, device, 0x80)] if efi_image else []
    images += [(512, b'VN', 0xE0, device & 0xFF80, 0), (8192, b'VN', 0xE0, device & 0xFF80, 0), (512, b'VN', 0x70, 0, 0x80)]
    bank = bytearray(b'\xff' * bank_size)
    bank[:4] = b'NVGI'
    regions, at = [], prefix
    for size, signature, code, dev, last in images:
        bank[at:at + size] = bytes(size)
        bank[at:at + 2] = signature
        struct.pack_into('<H', bank, at + 0x18, 0x20)
        h = at + 0x20
        bank[h:h + 4] = b'PCIR' if signature == b'\x55\xaa' else b'NPDS'
        struct.pack_into('<HHHH', bank, h + 4, 0x10DE, dev, 0, 0x18)
        struct.pack_into('<H', bank, h + 0x10, size // 512)
        bank[h + 0x14:h + 0x16] = bytes((code, last))
        if code == 0xE0:
            bank[at + 0x40:at + 0x4C] = b'NPDE' + struct.pack('<HHHBB', 0x101, 0x14, size // 512, 0, 0)
        if code == 0x70:
            bank[at + 0x38:at + 0x3C] = b'ISBN'
        bank[at + size - 16:at + size] = b'\xff' * 16
        regions.append((at, at + size))
        at += size
    legacy = prefix
    bit = legacy + 128
    bank[bit:bit + 6] = b'\xff\xb8BIT\x00'
    bank[bit + 8:bit + 11] = bytes((12, 6, 2))
    bank[bit + 11] = -sum(bank[bit:bit + 12]) & 255
    struct.pack_into('<BBHH', bank, bit + 12, ord('P'), 2, 0xC4, 256)
    struct.pack_into('<BBHH', bank, bit + 18, ord('C'), 2, 0x1C, 600)
    bank[legacy + 700:legacy + 714] = b'90.06.44.00.AE'
    efi = 512 if efi_image else 0
    data = regions[-2][0]
    power, table = data + 0x100, data + 0x600
    for offset, target in ((0x2C, power), (0x3C, table)):
        struct.pack_into('<I', bank, legacy + 256 + offset, target - legacy - efi)
    bank[power:power + 4] = bytes((0x30, header, 0x42, 3))
    bank[power + 10] = 2
    if notebook:
        bank[power + 10:power + 14] = bytes((0xFF, 0xFF, 0xFF, 2))
    row = power + header + 2 * 0x42
    bank[row:row + 2] = bytes((0x21, (0 if notebook else 9) if tgp_channel is None else tgp_channel))
    struct.pack_into('<III', bank, row + 2, *limits)
    bank[table:table + 6] = bytes.fromhex('20 06 16 14 00 00')
    for index, entry in (channels or (NOTEBOOK_CHANNELS if notebook else DESKTOP_CHANNELS)).items():
        entry = bytes.fromhex(entry)
        bank[table + 6 + 0x16 * index:table + 6 + 0x16 * index + len(entry)] = entry
    for start, end in regions:
        bank[end - 1] = (bank[end - 1] - sum(bank[start:end])) & 255
    tail = bytearray(b'\xff' * 512)
    tail[:2], tail[0x18:0x1A], tail[0x20:0x24] = b'VN', b'\x20\x00', b'NPDS'
    struct.pack_into('<HHHH', tail, 0x24, 0x10DE, 0, 0, 0x18)
    struct.pack_into('<H', tail, 0x30, 1)
    tail[0x34:0x36] = bytes((0x70, 0x80))
    return bytes(bank) * copies + bytes(tail)


def patch_banks(blob, change):
    """Apply change(bytearray, chain) to every chain of blob, then repair every image checksum."""
    chains = backend(from_bytes(blob)).chains
    patched = bytearray(blob)
    for chain in chains:
        change(patched, chain)
    for image in (image for chain in chains for image in chain):
        patched[image['end'] - 1] = (patched[image['end'] - 1] - sum(patched[image['start']:image['end']])) & 255
    return bytes(patched)


def chain_types(blob):
    """Image types of the first Turing chain of blob (headers only, no checksums)."""
    return [p['type'] for p in image_chains(blob, *scan_images(blob)[:2], family='turing')[0]]


def descriptors(image):
    return {f['key']: f for f in inspect_image(image)['fields']}


def tgp_offsets(blob):
    parser = backend(from_bytes(blob))
    return parser.copy_offsets(parser.power_rows()[parser.tgp_index]['maximum_offset'] - 8, 12)


class TuringStructureTests(unittest.TestCase):
    def test_turing_ids_and_bios_family(self):
        arch = architecture(0x1F06, ('90.06.44.00.AE',))
        self.assertEqual((arch['family'], arch['in_scope'], arch['bios_family_consistent']), ('turing', True, True))
        self.assertEqual(arch['evidence'][1]['expected_prefix'], '90.')
        self.assertFalse(architecture(0x1F06, ('94.06.44.00.AE',))['bios_family_consistent'])
        for device in (0x1E02, 0x1E07, 0x1E30, 0x1E84, 0x1E90, 0x1F08, 0x1F82, 0x1F83, 0x2182, 0x2187, 0x21C4):
            self.assertEqual(architecture(device)['family'], 'turing', hex(device))
        # GA100 keeps its own BIOS family; neighbors outside NVIDIA's table stay unknown.
        self.assertEqual(architecture(0x20B0, ('92.00.25.00.08',))['evidence'][1]['expected_prefix'], '92.')
        self.assertEqual(architecture(0x1E00)['family'], 'unknown')

    def test_chain_ends_with_the_type_0x70_image(self):
        for efi in (True, False):
            with self.subTest(efi=efi):
                parser = backend(from_bytes(synthetic_turing(efi_image=efi)))
                self.assertEqual(len(parser.chains), 2)
                types = [p['type'] for p in parser.chains[0]]
                self.assertEqual(types, [0, 3, 0xE0, 0xE0, 0x70] if efi else [0, 0xE0, 0xE0, 0x70])
                self.assertEqual([p['last'] for p in parser.chains[0][-2:]], [False, True])
                self.assertEqual(parser.efi is not None, efi)
                self.assertTrue(parser.integrity()['valid'])

    def test_ampere_and_ada_rules_do_not_take_the_turing_chain(self):
        blob = synthetic_turing()
        pci, extended, _ = scan_images(blob)
        for family in ('ampere', 'ada', None):
            with self.subTest(family=family), self.assertRaisesRegex(FormatError, 'complete last image'):
                image_chains(blob, pci, extended, family=family)
        # A type-0x70 image that is not flagged last does not end a Turing chain either.
        broken = bytearray(blob)
        npds = [p for p in extended if p['type'] == 0x70][0]['npds']
        broken[npds + 0x15] = 0
        with self.assertRaisesRegex(FormatError, 'complete last image'):
            image_chains(bytes(broken), *scan_images(bytes(broken))[:2], family='turing')

    def test_only_an_unflagged_data_image_and_an_nvidia_type_0x70_npds_tail_end_the_chain(self):
        blob = synthetic_turing()
        parser = backend(from_bytes(blob))
        self.assertEqual(chain_types(blob), [0, 3, 0xE0, 0xE0, 0x70])
        tail, last = parser.chains[0][-1], parser.chains[0][-2]
        # The tail carries no device (0000) on the reference images; this chip's ID is accepted too.
        accepted = bytearray(blob)
        struct.pack_into('<H', accepted, tail['npds'] + 6, 0x1F00)
        self.assertEqual(chain_types(bytes(accepted))[-1], 0x70)
        refused = {'another chip': lambda b: struct.pack_into('<H', b, tail['npds'] + 6, 0x2200),
                   'another vendor': lambda b: struct.pack_into('<H', b, tail['npds'] + 4, 0x1234),
                   # A PCIR image (55 aa) of type 0x70 is not the NPDS tail.
                   'PCIR image': lambda b: (b.__setitem__(slice(tail['start'], tail['start'] + 2), b'\x55\xaa'),
                                            b.__setitem__(slice(tail['npds'], tail['npds'] + 4), b'PCIR')),
                   # A loader that reads the NPDE byte would end the chain at this data image.
                   'NPDE last byte': lambda b: b.__setitem__(npde(blob, last) + 0x0A, 0x80)}
        for name, change in refused.items():
            broken = bytearray(blob)
            change(broken)
            with self.subTest(refused=name), self.assertRaisesRegex(FormatError, 'complete last image'):
                chain_types(bytes(broken))
        # A data image flagged last in its NPDS ends the chain there, as on Ampere and Ada.
        flagged = bytearray(blob)
        flagged[last['npds'] + 0x15] = 0x80
        self.assertEqual(chain_types(bytes(flagged)), [0, 3, 0xE0, 0xE0])

    def test_no_table_is_read_from_the_type_0x70_image(self):
        blob = synthetic_turing()
        parser = backend(from_bytes(blob))
        power, size = parser.pointer('P', 0x2C), 0x2C + 3 * 0x42
        def move(b, chain):
            # Copy the power table into the type-0x70 image and point P+0x2c at the copy.
            at = chain[-1]['start'] + 0x40
            b[at:at + size] = blob[chain[0]['start'] + power - parser.legacy['start']:][:size]
            entry = chain[0]['start'] + parser.tokens['P']['data'] - parser.legacy['start'] + 0x2C
            struct.pack_into('<I', b, entry, at - chain[0]['start'] - parser.efi['size'])
        report = inspect_image(from_bytes(patch_banks(blob, move)))
        self.assertFalse([f for f in report['fields'] if f['key'] in POWER])
        self.assertIn('outside or crosses a primary image boundary',
                      ' '.join(d['message'] for d in report['diagnostics']))

    def test_smaller_bit_tokens_have_no_pointers_past_their_end(self):
        parser = backend(from_bytes(synthetic_turing()))
        self.assertEqual(parser.tokens['P']['size'], 0xC4)
        for offset in (0xC4, 0xDC, 0xE0, 0xE8, 0xF4):
            with self.subTest(offset=hex(offset)), self.assertRaisesRegex(FormatError, 'outside BIT token'):
                parser.pointer('P', offset)
        self.assertIsNone(parser.profile_table())
        self.assertEqual(parser.power_profiles(), [])


class TuringPowerTests(unittest.TestCase):
    def test_board_power_fields_only_experimental_with_the_turing_caveats(self):
        image = from_bytes(synthetic_turing())
        report = inspect_image(image)
        fields = {f['key']: f for f in report['fields']}
        self.assertEqual([fields[k]['current'] for k in POWER], [200, 175, 125])
        self.assertEqual(sorted(k for k, f in fields.items() if f['editable']), sorted(POWER))
        self.assertEqual(sorted(fields), sorted(POWER + ['current_limit_a', 'ocp_limit_a']))
        for key in POWER:
            field = fields[key]
            self.assertTrue(field['experimental'], key)
            for text in ('decodes like the Ampere one', 'not hardware-tested on Turing', 'signed hash list',
                         'whether the driver checks it is unknown'):
                self.assertIn(text, field['reason'], key)
            self.assertIn('Turing 30/2c/42', field['evidence'][0]['recognized_variants'])
            self.assertIn('integrity-observation', [e['kind'] for e in field['evidence']])
        # Same bounds as the Ampere fields: ceiling from the rated value, floor from 1 W.
        self.assertEqual((fields['power_max_w']['bounds']['minimum'], fields['power_min_w']['bounds']['minimum']),
                         (175, 1))
        self.assertIsNone(fields['power_max_w']['bounds']['hardware_safe_maximum'])
        messages = ' '.join(d['message'] for d in report['diagnostics'])
        for tables in ('rail and VFE', 'clock', 'fan'):
            self.assertIn(f'Turing {tables} tables are not reviewed', messages)

    def test_header_variant_and_notebook_layout(self):
        fields = descriptors(from_bytes(synthetic_turing(header=0x27)))
        self.assertEqual([fields[k]['current'] for k in POWER], [200, 175, 125])
        notebook = descriptors(from_bytes(synthetic_turing(notebook=True, efi_image=False, limits=(1000, 80000, 95000))))
        self.assertEqual([notebook[k]['current'] for k in POWER], [95, 80, 1])
        self.assertIn('stored notebook TGP', notebook['power_max_w']['reason'])
        self.assertIn('not hardware-tested on Turing', notebook['power_default_w']['reason'])

    def test_tgp_row_must_read_the_only_board_total_channel(self):
        refused = (dict(tgp_channel=0),                                               # another class-2 sum
                   dict(channels={**DESKTOP_CHANNELS, 3: '02 f5 00 1b b7 00 00 10'}),        # two board totals
                   dict(channels={0: '02 df 00 1b b7 00 00 10'}))                       # none
        for options in refused:
            with self.subTest(options=options):
                report = inspect_image(from_bytes(synthetic_turing(**options)))
                self.assertFalse([f for f in report['fields'] if f['key'] in POWER])
                self.assertIn('total board power channel', ' '.join(d['message'] for d in report['diagnostics']))
        moved = synthetic_turing(channels={4: '02 f5 00 1b b7 00 00 10'}, tgp_channel=4)
        self.assertEqual(descriptors(from_bytes(moved))['power_max_w']['current'], 200)
        blob = synthetic_turing()
        parser = backend(from_bytes(blob))
        table = parser.pointer('P', 0x3C) - parser.legacy['start']
        count_0x20 = patch_banks(blob, lambda b, chain: b.__setitem__(chain[0]['start'] + table + 3, 0x20))
        messages = [d['message'] for d in inspect_image(from_bytes(count_0x20))['diagnostics']]
        self.assertIn('unvalidated Turing power channel table', messages)

    def test_edit_writes_both_banks_and_their_checksums_and_reverts(self):
        image = from_bytes(synthetic_turing())
        result = edit(image, {'power_max_w': 250, 'power_default_w': 180, 'power_min_w': 100})
        parser = backend(result.image)
        self.assertTrue(parser.integrity()['valid'])
        self.assertEqual([r['default_raw'] for r in parser.power_rows()], [0, 0, 180000])
        changed = [i for i, (a, b) in enumerate(zip(image.blob, result.blob)) if a != b]
        rows, ends = tgp_offsets(image.blob), [c[-2]['end'] - 1 for c in parser.chains]
        self.assertTrue(set(changed) <= {at + k for at in rows for k in range(12)} | set(ends))
        self.assertEqual({at // 16384 for at in changed}, {0, 1})          # both banks
        self.assertEqual(sorted(r['kind'] for r in result.manifest['integrity_repairs']), ['additive_checksum'] * 2)
        back = edit(result.image, {'power_max_w': 200, 'power_default_w': 175, 'power_min_w': 125})
        self.assertEqual(back.blob, image.blob)

    def test_unpadded_power_image_keeps_every_field_read_only(self):
        blob = bytearray(synthetic_turing(copies=1))
        parser = backend(from_bytes(bytes(blob)))
        end = parser.chains[0][-2]['end']
        blob[end - 2] = 0
        blob[end - 1] = (blob[end - 1] + 0xFF) & 255
        report = inspect_image(from_bytes(bytes(blob)))
        self.assertEqual([f['key'] for f in report['fields'] if f['editable']], [])


class TuringPayloadTests(unittest.TestCase):
    def test_default_payload_is_the_single_bank_as_it_is(self):
        blob = synthetic_turing()
        payload = normalize(from_bytes(blob))
        self.assertEqual(payload.blob, blob[:16384])
        parser = backend(payload)
        self.assertEqual([p['type'] for p in parser.chains[0]], [0, 3, 0xE0, 0xE0, 0x70])
        self.assertEqual(normalize(payload).blob, payload.blob)

    def test_e0_end_payload_ends_at_the_second_e0_image(self):
        for efi in (True, False):
            with self.subTest(efi=efi):
                bank = normalize(from_bytes(synthetic_turing(efi_image=efi))).blob
                payload = normalize(from_bytes(synthetic_turing(efi_image=efi)), representation=E0_END)
                parser = backend(payload)
                chain = parser.chains[0]
                self.assertEqual([p['type'] for p in chain], [0, 3, 0xE0, 0xE0] if efi else [0, 0xE0, 0xE0])
                self.assertTrue(chain[-1]['last'])
                self.assertEqual(len(payload.blob), chain[-1]['end'])
                self.assertFalse([p for p in scan_images(payload.blob)[1] if p['type'] == 0x70])
                self.assertTrue(parser.integrity()['valid'])
                self.assertEqual(parser.legacy['device'], 0x1F06)
                # The NPDS and NPDE last-image bits; their sum keeps the checksum byte unchanged.
                diff = [i for i in range(len(payload.blob)) if payload.blob[i] != bank[i]]
                last = chain[-1]
                self.assertEqual(diff, [last['npds'] + 0x15, last['start'] + 0x4A])
                self.assertEqual([payload.blob[i] for i in diff], [0x80, 0x80])
                self.assertEqual(descriptors(payload)['power_max_w']['current'], 200)
                for representation in (None, E0_END):
                    self.assertEqual(normalize(payload, representation=representation).blob, payload.blob)

    def test_e0_end_repairs_the_checksum_when_the_flags_do_not_cancel(self):
        from nvidia_vbios.rom import turing
        blob = bytearray(synthetic_turing(copies=1))
        bank = backend(from_bytes(bytes(blob)))
        last = bank.chains[0][-2]
        blob[last['start'] + 0x4A] = 0x80                     # NPDE last-image byte already set
        blob[last['end'] - 1] = (blob[last['end'] - 1] - 0x80) & 255
        # The chain rule refuses such a source (the NPDE ends the chain there); a bank handed over
        # directly still gets a valid checksum.
        with self.assertRaisesRegex(FormatError, 'complete last image'):
            backend(from_bytes(bytes(blob)))
        bank.blob = bytes(blob)
        payload = from_bytes(turing.e0_end(bank))
        self.assertTrue(backend(payload).integrity()['valid'])
        diff = [i for i in range(len(payload.blob)) if payload.blob[i] != blob[i]]
        self.assertEqual(diff, [last['npds'] + 0x15, last['end'] - 1])

    def test_e0_end_refuses_other_families_and_turing_refuses_other_representations(self):
        from test_rom_formats import synthetic_rom
        with self.assertRaises(VbiosError) as exc:
            normalize(from_bytes(synthetic_rom(family='ampere')), representation=E0_END)
        self.assertEqual(exc.exception.code, 'UNREVIEWED_RELOCATION_SOURCE')
        for representation in ('ada-relocated-v1', 'ada-relocated-v2', 'ampere-relocated-v1'):
            with self.subTest(representation=representation), self.assertRaises(VbiosError) as exc:
                normalize(from_bytes(synthetic_turing()), representation=representation)
            self.assertEqual(exc.exception.code, 'UNREVIEWED_RELOCATION_SOURCE')

    def test_e0_end_needs_an_npde_last_image_byte(self):
        blob = bytearray(synthetic_turing(copies=1))
        last = backend(from_bytes(bytes(blob))).chains[0][-2]
        blob[last['start'] + 0x40:last['start'] + 0x44] = b'XXXX'
        blob[last['end'] - 1] = (blob[last['end'] - 1] - sum(b'XXXX') + sum(b'NPDE')) & 255
        with self.assertRaises(VbiosError) as exc:
            normalize(from_bytes(bytes(blob)), representation=E0_END)
        self.assertEqual(exc.exception.code, 'RELOCATION_VERIFICATION_FAILED')

    def test_e0_end_refuses_an_unpadded_image_or_an_npde_without_a_reviewed_last_image_byte(self):
        blob = synthetic_turing()
        cases = {'no checksum padding': lambda b, chain: b.__setitem__(chain[-2]['end'] - 2, 0),
                 'NPDE version 0x200': lambda b, chain: struct.pack_into('<H', b, chain[-2]['start'] + 0x44, 0x200),
                 'NPDE header 0x0a': lambda b, chain: struct.pack_into('<H', b, chain[-2]['start'] + 0x46, 0x0A)}
        for name, change in cases.items():
            source = from_bytes(patch_banks(blob, change))
            self.assertTrue(backend(source).integrity()['valid'])
            with self.subTest(case=name), self.assertRaises(VbiosError) as exc:
                normalize(source, representation=E0_END)
            self.assertEqual(exc.exception.code, 'RELOCATION_VERIFICATION_FAILED')

    def test_e0_end_checks_the_source_chain_and_the_re_parsed_payload(self):
        from nvidia_vbios.rom import turing
        bank = backend(normalize(from_bytes(synthetic_turing())))
        changes = {'PCI identity': lambda p: setattr(p, 'legacy', dict(p.legacy, device=0x1F07)),
                   'chain shape': lambda p: p.chains[0].__setitem__(1, dict(p.chains[0][1], type=4)),
                   'last image': lambda p: p.chains[0].__setitem__(-1, dict(p.chains[0][-1], last=False)),
                   'integrity': lambda p: setattr(p, 'integrity', lambda: {'valid': False})}
        for name, change in changes.items():
            class Reparsed(turing.TableRom):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    change(self)
            with self.subTest(changed=name), mock.patch.object(turing, 'TableRom', Reparsed), \
                    self.assertRaises(VbiosError) as exc:
                turing.e0_end(bank)
            self.assertEqual(exc.exception.code, 'RELOCATION_VERIFICATION_FAILED')
        # The tail must be the type-0x70 image.
        bank.chains[0][-1] = dict(bank.chains[0][-1], type=0x71)
        with self.assertRaises(VbiosError) as exc:
            turing.e0_end(bank)
        self.assertEqual(exc.exception.code, 'RELOCATION_VERIFICATION_FAILED')

    def test_cli_normalize_writes_the_e0_end_payload_and_its_manifest(self):
        from nvidia_vbios import cli
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / 'edited.rom', Path(tmp) / 'payload.bin'
            source.write_bytes(synthetic_turing())
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(['normalize', str(source), str(output), '--representation', E0_END])
            self.assertEqual(code, 0)
            manifest = json.loads(output.with_name('payload.bin.json').read_text())
            self.assertEqual(output.read_bytes(), normalize(from_bytes(synthetic_turing()), representation=E0_END).blob)
        self.assertEqual(manifest['representation'], E0_END)
        self.assertIn('type-0x70 image', manifest['note'])

    def test_manifest_note(self):
        source = from_bytes(synthetic_turing())
        payload = normalize(source, representation=E0_END)
        note = normalize_manifest(source, payload, E0_END, 'source.rom')['note']
        self.assertIn('Experimental, not hardware validated', note)
        self.assertIn('type-0x70 image', note)

    def test_editor_window_saves_both_payloads_next_to_a_turing_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.rom'
            source.write_bytes(synthetic_turing())
            output = Path(tmp) / 'copy.rom'
            saved = save_document(stage_document(open_document(source), {'power_max_w': 220}), output).last_saved
            self.assertEqual([(l['output'], l['representation']) for l in saved['loaders']],
                             [(str(Path(tmp) / 'copy-loader.bin'), None),
                              (str(Path(tmp) / 'copy-loader-e0end.bin'), E0_END)])
            self.assertEqual(saved['loader'], saved['loaders'][0])
            copy = load(output)
            for loader in saved['loaders']:
                manifest = json.loads(Path(loader['manifest']).read_text())
                self.assertEqual((manifest['representation'], manifest['source_sha256']),
                                 (loader['representation'], copy.sha256))
                payload = Path(loader['output']).read_bytes()
                self.assertEqual(payload, normalize(copy, representation=loader['representation']).blob)
                self.assertEqual(descriptors(from_bytes(payload))['power_max_w']['current'], 220)
            # Either payload left by an earlier copy refuses the whole save.
            for name in ('again-loader.bin', 'again-loader-e0end.bin.json'):
                with self.subTest(existing=name):
                    (Path(tmp) / name).write_bytes(b'older')
                    with self.assertRaises(VbiosError) as exc:
                        save_document(stage_document(open_document(source), {'power_max_w': 230}),
                                      Path(tmp) / 'again.rom')
                    self.assertEqual(exc.exception.code, 'LOADER_OUTPUT_EXISTS')
                    self.assertFalse((Path(tmp) / 'again.rom').exists())
                    (Path(tmp) / name).unlink()

    def test_a_payload_the_loaders_would_refuse_is_not_saved(self):
        # A full-size file whose second bank is erased: plain normalize keeps the flash bytes after
        # the chain and sends more than 512 KiB, the e0-end payload ends at the last data image.
        single = synthetic_turing(copies=1)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.rom'
            source.write_bytes(single[:16384] + b'\xff' * 0x80000 + single[16384:])
            saved = save_document(stage_document(open_document(source), {'power_max_w': 220}),
                                  Path(tmp) / 'copy.rom').last_saved
            default, e0_end = saved['loaders']
            self.assertIn('accepts at most 524288', default['error'])
            self.assertFalse((Path(tmp) / 'copy-loader.bin').exists())
            self.assertEqual(e0_end['output'], str(Path(tmp) / 'copy-loader-e0end.bin'))
            self.assertEqual(loader_messages(saved), [('saved_loader', dict(output=e0_end['output'])),
                                                      ('saved_loader_other_failed', dict(reason=default['error']))])

    def test_status_lines_name_the_file_to_load_first(self):
        first, second = dict(output='copy-loader.bin'), dict(output='copy-loader-e0end.bin')
        refused = dict(error='refused')
        cases = (([first, second], [('saved_loader', dict(output='copy-loader.bin')),
                                    ('saved_loader_alternative', dict(output='copy-loader-e0end.bin'))]),
                 ([first, refused], [('saved_loader', dict(output='copy-loader.bin')),
                                     ('saved_loader_other_failed', dict(reason='refused'))]),
                 ([refused, refused], [('saved_loader_failed', dict(reason='refused'))] * 2),
                 ([], []))
        for loaders, lines in cases:
            with self.subTest(loaders=loaders):
                self.assertEqual(loader_messages(dict(loader=loaders[0] if loaders else None, loaders=loaders)), lines)
        # One payload (Ampere, Ada): as before.
        self.assertEqual(loader_messages(dict(loader=first)), [('saved_loader', dict(output='copy-loader.bin'))])
        self.assertEqual(loader_messages(dict(loader=refused)), [('saved_loader_failed', dict(reason='refused'))])


if __name__ == '__main__':
    unittest.main()
