"""Read-only memory view: memory configurations, clock bands, timing entries and the GB20x board profile.

Turing, Ampere, Ada and GB20x share the table set (nouveau M0203, rammap and timing layouts):
- BIT M+0x03 (u16, legacy-relative) is the memory configuration table, version 0x10: per entry,
  byte 0 holds the type (low nibble, 0xf = unused) and the hardware strap (high nibble), byte 1
  the column of the per-configuration tables (low nibble, nouveau "group"; not the strap) and the
  memory vendor (high nibble, NVIDIA's MEMORYINFO_VENDOR_ID codes). The board's strap pins select
  the entry; the ROM cannot tell which one a card uses.
- BIT P+0x04 is the memory clock table, version 0x11: bands with a u16 minimum and maximum MHz (the
  scale of the DRAM clock points), then one sub-entry per column whose byte 0 indexes the timing table.
  A 0-0 MHz band is a placeholder: no clock falls in it, so its timing entries are not in use.
- BIT P+0x08 is the timing table, version 0x20: raw images of memory controller timing registers.
  Word 0 reads as tRC [7:0], tRFC [16:8], tRAS [23:17], tRP [31:24]: tRC is within -2..+3 of
  tRAS + tRP on every entry the corpus uses. CL (word 1 [5:0]) and tWR (word 2 [22:16]) are the
  nouveau GDDR5 positions; they scale with the clock but are tentative. Values are controller
  cycles; the cycle length depends on the memory type, so no time is derived. Word 1 [11:7]
  (WL in nouveau) is constant on Ada and is not named.
GB20x object 0x89 holds undecoded per-board boot data, probably memory-interface training: two
signatures 0x8b0 apart anchor its groups, and records B1 and B2 store each field twice in a row
(column 0, then column 1). It is read at boot, so only flashing the whole ROM applies it, not the
override. Nothing here names, ranks or rewrites a value.
"""
import hashlib
import struct

from .blackwell import BlackwellRom
from .errors import FormatError, VbiosError
from .image import backend
from .tables import TableRom

VENDORS = {1: 'Samsung', 6: 'SK hynix', 0xF: 'Micron'}
# Type 9 is GDDR6 in nouveau; 0xa appears only on GDDR6X boards and 0xd only on GB20x (GDDR7).
TYPES = {9: 'GDDR6'}
TYPE_GUESSES = {0xA: 'GDDR6X', 0xD: 'GDDR7'}
# (name, word, first bit, width, confidence) of the decoded timing fields.
TIMING_FIELDS = (('tRC', 0, 0, 8, 'inferred'), ('tRAS', 0, 17, 7, 'inferred'), ('tRP', 0, 24, 8, 'inferred'),
                 ('tRFC', 0, 8, 9, 'probable'), ('CL', 1, 0, 6, 'tentative'), ('tWR', 2, 16, 7, 'tentative'))
UNIT = 'controller cycles'
STRAP_NOTE = 'the board sets the strap; the ROM cannot tell which configuration a card uses'
# GB20x memory objects reached from BIT M (u32 pointers), hashed whole for comparisons.
MEMORY_OBJECTS = ((0x05, 'training'), (0x09, 'training patterns'), (0x19, 'memory data'),
                  (0x1D, 'memory data'), (0x21, 'memory data'), (0x25, 'memory data'))
