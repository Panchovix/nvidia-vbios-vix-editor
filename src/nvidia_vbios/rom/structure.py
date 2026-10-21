"""Bounded PCI/NPDS and BIT parsing, independent of total dump size."""
import math
import struct
from .errors import FormatError

# Quadratic coefficients below this are float residue (corpus: at most 5e-9; real slopes are 35 and up).
VFE_RESIDUE = 1e-6


def read(blob, fmt, at, *, end=None):
    size = struct.calcsize(fmt)
    if at < 0 or at + size > min(len(blob), len(blob) if end is None else end):
        raise FormatError(f'read outside image at {at:#x} ({size} bytes)')
    return struct.unpack_from(fmt, blob, at)


# Bit 4 of a clock programming entry's flag byte: set on the stored clocks a clock offset
# moves (GPC/XBAR entries and the top DRAM entries on the stock images; inferred meaning).
DRAM_POINT_OFFSET_BIT = 0x10
DRAM_POINT_FLAGS = (0x03, 0x13)


def dram_points(blob, at, first, last, version):
    """DRAM entries first..last of the clock programming table at `at` (version 0x40 or 0x50).

    The table has an 8-byte header (version, header size, entry size, entry count, then two
    sub-entry counts and sizes); each entry starts with a flag byte and the u16 clock in MHz.
    The DRAM row of the clocks table names the DRAM entries. Reviewed shape, as on every Ada,
    Ampere and GB20x image examined: flag byte 0x03 or 0x13, clocks strictly rising, the two
    lowest (the idle levels) without the offset bit, and the entries with it forming a
    nonempty top run.
    """
    if at + 8 > len(blob):
        raise FormatError("clock programming table header exceeds the image")
    hs, size, count, c1, s1, c2, s2 = blob[at + 1:at + 8]
    if blob[at] != version or hs != 8 or size < 3:
        raise FormatError("unsupported clock programming table")
    stride = size + c1 * s1 + c2 * s2
    if at + hs + stride * count > len(blob):
        raise FormatError("clock programming table exceeds the image")
    if not first <= last < count or last - first < 2:
        raise FormatError("unsupported DRAM clock programming entries")
    points = []
    for i in range(first, last + 1):
        e = at + hs + stride * i
        points.append(dict(index=i, offset=e, flags=blob[e], mhz=read(blob, "<H", e + 1)[0]))
    moved = [p["flags"] & DRAM_POINT_OFFSET_BIT == DRAM_POINT_OFFSET_BIT for p in points]
    if (any(p["flags"] not in DRAM_POINT_FLAGS for p in points) or
            any(a["mhz"] >= b["mhz"] for a, b in zip(points, points[1:])) or
            any(moved[:2]) or not moved[-1] or moved != sorted(moved)):
        raise FormatError("DRAM clock programming entries outside the reviewed shape")
    return dict(offset=at, size=hs + stride * count, points=points)


def fan_curve(blob, at):
    """Stored curve of the fan policy entry at `at`: bytes 14..16 hold three level (%)
    points and bytes 18..29 three (temperature in 1/32 C, RPM) points, '<H' each."""
    return dict(curve_levels=tuple(blob[at + 14:at + 17]),
                curve_points=tuple(read(blob, '<HH', at + 18 + 4 * k) for k in range(3)))


