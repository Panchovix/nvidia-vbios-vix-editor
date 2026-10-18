"""Public fixtures are generated structures, never proprietary firmware bytes."""
import os
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nvidia_vbios.rom import from_bytes, inspect_image, normalize, VbiosError
from nvidia_vbios.rom.image import backend
from nvidia_vbios.rom.structure import scan_images, parse_bit


# Ada power rows with the shapes the editor recognizes (bytes 0..1 and parameter
# bytes; range bytes 2..13 hold the limits): generated structure, not firmware.
ADA_POLICY_ROWS = {
    5: ({0: 0x04, 1: 4, 41: 1}, (1000, 66000, 66000)),            # PCIe slot power, mW
    8: ({0: 0x15, 1: 4, 41: 1}, (1000, 8250, 8250)),              # slot current threshold, mA
    9: ({0: 0x15, 1: 9, 41: 1}, (1000, 30000, 30000)),            # 12 V input threshold 0, mA
    10: ({0: 0x15, 1: 9, 14: 1, 41: 1}, (1000, 30000, 30000)),    # 12 V input threshold 1, mA
    13: ({0: 0x10, 1: 0x13, 15: 0x0D, 41: 1}, (1, 108000, 108000)),  # NVVDD output current, mA
    16: ({0: 0x05, 1: 0x12, 15: 2, 16: 1, 18: 0x99, 19: 9, 41: 1}, (10000, 125983, 125983)),  # NVVDD power
}
# Power channel entries 4 (slot), 9 (12 V input), 18/19 (NVVDD output power/current).
ADA_CHANNELS = {4: '05 ff 00 1b b7 00 00 10', 9: '05 e0 00 1b b7 00 00 10 00 00 00 00 00 00 00 0e',
                18: '01 01 00 1b b7 00 00 10 00 00 00 00 00 00 05', 19: '01 01 00 1b b7 00 00 10 00 00 00 00 00 00 06'}
# Ampere (GA102-like) power rows on 22-byte channels: slot 4, connectors 5/6 (rails
# 0xfa/0xfb, provider bytes 1/2), 12 V input 15 (rail 0xe0) and NVVDD current 19.
AMPERE_POLICY_ROWS = {
    5: ({0: 0x04, 1: 4}, (1000, 66000, 78000)),          # PCIe slot power, mW
    6: ({0: 0x04, 1: 5}, (1000, 150000, 175000)),        # connector 1 power, mW
    7: ({0: 0x04, 1: 6}, (1000, 150000, 175000)),        # connector 2 power, mW
    8: ({0: 0x15, 1: 4}, (1000, 11350, 12500)),          # slot current threshold, mA
    10: ({0: 0x15, 1: 15, 14: 2}, (1000, 37800, 37800)),  # 12 V input threshold, mA
    13: ({0: 0x10, 1: 19}, (1, 226800, 226800)),         # NVVDD output current, mA
}
AMPERE_CHANNELS = {4: '05 ff 00 1b b7 00 00 10', 5: '05 fa 00 1b b7 00 00 10 00 00 00 00 00 00 00 01',
                   6: '05 fb 00 1b b7 00 00 10 00 00 00 00 00 00 00 02',
                   15: '05 e0 00 1b b7 00 00 10 00 00 00 00 00 00 00 09',
                   19: '01 01 00 1b b7 00 00 40 00 00 00 00 00 00 06 02'}


