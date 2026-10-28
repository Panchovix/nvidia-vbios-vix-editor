# Changelog

One line per change. What each change does, where it applies and what was tested is in the
[changelog details](https://github.com/Panchovix/nvidia-vbios-vix-editor/blob/main/docs/changelog-details.md).

## 0.1.37

- HP OEM RTX 3060 12 GB: zero RPM can't stop the fan (hardware result).
- Fans: extra fan curves may sit below the fan minimums, so the RTX 3090 blower's minimums and channel count can be edited.

## 0.1.36

- HP OEM RTX 3060 12 GB: the fan fields can be edited.
- RTX 3050 6 GB and 8 GB (GA107): the fan fields can be edited.

## 0.1.35

- RTX 5080 and RTX 5090 Laptop GPU: raise the boot default, the base TGP and the ceiling together.

## 0.1.34

- Ampere: the NVVDD output current limit can be edited (experimental, opt-in).
- Power connector limit on Ada and Blackwell (opt-in, experimental).
- RTX PRO 6000 Max-Q and RTX 5070: the 12 V input current reasons name the connector.

## 0.1.33

- RTX 5090 Laptop GPU: the NVVDD and MSVDD output current limits can be edited.
- RTX 5090 Laptop GPU: the GR rail gating switch.
- RTX 5090 Laptop GPU: Max operating temperature can be raised.
- Idle power switches on products the editor has not reviewed.
- Laptop output current limits are recognized by the ROM's tables, not by its device ID.
- Laptops: the power ceiling notes say what it does and does not do.
- Notebook base TGP (experimental, opt-in; RTX 5080 and 5090 Laptop GPU).

## 0.1.32

- Lowering Fan channels no longer gets stuck on "Checking changes…".
- Greyed-out rows keep what you typed.
- The change list no longer shows unchanged hidden fields.

## 0.1.31

- Import from ROM… copies a fan curve with its levels.
- The import window shows its whole summary.

## 0.1.30

- VMIN set per chip (experimental; Ampere, Ada and Blackwell).
- Fan zero RPM on Ada and Ampere, and on blower workstation cards (experimental).
- Zero RPM start temperature follows the fan curve (Ampere, Ada and Blackwell).
- Smaller changes.

## 0.1.29

- Factory GPC and memory offsets on every ROM (experimental; Turing, Ampere, Ada and Blackwell).
- Max operating temperature on Turing, Ampere and Ada (experimental).
- Advanced section on Turing, Ampere and Ada (experimental).
- RTX 4090 BIOS with 16-pin cable power profiles (experimental; Ada).
- VMIN on RTX 4090 95.02.3C builds (experimental; Ada).
- Smaller changes.

## 0.1.28

- Max operating temperature (experimental; Blackwell).
- Factory GPC offset (experimental; Blackwell).
- Import from ROM… copies the factory GPC offset with the Clock offsets.
- Advanced section: clock controllers and idle power saving (experimental; Blackwell).
- Ampere and Ada images that end with an empty table before the checksum are editable, some laptops included.

## 0.1.26

- Import from another ROM (Turing, Ampere, Ada and Blackwell).
- Read-only memory view (Turing, Ampere, Ada and Blackwell).
- Windows driver 621.01 works on Blackwell, Ada and Ampere.
- Memory levels that follow the memory offset: hardware result.

## 0.1.25

- GPC curve offset (experimental, opt-in; Blackwell, Ada and Ampere).

## 0.1.24

- Memory levels that follow the memory offset (experimental, opt-in; Blackwell, Ada and Ampere).

## 0.1.23

- Fan zero RPM temperatures on Ada and Ampere (experimental, opt-in).
- Fan zero RPM upper threshold tested on one RTX 5080.
- Turing: a raised power limit confirmed on an RTX 2070.

## 0.1.22

- Fan minimum speed: lowering it did not lower the fans on one RTX 5080.
- GUI: explain fan-curve limits.
- Fan zero RPM temperatures (experimental, opt-in, GB20x).

## 0.1.21

- Ada laptop images: a clear refusal.
- Ampere laptop: a lowered power ceiling confirmed on one RTX 3050 6GB Laptop GPU.
- Turing: PCIe slot power on the MSI GTX 1650.

## 0.1.20

- Turing: board and connector power confirmed on one RTX 2080 Ti.
- Turing: the Galax HOF XOC voltage layout is accepted.
- Fan zero RPM confirmed on one RTX 5090.
- GUI: a section says when some of its fields are not shown.
- GUI: no more "Unknown" placeholder rows.

## 0.1.19

- Turing: more fields (experimental).
- Ada: REL and ALT follow OV (advanced, experimental).
- Ada: fixed REL and ALT voltages (experimental).
- Blackwell: REL and ALT follow OV confirmed on one RTX 5090.
- Fan zero RPM (experimental, opt-in, GB20x).
- Ampere: connector power sum (experimental, not tested on Ampere hardware).
- Ampere: connector current thresholds (experimental, opt-in).
- GUI: the connector rows show the sum limit.

## 0.1.18

- Turing (experimental, not tested on Turing hardware).

## 0.1.17

- Windows: the programs start again on CPUs without AVX-512.

## 0.1.16

- Minimum voltage (VMIN), experimental.
- The old "VMIN equation ceiling" is not VMIN.
- REL and ALT follow OV (advanced, experimental).
- Fan percent.
- Ada and Ampere: min/max equations read their child links correctly.

## 0.1.15

- Fan limits and curves per channel (experimental).

## 0.1.14

- Open source.
- Third-party notices name the exact package versions and where their source is.
- Field evidence uses public descriptions instead of internal references.

## 0.1.13

- Editor window: the Technical details section is removed.
- Third-party notices include the licenses of software inside CPython.

## 0.1.12

- Editor window: dark theme.

## 0.1.11

- Editor window: saving an Ampere or Ada copy also saves its loader payload.
- RTX 4090 with VBIOS 95.02.18: power fields recognized.
- First hardware results for the relocated payloads (RTX 4090, RTX A2000).

## 0.1.10

- ASUS ROG Astral XOC-style images: power and 12 V input current editable.

## 0.1.9

- Ampere (GA102-GA107) images recognized, with experimental editable fields.
- Experimental `ampere-relocated-v1` payload export.

## 0.1.8

- Editor window: display-only shunt multiplier.

## 0.1.7

- Ada: many more editable fields (experimental).
- Ada: fields that would not change the effective limit stay read-only.

## 0.1.6

- Experimental `ada-relocated-v2` payload export.
- Ada and Ampere ROMs with an unstamped UEFI PCI identity are read.

## 0.1.5

- `ada-relocated-v1` payload export for the Linux loader.

## 0.1.4

- RTX 5080 Laptop GPU: board power, output OCP and clock offset ranges editable.

## 0.1.3

- Safer saving on drives without hard links.
- Third-party notices: Nuitka 4 license corrected, Zstandard license added.
- Private reference-image filenames removed from public evidence.
- Nuitka's Apache license and the common license texts bundled.
- Release versions validated, source exports kept temporary.
- Environment handling clarified (CPython startup variables).

## 0.1.2

- Windows x86_64 programs.
- Saving works on drives without hard links.
- The path dialog accepts Windows drive, UNC and `file:///` paths.
- The command line exits quietly when its output is closed early.

## 0.1.1

- Internal notes, capture names and dates removed from field evidence.
- Isolated import paths, one-line error messages.
- PyGObject ships as replaceable files.
- README: responsibility notice, Ada and Ampere support, acknowledgements.

## 0.1.0

First public release, Linux x86_64.

- Offline editing of GB20x (Blackwell) VBIOS images.
- Single-rail images (RTX PRO 6000 Workstation, RTX 5060 Ti, RTX 5070).
- Editor window with live verification, English and Spanish.
- JSON command line: inspect, fields, verify, edit, normalize.
- Every save writes a new ROM and a JSON manifest.
