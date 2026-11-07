# Changelog details

What each change does, where it applies, what was tested and its risks. CHANGELOG.md lists the same
changes, one line each, in the same order.

## 0.1.44

- **Ada: the power connector limit on 16-pin boards that store it (RTX 4090 95.02.18.C0.75, untested).** A Gigabyte
  RTX 4090 ROM (95.02.18.C0.75) stores a power limit on its 16-pin connector input (row 6, 600 W), and its cable
  sense profiles change it: profile 2 sets 450 W, profile 3 (the top level) 600 W. The editor did not show it because
  the 16-pin connector input carries a value in bytes 10..13 (200, as the Turing current correction offset, nvgpu
  curr_corr_offset) that the 8-pin boards do not. That exact value is now accepted; any other parameter still rejects the channel. **Connector power channel 1** now shows it
  under **Show advanced XOC-style fields**, like on the other boards with this limit. An edit writes the base row and
  profile 3's entries in every chain; profile 2 keeps 450 W and bounds the values from below. A class-0 current
  limit on the same connector (row 8 here, 57.5 A, about 690 W at 12 V; its enforcement is unknown) has no field,
  and the row names it as a limit that may bind next; the RTX 4070, RTX 4000 Ada and RTX 4500 Ada rows now name
  theirs too. The other 16-pin images (RTX 4090, 4080 and others) read that connector only with class-0 rows and
  still get no field. The bytes an edit writes on the other boards do not change. Not tested on hardware. Reported
  in [issue #32](https://github.com/Panchovix/nvidia-vbios-vix-editor/issues/32). For API users: the descriptors may
  carry `current_limit_rows`.

## 0.1.43

- **Fields tested on hardware are no longer experimental on their GPU family.** One table in the registry
  (`registry.HARDWARE_TESTED`) lists the fields tested per family. There they carry no experimental flag and no
  badge in the window, and their notes name the test. The bytes an edit writes do not change.
  - Turing: desktop board power and the connector power rows (RTX 2070 at 225 W, RTX 2080 Ti at 500 W with 250 W
    per connector), and the runtime power limit switch (one RTX 2070 Laptop GPU).
  - Ampere: board power, laptops included (RTX 3050 6GB Laptop GPU at 70/55 W, RTX A2000), PCIe slot power (RTX
    A2000), the fan minimums (RTX 3090 blower, issue #24) and point 1 of a fan's own curve (HP RTX 3060, issue #22).
  - Ada: board power (RTX 2000 Ada, RTX 4090 95.02.18 at 671 W), the NVVDD REL ceiling (RTX 2000 Ada, 1100 mV), the
    GPC offset ceiling (RTX 4090, +1200 MHz), a pinned NVVDD VMIN (RTX 2000 Ada, 700 mV stored, 790 mV reported),
    PCIe slot power (RTX 2000 Ada) and the fan minimums (RTX 4070, 800 RPM with the level at 15 %).
  - Blackwell: the boot default power (RTX PRO 6000 Max-Q; RTX 5090 Laptop GPU with the base TGP and ceiling), the
    notebook base TGP, the NVVDD and MSVDD REL floors (three RTX PRO 6000 Max-Q and an RTX PRO 4000 SFF at 1100 mV),
    a constant NVVDD VMIN (RTX 5080, 800 -> 850 mV), the GPC offset ceiling, memory offset floor and 12 V input
    current (RTX 50 boards), PCIe slot power and the runtime voltage offsets switch (RTX PRO 4000 SFF), zero RPM (HP
    Omen RTX 5090), the fan speed maximum (RTX 5080, 3500 -> 4000 RPM) and the upper zero RPM threshold (Zotac RTX
    5080 at 60 °C, issue #12).
  - Still experimental: the lower zero RPM threshold, curve points 2 and 3 and the extra curves,
    `input_current_policy7_limit_ma` and the Ada and Ampere input current thresholds, values bound to an override
    profile (Ada cable sense profiles, the ASUS RTX 5090 XOC ROMs), the Ada and Turing notebook TGP, a VMIN set per
    chip or through a min/max tree, the VMIN copy of the RTX 4090 95.02.3C ROMs, zero RPM where it writes another
    board's values or leaves bit 4 clear, and every other field.
  - For API users: those descriptors no longer carry `experimental`.

## 0.1.42

- **Blackwell: runtime voltage offsets switch, mVolt+-compatible VFE hooks for runtime offset tools (experimental;
  worked on one RTX PRO 4000 SFF).** On Windows 621.01 and newer the driver ignores rail voltage offsets on RTX 50
  cards, so mVolt+ applies its offsets through VFE variables: in the BIOS override each REL, ALT, OV and VMIN limit
  gets a hook, an equation that adds a dedicated variable (in uV, clamped to +-1.25 V) to the original equation, and
  at runtime it writes the variable. The new **Runtime voltage offsets** switch (advanced) writes those same bytes on
  every RTX 50 ROM that allows it: a copy of the stock template variable and a hook equation per present REL, ALT, OV
  and VMIN selector of each rail, in the first unused VFE entries, with the selector moved to the hook. The image
  stores no offset, so with no runtime tool nothing changes. Off removes the hooks and gives back the stock bytes (on
  the RTX PRO 6000 Max-Q ROMs two unused variables get clean unused bytes instead of their leftover ones). A ROM whose
  selectors all hold complete hooks, mVolt+-made ones included, shows the switch on; a partial or foreign set is
  read-only. With hooks installed, the REL floor and ceilings, ALT and OV ceilings and VMIN edit the original
  equations through the hooks, so fixed values and runtime offsets work together and the order of the edits does not
  matter; the follow-OV switch is read-only while hooks are installed. On the ASUS XOC and MSI Lightning ROMs, and on
  copies whose REL and ALT follow OV, REL, ALT and OV share one equation: each gets its own hook linking it, as mVolt+
  installs them. With hooks installed after a GPC curve offset, that offset can change but not go back to 0 until the
  hooks are removed (it would leave a gap in the unused VFE entries). Open and edit copies with hooks only with this
  version or newer: older versions show the hook clamp (1250 mV) as the REL and OV ceilings, and editing it there
  breaks the hooks. Tested statically on all 35 GB20x ROMs of the corpus: the installed bytes equal an independent
  build from the layout, every limit evaluates the same with the variables at 0, and removal gives back the stock
  bytes. On one RTX PRO 4000 SFF (Linux, driver 615.78.08) the VFE masks and selectors the GSP firmware reports
  matched the hooks, and a runtime tool wrote the hook variables (hardware result). Other cards and drivers are
  untested, and the VMIN hooks link a min/max root on most ROMs, a link no NVIDIA image has. Load the copy with the
  loader; removing the override brings the card back. For API users: the field carries `runtime_hooks` (the slot
  table: rail, role, stored word, hook, variable, target, the reference template variable and the leftover entries an
  install takes), and hooked voltage fields carry `selector.runtime_hook`.

- **Blackwell: `nvbios vfe-layout` prints the layout document runtime offset tools read to trust the voltage-offset
  hooks.** A runtime tool that writes the hook variables has to know which VFE entries are hooks before it writes one.
  `nvbios vfe-layout PAYLOAD` prints that table for an image whose runtime voltage offsets switch is on, as the
  `nvidia-runtime-vfe-layout/v1` JSON document: the image's SHA-256, the untouched template variable read as the
  reference, bitmaps of the used VFE variables and equations, and per hook its rail, role (REL, ALT, OV or VMIN), hook
  equation, linked equation, variable and clamp. It prints the document itself, not the result envelope (LF line ends,
  also on Windows); `--output FILE` writes it through a temporary file replaced in one step, replacing an existing
  FILE. Images that are not RTX 50, have no complete set of hooks or break a rule of the document (unused entries that
  are not one block at the end of their table, no untouched template variable, other hook bytes, shared hooks or
  variables, a hook that is another slot's linked equation) are refused with the usual error envelope. Tested
  statically on every GB20x ROM of the corpus with hooks installed (the document matches the hook table and every
  rule), and the documents of 8 edited payloads of 7 RTX 50 cards equal the ones built and checked for them
  independently. On one RTX PRO 4000 SFF (Linux, driver 615.78.08) the document matched the VFE masks and selectors
  the GSP firmware reports, and a runtime tool wrote the hook variables (hardware result). For API users:
  `nvidia_vbios.rom.vfe_layout.layout_document(image)` returns the document.

- **Ada: cable sense levels may apply a direct and a threshold profile with different limits (RTX 4090
  95.02.18.C0.75, untested).** On a Gigabyte RTX 4090 ROM (95.02.18.C0.75, reported in [issue
  #32](https://github.com/Panchovix/nvidia-vbios-vix-editor/issues/32)) 0.1.41 still hid the power fields, now with
  "Ada override profile thresholds are not ascending or name a disabled profile". Its threshold row names two
  disabled profiles (4 and 5) that no sense code selects, and at codes 2 and 3 its sense entries name direct profiles
  2 and 3 while the threshold row selects profiles 6 and 7. Static analysis of GSP-RM 615.78.08 and 620.70.06 shows
  that the firmware applies only the threshold a vote selects, and that at a code with a vote it applies the direct
  profile first and then the threshold profile. On this ROM the direct profiles set row 6 and the 12 V input maxima
  and the threshold profiles set only the TGP maximum, so the result does not depend on the order. The editor now
  accepts a threshold that names a disabled profile when no vote selects it, and a direct profile that differs from
  the threshold profile when it is enabled and the two set different limits; a direct profile that sets a limit the
  threshold profile sets too, a disabled one at a code that votes, and a selected threshold naming a disabled profile
  are still refused. Each field binds the top level's entries on its own rows: `power_max_w` writes the base TGP row
  and profile 7 together (600 to 800 W changes 14 bytes in the two chains, checksums included), and
  `input_current_max_ma` stays read-only because direct profile 3 sets 60 A there against 58 A in the base. Where a
  sense level sets a row's maximum but not its rated value (here profile 6, TGP 450 W, and profile 2, 12 V input
  45 A, both at code 2), the base rated value runs under that maximum at that level; how the firmware treats a rated
  value above it is not known (not analysed), so the editor does not bound it and the reasons of `power_default_w`
  and `input_current_rated_ma` name the profile and its maximum. The `power_max_w` reason now says that the other profiles bound it from
  below only, with no upper bound but the encoding. Tested on a synthetic image built from the profile table the user
  posted and on a corpus ROM of the same version with the same table; nothing was loaded on a card. Load the copy
  with the loader, never flash it; removing the override brings the stock behaviour back.

- **Ada: REL ceiling, REL floor and ALT ceiling edits must keep REL at or below ALT at every temperature (RTX 4090
  95.02.18).** The REL ceiling, the REL floor and the ALT ceiling were each checked against their own range only, so
  on the RTX 4090 95.02.18 images (REL 1640 - 5.714 x T clamped to 1040..1080 mV, ALT 20 mV higher, clamped to
  1060..1100 mV) a REL ceiling of 1195 mV with ALT left at 1100 mV was accepted, and so was a REL floor and ceiling of
  1195 mV with the ALT ceiling at 1195 mV, although ALT keeps its 1060 mV clamp minimum when hot (reported by a user).
  Every voltage edit now checks its result, on every family: where REL and ALT are each one clamped quadratic equation
  (a constant or a temperature equation on the same variable), REL must stay at or below ALT at every input value,
  checked exactly at the points where REL minus ALT can peak; otherwise the edit is refused with `OUT_OF_BOUNDS`, a
  message naming the REL (or ALT) field and the voltages where REL passes ALT. Raising the REL and ALT ceilings
  together still works, and neither ceiling is capped at OV. ALT has no floor field, so on those images the REL floor
  goes up to 1060 mV; a flat higher REL is the follow-OV switch and its value (REL = ALT = OV). Not checked where the
  editor cannot evaluate REL or ALT: a compare on fused inputs (RTX 4060 family, 4070 Ti SUPER) and the GB20x
  leakage polynomial, whose ALT is a +20 mV head on the REL equation, so the REL floor and ceiling raises on RTX 50 cards are unchanged.
  Every image of the corpus passes as stored. An image saved earlier with REL above ALT keeps accepting edits that
  leave that rail's REL and ALT alone. Also in the docs and field evidence: the Ada 12 V input current and
  NVVDD output power threshold ranges, now 16-66 A rated (maxima up to 70 A) on the 18 stock images with those rows
  and 122-700 W rated (maxima up to 900 W). Offline check only; nothing ran on a card.

## 0.1.41

- **Ada: cable sense entries may name the profile their level selects (RTX 4090 95.02.18.C0.75): power limit
  may unlock (untested).** On a Gigabyte RTX 4090 ROM (95.02.18.C0.75, reported in [issue
  #30](https://github.com/Panchovix/nvidia-vbios-vix-editor/issues/30)) the power fields were hidden with
  "unrecognized Ada override profile selection entry", so the board power limit could not be edited. Its sense
  entries (selection row 0) hold their code in byte 1, where the reviewed MSI RTX 4090 Suprim (95.02.3C.40.EA) holds
  0xff. Static analysis of GSP-RM 615.78.08 and 620.70.06 shows that this byte names a direct profile, which the
  firmware applies as soon as that code is read and before the threshold row (0xff: none). The editor now accepts a
  direct profile equal to the entry's code when, at each code that votes, the threshold row selects that same
  profile: the firmware then applies one profile per level, as with 0xff, so the selection, fields and bounds are the
  same, and an edit keeps the byte. A direct profile the threshold row does not select still hides the power fields,
  since the firmware would apply two profiles there and the editor does not model that. Tested on synthetic images
  only: the ROM was not shared, so whether its threshold row selects the same profiles is not known, and nothing was
  loaded on a card. Load the copy with the loader, never flash it; removing the override brings the stock behaviour
  back.

## 0.1.40

- **RTX 5050 Laptop GPU and single-rail RTX 50 laptops with the same rows: the NVVDD output current limit can be
  edited (untested).** On the RTX 5050 Laptop GPU ROM (98.07.29.00.7E, reported in [issue
  #26](https://github.com/Panchovix/nvidia-vbios-vix-editor/issues/26)) **NVVDD output OCP current ceiling** and
  **MSVDD output OCP current ceiling** were read-only with no value. Its power table has the laptop layout of the RTX
  5080 and 5090 Laptop GPU, but its rail table has one row (NVVDD), as on the RTX 5060 Ti and 5070, and its output
  current rows are those of these single-rail desktop ROMs. The single-rail rule took those rows only on the desktops'
  device IDs, and the laptop rule only the two-rail rows of the RTX 5080 and 5090 Laptop GPU. The NVVDD row (row 13)
  is now recognized when a ROM has the laptop power table layout and the one-row rail table, the row equals the
  single-rail NVVDD row byte for byte (its limits excluded) and it reads the reviewed NVVDD output channel and power
  device, whatever the device ID. **NVVDD output OCP current ceiling** and **NVVDD output OCP current limit, rated
  (experimental)** can then be edited: 180 A rated and 180 A ceiling on this ROM. Row 14 holds no MSVDD limit there
  (5001 A on the same channel), so the MSVDD row stays read-only with the single-rail reason, as on the single-rail
  desktops. An edit writes only the rated value and the ceiling of row 13 and repairs the power table's hash, the
  directory digest and the image checksums. Tested statically only: the ROM's rows and channel chain were compared
  with the reviewed ones, and edits were checked to change only those bytes and to revert byte for byte. Nothing was
  loaded on a laptop and there is no runtime reading of this GPU, so whether the driver enforces a raised limit is not
  known. The laptop's VRM was sized for the stock current, and a higher current limit alone may not raise the power:
  on RTX 50 laptops Dynamic Boost requests the running limit, so raise **Boot default board power**, **Notebook base
  TGP** and **Board power ceiling** together, as on one RTX 5090 Laptop GPU (0.1.35). On that laptop the NVVDD output
  drew about 120 A of the same 180 A at about 175 W, so with this ROM's 75 W ceiling the stock current limit is
  unlikely to be what holds the power (inferred). Load the copy with the loader, never flash it; removing the
  override brings the stock behaviour back. For API users: the two NVVDD fields carry `structural-row-comparison`
  evidence (format `GB20x notebook single-rail row13 type7; monitor 26`, `runtime_get` and `set_tested` false).

- **Docs: RTX 50 laptop fields are described by layout; the README says the switch was tested on one Turing laptop
  only.** The 0.1.39 texts named only the RTX 5080 and 5090 Laptop GPU for what applies to every RTX 50 laptop ROM
  with that layout (the runtime power limit switch, the laptop power fields and **Notebook base TGP**; the output
  current limits also need the reviewed rows) and counted 2 GB20x laptop ROMs. The README, the window guide, the field
  docs and the field evidence now name the layout (among the reviewed ROMs the RTX 5050, 5080 and 5090 Laptop GPU)
  and count 3, the README lists GB207 among the recognized GB20x chips, and the README's paragraph on the switch says
  that other Turing laptops and the Ampere and RTX 50 laptops are not tested yet. The hardware results stay with the
  laptops they came from (one RTX 5090 Laptop GPU for the laptop power fields, one RTX 2070 Laptop GPU for the
  switch). The field docs also describe the RTX 5050 Laptop GPU ROM: TGP 5/50/75 W, base TGP 60 W, the single-rail
  table with a 900..1025 mV REL clamp (also in the REL floor evidence), and no GR rail gating switch, since the ROM
  enables none. The window guide notes that its maximum operating temperature can only be lowered, as the editor has
  no reviewed stock value for it. What the editor offers changes only as in the entry above.

## 0.1.39

- **Turing, Ampere and RTX 50 laptops: runtime power limit switch (experimental, opt-in; worked on one RTX 2070 Laptop
  GPU).** Laptop ROMs leave the TGP entry of the power table header empty (`0xff`), and current NVIDIA drivers then
  refuse runtime power limit changes: `nvidia-smi -pl` and MSI Afterburner's power limit slider. Drivers up to R525
  (Linux 525.89.02, Windows 528.49) took the TGP row by themselves on Turing and Ampere laptops; later drivers do not
  (static analysis of GSP-RM 615.78.08 and the Windows 621.01 driver). **Expose runtime power limit (nvidia-smi -pl,
  Afterburner)**, under **Show advanced XOC-style fields** (after **Notebook base TGP** on RTX 50 laptops), writes the
  TGP row into that entry, as R525 did, and off writes `0xff` back, so a copy switched back equals the stock ROM byte
  for byte. It is offered where the power table has the laptop layout: on Turing and Ampere laptop ROMs, Max-Q laptops
  included, and on the RTX 5080 and 5090 Laptop GPU ROMs, where no driver did this before. Ada laptops are left out for
  now, because no override has loaded on an Ada laptop yet. The switch itself changes no limit: the driver then takes
  limits between **Board power floor** and **Board power ceiling**. For a higher limit from the slider or
  `nvidia-smi -pl`, raise only the ceiling: **Boot default board power**, which is 100 % on Afterburner's slider, can
  stay at stock, and the slider then goes up to the ceiling (113 % for a 130 W ceiling over 115 W). A limit set this way
  lasts until the driver loads again, so set it after every boot (Afterburner can apply it at startup). Dynamic Boost
  and the laptop's configurable TGP (the NVIDIA platform framework, NVPCF, on Windows; nvidia-powerd on Linux, Ampere
  and newer) keep their own request on the same row and the lowest request wins: while they hold one, a higher value has
  no effect and their next update drops yours. Their request is capped by the ceiling too, so a raised ceiling may let
  them go above the stock limit by themselves. On battery the lower battery limits still apply. One user tested it on an
  RTX 2070 Laptop GPU (90.06.58.40.08) on Windows with driver 621.01 and the Windows loader, with the power limits at
  stock (1 W floor, 115 W default and ceiling): before the edit `nvidia-smi -pl` and the Afterburner slider were
  refused; with the switch on the slider became available, and at 64 % (73.6 W) the GPU drew 71.1 W under load in a
  game. Which of the two Turing loader files was loaded, whether Dynamic Boost was active and the behaviour on battery
  were not reported, and nothing above the stock 115 W was tried. Other Turing laptops and the Ampere and RTX 50 laptops
  are not tested, and on Turing the signed hash list over the power table is left stale, as for the other Turing power
  edits. The laptop's VRM, cooling and power adapter were sized for the stock limit, and a raised ceiling asks more of
  them; a battery that drains while plugged in under full CPU and GPU load means the adapter falls short. Load the copy
  with the loader, never flash it; removing the override brings the stock behaviour back. For API users:
  `runtime_power_limit_unlock` (flag, opt-in), copied by an import only with opt-in fields included and only between
  ROMs that both have it.

- **Blackwell REL floor: tested on RTX PRO 6000 Max-Q and RTX PRO 4000 SFF boards (hardware result).** The **NVVDD REL
  floor** and **MSVDD REL floor** of 0.1.38 were not tested on hardware. On Linux with driver 615.78.08 and the Linux
  loader, three RTX PRO 6000 Blackwell Max-Q boards and one RTX PRO 4000 Blackwell SFF loaded copies with both floors at
  1100 mV and both REL ceilings at 1125 mV. On the Max-Q boards the driver evaluated REL at 1100 mV on NVVDD and MSVDD
  with no runtime request, where their chip value, from the fused leakage, is about 990 to 1000 mV (the REL they
  reported with only the ceiling raised). On the RTX PRO 4000 SFF a runtime request of 1000 mV on both rails (an offset
  of -100 mV written by a tuning tool) evaluated 1000 mV, so a runtime offset still adds to the floor where the driver
  applies it, and a negative one takes REL below the floor. The field reasons and the docs now say so; what the fields
  accept is unchanged. GeForce RTX 50 cards, the RTX PRO 6000 Workstation and the laptops are not tested. More voltage
  means more heat, power and wear; load the copy with the loader, never flash it, and removing the override brings the
  card back.

- **Ada, Ampere and Turing: the flat NVVDD voltage's reason notes the 1250 mV VFE range (1243.75 mV on Turing), as on
  Blackwell.** The reason of **NVVDD flat voltage (REL = ALT = OV)** (in `nvbios fields` and the API) now says on these
  families too that above 1250 mV on Ada and Ampere, and above 1243.75 mV on Turing, the value is beyond the range of
  the VFE voltage variable (450 to 1250 mV, on Turing 450 to 1243.75 mV, on every image of these families examined), so
  the VF curve might not use it. The 0.1.38 docs already said so; the field and its range are unchanged.

## 0.1.38

- **Blackwell: REL floor, and one NVVDD voltage for REL = ALT = OV once they follow OV (experimental).** REL is the
  chip's own value, from its fused leakage, kept between the floor and the ceiling of its equation. **NVVDD REL
  floor** and **MSVDD REL floor** now set that floor, next to the ceiling: a floor above the chip value becomes the
  REL. On RTX PRO 6000 Max-Q boards with a raised ceiling the driver reported REL at about 990 to 1000 mV, the chip
  value, and a floor can set it higher. This matters on RTX 50 cards where the driver ignores runtime rail offsets; a
  tuning tool's offset still adds where the driver applies it. The floor goes from 850 mV up to the ceiling and at
  most OV (1200 mV), so REL and VMIN stay at or below OV; raise both in one edit to go past the stored ceiling. With
  **Show advanced XOC-style fields**, **NVVDD flat voltage (REL = ALT = OV)** sets one value for REL, ALT and OV, from
  850 to 1560 mV (stock 1200 mV), on a copy saved with **NVVDD REL and ALT follow OV** on (save the switch, open the
  copy, then set the value) and on the ASUS XOC and MSI Lightning ROMs. On the RTX 5090, 5070 and 5060 Ti it changes
  the OV equation itself. On the RTX PRO 6000, RTX PRO 4000 SFF, laptops, RTX 5080 and 5070 Ti, where other tables or
  the MSVDD rail may use that equation, the first save writes a copy of it into the first unused VFE slot and points
  REL, ALT and OV at the copy, so the others keep 1200 mV; on those boards save it and the GPC curve offset in
  separate copies. While REL and ALT follow OV, the NVVDD REL, ALT and OV ceilings and the NVVDD REL floor are
  read-only. Above 1250 mV the value is beyond the range of the VFE voltage variable, so the VF curve might not use
  it, and the board power and current limits still apply. Neither field is tested on hardware (the follow-OV switch
  alone loaded fine on an RTX 5090). More voltage means more heat, power and wear; removing the override brings the
  card back. For API users: `nvvdd_rel_equation_min_mv` and `msvdd_rel_equation_min_mv` form the ordering groups
  `nvvdd-rel-clamp` and `msvdd-rel-clamp` with their ceilings, and `nvvdd_rel_alt_follow_ov_mv` reports in
  `vfe_copy_slot` the slot a copy takes.

- **Ada, Ampere and Turing: one NVVDD voltage once REL and ALT follow OV; Ada REL floor; Ampere fixed REL/ALT
  (experimental).** On Ada, **NVVDD REL floor** sets the floor of a REL that follows the temperature (the RTX 4090
  95.02.18, 4080 SUPER, 4070, 4070 SUPER and most RTX Ada workstation ROMs): REL falls as the GPU heats up, from
  about 97 °C with the stock clamps, so the floor is the REL of a hot GPU; it goes from 830 mV up to the ceiling and
  at most OV (1200 mV), and a fixed REL keeps its own field. **NVVDD REL and ALT follow OV**, under **Show advanced
  XOC-style fields**, now also works on Ampere (the NVVDD rail; the MSVDD rail of the GA102 boards keeps its own) and
  Turing, and on a copy saved with it on, **NVVDD flat voltage (REL = ALT = OV)** sets one value for REL, ALT and OV
  on all three: 830 to 1560 mV on Ada (OV 1200 mV), 900 to 1430 mV on Ampere (OV 1100 mV) and 950 to 1462 mV on
  Turing (OV 1125 mV; there also at least the boot voltage and VMIN plus its chained terms). On every Ada, Ampere and
  Turing ROM nothing else uses the OV equation, so the value goes into it, in every copy of the tables. As on
  Blackwell, above 1250 mV (1243.75 mV on Turing) the value is beyond the range of the VFE voltage variable, so the
  VF curve might not use it. On Ada a flat voltage or floor below VMIN plus its chained terms needs VMIN lowered in
  the same edit. Where each
  chip sets its own VMIN, the flat voltage and the Ada REL floor stay at or above the highest VMIN it can reach until
  **NVVDD minimum voltage (VMIN)** is fixed: 979 mV on the RTX 4060 Ti, 989 mV on the RTX 4060 and 1140.5 mV on the
  RTX 5000 Ada, whose floor then only goes up, so REL does not end below VMIN. On the RTX 4090 95.02.3C ROMs the
  flat voltage stays at or above 926 mV, the stock VMIN that their memory clock voltage floor keeps plus its chain.
  The Galax HOF XOC RTX 2080 Ti ROM
  already points REL and ALT at OV: there the switch reads on and the voltage can be set directly. One RTX 2080 ROM,
  whose image holding the rail table lacks the checksum padding, keeps the switch read-only. On Ampere, **NVVDD
  REL/ALT fixed voltage** and, on the two-rail GA102 boards, **MSVDD REL/ALT fixed voltage** (advanced) set the
  constant REL and ALT of each rail, as on Ada and Turing, up to OV: REL goes from its stored 900 to 1087.5 mV up to
  1100 mV, and an ALT already at 1100 mV (GeForce boards) stays there. While REL follows OV, the NVVDD fixed values
  are read-only on every family: the flat voltage sets them. None of it is tested on hardware; more voltage means
  more heat, power and wear, and removing the override brings the card back. For API users: the new keys
  `msvdd_rel_fixed_mv` and `msvdd_alt_fixed_mv` form the ordering group `msvdd-rel-alt`; on Turing
  `nvvdd_rel_alt_follow_ov_mv` joins `nvvdd-rel-alt` with `nvvdd_vmin_mv`, and the Turing clock programming 3.5, FLL
  1.0 and voltage policy 1x tables are read to rule out other users of the OV equation.

## 0.1.37

- **HP OEM RTX 3060 12 GB: zero RPM can't stop the fan (hardware result).** One user tested the 0.1.36 fan fields on
  this card (94.06.2F.00.ED) on Windows with driver 621.01. With **Fan zero RPM** on, and also with **Fan 1 minimum
  level**, **Fan 1 minimum speed** and the speed of point 1 of the curve at 0, the fan stayed at about 1200 RPM at 30
  °C, the same as with the stock ROM, which asks for 1000 RPM there. Raising point 1 of the curve to 2000 RPM and 45 %
  raised the idle speed to about 2000 RPM, so the fan settings reach the card and the floor of about 1200 RPM most
  likely comes from the fan itself. Nothing changed in the editor. Reported in [issue
  #22](https://github.com/Panchovix/nvidia-vbios-vix-editor/issues/22).

- **Fans: extra fan curves may sit below the fan minimums, so the RTX 3090 blower's minimums and channel count can be
  edited.** A stock RTX 3090 blower ROM (94.02.26.48.D6) runs both fans between 3000 and 5000 RPM and 60 and 100 %,
  and keeps its two extra fan curves, which start at 95 and 97 °C, at 1000/2203/3541 RPM and 30/55/80 %, starting
  below those minimums. The editor kept every fan minimum at or below the start of every curve, extra curves included,
  so on that ROM **Fan 1 minimum speed**, **Fan 2 minimum speed**, both minimum levels, the low points of the extra
  curves and **Fan channels** were read-only. Now only a fan's own curve (and the speed-table value where the ROM uses
  one) bounds its minimum, the points of an extra curve go from 0 up to the lowest fan maximum, and a stored fan
  channel needs only its maximums above the extra curves; the maximums still stay above every curve. When a curve
  blocks a raised minimum, the Fans card now names only the points of that fan's own curve. Static analysis of the
  driver's GSP firmware found no check of fan curve points against the fan limits, and the stock ROM shows that the
  driver accepts extra curves below the minimums, but the fan controller most likely never runs a fan below its
  minimum. One user reported that on that card the fan reads 42 % at idle and runs about 3333 RPM at a manual 30 %,
  which the driver turns into a 3000 RPM target (the minimum speed), so something holds it higher, possibly the 60 %
  minimum level or the fan itself. To try for about 2000 RPM, lower **Fan 1 minimum speed** and **Fan 2 minimum
  speed** to 2000 RPM, both minimum levels to 30 % and point 1 of both fan curves to 2000 RPM and 40 % in one edit
  (the levels are under **Show advanced XOC-style fields**). This may let the fan idle near 2000 RPM, but on an RTX
  5080 a lowered minimum did not lower the speed the fan ran at, and an HP OEM RTX 3060 12 GB fan stayed at about 1200
  RPM, so it may change nothing. None of this is tested on an RTX 3090. **Fan zero RPM** stays read-only there,
  because its fan entries mix the zero RPM bits. A slower fan lets the card run warmer, so watch the GPU and memory
  temperatures after the change. On other ROMs the first points of the extra curves can now go lower, and on an RTX
  3080 Ti and an RTX 4500 Ada a minimum can now rise to its own curve. Reported in [issue
  #24](https://github.com/Panchovix/nvidia-vbios-vix-editor/issues/24). For API users: the maximum of `fan_N_min_rpm`
  and `fan_N_min_pct` comes from the channel's own curve, `fan_extra_M_curve_1_rpm` and `fan_extra_M_curve_1_pct` have
  0 as their minimum, and `fan_channels` checks only the maximums of a stored channel against the extra curves.
  Importing fans now copies extra curves that start below the target's minimums, and the fan limit and curve fields of
  GB20x, Ada and Ampere ROMs carry two new static-firmware-analysis evidence entries.

## 0.1.36

- **HP OEM RTX 3060 12 GB: the fan fields can be edited.** On this ROM (94.06.2F.00.ED) the Fans card said that some
  fields were not shown, because the ROM keeps a copy of the fan 1 settings in the entry of a second fan channel that it
  disables. In the driver's GSP firmware no fan control entry names that copy, so it is most likely unused, and the
  editor now writes both entries the same way, so they always hold the same values. The fan limits and curves, the PWM
  frequency and **Fan zero RPM** with its thresholds can now be edited there, and **Fan channels** stays read-only.
  **Fan 1 minimum level** and **Fan 1 maximum level**, the curve point levels, **Fan zero RPM** and its thresholds are
  under **Show advanced XOC-style fields**. The stored minimum is 15 % (1000 RPM). Lowering **Fan 1 minimum level** and
  **Fan 1 minimum speed** together with point 1 of the curve may let the fan go lower, but on an RTX 5080 a lowered
  minimum did not lower the speed the fan ran at, so this may change nothing. **Fan zero RPM** can be turned on with the
  fan-stop temperatures the ROM already stores (50 and 60 °C on fan 1), so the fan most likely stops below 50 °C at idle
  and starts again above 60 °C. Neither change is tested on an RTX 30 card. A slower or stopped fan lets the card run
  warmer, so watch the GPU and memory temperatures after the change. Reported in [issue
  #22](https://github.com/Panchovix/nvidia-vbios-vix-editor/issues/22). For API users: the fields that write the fan 1
  entry carry `fan_policy_copies`, and their offsets include the copy.

- **RTX 3050 6 GB and 8 GB (GA107): the fan fields can be edited.** On these ROMs (94.07.91.00.59 and 94.07.68.00.5D)
  the Fans card said that some fields were not shown, because the ROM keeps an extra fan curve in the entry of a second
  fan channel that it disables, while other RTX 30 ROMs keep theirs after the fan entries. In the driver's GSP firmware
  that entry is linked to the fan the same way as the other extra curves, so the editor now reads it as one: it shows as
  **Extra fan curve 1**, from 95 °C up. The fan limits and curves, the extra curve, the PWM frequency and **Fan zero
  RPM** can now be edited there, on the 8 GB also the zero RPM thresholds (the 6 GB stores its 52 and 55 °C in a form
  the editor does not offer, so they stay as they are), and **Fan channels** stays read-only. **Fan 1 minimum level**
  and **Fan 1 maximum level**, the curve point levels, **Fan zero RPM** and its thresholds are under **Show advanced
  XOC-style fields**. Both ROMs ship with zero RPM on, so the fan most likely stands still at idle: turning **Fan zero
  RPM** off should keep it turning, and turning it on again writes the stock values back. None of this is tested on an
  RTX 3050. A slower or stopped fan lets the card run warmer, so watch the GPU and memory temperatures after the change.
  For API users: on these ROMs `fan_extra_1` is fan policy entry 1 (`fan_policy: 1`).

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