def synthetic_rom(*, family='ada', copies=1, prefix=512, tail=b'ARCHIVE-IDENTITY', unknown=False, version=None,
                  power_variant=0x5B, notebook=False, policies=False, alt=False, rel='derated', fans=0,
                  device=None, rails=2, efi_image=True, fan_speed=True):
    """Small complete PCI/NPDS chains with schema-shaped tables and bank padding.

    Ada options: power_variant 0x53 (header 0x32), 0x5B (header 0x34) or 0x4B (header 0x2C); notebook
    puts the TGP index in header byte 13; policies adds twenty power rows with the
    slot, 12 V input, NVVDD threshold and NVVDD current shapes; alt adds a
    temperature-derated ALT equation (selectors REL 2, ALT 3, VMIN 4, OV 5); rel
    picks the REL equation kind (derated, constant, compare, chained, shared);
    fans adds the five fan tables with 1 or 2 active channels (negative: laptop,
    no GPU-driven fan; 3: one active channel and a stored second channel).

    Ampere images are GA102-like: power 30/2c/47 (power_variant 0x43: 30/2c/43; 0x32: 30/32/47),
    22-byte power channel entries, a clocks table with one rail sub-entry per rail,
    rails (1 or 2) V20 rows of 17 bytes with constant REL/ALT/OV equations (24-byte
    VFE equations); policies adds the slot, two connector, slot-current, 12 V input
    and NVVDD current rows; fans as for Ada, fan_speed=False leaves the speed table
    disabled; efi_image=False drops the EFI image (legacy marked last); device sets the
    legacy PCI ID while the data images keep the GA10x stamp 0x2200.
    """
    ampere = family == 'ampere'
    device, default = (device or 0x2204, b'94.02.42.00.11') if ampere else (0x28B0, b'95.07.47.00.19')
    version = version or default
    chain_size, bank_size = 11264, 12288
    output = bytearray(b'\xff' * (copies * bank_size) + tail)
    legacy, efi, meta, data = prefix, prefix + 2048, prefix + 2560, prefix + 3072
    b = bytearray(b'\x00' * chain_size)
    for start, size, signature, code, dev, last in (
        (0, 2048, b'\x55\xaa', 0, device, 0),
        (2048, 512, b'\x55\xaa', 3, device, 0x80),
        (2560, 512, b'VN', 0xE0, 0x2200 if ampere else device & 0xFF80, 0),
        (3072, 8192, b'VN', 0xE0, 0x2200 if ampere else device & 0xFF80, 0x80)):
        b[start:start + 2] = signature
        struct.pack_into('<H', b, start + 24, 32)
        h = start + 32
        b[h:h + 4] = b'PCIR' if code in (0, 3) else b'NPDS'
        struct.pack_into('<HHHH', b, h + 4, 0x10DE, dev, 0, 24)
        struct.pack_into('<H', b, h + 16, size // 512)
        b[h + 20:h + 22] = bytes((code, last))
        b[start + size - 16:start + size] = b'\xff' * 16
    bit = 128
    b[bit:bit + 6] = b'\xff\xb8BIT\x00'
    b[bit + 8:bit + 11] = bytes((12, 6, 2))
    b[bit + 11] = -sum(b[bit:bit + 12]) & 255
    struct.pack_into('<BBHH', b, bit + 12, ord('P'), 2, 252 if family == 'ada' else 0xE8, 256)
    struct.pack_into('<BBHH', b, bit + 18, ord('C'), 2, 12, 600)
    b[700:700 + len(version)] = version
    power, vfe, profiles, clocks, rail, channels = (8900 if policies else 5200), 3136, 6000, 7600, 1000, 8000
    def pointer(at):
        return at if at < 2048 else at - 512
    for off, at in ((0x2C, power), (0x68, rail), (0x20, vfe)):
        struct.pack_into('<I', b, 256 + off, pointer(at))
    if family == 'ada':
        struct.pack_into('<I', b, 256 + 0xF4, pointer(profiles))
        # Power channel table (P+0x3c): channel 0 is the total-board sum (class 2, rail 0xf5).
        struct.pack_into('<I', b, 256 + 0x3C, pointer(channels))
        b[channels:channels + 6] = bytes.fromhex('20 06 1a 20 2e 20')
        b[channels + 6:channels + 14] = bytes.fromhex('02 f5 00 1b b7 00 00 10')
        for index, entry in (ADA_CHANNELS.items() if policies else ()):
            at = channels + 6 + 26 * index
            b[at:at + len(bytes.fromhex(entry))] = bytes.fromhex(entry)
    if ampere:
        struct.pack_into('<I', b, 256 + 0x3C, pointer(channels))
        b[channels:channels + 6] = bytes.fromhex('20 06 16 20 2e 20')
        b[channels + 6:channels + 14] = bytes.fromhex('02 f5 00 1b b7 00 00 10')
        for index, entry in (AMPERE_CHANNELS.items() if policies else ()):
            at = channels + 6 + 22 * index
            b[at:at + len(bytes.fromhex(entry))] = bytes.fromhex(entry)
    struct.pack_into('<I', b, 608, pointer(clocks))
    hs, stride = (({0x5B: 0x34, 0x4B: 0x2C}.get(power_variant, 0x32), power_variant) if family == 'ada' else
                  {0x43: (0x2C, 0x43), 0x32: (0x32, 0x47)}.get(power_variant, (0x2C, 0x47)))
    count = 20 if policies else 3
    b[power:power + 4] = bytes((0x30, hs, stride if not unknown else stride - 1, count))
    b[power + 10] = 2
    if notebook:
        b[power + 10:power + 14] = bytes((0xFF, 0xFF, 0xFF, 2))
    for i in range(count):
        row = power + hs + stride * i
        identity, limits = (ADA_POLICY_ROWS if family == 'ada' else AMPERE_POLICY_ROWS).get(
            i, ({0: 1}, (30000, 70000, 70000))) if policies else ({0: 1}, (30000, 70000, 70000))
        if policies and i != 2 and (i in (0, 1, 3, 4, 6, 7, 11, 12, 14, 15, 17, 18, 19) if family == 'ada' else
                                    i not in AMPERE_POLICY_ROWS):
            identity, limits = {}, (0, 0, 0)
        for at, value in identity.items():
            b[row + at] = value
        struct.pack_into('<III', b, row + 2, *limits)
    b[profiles:profiles + 10] = bytes.fromhex('10 0a 05 04 07 08 01 10 09 08')
    b[clocks:clocks + 9] = bytes.fromhex('40 0d 0f 0a 03 01 03 e8 03' if family == 'ada' else
                                         f'40 0c 0d 0a 03 {rails:02x} 03 e8 03')
    # Rows follow the GV HAL shape: usage, programming range, offsets, ordering
    # byte, fixed ffff and a rail sub-entry (type, programming range); Ampere has
    # one sub-entry per rail (GPC on rail 0, the others on the last rail) and VID type 2.
    usage, ordering = (1, 1, 1, 1, 1, 1, 0, 1, 1, 1), (0x13, 0x24, 0x62, 0x35, 0x71, 0x46, 0xFF, 0x80, 0x08, 0x57)
    types = (1, 1, 1, 2, 2, 1, 0, 1, 2, 2) if family == 'ada' else (1, 1, 1, 2, 2, 2, 0, 1, 2, 2)
    for i in range(10):
        row = clocks + (13 + 18 * i if family == 'ada' else 12 + (13 + 3 * rails) * i)
        first, last = (7, 11) if i == 2 else (i, i)
        b[row:row + 3] = bytes((usage[i], first, last))
        struct.pack_into('<hh', b, row + 3, -1000, 3000)
        b[row + 7:row + 11] = bytes((ordering[i], 0, 0xFF, 0xFF))
        if family == 'ada':
            b[row + 15:row + 18] = bytes((types[i], first, last))
        elif types[i]:
            sub = row + 13 + 3 * (0 if i == 0 else rails - 1)
            b[sub:sub + 3] = bytes((types[i], first, last) if types[i] == 1 else (2, 1, 0xFF))
            for other in range(rails):
                if row + 13 + 3 * other != sub:
                    b[row + 13 + 3 * other:row + 16 + 3 * other] = b'\x00\xff\xff'
    if ampere:
        # Rails 20/05/11: rail 0 REL 2, ALT 3, VMIN 4, OV 5; rail 1 REL 0, ALT 1, VMIN 6, OV 7.
        b[rail:rail + 5] = bytes((0x20, 5, 0x11, rails, rails - 1))
        for i, (rel_at, alt_at, vmin_at, ov_at) in enumerate(((2, 3, 4, 5), (0, 1, 6, 7))[:rails]):
            row = rail + 5 + 0x11 * i
            struct.pack_into('<I', b, row, 750000)
            b[row + 4:row + 7], b[row + 11] = bytes((rel_at, alt_at, ov_at)), vmin_at
        b[vfe:vfe + 9] = bytes.fromhex('30 09 19 32 18 08 32 0f 28')
        b[vfe + 9 + 11 * 25] = 3  # variable 11: sensed temperature
        base = vfe + 9 + 25 * 50
        for index, kind, value in ((2, 1, 1081250), (3, 1, 1100000), (5, 1, 1100000), (4, 4, 0),
                                   (0, 1, 1081250), (1, 1, 1100000), (7, 1, 1100000), (6, 4, 0)):
            eq = base + 24 * index
            b[eq:eq + 3] = bytes((kind, 0x0B if index in (0, 1, 2, 3) else 0x0A, 0xFF))
            if kind == 1:  # constant quadratic: minimum = maximum = c0, c1 = c2 = 0
                struct.pack_into('<fffff', b, eq + 3, value, value, value, 0, 0)
            b[eq + 23] = 2
        if fans:
            ada_fan_tables(b, fans, pointer, speed=fan_speed)
    if family == 'ada':
        b[rail:rail + 5] = bytes.fromhex('20 05 1f 01 00')
        # REL, ALT (absent unless alt), OV, and VMIN = OV - 1 at row byte 11.
        b[rail + 9:rail + 12] = bytes((2, 3, 5)) if alt else bytes((2, 0xFF, 4))
        b[rail + 16] = 4 if alt else 3
        b[vfe:vfe + 5] = bytes.fromhex('30 0b 19 32 19')
        b[vfe + 5] = 8  # equation count (u16 at header bytes 5 and 10)
        b[vfe + 11] = 3
        b[vfe + 20] = 1
        base = vfe + 11 + 25 * 50
        rel_eq = {'constant': ((955000, 955000), (955000, 0, 0))}.get(rel, ((915000, 955000), (1440000, -5000, 0)))
        equations = [(2, 3 if rel == 'compare' else 1, *rel_eq), ((5 if alt else 4), 1, (1200000, 1200000), (1200000, 0, 0))]
        if alt:
            equations.append((3, 1, (935000, 975000), (1460000, -5000, 0)))
        for index, kind, (lo, hi), coefficients in equations:
            eq = base + index * 25
            b[eq:eq + 3] = bytes((kind, 0, 0xFF))
            struct.pack_into('<ff', b, eq + 3, lo, hi)
            struct.pack_into('<fff', b, eq + 11, *coefficients)
            b[eq + 23:eq + 25] = bytes((2, 0xFF))
        if rel == 'chained':
            b[base + 2 * 25 + 2], b[base + 2 * 25 + 24] = 6, 0  # REL continues in equation 6
            b[base + 6 * 25:base + 6 * 25 + 3] = bytes((1, 0, 0xFF))
            b[base + 6 * 25 + 23:base + 6 * 25 + 25] = bytes((2, 0xFF))
        if rel == 'shared':
            b[base + 6 * 25:base + 6 * 25 + 3] = bytes((1, 0, 2))  # equation 6 links to REL
            b[base + 6 * 25 + 23:base + 6 * 25 + 25] = bytes((2, 0))
        eq = base + (4 if alt else 3) * 25  # VMIN: fixed-point equation
        b[eq:eq + 3] = bytes((4, 0, 0xFF))
        b[eq + 23:eq + 25] = bytes((2, 0xFF))
        if fans:
            ada_fan_tables(b, fans, pointer)
    images = ((0, 2048), (2048, 512), (2560, 512), (3072, 8192))
    if not efi_image:
        # Legacy image marked last and followed directly by the data images.
        b = b[:2048] + b[2560:] + b'\xff' * 512
        b[32 + 21] = 0x80
        images = ((0, 2048), (2048, 512), (2560, 8192))
    for start, size in images:
        b[start + size - 1] = -sum(b[start:start + size - 1]) & 255
    for i in range(copies):
        at = i * bank_size + prefix
        output[at:at + chain_size] = b
    return bytes(output)


def ada_fan_tables(b, fans, pointer, speed=True):
    """Ada cooler/policy/mapping/control/speed tables (two entries each) between VFE and power.

    fans: 1 (second entry not stored) or 2 active channels; 3: one active and a stored second channel;
    negative: laptop layout (no list, no enables). speed=False leaves every speed entry disabled
    (as on the Ampere RTX 3080/3090 boards).
    """
    tables = {'cooler': (0x58, 4600, bytes((0x10, 6, 0x1A, 2)), 6, 0x1A),
              'policy': (0x5C, 4660, bytes((0x20, 4, 0x33, 8)), 4, 0x33),
              'mapping': (0x64, 5072, bytes((0x10, 4, 5, 2)), 4, 5),
              'control': (0xDC, 5086, bytes((0x10, 4, 0x0D, 2)), 4, 0x0D),
              'speed': (0xE0, 5116, bytes((0x10, 4, 6, 2)), 4, 6)}
    active = 0 if fans < 0 else 1 if fans == 3 else fans
    entry = {}
    for name, (offset, at, header, header_size, size) in tables.items():
        struct.pack_into('<I', b, 256 + offset, pointer(at))
        b[at:at + 4] = header
        entry[name] = lambda i, at=at, header_size=header_size, size=size: at + header_size + size * i
    cooler = tables['cooler'][1]
    b[cooler + 4:cooler + 6] = bytes(i if i < active else 0xFF for i in range(2))
    for i in range(2):
        on = i < active
        row = entry['cooler'](i)
        b[row] = 2 if on else 0
        b[row + 4:row + 6], b[row + 10] = (bytes.fromhex('3d 02'), 9) if i == 0 else (bytes.fromhex('d2 02'), 0xD1)
        struct.pack_into('<I', b, row + 11, 27000)
        b[row + 2:row + 4] = bytes((20, 100))  # level limits (%)
        struct.pack_into('<HH', b, row + 14, 1000, 3300)  # speed limits (RPM)
        if fans < 0:
            continue
        b[entry['policy'](i)] = int(on)
        # Curve levels 20/50/100 % and three (1/32 C, RPM) points that reach the row limits.
        b[entry['policy'](i) + 14:entry['policy'](i) + 17] = bytes((20, 50, 100))
        struct.pack_into('<6H', b, entry['policy'](i) + 18, 55 * 32, 1000, 70 * 32, 2000, 85 * 32, 3300)
        b[entry['mapping'](i):entry['mapping'](i) + 2] = bytes((int(on), i))
        control = entry['control'](i)
        # As on the RTX 2000 Ada, a one-channel layout keeps an unstored second entry.
        b[control], b[control + 2], b[control + 5] = int(on), i, 0x06 if fans == 1 and i else 0x0C | 1 << i
        b[entry['speed'](i):entry['speed'](i) + 2] = bytes((int(on and speed), i))
        struct.pack_into('<H', b, entry['speed'](i) + 2, 2295)  # speed value (RPM), as on the RTX 4090
    if fans > 0:
        for i, start in ((2, 98), (3, 92)):  # enabled policy entries that are not per channel, same curve
            b[entry['policy'](i)] = 1
            b[entry['policy'](i) + 14:entry['policy'](i) + 17] = bytes((20, 50, 100))
            struct.pack_into('<6H', b, entry['policy'](i) + 18, start * 32, 1000, (start + 5) * 32, 2000,
                             (start + 10) * 32, 3300)


class StructureTests(unittest.TestCase):
    def test_variable_archive_sizes_and_duplicate_chain_normalization(self):
        for copies, tail in ((1, b''), (2, b'BOARD-UNIQUE-123'), (3, b'PRIVATE')):
            with self.subTest(copies=copies):
                image = from_bytes(synthetic_rom(copies=copies, tail=tail))
                report = inspect_image(image)
                self.assertTrue(report['integrity']['valid'])
                self.assertEqual(report['duplicate_chain_count'], copies)
                payload = normalize(image)
                expected = image.blob if copies == 1 else image.blob[512:11776]
                self.assertEqual(payload.blob, expected)
                self.assertTrue(inspect_image(payload)['integrity']['valid'])
                self.assertEqual(len(backend(payload).chains), 1)

    def test_nvgi_bank_envelope_is_preserved_and_boundary_is_derived(self):
        blob = bytearray(synthetic_rom(copies=2))
        blob[:4] = b'NVGI'
        blob[12288:12292] = b'NVGI'
        blob[12288 + 8] = 0x31  # bank metadata is allowed to differ
        payload = normalize(from_bytes(blob))
        self.assertEqual(payload.blob, bytes(blob[:12288]))
        self.assertEqual(normalize(payload).blob, payload.blob)

    def test_unknown_bytes_and_board_serial_are_not_format_pins(self):
        image = from_bytes(synthetic_rom(tail=b'1234567890123-any-other-board-record'))
        self.assertTrue(inspect_image(image)['integrity']['valid'])
        self.assertEqual(inspect_image(image)['capabilities']['edit']['status'], 'supported')

    def test_unsupported_raw_inspection_remains_available(self):
        report = inspect_image(from_bytes(b'unknown ROM'))
        self.assertIsNone(report['format'])
        self.assertEqual(report['capabilities']['inspect']['status'], 'supported')
        self.assertEqual(report['capabilities']['edit']['status'], 'unsupported')
        self.assertIsNone(report['integrity']['valid'])

    def test_excluded_hopper_datacenter_blackwell_and_unknown_ids(self):
        for device in (0x2330, 0x2901, 0x2941, 0x3182, 0x2E12, 0xFFFF):
            blob = bytearray(synthetic_rom())
            struct.pack_into('<H', blob, 512 + 38, device)
            report = inspect_image(from_bytes(blob))
            self.assertFalse(report['architecture']['in_scope'])
            self.assertEqual(report['capabilities']['edit']['status'], 'unsupported')
            with self.assertRaises(VbiosError) as exc:
                normalize(from_bytes(blob))
            self.assertEqual(exc.exception.code, 'UNSUPPORTED_ARCHITECTURE')

    def test_server_branding_does_not_exclude_gb20x_architecture(self):
        from nvidia_vbios.rom.architecture import architecture
        for device in (0x2BB5, 0x2C3A, 0x2C77, 0x2D79):
            report = architecture(device, ['98.02.6A.00.03'])
            self.assertTrue(report['in_scope'])
            self.assertEqual(report['family'], 'blackwell-gb20x')
        self.assertTrue(architecture(0x20B0, ['92.00.45.00.03'])['in_scope'])
        self.assertTrue(architecture(0x20B0, ['92.00.45.00.03'])['bios_family_consistent'])
        self.assertFalse(architecture(0x20B0, ['94.00.00.00.01'])['bios_family_consistent'])

    def test_architecture_requires_pci_and_bios_agreement(self):
        blob = synthetic_rom().replace(b'95.07.47.00.19', b'98.07.47.00.19')
        report = inspect_image(from_bytes(blob))
        self.assertEqual(report['diagnostics'][-1]['code'], 'ARCHITECTURE_MISMATCH')

    def test_truncated_image_and_npds_identity_fail_closed(self):
        for mode in ('truncate', 'identity'):
            blob = bytearray(synthetic_rom())
            if mode == 'truncate':
                struct.pack_into('<H', blob, 512 + 3072 + 32 + 16, 0xFFFF)
            else:
                struct.pack_into('<H', blob, 512 + 3072 + 32 + 6, 0x2B80)
            report = inspect_image(from_bytes(blob))
            self.assertEqual(report['capabilities']['edit']['status'], 'unsupported')
            self.assertTrue(report['diagnostics'])

    def test_unstamped_efi_identity_is_accepted_and_foreign_identities_are_rejected(self):
        efi = 512 + 2048
        for identity, accepted in (((0, 0), True), ((0x10DE, 0), True), ((0x10DE, 0x28B0), True),
                                   ((0, 0x28B0), False), ((0x10DE, 0x2882), False), ((0x1002, 0), False)):
            blob = bytearray(synthetic_rom(copies=2))
            for bank in (0, 12288):
                struct.pack_into('<HH', blob, bank + efi + 32 + 4, *identity)
                blob[bank + efi + 511] = 0
                blob[bank + efi + 511] = -sum(blob[bank + efi:bank + efi + 512]) & 255
            image = from_bytes(blob)
            with self.subTest(identity=identity):
                if accepted:
                    self.assertTrue(inspect_image(image)['integrity']['valid'])
                    self.assertEqual(normalize(image).blob, bytes(blob[512:11776]))
                else:
                    with self.assertRaises(VbiosError) as exc:
                        backend(image)
                    self.assertIn('EFI image PCI identity', str(exc.exception))

    def test_duplicate_bit_token_is_rejected(self):
        blob = bytearray(synthetic_rom())
        blob[512 + 128 + 18] = ord('P')
        pci, _, _ = scan_images(blob)
        with self.assertRaises(VbiosError):
            parse_bit(blob, pci[0])

    def test_unknown_table_variant_refuses_only_affected_fields(self):
        report = inspect_image(from_bytes(synthetic_rom(unknown=True)))
        self.assertNotIn('power_max_w', {f['key'] for f in report['fields']})
        self.assertIn('nvvdd_rel_max_mv', {f['key'] for f in report['fields']})
        self.assertTrue(report['diagnostics'])




def synthetic_blackwell(*, shared_objects=False, rails=2, clock_subsize=2, power_topology=False, fans=False):
    """Object directory with BIT-referenced tables and computed SHA384 hashes.

    rails=1 and clock_subsize=1 give the single-rail Workstation layout.
    power_topology adds empty power channel (P+0x3c) and device (P+0x28) tables;
    fans adds a fan cooler table (P+0x58) with two active 27 kHz channels.
    """
    import hashlib
    legacy, efi, meta, extended = 512, 2560, 3072, 11264
    b = bytearray(b'\x00' * 28160 + b'UNKNOWN-ARCHIVE-IDENTITY')
    for start, size, magic, dev, code, last in (
        (legacy, 2048, b'PCIR', 0x2B85, 0, 0),
        (efi, 512, b'PCIR', 0, 3, 0x80),
        (meta, 8192, b'PCIR', 0x2B80, 0xE0, 0),
        (extended, 16384, b'NPDS', 0x2B80, 0xE0, 0x80)):
        ptr = 0x1800 if start == meta else 32
        b[start:start + 2] = b'VN' if magic == b'NPDS' else b'\x55\xaa'
        struct.pack_into('<H', b, start + 24, ptr)
        h = start + ptr
        b[h:h + 4] = magic
        struct.pack_into('<HHHH', b, h + 4, 0 if start == efi else 0x10DE, dev, 0, 24)
        struct.pack_into('<H', b, h + 16, size // 512)
        b[h + 20:h + 22] = bytes((code, last))
    bit = legacy + 128
    b[bit:bit + 6] = b'\xff\xb8BIT\x00'
    b[bit + 8:bit + 11] = bytes((12, 6, 2))
    b[bit + 11] = -sum(b[bit:bit + 12]) & 255
    struct.pack_into('<BBHH', b, bit + 12, ord('P'), 2, 252, 256)
    struct.pack_into('<BBHH', b, bit + 18, ord('C'), 2, 12, 600)
    version = b'98.02.18.00.01'
    b[legacy + 700:legacy + 700 + len(version)] = version
    clocks, power, vfe, rail, profiles = 11776, 12288, 16384, legacy + 1000, 14592
    def pointer(at):
        return at - legacy if at < efi else at - legacy - 512
    for off, at in ((0x2C, power), (0x68, rail), (0x20, vfe), (0xF4, profiles)):
        struct.pack_into('<I', b, legacy + 256 + off, pointer(at))
    struct.pack_into('<I', b, legacy + 608, pointer(clocks))
    b[clocks:clocks + 6] = bytes((0x50, 13, 15, 9, 3, clock_subsize))
    ranges = ((13, 13), (17, 17), (8, 12), (15, 15), (14, 14), (16, 16), (22, 26), (0, 7), (18, 21))
    descriptors = (0x43, 0x84, 0x182, 0xC5, 0x106, 0x147, 8, 0x200, 0x1C1)
    for i, ((first, last), identity) in enumerate(zip(ranges, descriptors)):
        row = clocks + 13 + (15 + 3 * clock_subsize) * i
        b[row:row + 3] = bytes((2, first, last))
        struct.pack_into('<hh', b, row + 3, -1000, 3000)
        struct.pack_into('<H', b, row + 9, identity)
    b[power:power + 4] = bytes((0x40, 0x38, 0x66, 20))
    for i in range(20):
        row = power + 0x38 + 0x66 * i
        b[row] = {2: 1, 7: 13, 8: 12, 9: 11}.get(i, 0)
        struct.pack_into('<III', b, row + 13, 30000, 70000, 100000)
    b[profiles:profiles + 10] = bytes.fromhex('10 0a 05 04 07 08 01 10 09 08')
    row = profiles + 0xFE
    b[row] = 1
    for j, (policy, field) in enumerate((p, f) for p in (2, 7, 8, 9) for f in (0, 1)):
        entry = row + 1 + j * 9
        b[entry] = 1
        struct.pack_into('<II', b, entry + 1, policy | field << 8, 100000 if field == 0 else 70000)
    b[rail:rail + 5] = bytes((0x30, 5, 0x41, rails, 0))
    b[vfe:vfe + 5] = bytes((0x30, 14, 29, 255, 25))
    equations = vfe + 14 + 29 * 255
    for i in range(rails):
        row = rail + 5 + 0x41 * i
        b[row:row + 2] = bytes((1, i + 1))
        struct.pack_into('<H', b, row + 0x0D, i)
        eq = equations + 25 * i
        b[eq] = 1
        struct.pack_into('<ff', b, eq + 3, 900000, 1000000)
        b[eq + 23] = 2
    directory = meta + 0x500
    objects = [(0xFB, None, 32), (0xBE, meta + 0x1800, 24), (3, clocks, 512),
               (0x13, power, 4096), (0x14, vfe, 8192)]
    if power_topology:
        channels, devices = 24576, 25600
        for off, at in ((0x3C, channels), (0x28, devices)):
            struct.pack_into('<I', b, legacy + 256 + off, pointer(at))
        b[channels:channels + 4] = bytes((0x20, 0x11, 0x1A, 0x20))
        b[devices:devices + 4] = bytes((0x30, 0x18, 0x19, 0x0B))
        objects += [(0x16, channels, 0x11 + 0x1A * 0x20), (0x12, devices, 0x18 + 0x19 * 0x0B)]
    if fans:
        coolers = 26112
        struct.pack_into('<I', b, legacy + 256 + 0x58, pointer(coolers))
        b[coolers:coolers + 9] = bytes((0x10, 9, 0x1A, 4, 0, 1, 0xFF, 0xFF, 0))
        # Like the Astral XOC: rows 0/1 active, row 2 its own idle channel, row 3 a copy of row 0.
        for i, (gpio, tach) in enumerate(((0x3D, 0x09), (0xD2, 0xD1), (0xFB, 0xFA), (0x3D, 0x09))):
            row = coolers + 9 + 0x1A * i
            b[row:row + 6] = bytes((2 if i < 2 else 0, 0, 0x14, 0x64, gpio, 2))
            b[row + 10] = tach
            b[row + 11:row + 14] = (27000).to_bytes(3, 'little')
            struct.pack_into('<HH', b, row + 14, 1050, 3500)  # speed limits (RPM), as on the RTX 5080
        objects.append((0x1D, coolers, 9 + 0x1A * 4))
        # Policy (P+0x5c) and mapping (P+0x64) entries of the same channels.
        policy, mapping = 26240, 26816
        for off, at in ((0x5C, policy), (0x64, mapping)):
            struct.pack_into('<I', b, legacy + 256 + off, pointer(at))
        b[policy:policy + 4] = bytes((0x20, 4, 0x33, 0x0B))
        b[mapping:mapping + 4] = bytes((0x10, 4, 5, 4))
        for i, (enable, stored, row) in enumerate(((1, 1, 0), (1, 1, 1), (0, 1, 2), (0, 0, 0))):
            b[policy + 4 + 0x33 * i:policy + 6 + 0x33 * i] = bytes((enable, stored))
            b[mapping + 4 + 5 * i:mapping + 9 + 5 * i] = bytes((enable, row, 0x0A, 0x10, 0x27))
        # Curves: levels 20/50/100 % and three (1/32 C, RPM) points reaching the row limits, on the
        # channel entries and on entries 4/5, enabled past the cooler rows as on every source.
        # Bytes 30..33 hold the fan-stop temperatures 43/50 C (1/32 C), as on the RTX 5080.
        for i in range(6):
            entry, start = policy + 4 + 0x33 * i, 50 if i < 4 else 93
            if i >= 4:
                b[entry] = 1
            b[entry + 14:entry + 17] = bytes((20, 50, 100))
            struct.pack_into('<6H', b, entry + 18, start * 32, 1050, (start + 5) * 32, 2200, (start + 10) * 32, 3500)
            struct.pack_into('<HH', b, entry + 30, 43 * 32, 50 * 32)
        objects += [(0x1E, policy, 4 + 0x33 * 0x0B), (0x20, mapping, 4 + 5 * 4)]
        # Control (P+0xdc) and speed (P+0xe0) entries: channels 0-2 stored, 3 a placeholder.
        control, speed = 26848, 26912
        for off, at in ((0xDC, control), (0xE0, speed)):
            struct.pack_into('<I', b, legacy + 256 + off, pointer(at))
        b[control:control + 4] = bytes((0x10, 4, 0x0D, 4))
        b[speed:speed + 4] = bytes((0x10, 4, 6, 4))
        for i in range(4):
            enable, stored = (1 if i < 2 else 0), i < 3
            b[control + 4 + 0x0D * i:control + 10 + 0x0D * i] = bytes(
                (enable, 0, i if stored else 0xFF, 0xC8, 0, 0x30 | 1 << i if stored else 0))
            b[speed + 4 + 6 * i:speed + 10 + 6 * i] = bytes((enable, i, 0xFC, 8, 0x24, 0) if stored else (0, 0xFF, 0, 0, 0, 0))
        objects += [(0x80, control, 4 + 0x0D * 4), (0x83, speed, 4 + 6 * 4)]
    count = len(objects) + (1 if shared_objects else 0)
    base = directory + 16 + count * 60
    objects[0] = (0xFB, base, 32)
    if shared_objects:
        # Hash the same clock table twice with a different object ID. The table
        # owner must remain unambiguous at editable bytes, so use an overlapping
        # prefix in object 13 instead, away from its fields.
        objects.append((0x77, power, 32))
    struct.pack_into('<IIII', b, directory, 3, 16, count, 0x2B85)
    for i, (oid, at, size) in enumerate(objects):
        h = directory + 16 + 60 * i
        struct.pack_into('<III', b, h, oid, at - base, size)
        b[h + 12:h + 60] = hashlib.sha384(b[at:at + size]).digest()
    b[meta + 0x209:meta + 0x239] = hashlib.sha384(b[directory:base]).digest()
    for start, end in ((legacy, efi), (efi, meta), (meta, extended), (extended, extended + 16384)):
        b[end - 1] = -sum(b[start:end - 1]) & 255
    return bytes(b)


class BlackwellStructureTests(unittest.TestCase):
    def test_small_synthetic_object_directory_size_is_not_pinned(self):
        for shared in (False, True):
            image = from_bytes(synthetic_blackwell(shared_objects=shared))
            report = inspect_image(image)
            self.assertEqual(report['format'], 'gb20x-object-directory-v3')
            self.assertTrue(report['integrity']['valid'])
            self.assertEqual(report['capabilities']['edit']['status'], 'supported')

    def test_bad_object_hash_is_readable_but_read_only(self):
        blob = bytearray(synthetic_blackwell())
        blob[16384 + 100] ^= 1
        report = inspect_image(from_bytes(blob))
        self.assertFalse(report['integrity']['valid'])
        self.assertEqual(report['capabilities']['edit']['status'], 'unsupported')
        self.assertIn(0x14, report['integrity']['bad_object_ids'])


if __name__ == "__main__":
    unittest.main()
