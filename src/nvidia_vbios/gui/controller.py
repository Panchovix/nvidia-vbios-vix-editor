"""GTK-free, transactional state for the immutable public editor API."""
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from nvidia_vbios import editor
from nvidia_vbios.families import GA100_DEVICE_IDS, architecture

# Ampere and Ada full ROMs usually hold two banks or more than the 512 KiB their GSP firmware
# reads, so saving such a copy also saves the relocated payload the VBIOS loaders take next to
# it. Ada uses v2: ada-relocated-v1 accepts only the unedited reviewed archive, and on that
# layout v2 writes the same bytes. GPUs outside the loaders' scope (GA100, editor-only IDs) get none.
LOADER_REPRESENTATIONS = {'ampere': 'ampere-relocated-v1', 'ada': 'ada-relocated-v2'}


@dataclass(frozen=True)
class Document:
    original: Any
    report: dict
    changes: dict
    proposal: Any = None
    last_saved: dict | None = None

    @property
    def preview(self):
        if self.proposal is None:
            return []
        after = {f['key']: f for f in self.proposal.manifest['after']['fields']}
        return [(field, after[field['key']]) for field in self.report['fields']
                if field['current'] != after[field['key']]['current']]


def controls(report):
    """Copy typed descriptors; prefer the validated MHz alias over raw table editing."""
    fields = [dict(f) for f in report.get('fields', [])]
    alias = next((f for f in fields if f['key'] == 'memory_offset_max_mhz'), None)
    if alias and alias['editable']:
        for field in fields:
            if field['key'] == 'dram_max_table_mhz':
                field.update(editable=False, reason='Same field as the MHz control; edit that control.')
    by_key = {f['key']: f for f in fields}
    for field in fields:
        canonical = by_key.get(field.get('alias_of'))
        if canonical is not None:
            field.update(editable=False, reason='Equivalent representation; use the main control.')
    return fields


def open_document(path):
    image = editor.load(path)
    # The public immutable BiosImage.report inspects precisely the loaded bytes,
    # avoiding a second read of a source that could change between load/inspect.
    return Document(image, image.report, {})


def stage_document(document, changes):
    if document is None:
        raise editor.VbiosError('INVALID_IMAGE', 'Open a ROM first.')
    fields = {f['key']: f for f in controls(document.report)}
    if 'dram_max_table_mhz' in changes and 'memory_offset_max_mhz' in changes:
        raise editor.VbiosError('CONFLICTING_FIELDS', 'Choose one memory unit representation.')
    requested = {}
    for key, value in changes.items():
        field = fields.get(key)
        if field is None:
            raise editor.VbiosError('UNKNOWN_FIELD', f'Unknown field: {key}')
        if not field['editable']:
            raise editor.VbiosError('FIELD_READ_ONLY', f"{field['label']}: {field.get('reason', 'Read-only')}")
        if field['type'] not in ('number', 'integer') or isinstance(value, bool):
            raise editor.VbiosError('INVALID_VALUE', f'{key} requires a numeric value.')
        try:
            amount = Decimal(str(value))
        except InvalidOperation as exc:
            raise editor.VbiosError('INVALID_VALUE', f'{key} requires a finite number.') from exc
        if not amount.is_finite() or (field['type'] == 'integer' and amount != amount.to_integral_value()):
            raise editor.VbiosError('INVALID_VALUE', f'{key} requires a finite {field["type"]}.')
        if amount != Decimal(str(field['current'])):
            requested[key] = str(amount)
    proposal = editor.plan(document.original, requested)
    return replace(document, changes=requested, proposal=proposal, last_saved=None)


def reset_document(document):
    return replace(document, changes={}, proposal=None, last_saved=None)


def loader_representation(document):
    """The relocation the VBIOS loaders need for this document's GPU, or None."""
    try:
        device = int(document.report['pci_device'].split(':')[1], 16)
    except (KeyError, AttributeError, IndexError, ValueError):
        return None
    if device in GA100_DEVICE_IDS:
        return None
    return LOADER_REPRESENTATIONS.get(architecture(device)['family'])


def loader_path(path):
    path = Path(path)
    return path.with_name(path.stem + '-loader.bin')


def save_loader_payload(document, path):
    """After saving an Ampere or Ada copy at path: save its loader payload next to it.

    Returns None when the GPU gets no payload, dict(output=, manifest=, representation=)
    when saved, or dict(error=) when the relocation is refused or the file cannot be
    written; the copy itself stays saved either way.
    """
    representation = loader_representation(document)
    if representation is None:
        return None
    image = document.proposal.image
    try:
        payload = editor.normalize(image, representation=representation)
        manifest = editor.normalize_manifest(image, payload, representation, path)
        return dict(editor.save(payload, loader_path(path), manifest=manifest), representation=representation)
    except editor.VbiosError as exc:
        return dict(error=str(exc))


def save_document(document, path):
    if document is None:
        raise editor.VbiosError('INVALID_IMAGE', 'Open a ROM first.')
    if document.proposal is None:
        raise editor.VbiosError('INVALID_CHANGES', 'Preview the copy before saving.')
    if loader_representation(document) is not None:
        # A payload left by an earlier copy of the same name would sit next to this copy.
        target = loader_path(path)
        for existing in (target, target.with_name(target.name + '.json')):
            if existing.exists() or existing.is_symlink():
                raise editor.VbiosError('LOADER_OUTPUT_EXISTS', f'refusing to overwrite {existing}')
    saved = editor.save(document.proposal, path)
    return replace(document, last_saved=dict(saved, loader=save_loader_payload(document, path)))


class Controller:
    """Synchronous facade; state changes only after a successful operation.

    GTK executes the pure document functions on workers, then installs their
    returned state only if its request generation is still current.
    """
    def __init__(self):
        self.document = None

    def open(self, path):
        self.document = open_document(path)
        return self.document

    def stage(self, changes):
        self.document = stage_document(self.document, changes)
        return self.document

    def reset(self):
        if self.document is not None:
            self.document = reset_document(self.document)
        return self.document

    def save(self, path):
        self.document = save_document(self.document, path)
        return self.document.last_saved
