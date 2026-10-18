# Offline editor API, schema version 1

The public API uses stdlib Python and never accesses a GPU or driver. It recognizes
formats from bounded PCI/NPDS chains, BIT tokens and, on GB20x, an object directory.
A filename, total dump size, board serial or complete-file hash never selects an
editor. Unknown ROMs retain raw PCI/NPDS/checksum inspection and explicitly refuse
editing. A recognized architecture does not imply a recognized editable table.

```python
from nvidia_vbios.editor import load, inspect, edit, plan, save, normalize, VbiosError

original = load("source.rom")
report = inspect("source.rom")         # JSON-compatible dict, schema_version=1
proposal = plan(original, {"power_max_w": 100})  # builds and verifies bytes in memory
staged = edit(original, {"power_max_w": 100})
next_stage = edit(staged.image, {"nvvdd_rel_max_mv": 1100})
saved = save(next_stage, "output.rom")  # exclusive ROM plus output.rom.json
payload = normalize(next_stage.image)  # primary NVGI bank if duplicated; otherwise exact bytes
reverted = original                   # retain immutable original for UI revert
```

Choose requested values from that ROM's `fields`, not this example. `load(path)`
returns immutable `BiosImage`; `from_bytes(data, name)` is available from
`nvidia_vbios.rom`. `inspect_image(image)` inspects staged bytes without reopening
the original. `edit(image, changes, dry_run=False)` and `plan(image, changes)`
return `EditResult(image, manifest)`; `.blob` and `.to_dict()` are convenience
accessors. Staging is an in-memory operation; save is always explicit. An empty
or already-satisfied request returns a verified zero-change result.

`save(result, path)` publishes the ROM and manifest without replacing an existing
file or symlink. It uses hard links where available and an exclusive copy on
filesystems without hard-link support. It rejects the source path and verifies
that the original file still has its loaded SHA256. A failed copy, manifest or
close rolls back every file this save created, and only those: an exclusive copy stays open until
the save ends, so its path is provably ours (POSIX keeps the inode; Windows lets
nobody else delete or rename it), and a hard link is checked against the private
temporary file it shares. The ROM is removed only if it still holds exactly the
saved bytes; a file another writer replaced or changed is kept. If a file of
this save cannot be removed, the error names it. A copy can be visible while it
is written; a replacement racing the final check and unlink is not detected.
Successful publication is reported only after both writes complete.
`save(image, path)` saves an exact copy without a manifest; pass `manifest=...` to include one. Source provenance persists across
staged edits. No cryptographic signature is verified or regenerated; integrity
reports identify which non-signature checks were run.

## Fields and capabilities

Every field has a stable `key`, numeric `type`, explicit `units`, `current`,
`bounds`, `editable`, `capability_status` and `evidence`. Read-only unknown values
are `null`; unknown hardware limits are `null`. Bounds marked
`encoding-and-preserved-defaults` describe exact storage, protected minima and
factory defaults. They are not hardware-safe operating maxima. For a field with an
`ordering_group`, the bounds hold its partners' current values; partners requested
together are checked on the combined result (see `extended-fields.md`). The descriptor
retains the `factory_default` for board power and the temperature coefficients
for the Ada REL equation. Fields that fail an independent variant check are
omitted with a diagnostic; other independently recognized fields can remain
editable.

| Field key | Public unit | Stored unit | Recognized support |
| --- | --- | --- | --- |
| `power_min_w` | W | mW, uint32 | TGP minimum: Ada/Ampere/Turing header index; GB20x row8, 1 W through the TGP rated default |
| `power_default_w`, `input_current_*_ma`, `*_output_ocp_rated_ma`, `slot_power_*_w`, `connector_N_power_*_w`, `board_fixed_rated_w`, clock offset ranges | W, mA, MHz | see `extended-fields.md` | Experimental, not hardware-tested; `board_fixed_rated_w` and the Ada/Ampere `input_current_*_ma`, `slot_current_threshold_*_ma` and Ada `nvvdd_power_threshold_*_w` hardware thresholds (`policy_class: "hardware-threshold"`) are opt-in (`opt_in: true`); `connector_N_power_*_w` are the Ampere external connector-channel policies (a sense channel, not a physical connector) |
| `power_max_w` | W | mW, uint32 | Ada V3x 30/32/53, 30/34/5b and 30/2c/4b; Ampere V3x 30/2c/47, 30/2c/43 and 30/32/47 (every Ampere field is experimental); Turing V3x 30/2c/42 and 30/27/42 (the only Turing fields with the default and floor; experimental, see `turing.md`); GB20x V40 40/38-or-3d/66 |
| `nvvdd_rel_max_mv` | mV | uV, exact float32 | Ada single logic rail V20; GB20x V30; Ampere read-only (constant equations) |
| `msvdd_rel_max_mv` | mV | uV, exact float32 | GB20x; Ampere two-rail GA102 read-only (constant equations); Ada exposes one rail and refuses MSVDD |
| `dram_max_table_mhz` | table MHz | signed int16 | GB20x clock V50 with reviewed identity descriptors; Ada/Ampere GV HAL clocks table, experimental |
| `memory_offset_max_mhz` | MHz | signed int16 table MHz | GB20x; MHz (NVML/Linux scale) = 2 × table MHz, validated relationship supplied by user (Ada: NVML reading; Ampere: by analogy, experimental); Windows tools such as MSI Afterburner show the table value |
| `current_limit_a`, `ocp_limit_a` | A | unknown | Read-only pending independent field evidence |