def vfe_range(blob, base, size, width, count, index, seen=frozenset()):
    """(lowest, highest) uV of the VFE equation list at index, or None when it is not bounded.

    Each equation is clamped to its own float bounds (bytes 3/7) and its next link
    (byte 2, | byte 24 << 8 when links are u16) is added, as the RTX 2000 Ada VMIN
    shows (clamp 560 mV, driver 650 mV). A quadratic (1) whose slopes are float
    residue is its constant (byte 11); otherwise a quadratic or the GB20x type 7
    polynomial is bounded by its clamp alone. Min/max (2) and compare (3) span
    their two children (bytes 11/12 and 15/16, u16 high bytes 4 further on).
    Other kinds or output units, indices outside the table and cycles give None;
    a missing link (index 0xff/0xffff) is an empty list, (0, 0).
    """
    none = (1 << 8 * width) - 1
    low = high = 0.0
    while index != none:
        if index >= count or index in seen:
            return None
        seen |= {index}
        e = blob[base + size * index:base + size * index + size]
        lo, hi, c0, c1, c2 = struct.unpack_from('<5f', e, 3)
        if e[23] & 15 != 2 or not lo <= hi:
            return None
        if e[0] in (1, 7):
            constant = e[0] == 1 and abs(c1) < VFE_RESIDUE and abs(c2) < VFE_RESIDUE
            span = (c0, c0) if constant else (-math.inf, math.inf)
        elif e[0] in (2, 3):
            children = [vfe_range(blob, base, size, width, count, e[k] | (e[k + 4] << 8 if width == 2 else 0), seen)
                        for k in ((11, 12) if e[0] == 2 else (15, 16))]
            if None in children:
                return None
            span = (min(c[0] for c in children), max(c[1] for c in children))
        else:
            return None
        value = (min(max(span[0], lo), hi), max(min(span[1], hi), lo))
        if not all(abs(v) < 1e30 for v in value):  # a +-FLT_MAX clamp bounds nothing
            return None
        low, high = low + value[0], high + value[1]
        index = e[2] | (e[24] << 8 if width == 2 else 0)
    return low, high


def scan_images(blob):
    pci, extended, issues = [], [], []
    for start in range(0, len(blob) - 0x1A + 1, 512):
        signature = blob[start:start + 2]
        if signature not in (b'\x55\xaa', b'VN'):
            continue
        header = start + read(blob, '<H', start + 0x18)[0]
        magic = b'PCIR' if signature == b'\x55\xaa' else b'NPDS'
        if blob[header:header + 4] != magic:
            # Signature-like bytes inside a payload do not constitute an image.
            continue
        if header < start + 0x1A or header + 0x18 > len(blob):
            issues.append({'code': 'INVALID_IMAGE_HEADER', 'offset': start})
            continue
        vendor, device, _, header_size = read(blob, '<HHHH', header + 4)
        size = read(blob, '<H', header + 0x10)[0] * 512
        end = start + size
        if header_size < 0x18 or not size or end > len(blob) or header + header_size > end:
            issues.append({'code': 'TRUNCATED_IMAGE', 'offset': start})
            continue
        entry = dict(start=start, end=end, size=size, vendor=vendor, device=device,
                     type=blob[header + 0x14], last=bool(blob[header + 0x15] & 0x80))
        entry['pcir' if magic == b'PCIR' else 'npds'] = header
        (pci if magic == b'PCIR' else extended).append(entry)
    ordered = sorted(pci + extended, key=lambda p: p['start'])
    for a, b in zip(ordered, ordered[1:]):
        if a['end'] > b['start']:
            issues.append({'code': 'OVERLAPPING_IMAGES', 'offset': b['start']})
    return pci, extended, issues


def npde(blob, image):
    """Offset of the NPDE after an image's NPDS (16-byte aligned) when it holds a last-image byte, else None."""
    header = image['npds']
    at = (header + struct.unpack_from('<H', blob, header + 0x0A)[0] + 0xF) & ~0xF
    if (blob[at:at + 4] != b'NPDE' or at + 0x0B > image['end'] or
            struct.unpack_from('<H', blob, at + 4)[0] not in (0x100, 0x101) or
            struct.unpack_from('<H', blob, at + 6)[0] < 0x0B):
        return None
    return at


