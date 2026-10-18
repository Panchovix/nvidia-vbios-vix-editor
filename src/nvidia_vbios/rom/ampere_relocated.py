"""Experimental Ampere GA10x relocation: representation ampere-relocated-v1.

GA102-GA107 load the same GSP firmware as AD10x, whose override receiver takes at
most 512 KiB counted from the legacy image. GSP addresses tables in a logical view:
the legacy image followed by the contiguous E0 images, EFI skipped. The payload
keeps the bank prefix, the legacy image and the E0 images, and drops the EFI image
and every bank byte after the last E0 image, so the logical view is unchanged with
bias 0. No byte inside any image is modified and no pointer moves. Anything that
does not verify is refused. Output is not hardware validated and is not accepted by
the lifecycle configuration; it is a transport payload for a loader.
"""
import struct
from ..families import GA100_DEVICE_IDS
from .errors import FormatError, VbiosError
from .tables import TableRom
from .ada_general import PROBES, _values
from . import _ada_relocation as recipe

REPRESENTATION = 'ampere-relocated-v1'
GSP_LIMIT = recipe.RECEIVER_LIMIT
POLICY_ROLES = ('slot_power', 'slot_current', 'input_current', 'connector_power', 'connector_current', 'connector_sum',
                'nvvdd_current')
# Further logical pointers into the NPDS images seen on the GA10x corpus (u v1 size 17,
# i v2, B v2); kept apart from the reviewed Ada recipe's POINTER_FIELDS.
EXTRA_POINTER_FIELDS = (('u', 0x0D), ('i', 0x58), ('B', 0x21))


def walk(blob, legacy_start):
    """Host-loader chain walk; only legacy [+ one EFI image] + E0 images ending the chain."""
    images = recipe.walk_chain(blob, legacy_start)
    types = [i['type'] for i in images]
    data = types[2:] if types[1:2] == [3] else types[1:]
    if types[0] != 0 or not data or any(t != 0xE0 for t in data):
        raise recipe.RelocationError(f'chain is not legacy [+ EFI] + NPDS images: {[hex(t) for t in types]}')
    return images


def pointer_fields(view, tokens):
    """Nonzero values of the known BIT pointer fields; P/C/M extents follow the token size."""
    fields = {}
    for tid, (offsets, version, _) in recipe.POINTER_FIELDS.items():
        token = tokens.get(tid)
        if token is None:
            continue
        if token['version'] != version:
            raise recipe.RelocationError(f'BIT token {tid} version {token["version"]} is not {version}')
        if offsets in ('all', 'from5'):
            offsets = range(0 if offsets == 'all' else 5, token['size'] - 3, 4)
        elif max(offsets) + 4 > token['size']:
            raise recipe.RelocationError(f'BIT token {tid} is too short for its pointer fields')
        for off in offsets:
            value = recipe.u32(view, token['data'] + off)
            if value:
                fields[f'{tid}+{off:#x}'] = value
    for tid, off in EXTRA_POINTER_FIELDS:
        token = tokens.get(tid)
        if token is not None and off + 4 <= token['size']:
            value = recipe.u32(view, token['data'] + off)
            if value:
                fields[f'{tid}+{off:#x}'] = value
    return fields


