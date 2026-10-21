"""Read-only memory view: configurations, clock bands, timing entries and the GB20x board profile."""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import unittest

from nvidia_vbios.rom import from_bytes, inspect_image, load
from nvidia_vbios.rom.memory import (board_profile, compare, memory_report, PROFILE_COLUMNS, PROFILE_FIELDS,
                                     PROFILE_LISTS, PROFILE_RECORD)
from test_rom_formats import synthetic_blackwell, synthetic_rom


def profile_object(shift=0, *, arrays=True, flags=True):
    """Synthetic object 0x89 bytes: both signatures, records B1/B2 counting up, the arrays and flag bytes."""
    data = bytearray(0x3000)
    group = 0x6E0 + shift
    header = group + 0x8B0
    data[group:group + 4] = bytes.fromhex('12 12 98 98')
    data[header:header + 4] = bytes.fromhex('95 28 94 28')
    data[header + 0x2E:header + 0x34] = bytes.fromhex('00 29 01 00 00 03')
    b1 = header + 0x3A
    data[b1:b1 + 2 * PROFILE_RECORD] = bytes(i % 251 for i in range(2 * PROFILE_RECORD))
    if arrays:
        struct.pack_into('<8H', data, group - 0x110, 1000, 1000, 1000, 216, 300, 300, 300, 0)
        data[group - 0x100:group - 0xFC] = bytes.fromhex('21 43 34 12')
    end = b1 + 2 * PROFILE_RECORD
    if flags:
        data[end + 2:end + 6] = bytes.fromhex('23 61 81 29')
        data[end + 0x0A:end + 0x10] = bytes.fromhex('01 00 48 28 22 29')
    return bytes(data), header, b1


