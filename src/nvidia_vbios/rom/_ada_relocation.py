"""Pure Ada relocation recipe (plan, render and verification functions only).

The original offline recipe accounts for every output byte and narrows the
reference-scan claim: the pinned set does not exclude an interior-field pointer.
Only its pure plan/render/verification functions are kept here; no CLI,
filesystem access, external repository import or hardware operation is retained.
The public ada_relocated adapter further pins exact inputs and output. This
recipe does not establish support for arbitrary Ada images or driver versions.
NVIDIA nvgpu bios.h layout references in the original recipe are MIT licensed.

Layout facts reach plan_for/render/verify_payload as a pins dict. reviewed_pins()
returns the REVIEWED constants below (ada-relocated-v1, byte-identical output).
derive_pins() re-derives the same facts from the bank itself for the experimental
ada-relocated-v2; its 'general' flag enables the stricter checks that replace the
reviewed scan digest and fixed-offset value probes.
"""
import hashlib
import struct

SCHEMA = 'nvidia-vbios-ada-relocation-candidate/v1'
ARCHIVE_SIZE = 2048000
BANK_SIZE = 0xE0000
LEGACY_START = 0x9400
RECEIVER_LIMIT = 0x80000           # AD10x fresh-image capacity in the audited receivers
PCI_ID = 0x28B010DE                # 10de:28b0, PCI config dword order
VFE_ENTRY_SIZE = 0x19
TAIL_PAD_COPY = 0x40               # trailing 0xFF bytes copied after the last table

CHAIN_TYPES = [0x00, 0x03, 0xE0, 0xE0]  # legacy, EFI, two NPDS images

# Reviewed layout facts. Region boundaries are re-derived and must match these.
REVIEWED = {
    'r_low': (0x78B8F, 0x7A40C),
    'vfe': (0x7A40C, 0x81258),
    'r_tail': (0x81258, 0x8505B),
    'zero_area': (0x829D, 0xF114),   # zero bytes between legacy x86 code blocks
    'reserved_zero_tables': (0x829D, 0x82A9),   # BIT M targets inside the zero area
}
DEST_LOW = 0x9980                  # leaves 0x16D7 bytes after the last M zero table
DEST_TAIL = 0xB200
DEST_END_MARGIN = 0x80             # minimum distance to the following x86 code
DEST_GAP = DEST_LOW - REVIEWED['reserved_zero_tables'][1]   # 0x16D7 kept free after the M zero tables
DEST_ALIGN = 0x100                 # DEST_TAIL = DEST_LOW + R_LOW rounded up (0xB1FD -> 0xB200)
LAPTOP_TABLE = 0xC8                # P pointer set on every Ada laptop image of the corpus, on no desktop one

# Pointer fields (token, byte offsets). Every other 32-bit value was classified.
POINTER_FIELDS = {
    'P': ('all', 2, 252), 'C': ('all', 2, 44), 'M': ('from5', 2, 41),
    'p': ((0,), 2, 4), 'i': ((0x60, 0x6A), 2, 110),
}

# primary-bank SHA256 -> (label, reviewed scan digest, expected TGP max mW, REL max uV)
REVIEWED_INPUTS = {
    'aaf1abb66575d9e36fdf7955d5d86c9b0cf54e3e78dd0d419e0816411c2cb627':
        ('persistent-v1 bank: TGP max 100 W, NVVDD REL 1.100 V',
         '3ef887a93a98bb36236ff8ff130acb6eecb674752fb0c7f4c773672c0cb17414', 100000, 1100000.0),
    'fb20a772e21b292b4714f9c395af68c66c8d374c9a373141c9cb435a1c43a4e1':
        ('clock-ranges-v2 bank: GPC max +1500, memory min -5000 MHz; booted on hardware',
         '3ef887a93a98bb36236ff8ff130acb6eecb674752fb0c7f4c773672c0cb17414', 100000, 1100000.0),
}


class RelocationError(Exception):
    pass


class DoesNotFit(RelocationError):
    """The tables that must move do not fit the free legacy area or the receiver."""


class LaptopDoesNotFit(DoesNotFit):
    """DoesNotFit on a laptop image: its laptop-only performance tables are part of what must move."""


