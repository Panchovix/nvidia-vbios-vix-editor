"""Runtime VFE layout document (nvidia-runtime-vfe-layout/v1) of a GB20x image with runtime voltage-offset hooks.

A runtime offset tool writes the VALUE of a hook variable through the driver (BlackwellRom.runtime_hooks); it
trusts the hook slots only through this document, built from the exact image the loader stages:

    {"schema_version": "nvidia-runtime-vfe-layout/v1", "image_sha256": <SHA-256 of the image bytes>,
     "reference_variable": <the untouched stock template variable>,
     "variable_bitmap_hex": <32 bytes>, "equation_bitmap_hex": <1024 bytes>,
     "slots": [{"rail", "field", "wrapper", "next", "variable", "min_uv", "max_uv"}, ...]}

Bit i of a bitmap is byte i // 8, bit i % 8 (LSB first), set for each variable or equation whose type byte is not
0; the unused entries must form one block at the end of each table. A slot is a hook: `field` its role (REL, ALT,
OV or VMIN), `wrapper` the hook equation, `next` the equation it links, `variable` its variable, and min_uv/max_uv
the hook's clamp. Anything else is refused (VbiosError), so a document always holds a complete, consistent set.
"""
import hashlib
import json
import struct
from .blackwell import BlackwellRom
from .errors import VbiosError
from .image import backend, from_bytes, metadata
from .structure import VFE_HOOK_LIMIT_UV, VFE_HOOK_VARIABLE, vfe_hook_equation

SCHEMA = 'nvidia-runtime-vfe-layout/v1'
RAILS = ('NVVDD', 'MSVDD')
FIELDS = ('REL', 'ALT', 'OV', 'VMIN')
VARIABLES = 255          # entries of the GB20x VFE variable table (bit 255 of the mask stays clear)
MASK_BYTES = (32, 1024)  # variable and equation bitmaps
MAX_EQUATION = 0x1FFF


def _refuse(message):
    return VbiosError('VFE_LAYOUT_REFUSED', message)


def _used(blob, base, stride, count, what):
    """Number of used entries (type byte != 0), which must be the first ones of the table."""
    used = [blob[base + stride * i] != 0 for i in range(count)]
    n = used.index(False) if False in used else count
    if any(used[n:]):
        raise _refuse(f'the unused VFE {what} do not form one block at the end of their table')
    return n


def _bitmap(count, size):
    mask = bytearray(size)
    for i in range(count):
        mask[i >> 3] |= 1 << (i & 7)
    return mask.hex()


def _document(image, parser):
    if not isinstance(parser, BlackwellRom):
        raise VbiosError('UNSUPPORTED_ARCHITECTURE', 'a VFE layout exists only for GB20x (RTX 50) images')
    hooks = parser.runtime_hooks()
    if hooks['state'] != 'on':
        detail = f": {hooks['diagnostic']}" if hooks['diagnostic'] else ''
        raise VbiosError('NO_RUNTIME_HOOKS', f"the image has no complete set of runtime voltage-offset hooks "
                         f"(runtime_voltage_offsets is {hooks['state']}{detail})", details={'state': hooks['state']})
    blob = image.blob
    vfe = parser.pointer('P', 0x20)
    variables = vfe + blob[vfe + 1]
    equations = variables + 29 * VARIABLES
    count = blob[vfe + 5] | blob[vfe + 10] << 8
    if count > 8 * MASK_BYTES[1]:
        raise _refuse(f'the VFE table has {count} equations, more than the equation bitmap holds')
    used_v = _used(blob, variables, 29, VARIABLES, 'variables')
    used_e = _used(blob, equations, 25, count, 'equations')
    slots = []
    for s in hooks['slots']:
        wrapper, target, var = s['hook'], s['target'], s['variable']
        where = f"the {s['rail']} {s['role']} hook"
        if s['hook_offset'] != equations + 25 * wrapper or s['variable_offset'] != variables + 29 * var:
            raise _refuse(f'{where} is not in the VFE tables')
        if not (max(wrapper, target) <= MAX_EQUATION and wrapper < used_e and target < used_e):
            raise _refuse(f'{where} or the equation it links is not an equation in use')
        if not var < min(used_v, 0xFF):
            raise _refuse(f'the variable of {where} is not a variable in use')
        entry = blob[equations + 25 * wrapper:equations + 25 * wrapper + 25]
        if entry != vfe_hook_equation(var, target) or blob[s['variable_offset']:s['variable_offset'] + 29] != VFE_HOOK_VARIABLE:
            raise _refuse(f'{where} does not hold the exact hook bytes')
        low, high = struct.unpack_from('<2f', entry, 3)
        slots.append(dict(rail=s['rail'], field=s['role'], wrapper=wrapper, next=target, variable=var,
                          min_uv=int(low), max_uv=int(high)))
    wrappers, nexts, used = ([x[k] for x in slots] for k in ('wrapper', 'next', 'variable'))
    roles = [(x['rail'], x['field']) for x in slots]
    reference = hooks['reference']
    if not 1 <= len(slots) <= 8 or any(r not in RAILS or f not in FIELDS for r, f in roles) or len(set(roles)) != len(roles):
        raise _refuse('the hooks are not one slot per present REL, ALT, OV and VMIN selector of NVVDD and MSVDD')
    if len(set(wrappers)) != len(wrappers) or len(set(used)) != len(used):
        raise _refuse('two slots share a hook equation or a hook variable')
    if set(wrappers) & set(nexts):
        raise _refuse("a hook equation is a slot's linked equation")
    if any((x['min_uv'], x['max_uv']) != (-VFE_HOOK_LIMIT_UV, VFE_HOOK_LIMIT_UV) for x in slots):
        raise _refuse('a hook clamp is not -1250000..1250000 uV')
    if (reference is None or reference in used or not reference < min(used_v, 0xFF) or
            blob[variables + 29 * reference:variables + 29 * reference + 29] != VFE_HOOK_VARIABLE):
        raise _refuse('no untouched stock template variable is left as the reference')
    return dict(schema_version=SCHEMA, image_sha256=hashlib.sha256(blob).hexdigest(), reference_variable=reference,
                variable_bitmap_hex=_bitmap(used_v, MASK_BYTES[0]), equation_bitmap_hex=_bitmap(used_e, MASK_BYTES[1]),
                slots=slots)


def layout_document(image):
    """The v1 layout document (a dict, keys in the schema's order) of a BiosImage; VbiosError when the image is not
    GB20x (UNSUPPORTED_ARCHITECTURE), has no complete set of hooks (NO_RUNTIME_HOOKS) or breaks a rule of the
    document (VFE_LAYOUT_REFUSED)."""
    return _document(image, backend(image))


def layout_bytes(document):
    """The file bytes of a layout document: two-space indented JSON and a final newline."""
    return (json.dumps(document, indent=2, allow_nan=False) + '\n').encode('ascii')


def payload_layout(data, name='<payload>'):
    """layout_bytes of a stored override payload, or None when it is not a GB20x image or has no hooks at all;
    VbiosError for a GB20x payload that does not parse, holds a partial set of hooks or breaks a rule."""
    image = from_bytes(data, name)
    if metadata(image)['architecture']['family'] != 'blackwell-gb20x':
        return None
    parser = backend(image)
    if parser.runtime_hooks()['state'] == 'off':
        return None
    return layout_bytes(_document(image, parser))
