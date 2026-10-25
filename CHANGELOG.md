# Changelog

## 0.1.35

- **RTX 5080 and RTX 5090 Laptop GPU: raise the boot default, the base TGP and the ceiling together.** One user
  reported that on their RTX 5090 Laptop GPU (stock 175 W), raising **Board power ceiling** alone, or with only **Boot
  default board power** or only **Notebook base TGP**, left the GPU at about 175 W. Raising all three together (190 W
  ceiling, 110 W boot default and 165 W base TGP, from 175, 95 and 150 W) took the GPU to about 185 W under load. On
  that laptop the running limit looks like the boot default plus 55 W, at most the base TGP, plus 25 W of Dynamic
  Boost, and never above the ceiling (inferred from this one laptop; for those values it gives 190 W). So to raise the
  running limit, raise the three together, the boot default by as many watts as you raise the base TGP, and keep the
  base TGP at or below the ceiling, which stays the cap. The notes under the three fields and the docs now say so, and
  **Notebook base TGP** is now marked as tested on that laptop. It stays experimental and under **Show advanced
  XOC-style fields**, and nothing changed in what the fields accept. **Notebook base TGP** exists only on Blackwell
  laptop ROMs with this power layout (the RTX 5080 and RTX 5090 Laptop GPU); Ampere and Ada laptops do not have it.
  The RTX 5080 Laptop GPU and other laptops are not tested, and the 55 W and 25 W most likely come from each laptop's
  system BIOS, so they can differ between models. The laptop's VRM, cooling and power adapter were sized for the stock
  limit, and a battery that drains while plugged in under full CPU and GPU load means the adapter falls short. For API
  users: on the RTX 5080 and RTX 5090 Laptop GPU layout, `power_max_w`, `power_default_w` and `notebook_base_tgp_w`
  carry a `hardware-test` evidence entry whose scope names that one laptop.

## 0.1.34

