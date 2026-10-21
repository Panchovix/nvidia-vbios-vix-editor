# Native offline GUI

English | [Español](gui_es.md)

The GTK4 editor uses the public immutable `nvidia_vbios.editor` library. It reads
local ROM files and saves new copies with JSON manifests. It does not flash,
deploy, activate, reload a driver or change GPU settings. A GPU need not be present.
An edited image says nothing about the settings currently applied to hardware.

English is the default interface language. Select Spanish explicitly with
`--lang es`; `--lang en` selects English. Language selection affects labels and
help text, while field IDs, units and JSON contracts stay unchanged. Backend
evidence stays in English in the JSON manifest; `nvbios fields` lists it with the raw diagnostics. Native
desktop/portal controls such as Cancel may follow the desktop language; dialog
titles, filters and accept buttons use the selected application language.

Launch from the repository with a Python interpreter that has PyGObject:

```sh
./nvbios gui
./nvbios gui /path/to/source.rom
./nvbios gui --lang es /path/to/source.rom
```

After installation, both the CLI and separate GUI launcher accept the same
language option and optional ROM path:

```sh
nvbios gui
nvbios gui --lang es /path/to/source.rom
nvbios-editor
nvbios-editor --lang es /path/to/source.rom
```

When the package is available to the interpreter, the module launcher also works:

```sh
python3 -m nvidia_vbios.gui --lang es /path/to/source.rom
```

Integration entry point: `nvidia_vbios.gui.main(argv=None)`, where `argv` is an
optional list containing `--lang en|es` and/or one ROM path. It returns the GTK
application exit code. It is wired to the separate installed `nvbios-editor`
launcher and the CLI's `nvbios gui [--lang en|es] [ROM]` command. Each invocation
opens its own application instance.

Dependencies: Python compatible with this package, PyGObject (`gi`), GTK4
introspection data and GTK **4.10 or newer** (`Gtk.FileDialog`). Tested with GTK
4.20.4 and system Python 3.14. PySide6 is not used. If a virtual environment cannot
see system `gi`, use a compatible system Python or an environment configured to
include those system packages. GUI and controller imports do not import GTK;
only invoking the GUI loads it, so the CLI/core remain usable without `gi`.

## Editing flow

1. **Open ROM…** opens a native GTK file dialog for a local file. Identity,
   product, architecture, BIOS version, format, source SHA256 and integrity are
   taken from the loaded immutable image. Unknown formats expose metadata and
   diagnostics without invented editable fields.