The two GB20x memory keys edit the same field. Supply one representation per
request; an overlapping request produces `CONFLICTING_FIELDS`. When an Ada or Ampere
clock table is not recognized, a read-only `memory_offset_max_mhz` with unknown current value remains, so callers
can explicitly present the missing unit/domain evidence.

`capabilities.inspect`, `capabilities.edit`, and `capabilities.normalize` contain
`status` and, where relevant, a reason. The schema separates architecture,
format, field capabilities and integrity. `integrity.valid=null` means the full
format is unknown; raw image sums do not establish full integrity. A corrupt
recognized image reports failed integrity and cannot be edited or normalized.

## Structural and preservation checks

PCI and NPDS image lengths bound every read and table. BIT header sums, token
uniqueness, token bounds and requested pointer widths are checked. Ada/Ampere/Turing
require contiguous legacy/EFI/NPDS chains (Ampere and Turing: or a legacy image marked last
followed directly by its NPDS images), an explicit last NPDS image (Turing: a type-0x70
NPDS image flagged last after the data images), consistent
PCI/chip identity (Ampere also accepts the shared GA10x NPDS ID 0x2200) and
identical duplicate image chains. The complete primary NVGI bank
can be selected using repeated chain positions and NVGI bank headers, independently
of total dump size or serial. Single-chain dumps retain all their bytes. The archival editor updates every duplicate chain symmetrically and
preserves bank padding and board records. Normalization preserves the primary NVGI envelope and padding when its bank
boundary is established. Wrapperless synthetic multi-chain containers select
the bounded primary PCI chain. These transformations do not replace the full
archive or prove the identity of a live GPU.

GB20x recognizes the reviewed directory version 3/header-size 16/60-byte SHA384
entry format and the examined metadata digest envelope at `metadata+0x209`.
The envelope location is an explicit format constraint. Every object SHA384,
directory SHA384 and bounded image sum is verified. Shared/partially overlapping
object data is permitted as observed in the corpus; editable fields must have
unambiguous ownership. Every hash owner intersecting a write is repaired.
The legacy image carries its own directory of the same format (digest at
`legacy+0x209`); `integrity.legacy_directory` reports its hashes without
changing `integrity.valid`. A write inside the legacy image (only the opt-in
`nvvdd_rel_alt_follow_ov`) requires that directory to verify, repairs every legacy
object it touches, its digest and the legacy image checksum, and must reparse
valid; those repairs carry `"directory": "legacy"` in the manifest.
The examined portable Blackwell EFI GOP explicitly allows identity `0000:0000`;
NVIDIA/chip identities remain checked on legacy, metadata and NPDS images.
Unknown directory/envelope versions do not become editable merely because they
have a plausible marker.

The writer repairs only declared fields, affected hashes and bounded checksum
padding. It reparses and verifies the output, checks structural identity and
BIT tokens, and rejects all undeclared byte changes. Unrequested factory/rated
defaults and power minima stay unchanged; only the canonical `power_default_w` and
`input_current_rated_ma` requests change a rated value (see `extended-fields.md`).
`power_min_w` permits only the reviewed TGP minimum bytes from 1 W through the
rated default; aliases and custom registries cannot bypass that protection. GB20x board power ceiling
changes update policies 2/7/8 plus complete profiles matching the original base bounds; policy 9, lower profiles
and OCP remain unchanged. When no profile matches the base (ASUS XOC-style images), `power_max_w`,
`power_default_w`, `board_fixed_rated_w`, `input_current_max_ma` and `input_current_rated_ma` bind to the profile
reached at the top level of the ROM's selection table and write only its entries; the base maximum and rated
values stay unchanged (see `extended-fields.md`). Ada power uses its header's TGP index rather than a
fixed board row. Ada REL editing changes only the clamp maximum and preserves
its temperature equation coefficients and sensed-temperature input. The evaluated
VMIN equation and the NVVDD REL/ALT selectors change only through the canonical
`*_vmin_mv` and `nvvdd_rel_alt_follow_ov` bindings, at their declared bytes.