# Object 0x89: group A and group B header signatures, group B = group A + 0x8b0, group A at
# +0x6e0 plus 0, 0x408 or 0x578 (every GB20x image of the corpus). Group B: a 0x3a-byte header,
# then records B1 and B2 of 0x716 bytes. The header's big-endian words +0x2e and +0x32 copy two
# B1 fields (a tag; it looks like an ID and a revision, unconfirmed).
PROFILE_OBJECT = 0x89
PROFILE_SIGNATURES = (bytes.fromhex('12 12 98 98'), bytes.fromhex('95 28 94 28'))
PROFILE_DISTANCE, PROFILE_GROUP, PROFILE_SHIFTS = 0x8B0, 0x6E0, (0, 0x408, 0x578)
PROFILE_HEADER, PROFILE_RECORD = 0x3A, 0x716
PROFILE_COLUMNS = ('B1/0', 'B1/1', 'B2/0', 'B2/1')
# Sizes of the paired fields that open a record (0x4ae bytes; the same split fits every 5090 and 5080
# record), followed by 0x268 bytes of index lists that are not split into columns.
PROFILE_FIELDS = tuple(int(size) for size in (
    '11222242421222122224222222242222222222222222222212222222212211244222222242222222222222222444222222222222'
    '22424444112242224212221222242222222422222222222222222122222222122242222224222222222222222222222222222222'
    '22222222222222222222222222222224444444424444444422442222124'))
PROFILE_LISTS = 0x4AE
# Two u16[4] arrays end 0x100 bytes before group A, where this marker follows them (layouts 0 and 0x408).
ARRAYS_MARKER, ARRAYS_AT = bytes.fromhex('21 43 34 12'), 0x110
# A u8[2] flag 0x0a bytes after record B2, between these bytes (layout 0 only).
FLAGS_BEFORE, FLAGS_AFTER = bytes.fromhex('23 61 81 29'), bytes.fromhex('28 22 29')


def unrecognized(reason):
    return dict(status='unrecognized', reason=str(reason))


def in_use(band):
    """False for a 0-0 MHz placeholder band."""
    return band['max_mhz'] > 0


def _header(blob, at, size):
    if at < 0 or at + size > len(blob):
        raise FormatError(f'table header outside the image at {at:#x}')
    return blob[at:at + size]


def _owner(parser, at, size):
    """The GB20x object holding at..at+size ('0x10'), None in a legacy image or a table-layout ROM."""
    if isinstance(parser, BlackwellRom):
        if parser.legacy['start'] <= at and at + size <= parser.legacy['end']:
            return None
        return f"{parser.object_for(at, size)['id']:#04x}"
    parser.owner(at, size)
    return None


def _table(parser, name, at, size):
    return dict(table=name, object=_owner(parser, at, size), offset=f'{at:#x}', size=size,
                sha256=hashlib.sha256(parser.blob[at:at + size]).hexdigest())


def _configurations(parser):
    token = parser.tokens.get('M')
    if not token or token['version'] != 2 or token['size'] < 5:
        raise FormatError('no version-2 BIT memory token')
    b = parser.blob
    at = parser.legacy['start'] + struct.unpack_from('<H', b, token['data'] + 3)[0]
    version, hs, size, count, lookup = _header(b, at, 5)
    if version != 0x10 or hs < 7 or size < 2 or not count or lookup:
        raise FormatError('unrecognized memory configuration table')
    table = _table(parser, 'memory configurations', at, hs + size * count)
    items = []
    for i in range(count):
        e = at + hs + size * i
        if b[e] & 0x0F == 0x0F:
            continue
        kind, vendor = b[e] & 0x0F, b[e + 1] >> 4
        items.append(dict(entry=i, strap=b[e] >> 4, column=b[e + 1] & 0x0F, vendor=VENDORS.get(vendor),
                          vendor_code=f'{vendor:#x}', type_code=f'{kind:#x}', type=TYPES.get(kind),
                          type_guess=TYPE_GUESSES.get(kind), raw=b[e:e + size].hex()))
    return dict(status='recognized', offset=table['offset'], items=items), table


