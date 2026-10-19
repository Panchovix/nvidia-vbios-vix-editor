"""Experimental general Ada relocation: representation ada-relocated-v2.

The pins of the reviewed ada-relocated-v1 recipe are re-derived from the ROM itself
(_ada_relocation.derive_pins) and the same pure plan/render/verify functions run with
the stricter general checks. Where the table parser understands the power, clock,
rail or fan variant, the values it reads through the relocated pointers must equal the
source values; other tables rely on the byte accounting of verify_payload. Anything
that does not verify is refused. Output is not hardware validated and is not
accepted by the lifecycle configuration; it is a transport payload for a loader.
"""
import struct
from .errors import FormatError, VbiosError
from .tables import TableRom
from . import _ada_relocation as recipe

REPRESENTATION = 'ada-relocated-v2'
GSP_LIMIT = recipe.RECEIVER_LIMIT
PROBES = ('power_rows', 'clock_ranges', 'rail_limits', 'rail_equations', 'fan_coolers')


def _values(item):
    """Parser output without file positions, which legitimately move."""
    if isinstance(item, dict):
        return {k: _values(v) for k, v in item.items() if not (k.endswith('offset') or k == 'rail_entry')}
    if isinstance(item, list):
        return [_values(v) for v in item]
    return item


def semantic_probes(source, plan, payload):
    """Compare parser readings of the source bank with the relocated payload.

    The payload omits the EFI image, which the table parser requires; the source EFI
    image is reinserted in memory only, restoring the source logical-to-file mapping.
    """
    start, legacy_length = plan['pins']['legacy_start'], plan['legacy_length']
    efi = source.efi
    rebuilt = (payload[:start + legacy_length] + source.blob[efi['start']:efi['end']]
               + payload[start + legacy_length:])
    relocated = TableRom(rebuilt, '<relocated payload>', family='ada')
    result = {}
    for name in PROBES:
        try:
            before = getattr(source, name)()
        except FormatError as exc:
            result[name] = f'not parsed ({exc}); bytes verified only'
            continue
        if _values(getattr(relocated, name)()) != _values(before):
            raise recipe.RelocationError(f'{name} readings differ after relocation')
        result[name] = 'equal'
    return result


def relocate(bank_parser):
    """Relocate the normalized primary bank of an Ada image, or refuse with a VbiosError."""
    bank = bank_parser.blob
    if bank_parser.family != 'ada':
        raise VbiosError('UNREVIEWED_RELOCATION_SOURCE', 'Ada relocation applies only to Ada images')
    try:
        pins = recipe.derive_pins(bank, bank_parser.legacy['start'])
        plan = recipe.plan_for(bank, pins)
        payload = recipe.render(plan, bank)
        proof = recipe.verify_payload(bank, payload, pins)
        proof['semantic_probes'] = semantic_probes(bank_parser, plan, payload)
    except recipe.LaptopDoesNotFit as exc:
        raise VbiosError('RELOCATION_DOES_NOT_FIT',
                         'Ada laptop images are not supported yet: their laptop-only performance tables leave no '
                         f'room to relocate the image under the {GSP_LIMIT}-byte GSP limit ({exc})') from exc
    except recipe.DoesNotFit as exc:
        raise VbiosError('RELOCATION_DOES_NOT_FIT',
                         f'this Ada image cannot be relocated under the {GSP_LIMIT}-byte GSP limit: {exc}') from exc
    except (recipe.RelocationError, IndexError, KeyError, ValueError, struct.error) as exc:
        raise VbiosError('RELOCATION_VERIFICATION_FAILED',
                         f'experimental Ada relocation refused: {exc}') from exc
    if len(payload) - bank_parser.legacy['start'] > GSP_LIMIT:
        raise VbiosError('RELOCATION_DOES_NOT_FIT', 'relocated payload exceeds the GSP limit')
    return payload, proof
