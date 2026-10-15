# NVIDIA VBIOS Vix Editor

Offline editor for NVIDIA Blackwell (GB20x) VBIOS images, for Linux and Windows, with a
GTK editor window and a JSON command line. It edits power limits, voltage ceilings, clock offset ranges,
12 V input current and output OCP limits, fan PWM frequency and fan channels. Ada
(AD10x) and Ampere (GA10x) images are supported too, limited to their validated fields.

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
manifest. The original file is never modified.

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
  that accepts unsigned images.
- **YOU ARE SOLELY RESPONSIBLE FOR WHAT YOU DO WITH THIS SOFTWARE.** Every modification
  you make, and any damage, malfunction, data loss or other harm to your hardware,
  your system or anything else that results from using this software or the images it
  produces, is entirely your own responsibility. The same applies to anything derived
  from the software or its output, such as edited images, files, tools or other works,
  whoever makes, shares or uses them. The author accepts no responsibility or liability
  of any kind for any of it. If you do not accept this, do not use the software.
- Fields marked *experimental* have not been tested on hardware. Raising power,
  current or voltage limits can damage hardware.
- Recognized images: GB20x object-directory v3 (GB202, GB203, GB205, GB206). Ada (AD10x)
  and Ampere (GA10x) images are supported with the same restriction as any other
  image: they can be inspected, and only the fields validated for them can be edited.

## Acknowledgements

Thanks to @pantsoftime and @b00nza.

## License

See LICENSE and THIRD_PARTY_NOTICES.md.