def _bands(parser, columns):
    b, at = parser.blob, parser.pointer('P', 4)
    version, hs, size, subsize, subcount, count = _header(b, at, 6)
    if version != 0x11 or hs < 6 or size < 4 or not subsize or not subcount or not count:
        raise FormatError('unrecognized memory clock table')
    stride = size + subsize * subcount
    table = _table(parser, 'memory clock bands', at, hs + stride * count)
    try:
        points, reason = [p['mhz'] for p in parser.dram_points()['points']], None
    except VbiosError as exc:
        points, reason = None, str(exc)
    outside = [c for c in columns or () if c >= subcount]
    columns = [c for c in columns if c < subcount] if columns is not None else list(range(subcount))
    items = []
    for i in range(count):
        e = at + hs + stride * i
        low, high = struct.unpack_from('<HH', b, e)
        sub = {str(c): e + size + subsize * c for c in columns}
        items.append(dict(entry=i, min_mhz=low, max_mhz=high,
                          timing_index={c: None if b[s] == 0xFF else b[s] for c, s in sub.items()},
                          stock_points=[p for p in points or () if low <= p <= high], raw=b[e:e + size].hex(),
                          sub_entries={c: b[s:s + subsize].hex() for c, s in sub.items()}))
    section = dict(status='recognized', offset=table['offset'], column_count=subcount, columns=columns,
                   stock_points=points, items=items)
    if outside:
        section['outside_table'] = outside
    if reason:
        section['stock_points_reason'] = reason
    return section, table


def _timings(parser, indices):
    b, at = parser.blob, parser.pointer('P', 8)
    version, hs, size, _, subcount, count = _header(b, at, 6)
    if version != 0x20 or hs < 6 or size < 12 or subcount or not count:
        raise FormatError('unrecognized timing table')
    table = _table(parser, 'timings', at, hs + size * count)
    items = []
    for i in sorted(i for i in indices if i < count):
        e = at + hs + size * i
        words = struct.unpack_from('<3I', b, e)
        items.append(dict(index=i, offset=f'{e:#x}', raw=b[e:e + size].hex(),
                          decoded={name: (words[word] >> shift) & ((1 << width) - 1)
                                   for name, word, shift, width, _ in TIMING_FIELDS}))
    section = dict(status='recognized', offset=table['offset'], entry_size=size, count=count, unit=UNIT,
                   confidence={name: level for name, _, _, _, level in TIMING_FIELDS}, items=items)
    missing = sorted(i for i in indices if i >= count)
    if missing:
        section['outside_table'] = missing
    return section, table


def _columns(record, column):
    """One column of a profile record: the bytes of every field in that column, field by field."""
    fields, at = [], 0
    for size in PROFILE_FIELDS:
        fields.append(record[at + size * column:at + size * (column + 1)])
        at += 2 * size
    return fields