2. Enter values in the controls generated from typed field descriptors. Each
   control shows its public unit and the original value. Known field labels use
   the selected interface language. The ROM's rated defaults remain visible;
   accepted ranges are in `nvbios fields` and the manifest, never hardware-safe maxima.
   **Board power floor** (`power_min_w`) accepts 1 W through the TGP rated
   default, with exact 0.001 W increments. **Board power ceiling** remains
   bounded below by the rated defaults. Experimental fields (boot default power,
   12 V input current, clock offset ranges) say so in their label; stage partners
   such as a new default and ceiling together, because the order
   minimum <= default <= maximum is checked on the combined result. The 12 V input
   current values are stored policy values, not hardware-safe ratings; connector,
   slot and cable limits still apply. **Show advanced XOC-style fields** (off by
   default) reveals opt-in fields such as the rated power of the fixed board
   policies 2/7, the hardware thresholds (slot current; on Ampere and Turing
   the connector current; on Ada the NVVDD output power and the 12 V input
   current, labelled "threshold"), the Turing NVVDD output current limit and
   fixed REL/ALT voltages and, on Blackwell and Ada, **NVVDD REL and ALT follow
   OV** (a switch: on gives the flat XOC-style voltage limit; save it on its own,
   and keep the original image to go back) and, on Blackwell, **Fan zero RPM** (a
   switch for the flag bits that let the fans stand still at idle, hardware-tested
   on one RTX 5090; experimental) and, on Blackwell, Ada and Ampere, the **zero RPM
   lower and upper thresholds** of each fan and extra curve (the two temperatures
   stored with those bits; idle fans most likely stop below the lower one and start
   above the upper one; on one RTX 5080 a raised upper threshold kept the fans
   stopped below it; on Ada and Ampere editable only where zero RPM is on, and not
   hardware-tested there; experimental); values typed before ticking it are kept. Read-only 0/1 fields
   show On or Off. **Shunt multiplier (x)** (1 = off, up to 10) is display only:
   for board power, PCIe slot power/current, connector power/current and 12 V
   input current rows it adds a note with the real limit on a shunt-modded card, about
   the stored value times the multiplier, assuming the same factor on every 12 V
   input shunt.
   NVVDD/MSVDD output limits are measured by the VRM and are not scaled; nothing
   is written to the ROM. On Ampere images where another power row also caps the
   sum of the connector channels, each connector row notes that row's rated and
   maximum values; where that row has a field, raise **Connector power sum** too.
   Rated output OCP and the
   SFF slot power fields are also experimental: a rated value is what the firmware
   enforces from boot, so lowering it caps the card. On Blackwell the floor
   edits TGP row8 and preserves the distinct rows2/7 minima; recognized profiles
   override maximum/default only. Ada/Ampere use the header-indexed TGP row in
   every validated duplicate chain. These controls edit stored bounds;
   firmware acceptance and the runtime minimum remain unknown.
   Unsupported
   fields and unidentified input-current policies remain read-only with a reason.
   Reviewed per-rail output OCP ceilings appear in mA when the backend validates
   that exact policy/monitor association; enforcement by hardware remains untested.
   Recognized Blackwell memory offsets are edited in **MHz** on the NVML/Linux
   scale, which is twice the stored table value. Each memory row also shows the
   value Windows tools such as MSI Afterburner display (half the MHz value); the
   core offset is the same on both. With the advanced fields, **GPC curve offset**
   (Blackwell, Ada and Ampere; experimental, not hardware-tested; -500..+500 MHz)
   is expected to shift the stock core VF curve by that many MHz at every voltage, on
   every boot, under any tool's offset; 0 puts the stock bytes back. **Memory clock N MHz
   follows the memory offset** (Blackwell, Ada and Ampere; experimental, not
   hardware-tested) should let a negative memory offset move an intermediate memory
   level too, instead of the memory dropping to a low idle clock below it (an inferred
   meaning of the bit it sets); lower the memory
   offset floor as well. The overlapping table representation is not
   shown (it stays in `nvbios fields`). Current fields stored in mA (12 V input
   current, output OCP) are shown and typed in A with up to three decimals; the
   GUI converts them exactly, and the backend, CLI and manifest stay in mA. The
   fan PWM frequency is shown and typed in kHz the same way; the Fans card also
   sets the number of fan channels and, per channel, the minimum and maximum speed
   in RPM, then the three points of the channel's stored fan curve (temperature in
   °C, speed in RPM), and last the extra curves that serve every channel (all
   experimental). Temperatures take steps of 1/32 °C (`60.5` is fine, `60.01` is not)
   and show decimals only when they need them. A limit moves only as far as the
   stored curves: to lower a maximum below them, type the new maximum and the curve
   points above it, including those of the extra curves, and they are checked and
   saved together as one copy. To raise a minimum, also raise every curve point
   below it. If a curve blocks a limit, the row names the points that still need
   changing, including extra curves, using the values currently typed. For example,
   two fans and two extra curves starting at 1000 RPM require six changes to raise
   both minima to 1200 RPM: both minima and the first point of all four curves.
   No values are adjusted automatically. The minimum and maximum level (%) of each channel
   and the curve levels appear with the advanced fields. Save a new channel count
   before changing channel limits, curves or zero RPM on the copy.
   Voltage compatibility aliases, selector indices and stored boot values are
   not shown; `nvbios fields` lists them. The same goes for the generic input
   current and OCP placeholders (`current_limit_a`, `ocp_limit_a`) and the MSVDD
   ceiling of single-rail images while their value is unknown: no VBIOS row backs them.
   Each equation ceiling, including ALT, is an
   expression bound, not an evaluated VOP reading or runtime offset. **Minimum
   voltage (VMIN)** (experimental) is the stored value of the equation the driver
   evaluates as VMIN; on Ada the driver adds its chained terms (+90 mV on an RTX
   2000 Ada), so the value goes up to the lowest REL value less the most those terms
   can add (753 mV on that board). The read-only "rail INFO VMIN-slot" ceiling
   is a different equation and does not set VMIN. On Ada images whose REL or ALT
   is a constant (the newer RTX 4090 image, 4080, RTX 4000 Ada; ALT on the 4080
   SUPER, 4070 Ti SUPER and 4060), **NVVDD REL/ALT fixed voltage** (experimental)
   sets that value, from its clamp minimum up to the OV value (1200 mV), with REL at
   most ALT: change both together to raise REL past ALT. Lowering REL below a raised
   VMIN likewise needs VMIN in the same edit. Turing images get the same row with the
   advanced fields (REL 1068.75 mV and ALT 1093.75 mV on most boards, OV 1125 mV); there
   REL and ALT also stay at or above the boot voltage and VMIN plus its chained terms,
   and VMIN can be raised past the old REL when REL is raised with it (VMIN plus its chain
   stays at most REL). The full
   source SHA256 and integrity scope are in the saved manifest.
   Ada/Ampere do not inherit the Blackwell memory conversion.
3. The preview is live. Typing marks the row, shows original → new value and the
   change list in the bar at the bottom at once. After a 350 ms pause the copy is
   built in memory with `plan` and verified on a worker; the inputs stay editable
   while it runs, and results for older inputs are discarded. A value that is not
   a number is flagged on its row and never sent to the backend; an out-of-range
   value marks its row with the accepted range. `Ctrl+Enter` verifies at once.
   The change list shows memory once, in MHz; the raw table representation
   remains in the backend manifest.
   A static REL equation ceiling is not the voltage evaluated at runtime;
   temperature coefficients remain preserved by the backend.
4. **Reset changes** discards the proposal and returns controls to the
   immutable original. Saving stays disabled while inputs differ from the last
   verified copy or a check is running.
