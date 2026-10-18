"""Immutable image and version-1 inspection API."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from . import ada_general, ampere_relocated, turing
from .ada_relocated import REPRESENTATION, recognize_payload, relocate
from .architecture import architecture
from .blackwell import BlackwellRom
from .errors import VbiosError, FormatError
from .structure import scan_images
from .tables import TableRom


@dataclass(frozen=True)
class BiosImage:
    blob: bytes
    name: str = '<memory>'
    source_sha256: str | None = None
    source_path: str | None = None

    def __post_init__(self):
        object.__setattr__(self, 'blob', bytes(self.blob))
        object.__setattr__(self, 'name', str(self.name))
        if self.source_sha256 is None:
            object.__setattr__(self, 'source_sha256', self.sha256)

    @property
    def sha256(self):
        return hashlib.sha256(self.blob).hexdigest()

    @property
    def report(self):
        return inspect_image(self)

    def override_blob(self):
        return normalize(self).blob


def from_bytes(blob, name='<memory>'):
    try:
        return BiosImage(bytes(blob), str(name))
    except (TypeError, ValueError) as exc:
        raise VbiosError('INVALID_IMAGE', 'ROM data must be bytes-compatible') from exc


def load(path):
    try:
        path = Path(path)
        return BiosImage(path.read_bytes(), str(path), source_path=str(path.resolve()))
    except (OSError, TypeError, ValueError) as exc:
        raise VbiosError('IO_ERROR', f'cannot read ROM: {exc}') from exc


def metadata(image):
    if not isinstance(image, BiosImage):
        raise VbiosError('INVALID_IMAGE', 'operation requires an immutable BiosImage')
    pci, extended, issues = scan_images(image.blob)
    legacy = [p for p in pci if p['vendor'] == 0x10DE and p['type'] == 0]
    devices = sorted({p['device'] for p in legacy})
    versions = sorted({m.group().decode('ascii') for m in re.finditer(
        rb'9[0-9]\.[0-9A-Fa-f]{2}\.[0-9A-Fa-f]{2}\.[0-9A-Fa-f]{2}\.[0-9A-Fa-f]{2}', image.blob)})
    arch = architecture(devices[0], versions, editor=True) if len(devices) == 1 else dict(
        family='unknown', product='ambiguous or missing PCI identity', in_scope=False,
        bios_family_consistent=False, evidence=[], reason='requires a unique NVIDIA legacy PCI identity')
    return dict(schema_version=1, file=image.name, size=len(image.blob), sha256=image.sha256,
                source_sha256=image.source_sha256, versions=versions,
                pci_device=f'10de:{devices[0]:04x}' if len(devices) == 1 else None,
                pci_images=pci, npds_images=extended, architecture=arch, diagnostics=issues)


def backend(image, *, require_scope=True):
    info = metadata(image)
    arch = info['architecture']
    if info['diagnostics']:
        raise FormatError('invalid image boundaries', details={'issues': info['diagnostics']})
    if require_scope and not arch['in_scope']:
        raise VbiosError('UNSUPPORTED_ARCHITECTURE', arch['reason'], details={'architecture': arch})
    if require_scope and not arch['bios_family_consistent']:
        raise VbiosError('ARCHITECTURE_MISMATCH', 'PCI architecture and BIOS version family do not agree',
                         details={'architecture': arch})
    if arch['family'] == 'blackwell-gb20x':
        return BlackwellRom(image.blob, image.name)
    if arch['family'] in ('ada', 'ampere', 'turing'):
        return TableRom(image.blob, image.name, family=arch['family'])
    raise FormatError('no supported parser for this architecture')


def inspect_image(image):
    info = metadata(image)
    checksums = [dict(start=p['start'], end=p['end'], checksum=sum(image.blob[p['start']:p['end']]) & 255)
                 for p in info['pci_images'] + info['npds_images']]
    info['integrity'] = dict(valid=None, image_checksums=checksums,
                             cryptographic_signature='not verified',
                             scope='raw image checksums only; full format unrecognized')
    info['format'] = None
    info['capabilities'] = {'inspect': {'status': 'supported'},
                            'edit': {'status': 'unsupported'},
                            'normalize': {'status': 'unsupported'},
                            'vbios': {'writable': 'unknown', 'editable_fields': [],
                                      'scope': 'offline image bytes', 'persistence': 'unknown'},
                            'runtime': {'writable': 'unknown', 'evaluated_values': None,
                                        'applied': 'unknown',
                                        'reason': 'offline inspection performs no GPU queries'}}
    info['fields'] = []
    runtime = recognize_payload(image.blob)
    if runtime is not None:
        # This closed runtime representation is deliberately outside backend().
        # It has no editable table bindings, including through custom registries.
        info.update(runtime)
        info['capabilities']['edit'] = {'status': 'unsupported',
                                        'reason': 'reviewed relocated runtime payload is read-only'}
        info['capabilities']['normalize'] = {'status': 'supported', 'reason': 'identity transformation'}
        info['capabilities']['vbios'].update(writable='unsupported', editable_fields=[])
        info['duplicate_chain_count'] = 1
        return info
    try:
        parser = backend(image)
        info['format'] = 'gb20x-object-directory-v3' if isinstance(parser, BlackwellRom) else 'pci-bit-npds-v3x'
        info['integrity'] = parser.integrity()
        info['integrity']['scope'] = 'recognized format integrity; cryptographic signatures unverified'
        from ..editor.registry import describe
        fields, diagnostics = describe(image, parser)
        info['fields'] = fields
        info['diagnostics'].extend(diagnostics)
        editable = any(f['editable'] for f in fields)
        info['capabilities']['edit'] = {'status': 'supported' if editable else 'unsupported',
                                        'reason': 'independently validated fields only' if editable else
                                                  'no editable field has validated format evidence'}
        info['capabilities']['normalize'] = {'status': 'supported' if info['integrity']['valid'] else 'unsupported'}
        info['capabilities']['vbios'].update(
            writable='verified' if editable else 'unsupported',
            editable_fields=[f['key'] for f in fields if f['editable']])
        info['directory'] = parser.directory
        info['duplicate_chain_count'] = len(getattr(parser, 'chains', [1]))
    except VbiosError as exc:
        info['diagnostics'].append(exc.to_dict()['error'])
        info['capabilities']['edit']['reason'] = str(exc)
        info['capabilities']['normalize']['reason'] = str(exc)
    return info


def inspect(path):
    return inspect_image(load(path))


def normalize(image, *, representation=None):
    if not isinstance(image, BiosImage):
        raise VbiosError('INVALID_IMAGE', 'operation requires an immutable BiosImage')
    if representation not in (None, REPRESENTATION, ada_general.REPRESENTATION, ampere_relocated.REPRESENTATION,
                              turing.REPRESENTATION):
        raise VbiosError('UNKNOWN_REPRESENTATION', 'unrecognized override representation')
    if recognize_payload(image.blob) is not None:
        return image
    parser = backend(image)
    if not parser.integrity()['valid']:
        raise VbiosError('INTEGRITY_FAILED', 'source integrity failed before normalization')
    if isinstance(parser, BlackwellRom):
        if representation is not None:
            raise VbiosError('UNREVIEWED_RELOCATION_SOURCE', f'{representation} does not apply to Blackwell')
        return image
    payload = parser.override_blob()
    result = BiosImage(payload, '<normalized>', image.source_sha256, image.source_path)
    rebuilt = backend(result)
    if not rebuilt.integrity()['valid'] or rebuilt.legacy['device'] != parser.legacy['device']:
        raise VbiosError('INTEGRITY_FAILED', 'normalized chain lost integrity or PCI identity')
    if representation == REPRESENTATION:
        payload = relocate(image.blob, result.blob)
        return BiosImage(payload, '<normalized ada-relocated-v1>', image.source_sha256, image.source_path)
    if representation == ada_general.REPRESENTATION:
        payload, _ = ada_general.relocate(rebuilt)
        return BiosImage(payload, '<normalized ada-relocated-v2>', image.source_sha256, image.source_path)
    if representation == ampere_relocated.REPRESENTATION:
        payload, _ = ampere_relocated.relocate(rebuilt)
        return BiosImage(payload, '<normalized ampere-relocated-v1>', image.source_sha256, image.source_path)
    if representation == turing.REPRESENTATION:
        return BiosImage(turing.e0_end(rebuilt), '<normalized turing-e0-end-v1>', image.source_sha256, image.source_path)
    return result