def u16(b, at):
    return struct.unpack_from('<H', b, at)[0]


def u32(b, at):
    return struct.unpack_from('<I', b, at)[0]


def walk_chain(bank, start=LEGACY_START):
    """Follow PCIR/NPDS images and NPDE lengths/last flags like the host loader."""
    images, at = [], start
    while True:
        if at + 0x1A > len(bank):
            raise RelocationError(f'image header outside bank at {at:#x}')
        sig = u16(bank, at)
        if sig not in (0xAA55, 0x4E56):
            raise RelocationError(f'unexpected ROM signature {sig:#06x} at {at:#x}')
        ds = at + u16(bank, at + 0x18)
        if bank[ds:ds + 4] != (b'PCIR' if sig == 0xAA55 else b'NPDS'):
            raise RelocationError(f'missing PCI data structure for image at {at:#x}')
        blocks, last = u16(bank, ds + 0x10), bool(bank[ds + 0x15] & 0x80)
        npde = (ds + u16(bank, ds + 0x0A) + 0xF) & ~0xF
        if bank[npde:npde + 4] == b'NPDE' and u16(bank, npde + 4) in (0x100, 0x101):
            blocks = u16(bank, npde + 8)
            if u16(bank, npde + 6) >= 0x0B:
                last = bool(bank[npde + 0x0A] & 0x80)
        else:
            npde = None
        if not blocks or at + blocks * 512 > len(bank):
            raise RelocationError(f'invalid image length at {at:#x}')
        images.append(dict(start=at, length=blocks * 512, type=bank[ds + 0x14], sig=sig,
                           ds=ds, npde=npde, last=last))
        at += blocks * 512
        if last:
            return images


def logical_view(bank, images):
    """GSP table address space: legacy image followed by E0 images, EFI skipped."""
    legacy = images[0]
    if legacy['type'] != 0 or legacy['sig'] != 0xAA55:
        raise RelocationError('chain does not start with the legacy image')
    ext = [i for i in images[1:] if i['type'] == 0xE0]
    if not ext:
        raise RelocationError('no NVIDIA E0 expansion image')
    bias = (ext[0]['start'] - legacy['start']) - legacy['length']
    if any(b['start'] != a['start'] + a['length'] for a, b in zip(ext, ext[1:])):
        raise RelocationError('E0 images are not contiguous')
    view = bank[legacy['start']:legacy['start'] + legacy['length']]
    view += bank[ext[0]['start']:ext[-1]['start'] + ext[-1]['length']]
    return bytes(view), bias, legacy['length']


def parse_bit(view, legacy_length):
    at = view.find(b'\xff\xb8BIT\x00', 0, legacy_length)
    if at < 0 or view.find(b'\xff\xb8BIT\x00', at + 1, legacy_length) >= 0:
        raise RelocationError('expected exactly one BIT header in the legacy image')
    hs, ts, count = view[at + 8:at + 11]
    tokens = {}
    for k in range(count):
        tid, version, size, ptr = struct.unpack_from('<BBHH', view, at + hs + k * ts)
        tokens[chr(tid)] = dict(version=version, size=size, data=ptr)
    return at, tokens


def pointer_sites(tokens):
    sites = {}
    for tid, (offsets, version, size) in POINTER_FIELDS.items():
        token = tokens.get(tid)
        if not token or token['version'] != version or token['size'] != size:
            raise RelocationError(f'BIT token {tid} differs from the reviewed layout')
        if offsets == 'all':
            offsets = range(0, size - 3, 4)
        elif offsets == 'from5':
            offsets = range(5, size - 3, 4)
        for off in offsets:
            sites[token['data'] + off] = f'{tid}+{off:#x}'
    return sites


