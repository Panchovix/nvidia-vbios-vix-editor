"""Closed recognition and conversion of two reviewed AD107 runtime payloads.

The format is ada-relocated-v1, not a generic no-EFI Ada format. Conversion
requires the exact reviewed source archive or primary bank, replays the pure
vendored recipe and verifies every output byte plus the full output digest.
Runtime inspection is read-only; backend/table parsing remains unchanged.
No files, GPU APIs, driver state or firmware signatures are modified here.
"""
import hashlib
from .errors import FormatError, VbiosError
from .structure import parse_bit, scan_images

REPRESENTATION = 'ada-relocated-v1'
RECIPE_VERSION = 'ada-relocation-recipe/v1'
BANK_SHA256 = 'aaf1abb66575d9e36fdf7955d5d86c9b0cf54e3e78dd0d419e0816411c2cb627'
ARCHIVE_SHA256 = '8d0c8ae2f188cd991feb627a8c7417488af47fa3003fbceec2c4abcc367a4a0a'
PAYLOAD_SHA256 = 'cc194a71822cd5cc0c0c7390f7841b72daebcbb268ffec8aeef9036a7558fc50'
BANK_SIZE = 917504
ARCHIVE_SIZE = 2048000
PAYLOAD_SIZE = 560640
HOST_SKIP = 37888
GSP_BYTES = 522752
# Public constants above retain the original successful boot-trial tuple.
# These two tuples are internal format evidence, not a caller-extensible registry.
# payload SHA256 -> (matching full archive, primary bank, hardware validation)
_VARIANTS = {
    PAYLOAD_SHA256: (ARCHIVE_SHA256, BANK_SHA256, 'boot trial'),
    'd2455c82289687a50022465d78c3c3c127ccd4bfb141508588a93bfc5b63e2ae': (
        '4948b4d8f975800432b65733c7270296f47fb3eac086b42dacd895cdf2fec2f0',
        'fb20a772e21b292b4714f9c395af68c66c8d374c9a373141c9cb435a1c43a4e1',
        'boot trial, clock-range variant'),
}
_INPUTS = {pin: payload for payload, (archive, bank, _) in _VARIANTS.items()
           for pin in ((ARCHIVE_SIZE, archive), (BANK_SIZE, bank))}


def recognize_payload(blob):
    """Return format integrity evidence only for the complete pinned bytes.

    Hash equality never broadens backend() or makes EFI optional. Mutants,
    including checksum-correct mutations and alternate IFR prefixes, return None.
    Bounds/checksums/BIT identity are independently rechecked after the digest.
    """
    if len(blob) != PAYLOAD_SIZE:
        return None
    payload_sha256 = hashlib.sha256(blob).hexdigest()
    variant = _VARIANTS.get(payload_sha256)
    if variant is None:
        return None
    archive_sha256, bank_sha256, hardware_validation = variant
    pci, npds, issues = scan_images(blob)
    ordered = sorted(pci + npds, key=lambda p: p['start'])
    expected = [(HOST_SKIP, 64512, 0, False),
                (HOST_SKIP + 64512, 24576, 0xE0, False),
                (HOST_SKIP + 89088, 433664, 0xE0, True)]
    shape = [(p['start'], p['size'], p['type'], p['last']) for p in ordered]
    if issues or len(pci) != 1 or len(npds) != 2 or shape != expected:
        raise FormatError('pinned Ada relocation lost its reviewed image-chain shape')
    if (pci[0]['vendor'], pci[0]['device']) != (0x10DE, 0x28B0) or any(
            p['vendor'] != 0x10DE or p['device'] & 0xFF80 != 0x2880 for p in npds):
        raise FormatError('pinned Ada relocation lost PCI identity')
    tokens = parse_bit(blob, pci[0])
    if tokens.get('P', {}).get('version') != 2:
        raise FormatError('pinned Ada relocation lost its BIT identity')
    checksums = [dict(start=p['start'], end=p['end'], checksum=sum(blob[p['start']:p['end']]) & 255)
                 for p in ordered]
    if any(p['checksum'] for p in checksums):
        raise FormatError('pinned Ada relocation image checksum failed')
    return {
        'format': REPRESENTATION,
        'integrity': {'valid': True, 'image_checksums': checksums,
                      'pinned_payload_sha256': payload_sha256,
                      'cryptographic_signature': 'not verified',
                      'scope': 'exact reviewed relocated payload digest, bounded chain, BIT and image checksums'},
        'representation': {'name': REPRESENTATION, 'recipe_version': RECIPE_VERSION,
                           'reviewed_input_bank_sha256': bank_sha256,
                           'reviewed_input_archive_sha256': archive_sha256,
                           'output_sha256': payload_sha256, 'host_skip': HOST_SKIP,
                           'gsp_bytes': GSP_BYTES, 'efi_present': False,
                           'editable': False, 'hardware_validation': hardware_validation,
                           'scope': 'exact reviewed AD107 payload; no general Ada or future-driver capacity claim'},
    }


def relocate(source_blob, normalized_bank):
    """Reproduce the matching reviewed tuple from a strict normalized input.

    The image API checks the full ordinary source with its existing backend
    before calling this helper. Full archive and primary-bank pins are both
    checked: an unchanged primary bank in a modified archive is insufficient.
    """
    source_pin = (len(source_blob), hashlib.sha256(source_blob).hexdigest())
    expected_payload = _INPUTS.get(source_pin)
    if expected_payload is None:
        raise VbiosError('UNREVIEWED_RELOCATION_SOURCE',
                         'ada-relocated-v1 requires the exact reviewed archive or primary bank')
    expected_bank = _VARIANTS[expected_payload][1]
    if len(normalized_bank) != BANK_SIZE or hashlib.sha256(normalized_bank).hexdigest() != expected_bank:
        raise VbiosError('UNREVIEWED_RELOCATION_SOURCE', 'Ada primary bank differs from the reviewed relocation input')
    from . import _ada_relocation as recipe
    try:
        plan = recipe.plan_for(normalized_bank)
        output = recipe.render(plan, normalized_bank)
        recipe.verify_payload(normalized_bank, output)
    except (recipe.RelocationError, IndexError, KeyError, ValueError) as exc:
        raise VbiosError('RELOCATION_VERIFICATION_FAILED', 'Ada relocation failed complete recipe verification') from exc
    if hashlib.sha256(output).hexdigest() != expected_payload or recognize_payload(output) is None:
        raise VbiosError('RELOCATION_VERIFICATION_FAILED', 'Ada relocation differs from the exact reviewed runtime payload')
    return output