def verify_payload(bank, payload, legacy_start):
    """Re-derive the source logical view and check the payload against it."""
    source = walk(bank, legacy_start)
    view, _, legacy_length = recipe.logical_view(bank, source)
    if len(view) > GSP_LIMIT:
        raise recipe.DoesNotFit(f'the legacy and NPDS images alone are {len(view)} bytes')
    if payload[:legacy_start] != bank[:legacy_start]:
        raise recipe.RelocationError('bank prefix differs from the source bank')
    if payload[legacy_start:] != view:
        raise recipe.RelocationError('payload differs from the source logical view')
    images = walk(payload, legacy_start)
    if [(i['type'], i['length']) for i in images] != [(i['type'], i['length']) for i in source if i['type'] != 3]:
        raise recipe.RelocationError('payload chain shape differs from the source legacy and NPDS images')
    view2, bias, _ = recipe.logical_view(payload, images)
    if bias != 0 or view2 != view:
        raise recipe.RelocationError('payload logical view or bias is wrong')
    sums = [sum(payload[i['start']:i['start'] + i['length']]) & 0xFF for i in images]
    if any(sums):
        raise recipe.RelocationError(f'image checksums are not zero: {sums}')
    if recipe.host_parser(payload, recipe.u32(bank, source[0]['ds'] + 4)) != legacy_start:
        raise recipe.RelocationError('host loader parser rejects the payload')
    _, tokens = recipe.parse_bit(view, legacy_length)
    fields = pointer_fields(view, tokens)
    fields.update({f'{tid} data': t['data'] for tid, t in tokens.items() if t['data']})
    beyond = {name: value for name, value in fields.items() if value >= len(view)}
    if beyond:
        raise recipe.RelocationError(f'BIT pointers reach past the {len(view)}-byte logical view, '
                                     f'into bytes the payload drops: {sorted(beyond)[:8]}')
    starts = [i['start'] - legacy_start for i in images[1:]]
    fake, tolerated = recipe.unexpected_signatures(view, view, starts, True)
    if fake:
        raise recipe.RelocationError(f'unexpected image signatures at logical {[hex(o) for o in fake]}')
    efi = source[1] if source[1]['type'] == 3 else None
    end = source[-1]['start'] + source[-1]['length']
    return dict(chain=[dict(type=i['type'], start=i['start'], length=i['length'], last=i['last'])
                       for i in images],
                source_chain=[dict(type=i['type'], start=i['start'], length=i['length']) for i in source],
                gsp_bytes=len(view), gsp_limit=GSP_LIMIT,
                dropped=dict(efi_bytes=efi['length'] if efi else 0, after_chain_bytes=len(bank) - end),
                checks=['payload equals bank prefix + source logical view', 'chain legacy + NPDS, bias 0',
                        'image checksums zero', 'host loader parser selects the legacy image',
                        'one BIT header', 'known BIT pointers inside the logical view',
                        'no unexpected image signatures'],
                pointer_fields_checked=len(fields), preexisting_signatures_tolerated=tolerated)


def semantic_probes(source, payload, legacy_ds):
    """Compare parser readings of the source bank with the payload read at bias 0, as GSP does.

    The table parser expects an EFI image after a legacy image not marked last; a
    scratch copy with the legacy PCIR last flag set takes its EFI-less path instead.
    """
    scratch = bytearray(payload)
    scratch[legacy_ds + 0x15] |= 0x80
    relocated = TableRom(bytes(scratch), '<relocated payload>', family='ampere')
    probes = [(name, name, ()) for name in PROBES]
    probes += [(f'ampere_policies({role})', 'ampere_policies', (role,)) for role in POLICY_ROLES]
    result = {}
    for label, name, args in probes:
        try:
            before = getattr(source, name)(*args)
        except FormatError as exc:
            result[label] = f'not parsed ({exc}); bytes verified only'
            continue
        if _values(getattr(relocated, name)(*args)) != _values(before):
            raise recipe.RelocationError(f'{label} readings differ in the payload')
        result[label] = 'equal'
    return result


def relocate(bank_parser):
    """Export the normalized primary bank of a GA10x image, or refuse with a VbiosError."""
    bank, legacy = bank_parser.blob, bank_parser.legacy
    if getattr(bank_parser, 'family', None) != 'ampere' or legacy['device'] in GA100_DEVICE_IDS:
        raise VbiosError('UNREVIEWED_RELOCATION_SOURCE',
                         f'{REPRESENTATION} applies only to Ampere GA102-GA107 images')
    start = legacy['start']
    try:
        images = walk(bank, start)
        data = [i for i in images if i['type'] == 0xE0]
        legacy_end = start + images[0]['length']
        payload = bank[:legacy_end] + bank[data[0]['start']:data[-1]['start'] + data[-1]['length']]
        proof = verify_payload(bank, payload, start)
        proof['semantic_probes'] = semantic_probes(bank_parser, payload, images[0]['ds'])
    except recipe.DoesNotFit as exc:
        raise VbiosError('RELOCATION_DOES_NOT_FIT',
                         f'this Ampere image does not fit the {GSP_LIMIT}-byte GSP limit: {exc}') from exc
    except (recipe.RelocationError, IndexError, KeyError, ValueError, struct.error) as exc:
        raise VbiosError('RELOCATION_VERIFICATION_FAILED',
                         f'experimental Ampere relocation refused: {exc}') from exc
    return payload, proof