## Architecture gate and sources

The gate uses an explicit PCI-ID inventory from NVIDIA's
[615.71.09 product table](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/615.71.09/README.md),
and corroborates the ROM's BIOS version family (`92` GA100, `94` GA10x,
`95` Ada, `98` GB20x). The inventory records product names and excludes Hopper,
datacenter Blackwell, GB10 and unknown PCI IDs. GB20x Server/Embedded branding
alone does not exclude an otherwise recognized architecture. Numeric PCI neighborhoods and strings
inside an arbitrary filename never authorize a device. PCI architecture
recognition is distinct from supported table variants and hardware validation.

BIT pointer/token structure derives from NVIDIA's
[BIT specification](https://nvidia.github.io/open-gpu-doc/BIOS-Information-Table/BIOS-Information-Table.html).
V3x power prefix/unit flags, the V1x rail prefix, and VFE output layouts derive
from NVIDIA-authored
[nvgpu bios.h](https://github.com/OE4T/linux-nvgpu/blob/patches-rel-36/drivers/gpu/nvgpu/include/nvgpu/bios.h)
(the linked tree is a mirror). The Python Blackwell parser applies the reviewed
clock-domain, power/profile and rail shape checks. These are format/evidence
checks, not an assertion that arbitrary GPUs or drivers accept edited bytes.
No source ROM, executable or NVIDIA driver binary belongs in Git.

## Errors, manifests and extensions

Catch `VbiosError`; `.code` is stable and `.to_dict()` returns:

```json
{"schema_version": 1, "error": {"code": "FIELD_READ_ONLY", "message": "...", "details": {}}}
```

Codes include `INVALID_IMAGE`, `INVALID_CHANGES`, `INVALID_PATH`, `INVALID_VALUE`,
`UNKNOWN_FIELD`, `FIELD_READ_ONLY`, `OUT_OF_BOUNDS`, `UNREPRESENTABLE_VALUE`,
`CONFLICTING_FIELDS`, `SEPARATE_EDIT_REQUIRED`, `UNSUPPORTED_ARCHITECTURE`, `ARCHITECTURE_MISMATCH`,
`UNSUPPORTED_FORMAT`, `INTEGRITY_FAILED`, `INVALID_FIELD_EVIDENCE`,
`REGISTRY_CONFLICT`, `UNSUPPORTED_CHECKSUM_LAYOUT`, `IDENTITY_CHANGED`,
`FACTORY_DEFAULT_CHANGED`, `PRESERVED_FIELD_CHANGED`, `POSTCONDITION_FAILED`, `UNDECLARED_CHANGE`,
`SOURCE_OVERWRITE`, `SOURCE_CHANGED`, `OUTPUT_EXISTS`, and `IO_ERROR`.

Version-1 manifests contain source/original/output SHA256, requested values,
before/after field descriptors, every explicit edit, byte diff ranges, integrity
repairs, changed object IDs and preservation claims. Hardware validation of a
new edit is always false; original-source hardware validation is unknown to the
library and must be supplied independently by callers with evidence.

`FieldRegistry` and immutable `Binding` provide an explicit extension point for
new independently reviewed fields. A resolver receives `(image, parser)`, returns
bindings with descriptor/evidence, exact encoding/scale and bounded offsets, and
must establish the format and units before marking a field editable. Pass a
registry via `edit(..., field_registry=registry)` or register a resolver with the
default registry. The writer rechecks ownership, overlap, factory defaults and
post-edit field values. New resolvers do not bypass the architecture gate.

The `nvbios` CLI and the GUI call these functions directly; this package adds no
CLI entry point, installation behavior or GPU activation command.

## Validation

The tests build small synthetic PCI/NPDS and SHA384-directory images; no ROM file,
GPU or driver is needed:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_rom*.py'
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_editor*.py'
```

Development also checks real reference ROMs, which are not distributed; the suite
here is synthetic only. Eight archival images are recognized and
survive independently verified power/voltage edits in memory, three generated
1.10 V images match independently made reference edits byte for byte, and an RTX
3090 image validates the Ampere power variant offline (its voltage fields stay
read-only and its clock fields experimental). These tests neither activate a ROM
nor establish a driver's runtime acceptance of new edits.
