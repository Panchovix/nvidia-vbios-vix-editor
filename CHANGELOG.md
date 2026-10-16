# Changelog

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
