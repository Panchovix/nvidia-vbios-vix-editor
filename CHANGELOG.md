# Changelog

## 0.1.21

- **Ada laptop images: a clear refusal.** Saving a loader payload for an Ada laptop image (RTX 4050-4080 Laptop,
  RTX 5000 Ada Laptop) now says that Ada laptop images are not supported yet, instead of only the byte counts.
  These images carry about 35 KB of laptop-only performance tables, so the relocated image does not fit the
  512 KiB the GSP firmware accepts.
- **Ampere laptop: a lowered power ceiling confirmed on one RTX 3050 6GB Laptop GPU.** With a 75 W HP BIOS, an
  image with the board power ceiling at 70 W and the boot default at 55 W loaded through the Windows loader
  (`ampere-relocated-v1`, driver 617.42), and the driver then reported a 70 W limit. It is the first laptop
  report; a raised ceiling is not tested on a laptop, where the platform (Dynamic Boost) sets the running limit.
  Reported in [issue #4](https://github.com/Panchovix/nvidia-vbios-vix-editor/issues/4).
- **Turing: PCIe slot power on the MSI GTX 1650.** That slot-powered image stores its slot power row in the
  board power's class instead of the one the editor knew, so it showed no slot field. Under load the slot 12 V
  input read 62.5 W, at its 63 W limit, and the card stayed near 66 W with the board power at 75 W or 90 W.
  `slot_power_rated_w` and `slot_power_max_w` now edit that row (30/63/74 W stock); raising it is not tested on
  Turing hardware yet. The Turing guide says
  that on a slot-powered card the slot limit has to be raised with the board power, and that above 66 W rated
  the slot can be asked for more than the PCIe specification allows.
  Reported in [issue #5](https://github.com/Panchovix/nvidia-vbios-vix-editor/issues/5).

## 0.1.20

- **Turing: board and connector power confirmed on one RTX 2080 Ti.** On an RTX 2080 Ti with the ROG Matrix BIOS,
  an edit of 500 W board power plus 250 W per connector loaded through the Windows loader, and the card reached
  about 458 W under load: the power limiter no longer triggered, the voltage limiters (Reliability Voltage, Max
  Operating Voltage) did. The stop near 300 W reported in 0.1.19, with the per-connector rows at stock, went away
  once they were raised. The field notes and the
  [tester guide](https://github.com/Panchovix/nvidia-vbios-vix-editor/blob/main/docs/turing.md) say so; the
  voltage fields are still not tested on Turing hardware. Tested by @Cancretto.
- **Turing: the Galax HOF XOC voltage layout is accepted.** That RTX 2080 Ti image points the NVVDD REL and ALT
  selectors at the OV equation (REL = ALT = OV = 1125 mV). The editor refused the layout and showed no voltage
  field at all; it now shows REL, ALT and OV read-only (the fixed REL and ALT fields too) and keeps the minimum
  voltage (`nvvdd_vmin_mv`) editable, 400-1050 mV. On a stock image, setting `nvvdd_alt_fixed_mv` and
  `nvvdd_rel_fixed_mv` to 1125 mV in one edit (advanced) gives the same evaluated values; not tested on Turing
  hardware. The Turing checks now cover 24 images, the ROG Matrix and HOF XOC RTX 2080 Ti ones included; the HOF
  XOC image leaves its third connector (`connector_3_power_*_w`) at 143/167 W.
- **Fan zero RPM confirmed on one RTX 5090.** On an HP Omen RTX 5090, whose BIOS ships with the fan-stop bits clear
  (fans at about 1100 RPM at idle), an image with `fan_zero_rpm` set to 1 loaded through the Windows loader: all
  three fans stood still at idle, started under load and stopped again after cooling down. Other boards are not
  tested. Tested by @dsemprich.
- **GUI: a section says when some of its fields are not shown.** When part of an image uses a layout the editor
  does not support yet, the section that lost fields, or all of them (Voltage, Power, Current and protection, Clock
  offsets or Fans), now says so, in English or Spanish, and keeps its heading. Before, a section with no field left
  just disappeared, as the Fans section did on a few images whose fan tables disagree.
- **GUI: no more "Unknown" placeholder rows.** The read-only "Input current limit" and "Overcurrent protection
  (OCP)" rows, and the MSVDD REL ceiling of single-rail images, have no VBIOS row behind them and read as missing
  limits; the window no longer lists them while their value is unknown. `nvbios fields` and the JSON keep them.

## 0.1.19

- **Turing: more fields (experimental).** Besides the board power limits, Turing images now get the PCIe slot and
  connector power limits (`slot_power_*_w`, `connector_N_power_*_w`), the slot and connector current thresholds and
  the NVVDD output current limit (advanced, opt-in: `slot_current_threshold_*_ma`,
  `connector_N_current_threshold_*_ma`, `nvvdd_output_ocp_*_ma`), the minimum voltage (`nvvdd_vmin_mv`), the core
  and memory clock offset ranges, and the fan PWM frequency, speed and level limits and fan curves. The fixed REL
  and ALT voltages (`nvvdd_rel_fixed_mv`, `nvvdd_alt_fixed_mv`, the fields Ada gets below; constant values,
  1068.75/1093.75 mV on most boards) are advanced, opt-in fields: from the stored value up to OV (1125 mV,
  read-only), REL at most ALT, and at least the boot voltage and VMIN plus its chained equations; their effect is
  untested. Each table was decoded by structure on the 22 Turing images examined; edits go to both banks with their
  checksums. On one RTX 2080 Ti the override loaded through the Windows loader and `nvidia-smi` reported an edited
  board power limit, but the card still stopped near 300 W under load: raising the board power probably needs the
  connector limits raised too (inferred; see the
  [tester guide](https://github.com/Panchovix/nvidia-vbios-vix-editor/blob/main/docs/turing.md), which also says
  what to report). Nothing else is tested on Turing hardware. One RTX 2080 image keeps its clock ranges read-only
  (its legacy image lacks the checksum padding), the Quadro RTX 8000 stores them as 0..0, and the GTX 1650 SUPER
  fan tables disagree (no fan field).
- **Ada: REL and ALT follow OV (advanced, experimental).** `nvvdd_rel_alt_follow_ov` now works on Ada too: 1 points
  the NVVDD REL and ALT selectors at the OV equation, a constant 1200 mV on every Ada image, in both banks, and
  repairs the legacy image checksums (the Ada rail table has no hash directory). On the RTX 4080 that takes REL
  from a fixed 1075 mV (ALT 1095 mV) to 1200 mV; images with a lower REL take a larger step (up to +325 mV on
  the RTX 4080 Laptop image), and the field's note gives the stored REL. Images without an ALT selector move REL
  alone. Save it on its
  own; at 1 the field is read-only, so keep the original image to go back. A copy saved this way opens again
  and its loader file is still verified. Not tested on Ada hardware.
- **Ada: fixed REL and ALT voltages (experimental).** Where the REL or ALT equation is a constant (the newer
  RTX 4090 image, RTX 4080, RTX 4000 Ada; ALT alone on the 4080 SUPER, 4070 Ti SUPER and 4060), the new
  `nvvdd_rel_fixed_mv` and `nvvdd_alt_fixed_mv` fields set that value, from the clamp minimum up to the OV value
  (1200 mV), with REL at most ALT: change both together to raise REL past ALT. The edit writes the equation's
  constant and clamp maximum and keeps its clamp minimum, so a copy can be set back exactly. A voltage edit that
  would push another voltage field out of its range (for example REL lowered below a raised VMIN) is refused:
  change both together. Raising REL lets the GPU request
  a higher voltage on its VF curve; the power and thermal limits still apply. Until now the RTX 4080 showed only
  VMIN under Voltage. Not tested on hardware. Turing images get the same fields (see above).
- **Blackwell: REL and ALT follow OV confirmed on one RTX 5090.** A copy edited with `nvvdd_rel_alt_follow_ov`
  loaded as an override on an RTX 5090 without problems (0.1.16 listed it as not tested on hardware).
- **Fan zero RPM (experimental, opt-in, GB20x).** New field `fan_zero_rpm`: bits 1 and 2 of byte `0x32` of every
  enabled fan policy entry, both set (1) or both clear (0). GSP-RM 615.78.08 contains its own parser for this
  entry (static analysis) and decodes the two bits as separate booleans; every GeForce GB20x image sets both and
  every RTX PRO image clears both, and owner reports that came with the contribution tie them to fans that stand
  still at idle (inferred meaning). Each entry keeps its other flag bits. The field is read-only when an entry
  sets one bit alone or the entries disagree, and offers 1 only where the entries store fan-stop parameters (not
  on the RTX PRO 6000 Max-Q). The editor window shows 0/1 fields as switches, with On/Off text. Not
  hardware-tested. Contributed by @bitninja0 (PR #2).
- **Ampere: connector power sum (experimental, not tested on Ampere hardware).** New `connector_sum_power_rated_w`
  / `connector_sum_power_max_w` fields edit the power row that caps the external 12 V connector channels
  together, where the BIOS has one: 300 W rated / 350 W maximum on an RTX 3080 Ti BIOS with two connector
  channels, 450 W on one with three, 280 W on the RTX A6000. Raising the per-connector limits alone may have no
  effect there.
- **Ampere: connector current thresholds (experimental, opt-in).** `connector_N_current_threshold_*_ma`, the
  hardware current threshold on the channel of connector power row N, on the desktop and workstation images
  that store one (rows 9 and 10). Not hardware-tested.
- **GUI: the connector rows show the sum limit.** When another row also caps the sum of the connector channels,
  each connector row now notes the sum row's rated and maximum values and, where that row has a field, that the
  connector power sum must be raised too. Before, only `nvbios fields` showed this warning.

## 0.1.18

- **Turing (experimental, not tested on Turing hardware).** TU102, TU104, TU106, TU116 and TU117 images
  (GeForce RTX 20 and GTX 16, TITAN RTX, Quadro RTX, T series; BIOS 90.xx) are recognized. Only the board power
  limits are editable: `power_max_w`, `power_default_w` and `power_min_w`. The power table decodes like the
  Ampere one on the 22 Turing images examined, and edits go to both banks with their checksums. Turing
  images carry a signed digest list over this table that the editor cannot update; whether the driver checks
  it is unknown. Voltage, clock and fan tables are not decoded on Turing. Saving an edited Turing copy saves
  two loader files: `<name>-loader.bin` (the first bank, unchanged; load it first) and
  `<name>-loader-e0end.bin` (the same bank ending at its last data image, new representation
  `turing-e0-end-v1`; try it if the first does not apply the edit). Both send 250-355 KB from the legacy
  image, under the 512 KiB the Turing GSP firmware reads (the files keep a bank prefix of up to about 162 KiB
  that is not sent). If you own a Turing card, see the
  [tester guide](https://github.com/Panchovix/nvidia-vbios-vix-editor/blob/main/docs/turing.md):
  an override the driver rejects falls back to the stock VBIOS.

## 0.1.17

- **Windows: the programs start again on CPUs without AVX-512.** The 0.1.15 and 0.1.16 `.exe` files closed at
  once, without a message and before unpacking anything, on CPUs without AVX-512: the compiler built their
  memory-copy routine for the CPU of the build machine. The build now targets baseline x86-64 and fails if
  AVX or AVX-512 code reaches either program (0.1.14 needed AVX2 for the same reason). The editor itself and
  the Linux packages are unchanged.

## 0.1.16

- **Minimum voltage (VMIN), experimental.** New `nvvdd_vmin_mv` / `msvdd_vmin_mv` fields edit the equation the
  driver actually evaluates as VMIN: on Blackwell the constant equation selected at rail row +0x13, on Ada and
  Ampere the equation at rail row byte 7 when its clamp pins the value. The value goes from 450 mV (Blackwell) or
  400 mV (Ada, Ampere) up to the lowest value REL can take, less the most the equations chained after VMIN can
  add, so VMIN never ends up above REL (for example up to 753 mV on the RTX 2000 Ada, 814 mV on the RTX 4080).
  Tested on an RTX 5080: 800 -> 850 mV made the driver report VMIN 850 mV and the card idled at 850 mV. On an
  RTX 2000 Ada the driver reported the stored value plus 90 mV (650 mV stock, 790 mV with 700 mV stored); the
  offset may differ on other boards. Other shapes (for example the min/max equation trees of the RTX 5090 MSVDD
  and RTX PRO 4000 SFF rails) are read-only, and so is the RTX 5080/5070 Ti MSVDD VMIN, whose 800 mV already lies
  above the lowest MSVDD REL value (760.2 mV). Not tested on Ampere.
- **The old "VMIN equation ceiling" is not VMIN.** `*_vmin_equation_max_mv` is the slot the driver's rail info
  lists as VMIN, but the driver does not evaluate it as the minimum voltage (on the RTX 2000 Ada a new value
  there changed nothing). It is now read-only on every image and labelled "rail INFO VMIN-slot equation
  ceiling (not the evaluated VMIN)"; the key is unchanged.
- **REL and ALT follow OV (advanced, experimental).** On Blackwell, `nvvdd_rel_alt_follow_ov` = 1 points the
  NVVDD REL and ALT selectors at the OV equation, as the ASUS XOC and MSI Lightning RTX 5090 images do (a flat
  1.2 V voltage limit; images without an ALT selector, such as the RTX PRO 4000 SFF, move REL alone). The rail
  table lives in the legacy image, which has its own SHA384 object directory: the editor now reads it
  (`integrity.legacy_directory`) and repairs its hashes, digest and checksum on this edit. On the stock ASUS
  RTX 5090 image the result matches the XOC image's rail table byte for byte. Save it on its own; at 1 the field
  is read-only, so keep the original image to go back. Not tested on hardware.
- **Fan percent.** The driver maps its fan percent linearly from 30 % at the minimum speed to 100 % at the
  maximum speed (checked on four Blackwell models). The fan descriptions now say so, instead of "percent = RPM /
  maximum": the 30 % setting runs at `fan_N_min_rpm`, so lowering it should lower the slowest manual fan speed
  (not tested on hardware).
- Ada and Ampere: min/max equations now read their child links correctly when the editor checks whether an
  equation is shared. On the corpus this changes no field.

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
