# NVIDIA VBIOS Vix Editor

Offline editor for NVIDIA Blackwell (GB20x) VBIOS images, with a GTK editor window and
a JSON command line. It edits power limits, voltage ceilings, clock offset ranges,
12 V input current and output OCP limits, fan PWM frequency and fan channels.

**Not affiliated with, endorsed by or sponsored by NVIDIA Corporation.** NVIDIA and
GeForce are trademarks of NVIDIA Corporation.

## Download

From the Releases page:

| File | Contents |
|---|---|
| `nvidia-vbios-vix-editor-<version>-linux-x86_64.tar.gz` | editor window (`nvbios-gui`) and command line (`nvbios`) |
| `nvbios-<version>-linux-x86_64` | command line only, one file |
| `SHA256SUMS` | checksums: `sha256sum -c SHA256SUMS` |

## Requirements

- Linux x86_64 with glibc 2.39 or newer: Ubuntu 24.04+, Debian 13+, Fedora 40+, Arch and
  derivatives.
- Editor window: GTK 4.14+ and the GObject Introspection runtime.
  - Ubuntu / Debian: `sudo apt install libgtk-4-1 libgirepository-1.0-1`
  - Fedora: `sudo dnf install gtk4 gobject-introspection`
  - Arch: `sudo pacman -S gtk4 gobject-introspection-runtime`
- Command line: nothing else.

## Use

```sh
tar xf nvidia-vbios-vix-editor-<version>-linux-x86_64.tar.gz
cd nvidia-vbios-vix-editor-<version>
./nvbios-gui                     # editor window (English)
./nvbios-gui --lang es card.rom  # Spanish, with a ROM
./nvbios fields card.rom         # JSON list of the fields
./nvbios edit card.rom out.rom --set power_max_w=700
```

The editor window verifies each change while you type and saves a new ROM plus a JSON
manifest. The original file is never modified.

## Read before using an edited image

- Edited images keep the original cryptographic signature, which no longer matches.
  **Do not flash them with nvflash.** Load them through a firmware override method
  that accepts unsigned images.
- Fields marked *experimental* have not been tested on hardware. Raising power,
  current or voltage limits can damage hardware. You use this software at your own
  risk.
- Recognized images: GB20x object-directory v3 (GB202, GB203, GB205, GB206). Other
  images can be inspected; their editable fields are limited to what was validated.

## License

Free to use, closed source: see `LICENSE`. Third-party components keep their own
licenses: see `THIRD_PARTY_NOTICES.md`.
