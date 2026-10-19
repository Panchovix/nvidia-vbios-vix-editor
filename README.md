# NVIDIA VBIOS Vix Editor

Offline editor for NVIDIA Blackwell (GB20x) VBIOS images, for Linux and Windows, with a
GTK editor window and a JSON command line. It edits power limits, voltage ceilings, the minimum voltage
(VMIN), clock offset ranges, 12 V input current and output OCP limits, fan PWM frequency, fan channels,
per-channel fan speed limits, the stored fan curves and zero RPM (experimental). Ada (AD10x) images get power limits,
clock offset ranges, slot power, fans and, where they apply, voltage ceilings, VMIN, fixed REL/ALT voltages
and the XOC-style flat voltage limit (experimental).
Ampere (GA10x) images get power limits, power connector channels, clock offset ranges, slot power, fans
and, where it applies, VMIN (experimental). Turing (TU10x/TU11x) images get power limits, slot and
connector power and current limits, VMIN, fixed REL/ALT voltages, clock offset ranges and fans
(experimental; on one RTX 2080 Ti edited board and connector power limits loaded and the card reached about
458 W under load, nothing else is tested on a Turing card; see the
[Turing tester guide](https://github.com/Panchovix/nvidia-vbios-vix-editor/blob/main/docs/turing.md)).

Loading an edited image with the Linux or Windows loader works with NVIDIA 615.x (R615) drivers on Linux and
616.x and 617.x drivers on Windows. It may stop working in a future driver if NVIDIA decides to change or remove
the override, so check that it still applies after every driver update (Linux: `nvbios system status` and an
edited value in `nvidia-smi`; Windows: **Verify**).

**Not affiliated with, endorsed by or sponsored by NVIDIA Corporation.** NVIDIA and
GeForce are trademarks of NVIDIA Corporation.

> [!CAUTION]
> **You use this software entirely at your own risk.** Any modification you make with it,
> anything derived from it or from its output, and any damage that results, is solely your
> responsibility. See [Read before using an edited image](#read-before-using-an-edited-image).

## Download

From the Releases page:

| File | Contents |
|---|---|
| `nvidia-vbios-vix-editor-<version>-linux-x86_64.tar.gz` | Linux: editor window (`nvbios-gui`) and command line (`nvbios`) |
| `nvbios-<version>-linux-x86_64` | Linux: command line only, one file |
| `nvbios-gui.exe` | Windows: editor window, one file with its own GTK 4 |
| `nvbios.exe` | Windows: command line, one file |
| `SHA256SUMS` | checksums: `sha256sum -c SHA256SUMS`, or `Get-FileHash FILE` in PowerShell |

## Requirements

Windows: Windows 10 or 11, x86_64. Nothing else; `nvbios-gui.exe` carries its own GTK 4.

Linux:

- x86_64 with glibc 2.39 or newer: Ubuntu 24.04+, Debian 13+, Fedora 40+, Arch and
  derivatives.
- Editor window: GTK 4.14+ and the GObject Introspection runtime.
  - Ubuntu / Debian: `sudo apt install libgtk-4-1 libgirepository-1.0-1`
  - Fedora: `sudo dnf install gtk4 gobject-introspection`
  - Arch: `sudo pacman -S gtk4 gobject-introspection-runtime`
- Command line: nothing else.

## Your VBIOS image

The editor does not include any VBIOS. You provide the image of your own card, for
example:

- Windows: GPU-Z, with the arrow next to the BIOS version and *Save to file…*.
- Linux: `nvflash --save card.rom` (reading only; never write an edited image with
  nvflash).

Keep the original file: the editor never modifies it and always saves a new copy.

## Use

Linux:

```sh
tar xf nvidia-vbios-vix-editor-<version>-linux-x86_64.tar.gz
cd nvidia-vbios-vix-editor-<version>
./nvbios-gui                     # editor window (English)
./nvbios-gui --lang es card.rom  # Spanish, with a ROM
./nvbios fields card.rom         # JSON list of the fields
./nvbios edit card.rom out.rom --set power_max_w=700
```

Windows: double-click `nvbios-gui.exe`. The first start unpacks its GTK runtime to
`%LOCALAPPDATA%\NVIDIA VBIOS Vix Editor` (a few seconds); later starts reuse it. From a
terminal:

```powershell
.\nvbios-gui.exe --lang es card.rom
.\nvbios.exe fields card.rom
.\nvbios.exe edit card.rom out.rom --set power_max_w=700
```

The programs are not code-signed, so Windows SmartScreen may warn the first time:
choose *More info*, then *Run anyway*.

The editor window verifies each change while you type and saves a new ROM plus a JSON
manifest. The original file is never modified. On Windows it follows the light or dark app
mode; *File options > Theme* (or `--theme light` / `--theme dark`) changes it.

**Shunt multiplier (x)**: on a shunt-modded card, type the shunt factor (for example 2) and
the board power, PCIe slot and 12 V input current rows also show about the real limit, the
value times the factor. It is display only: the saved ROM keeps the values in the fields. It
assumes the same factor on every 12 V input shunt; NVVDD/MSVDD output current limits are
measured by the VRM and are not scaled.

### Startup environment

The compiled application isolates import search paths and disables site imports.
CPython still reads some startup variables before the application's recovery code
runs. Invalid `PYTHONMALLOC` or `PYTHONHASHSEED` values can therefore stop startup.
If those variables are set by another Python environment, launch with:

```sh
env -u PYTHONMALLOC -u PYTHONDEVMODE -u PYTHONHASHSEED ./nvbios --version
env -u PYTHONMALLOC -u PYTHONDEVMODE -u PYTHONHASHSEED ./nvbios-gui
```

## Screenshots

<table>
<tr>
<td align="center"><a href="https://github.com/Panchovix/nvidia-vbios-vix-editor/raw/main/docs/screenshots/gb202-rtx5090.png"><img src="https://github.com/Panchovix/nvidia-vbios-vix-editor/raw/main/docs/screenshots/gb202-rtx5090.png" width="280" alt="RTX 5090 (GB202)"></a><br>RTX 5090 (GB202): changes verified while typing</td>
<td align="center"><a href="https://github.com/Panchovix/nvidia-vbios-vix-editor/raw/main/docs/screenshots/gb203-rtx5080.png"><img src="https://github.com/Panchovix/nvidia-vbios-vix-editor/raw/main/docs/screenshots/gb203-rtx5080.png" width="280" alt="RTX 5080 (GB203)"></a><br>RTX 5080 (GB203): image just opened</td>
<td align="center"><a href="https://github.com/Panchovix/nvidia-vbios-vix-editor/raw/main/docs/screenshots/gb205-rtx5070.png"><img src="https://github.com/Panchovix/nvidia-vbios-vix-editor/raw/main/docs/screenshots/gb205-rtx5070.png" width="280" alt="RTX 5070 (GB205)"></a><br>RTX 5070 (GB205): single rail, current in A, fans</td>
</tr>
</table>

## Read before using an edited image

- Edited images keep the original cryptographic signature, which no longer matches.
  **Do not flash them with nvflash.** Load them through a firmware override method
  that accepts unsigned images. On Linux, the open
  [NVIDIA Linux VBIOS Vix Loader](https://github.com/Panchovix/nvidia-linux-vbios-vix-loader) loads them at
  boot; on Windows, the open
  [NVIDIA Windows VBIOS Vix Loader](https://github.com/Panchovix/nvidia-windows-vbios-vix-loader) loads them
  through the driver's registry override. Ada and Ampere GPUs read at most 512 KiB of the image, so they
  need a relocated payload: saving an edited Ada or Ampere copy in the editor window also saves it as
  `<name>-loader.bin`. From the command line:
  `nvbios normalize edited.rom payload.bin --representation ada-relocated-v2` (Ada desktop and
  workstation) or `--representation ampere-relocated-v1` (Ampere GA102–GA107). Both are experimental;
  so far they have been loaded on an RTX 4090 and an RTX A2000. Turing payloads fit without relocation:
  saving an edited Turing copy saves `<name>-loader.bin` (load it first) and `<name>-loader-e0end.bin`
  (`--representation turing-e0-end-v1`, to try if the first does not apply the edit); both have loaded
  on an RTX 2080 Ti through the Windows loader.
- **YOU ARE SOLELY RESPONSIBLE FOR WHAT YOU DO WITH THIS SOFTWARE.** Every modification
  you make, and any damage, malfunction, data loss or other harm to your hardware,
  your system or anything else that results from using this software or the images it
  produces, is entirely your own responsibility. The same applies to anything derived
  from the software or its output, such as edited images, files, tools or other works,
  whoever makes, shares or uses them. The author accepts no responsibility or liability
  of any kind for any of it. If you do not accept this, do not use the software.
- Fields marked *experimental* have not been tested on hardware. Raising power,
  current or voltage limits can damage hardware.
- Recognized images: GB20x object-directory v3 (GB202, GB203, GB205, GB206). Ada (AD10x),
  Ampere (GA10x) and Turing (TU10x/TU11x) images are supported with the same restriction as any other
  image: they can be inspected, and only the fields validated for them can be edited.
- Laptops: the RTX 5080 Laptop GPU layout is recognized. On a laptop the platform
  (Dynamic Boost) sets the running power limit, so a raised power ceiling may not raise
  it, and the fans belong to the laptop, not to the image. A lowered power ceiling loaded through the
  Windows loader on one RTX 3050 6GB Laptop GPU (Ampere); no other laptop is tested.

## Run from source

Python 3.11 or newer. The command line uses only the standard library; the editor window also
needs PyGObject with GTK 4.10 or newer:

- Ubuntu / Debian: `sudo apt install python3-gi gir1.2-gtk-4.0`
- Fedora: `sudo dnf install python3-gobject gtk4`
- Arch: `sudo pacman -S python-gobject gtk4`
- Windows: in an [MSYS2](https://www.msys2.org) UCRT64 shell,
  `pacman -S mingw-w64-ucrt-x86_64-python mingw-w64-ucrt-x86_64-python-gobject mingw-w64-ucrt-x86_64-gtk4`

```sh
git clone https://github.com/Panchovix/nvidia-vbios-vix-editor
cd nvidia-vbios-vix-editor
./nvbios fields card.rom                 # Windows (MSYS2): python nvbios fields card.rom
./nvbios edit card.rom out.rom --set power_max_w=700 --dry-run
./nvbios gui --lang es card.rom
```

`inspect`, `fields`, `verify`, `edit` and `normalize` print one JSON document,
`{"ok": true, "result": ...}`, or `{"ok": false, "error": {...}}` with exit status 2. On Windows,
start the window with `GSK_RENDERER=cairo python nvbios gui`: GTK's OpenGL renderer aborts on some
NVIDIA desktops, and the release programs choose cairo for the same reason. Over SSH the window
uses its built-in file picker; see `docs/gui.md`.

To install it, give it a virtual environment of its own. The Linux loader installs the same
`nvidia_vbios` package and `nvbios` command, so the two cannot share one:

```sh
python3 -m venv --system-site-packages .venv   # the system site-packages provide PyGObject
.venv/bin/pip install .
.venv/bin/nvbios --version
.venv/bin/nvbios-editor --lang es
```

The tests build small synthetic ROM structures; no VBIOS image is needed:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

The GTK window test is opt-in; see `docs/gui.md`. More documentation: `docs/editor-api.md`
(formats, editor API and limitations), `docs/extended-fields.md` (voltage, OCP, memory and fan
fields) and `docs/gui.md` (the window; in Spanish, `docs/gui_es.md`).

## Build

The release programs are compiled with Nuitka from this tree by the scripts in `tools/release/`.
Their version is `__version__` in `src/nvidia_vbios/__init__.py`.

- Linux: in a clean checkout with podman, `tools/release/build.sh X.Y.Z`. It builds in an
  Ubuntu 24.04 container (the oldest supported glibc and GTK), runs the tests first, and writes
  the archive, the one-file `nvbios` and `SHA256SUMS` to `dist/release-X.Y.Z/`.
- Windows: the *windows-release* GitHub Actions workflow (`.github/workflows/windows.yml`) builds
  `nvbios-gui.exe`, `nvbios.exe` and their third-party notices as a workflow artifact. Only the
  repository owner starts it, with *Run workflow* or by pushing a `vX.Y.Z` tag that matches the
  version. To build locally: an MSYS2 UCRT64 shell with the packages that workflow installs,
  Nuitka 4.2.2 and Zig 0.16.0 on `PATH`, then `VERSION=X.Y.Z tools/release/build-windows.sh`
  (output in `dist-windows/`).

## Contributing

Issues and pull requests are welcome. Run the tests before you open a pull request.
The maintainers port accepted changes into the project themselves, so a merged change
can land as a different commit from your branch. Contributions are licensed under
GPL-3.0-or-later, like the rest of the project.

Pull requests, forks included, run the unit tests on Linux (`.github/workflows/tests.yml`).

## Acknowledgements

Thanks to **@pantsoftime** ([overclock.net](https://www.overclock.net)), whose original GB202 VBIOS
editor and `vbios_override` patch this project builds on. Thanks also to @b00nza.

## License

Copyright (C) 2026 panchovix. GNU General Public License v3.0 or later (`GPL-3.0-or-later`), see
[LICENSE](LICENSE): you can use, study, change and share it, and changed versions you share must stay
under the same license. There is no warranty, to the extent permitted by law.

The source code is at <https://github.com/Panchovix/nvidia-vbios-vix-editor>; the tag `v<version>` matches
each release. The binaries also contain third-party components under their own licenses: see
THIRD_PARTY_NOTICES.md, which also says where to get their source code. Binary releases up to 0.1.13 were
distributed under a freeware license agreement.
