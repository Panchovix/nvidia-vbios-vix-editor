# Changelog

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
- Python environment variables are ignored; unexpected errors print one line instead
  of a traceback.
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
