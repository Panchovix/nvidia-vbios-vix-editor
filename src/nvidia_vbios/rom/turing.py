"""Experimental Turing loader payload ending at the last data image: representation turing-e0-end-v1.

A Turing chain (legacy [+ EFI] + E0 + E0) ends with a small type-0x70 NPDS image
flagged last (NBSI signature in its body); its last E0 image carries no last-image
flag. GA10x/AD10x chains end at their last E0 image, which carries both flags (bit 7
of NPDS byte 0x15 and of NPDE byte 0x0a), and keep the type-0x70 image outside the
chain. This payload keeps the normalized primary bank up to the end of the last E0
image, sets those two flags there, repairs that image's additive checksum and drops
the type-0x70 image and every later bank byte. No other byte changes and no pointer
moves. Whether GSP needs the type-0x70 image (it holds a signed digest list over
tables of the E0 images) is unknown; this payload lets a tester compare.
"""
from .errors import FormatError, VbiosError
from .structure import npde
from .tables import TableRom

REPRESENTATION = 'turing-e0-end-v1'
LAST_IMAGE = 0x80  # bit 7 of NPDS byte 0x15 and of NPDE byte 0x0a


def e0_end(bank_parser):
    """Payload of a normalized single-bank Turing image whose chain ends at its last E0 image.

    A bank that already ends there is returned up to that image's end.
    """
    if getattr(bank_parser, 'family', None) != 'turing' or len(bank_parser.chains) != 1:
        raise VbiosError('UNREVIEWED_RELOCATION_SOURCE', f'{REPRESENTATION} applies only to one Turing bank')
    chain = bank_parser.chains[0]
    if chain[-1]['type'] == 0xE0:
        return bank_parser.blob[:chain[-1]['end']]
    tail, last = chain[-1], chain[-2]
    blob = bytearray(bank_parser.blob[:last['end']])
    at = npde(blob, last) if tail['type'] == 0x70 and last['type'] == 0xE0 else None
    if at is None:
        raise VbiosError('RELOCATION_VERIFICATION_FAILED', f'{REPRESENTATION} refused: the chain does not end with '
                         'a type-0x70 image after an E0 image with an NPDE last-image byte')
    if blob[last['end'] - 16:last['end'] - 1] != b'\xff' * 15:
        raise VbiosError('RELOCATION_VERIFICATION_FAILED',
                         f'{REPRESENTATION} refused: the last E0 image lacks the reviewed checksum padding')
    flags = (last['npds'] + 0x15, at + 0x0A, last['end'] - 1)
    blob[flags[0]] |= LAST_IMAGE
    blob[flags[1]] |= LAST_IMAGE
    blob[flags[2]] = (blob[flags[2]] - sum(blob[last['start']:last['end']])) & 0xFF
    try:
        result = TableRom(bytes(blob), f'<{REPRESENTATION}>', family='turing')
    except FormatError as exc:
        raise VbiosError('RELOCATION_VERIFICATION_FAILED', f'{REPRESENTATION} refused: {exc}') from exc
    shape = lambda images: [(p['type'], p['start'], p['end']) for p in images]
    changed = {i for i in range(len(blob)) if blob[i] != bank_parser.blob[i]}
    if (len(result.chains) != 1 or shape(result.chains[0]) != shape(chain[:-1]) or not result.chains[0][-1]['last']
            or not result.integrity()['valid'] or result.legacy['device'] != bank_parser.legacy['device']
            or not changed <= set(flags)):
        raise VbiosError('RELOCATION_VERIFICATION_FAILED',
                         f'{REPRESENTATION} refused: the payload chain, integrity or PCI identity differs')
    return bytes(blob)