class MemoryTableTests(unittest.TestCase):
    def setUp(self):
        self.blob = synthetic_rom(memory=True)
        self.report = memory_report(from_bytes(self.blob, 'memory.rom'), raw=True)

    def test_configurations_name_the_column_vendor_and_only_type_9(self):
        items = self.report['configurations']['items']
        self.assertEqual([(i['strap'], i['column'], i['vendor'], i['vendor_code'], i['type_code'], i['type'],
                           i['type_guess']) for i in items],
                         [(0, 0, 'Samsung', '0x1', '0x9', 'GDDR6', None), (1, 1, 'SK hynix', '0x6', '0xa', None, 'GDDR6X'),
                          (2, 1, 'Micron', '0xf', '0xd', None, 'GDDR7'), (5, 3, None, '0x2', '0x3', None, None)])
        self.assertIn('board', self.report['strap_note'])

    def test_bands_index_timings_by_column_not_strap(self):
        bands = self.report['bands']
        self.assertEqual(bands['columns'], [0, 1, 3])
        self.assertEqual([(b['min_mhz'], b['max_mhz'], b['timing_index']) for b in bands['items']],
                         [(0, 540, {'0': 0, '1': 2, '3': None}), (541, 5000, {'0': 2, '1': 3, '3': None}),
                          (5001, 16383, {'0': 1, '1': 4, '3': None})])
        # The synthetic C token holds no clock programming table: no stock clock is marked.
        self.assertIsNone(bands['stock_points'])
        self.assertIn('stock_points_reason', bands)
        # Each band carries its own bytes and the sub-entries of the configurations' columns.
        first = bands['items'][0]
        self.assertEqual((bands['column_count'], first['raw']), (4, '00001c0200000000'))
        self.assertEqual(first['sub_entries'], {'0': '0000', '1': '0200', '3': 'ff00'})
        self.assertNotIn('outside_table', bands)

    def test_placeholder_bands_and_columns_outside_the_table(self):
        changed = bytearray(self.blob)
        bands = int(self.report['bands']['offset'], 16) + 6
        changed[bands + 32:bands + 36] = bytes(4)                           # band 2 -> 0-0 MHz
        changed[int(self.report['configurations']['offset'], 16) + 7 + 6 * 3 + 1] = 0x25   # strap 5 -> column 5
        report = memory_report(from_bytes(bytes(changed), 'changed.rom'))
        self.assertEqual((report['bands']['columns'], report['bands']['outside_table']), ([0, 1], [5]))
        self.assertEqual(report['bands']['items'][2]['timing_index'], {'0': 1, '1': 4})
        # No clock falls in a 0-0 MHz band: its entries (1 and 4) are not in use.
        self.assertEqual([t['index'] for t in report['timings']['items']], [0, 2, 3])
        changed[bands + 32] = 1                                             # band 2 -> 1-0 MHz, still unused
        result = compare(report, memory_report(from_bytes(bytes(changed), 'other.rom')))
        self.assertEqual(result['sections']['bands']['status'], 'identical')

    def test_timing_entries_decode_controller_cycles_with_raw_bytes(self):
        timings = self.report['timings']
        self.assertEqual((timings['unit'], timings['entry_size'], timings['count']), ('controller cycles', 16, 5))
        self.assertEqual(timings['confidence'], {'tRC': 'inferred', 'tRAS': 'inferred', 'tRP': 'inferred',
                                                 'tRFC': 'probable', 'CL': 'tentative', 'tWR': 'tentative'})
        entries = {t['index']: t for t in timings['items']}
        self.assertEqual(sorted(entries), [0, 1, 2, 3, 4])
        self.assertEqual(entries[1]['decoded'], dict(tRC=79, tRAS=53, tRP=26, tRFC=253, CL=35, tWR=42))
        self.assertEqual(len(bytes.fromhex(entries[1]['raw'])), 16)
        self.assertTrue(entries[1]['raw'].startswith('4ffd6a1aa3056879000f2acc'))
        self.assertNotIn('WL', entries[1]['decoded'])
        for entry in entries.values():
            self.assertNotIn('ns', json.dumps(entry))

    def test_tables_are_hashed_and_the_profile_belongs_to_gb20x(self):
        self.assertEqual([t['table'] for t in self.report['tables']],
                         ['memory configurations', 'memory clock bands', 'timings'])
        for table in self.report['tables']:
            at = int(table['offset'], 16)
            self.assertEqual(table['sha256'], hashlib.sha256(self.blob[at:at + table['size']]).hexdigest())
        self.assertEqual(self.report['board_profile']['status'], 'not-applicable')

    def test_report_is_read_only(self):
        image = from_bytes(self.blob, 'memory.rom')
        fields = inspect_image(image)['fields']
        memory_report(image, raw=True)
        self.assertEqual(image.blob, self.blob)
        self.assertEqual(inspect_image(image)['fields'], fields)
        self.assertNotIn('memory', inspect_image(image))

    def test_missing_or_damaged_tables_report_a_status_never_an_exception(self):
        plain = memory_report(from_bytes(synthetic_rom(), 'plain.rom'))
        self.assertEqual(plain['status'], 'recognized')
        for section in ('configurations', 'bands', 'timings'):
            self.assertEqual(plain[section]['status'], 'unrecognized')
            self.assertTrue(plain[section]['reason'])
        blackwell = memory_report(from_bytes(synthetic_blackwell(), 'gb.rom'), raw=True)
        self.assertEqual(blackwell['board_profile'], {'status': 'unrecognized', 'reason': 'no object 0x89'})
        self.assertEqual(memory_report(from_bytes(b'not a rom', 'x.rom'))['status'], 'unrecognized')
        at = int(self.report['timings']['offset'], 16)
        for offset, value in ((int(self.report['configurations']['offset'], 16), 0x11), (at, 0x21), (at + 2, 4)):
            damaged = bytearray(self.blob)
            damaged[offset] = value
            report = memory_report(from_bytes(bytes(damaged), 'damaged.rom'))
            self.assertIn('unrecognized', {report[s]['status'] for s in ('configurations', 'timings')})

    def test_compare_reports_identical_or_differs_per_section(self):
        same = compare(self.report, memory_report(from_bytes(self.blob, 'copy.rom'), raw=True))
        self.assertEqual({name: section['status'] for name, section in same['sections'].items()},
                         dict(configurations='identical', bands='identical', timings='identical', tables='identical',
                              board_profile='not-applicable'))
        changed = bytearray(self.blob)
        changed[int(self.report['timings']['items'][1]['offset'], 16)] += 1      # tRC of entry 1
        result = compare(self.report, memory_report(from_bytes(bytes(changed), 'changed.rom'), raw=True))
        self.assertEqual(result['sections']['timings'], dict(status='differs', count=1, keys=[1], fields=['tRC']))
        self.assertEqual(result['sections']['tables'], dict(status='differs', count=1, keys=['timings']))
        self.assertEqual(result['sections']['configurations']['status'], 'identical')
        self.assertNotIn('better', json.dumps(result))
        plain = compare(self.report, memory_report(from_bytes(synthetic_rom(), 'plain.rom')))
        self.assertEqual(plain['sections']['timings']['status'], 'unavailable')

    def test_compare_bands_by_their_bytes_in_use(self):
        bands = int(self.report['bands']['offset'], 16) + 6
        for at, expected in ((bands + 5, ('differs', [0], ['memory clock bands'])),      # band 0 header
                             (bands + 8 + 1, ('differs', [0], ['memory clock bands'])),  # column 0 sub-entry
                             (bands + 8 + 2 * 2, ('identical', [], ['memory clock bands']))):  # column 2: unused
            with self.subTest(at=at):
                changed = bytearray(self.blob)
                changed[at] ^= 0x40
                result = compare(self.report, memory_report(from_bytes(bytes(changed), 'changed.rom')))['sections']
                self.assertEqual((result['bands']['status'], result['bands']['keys'], result['tables']['keys']),
                                 expected)

    def test_compare_tables_owned_by_an_object_and_tables_without_one(self):
        other = copy.deepcopy(self.report)
        for table in other['tables']:
            table['object'] = '0x0f'
        result = compare(self.report, other)['sections']['tables']
        self.assertEqual((result['status'], result['count']), ('differs', 6))
        self.assertIn('timings (0x0f)', result['keys'])

    def test_compare_with_a_blackwell_profile_is_not_applicable(self):
        other = copy.deepcopy(self.report)
        other['board_profile'] = board_profile(profile_object()[0])
        self.assertEqual(other['board_profile']['status'], 'recognized')
        for a, b in ((self.report, other), (other, self.report)):
            self.assertEqual(compare(a, b)['sections']['board_profile'], {'status': 'not-applicable'})


