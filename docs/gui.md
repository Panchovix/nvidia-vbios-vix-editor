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
   minimum <= default <= maximum is checked on the combined result. On a laptop,
   Dynamic Boost requests the running power limit at runtime and the ceiling only caps
   it; monitoring tools show the stored ceiling, so raising it alone usually does not
   raise the running limit. On one RTX 5090 Laptop GPU the running limit went from 175
   to about 185 W only with the ceiling, the boot default and **Notebook base TGP**
   raised together (190, 110 and 165 W, from 175, 95 and 150 W); the ceiling alone, or
   with only one of the other two, left it at 175 W. To raise the running limit, raise
   the three together, the boot default by as many watts as you raise the base TGP, and
   keep the base TGP at or below the ceiling, which stays the cap. Other laptops are not
   tested, and the laptop's VRM, cooling and power adapter were sized for the stock
   limit. The window notes this under the three fields on RTX 5080 and 5090 Laptop GPU
   ROMs. The 12 V input
   current values are stored policy values, not hardware-safe ratings; connector,
   slot and cable limits still apply. **Max operating temperature** (Blackwell, Ada,
   Ampere and Turing, in the Power card; experimental, not hardware-tested) is the
   temperature limit the driver reports as the GPU's maximum operating temperature (in
   `nvidia-smi`, the current temperature plus T.Limit, as checked on desktop cards): it
   goes down to 40 °C and up to 3 °C above the product's stock value (90 °C on an RTX
   5090 or RTX 4090, 93 °C on an RTX 3090, 89 °C on an RTX 2080 Ti), in steps of 1/32
   °C, and it is read-only on XOC-style ROMs, where that limit is disabled or missing.
   A lower value is expected to make the driver slow the GPU sooner, and a higher one
   leaves less thermal margin. The
   RTX 5080 and 5090 Laptop GPU ROMs also store a second limit of the same kind (87 °C) whose
   role was not traced, so raising the value there may have no effect. On Ampere and Ada laptop
   ROMs it is read-only: they store a lower limit of the same kind (89 °C) and it is not
   known which one the GPU reaches first. **Show advanced XOC-style fields** (off by
   default) reveals opt-in fields such as the rated power of the fixed board
   policies 2/7, the experimental **Notebook base TGP** of the RTX 5080 and 5090 Laptop
   GPU (it behaved as the base Dynamic Boost adds its boost to on one RTX 5090 Laptop
   GPU; raise it with the ceiling and the boot default, see above), on
   Ada and Blackwell the power limit of the auxiliary power connector (**Connector power
   channel 1**, experimental: on a board with one 8-pin connector it most likely holds that
   connector near 150 W even with a higher board power limit; a PCIe 8-pin connector is rated
   150 W, and going past what the connector and its cable are rated for puts the cable, the
   connector and the power supply at risk, which is your call; the board power, slot and 12 V
   input current limits still apply; the row notes this), the
   hardware thresholds (slot current; on Ampere and Turing
   the connector current; on Ada the NVVDD output power and the 12 V input
   current, labelled "threshold"), the Turing and Ampere NVVDD output current
   limit (on Ampere it may be what caps a laptop below a raised power ceiling;
   untested, and the VRM was sized for the stock value), the Turing and Ampere fixed
   REL/ALT voltages and **NVVDD REL and ALT follow
   OV** (a switch: on gives the flat XOC-style voltage limit; save it on its own,
   and keep the original image to go back; on the saved copy
   **NVVDD flat voltage (REL = ALT = OV)**, right under it, sets that voltage, 850 to
   1560 mV, on Ada 830 to 1560 mV, on Ampere 900 to 1430 mV, on Turing 950 to 1462 mV, and
   never below the highest VMIN where each chip sets its own) and,
   on Blackwell, Ada and Ampere, **Fan
   zero RPM** (a switch for the flag bits that let the fans stand still at idle,
   hardware-tested on one RTX 5090, not on Ada, Ampere or the RTX PRO 6000 Max-Q;
   experimental). On blower boards that store no fan-stop values (RTX PRO 6000
   Max-Q, RTX 5000 and 6000 Ada, RTX A-series) the switch also writes the values
   NVIDIA stores on another of its boards, and off on such a copy writes the stock
   bytes back; notes under the switch name that board and the risks: no blower card
   ships with fan stop on, a stopped blower most likely moves no air through the card,
   memory and power stages included, until the card passes the upper threshold,
   restarting a blower from 0 RPM is untested, and dense multi-GPU builds can see heat
   soak and stop/start cycling. On any other ROM that ships with zero RPM off (every
   RTX PRO and RTX A-series board, some GeForce Ampere ones) a note gives the same
   risks for a card with a blower fan. Where the switch would leave the fan channel
   entries with bit 4 of their flag byte clear (the RTX PRO 6000 Workstation and Max-Q
   and the blower boards above), a note says that no shipped ROM runs zero
   RPM with that flag form and that whether the fans stop is untested. Where an entry
   stores the same lower and upper threshold (the RTX 3060 8GB, 40 °C), a note says
   there is no hysteresis, so the fans may stop and start often around it, and to set
   that lower threshold a few degrees below. A fan tool that holds manual control keeps
   the fans running whatever the switch says. A ROM whose fan entries disagree (one
   RTX 3060) shows the field read-only as Mixed. An HP OEM RTX 3060 12 GB ROM keeps a
   copy of its fan 1 settings, most likely unused, in the entry of a second fan channel
   it disables: a note says the editor changes both the same way (curve points, zero RPM
   and its thresholds), and **Fan channels** stays read-only. On a copy where the switch wrote
   fan-stop values, turning it off and changing its thresholds are separate saves. The
   **zero RPM lower and upper thresholds** of each fan and extra curve (Blackwell, Ada
   and Ampere) are the two temperatures stored with those bits: idle fans most likely
   stop below the lower one and start above the upper one, and on one RTX 5080 a
   raised upper threshold kept the fans stopped below it. The upper threshold goes up
   to point 1 of the same fan curve. With zero RPM on, a point 1 below the upper
   threshold, or zero RPM turned on with an upper threshold above point 1, is refused
   and the row to change says its allowed range; change them together (on an RTX 3090,
   turning zero RPM on needs both upper thresholds lowered to 51.90625 °C, their point
   1, or less). Where the lower threshold is at or above point 1 (an RTX 3080's extra
   curves, the GA106 RTX 3050, some RTX 4090 ROMs) its row is marked too: set it below the
   upper threshold in the same edit. A larger **Fan channels** count that turns on a
   stored fan whose upper threshold is above its point 1 with zero RPM on is refused:
   turn zero RPM off and save, change the count on that copy, then turn zero RPM on
   with that threshold lowered (on the RTX 3060 whose entries disagree the count cannot
   be raised). On Ada and Ampere the thresholds are editable wherever the switch is,
   and not hardware-tested there; experimental. Values typed before ticking **Show
   advanced XOC-style fields** are kept. Read-only 0/1 fields show On or Off. **Shunt multiplier (x)** (1 = off, up to 10) is display only:
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
   firmware acceptance and the runtime minimum remain unknown. Some Ada ROMs (an
   MSI RTX 4090 image) pick their power limits from the 16-pin cable sense pins.
   There the board power ceiling and boot default also write the profile of the
   top level, and the lower levels keep their own limits and set the lowest
   accepted values (experimental, not hardware-tested). Notes under the rows say
   that the top level is most likely a 600 W cable (inferred), that going past
   600 W is your call, and that the 12 V input current threshold (about 576 W at
   12 V on that ROM, an advanced field) may limit first, so raise it too.
   Unsupported
   fields and unidentified input-current policies remain read-only with a reason.
   Reviewed per-rail output OCP ceilings appear in mA when the backend validates
   that exact policy/monitor association; enforcement by hardware remains untested.
   Recognized Blackwell memory offsets are edited in **MHz** on the NVML/Linux
   scale, which is twice the stored table value. Each memory row also shows the
   value Windows tools such as MSI Afterburner display (half the MHz value); the
   core offset is the same on both. **Factory GPC offset (vendor overclock)** and
   **Factory memory offset (vendor overclock)** (Blackwell, Ada, Ampere and Turing;
   experimental, not hardware-tested; shown without the advanced fields) are the factory
   overclock a board vendor stores in the ROM (+15 to +195 MHz on the core on the
   factory-OC ROMs reviewed; a memory offset on two RTX 20 ROMs only). The GPC offset
   takes -500 to +500 MHz and the memory offset -5000 to +5000 MHz, in whole MHz. The
   memory offset is in the memory clock that `nvidia-smi` and MSI Afterburner show (7000
   MHz on 14 Gbps GDDR6); nvidia-settings, which shows the transfer rate, and the memory
   offset ceiling and floor rows use twice that number, which the row shows too (-5000 to
   +5000 MHz here is -10000 to +10000 MHz there). On a ROM that stores no factory offset
   (Founders Edition, reference, workstation and laptop ROMs) the field shows 0, and a
   value other than 0 turns one on, which was not tested on such ROMs (the row says so);
   0 turns the offset off the way those ROMs store it, so it gives back their original
   bytes, even from a saved copy. A
   negative value lowers the clock, values far from the stock one can make the
   card unstable or keep it from starting, and whether a tuning tool's offset adds to the
   factory one or replaces it was not traced. The **Factory rated boost clock** in the
   read-only list stays as stored. With
   the advanced fields, **GPC curve offset** (Blackwell, Ada and Ampere; experimental, not
   hardware-tested; -500..+500 MHz) is expected to shift the stock core VF curve by that
   many MHz at every voltage, on every boot, under any tool's offset; 0 puts the stock
   bytes back. It is not the factory GPC offset: on a factory-OC ROM both apply. **Memory clock N MHz
   follows the memory offset** (Blackwell, Ada and Ampere; experimental) was meant to
   let a negative memory offset move an intermediate memory level too, instead of the
   memory dropping to a low idle clock below it; on the one card tested (an RTX 3050
   Laptop GPU) it did not. The overlapping table representation is not
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
   saved together as one copy. To raise a minimum, also raise the points of that
   fan's own curve below it; the extra curves may stay below a minimum. If a curve
   blocks a limit, the row names the points that still need changing (for a maximum
   including the extra curves), using the values currently typed. For example, two
   fans and two extra curves starting at 1000 RPM require four changes to raise both
   minima to 1200 RPM: both minima and the first point of both fan curves.
   No values are adjusted automatically. The minimum and maximum level (%) of each channel
   and the curve levels appear with the advanced fields. Save a new channel count
   before changing channel limits, curves or zero RPM on the copy. A lower count greys
   out the rows of the fans it turns off (the copy keeps them stored but off) and the
   change list shows their values as "not used"; a value typed in such a row comes back
   when the count turns its fan on again. A higher count lists the stored values of the
   fans it turns on. An RTX 3050 6 GB or 8 GB ROM stores its extra curve (Extra fan
   curve 1) in the entry of a second fan channel that it disables, so **Fan channels**
   stays read-only there and its row says why.
   Voltage compatibility aliases, selector indices and stored boot values are
   not shown; `nvbios fields` lists them. The same goes for the generic input
   current and OCP placeholders (`current_limit_a`, `ocp_limit_a`) and the MSVDD
   ceiling of single-rail images while their value is unknown: no VBIOS row backs them.
   Each equation ceiling, including ALT, is an
   expression bound, not an evaluated VOP reading or runtime offset. On Blackwell,
   **NVVDD REL floor** and **MSVDD REL floor** (experimental, under each REL ceiling)
   set the lowest REL: REL is the chip's own value kept between the floor and the
   ceiling, so a floor above it becomes the REL; raise both together to go past the
   stored ceiling, up to OV (1200 mV). On Ada, **NVVDD REL floor** does the same where
   REL follows the temperature (it falls as the GPU heats up), from 830 mV (or, where
   each chip sets its own VMIN, from the highest VMIN it can reach): the floor
   is then the REL of a hot GPU. **Minimum
   voltage (VMIN)** (experimental) is the stored value of the equation the driver
   evaluates as VMIN; on Ada the driver adds its chained terms (+90 mV on an RTX
   2000 Ada), so the value goes up to the lowest REL value less the most those terms
   can add (753 mV on that board). The read-only "rail INFO VMIN-slot" ceiling
   is a different equation and does not set VMIN. Where each chip sets its own VMIN
   (a tree of equations on fused values and the temperature: RTX PRO 6000 and PRO 4000,
   RTX 5060 Ti, RTX 5080 Laptop GPU, RTX 5090 MSVDD and several Ampere and Ada boards)
   the row starts empty and reads "Original: per chip"; a value fixes VMIN at it for
   every chip and temperature (on Ada the terms chained after it still add theirs).
   Experimental and not tested on hardware: a value below the chip's stock VMIN can make
   idle and light-load states unstable, and the driver might keep its stock VMIN. On a
   copy saved that way **Fixed VMIN** shows as a switch, and turning it off writes the
   stock bytes back; save that change and a new value in separate copies. On the RTX 4090 95.02.3C ROMs a
   15 mV constant that sets the memory clock voltage floor links the VMIN equation;
   a new VMIN there first copies that equation into an unused VFE slot, so the
   memory floor keeps its stock value and a lower VMIN shows only at the 405 MHz idle
   memory clock; a higher one shows at every memory clock only above 826 mV (inferred,
   not measured). Its notes say so, and that no Ada card has run an equation the
   editor adds: the override might not load or the driver might fail to start, and
   removing the override brings the card back. The stock value
   restores the stock bytes. Save VMIN and the GPC curve offset in separate copies
   there, since both use that slot. On Ada images whose REL or ALT is a constant
   (the newer RTX 4090 image, 4080, RTX 4000 Ada; ALT on the 4080
   SUPER, 4070 Ti SUPER and 4060), **NVVDD REL/ALT fixed voltage** (experimental)
   sets that value, from its clamp minimum up to the OV value (1200 mV), with REL at
   most ALT: change both together to raise REL past ALT. Lowering REL below a raised
   VMIN likewise needs VMIN in the same edit. Turing images get the same row with the
   advanced fields (REL 1068.75 mV and ALT 1093.75 mV on most boards, OV 1125 mV); there
   REL and ALT also stay at or above the boot voltage and VMIN plus its chained terms,
   and VMIN can be raised past the old REL when REL is raised with it (VMIN plus its chain
   stays at most REL). Ampere images get it for each rail (MSVDD too on the two-rail GA102
   boards), also with the advanced fields: REL goes up to OV (1100 mV), and an ALT already at
   1100 mV (GeForce boards) stays there. The full
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
reset, `Ctrl+I` import from another ROM, `Ctrl+Q` close. Tab navigates native
controls. The default 760×920 window
is a single column: a device card (product, PCI ID, BIOS version, integrity),
then Power, Voltage, Clock offsets, Current and protection, and Fans cards, the
collapsed **Advanced** section, and the read-only fields grouped in a
collapsed section after them. When part of the image
uses a layout the editor does not support yet (for example the fan tables of a few
images), the matching card says that some of its fields are not shown; the
heading appears even when no field is left. The change bar stays
visible below the scrolling fields. Experimental fields carry a badge.
Load/inspection, preview generation and save run outside the GTK main thread.
Generation checks discard results from earlier opens/resets. Backend errors show
stable error codes and messages in the status area.