5. **Save Copy…** asks for a new local destination. The backend exclusively
   publishes both the ROM and `output.rom.json`; it refuses existing destinations,
   symlinks, the source and a changed source. A failed save retains the staged
   proposal for retry. A dialog opened for an older document cannot save a newer
   document accidentally. `Ctrl+Enter` with unchanged values permits an exact
   copy with a zero-change manifest for supported editable formats.

The GUI saves the archival bytes; it does not implicitly normalize the image.
Unknown/noneditable formats support inspection only. Cryptographic signatures
are neither verified nor regenerated. Capability decisions and architecture
gates come entirely from the backend; model strings and filenames do not select
an editor. See [the editor API](editor-api.md) for format support and limitations.

Keyboard: `Ctrl+O` open, `Ctrl+Enter` verify now, `Ctrl+S` save copy, `Ctrl+R`
reset, `Ctrl+Q` close. Tab navigates native controls. The default 760×920 window
is a single column: a device card (product, PCI ID, BIOS version, integrity),
then Power, Voltage, Clock offsets, Current and protection, and Fans cards, with
read-only fields grouped in a collapsed section after them. When part of the image
uses a layout the editor does not support yet (for example the fan tables of a few
images), the matching card says that some of its fields are not shown; the
heading appears even when no field is left. The change bar stays
visible below the scrolling fields. Experimental fields carry a badge.
Load/inspection, preview generation and save run outside the GTK main thread.
Generation checks discard results from earlier opens/resets. Backend errors show
stable error codes and messages in the status area.

## Tests and headless render

GTK-free controller tests use synthetic ROMs and temporary files:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_gui*.py' -v
```

The real GTK test is opt-in. Run on a dedicated test display, for example Xvfb
when available, without disturbing an existing desktop:

```sh
PYTHONPATH=src VBIOS_GUI_SMOKE=1 python3 -m unittest discover -s tests -p 'test_gui_gtk.py' -v
```

Without Xvfb, GTK's Broadway backend also works; bind it only to loopback. Start
it in a separate test terminal, then stop it after testing:

```sh
gtk4-broadwayd --address=127.0.0.1 --port=18765 :55
```

```sh
PYTHONPATH=src GDK_BACKEND=broadway BROADWAY_DISPLAY=:55 GSK_RENDERER=cairo VBIOS_GUI_SMOKE=1 VBIOS_GUI_SCREENSHOT="$PWD/screenshot.png" python3 -m unittest discover -s tests -p 'test_gui_gtk.py' -v
```

The smoke test instantiates a real GTK window and file dialog, asynchronously
loads/stages/saves a synthetic Blackwell ROM, checks memory control selection,
reset, stale-result handling, the absence of a technical-details section and original values,
and optionally renders PNG through GTK/GSK. The initial render used Spanish
labels; current language checks cover the English default and explicit Spanish
selection.
The Broadway content render explicitly allocates actual widgets at 760×920
because a browserless Broadway display has no native frame allocation. The PNG
includes the GTK header and content; it is not a screenshot of a desktop session.
The tests use only synthetic ROMs. Native chooser selection, portal behavior and
interactive assistive-technology navigation still require a desktop manual test.

## SSH / X11 forwarding (including MobaXterm)

If the desktop file dialog does not appear on your forwarded display, use the
in-process picker:

```sh
nvbios gui --file-dialog builtin
nvbios gui --lang es --file-dialog builtin /path/to/source.rom
```

The default `--file-dialog auto` selects this picker when SSH connection
variables are present. Locally it keeps the system dialog. `--file-dialog system`
explicitly selects the original desktop dialog. The built-in picker stays on the GUI's display and avoids asking the desktop
portal to select files.
Its GTK4 compatibility implementation uses Gtk.FileChooserDialog directly rather
than Gtk.FileChooserNative/FileDialog. See the [GTK API](https://docs.gtk.org/gtk4/class.FileChooserDialog.html).

The header's **File options** menu also offers:

- **Open/Save with built-in picker…** to choose files with an integrated browser.
- **Open by path…** (`Ctrl+Shift+O`) and **Save copy by path…** (`Ctrl+Shift+S`) to
  type or paste a local file path, independently of any file browser.

Paths refer to files on the **Linux computer**, even when its windows are shown
on Windows. Absolute paths, relative paths and `~/` work in the path dialog.
Loading an existing ROM from the command line also bypasses the open dialog.
Saving still requires a verified current preview and a new destination, and
creates the same ROM plus JSON manifest. Neither picker can overwrite the source
or an existing output, save a stale preview, or modify GPU settings.

MobaXterm must still provide a working forwarded display for GTK itself. If the
window has rendering problems over X11, software rendering can be selected for
that launch:

```sh
GDK_BACKEND=x11 GSK_RENDERER=cairo nvbios gui --file-dialog builtin
```

The integrated picker and path-entry flows are covered by isolated Broadway GTK
tests for opening, saving, cancellation, stale previews and no-overwrite behavior.
This automated check does not exercise a particular Windows X server.
