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
| `power_default_w`, `input_current_*_ma`, `*_output_ocp_rated_ma`, `slot_power_*_w`, `connector_N_power_*_w`, `connector_sum_power_*_w`, `connector_N_current_threshold_*_ma`, `board_fixed_rated_w`, clock offset ranges, `nvvdd_vmin_mv`, fan fields | W, mA, MHz, mV, Hz, RPM, %, °C | see `extended-fields.md` | Experimental, not hardware-tested (Turing board and connector power: one RTX 2080 Ti, see `turing.md`); `board_fixed_rated_w` and the Ada/Ampere `input_current_*_ma`, Ada/Ampere/Turing `slot_current_threshold_*_ma`, Ampere/Turing `connector_N_current_threshold_*_ma` and Ada `nvvdd_power_threshold_*_w` hardware thresholds (`policy_class: "hardware-threshold"`) are opt-in (`opt_in: true`), as is the Turing `nvvdd_output_ocp_*_ma` (row 13, class 10); `connector_N_power_*_w` are the Ampere/Turing external connector-channel policies (a sense channel, not a physical connector) and `connector_N_current_threshold_*_ma` the current threshold row on the same channel; `connector_sum_power_*_w` is the Ampere policy on their sum, where one row caps it |
| `power_max_w` | W | mW, uint32 | Ada V3x 30/32/53, 30/34/5b and 30/2c/4b; Ampere V3x 30/2c/47, 30/2c/43 and 30/32/47 (every Ampere field is experimental); Turing V3x 30/2c/42 and 30/27/42 (experimental, see `turing.md`); GB20x V40 40/38-or-3d/66 |
| `nvvdd_rel_max_mv` | mV | uV, exact float32 | Ada single logic rail V20; GB20x V30; Ampere and Turing read-only (constant equations) |
| `nvvdd_rel_fixed_mv`, `nvvdd_alt_fixed_mv` | mV | uV, exact float32 (constant and clamp maximum; the clamp minimum is kept) | Constant Ada and Turing REL/ALT equations; experimental (opt-in on Turing); ordering group `nvvdd-rel-alt`, with `nvvdd_vmin_mv` on Turing |
| `msvdd_rel_max_mv` | mV | uV, exact float32 | GB20x; Ampere two-rail GA102 read-only (constant equations); Ada exposes one rail and refuses MSVDD |
| `dram_max_table_mhz` | table MHz | signed int16 | GB20x clock V50 with reviewed identity descriptors; Ada/Ampere GV HAL clocks table and Turing v0x35 clocks table, experimental |
| `memory_offset_max_mhz` | MHz | signed int16 table MHz | GB20x; MHz (NVML/Linux scale) = 2 × table MHz, validated relationship supplied by user (Ada: NVML reading; Ampere and Turing: by analogy, experimental); Windows tools such as MSI Afterburner show the table value |
| `current_limit_a`, `ocp_limit_a` | A | unknown | Read-only pending independent field evidence |

The two GB20x memory keys edit the same field. Supply one representation per
request; an overlapping request produces `CONFLICTING_FIELDS`. When an Ada, Ampere or Turing
clock table is not recognized, a read-only `memory_offset_max_mhz` with unknown current value remains, so callers
can explicitly present the missing unit/domain evidence.

`capabilities.inspect`, `capabilities.edit`, and `capabilities.normalize` contain
`status` and, where relevant, a reason. The schema separates architecture,
format, field capabilities and integrity. `integrity.valid=null` means the full
format is unknown; raw image sums do not establish full integrity. A corrupt
recognized image reports failed integrity and cannot be edited or normalized.

## Memory view (read-only)

`nvidia_vbios.rom.memory.memory_report(image, *, raw=False)` decodes the memory tables of a
Turing, Ampere, Ada or GB20x image (a `BiosImage` or a parsed ROM) and writes nothing;
`nvbios memory ROM [--raw]` prints it. It is separate from `inspect` and `fields`, whose
output does not change.

- `configurations`: the memory configuration table (BIT M+0x03, nouveau M0203). Per used
  entry: the hardware `strap`, the `column` of the per-configuration tables (the entry's
  group, which need not equal the strap), the `vendor` (`1` Samsung, `6` SK hynix, `0xf`
  Micron; always `vendor_code`), `type_code` and the `raw` entry bytes. Only type 9 is named
  (`type`: GDDR6); 0xa and 0xd carry `type_guess` GDDR6X and GDDR7. The board's strap pins
  select the entry; the ROM cannot tell which one a card uses (`strap_note`).
