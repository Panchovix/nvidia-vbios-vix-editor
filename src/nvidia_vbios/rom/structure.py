"""Bounded PCI/NPDS and BIT parsing, independent of total dump size."""
import math
import struct
from .errors import FormatError

# Quadratic coefficients below this are float residue (corpus: at most 5e-9; real slopes are 35 and up).
VFE_RESIDUE = 1e-6
# Bit 4 of a compare equation's output byte (23): the criterion is the value of the equation named by
# bytes 11/12 (u16), not the float there (GSP-RM 615.78.08 VFE parser 0x119dd48, for every entry size).
VFE_CRITERION_EQUATION = 0x10
# Output clamp (bytes 3..10) of a VFE equation that clamps nothing: -FLT_MAX, +FLT_MAX. Every min/max
# and compare root of a VMIN tree in the corpus stores it; a fixed VMIN writes minimum = maximum there.
VFE_UNCLAMPED = bytes.fromhex('ffff7fffffff7f7f')


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


# Default GPC VF curve offset: a constant MHz equation linked from the GPC root (MHz).
GPC_CURVE_OFFSET_LIMIT = 500


def vfe_free_slot(size):
    """Bytes of an unused VFE equation slot: type 0, no links, zero floats (u16-link layouts end in 0xff)."""
    return bytes((0, 0xFF, 0xFF)) + bytes(20) + (bytes((0, 0xFF)) if size == 25 else bytes(1))


def vfe_constant_mhz(size, var, value):
    """A constant MHz equation: type 1 on var, no next link, minimum = maximum = constant = value, zero slopes."""
    return (bytes((1, var, 0xFF)) + struct.pack('<5f', value, value, value, 0.0, 0.0) + bytes((1,)) +
            (bytes((0xFF,)) if size == 25 else b''))


def vfe_referrers(blob, base, size, width, count):
    """Equation index -> [(referrer index, 'next', 'child' or 'criterion')]: who links each equation.

    Kinds 1, 4 and 7 link only their next equation; min/max (2) and compare (3) also link
    two children (bytes 11/12 and 15/16, u16 high bytes 4 further on). A compare whose
    output byte (23) has bit 4 set compares its variable with the value of the equation
    named by bytes 11/12 (GSP-RM 615.78.08 VFE parser 0x119dd48 keeps those 16 bits instead
    of the float criterion, for every entry size; the GB20x VMIN trees use it for their
    fused bin), so that equation is linked too ('criterion').
    """
    none, result = (1 << 8 * width) - 1, {}
    high = (lambda e, k: e[k + 4] << 8) if width == 2 else (lambda e, k: 0)
    for i in range(count):
        e = blob[base + size * i:base + size * i + size]
        if e[0] not in (0, 1, 2, 3, 4, 7):
            raise FormatError("unreviewed VFE equation kind")
        if not e[0]:
            continue
        links = [(e[2] | ((e[24] << 8) if width == 2 else 0), 'next')]
        if e[0] == 2:
            links += [(e[11] | high(e, 11), 'child'), (e[12] | high(e, 12), 'child')]
        elif e[0] == 3:
            links += [(e[15] | high(e, 15), 'child'), (e[16] | high(e, 16), 'child')]
            if e[23] & VFE_CRITERION_EQUATION:
                links.append((e[11] | e[12] << 8, 'criterion'))
        for x, kind in links:
            if x != none:
                result.setdefault(x, []).append((i, kind))
    return result


def vfe_tree(blob, base, size, width, count, root):
    """Indices of the equations the VFE equation `root` evaluates: itself and everything its next links,
    children and criterion equations reach (vfe_referrers' links), in walk order; FormatError on an
    index outside the table."""
    none, high = (1 << 8 * width) - 1, (lambda e, k: e[k + 4] << 8) if width == 2 else (lambda e, k: 0)
    order, seen, pending = [], set(), [root]
    while pending:
        i = pending.pop()
        if i in seen:
            continue
        if not 0 <= i < count:
            raise FormatError("VFE tree link outside the equation table")
        seen.add(i)
        order.append(i)
        e = blob[base + size * i:base + size * i + size]
        links = [e[2] | ((e[24] << 8) if width == 2 else 0)] if e[0] else []
        if e[0] == 2:
            links += [e[11] | high(e, 11), e[12] | high(e, 12)]
        elif e[0] == 3:
            links += [e[15] | high(e, 15), e[16] | high(e, 16)]
            if e[23] & VFE_CRITERION_EQUATION:
                links.append(e[11] | e[12] << 8)
        pending.extend(reversed([x for x in links if x != none]))
    return order


def vfe_clamp_state(blob, at):
    """('unclamped', None) for a VFE equation at `at` whose output clamp is VFE_UNCLAMPED, ('pinned', uV)
    for a finite clamp whose minimum equals its maximum and is a whole uV, else (None, None)."""
    if blob[at + 3:at + 11] == VFE_UNCLAMPED:
        return 'unclamped', None
    lo, hi = struct.unpack_from('<ff', blob, at + 3)
    if math.isfinite(lo) and lo == hi and lo == int(lo):
        return 'pinned', lo
    return None, None


