"""Bounded PCI/NPDS and BIT parsing, independent of total dump size."""
import struct
from .errors import FormatError


def read(blob, fmt, at, *, end=None):
    size = struct.calcsize(fmt)
    if at < 0 or at + size > min(len(blob), len(blob) if end is None else end):
        raise FormatError(f'read outside image at {at:#x} ({size} bytes)')
    return struct.unpack_from(fmt, blob, at)


def fan_curve(blob, at):
    """Stored curve of the fan policy entry at `at`: bytes 14..16 hold three level (%)
    points and bytes 18..29 three (temperature in 1/32 C, RPM) points, '<H' each."""
    return dict(curve_levels=tuple(blob[at + 14:at + 17]),
                curve_points=tuple(read(blob, '<HH', at + 18 + 4 * k) for k in range(3)))


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
    """
    by_start = {p['start']: p for p in pci + extended}
    chains = []
    for legacy in pci:
        if legacy['vendor'] != 0x10DE or legacy['type'] != 0:
            continue
        efi = by_start.get(legacy['end'])
        if family == 'ampere' and legacy['last'] and efi and efi['type'] == 0xE0 and 'npds' in efi:
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
        if len(images) == first or not images[-1]['last']:
            raise FormatError('NPDS data chain lacks a complete last image')
        chains.append(images)
    return chains