- `bands`: the memory clock table (BIT P+0x04): per band `min_mhz`, `max_mhz`, the
  `timing_index` of each used column (`null` when the band has no entry), the band's `raw`
  bytes, the `sub_entries` bytes of the used columns and the stock DRAM clocks it holds
  (`stock_points`; Blackwell, Ada and Ampere, when the ROM's clock points are read).
  `column_count` is the table's number of columns; used columns at or beyond it are listed
  in `outside_table`. A 0–0 MHz band is a placeholder that no clock selects.
- `timings`: the timing entries the bands above 0 MHz select (BIT P+0x08) with their
  `raw` bytes and `decoded` values in controller cycles (`unit`). `confidence` names how each was
  identified: `tRC`, `tRAS` and `tRP` (word 0) are inferred from byte patterns, `tRFC` is
  probable, `CL` (word 1 bits 5..0) and `tWR` (word 2 bits 22..16) are tentative. No time
  in ns is derived: the cycle length depends on the memory type.
- `tables`: offset, size and SHA-256 of each decoded table and, on GB20x, of the other
  memory objects BIT M points to, with the owning object.
- `board_profile`: on GB20x, object 0x89, undecoded per-board boot data, probably
  memory-interface training. It is recognized only when its two signatures are 0x8b0
  apart at a reviewed position, and reports a `tag` (two big-endian header words; that
  they are an ID and a revision is unconfirmed), a `fingerprint` (SHA-256 prefix of the
  group B header and record B1 column 0) and a `sha256` of every byte the view reports
  (the header, both records and, when recognized, the arrays and flags). `raw` adds every
  paired field of records B1 and B2 in both columns, their index lists, two u16[4] arrays
  and a flag pair. Only flashing the whole ROM applies this data; the override cannot.

A section that fails a check reads `{"status": "unrecognized", "reason": ...}`; when no
parser accepts the image, the whole report does. `compare(a, b)` (`nvbios memory ROM
--compare OTHER`; with `--raw` it also returns both reports) gives each section's
`status`: `identical`, `differs` with the count and keys of the differing entries or
tables, `unavailable` when either report lacks the section, or, for the board profile only,
`not-applicable` when either ROM is not Blackwell. `configurations`, `bands`
and `timings` compare the bytes of the entries in use (the configurations, the bands above
0 MHz with their used sub-entries, and the timing entries those bands select); `tables`
compares every byte of each table and names the tables that differ, so it can differ
while the other sections are identical. The board profile status follows its `sha256`;
with `raw=True` reports it also counts differing fields per column and says which other
parts differ. Its `meaning` is `unknown`. It never says which ROM is better.

## Import from another ROM

`import_fields(target, donor, sections, *, include_opt_in=False, dry_run=False)` copies the
editable values of the chosen sections from `donor` into `target`, two `BiosImage`s of the same
family and format. The sections are the GUI's (`IMPORT_SECTIONS`: `power`, `voltage`, `clocks`,
`current`, `fans`). Another family or format is refused with `FAMILY_MISMATCH`; another device of
the family (another PCI device ID) is allowed with a `DIFFERENT_DEVICE` warning. `nvbios import ROM
DONOR [OUTPUT] --sections fans[,power,...] [--include-opt-in] [--dry-run]` prints the report with
the `manifest` of the edit; without `--dry-run` it saves OUTPUT and `OUTPUT.json` through the same
path as `edit`, and with nothing to import it refuses with `NOTHING_TO_IMPORT`.

A field is proposed when its donor value differs and it is editable in both ROMs, means the same
quantity in both and the value is inside the target's bounds, checked as `edit` checks them (an
ordering group's encoding bounds when its partners are proposed with it). The same quantity means
the same `units`, memory level (`memory_mhz`), power layout (`notebook_tgp`, which marks the three
board power fields of a notebook TGP layout) and `equation_type`, and a voltage field on an
equation shared by the same fields (REL and ALT that follow OV share its equation, so their values
are not those of a ROM where each has its own). Aliases and placeholders the GUI hides are left
out, opt-in fields unless `include_opt_in`, and the fan channel count, which describes the board's
fans. A dependent set comes whole from the donor: an ordering group (a minimum, rated value and
maximum), the fan curve (`fan_N_min/max_rpm/pct` and every curve point's temperature, speed and
level) and the 12 V input limit with `input_current_policy7_limit_ma`. When a field of a set
differs but is left out (opt-in, read-only in either ROM, another quantity, out of bounds), the
rest of the set is held back. The proposal is one `edit` request, so the cross-field checks see
the final set. A unit the editor refuses is dropped whole and the rest tried again: every voltage
field (each bounds the others), a set or one field; nothing is applied in part.

It returns `(report, result)`. `result` is the verified `EditResult` of the applied values, or
`None` when none is applied. `report` holds `changes` (key → value, as `edit` takes them), the
`applied` and `skipped` fields (`field`, `section`, `label`, `units` and the `target` and `donor`
values), `unchanged` (the keys editable in the target whose value already equals the donor's),
`warnings` and a `note`. A skipped field's `reason` is `absent_in_donor`, `absent_in_target`,
`read_only_in_donor`, `read_only_in_target`, `read_only` (in both ROMs; listed only when it holds
a set back), `opt_in`, `board_specific` (the fan channel count), `different_meaning`,
`out_of_bounds` (with the `bounds`), `held_back` (with the `partners` that held its set back) or
`refused` (with the editor's `code` and `message`). An opt-in field is listed only when both ROMs
hold it with different values.

Values are copied as stored numbers, not adapted to the board: fan speeds, power or current
limits and voltage limits from another board can exceed this board's hardware (fans rated for a
lower speed, a single 12V-2x6 connector).

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
On Ada the rail table lies in the legacy image of every chain, without an object
directory: `nvvdd_rel_alt_follow_ov` writes its selectors in each chain and repairs
each legacy image checksum, which needs the reviewed checksum padding.
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
`*_vmin_mv` and `nvvdd_rel_alt_follow_ov` bindings, and the constant and clamp maximum
of a constant Ada or Turing REL/ALT equation only through `nvvdd_rel_fixed_mv` and
`nvvdd_alt_fixed_mv`, at their declared bytes; the rail table of every chain
changes nowhere else.

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
`SOURCE_OVERWRITE`, `SOURCE_CHANGED`, `OUTPUT_EXISTS`, `IO_ERROR`, and for imports `INVALID_SECTIONS`,
`FAMILY_MISMATCH` and `NOTHING_TO_IMPORT`.

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