**Advanced: performance controllers and idle power** (Blackwell, Ada, Ampere and Turing;
collapsed, after the Fans card and before the read-only fields; every field experimental and
not hardware-tested)
holds two groups, each in its own card. Under **Clock controllers**, the **Utilization clock
policy** switch and, for the GPC, DRAM and VID clocks, the **utilization target** and **jump
threshold** (whole percent; 10 % up to 1 % below the jump threshold, and the target + 1 % up
to 100 %; to move the target to or above the stored jump threshold, raise the jump threshold
in the same edit) and the **clock-down** and **clock-up hysteresis** (samples; 0.5x to 4x
stock down, 1 to 4 up). These tune how the driver raises and lowers clocks with load: a
lower target raises the clock sooner at partial load, with more power and heat. That the
driver uses this table is not proven on any of these cards. Under **Idle power saving**, the
idle power switches the ROM has, each **Stock** (as shipped) or **Off**: **GR power gating**
and **Memory system clock gating, MSCG** on every family, **NVDEC/NVENC/OFA/NVJPG power
gating** on Blackwell, **DIFR idle display power saving** on Blackwell and on the Ada cards
that ship it on, and **GR rail gating** where it ships on (among the reviewed ROMs the RTX
PRO 4000 SFF, the RTX 5080 and 5090 Laptop GPU and the GA102 RTX 3080/3090, RTX A4500..A6000
and A40 cards); and the **DIFR** and **GR rail gating idle times** (ms or µs, GR rail gating
in 10 µs steps, 0.5x to 4x stock). Where a switch's entries look the same shipped off or
turned off (GR rail gating, Ada DIFR, Turing GR power gating and MSCG) and the editor has not
reviewed the product, the switch covers the entries the ROM enables, and its row says so: a
copy saved with **Off** no longer shows that switch, so keep the original ROM to go back to
**Stock**. An entry the editor does not recognize keeps the switch read-only, with the
reason. They are expected to act only at idle or light load (inferred).
Off costs a little idle power and may avoid idle stutter or flicker; very short idle times
can cause stutter or, rarely, a black screen at idle. A value that depends on a switch (the
controller values on the utilization policy, an idle time on its feature) is greyed out,
with the reason, while that switch is off, including when you turn it off before saving; a
value typed there shows the stored one meanwhile, and turning the switch back on makes it
editable again with the typed value. This section is not behind **Show advanced XOC-style
fields**, and **Import from ROM…** never copies it.