def derive_regions(view, tokens, expected=None):
    """Re-derive the moved regions from table headers and BIT pointers."""
    p = tokens['P']['data']

    def ptr(off):
        return u32(view, p + off)

    rammap, tweak, vfe, after_vfe, before_vfe = ptr(0x04), ptr(0x08), ptr(0x20), ptr(0x28), ptr(0xE8)
    if view[rammap] != 0x11:
        raise RelocationError('memory clock table version differs')
    hdr, length, ssz, snr, cnt = view[rammap + 1:rammap + 6]
    if rammap + hdr + cnt * (length + snr * ssz) != tweak:
        raise RelocationError('memory clock table does not end at the memory tweak table')
    hs, es, cnt = view[before_vfe + 1:before_vfe + 4]
    if before_vfe + hs + es * cnt != vfe:
        raise RelocationError('the table before VFE does not end at the VFE table')
    if view[vfe] != 0x30 or view[vfe + 2] != VFE_ENTRY_SIZE or view[vfe + 4] != VFE_ENTRY_SIZE:
        raise RelocationError('VFE header differs from the reviewed 3x layout')
    if (after_vfe - vfe - view[vfe + 1]) % VFE_ENTRY_SIZE:
        raise RelocationError('VFE region is not a whole number of entries')
    end = len(view) - 1                      # last byte of the final image is its checksum
    content_end = end
    while view[content_end - 1] == 0xFF:
        content_end -= 1
    regions = dict(r_low=(tweak, vfe), vfe=(vfe, after_vfe), r_tail=(after_vfe, content_end))
    for name, value in regions.items():
        if expected is not None and value != expected[name]:
            raise RelocationError(f'derived {name} {value} differs from the reviewed layout')
    return regions


def scan_references(view, sites, lo, hi):
    """Every 32-bit little-endian value in [lo, hi) that is not a known pointer field."""
    found = []
    for at in range(len(view) - 3):
        value = u32(view, at)
        if lo <= value < hi and at not in sites:
            found.append((at, value))
    return found


def classify(view, sites, tokens, found, regions):
    """Reject any unexplained reference to a structure start or region boundary."""
    starts = {u32(view, s) for s in sites} - {0}
    boundaries = {a for pair in regions.values() for a in pair}
    falcon = u32(view, tokens['p']['data'])
    descriptors = [u32(view, falcon + 6 + k * 6 + 2) for k in range(view[falcon + 3])]
    ucode = (min(d for d in descriptors if d), min(s for s in starts if s > max(descriptors)))
    suspicious, counts = [], dict(ucode_body=0, mid_structure=0)
    for at, value in found:
        if ucode[0] <= at < ucode[1]:
            counts['ucode_body'] += 1
        elif value in starts or value in boundaries:
            suspicious.append((at, value))
        else:
            counts['mid_structure'] += 1
    digest = hashlib.sha256(b''.join(struct.pack('<II', a, v) for a, v in found)).hexdigest()
    return dict(counts=counts, total=len(found), digest=digest, ucode_area=list(ucode),
                suspicious=[dict(site=a, value=v) for a, v in suspicious],
                note='classified by location only; values inside structures were reviewed manually as data',
                candidates=[[a, v] for a, v in found])


def relocate_address(value, regions, dest_low, dest_tail):
    (low0, low1), (vfe0, vfe1), (tail0, tail1) = regions['r_low'], regions['vfe'], regions['r_tail']
    if low0 <= value < low1:
        return value - low0 + dest_low
    if vfe0 <= value < vfe1:
        return value - (vfe0 - low0)
    if tail0 <= value < tail1:
        return value - tail0 + dest_tail
    return value


def host_parser(image, pci_id=PCI_ID):
    """Python port of kgspVbiosOverrideFindLegacy from the per-GPU loader patch."""
    found, selected = 0, None
    for off in range(0, len(image) - 0x200 + 1, 0x200):
        if image[off] != 0x55 or image[off + 1] != 0xAA:
            continue
        rel = u16(image, off + 0x18)
        if rel > len(image) - off - 0x18:
            continue
        pcir = off + rel
        if image[pcir:pcir + 4] != b'PCIR' or image[pcir + 0x14] != 0:
            continue
        length = u16(image, pcir + 0x10) * 512
        if (u32(image, pcir + 4) != pci_id or not length or length > len(image) - off
                or rel > length or length - rel < 0x18):
            return None
        found += 1
        if sum(image[off:off + length]) & 0xFF or found != 1:
            return None
        selected = off
    return selected if found == 1 else None


