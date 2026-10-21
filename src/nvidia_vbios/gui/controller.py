"""GTK-free, transactional state for the immutable public editor API."""
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from nvidia_vbios import editor
from nvidia_vbios.families import GA100_DEVICE_IDS, architecture
from nvidia_vbios.rom.memory import compare, memory_report
from nvidia_vbios.rom.structure import scan_images

# Ampere and Ada full ROMs usually hold two banks or more than the 512 KiB their GSP firmware
# reads, so saving such a copy also saves the relocated payload the VBIOS loaders take next to
# it. Ada uses v2: ada-relocated-v1 accepts only the unedited reviewed archive, and on that
# layout v2 writes the same bytes. GPUs outside the loaders' scope (GA100, editor-only IDs) get none.
LOADER_REPRESENTATIONS = {'ampere': 'ampere-relocated-v1', 'ada': 'ada-relocated-v2'}
# Turing gets two experimental payloads: the single bank as it is, and the same bank ending at
# its last data image (turing-e0-end-v1), to try when the first one does not apply the edit.
TURING_LOADERS = (('-loader.bin', None), ('-loader-e0end.bin', 'turing-e0-end-v1'))
# The loaders refuse a payload that sends more than this from its legacy image: the GSP receiver
# capacity of TU10x/TU11x, GA10x and AD10x, the GPUs that get loader files. The Ampere and Ada
# relocations already fit it; a Turing file that keeps flash bytes after its chain may not.
LOADER_GSP_LIMIT = 512 * 1024


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


def memory_view(image):
    """Read-only memory report of an image, raw bytes included; nothing is staged or written."""
    return memory_report(image, raw=True)


def compare_memory(report, path):
    """Compare a memory report with the ROM at path; no document, change list or save is involved."""
    return compare(report, memory_report(editor.load(path), raw=True))


def import_from(document, path, sections, include_opt_in=False):
    """What importing `sections` from the ROM at path gives the document's original (editor.import_fields);
    the window types its `changes` in as pending values, so nothing is staged or written here."""
    if document is None:
        raise editor.VbiosError('INVALID_IMAGE', 'Open a ROM first.')
    report, _ = editor.import_fields(document.original, editor.load(path), sections, include_opt_in=include_opt_in,
                                     dry_run=True)
    return report


def loader_outputs(document):
    """(file suffix, representation) of each payload the VBIOS loaders take for this document's GPU."""
    try:
        device = int(document.report['pci_device'].split(':')[1], 16)
    except (KeyError, AttributeError, IndexError, ValueError):
        return ()
    if device in GA100_DEVICE_IDS:
        return ()
    family = architecture(device)['family']
    if family == 'turing':
        return TURING_LOADERS
    return (('-loader.bin', LOADER_REPRESENTATIONS[family]),) if family in LOADER_REPRESENTATIONS else ()


def loader_path(path, suffix='-loader.bin'):
    path = Path(path)
    return path.with_name(path.stem + suffix)


def save_loader_payload(document, path, suffix='-loader.bin', representation=None):
    """After saving a Turing, Ampere or Ada copy at path: save one loader payload next to it.

    Returns dict(output=, manifest=, representation=) when saved, or dict(error=) when the
    relocation is refused, the payload is too large for the loaders or the file cannot be
    written; the copy itself stays saved either way.
    """
    image = document.proposal.image
    try:
        payload = editor.normalize(image, representation=representation)
        sent = len(payload.blob) - min((p['start'] for p in scan_images(payload.blob)[0]
                                        if p['vendor'] == 0x10DE and p['type'] == 0), default=0)
        if sent > LOADER_GSP_LIMIT:
            raise editor.VbiosError('RELOCATION_DOES_NOT_FIT',
                                    f'this payload sends {sent} bytes from its legacy image; the GSP firmware '
                                    f'accepts at most {LOADER_GSP_LIMIT} and the loaders refuse it')
        manifest = editor.normalize_manifest(image, payload, representation, path)
        return dict(editor.save(payload, loader_path(path, suffix), manifest=manifest), representation=representation)
    except editor.VbiosError as exc:
        return dict(error=str(exc))


def save_document(document, path):
    if document is None:
        raise editor.VbiosError('INVALID_IMAGE', 'Open a ROM first.')
    if document.proposal is None:
        raise editor.VbiosError('INVALID_CHANGES', 'Preview the copy before saving.')
    outputs = loader_outputs(document)
    for suffix, _ in outputs:
        # A payload left by an earlier copy of the same name would sit next to this copy.
        target = loader_path(path, suffix)
        for existing in (target, target.with_name(target.name + '.json')):
            if existing.exists() or existing.is_symlink():
                raise editor.VbiosError('LOADER_OUTPUT_EXISTS', f'refusing to overwrite {existing}')
    saved = editor.save(document.proposal, path)
    # 'loader' is the payload to load first; 'loaders' lists every saved payload in that order.
    loaders = [save_loader_payload(document, path, suffix, representation) for suffix, representation in outputs]
    return replace(document, last_saved=dict(saved, loader=loaders[0] if loaders else None, loaders=loaders))


def loader_messages(saved):
    """(message key, arguments) of the status lines about the loader files saved with a copy.

    The first saved file is the one to load, a second one (Turing) the alternative to try when it
    does not apply the edit; files that could not be saved are reported after them.
    """
    loaders = saved.get('loaders') or ([saved['loader']] if saved.get('loader') else [])
    files = [loader['output'] for loader in loaders if 'output' in loader]
    lines = [('saved_loader' if index == 0 else 'saved_loader_alternative', dict(output=output))
             for index, output in enumerate(files)]
    failed = 'saved_loader_other_failed' if files else 'saved_loader_failed'
    return lines + [(failed, dict(reason=loader['error'])) for loader in loaders if 'output' not in loader]


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