**Memory (read-only)**, a collapsed section after the read-only fields, shows the
memory tables of Turing, Ampere, Ada and Blackwell images (`nvbios memory` prints the
same report as JSON, see [the editor API](editor-api.md)). It is read on a worker the
first time it is opened. It lists the memory configurations (strap → column, vendor,
type code; only type 9 is named, GDDR6) and, per column, the timing entry of each band
that holds a stock memory clock (every band above 0 MHz when the editor does not read the
ROM's stock clocks, as on Turing) with its decoded values in controller cycles: tRC, tRAS and
tRP are marked "inferred" (their names come from byte patterns, not NVIDIA documentation),
tRFC "probable", CL and tWR "tentative". Columns with the same entries share one
heading; a column the memory clock table does not have is listed with a note. Which
configuration a card uses is set by the board, not by the ROM. On
Blackwell it also shows the board memory-training profile of object 0x89 as a tag and
a fingerprint: undecoded per-board boot data, probably memory-interface training. A
difference there does not mean one BIOS is faster, and it only takes effect by
flashing the whole ROM; the override cannot apply it. **Raw bytes** lists every band
with its bytes, the timing entries the bands select, each table hash and the profile
bytes. **Compare with another ROM…** reads a second ROM on a worker and says, per
section, whether it is identical or differs (the number of differing entries or profile
fields, whose meaning is unknown), never which one is better. The configuration, band
and timing lines compare the entries in use; the table line compares every byte of each
table and names the tables that differ. Nothing in this section edits, stages or saves
anything, and the comparison leaves the open ROM, the change list and saving untouched.

**Import from ROM…** (in the change bar) copies values from another ROM of the same family
into the open one, for example the fan settings of another board: choose the ROM, tick the
sections (Power, Voltage, Clock offsets, Current and protection, Fans; never the
Advanced section) and, if wanted, the advanced XOC-style fields (off by default). The other ROM is read on a worker. Each value that
differs and that this ROM can take is typed into its row as if you had entered it: it shows in the
change list, is verified like any other value, and retyping the original value or **Reset
changes** undoes it. A value you had typed in a chosen section where both ROMs agree goes back to
the value both ROMs hold. Nothing is written until **Save Copy…**, and pending values of other sections stay.

Related fields come whole from the other ROM or not at all: a minimum, rated value and maximum;
a fan curve (the fan limits and each point's temperature, speed and level); the 12 V input limit
and its policy 7 copy. When one of them differs but is left out, for example the rated power of
the fixed board policies, an advanced field you did not include, the others are held back too.
The levels of a fan curve are advanced fields too, but they come with their curve even when the
advanced fields are not ticked: each ROM pairs its fan speeds with levels set for its own fans, so
speeds without their levels would run the fans at other speeds than the curve says. They show in
the change list and stay behind **Show advanced XOC-style fields**, which the import turns on only
when you tick the advanced fields and some of them come. A value the editor refuses is dropped
with the values it depends on (those related fields, or all voltage fields). With zero RPM on, a
curve that starts below this ROM's zero RPM upper threshold is refused unless the other ROM's
thresholds, or its zero RPM off, come with it, so without the advanced fields the summary asks you
to import again with them.
The dialog then says how many values were imported and lists the fields left out with their
reason: not in one of the ROMs, read-only, another quantity in the other ROM (other units,
memory level, notebook or board power layout, or voltage equation, such as REL and ALT that
follow OV), outside this ROM's range, an advanced field not included, held back with related
fields, or refused by the editor. Fields read-only in both ROMs are listed only when they hold
related fields back. The fan channel count describes the board's fans and is never copied,
and neither is the **Max operating temperature** (each product has its own); a value you typed
in it stays. The **Factory GPC offset** and **Factory memory offset** come with the Clock offsets.
If the other ROM stores none (a Founders Edition, for example), this ROM gets 0 MHz, and a ROM
that stores none takes the other ROM's value.
Another GPU family or format (for example a loader `.bin`) is refused; another product of the same family (another PCI device ID) is
allowed with a warning. `nvbios import` does the same from the command line (see [the editor
API](editor-api.md)).

**Values are copied as stored numbers, not adapted to this board.** Fan speed limits, power or
current limits and voltage limits from another board can exceed what this board's hardware is
rated for, for example fans rated for a lower speed or a single 12V-2x6 connector where the other
board has more power connectors or stronger power stages. A factory GPC or memory offset from
another board may not be stable on this one. Check every imported value in the change list before saving.

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