- **Ampere: the NVVDD output current limit can be edited (experimental, opt-in).** Under **Show advanced XOC-style
  fields**, Ampere ROMs now show **NVVDD output current limit ceiling** and **NVVDD output current limit, rated** (row
  13 of the power table). Before, the ceiling was shown read-only. On one RTX 3050 Ti Laptop GPU, a raised power
  ceiling and boot default stopped at about 60-64 W with power limit as the reason. Its ROM stores 45 A there, while
  an 80 W ROM of the same GPU stores 90 A, so this low stored value is the likely cause of that cap, though it is not
  proven. The ceiling can be raised alone. To raise the rated value past the stored ceiling, raise the ceiling in the
  same edit: 90 A in the window, or in mA on the command line
  `nvbios edit ROM OUT --set nvvdd_output_ocp_max_ma=90000 --set nvvdd_output_ocp_rated_ma=90000`. 90 A is what the
  80 W ROM stores, and smaller steps are possible. The limit likely protects the core VRM, which was sized for the
  stock value, and it is not known whether the GPU enforces it. Once it is raised, the stored voltage ceiling,
  read-only on Ampere, may be the next limit, and two other NVVDD rows (16 and 17, not editable) may bind first; those
  would show as a hardware slowdown, not a power limit (inferred). Values stay below 5001 A, the value the ROM uses
  for no limit. Not tested on hardware. Reported in [issue
  #8](https://github.com/Panchovix/nvidia-vbios-vix-editor/issues/8).
- **Power connector limit on Ada and Blackwell (opt-in, experimental).** An RTX 4070 with one 8-pin power connector
  stopped at about 143 W on that connector (about 95 % of a stored 150 W limit) even with a higher board power limit,
  most likely because the ROM also stores a power limit for the auxiliary power connector; a similar stop was reported
  on an RTX 5060 Ti with one 8-pin connector (no readings). On the Ada and Blackwell ROMs where the editor recognizes
  it (in its corpus: RTX 4070, RTX 4060 Ti, RTX 5060 Ti, RTX 4000, 4500, 5000 and 6000 Ada), **Connector power channel
  1** now shows it under **Show advanced XOC-style fields**, with its ceiling and rated value; to raise the rated
  value past the stored ceiling, raise the ceiling in the same edit. The ROM does not say which connector the board
  has: a PCIe 8-pin connector is rated for 150 W, a 12V-2x6 cable for the level its sense pins report. Going past what
  the connector and its cable are rated for puts the cable, the connector and the power supply at risk, and that is
  your call. The board power limit, the PCIe slot limit and the 12 V input current limit still apply and may limit
  next, so raise them too where needed; on the RTX 4000 Ada a 12.34 A threshold on the same connector (not editable)
  may limit it first, near 148 W. Not tested on hardware. For API users: the keys are `connector_1_power_max_w` and
  `connector_1_power_rated_w`, as on Ampere, with `opt_in: true` and `power_input: "auxiliary-connector"`.
- **RTX PRO 6000 Max-Q and RTX 5070: the 12 V input current reasons name the connector.** On these ROMs the 12 V input
  current policy reads the auxiliary power connector input, not the whole 12 V input, so it limits the current through
  the connector alone. Only the field reasons changed.

## 0.1.33

- **RTX 5090 Laptop GPU: the NVVDD and MSVDD output current limits can be edited.** Its output OCP
  rows are the same as on the RTX 5080 Laptop GPU (NVVDD 180 A, MSVDD 60 A), so the ceiling and rated values of
  both rails are now editable there too. Before, they were read-only on this laptop. Not tested on hardware.
- **RTX 5090 Laptop GPU: the GR rail gating switch.** Its idle power tables are the same as on the RTX 5080 Laptop
  GPU, so **GR rail gating** (entries 0 to 2) and its idle time can now be set there too. Before, both were read-only
  on this laptop. Other ROMs that enable GR rail gating with the value the editor knows get the switch too (next
  entry). Not tested on hardware.
- **RTX 5090 Laptop GPU: Max operating temperature can be raised.** Its stock value is 89 °C, the same as on the RTX
  5080 Laptop GPU, so it now goes up to 92 °C like there. Before, it could only be lowered. Both laptops also store a
  second, lower temperature limit (87 °C) whose role is not known, so a raised value may have no effect. Not tested on
  hardware.
- **Idle power switches on products the editor has not reviewed.** In some tables an entry that ships off looks the
  same as one turned off: GR rail gating, DIFR on Ada, and GR power gating and MSCG on Turing. On a product the editor
  has not reviewed, these switches were read-only. Now the switch covers the entries that ROM enables, as long as they
  hold the values the editor knows. A copy saved with **Off** no longer shows that switch, because nothing in it says
  which entries to turn back on, so keep the original ROM to go back to **Stock**. The row in the window says so. A
  ROM that enables none of those entries still has no switch. For API users: such a switch carries
  `lpwr_coverage: "enabled-entries"`, and an accepted **Off** edit lists it in `affected_fields` with `after: 0` but not
  in the copy's fields.
- **Laptop output current limits are recognized by the ROM's tables, not by its device ID.** Another Blackwell
  laptop ROM with the same power layout, both voltage rails, output current rows and sensor chain as the RTX 5080 and
  5090 Laptop GPU ROMs gets the same editable NVVDD and MSVDD output current limits. Not tested on hardware.
- **Laptops: the power ceiling notes say what it does and does not do.** On a laptop, Dynamic Boost (the NVIDIA
  platform framework on Windows, nvidia-powerd on Linux) requests the running power limit at runtime, and the ceiling
  in the ROM only caps it. Monitoring tools show the stored ceiling, so raising **Board power ceiling** alone usually
  does not raise the running limit: one user reported that on their RTX 5090 Laptop GPU, raising it from 175 to 225 W
  and also the boot default left the GPU at 175 W. The window now says so under the ceiling on RTX 5080 and 5090
  Laptop GPU ROMs.
- **Notebook base TGP (experimental, opt-in; RTX 5080 and 5090 Laptop GPU).** A new field under **Show advanced
  XOC-style fields** edits a stored value, 150 W on both laptops, that may be the base TGP Dynamic Boost adds its
  boost to. That is a guess from a public log of another RTX 5090 Laptop GPU and has not been tested. When you change
  it, it has to stay between **Boot default board power** and **Board power ceiling**. To go above the ceiling, raise
  the ceiling with it in the same edit, for example a 225 W ceiling and a 200 W base
  (`nvbios edit ROM OUT --set power_max_w=225 --set notebook_base_tgp_w=200`). It does not limit the other power
  fields: if you leave it alone, the ceiling and the boot default keep the same ranges as before. A ROM whose ceiling
  is below it or whose boot default is above it does not show the field but keeps its stored value, and the field
  comes back once they are moved back. The laptop's VRM, cooling and power adapter were sized for the stock limit.

## 0.1.32

- **Lowering Fan channels no longer gets stuck on "Checking changes…".** Typing a smaller fan channel count (for
  example 2 on a 3-channel ROM such as the ROG Matrix or the Astral 20th anniversary, to use it on a 2-channel Astral)
  left the window waiting forever, so the copy could not be saved; `nvbios edit ROM OUT --set fan_channels=2` was not
  affected. Now the rows of the fans the new count turns off are greyed out with the reason and show their stored
  values, the change list shows those values as "not used" (and the values of the fans a larger count turns on as "not
  used → value"), and an unexpected error in the window or during an import shows in the status line and in the import
  window instead of a silent wait.
- **Greyed-out rows keep what you typed.** A value typed in a row that the fan channel count or a switch (the
  utilization policy, a DIFR or GR rail gating feature) greys out comes back when the count turns its fan on again or
  the switch is turned back on, so a passing count such as 1 while typing 3 loses nothing. Before, a row greyed out by
  a switch went back to its stored value for good. Hidden advanced values of a fan the count turns off stay out of the
  check until the count turns it on again.
- **The change list no longer shows unchanged hidden fields.** Turning **Show advanced XOC-style fields** off while an
  edit was being checked listed every hidden advanced field as "800 → 800 W", "Off → Off" and so on until the check
  ended, and kept them if it failed.

## 0.1.31

- **Import from ROM… copies a fan curve with its levels.** Importing the Fans section now brings each fan curve with
  its levels (%), also when the advanced fields are not ticked (and with `nvbios import` without
  `--include-opt-in`). Each ROM pairs its fan speeds with levels set for its own fans, so speeds without their levels
  run the fans at other speeds than the curve says. Before, a curve whose levels differed, which is nearly always the
  case between two boards, was left out whole. The zero RPM switch and temperatures and the other advanced fields
  still come only when ticked, and the imported levels show in the change list without turning on **Show advanced
  XOC-style fields**. With zero RPM on, a curve that starts below this ROM's zero RPM upper threshold still needs the
  advanced fields, so that the other ROM's thresholds (or its zero RPM off) come with it. The summary now says so,
  and `nvbios import` lists those fields as `partners` of the refused ones.
- **The import window shows its whole summary.** It grows up to a height and then scrolls with a visible scroll bar.
  Before, it could show only its first two lines, so an import that left fields out looked like "Nothing imported"
  with no reason.

## 0.1.30

- **VMIN set per chip (experimental; Ampere, Ada and Blackwell).** On many ROMs the minimum voltage is not one
  stored value: each chip computes its own from fused values and the temperature, so VMIN was read-only there. It now
  shows "per chip" and can be fixed to one value, from 450 mV up to the lowest REL value of that rail (450 to 875 mV
  on the RTX PRO 6000 Max-Q, whose chips get 640 to 715 mV). A new **Fixed VMIN** switch goes back to the per-chip
  value with the original bytes, also from a saved copy; the value and the switch are saved in separate edits.
  Covered: both rails of the RTX PRO 6000 Max-Q, the RTX PRO 4000 SFF and the RTX 5080 Laptop GPU, NVVDD of the RTX
  PRO 6000 Workstation and RTX 5060 Ti, MSVDD of the RTX 5090; the RTX 3050, 3060, 3060 Ti and 3070, RTX A2000 and
  A4000 and the RTX 3070 and 3080 Laptop GPUs; the RTX 4060, 4060 Ti, RTX 4000 and 5000 Ada and the RTX 4050 and 4080
  Laptop GPUs. Turing ROMs already store a fixed VMIN. It stays read-only where something else in the ROM uses the
  same equation (RTX 6000 Ada, RTX 4070 Laptop GPU) or the original bytes could not be written back (RTX 4060 Laptop
  GPU). The fixed VMIN of the RTX 4070 Ti SUPER becomes editable too (400 to 836 mV). Import from ROM… copies a fixed
  VMIN only between ROMs that set it the same way. That the driver applies the fixed value on these ROMs is inferred
  from the firmware. Not tested on hardware.
- **Fan zero RPM on Ada and Ampere, and on blower workstation cards (experimental).** The **Fan zero RPM** switch,
  so far on Blackwell, now works on Ada and Ampere ROMs: GeForce desktop ROMs and the RTX 4000, 4000 SFF, 4500 and
  2000 Ada, which store the fan-stop values with the feature off. Blower cards that store no fan-stop
  values take the ones NVIDIA stores on a related card: the RTX PRO 6000 Max-Q from the RTX PRO 6000 Workstation,
  the RTX 5000 and 6000 Ada from the RTX 4000/4500/2000 Ada, the RTX A1000 to A6000 from the RTX 3080 Ti Founders
  Edition. Turning it off writes the original bytes back. No blower card ships with fan stop on. A stopped blower
  most likely moves no air through the card, memory and power stages included, until the card passes the start
  temperature, a blower starting again from 0 RPM was not tested, and dense multi-GPU builds may see heat soak. A
  fan tool that holds manual control keeps the fans running. The window lists these notes on each card, and on the
  RTX 3060 8GB, which stores the same stop and start temperature (40 °C), suggests a lower stop temperature. It
  stays read-only on the RTX A2000 and on one RTX 3060 whose fan entries disagree. Turing ROMs can stop their fans
  through the fan curve instead (minimum and point 1 at 0 RPM), as some of them ship. Not tested on hardware on Ada,
  Ampere or the Max-Q.
- **Zero RPM start temperature follows the fan curve (Ampere, Ada and Blackwell).** With zero RPM on, the
  temperature at which the fans start again can be at most the first point of the same fan curve. Every edit that
  changes either value, turns zero RPM on, imports a curve or raises the fan channel count is checked, and the
  refusal names the fields to change. ROMs that ship a higher start temperature keep it while it and the curve stay
  as they are. On a card with zero RPM on, lowering the first curve point now needs the start temperature lowered in
  the same edit, and the stop temperature too where it sits at or above that point, as on some ROMs. A higher fan
  channel count that brings in a stored fan whose start temperature is above its curve goes in steps: zero RPM off,
  the count, then zero RPM on with that start temperature lowered. On the RTX 3060 whose fan entries disagree, the
  count can no longer be raised. On Ada and Ampere the zero RPM temperatures are editable while zero RPM is off, so
  both can change in one edit.
- **Smaller changes.** On Blackwell, zero RPM is offered only where the ROM stores a fan-stop block the driver
  accepts, as on Ada and Ampere. No zero RPM temperature shows a minimum above its maximum. For API users: VMIN
  fields carry `vmin_tree` and a `*_vmin_fixed` switch, imports may list `per_chip_in_donor`, `fan_zero_rpm` may
  carry a `fan_stop_template`, a mixed `flag_state`, `channel_bit4_clear` and `zero_rpm_flat_pairs`, and the start
  temperature rule refuses with `ZERO_RPM_ABOVE_CURVE`, with `details.channel_count` when the fan channel count is
  the cause (`docs/editor-api.md`). An extension binding over the fan-stop bytes is now refused also next to a
  `fan_zero_rpm` request.

## 0.1.29

- **Factory GPC and memory offsets on every ROM (experimental; Turing, Ampere, Ada and Blackwell).** The vendor
  overclock of the factory clock record is now editable on Turing, Ampere and Ada as on Blackwell, and on every ROM,
  not only on factory-OC ones: the driver reads the entry the same way whether the ROM ships it on or off. The GPC
  offset goes from -500 to +500 MHz. A new **Factory memory offset** goes from -5000 to +5000 MHz in the memory
  clock nvidia-smi and MSI Afterburner show (7000 MHz on 14 Gbps GDDR6); nvidia-settings shows the transfer rate,
  twice that number, and the row shows that value too. On a ROM that shipped without an offset (Founders Edition,
  reference, workstation and laptop ROMs) a value other than 0 turns one on, which was not tested on such ROMs.
  0 turns it off the way those ROMs store it, so it gives back their original bytes even from a saved copy. A
  negative value lowers the clock, and values far from stock can make the card unstable or keep it from starting.
  Import from ROM… copies both offsets, so a Founders Edition donor brings 0 MHz. Not tested on hardware.
- **Max operating temperature on Turing, Ampere and Ada (experimental).** The same field as on Blackwell: lower it
  to 40 °C or raise it up to 3 °C above the product's stock value. It is read-only on Ampere and Ada laptop ROMs,
  which hold a second, lower limit, and on the two Turing XOC ROMs, which name none. On a desktop RTX 2000 Ada the
  current temperature plus nvidia-smi's T.Limit matched the stored value; laptops were not checked. Never copied by
  Import. Not tested on hardware.
- **Advanced section on Turing, Ampere and Ada (experimental).** The clock controllers (utilization policy, and per
  GPC, DRAM and VID clock the target, jump threshold and hysteresis) on all three families, and the idle power
  switches each ROM ships turned on: GR power gating and MSCG on all three, GR rail gating with its idle time on
  GA102 cards and the A40, DIFR with its idle times on Ada. The same ranges, switches and caveats as on Blackwell,
  including that it is not proven the driver uses the clock controller table. Not tested on hardware.
- **RTX 4090 BIOS with 16-pin cable power profiles (experimental; Ada).** Newer builds such as the MSI RTX 4090
  Suprim 95.02.3C.40.EA pick their power limits from the 16-pin cable sense pins (150/300/450/520 W profiles), and
  the editor hid the power limits on them. They are editable again: the board power ceiling and boot default write
  the base table and the profile of the top cable level (most likely a 600 W cable, inferred) together, since a
  selected profile replaces the base value. The ceiling has no cap at 600 W, as on other Ada ROMs; going past the
  cable rating is the user's call. The boot default goes from 450 to 520 W and the floor up to 300 W (a profile no
  cable level selects bounds an edit with twice its value). The 12 V input threshold (48 A, about 576 W) may limit first, so raise it too
  (advanced field). Not tested on hardware.
- **VMIN on RTX 4090 95.02.3C builds (experimental; Ada).** These builds link the VMIN equation to the voltage floor
  of the higher memory clocks, so VMIN was read-only. The editor now copies the equation to an unused slot for the
  memory floor and edits VMIN alone (400 to 935 mV); 811 mV gives back the original bytes. A lower VMIN shows only
  while the memory runs at 405 MHz; a higher one shows at every memory clock only above 826 mV. This is the first
  equation the editor adds on Ada, so the override might not load or the driver might not start; removing the
  override brings the card back. VMIN and the GPC curve offset are saved in separate edits on these ROMs. Not
  tested on hardware.
- **Smaller changes.** Edits on Blackwell are about three times faster. The Spanish texts use "tú" throughout.
  For API users: factory offsets use the `"<xi"` encoding (flag byte plus signed kHz) and carry `factory_entry` and
  `stored_flag`; `max_operating_temp_c` may carry `lower_limits`; VMIN on 95.02.3C carries `vfe_clone`, and its
  manifest lists the copied equation bytes as raw hex (`docs/editor-api.md`).

## 0.1.28

- **Max operating temperature (experimental; Blackwell).** A new Power field sets the thermal limit the driver
  reports as the GPU's max operating temperature (90 °C on an RTX 5090, 88 °C on an RTX 5080). It can be lowered to
  40 °C or raised up to 3 °C above the product's stock value. A lower value is expected to make the driver slow the
  GPU sooner, and a higher one leaves less thermal margin. It is read-only where the ROM ships this limit switched
  off (ASUS XOC, MSI Lightning), and on a product the editor has no stock value for it can only be lowered. On the
  RTX 5080 Laptop GPU the ROM holds a second, lower limit, so raising it there may do nothing. Not tested on
  hardware.
- **Factory GPC offset (experimental; Blackwell).** The vendor overclock that factory-OC ROMs store (for example
  +120 MHz on a Gigabyte Aorus, +195 MHz on an ASUS Matrix) is a new Clock offsets field, -500 to +500 whole MHz. A
  negative value lowers the clock. It is editable only where the ROM already stores one; Founders Edition,
  reference, laptop and RTX PRO ROMs show 0 read-only and the editor does not add one. The rated boost clock is
  shown read-only next to it. It is separate from the GPC curve offset, and whether a tuning tool's GPC offset adds
  to it or replaces it was not traced. Not tested on hardware.
- **Import from ROM… copies the factory GPC offset with the Clock offsets** when both ROMs store one. A ROM that
  stores none neither gives nor takes one, and an offset from another board may not be stable on this one. The max
  operating temperature belongs to each product and is never copied; it shows as left out with that reason.
- **Advanced section: clock controllers and idle power saving (experimental; Blackwell).** A new collapsed section,
  separate from the advanced XOC-style fields and never copied by Import, holds:
  - **Clock controllers.** The utilization policy that decides how the driver raises and lowers the GPC, memory
    (DRAM) and video (VID) clocks with load: an on/off switch, and per clock domain the utilization target, the jump
    threshold and the clock-down and clock-up hysteresis. The target goes from 10 % up to one below the jump
    threshold, the jump threshold up to 100 %, the clock-down hysteresis from 0.5x to 4x stock and the clock-up one
    from 1 to 4 samples. A lower target raises the clocks sooner, with more power and heat. It is not proven that
    the driver uses this table on Blackwell.
  - **Idle power saving.** Stock/Off switches for GR power gating, memory system clock gating (MSCG), NVDEC, NVENC,
    OFA and NVJPG power gating, DIFR idle display power saving and, on the RTX PRO 4000 SFF and the RTX 5080 Laptop
    GPU, GR rail gating. The DIFR and GR rail gating idle times can be set from 0.5x to 4x stock. Off uses a little
    more power at idle; very short idle times can cause stutter or, rarely, a black screen at idle.
  - A value that depends on a switch can only be changed while that switch is on. Setting every value back to
    stock gives the original bytes. Nothing in this section is tested on hardware.
- **Ampere and Ada images that end with an empty table before the checksum are editable, some laptops included.**
  Some builds, for example the RTX 3060 Laptop GPU 94.06.22, the RTX 3050 6GB 94.07.91 and the RTX 4070 Laptop GPU
  95.06.15, end their last data image with an empty table and fewer than 15 0xff bytes before the checksum byte. The
  editor required those 15 bytes before it would repair the checksum, so every field on these images was read-only.
  It now accepts this ending too and still rewrites only the checksum byte. Turing keeps the previous rule. The
  loaders still refuse Ada laptop images, so an edited RTX 4070 Laptop GPU copy cannot be loaded yet.

## 0.1.26

- **Import from another ROM (Turing, Ampere, Ada and Blackwell).** **Import from ROM…** and `nvbios import ROM DONOR
  [OUTPUT] --sections fans[,power,...] [--include-opt-in] [--dry-run]` copy the editable values of the chosen
  sections (power, voltage, clock offsets, current, fans) from another ROM of the same family, for example the fan
  settings of another board. The values go through the usual checks. Related fields (a minimum, rated value and
  maximum; a fan curve with its limits, temperatures, speeds and levels) come whole from the other ROM or not at
  all, values that mean another quantity there (a notebook TGP, REL and ALT that follow OV) are left out, the fan
  channel count is never copied, and the summary says why values were left out. Advanced fields only when ticked
  (`--include-opt-in`): fan levels, the fixed board power rating on Blackwell and the fixed REL/ALT voltages on
  Turing are advanced, so when they differ the whole fan curve, the board power set or, on Turing, VMIN is left out
  with them. Another family or format (such as a loader `.bin`) is refused; another product of the same family gets
  a warning. In the editor window the values become pending changes, saved only with Save Copy. They are copied as
  stored numbers, not adapted: fan speeds, power or current limits and voltage limits from another board can exceed
  this board's hardware.
- **Read-only memory view (Turing, Ampere, Ada and Blackwell).** A collapsed **Memory (read-only)** section and
  `nvbios memory ROM [--compare ROM2] [--raw]` show the memory configurations (strap → column, vendor, type code),
  the memory clock bands with the stock memory clocks they hold (not on Turing, or where the editor cannot read
  them), and the timing entries in controller cycles: tRC, tRAS and tRP inferred from byte patterns, tRFC probable,
  CL and tWR tentative, with the raw bytes. Which configuration a card uses is set by the board. On Blackwell an
  undecoded board memory-training profile (object 0x89) is shown as a tag and a fingerprint; it only takes effect by
  flashing the whole ROM. **Compare with another ROM…** says per section whether the tables are identical or differ,
  never which ROM is better; a differing profile does not mean a faster BIOS. Nothing is edited.
- **Windows driver 621.01 works on Blackwell, Ada and Ampere.** Overrides loaded with the Windows loader on an
  RTX 4090 (Ada) and an RTX A2000 (Ampere) stayed in place through the driver update, and after restarting Windows
  Verify reported both as `override-active`. On an RTX 5070 (Blackwell), Verify reported `override-active` for an
  edited VBIOS loaded on 621.01 after a GPU restart. Turing is not tested on 621.01 yet. The editor and Windows
  loader READMEs now list 621.x.
- **Memory levels that follow the memory offset: hardware result.** On the one card tested, an RTX 3050 Laptop GPU
  with the override verified, setting the field on its 5501 MHz level (with a lower memory offset floor) did not
  stop the memory dropping to 810 MHz below a -500 MHz offset. The bit these fields set does not decide that drop
  on that card, and what does is unknown; the fields stay, with this result in their notes.

## 0.1.25

- **GPC curve offset (experimental, opt-in; Blackwell, Ada and Ampere).** A new field shifts the stock core VF curve
  by a default number of MHz (-500 to +500), stored in the BIOS: a constant equation linked to the curve's root
  equation. No stock BIOS does this; NVIDIA shifts the curve inside its equations instead. That the driver adds
  it to every point of the curve is inferred, and it is not tested on hardware; large values can make the card
  unstable. A tuning tool's offset still applies on top; 0 restores the stock bytes.

## 0.1.24

- **Memory levels that follow the memory offset (experimental, opt-in; Blackwell, Ada and Ampere).** A memory offset
  only seems to move the top stored memory levels: past the next lower level the memory drops to a low idle clock
  instead (on one RTX 3050 Laptop GPU, below a -500 MHz offset it fell from 6001 to 810 MHz). New fields, one per
  intermediate level ("Memory clock N MHz follows the memory offset"), set the bit the stock BIOS sets on the levels
  the offset moves. That this bit is what makes a level move is inferred, so it may or may not let a degraded memory
  run between the stored levels; lower the memory offset floor too. Not tested on hardware.

## 0.1.23

- **Fan zero RPM temperatures on Ada and Ampere (experimental, opt-in).** The lower and upper zero RPM
  thresholds now also appear on Ada and Ampere images that store them, and they are editable where zero RPM is on
  (every enabled fan entry sets both bits, as on the GeForce Ada images and most GeForce Ampere ones; written to
  every image chain). Elsewhere they are read-only, for example on the RTX 3080, 3090, 3070 and 3050 images of the
  corpus. Not tested on Ada or Ampere hardware. Turing images store no thresholds, so they get none.
- **Fan zero RPM upper threshold tested on one RTX 5080.** With the upper threshold set to 60 °C (stock 50 °C), the
  fans stayed at 0 RPM at 59 °C during video playback; before, they started at about 52 °C. Reported
  in [issue #12](https://github.com/Panchovix/nvidia-vbios-vix-editor/issues/12).
- **Turing: a raised power limit confirmed on an RTX 2070.** With the power limit raised from 200 to 225 W, loaded
  through the Windows loader, the card reached 225 W. Reported in
  [Windows loader issue #4](https://github.com/Panchovix/nvidia-windows-vbios-vix-loader/issues/4).

## 0.1.22

- **Fan minimum speed: lowering it did not lower the fans on one RTX 5080.** On a Zotac RTX 5080, an image with
  both fan minimums and the first point of every curve lowered from 1050 to 900 RPM loaded through the Windows
  loader (Verify matched byte for byte), but at the driver's 30 % the fans still ran at about 1050-1110 RPM. The
  field descriptions now say so. Reported in [issue #12](https://github.com/Panchovix/nvidia-vbios-vix-editor/issues/12).

- **GUI: explain fan-curve limits.** A rejected fan minimum or maximum now names the curve points that must
  change in the same edit, including extra curves, in English and Spanish. The hint uses pending values and
  appears on each blocked fan row. Backend limits and saved bytes are unchanged.
- **Fan zero RPM temperatures (experimental, opt-in, GB20x).** New fields `fan_N_zero_rpm_low_temp_c` /
  `fan_N_zero_rpm_high_temp_c` and `fan_extra_M_zero_rpm_*_temp_c`: the two temperatures stored with the zero RPM
  bits in each fan policy entry (43/50 °C on most images). Idle fans may stop below the lower one and start above
  the upper one; that meaning is inferred from the firmware decode and the stored values, not traced, and it is not
  tested on hardware. Shown with the advanced fields, only where the entry stores a pair. Requested in
  [issue #12](https://github.com/Panchovix/nvidia-vbios-vix-editor/issues/12).

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