def parse_bit(blob, legacy):
    start, end = legacy['start'], legacy['end']
    at, candidates = start, []
    while True:
        at = blob.find(b'\xff\xb8BIT\x00', at, end)
        if at < 0:
            break
        if at + 12 > end:
            raise FormatError('truncated BIT header')
        hs, ts, count = blob[at + 8:at + 11]
        if hs < 12 or ts < 6 or not count or at + hs + ts * count > end:
            raise FormatError('invalid BIT dimensions')
        if sum(blob[at:at + hs]) & 255:
            raise FormatError('BIT header checksum failed')
        tokens = {}
        for i in range(count):
            tid, version, size, pointer = read(blob, '<BBHH', at + hs + i * ts, end=end)
            key = chr(tid)
            if key in tokens:
                raise FormatError('duplicate BIT token ID')
            if pointer + size > legacy['size']:
                raise FormatError('BIT token points outside legacy image')
            tokens[key] = dict(version=version, size=size, data=start + pointer)
        candidates.append(tokens)
        at += 1
    if len(candidates) != 1:
        raise FormatError(f'expected one BIT, found {len(candidates)}')
    return candidates[0]


def image_chains(blob, pci, extended, *, family=None):
    """Select contiguous legacy/EFI/data chains; all bounds come from headers.

    Ampere (family 'ampere') also accepts a legacy image marked last and followed
    directly by its data images (laptop and headless datacenter dumps carry no
    EFI image), and NPDS images stamped with the GA102 base ID 0x2200, which the
    GA102, GA104 and GA106 images all carry. Every data image of a chain must
    carry the same NPDS ID.

    Turing (family 'turing') accepts the same EFI-less chain. Its last data image
    is not flagged last (neither NPDS byte 0x15 nor NPDE byte 0x0a): a type-0x70
    NPDS image (NBSI signature in its body) flagged last, stamped with no device
    (0000) or this chip, ends the chain after the data images. No table is read
    from it.
    """
    by_start = {p['start']: p for p in pci + extended}
    chains = []
    for legacy in pci:
        if legacy['vendor'] != 0x10DE or legacy['type'] != 0:
            continue
        efi = by_start.get(legacy['end'])
        if family in ('ampere', 'turing') and legacy['last'] and efi and efi['type'] == 0xE0 and 'npds' in efi:
            images, cursor = [legacy], legacy['end']
        else:
            if not efi or efi['type'] != 3 or 'pcir' not in efi:
                raise FormatError('legacy image lacks a contiguous EFI image')
            # Generic GOP builds may leave the EFI PCIR identity unstamped (0000:0000),
            # as in the GB20x rule in blackwell.py; any other foreign identity is rejected.
            if (efi['vendor'], efi['device']) not in ((0, 0), (0x10DE, 0), (0x10DE, legacy['device'])):
                raise FormatError('EFI image PCI identity disagrees with legacy image')
            images, cursor = [legacy, efi], efi['end']
        chip = {legacy['device'] & 0xFF80} | ({0x2200} if family == 'ampere' else set())
        first = len(images)
        while cursor in by_start:
            image = by_start[cursor]
            if image['type'] != 0xE0 or 'npds' not in image or image['vendor'] != 0x10DE:
                break
            if image['device'] & 0xFF80 not in chip or (
                    family == 'ampere' and len(images) > first and image['device'] != images[first]['device']):
                raise FormatError('NPDS chip identity disagrees with legacy image')
            images.append(image)
            cursor = image['end']
            if image['last']:
                break
        tail = by_start.get(cursor)
        if (family == 'turing' and len(images) > first and not images[-1]['last'] and tail and
                tail['type'] == 0x70 and 'npds' in tail and tail['vendor'] == 0x10DE and tail['last'] and
                (tail['device'] == 0 or tail['device'] & 0xFF80 in chip)):
            # A loader that reads the NPDE byte would end the chain at a data image it flags last:
            # such a chain is refused instead of being read two ways.
            at = npde(blob, images[-1])
            if at is None or not blob[at + 0x0A] & 0x80:
                images.append(tail)
        if len(images) == first or not images[-1]['last']:
            raise FormatError('NPDS data chain lacks a complete last image')
        chains.append(images)
    return chains