class BoardProfileTests(unittest.TestCase):
    def test_field_split_covers_the_paired_part_of_a_record(self):
        self.assertEqual(2 * sum(PROFILE_FIELDS), PROFILE_LISTS)
        self.assertEqual(len(PROFILE_FIELDS), 267)
        self.assertLess(PROFILE_LISTS, PROFILE_RECORD)

    def test_recognized_profile_reports_tag_fingerprint_and_raw_columns(self):
        for shift in (0, 0x408, 0x578):
            with self.subTest(shift=shift):
                data, header, b1 = profile_object(shift)
                profile = board_profile(data, 0x1000)
                self.assertEqual((profile['status'], profile['tag'], profile['layout_shift']),
                                 ('recognized', ['0x0029', '0x0003'], f'{shift:#x}'))
                self.assertEqual(profile['offset'], f'{0x1000 + header:#x}')
                column0 = b''.join(bytes.fromhex(f['B1/0']) for f in board_profile(data, raw=True)['fields'])
                self.assertEqual(profile['fingerprint'],
                                 hashlib.sha256(data[header:b1] + column0).hexdigest()[:16])
                self.assertNotIn('fields', profile)
        data, header, b1 = profile_object()
        raw = board_profile(data, raw=True)
        first = raw['fields'][0]
        self.assertEqual((first['offset'], first['size'], first['B1/0'], first['B1/1']), ('0x000', 1, '00', '01'))
        self.assertEqual(first['B2/0'], f'{PROFILE_RECORD % 251:02x}')
        self.assertEqual(len(raw['fields']), len(PROFILE_FIELDS))
        self.assertEqual(raw['records'], {'B1': f'{b1:#x}', 'B2': f'{b1 + PROFILE_RECORD:#x}'})
        self.assertEqual(len(bytes.fromhex(raw['index_lists']['B1'])), PROFILE_RECORD - PROFILE_LISTS)
        self.assertEqual(raw['arrays']['values'], [[1000, 1000, 1000, 216], [300, 300, 300, 0]])
        self.assertEqual(raw['flags']['values'], [1, 0])
        bare = board_profile(profile_object(arrays=False, flags=False)[0], raw=True)
        self.assertEqual((bare['status'], bare['arrays']['status'], bare['flags']['status']),
                         ('recognized', 'unrecognized', 'unrecognized'))

    def test_any_gate_failure_is_unrecognized(self):
        data, header, b1 = profile_object()
        group = header - 0x8B0
        cases = {'corrupted signature': data[:group] + b'\x12\x12\x98\x99' + data[group + 4:],
                 'repeated signature': data[:0x100] + bytes.fromhex('95 28 94 28') + data[0x104:],
                 'other distance': data[:header] + bytes(4) + data[header:header + 4] + data[header + 8:],
                 'unreviewed position': profile_object(0x10)[0],
                 'truncated': data[:b1 + PROFILE_RECORD],
                 'empty': b''}
        for name, damaged in cases.items():
            with self.subTest(name):
                profile = board_profile(damaged, raw=True)
                self.assertEqual(profile['status'], 'unrecognized')
                self.assertTrue(profile['reason'])

    def test_compare_counts_differing_fields_without_ranking_them(self):
        data, header, b1 = profile_object()
        base = {'status': 'recognized', 'tables': [], 'board_profile': board_profile(data, raw=True)}
        changed = bytearray(data)
        changed[b1 + 4] ^= 0xFF                 # field 2 (u16 at +4), column 0 of B1
        changed[b1 + PROFILE_RECORD + 1] ^= 1   # field 0 (u8 at +0), column 1 of B2
        other = {'status': 'recognized', 'tables': [], 'board_profile': board_profile(bytes(changed), raw=True)}
        result = compare(base, other)['sections']['board_profile']
        self.assertEqual((result['status'], result['fields'], result['meaning']), ('differs', 2, 'unknown'))
        self.assertEqual(result['configurations'], {'B1/0': 1, 'B1/1': 0, 'B2/0': 0, 'B2/1': 1})
        self.assertEqual((result['fingerprint'], result['tag']), ('differs', 'identical'))
        self.assertEqual(compare(base, base)['sections']['board_profile']['status'], 'identical')
        self.assertEqual(set(PROFILE_COLUMNS), {'B1/0', 'B1/1', 'B2/0', 'B2/1'})

    def test_compare_covers_every_reported_profile_byte_without_raw(self):
        data, header, b1 = profile_object()
        group = header - 0x8B0

        def section(left, right, raw):
            return compare({'status': 'recognized', 'tables': [], 'board_profile': board_profile(left, raw=raw)},
                           {'status': 'recognized', 'tables': [], 'board_profile': board_profile(right, raw=raw)}
                           )['sections']['board_profile']
        changed = bytearray(data)
        changed[group - 0x110] ^= 1                                     # first array value only
        b2 = bytearray(data)
        b2[b1 + PROFILE_RECORD + 0x500] ^= 1                            # B2 index lists only
        for name, other in (('arrays', bytes(changed)), ('index lists', bytes(b2)),
                            ('one-sided flags', profile_object(flags=False)[0])):
            with self.subTest(name):
                self.assertEqual((section(data, other, False)['status'], section(data, other, True)['status']),
                                 ('differs', 'differs'))
        self.assertEqual(section(data, bytes(changed), True)['arrays'], 'differs')
        self.assertEqual(section(data, bytes(b2), True)['index_lists'], 'differs')
        self.assertEqual(section(data, profile_object(flags=False)[0], True)['flags'], 'unavailable')
        self.assertEqual(section(data, data, False)['status'], 'identical')


if __name__ == '__main__':
    unittest.main()
