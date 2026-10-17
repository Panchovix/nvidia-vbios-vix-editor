# Changelog

## 0.1.15

- **Fan limits and curves per channel (experimental).** Blackwell, Ada and Ampere images get the minimum
  and maximum fan speed (RPM) of each active fan channel and, behind *Show advanced XOC-style fields*, its
  minimum and maximum level (%). The three points of each stored fan curve are editable too: temperature
  (°C, in 1/32 °C steps), speed (RPM) and, with the advanced fields, level (%), for each channel's curve
  and for the extra curves that serve every channel. Points stay in order and inside the limits. On its
  own a limit moves only as far as the stored curves; edited together with the curve points above it
  (including the extra curves'), a maximum can go below its stored value, and a minimum above it, in one
  copy. A speed maximum never goes below the channel's stored speed-table value. Save a new channel count
  before changing these limits or curves on the copy. The fan channel count now turns a channel on or off
  only when its limits hold the extra curves, so the RTX PRO 4000 SFF and RTX 4080 Super images keep their
  stored count. Tested on an RTX 5080: raising the speed maximum from 3500 to 4000 RPM made the same
  fan percent spin about 12 % faster, so the driver scales the percent to this maximum; lowering the
  level minimum did not change the 30-100 % range the driver allows. The other limits and the curve
  points are not tested on hardware.

## 0.1.14

- **Open source.** The editor's source code is now in this repository under the GNU GPL v3.0 or later
  (`GPL-3.0-or-later`): you can use, study, change and share it, and changed versions you share must stay
  under the same license. Issues and pull requests are welcome. Binary releases up to 0.1.13 were
  distributed under a freeware license agreement. `nvbios --version` and the editor window show the
  license.
- Third-party notices name the exact Ubuntu and MSYS2 package versions of the bundled libraries and where
  their complete source is published, with a written offer for it.
- Field evidence in `nvbios fields` and `inspect` uses public descriptions of what was checked (with model,
  VBIOS version and PCI ID scopes) instead of internal capture references. For `ada-relocated-v1` payloads,
  `inspect` reports `recipe_version` instead of `recipe_commit`. Field values and saved bytes are unchanged.

## 0.1.13

- Editor window: the *Technical details* section is gone; it made the window long. Accepted ranges
  and encodings stay in the JSON manifest saved with each copy; `nvbios fields` also lists the
  diagnostics. An error without a translated message shows the backend's explanation in the status
  line.
- Third-party notices: the licenses of software incorporated in CPython (Mersenne Twister, dtoa,
  SipHash, cfuhash, HACL* and others), which the Python runtime inside the programs contains, are
  now included on Linux and Windows (`third_party/python-<version>-incorporated.txt`). Earlier
  releases left them out.

## 0.1.12

- Editor window: dark theme. On Windows it follows the app mode (Settings > Personalization >
  Colors); elsewhere GTK follows the desktop as before. File options > Theme, or `--theme light` /
  `--theme dark`, chooses one.

## 0.1.11

- Editor window: saving an edited Ampere or Ada copy also saves `<name>-loader.bin` next to it,
  the relocated payload the VBIOS loaders take (`ampere-relocated-v1` or `ada-relocated-v2`), with
  its JSON manifest. If the relocation is refused, the copy is still saved and the reason is shown.
  If a `<name>-loader.bin` already exists, nothing is saved, so an older payload never sits next to
  a new copy. GPUs outside the loaders' scope get no loader file.
- RTX 4090 images with VBIOS 95.02.18 (a shorter power table): power, PCIe slot power, 12 V input
  current and NVVDD power fields are now recognized, and `ada-relocated-v2` accepts them.
- First hardware results for the relocated payloads (Windows, driver 617.42): an RTX 4090 (VBIOS
  95.02.18, `ada-relocated-v2`) took a 671 W power limit and a +1200 MHz core clock offset ceiling;
  an RTX A2000 (`ampere-relocated-v1`) took a 5 W power floor. Other Ada and Ampere cards remain
  untested.

## 0.1.10

- ASUS ROG Astral XOC-style images: power and 12 V input current are now shown and
  editable from the override profile the ROM selects at its top level (profile 7: 1200 or
  1600 W, 120 or 160 A). The base table (2001 W / 5001 A) is kept unchanged. Experimental:
  which of the two the firmware enforces has not been tested on hardware.

## 0.1.9

- Ampere (GA102-GA107): every image examined (desktop, workstation and laptop, including
  laptop and A40 images without a UEFI image) is now recognized, with experimental
  editable fields. None of them has been tested on Ampere hardware.
  - Power minimum, default and maximum; PCIe slot power; power connector channels (one
    per 12 V sense channel; one physical connector can span several channels).
  - Clock offset ranges: GPC, memory, XBAR, SYS and VID. A range cannot be collapsed to
    0..0.
  - Fan channels and fan PWM frequency, where the image has them.
  - Advanced (opt-in): 12 V input current and slot current thresholds.
  - The shunt multiplier also scales the power connector channels.
  - Read-only, with the reason shown: voltages (fixed constants on these images), NVVDD
    output OCP, and the A40 clock ranges (stored as 0..0). The RTX 3050 6 GB image is
    read-only (no checksum padding).
- Experimental: `normalize --representation ampere-relocated-v1` exports a GA102-GA107
  payload that fits the 512 KiB limit of the GA10x GSP firmware, for the open-source
  Linux loader. It keeps the legacy and data images unchanged and drops the UEFI image
  and the bytes after the last data image; the result is refused unless every byte, known
  pointer and checksum verifies. Not tested on hardware. GA100 and the A40 image are
  refused.

## 0.1.8

- Editor window: a display-only shunt multiplier (x, 1 = off, up to 10). On a
  shunt-modded card, the board power, fixed board policy, PCIe slot power and current, and
  12 V input current rows also show about the real limit: the value times the multiplier,
  updated while you type. The saved ROM does not change. It assumes the same factor on
  every 12 V input shunt (connector and PCIe slot). NVVDD/MSVDD output current limits are
  measured by the VRM, not by the shunts, and are not scaled.

## 0.1.7

- Ada: many more editable fields. All are experimental except the four already reviewed
  on the RTX 2000 Ada (power minimum and maximum, NVVDD REL ceiling).
  - Power minimum, default and maximum on every desktop and workstation image, in both
    power table variants (RTX 4090, 4080, 6000 Ada and others were read-only before).
  - Clock offset ranges: GPC, memory, XBAR, SYS and VID, minimum and maximum.
  - PCIe slot power, fan channels and fan PWM frequency, where the image has them.
  - NVVDD REL and ALT voltage ceilings, only where they are temperature-derated equations.
  - Advanced (opt-in) hardware thresholds: 12 V input current, slot current and NVVDD
    output power.
  - RTX 4080, 4060 and 4050 Laptop images: power and clock offset ranges. On a laptop the
    platform sets the running power limit.
- Ada fields stay read-only, with the reason shown, when editing them would not change the
  effective limit: fixed-constant voltages, voltages that depend on the chip's fused speedo,
  policies whose rows hold different values or share a sensor with another threshold (the
  RTX 4060 NVVDD power threshold), and every power policy when the override profiles do not
  decode. The RTX 4090 Laptop image is still rejected (no UEFI image) and the RTX 4070
  Laptop image is read-only (no checksum padding).

## 0.1.6

- Experimental: `normalize --representation ada-relocated-v2` relocates other Ada
  desktop and workstation VBIOS images so the loaded image fits the 512 KiB limit of
  the Ada GSP firmware. The layout is derived from each ROM and the result is refused
  unless every output byte, every known pointer field and every checksum verifies.
  Values that point inside moved tables are treated as data and were not reviewed per
  ROM, unlike `ada-relocated-v1`. The laptop images tested do not fit and are refused
  with `RELOCATION_DOES_NOT_FIT`; a laptop image without a UEFI image (RTX 4090 Laptop)
  is still rejected by the parser. A v2 payload is verified only while it is exported
  from its source ROM: `inspect` and `verify` do not recognize it, so re-run `normalize`
  on the source to re-verify. Not tested on hardware except the reviewed RTX 2000 Ada
  layout, where v2 produces the same bytes as `ada-relocated-v1`. This makes these images
  loadable, not fully editable: on several of them the editor still recognizes few or no
  editable fields.
- Ada and Ampere ROMs whose UEFI image carries an unstamped PCI identity (0000:0000),
  such as some RTX 4090, RTX 6000 Ada, RTX 4500 Ada and RTX 4000 Ada images, are now
  read instead of being rejected.

## 0.1.5

- `normalize --representation ada-relocated-v1` exports a relocated Ada payload that fits the 512 KiB
  limit of the Ada GSP firmware, for use with the open
  [NVIDIA Linux VBIOS Vix Loader](https://github.com/Panchovix/nvidia-linux-vbios-vix-loader).
  Only the reviewed RTX 2000 Ada layout (VBIOS 95.07.47.00.19) is supported; other Ada images are refused.

## 0.1.4

- RTX 5080 Laptop GPU: board power (the laptop's TGP row), NVVDD and MSVDD output OCP,
  and the clock offset ranges are now decoded and editable. Laptop fans are system-driven,
  so no fan section is shown. Not tested on hardware; on laptops the platform (Dynamic
  Boost) can keep the running power limit below a raised ceiling.

## 0.1.3

- Saving on drives without hard links (FAT/exFAT, some network shares): a failed save
  no longer leaves a partial file, its rollback never removes a file another program
  replaced or changed, and a file it cannot remove is named in the error.
- Third-party notices: the Windows programs are built with Nuitka 4, licensed under the
  GNU AGPL v3 with the Nuitka Runtime Library Exception (0.1.2 wrongly said Apache 2.0);
  the Zstandard license of the single-file programs is included on Linux and Windows.
- Remove the remaining private reference-image filenames from public evidence.
- Bundle Nuitka's own Apache license and the full common-license texts referenced
  by third-party notices.
- Validate release versions and keep source exports temporary, preserving dated
  editor ZIPs that may already have been shared.
- Clarify environment handling: malformed CPython startup variables can fail
  before the compiled entry point runs; this is not a full environment sandbox.

## 0.1.2

- Windows x86_64: `nvbios-gui.exe` (editor window, one file with its own GTK 4 runtime)
  and `nvbios.exe` (command line).
- Saving works on drives without hard links (FAT/exFAT, some network shares): the new
  ROM is written as an exclusive copy, and a failed manifest removes only that ROM.
- The path dialog accepts Windows drive, UNC and `file:///` paths; `--changes` files
  are read as UTF-8.
- The command line exits quietly when its output is closed early (for example, piped
  into `head`).

## 0.1.1

- Internal research notes, capture names and dates no longer appear in field evidence.
- Import search paths and site imports are isolated; unexpected application errors
  print one line instead of a traceback. See the startup-environment limitation
  in the README.
- PyGObject ships as its original, replaceable files (`lib/nvbios-gui/gi/`).
- README: responsibility notice, Ada and Ampere support, acknowledgements.

## 0.1.0

First public release, Linux x86_64.

- Offline editing of GB20x (Blackwell) VBIOS images: board power floor, default and
  ceiling; NVVDD/MSVDD voltage equation ceilings; core, memory, XBAR, SYS and VID
  clock offset ranges; 12 V input current; output OCP limits; PCIe slot power on
  supported boards; fan PWM frequency and fan channel count.
- Single-rail images (RTX PRO 6000 Workstation, RTX 5060 Ti, RTX 5070).
- Editor window with live verification, English and Spanish.
- JSON command line: inspect, fields, verify, edit, normalize.
- Every save writes a new ROM and a JSON manifest; the source is never modified.
