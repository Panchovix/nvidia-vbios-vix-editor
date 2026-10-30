# Turing (experimental)

English | [Español](turing_es.md)

Turing GPUs (TU102, TU104, TU106, TU116 and TU117: GeForce RTX 20 and GTX 16 series, TITAN RTX, Quadro RTX and the
T series) are recognized by the editor and by both loaders, **experimentally**. One RTX 2080 Ti (ROG Matrix BIOS)
has run edited images through the Windows loader (driver 617.70). An edit of 500 W board power plus 250 W per
connector loaded, and the card reached about 458 W under load: the power limiter no longer triggered, the voltage
limiters (Reliability Voltage, Max Operating Voltage) did. With the board power alone it stopped near 300 W,
because the per-connector rows were still at stock. An RTX 2070 with its power limit raised from 200 to 225 W
reached 225 W through the Windows loader. Nothing else below is tested on hardware. If you own a Turing card, the
tester guide at the end tells us what works.

## What the editor does

Every Turing field is marked experimental. Fields marked *advanced* appear after ticking **Show advanced
XOC-style fields**.

- **Board power**: `power_max_w` (ceiling), `power_default_w` (boot default) and `power_min_w` (floor).
- **Per-input power limits** (desktop and workstation images): `slot_power_max_w` / `slot_power_rated_w` for
  the PCIe slot (on one MSI GTX 1650 the slot row has the board power's class; the same fields edit it), and
  `connector_N_power_max_w` / `connector_N_power_rated_w` for each external 12 V connector
  sense channel (two on most RTX 20 boards, one on the GTX 1660, 1660 SUPER, 1660 Ti and 1650 SUPER, three on the
  Galax HOF XOC RTX 2080 Ti image, which leaves the third at 143/167 W while the others are at 2000 W).
- **Current thresholds** (advanced): `slot_current_threshold_*_ma` and `connector_N_current_threshold_*_ma`,
  the hardware overcurrent thresholds of the slot and of each connector channel.
- **NVVDD output current limit** (advanced): `nvvdd_output_ocp_max_ma` / `nvvdd_output_ocp_rated_ma`. It guards
  the GPU core VRM; its exact meaning on Turing is unknown.
- **Minimum voltage**: `nvvdd_vmin_mv`, the equation the rail table names as the VMIN limit. How it relates to
  the voltage the driver reports on Turing is unknown.
- **Fixed REL and ALT voltages** (advanced): `nvvdd_rel_fixed_mv` and `nvvdd_alt_fixed_mv`, the constant values
  of the REL and ALT voltage limits (1068.75 and 1093.75 mV on most boards), the same fields as on Ada. Each goes
  from its stored value up to OV (1125 mV, read-only), with REL at most ALT: raise ALT first, or both together.
  Both also stay at or above the boot voltage and VMIN plus what its chained equations add. The edit keeps the
  stored value in the equation, so the copy can be set back exactly. Whether the card then runs at a higher
  voltage is not known: the VF curve and the other limits still apply, and more voltage means more heat, power
  and wear. The Galax HOF XOC image points REL and ALT at the OV equation (REL = ALT = OV = 1125 mV); the editor
  shows those values read-only there, fixed fields included, and keeps VMIN and the flat voltage below editable.
  On a stock image, setting ALT and REL fixed to 1125 mV in one edit gives the same evaluated values (not tested
  on Turing hardware).
- **REL and ALT follow OV** (advanced): `nvvdd_rel_alt_follow_ov`, a switch that points REL and ALT at the OV
  equation, as the Galax HOF XOC image does (REL = ALT = OV). Save it on its own and keep the original image to
  go back. On the saved copy (and on the HOF XOC image) `nvvdd_rel_alt_follow_ov_mv` sets that one voltage, from
  950 to 1462 mV (OV is 1125 mV), at least the boot voltage and VMIN plus what its chained equations add. Above
  1243.75 mV the value is beyond the range of the VFE voltage variable, so the VF curve might not use it. As
  with the fixed values, whether the card then runs at a higher voltage is not known, and more voltage means
  more heat, power and wear.
- **Clock offset ranges**: `gpc_offset_max_mhz` / `gpc_offset_min_mhz` (core) and `memory_offset_max_mhz` /
  `memory_offset_min_mhz`, the ranges an overclocking tool may use. They do not change the clocks by themselves.
- **Factory clock offsets**: `factory_gpc_offset_mhz` (-500..+500 MHz) and `factory_memory_offset_mhz`
  (-5000..+5000 MHz, in the memory clock `nvidia-smi` and MSI Afterburner show, half of what nvidia-settings
  shows), the vendor overclock some boards store in the ROM (+135 MHz core and +400 MHz memory on the ROG Matrix
  RTX 2080 Ti). A ROM without one shows 0, and a value other than 0 turns one on, which was not tested. The rated
  boost clock (`factory_rated_boost_mhz`) is read-only.
- **Max operating temperature**: `max_operating_temp_c`, the limit `nvidia-smi` reports as the current temperature
  plus T.Limit (86-95 °C on desktop boards, 102 °C on laptop and Max-Q boards, where that relation was not
  checked). It goes from 40 °C up to 3 °C above the product's stock value, and is read-only on the two XOC images,
  which name no such limit.
- **Fans**: `fan_pwm_frequency_hz`, the speed (RPM) and level (%, advanced) limits of each fan and the points of
  its fan curve. There is no zero RPM switch: Turing fans stop through the curve. Seven images ship that way (the
  RTX 2060 SUPER stores 0 RPM at point 1 but keeps a 10 % level floor), and on the others but the MSI GTX 1650,
  whose curve is read-only, one edit sets it up: the minimum speed and level and point 1's speed and level at 0,
  point 2 at the fan's lowest running speed where it should start (no hysteresis; see `extended-fields.md`).
- **Advanced section** (its own collapsed section, not behind the advanced toggle): the utilization clock policy and
  the targets, jump thresholds and hysteresis of its GPC, DRAM and VID controllers, and Stock/Off switches for GR
  power gating and MSCG (idle power saving) on the products whose stock entries were reviewed (every Turing image
  examined). That the driver uses these tables is not proven; see `extended-fields.md`.
- **Read-only**: the OV voltage limit (1125 mV; the flat voltage sets it once REL and ALT follow OV), the
  REL/ALT/OV equation and selector fields, the boot voltage and the number of fan channels.
- Not every image has every field: Max-Q and laptop images have no slot or connector rows and no GPU-driven fan;
  the GTX 1630 and Gigabyte GTX 1650 images keep their slot and connector rows disabled (class 0), so they
  show no slot field, while the MSI GTX 1650 image has an active slot row (63 W rated, 74 W maximum); the ASUS
  RTX 2080 Ti XOC image disables the
  current thresholds and the NVVDD limit, so they have no field there; the Quadro RTX 8000 stores its clock
  ranges as 0..0 (read-only); one RTX 2080 image lacks the checksum padding of the image that holds the clock
  and rail tables, so its clock ranges and the follow-OV switch are read-only; the GTX 1650 SUPER fan tables
  disagree and give no fan field; the MSI GTX 1650 stores RPM limits of 0, so only its fan percent limits are
  editable.
- The tables are decoded by structure, checked on the 25 Turing images examined (desktop, laptop, Max-Q, Quadro,
  TITAN and two XOC images, TU102 to TU117). Edits are written to both banks of the image, and the checksum of
  each touched image is repaired. Bounds keep the stored order (minimum <= rated <= maximum, a fan curve inside
  its limits); they are not hardware-safe limits.
- Turing images carry a **signed list of digests that covers the edited tables**. The editor cannot update it.
  On the RTX 2080 Ti above the driver used the edited board and connector power anyway; for the other tables it
  is not known.
- Saving an edited Turing copy also saves two loader files next to it:
  - `<name>-loader.bin`: the first bank of the copy, unchanged. Load this one first.
  - `<name>-loader-e0end.bin`: the same bank, ending at its last data image. The small image after it, which
    holds the digest list, is dropped, and the last data image gets the last-image flags that Ampere and Ada
    images carry there. From the command line:
    `nvbios normalize edited.rom payload.bin --representation turing-e0-end-v1`.

  Both send 250-355 KB from the legacy image to the GSP firmware, well below the 512 KiB it reads (found by
  static analysis of `gsp_tu10x.bin` 615.78.08, not on hardware). The files are larger, 364-500 KB, because
  they keep the bank prefix before the legacy image (about 162 KiB on most boards), which is not sent. A file
  whose second bank is erased keeps flash bytes after its image chain and would send more than 512 KiB; the
  editor then saves only `<name>-loader-e0end.bin` and says why. On the RTX 2080 Ti above both files loaded
  through the Windows loader (checked by reading the running VBIOS back).

**An override that the driver rejects falls back to the stock VBIOS.** Nothing is written to the card. On
Linux the kernel log says `rejected override at ... using stock VBIOS` when the loader refuses it. When the
GSP firmware refuses the image itself it is expected to fall back silently (static analysis, not tested on
Turing), so check the power limits as well.

## Tester guide

Use a loader release whose README lists Turing; earlier releases refuse Turing GPUs. On Linux, re-run the
setup so the module is rebuilt with the Turing chips.

1. **Before anything**, save the stock power limits: `nvidia-smi -q -d POWER > before.txt`, and save your
   card's ROM (for example `nvflash --save original.rom`, or GPU-Z on Windows).
2. **Unmodified image**: export it without changes, `nvbios normalize original.rom original-loader.bin`, and
   load `original-loader.bin`. Reboot (Linux) or restart Windows. The card should
   work as before, and on Linux `journalctl -k -b | grep vbios_override` should show
   `selected: ... staged for GSP`. This shows that the loader takes the file and the card still starts with
   it, not that GSP uses it: the unmodified file holds the same bytes as the card's own VBIOS, so on Windows
   **Verify** reports a match either way. On Windows, also load the unmodified e0-end file
   (`nvbios normalize original.rom original-e0end.bin --representation turing-e0-end-v1`), restart Windows
   and click **Verify**: that file differs from the card's own VBIOS (two flag bytes, no type-0x70 image), so
   `override-active` means the driver runs it and `override-not-active` means it does not.
3. **Power-limit edit**, the first real test: in the editor, change one power value by a visible amount
   (lowering the floor, `power_min_w`, is the least risky; for example 125 W to 100 W), save the copy, load
   `<name>-loader.bin` and reboot. Run `nvidia-smi -q -d POWER`: does Min (or Max, or Default) Power Limit
   show the new value?
4. **If it does not change**, load `<name>-loader-e0end.bin` (same edit) instead, reboot and check again.
5. **Raising the board power** above the stock limit takes more than the board power fields: each input has its
   own limit, and with stock values their sum is close to the stock maximum board power (on the RTX 2080 Ti above,
   steps 1 and 2 took it from about 300 W to 458 W). One step at a time, testing under load after each:
   1. `power_max_w` and `power_default_w` to the target, and both `connector_N_power_rated_w` and
      `connector_N_power_max_w` to about the target divided by the number of connectors (for example 500 W and
      250 W on a two-connector RTX 2080 Ti).
   2. On a card with connectors, keep the slot at its stock values (63 W rated and 74 W maximum on the RTX
      2080 Ti). On a card powered only by the slot, the slot row limits the whole board, so a higher board power
      alone may change nothing (on one MSI GTX 1650, 63 W of slot plus the 3.3 V rail held it near 66 W under a
      75 W and a 90 W board power): raise `slot_power_max_w` and `slot_power_rated_w` together, in the same edit
      (rated at most the ceiling). The slot channel measures only the 12 V pins, which the PCIe CEM rates at
      66 W (the 75 W slot figure includes the 3.3 V rail). A rated limit above 66 W permits a draw through the
      slot beyond the specification, through its edge contacts and the motherboard slot or riser; actual draw
      depends on the workload and other limits. Slot power edits are not tested on Turing hardware.
   3. If the card still stops at the same power: the advanced connector current thresholds
      (`connector_N_current_threshold_*_ma`), only where the stored value is below the new connector power
      divided by 12 V (250 W / 12 V is about 20.8 A). Never lower them; on the RTX 2080 Ti the stock 22.5 A
      rated and 33.75 A maximum already cover 250 W.
   4. Keep the NVVDD current limit at its stock value unless a load log shows the NVVDD current near it.

   These values can exceed the ratings of the connectors (150 W per 8-pin), of the cables and of the power
   supply; the card's own VRM and cooling still apply.
6. To go back, remove the override with the loader (Linux: **Remove override** or `nvbios system disable`;
   Windows: **Remove override**).

**If the card does not start** (no image, `nvidia-smi` fails): on Linux, choose your **normal** entry in the
boot menu, which loads no override, and remove the override from there (see
[If something goes wrong](https://github.com/Panchovix/nvidia-linux-vbios-vix-loader#if-something-goes-wrong));
on Windows, start in Safe Mode and click **Remove override** (see
[If the GPU does not start](https://github.com/Panchovix/nvidia-windows-vbios-vix-loader#if-the-gpu-does-not-start)).
Report that too.

**What to report** (an issue in the editor repository): the GPU model and PCI ID (Linux:
`lspci -nn | grep -i nvidia`; Windows: the loader's GPU list), the VBIOS version
(`nvidia-smi -q | grep -i "VBIOS Version"`), the driver version and the OS; which file you loaded at each step
and the edit; `nvidia-smi -q -d POWER,CLOCK,PERFORMANCE` before and after each step, taken **under load** (a
game or a benchmark at full load), whose `Clocks Event Reasons` (PerfCap) show what limits the card. On Windows,
a HWiNFO log under load with the per-input powers (PCIe slot, 8-pin #1 and #2), the GPU core (NVVDD) current
and the performance limit reasons helps most, as does the loader's **Verify** result. On Linux also the
`vbios_override` line of the kernel log.