def reviewed_pins(bank):
    """The REVIEWED layout facts for one reviewed primary bank (ada-relocated-v1)."""
    if len(bank) != BANK_SIZE:
        raise RelocationError('expected the 917,504-byte primary bank')
    digest = hashlib.sha256(bank).hexdigest()
    if digest not in REVIEWED_INPUTS:
        raise RelocationError(f'primary bank {digest} is not a reviewed input')
    label, pinned_scan, tgp_expected, rel_expected = REVIEWED_INPUTS[digest]
    return dict(label=label, general=False, legacy_start=LEGACY_START, pci_id=PCI_ID,
                regions={name: REVIEWED[name] for name in ('r_low', 'vfe', 'r_tail')},
                zero_area=REVIEWED['zero_area'], reserved_zero_tables=REVIEWED['reserved_zero_tables'],
                dest_low=DEST_LOW, dest_tail=DEST_TAIL, tail_pad=TAIL_PAD_COPY,
                scan_digest=pinned_scan, probes=(tgp_expected, rel_expected))


def derive_pins(bank, legacy_start):
    """Experimental (ada-relocated-v2): derive every layout fact from this bank alone.

    The rules reproduce the REVIEWED values on the reviewed input: regions come from
    the table chain, the zero area is the legacy zero run that holds the BIT M zero
    tables, DEST_LOW keeps DEST_GAP free after them, DEST_TAIL follows R_LOW on a
    DEST_ALIGN boundary, and the copied tail padding is limited to the 0xFF bytes
    present before the image checksum. There is no scan digest or value probe.
    """
    images = walk_chain(bank, legacy_start)
    if [i['type'] for i in images] != CHAIN_TYPES:
        raise RelocationError('chain is not legacy + EFI + two NPDS images')
    view, _, legacy_length = logical_view(bank, images)
    _, tokens = parse_bit(view, legacy_length)
    sites = pointer_sites(tokens)
    regions = derive_regions(view, tokens)
    targets = sorted({u32(view, s) for s, name in sites.items() if name.startswith('M+')})
    zero_tables = [t for t in targets if 0 < t < legacy_length and view[t] == 0]
    if not zero_tables:
        raise RelocationError('no BIT M zero table anchors a legacy zero area')
    zero0 = zero1 = zero_tables[0]
    while zero0 > 0 and view[zero0 - 1] == 0:
        zero0 -= 1
    while zero1 < legacy_length and view[zero1] == 0:
        zero1 += 1
    reserved = [t for t in zero_tables if t < zero1]
    dest_low = reserved[-1] + DEST_GAP
    low_size = regions['r_low'][1] - regions['r_low'][0]
    dest_tail = -(-(dest_low + low_size) // DEST_ALIGN) * DEST_ALIGN
    pci_id = u32(bank, images[0]['ds'] + 4)
    if pci_id & 0xFFFF != 0x10DE:
        raise RelocationError('legacy image is not an NVIDIA image')
    return dict(label='layout derived from this image (experimental)', general=True,
                legacy_start=legacy_start, pci_id=pci_id, regions=regions, zero_area=(zero0, zero1),
                reserved_zero_tables=(reserved[0], reserved[-1]), dest_low=dest_low, dest_tail=dest_tail,
                tail_pad=min(TAIL_PAD_COPY, len(view) - 1 - regions['r_tail'][1]),
                scan_digest=None, probes=None)


def general_checks(view, tokens, sites, regions, ucode, legacy_length, npds_length, windows):
    """Evidence that replaces the reviewed scan digest when the pins are derived.

    Refuses referenced data inside a destination window, a falcon ucode descriptor in
    the moved range, and an expansion-relative reference (value + legacy length) to
    a moved structure start anywhere but the first NPDS image. That image's directory
    copies are left unchanged, the assumption ada-relocated-v1 already makes.
    """
    lo, hi = regions['r_low'][0], regions['r_tail'][1]
    pointers = {u32(view, s) for s in sites} - {0}
    referenced = pointers | {token['data'] for token in tokens.values()}
    inside = sorted(t for t in referenced if any(a <= t < b for a, b in windows))
    if inside:
        raise RelocationError(f'destination windows hold referenced data at {[hex(t) for t in inside]}')
    falcon = u32(view, tokens['p']['data'])
    if any(lo <= u32(view, falcon + 6 + k * 6 + 2) < hi for k in range(view[falcon + 3])):
        raise RelocationError('a falcon ucode descriptor points into a moved region')
    starts = {t for t in pointers | {a for pair in regions.values() for a in pair} if lo <= t < hi}
    directory, unexplained = 0, []
    for at in range(len(view) - 3):
        if u32(view, at) + legacy_length in starts and at not in sites and not ucode[0] <= at < ucode[1]:
            if legacy_length <= at < legacy_length + npds_length:
                directory += 1
            else:
                unexplained.append(dict(site=at, value=u32(view, at)))
    if unexplained:
        raise RelocationError(f'unexplained expansion-relative references to moved structures: {unexplained[:8]}')
    return dict(expansion_relative_directory_entries=directory, destination_windows=[list(w) for w in windows])


def unexpected_signatures(view, new, image_starts, tolerate_preexisting=False):
    """512-byte aligned 55AA/VN signatures in the relocated view that start no chain image.

    With tolerate_preexisting (derived pins only), a 55AA signature is accepted when
    the source view has it at the same offset and neither copy leads to a PCIR header.
    A VN signature is accepted the same way, with neither copy leading to a PCIR or
    NPDS header, only inside the legacy image (before the first listed image start):
    x86 code in the RTX 4090 95.02.18 legacy image compares a word with 'VN' there.
    """
    def header(blob, at, names):
        return at + 0x1A <= len(blob) and blob[at + u16(blob, at + 0x18):][:4] in names
    legacy_end = min(image_starts, default=0)
    found, tolerated = [], []
    for o in range(0x200, len(new), 0x200):
        signature = new[o:o + 2]
        if signature not in (b'\x55\xaa', b'VN') or o in image_starts:
            continue
        names = (b'PCIR',) if signature == b'\x55\xaa' else (b'PCIR', b'NPDS')
        if (tolerate_preexisting and view[o:o + 2] == signature and (signature == b'\x55\xaa' or o < legacy_end)
                and not header(view, o, names) and not header(new, o, names)):
            tolerated.append(o)
        else:
            found.append(o)
    return found, tolerated


def plan_for(bank, pins=None):
    """Validate a primary bank against layout pins and derive the complete relocation plan.

    Without pins the bank must be a reviewed input and the REVIEWED pins apply.
    """
    if pins is None:
        pins = reviewed_pins(bank)
    images = walk_chain(bank, pins['legacy_start'])
    if [i['type'] for i in images] != CHAIN_TYPES:
        raise RelocationError('chain is not legacy + EFI + two NPDS images')
    view, bias, legacy_length = logical_view(bank, images)
    bit_at, tokens = parse_bit(view, legacy_length)
    sites = pointer_sites(tokens)
    regions = derive_regions(view, tokens, pins['regions'])

    low, vfe = regions['r_low'], regions['vfe']
    tail = (regions['r_tail'][0], regions['r_tail'][1] + pins['tail_pad'])
    zero0, zero1 = pins['zero_area']
    dest_low, dest_tail = pins['dest_low'], pins['dest_tail']
    windows = ((dest_low, dest_low + low[1] - low[0]), (dest_tail, dest_tail + tail[1] - tail[0]))
    if not (pins['reserved_zero_tables'][1] < dest_low and windows[0][1] <= dest_tail
            and windows[1][1] <= zero1 - DEST_END_MARGIN):
        kind = LaptopDoesNotFit if u32(view, tokens['P']['data'] + LAPTOP_TABLE) else DoesNotFit
        raise kind(f'destinations do not fit the zero area: {low[1] - low[0] + tail[1] - tail[0]} bytes '
                   f'of tables must move, {zero1 - DEST_END_MARGIN - dest_low} free bytes are available')
    if any(view[zero0:zero1]):
        raise RelocationError('legacy data area is not zero-filled')
    if any(b != 0xFF for b in view[regions['r_tail'][1]:tail[1]]):
        raise RelocationError('copied tail padding is not 0xFF')
    last = images[-1]
    last_logical = len(view) - last['length']           # start of the final NPDS image
    vfe_end = low[0] + (vfe[1] - vfe[0])
    new_end = last_logical + -(-(vfe_end + 1 - last_logical) // 512) * 512
    if new_end > RECEIVER_LIMIT:
        raise DoesNotFit(f'relocated chain still exceeds the receiver: {new_end:#x}')

    moved = (low[0], regions['r_tail'][1])
    scan = classify(view, sites, tokens, scan_references(view, sites, *moved), regions)
    if scan['suspicious']:
        raise RelocationError(f'unexplained references to moved structures: {scan["suspicious"]}')
    if pins['scan_digest'] is not None and scan['digest'] != pins['scan_digest']:
        raise RelocationError('reference scan differs from the reviewed result')
    general = (general_checks(view, tokens, sites, regions, scan['ucode_area'], legacy_length,
                              images[2]['length'], windows) if pins['general'] else None)
    updates, labels = {}, {}
    for site, name in sorted(sites.items()):
        old = u32(view, site)
        moved_to = relocate_address(old, regions, dest_low, dest_tail)
        if old and moved_to != old:
            updates[site], labels[site] = moved_to, name
    probes = pins['probes'] or (None, None)
    return dict(digest=hashlib.sha256(bank).hexdigest(), label=pins['label'], pins=pins,
                tgp_expected=probes[0], rel_expected=probes[1],
                images=images, view=view, bias=bias, legacy_length=legacy_length, bit_at=bit_at,
                tokens=tokens, sites=sites, regions=regions, scan=scan, general=general, tail_copy=tail,
                vfe_end=vfe_end, last_logical=last_logical, new_end=new_end,
                npds_length=images[2]['length'], blocks=(new_end - last_logical) // 512,
                ds=last['ds'] - last['start'] + last_logical,
                npde=last['npde'] - last['start'] + last_logical,
                updates=updates, labels=labels)


def render(plan, bank):
    """Build the payload: IFR prefix + relocated legacy/NPDS chain."""
    view, pins = plan['view'], plan['pins']
    low, vfe, tail = plan['regions']['r_low'], plan['regions']['vfe'], plan['tail_copy']
    dest_low, dest_tail = pins['dest_low'], pins['dest_tail']
    new = bytearray(view)
    new[dest_low:dest_low + low[1] - low[0]] = view[low[0]:low[1]]
    new[dest_tail:dest_tail + tail[1] - tail[0]] = view[tail[0]:tail[1]]
    new[low[0]:plan['vfe_end']] = view[vfe[0]:vfe[1]]
    del new[plan['new_end']:]
    new[plan['vfe_end']:plan['new_end']] = b'\xff' * (plan['new_end'] - plan['vfe_end'])
    for site, value in plan['updates'].items():
        struct.pack_into('<I', new, site, value)
    # Final NPDS image lengths: PCI data structure and PCI data extension.
    struct.pack_into('<H', new, plan['ds'] + 0x10, plan['blocks'])
    struct.pack_into('<H', new, plan['npde'] + 0x08, plan['blocks'])
    for start, end in ((0, plan['legacy_length']), (plan['last_logical'], plan['new_end'])):
        new[end - 1] = 0
        new[end - 1] = (-sum(new[start:end])) & 0xFF
    return bank[:pins['legacy_start']] + bytes(new)


def verify_payload(bank, payload, pins=None):
    """Check a payload against a freshly derived plan, accounting for every byte."""
    plan = plan_for(bank, pins)
    pins, legacy_start = plan['pins'], plan['pins']['legacy_start']
    view, legacy_length = plan['view'], plan['legacy_length']
    low, vfe, tail = plan['regions']['r_low'], plan['regions']['vfe'], plan['tail_copy']
    vfe_end, new_end = plan['vfe_end'], plan['new_end']
    if len(payload) != legacy_start + new_end:
        raise RelocationError('payload size differs from the plan')
    if payload[:legacy_start] != bank[:legacy_start]:
        raise RelocationError('IFR prefix differs from the source bank')
    new = payload[legacy_start:]
    fixed = {}
    for site, value in plan['updates'].items():
        for k, byte in enumerate(struct.pack('<I', value)):
            fixed[site + k] = byte
    for field in (plan['ds'] + 0x10, plan['npde'] + 0x08):
        fixed[field], fixed[field + 1] = plan['blocks'] & 0xFF, plan['blocks'] >> 8
    checksum_bytes = {legacy_length - 1, new_end - 1}       # validated by the image sums below
    low_dest = (pins['dest_low'], pins['dest_low'] + low[1] - low[0])
    tail_dest = (pins['dest_tail'], pins['dest_tail'] + tail[1] - tail[0])
    bad = []
    for i, value in enumerate(new):
        if i in fixed:
            expected = fixed[i]
        elif i in checksum_bytes:
            continue
        elif low_dest[0] <= i < low_dest[1]:
            expected = view[low[0] + i - low_dest[0]]
        elif tail_dest[0] <= i < tail_dest[1]:
            expected = view[tail[0] + i - tail_dest[0]]
        elif low[0] <= i < vfe_end:
            expected = view[vfe[0] + i - low[0]]
        elif i >= vfe_end:
            expected = 0xFF                                 # final NPDS padding
        else:
            expected = view[i]                              # unchanged, including zero gaps
        if value != expected:
            bad.append(i)
    if bad:
        raise RelocationError(f'{len(bad)} bytes differ from the plan, first at logical '
                              f'{[hex(i) for i in bad[:8]]}')

    images = walk_chain(payload, legacy_start)
    npds_length = plan['npds_length']                       # 0x6000 on the reviewed input
    if [(i['type'], i['length']) for i in images] != [(0x00, legacy_length), (0xE0, npds_length),
                                                     (0xE0, new_end - plan['last_logical'])]:
        raise RelocationError('relocated chain shape is wrong')
    view2, bias, _ = logical_view(payload, images)
    if bias != 0 or view2 != new:
        raise RelocationError('relocated logical view or bias is wrong')
    sums = [sum(payload[i['start']:i['start'] + i['length']]) & 0xFF for i in images]
    if any(sums):
        raise RelocationError(f'image checksums are not zero: {sums}')
    if host_parser(payload, pins['pci_id']) != legacy_start:
        raise RelocationError('host loader parser rejects the payload')
    if new.count(b'\xff\xb8BIT\x00') != 1:
        raise RelocationError('BIT signature is not unique')
    fake, tolerated = unexpected_signatures(view, new, (legacy_length, legacy_length + npds_length),
                                            pins['general'])
    if fake:
        raise RelocationError(f'unexpected image signatures at {fake}')
    # Every pointer field resolves to identical bytes: to the end of a moved region,
    # or a bounded window for structures that stay in place.
    moved_lo, moved_hi = low[0], plan['regions']['r_tail'][1]
    ends = sorted({x for pair in plan['regions'].values() for x in pair})
    checked = 0
    for site in plan['sites']:
        old = u32(view, site)
        if not old:
            continue
        span = (next(e for e in ends if e > old) - old) if moved_lo <= old < moved_hi else 0x100
        target = u32(new, site)
        if new[target:target + span] != view[old:old + span]:
            raise RelocationError(f'pointer at {site:#x} does not resolve to the same bytes')
        checked += 1
    tgp = rel = None
    if pins['probes'] is not None:
        p = plan['tokens']['P']['data']
        tgp = u32(new, u32(new, p + 0x2C) + 0xF4)
        rel = struct.unpack_from('<f', new, u32(new, p + 0x20) + 0x51F + 7)[0]
        if tgp != plan['tgp_expected'] or rel != plan['rel_expected']:
            raise RelocationError(f'edited values not preserved: TGP {tgp} REL {rel}')
    return dict(chain=[dict(type=i['type'], start=i['start'], length=i['length'], last=i['last'])
                       for i in images],
                byte_accounting='every output byte matched the re-derived plan',
                checksums_zero=True, host_parser_skip=legacy_start, bit_unique=True,
                pointer_fields_checked=checked, pointer_fields_updated=len(plan['updates']),
                tgp_max_mw=tgp, nvvdd_rel_max_uv=rel, gsp_bytes=new_end,
                preexisting_signatures_tolerated=tolerated, general=plan['general'])