def board_profile(data, base=0, *, raw=False):
    """Undecoded board profile of a GB20x object 0x89 (bytes data at ROM offset base), or an unrecognized status."""
    data = bytes(data)
    if any(data.count(signature) != 1 for signature in PROFILE_SIGNATURES):
        return unrecognized('the board profile signatures are absent or repeated')
    group, header = (data.find(signature) for signature in PROFILE_SIGNATURES)
    if header - group != PROFILE_DISTANCE or group - PROFILE_GROUP not in PROFILE_SHIFTS:
        return unrecognized('the board profile signatures are at an unreviewed position')
    b1 = header + PROFILE_HEADER
    end = b1 + 2 * PROFILE_RECORD
    if end > len(data):
        return unrecognized('the board profile records exceed the object')
    head = data[header:b1]
    records = [data[b1:b1 + PROFILE_RECORD], data[b1 + PROFILE_RECORD:end]]
    columns = {name: _columns(records[i // 2], i % 2) for i, name in enumerate(PROFILE_COLUMNS)}
    arrays, covered = unrecognized('the array marker is absent'), head + records[0] + records[1]
    if data[group - 0x100:group - 0xFC] == ARRAYS_MARKER:
        arrays = dict(status='recognized', offset=f'{base + group - ARRAYS_AT:#x}',
                      values=[list(struct.unpack_from('<4H', data, group - ARRAYS_AT + 8 * i)) for i in (0, 1)])
        covered += data[group - ARRAYS_AT:group - ARRAYS_AT + 16]
    flags = unrecognized('the flag bytes are not in the reviewed layout')
    if data[end + 2:end + 6] == FLAGS_BEFORE and data[end + 0x0D:end + 0x10] == FLAGS_AFTER:
        flags = dict(status='recognized', offset=f'{base + end + 0x0A:#x}', values=list(data[end + 0x0A:end + 0x0C]))
        covered += data[end + 0x0A:end + 0x0C]
    # sha256 covers every byte this view reports (comparisons use it); the fingerprint names the profile.
    result = dict(status='recognized', object=f'{PROFILE_OBJECT:#04x}', offset=f'{base + header:#x}',
                  layout_shift=f'{group - PROFILE_GROUP:#x}',
                  tag=[f"{int.from_bytes(head[at:at + 2], 'big'):#06x}" for at in (0x2E, 0x32)],
                  fingerprint=hashlib.sha256(head + b''.join(columns['B1/0'])).hexdigest()[:16],
                  sha256=hashlib.sha256(covered).hexdigest())
    if not raw:
        return result
    at, fields = 0, []
    for i, size in enumerate(PROFILE_FIELDS):
        fields.append(dict(offset=f'{at:#05x}', size=size,
                           **{name: columns[name][i].hex() for name in PROFILE_COLUMNS}))
        at += 2 * size
    result.update(header=head.hex(), records={'B1': f'{base + b1:#x}', 'B2': f'{base + b1 + PROFILE_RECORD:#x}'},
                  record_size=PROFILE_RECORD, fields=fields,
                  index_lists={name: record[PROFILE_LISTS:].hex() for name, record in zip(('B1', 'B2'), records)},
                  arrays=arrays, flags=flags)
    return result


def _profile(parser, raw):
    if not isinstance(parser, BlackwellRom):
        return dict(status='not-applicable', reason='object 0x89 belongs to the GB20x object directory')
    found = [o for o in parser.objects if o['id'] == PROFILE_OBJECT]
    if len(found) != 1:
        return unrecognized('no object 0x89')
    o = found[0]
    return board_profile(parser.blob[o['data']:o['data'] + o['size']], o['data'], raw=raw)


def _memory_objects(parser):
    """GB20x: the other memory objects BIT M points to, hashed whole."""
    if not isinstance(parser, BlackwellRom):
        return []
    found = []
    for offset, name in MEMORY_OBJECTS:
        try:
            o = parser.object_for(parser.pointer('M', offset))
        except VbiosError:
            continue
        found.append(dict(table=name, object=f"{o['id']:#04x}", offset=f"{o['data']:#x}", size=o['size'],
                          sha256=hashlib.sha256(parser.blob[o['data']:o['data'] + o['size']]).hexdigest()))
    return found


def memory_report(source, *, raw=False):
    """Read-only memory report of a BiosImage or a parsed ROM; a section it cannot verify says why.

    raw adds the board profile's field bytes, index lists, arrays and flags. Nothing is written.
    """
    if isinstance(source, (BlackwellRom, TableRom)):
        parser, name, blob = source, source.name, source.blob
    else:
        name, blob = source.name, source.blob
        try:
            parser = backend(source)
        except VbiosError as exc:
            return dict(schema_version=1, file=name, sha256=hashlib.sha256(blob).hexdigest(),
                        status='unrecognized', reason=str(exc))
    report = dict(schema_version=1, file=name, sha256=hashlib.sha256(blob).hexdigest(), status='recognized',
                  family='blackwell-gb20x' if isinstance(parser, BlackwellRom) else parser.family,
                  strap_note=STRAP_NOTE, tables=[])

    def section(build, *args):
        try:
            result, table = build(parser, *args)
        except (ValueError, IndexError, struct.error) as exc:
            return unrecognized(exc)
        report['tables'].append(table)
        return result
    report['configurations'] = section(_configurations)
    columns = (sorted({item['column'] for item in report['configurations']['items']})
               if report['configurations']['status'] == 'recognized' else None)
    report['bands'] = section(_bands, columns)
    if report['bands']['status'] == 'recognized':
        indices = {i for band in report['bands']['items'] if in_use(band)
                   for i in band['timing_index'].values() if i is not None}
        report['timings'] = section(_timings, indices)
    else:
        report['timings'] = unrecognized('no memory clock bands select the timing entries')
    report['tables'] += _memory_objects(parser)
    report['board_profile'] = _profile(parser, raw)
    return report


def table_key(table):
    """'memory clock bands (0x0f)' on GB20x, 'memory clock bands' elsewhere."""
    return f"{table['table']} ({table['object']})" if table['object'] else table['table']


def _differing(a, b, key, value):
    left = {key(item): value(item) for item in a}
    right = {key(item): value(item) for item in b}
    return sorted(k for k in left.keys() | right.keys() if left.get(k) != right.get(k))


def compare(a, b):
    """Per section, whether two memory reports are identical; never which one is better.

    Configurations, bands and timings compare the bytes of the entries in use (configurations, bands
    above 0 MHz with the sub-entries of the configurations' columns, the timing entries they select);
    tables compares every byte of each table. The board profile status follows its sha256; its field
    count needs reports made with raw=True, otherwise it is None.
    """
    def items(section, key, value, used=lambda i: True):
        sa, sb = a.get(section, {}), b.get(section, {})
        if sa.get('status') != 'recognized' or sb.get('status') != 'recognized':
            return dict(status='unavailable', reason=f'{section} not recognized in one or both images')
        keys = _differing([i for i in sa['items'] if used(i)], [i for i in sb['items'] if used(i)], key, value)
        return dict(status='differs' if keys else 'identical', count=len(keys), keys=keys)

    sections = dict(configurations=items('configurations', lambda i: i['strap'],
                                         lambda i: (i['column'], i['vendor_code'], i['type_code'], i['raw'])),
                    bands=items('bands', lambda i: i['entry'], lambda i: (i['raw'], i['sub_entries']), in_use),
                    timings=items('timings', lambda i: i['index'], lambda i: i['raw']))
    if sections['timings']['status'] == 'differs':
        left = {i['index']: i['decoded'] for i in a['timings']['items']}
        right = {i['index']: i['decoded'] for i in b['timings']['items']}
        sections['timings']['fields'] = sorted({name for k in sections['timings']['keys'] if k in left and k in right
                                                for name in left[k] if left[k][name] != right[k][name]})
    if a.get('status') == 'recognized' and b.get('status') == 'recognized':
        tables = _differing(a['tables'], b['tables'], table_key, lambda t: t['sha256'])
        sections['tables'] = dict(status='differs' if tables else 'identical', count=len(tables), keys=tables)
    else:
        sections['tables'] = dict(status='unavailable', reason='image not recognized')
    sections['board_profile'] = _compare_profiles(a.get('board_profile', {}), b.get('board_profile', {}))
    return dict(schema_version=1, a=dict(file=a.get('file'), sha256=a.get('sha256')),
                b=dict(file=b.get('file'), sha256=b.get('sha256')), sections=sections)


def _compare_profiles(a, b):
    if 'not-applicable' in (a.get('status'), b.get('status')):
        return dict(status='not-applicable')
    if a.get('status') != 'recognized' or b.get('status') != 'recognized':
        return dict(status='unavailable', reason='board profile not recognized in one or both images')
    # The status follows sha256 (header, records, arrays and flags); raw reports add where they differ.
    result = dict(status='identical' if a['sha256'] == b['sha256'] else 'differs', meaning='unknown',
                  tag='identical' if a['tag'] == b['tag'] else 'differs',
                  fingerprint='identical' if a['fingerprint'] == b['fingerprint'] else 'differs', fields=None)
    if 'fields' in a and 'fields' in b:
        result['configurations'] = {name: sum(x[name] != y[name] for x, y in zip(a['fields'], b['fields']))
                                    for name in PROFILE_COLUMNS}
        result['fields'] = sum(result['configurations'].values())
        for part in ('header', 'index_lists'):
            result[part] = 'identical' if a[part] == b[part] else 'differs'
        for part in ('arrays', 'flags'):
            values = a[part].get('values'), b[part].get('values')
            result[part] = ('unavailable' if None in values else 'identical' if values[0] == values[1] else 'differs')
    return result