def quadratic_span(blob, at, variables, variable_size):
    """(lowest, highest) float32 value of the quadratic VFE equation at `at` over its variable's stored range,
    or None.

    The quadratic is constant + slope x + curvature x^2 (floats at bytes 11, 15 and 19) on the variable
    named by byte 1, whose entry at variables + variable_size x index stores its range as floats at bytes
    1 and 5. The extremes (the range ends and an inner vertex) are computed in double precision and
    rounded to float32, so equal results give equal stored bytes.
    """
    c0, c1, c2 = struct.unpack_from('<fff', blob, at + 11)
    entry = variables + variable_size * blob[at + 1]
    if entry + 9 > len(blob):
        return None
    lo, hi = struct.unpack_from('<ff', blob, entry + 1)
    if not all(math.isfinite(x) and abs(x) < 1e30 for x in (c0, c1, c2, lo, hi)) or lo > hi:
        return None
    points = [lo, hi] + ([-c1 / (2 * c2)] if c2 and lo < -c1 / (2 * c2) < hi else [])
    exact = [c0 + c1 * x + c2 * x * x for x in points]
    if not all(abs(v) < 1e30 for v in exact):
        return None
    values = [struct.unpack('<f', struct.pack('<f', v))[0] for v in exact]
    return min(values), max(values)


def vfe_reference_counts(blob, base, size, width, count):
    """How many times each equation index is referenced (next links and min/max and compare children)."""
    return {index: len(who) for index, who in vfe_referrers(blob, base, size, width, count).items()}


def gpc_curve_slot(blob, base, size, width, count, root):
    """Where a default GPC curve offset lives in the VFE table, or FormatError.

    The GPC root (a compare node with MHz output that no equation references) gets a
    next link to a constant MHz equation in the first unused slot; the driver adds a
    next equation to the clamped value (as the voltage equations show), so every
    point of the curve moves by that constant (inferred). Returns the root and slot
    offsets, the link byte offsets and the current offset (0 without a link, else the
    linked constant, which only the root may reference).
    """
    none = (1 << 8 * width) - 1
    if not 0 <= root < count:
        raise FormatError("GPC root outside the VFE table")
    at = base + size * root
    e = blob[at:at + size]
    refs = vfe_reference_counts(blob, base, size, width, count)
    if e[0] != 3 or e[23] & 15 != 1 or refs.get(root):
        raise FormatError("unreviewed GPC root equation")
    links = [at + 2] + ([at + 24] if width == 2 else [])
    nxt = e[2] | ((e[24] << 8) if width == 2 else 0)
    if nxt == none:
        slot = next((i for i in range(count) if not blob[base + size * i]), None)
        if (slot is None or slot >= none or refs.get(slot) or
                blob[base + size * slot:base + size * slot + size] != vfe_free_slot(size)):
            raise FormatError("no clean free VFE slot for a GPC curve offset")
        current = 0
    else:
        slot = nxt
        s = blob[base + size * slot:base + size * slot + size] if slot < count else b''
        value = struct.unpack_from('<f', s, 11)[0] if len(s) == size else None
        if (value is None or s != vfe_constant_mhz(size, e[1], value) or refs.get(slot) != 1 or
                not math.isfinite(value) or value != int(value) or abs(value) > GPC_CURVE_OFFSET_LIMIT or not value):
            raise FormatError("the GPC root links an equation outside the reviewed offset shape")
        current = int(value)
    return dict(root=root, root_offset=at, var=e[1], link_offsets=links, slot=slot,
                slot_offset=base + size * slot, size=size, width=width, current=current)


def fan_curve(blob, at):
    """Stored curve of the fan policy entry at `at`: bytes 14..16 hold three level (%)
    points and bytes 18..29 three (temperature in 1/32 C, RPM) points, '<H' each."""
    return dict(curve_levels=tuple(blob[at + 14:at + 17]),
                curve_points=tuple(read(blob, '<HH', at + 18 + 4 * k) for k in range(3)))


def vfe_range(blob, base, size, width, count, index, seen=frozenset(), *, clamped_children=False):
    """(lowest, highest) uV of the VFE equation list at index, or None when it is not bounded.

    Each equation is clamped to its own float bounds (bytes 3/7) and its next link
    (byte 2, | byte 24 << 8 when links are u16) is added, as the RTX 2000 Ada VMIN
    shows (clamp 560 mV, driver 650 mV). A quadratic (1) whose slopes are float
    residue is its constant (byte 11); otherwise a quadratic or the GB20x type 7
    polynomial is bounded by its clamp alone. Min/max (2) and compare (3) span
    their two children (bytes 11/12 and 15/16, u16 high bytes 4 further on).
    Other kinds or output units, indices outside the table and cycles give None,
    and so does a list that no clamp bounds; a missing link (index 0xff/0xffff) is
    an empty list, (0, 0). A child that nothing bounds leaves its min/max or compare
    unbounded too, unless clamped_children: then that node's own clamp bounds it
    (the VMIN bounds use it, for the compare REL of the RTX 4060 family and the
    RTX 4070 Ti SUPER, clamped to 1015..1090 mV over a chain with an unclamped slope).
    """
    span = _vfe_span(blob, base, size, width, count, index, seen, clamped_children)
    return span if span is not None and all(math.isfinite(v) for v in span) else None


def _vfe_span(blob, base, size, width, count, index, seen, clamped_children):
    """vfe_range with -inf/+inf for the unbounded ends; None for a list it cannot read."""
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
            children = [_vfe_span(blob, base, size, width, count, e[k] | (e[k + 4] << 8 if width == 2 else 0), seen,
                                  clamped_children) for k in ((11, 12) if e[0] == 2 else (15, 16))]
            if None in children or not clamped_children and not all(math.isfinite(v) for c in children for v in c):
                return None
            span = (min(c[0] for c in children), max(c[1] for c in children))
        else:
            return None
        # A +-FLT_MAX clamp bounds nothing.
        lo, hi = (v if abs(v) < 1e30 else math.copysign(math.inf, v) for v in (lo, hi))
        low, high = low + min(max(span[0], lo), hi), high + max(min(span[1], hi), lo)
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
