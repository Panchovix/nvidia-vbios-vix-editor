# Extended offline power, equation, output-OCP, input-current and clock-range fields

These additions inspect saved ROM bytes and edit immutable copies. The package is
self-contained and uses stdlib at runtime; it never calls NVAPI, NVML, a GPU, or a
driver. The CLI and GUI are built on it.

The existing seven Blackwell edits have user-confirmed hardware results. That
evidence does not validate new ALT/OV/VMIN/OCP, boot-default, input-current or
clock-range edits. The reviewed Ada image reports a **100 W** NVML maximum only through
its reviewed relocated runtime payload, which is pinned to that one source; any other edited Ada
copy deploys only through the experimental `ada-relocated-v2` representation. Its REL temperature
input cannot be equated with NVML GPU temperature. The Ada fields are described in
[Ada fields](#ada-fields); all of them are experimental except the power ceiling/floor and the REL
ceiling of the hardware-tested RTX 2000 Ada (95.07.47.00.19). The RTX 3090 reference
image is used only offline and must not be deployed (see [Ampere fields](#ampere-fields)).

## Capability and unit contract

Every field retains the version-1 `key`, `current`, `units`, `bounds`, `editable`
and evidence descriptors, and adds independent namespaces:

```json
{
  "key": "nvvdd_ov_equation_max_mv",
  "units": "mV",
  "value_semantics": "stored-equation-output-ceiling",
  "capability": {
    "vbios": {
      "writable": "verified",
      "persistence": "unknown",
      "effect": "offline encoded bytes only; firmware acceptance unknown"
    },
    "runtime": {
      "writable": "unknown",
      "persistence": "unknown",
      "applied": "unknown",
      "evaluated_value": null,
      "offset": {
        "units": "uV",
        "type": "int32",
        "signed": true,
        "current": null,
        "writable": "unknown"
      }
    }
  }
}
```

`verified` means the offline writer recognizes and verifies that field's exact
format. `unsupported` means this editor explicitly refuses the operation, such
as an absent selector or a preserved boot value. `unknown` means the required
field/variant/unit association is missing. `editable` remains an offline-only
compatibility boolean. Root aggregates `capabilities.vbios/runtime` on the outer
inspection envelope; the editor supplies `capability.vbios/runtime` per field.
Neither SET API availability nor a successful GET proves writability or
persistent firmware acceptance.

`unit_metadata` identifies the public unit, stored unit, encoding and signedness.
Equation ceilings expose mV and store exact float32 uV. Their unchanged lower
clamp is the lower edit bound; the upper bound is a conservative encoding bound,
with `hardware_safe_maximum=null`. Runtime offsets are separately typed signed
int32 uV and have no offline binding. Output-OCP ceilings use integer mA stored
as uint32, without converting them into signed voltage offsets or measured amps.
The minimum editable OCP maximum is its unchanged factory rated/default value.

## Stable field IDs and selector meaning

| IDs (`*` stands for the `nvvdd` or `msvdd` prefix) | Meaning | Offline support |
| --- | --- | --- |
| `*_rel_equation_max_mv` | VFE output clamp maximum addressed by REL selector | Reviewed Blackwell; Ada temperature-derated REL |
| `*_rel_equation_min_mv` | VFE output clamp minimum (REL floor) addressed by REL selector: REL is the equation's value (GB20x: the chip value; Ada: a temperature value) clamped to the floor and the ceiling | Experimental, GB20x and Ada (NVVDD, every chain, a temperature-derated REL); editable with the REL ceiling while REL does not select the OV equation; 850 mV (Ada 830 mV and at least the highest VMIN set per chip; or the stored floor) up to the ceiling and at most OV (1200 mV), ordering group `*-rel-clamp` with it |
| `*_alt_equation_max_mv` | VFE output clamp maximum addressed by ALT selector | Reviewed Blackwell when present; Ada temperature-derated ALT (experimental) |
| `*_ov_equation_max_mv` | VFE output clamp maximum addressed by OV selector | Reviewed Blackwell |
| `*_vmin_equation_max_mv` | VFE output clamp maximum addressed by the rail INFO VMIN slot (GB20x row+`0x21`, Ada/Ampere row byte 11); **not** the evaluated VMIN | Read-only |
| `*_vmin_mv` | Evaluated minimum voltage (VMIN): the equation at GB20x row+`0x13`, Ada/Ampere row byte 7, Turing row byte 9 | Experimental, constant (GB20x) or clamp-pinned (Ada/Ampere/Turing) equations, kept below the lowest REL value; on the RTX 4090 95.02.3C images through a copy of the shared equation; a tree root (GB20x, Ampere) or per-chip equation (Ada) that nothing else names takes a value in its clamp, `current` `null` while stock |
| `*_vmin_fixed` | 1 while `*_vmin_mv` pins the clamp of a VMIN tree root or per-chip equation, 0 for its stock clamp (VMIN set per chip) | Experimental, GB20x, Ada and Ampere where `*_vmin_mv` is a tree root or per-chip equation; only 1 -> 0, which writes the stock clamp back byte for byte |
| `nvvdd_rel_alt_follow_ov` | 1 when the NVVDD REL and ALT selectors (REL alone without ALT) point at the OV equation (XOC-style) | Experimental, opt-in, GB20x, Ada, Ampere and Turing; only 0 -> 1 |
| `nvvdd_rel_alt_follow_ov_mv` | One NVVDD value for REL = ALT = OV while they follow OV: the OV constant, or a copy of it in the first unused VFE slot where other tables or the MSVDD row use it | Experimental, opt-in, GB20x, Ada, Ampere and Turing (in place only on Ada, Ampere and Turing); on a copy saved with `nvvdd_rel_alt_follow_ov` 1 and on the vendor XOC images; 850-1560 mV (Ada 830-1560 mV and Ampere 900-1430 mV, both at least the highest VMIN set per chip; Turing 950-1462 mV and at least the boot voltage and the highest VMIN) |
| `nvvdd_rel_fixed_mv`, `nvvdd_alt_fixed_mv`, `msvdd_rel_fixed_mv`, `msvdd_alt_fixed_mv` | Value of a constant REL or ALT equation: its constant and clamp maximum | Experimental, Ada (NVVDD), Ampere (every rail, opt-in) and Turing (NVVDD, opt-in); from the clamp minimum up to the rail's OV value, REL <= ALT; on Turing also at least the boot voltage and the highest VMIN |
| `fan_zero_rpm` | Bits 1\|2 of byte `0x32` of every enabled fan policy entry: 1 both set, 0 bit 2 clear (inferred meaning: the fans may stand still at low temperature) | Experimental, opt-in, GB20x, Ada and Ampere (not Turing); 1 only where the entries store a fan-stop block the firmware accepts or a reviewed template supplies one (RTX PRO 6000 Max-Q, RTX 5000/6000 Ada, RTX A1000-A6000); read-only when the entries disagree, an entry sets bit 2 alone, or no block or template applies (RTX A2000) |
| `fan_N_zero_rpm_low_temp_c`, `fan_N_zero_rpm_high_temp_c`, `fan_extra_M_zero_rpm_*_temp_c` | The two temperatures at bytes 30..33 (1/32 °C) of a channel's or an extra curve's fan policy entry, read with the zero RPM bits (inferred meaning: idle fans stop below the lower and start above the upper) | Experimental, opt-in, GB20x, Ada and Ampere (not Turing); only where the entry stores a nonzero pair (the upper at least the lower) and byte 46 is not 0xff; editable where the entry's block passes the firmware validator, on Ada and Ampere where `fan_zero_rpm` is offered; an edit keeps lower > 0, lower < upper <= point 1 of the same curve and 110 °C; with zero RPM on, an edit may not leave the upper above point 1 (`ZERO_RPM_ABOVE_CURVE`) |
| `*_rel/alt/ov/vmin_selector_index` | Full stored selector index | Read-only |
| `*_boot_voltage_uv` | Stored boot voltage | Read-only, preserved |
| `*_output_ocp_max_ma` | Reviewed output-OCP policy maximum (client ceiling) | Reviewed Blackwell rows13/14; NVVDD row 13 on single-rail images; Turing NVVDD row 13 (class 10, experimental, opt-in); Ampere NVVDD row 13 (class 0, experimental, opt-in) |
| `*_output_ocp_rated_ma` | Reviewed output-OCP rated value, enforced from boot | Experimental, reviewed Blackwell rows13/14; NVVDD row 13 on single-rail images; Turing and Ampere NVVDD row 13 (opt-in) |
| `slot_power_rated_w`, `slot_power_max_w` | PCIe slot power policy: row 19 (SFF), row 18 (5060 Ti), Ada and Ampere row 5, Turing row 3 | Experimental, reviewed row shapes only |
| `connector_N_power_rated/max_w`, `connector_N_current_threshold_rated/max_ma` | Power policy and current hardware threshold of external 12 V connector sense channel N, numbered in power-row order; on Ada and GB20x the power policy of the auxiliary power connector input | Experimental: Ampere and Turing, current thresholds opt-in; Ada and GB20x (power only, opt-in), reviewed row shapes on the connector input channel |
| `slot_current_threshold_rated/max_ma`, `nvvdd_power_threshold_rated/max_w` | Hardware-threshold policies (slot 12 V current; Ada NVVDD output power) | Experimental, opt-in; slot current on Ada, Ampere and Turing, NVVDD power on Ada only |
| `board_fixed_rated_w` | Rated value of the fixed board policies 2/7 | Experimental, opt-in (hidden in the GUI by default) |
| `notebook_base_tgp_w` | Row 2 +73 of the GB20x notebook layout, the base TGP that Dynamic Boost adds its boost to (as one RTX 5090 Laptop GPU behaved) | Experimental, opt-in (hidden in the GUI by default), GB20x notebook layout only; hardware-tested on one RTX 5090 Laptop GPU, where it raised the running limit only together with `power_default_w` and `power_max_w`; an edited value stays between `power_default_w` and `power_max_w`, which it does not bound |
| `input_current_rated_ma`, `input_current_max_ma` | 12 V board input-current policy, row 9 (Ada: thresholds 0/1, rows 9/10) | Experimental, reviewed row shapes |
| `input_current_policy7_limit_ma` | Policy 7 limit linked to the 12 V input policy | Experimental, reviewed Blackwell row shape |
| `input_policy_9_max_raw` | Row 9 raw maximum; units unknown | Read-only, only when row 9 is unrecognized |
| `fan_channels` | Active fan channels across the five fan tables | Experimental, Blackwell, Ada and Ampere, up to the stored channels; read-only on Turing |
| `fan_pwm_frequency_hz` | PWM frequency of every active fan channel | Experimental, Blackwell, Ada, Ampere and Turing, 21-28 kHz |
| `fan_N_min/max_rpm`, `fan_N_min/max_pct` | Speed (RPM) and level (%) limits of active fan channel N, numbered from 1 | Experimental, Blackwell, Ada, Ampere and Turing; move alone only as far as the stored fan curves (a minimum as far as the channel's own curve: the extra curves may sit below it), past them together with the curve points; level limits opt-in |
| `fan_N_curve_K_temp_c/rpm/pct`, `fan_extra_M_curve_K_temp_c/rpm/pct` | Point K (1..3) of channel N's stored fan curve or of extra curve M: temperature (°C, 1/32 °C steps), speed (RPM), level (%) | Experimental, Blackwell, Ada, Ampere and Turing; points stay in order and inside the limits (an extra curve from 0 up to the lowest channel maximum, so it may sit below the minimums); levels opt-in |
| `power_default_w` | Rated TGP value used at boot | Experimental; Blackwell, Ada, Ampere, Turing |
| `max_operating_temp_c` | Maximum operating temperature: the three temperatures (1/32 °C) of one thermal policy entry (P+0x50; GB20x entry 0, Turing, Ampere and Ada the entry header byte 9 names), written together | Experimental, GB20x, Ada, Ampere and Turing; 40 °C up to the product's stock value + 3 °C (only lower on products without a reviewed stock value); read-only where that entry is disabled or not named (XOC-style images) and on Ampere and Ada laptops (a lower limit of the same kind); never imported |
| `gpc_offset_min/max_mhz`, `memory_offset_min_mhz` | Clock offset range in MHz (NVML scale) | Experimental, reviewed Blackwell and Ada; Ampere and Turing by analogy |
| `gpc_curve_offset_mhz` | Default offset of the GPC VF curve: a constant MHz equation linked as the next equation of the GPC root in the VFE table | Experimental, opt-in, GB20x, Ada and Ampere (not Turing); -500..+500 MHz; 0 restores the stock bytes |
| `factory_gpc_offset_mhz` | Factory GPC offset: entry A0 of the factory clock record (P+0x98), a flag and a signed kHz value, applied at boot as the GPC clock frequency delta while the flag is 1 | Experimental, GB20x, Ada, Ampere and Turing; -500..+500 MHz in whole MHz on every image with the reviewed record; a value other than 0 sets the flag; imported with the clock offsets |
| `factory_memory_offset_mhz` | Factory memory offset: entry A1 of the same record, applied as the memory clock frequency delta, in the memory clock `nvidia-smi` shows (half the transfer rate) | Experimental, GB20x, Ada, Ampere and Turing; -5000..+5000 MHz in whole MHz, with the rules of `factory_gpc_offset_mhz`; imported with the clock offsets |
| `factory_rated_boost_mhz` | Rated boost clock of the factory clock record (entry B1) | Read-only, GB20x, Ada, Ampere and Turing, where B1 is enabled |
| `memory_point_K_follows_offset` | Bit 4 of the flag byte of the K-th intermediate memory level (from the lowest) in the clock programming table: 1 when a memory offset was expected to move that level | Experimental, opt-in, GB20x, Ada and Ampere (not Turing); the levels with the bit stay the top ones; idle and top levels not offered; did not stop the drop on the one card tested (RTX 3050 Laptop GPU) |
| `xbar/sys/vid_min/max_table_mhz`, `dram_min_table_mhz` | Clock offset range in table MHz | Experimental, reviewed Blackwell and Ada; Ampere; Turing `dram_min_table_mhz` only (its XBAR/SYS/VID rows store no range) |
| `perf_cf_util_policy` | PERF_CF utilization policy (policy entry 0, bit 7): 1 on, 0 off | Experimental, GB20x, Ada, Ampere and Turing, Advanced section; see [Advanced section](#advanced-section-performance-controllers-and-idle-power) |
| `perf_cf_D_target_pct`, `perf_cf_D_jump_pct`, `perf_cf_D_hysteresis_down`, `perf_cf_D_hysteresis_up` (D = `gpc`, `dram`, `vid`) | Utilization target and jump threshold (whole %) and decrease/increase hysteresis counts of the GPC, DRAM and video utilization controllers | Experimental, GB20x, Ada, Ampere and Turing, Advanced section; only while `perf_cf_util_policy` is 1 (`depends_on`) |
| `lpwr_gr_power_gating`, `lpwr_mscg`, `lpwr_nvdec_gating`, `lpwr_nvenc_gating`, `lpwr_ofa_gating`, `lpwr_nvjpg_gating`, `lpwr_difr`, `lpwr_gr_rail_gating` | LPWR idle power feature switches: 1 Stock, 0 Off (bit 0 of the entries the image enables in stock) | Experimental, Advanced section; GR power gating and MSCG on every family, the video engines on GB20x, DIFR on GB20x and Ada, GR rail gating where the image enables it (in the corpus the RTX PRO 4000 SFF, RTX 5080 and 5090 Laptop GPU, GA102 RTX 3080/3090 and RTX A4500..A6000, A40); `lpwr_coverage: "enabled-entries"` on a product the editor has not reviewed ([which entries a switch covers](#lpwr-idle-power-switches-and-idle-times)) |
| `lpwr_difr_dfpr_idle_ms`, `lpwr_difr_sw_asr_idle_us`, `lpwr_difr_cg_idle_us`, `lpwr_gr_rail_gating_idle_us` | LPWR idle times (DIFR DFPR, SW-ASR and clock gating; GR rail gating) | Experimental, GB20x, Ada and Ampere, Advanced section; 0.5x..4x stock; only while their switch is Stock (`depends_on`) |

Each selector field uses one complete role name, for example
`msvdd_vmin_selector_index`. Original `nvvdd_rel_max_mv` and
`msvdd_rel_max_mv` remain editable API aliases, with
`alias_of="*_rel_equation_max_mv"` and `ui_visible=false`. GUI callers should
present the canonical field once and keep aliases in read-only details.

The Blackwell V30 rail entries are 65 bytes with a 5-byte header. Proven selector
locations are row+`0x0d` REL, +`0x0f` ALT, +`0x11` OV, +`0x13` evaluated VMIN and
+`0x21` the slot the driver's rail INFO lists as VMIN; all are
**u16**. Boot is u32 uV at +`0x19`. `0xffff` means absent. Matrix MSVDD selectors
263–266 and other consumer selectors up to270 are retained without u8 truncation.
Each present selector is bounded against object14 and the complete 25-byte VFE
entry. Output minima/maxima use the reviewed float32 prefix at equation+3/+7;
recognized voltage output unit2 and equation kinds1/7 for REL, or kind1 for ALT
and OV, gate writable bindings. The rail INFO VMIN slot (+`0x21`) is never
writable (`capability.vbios.writable` is `unsupported`). Unknown kinds or ownership
remain read-only.

A selector is not an evaluated voltage. A stored ceiling is not a runtime offset.
Consumer ALT equations currently have output bounds of20mV; that is a stored
expression output, not a claim that the evaluated VOP rail is20mV. Constant OV and
VMIN equations keep their coefficients: raising an equation maximum can leave
its evaluated result unchanged. For example, a constant1200mV expression stays
1200mV when its clamp maximum increases to1300mV. No VFE input is evaluated here.

Ada selectors and equation kinds are described in [Ada fields](#ada-fields), Ampere
ones in [Ampere fields](#ampere-fields); neither inherits a Blackwell mapping.

## Evaluated VMIN (`nvvdd_vmin_mv`, `msvdd_vmin_mv`)

The driver's evaluated VMIN does not come from the VMIN role selector above. That
selector (`*_vmin_equation_max_mv`) is the slot the driver's rail INFO lists as VMIN;
it is read-only and labelled as such:

- **GB20x.** The driver VMIN equals the equation selected at row+`0x13`: a constant
  800 mV on both RTX 5080 rails, min/max equation trees on the RTX PRO 4000 SFF
  (630 mV NVVDD, 655 mV MSVDD). The +`0x21` slot holds a 900 or 750 mV constant
  the driver does not report, and a third-party driver dump shows the VMIN_LOGIC
  perf limit carrying the +`0x13` equation index. Hardware test on an RTX 5080:
  with that NVVDD equation's minimum, maximum and value raised from 800 to 850 mV,
  the driver reported VMIN 850 mV and the GPU idled at 850 mV.
- **Ada.** The equation at row byte 7 sets VMIN. On the RTX 2000 Ada it is a float
  quadratic on a fused input whose clamp pins 560 mV, and the driver reported
  650 mV; with the clamp at 700 mV in both chains it reported 790 mV. The
  equations chained after it (next link, temperature terms) add to the clamped
  value: +90 mV on that board, and the offset may differ per board. A new value in
  the byte-11 equation (and the identical equation 1) did not change the driver VMIN.
- **Ampere** stores the same row byte 7, mostly as a clamp-pinned constant; it has
  no hardware result.

`*_vmin_mv` is offered, experimental, only on these shapes:

- GB20x: a constant voltage equation (type 1, unit 2, minimum = maximum = value,
  zero coefficients, no next link) in object 0x14 that no other equation references
  and no other u16 word of the rail rows selects (+`0x0d`..+`0x17`, +`0x1d`..+`0x23`
  and the trailing block +`0x29`..+`0x3f`, which holds voltage equations on the
  Max-Q, RTX PRO 4000 SFF, RTX 5060 Ti and notebook rows). The edit writes the same
  float to its minimum, maximum and value. Corpus: NVVDD of the RTX 5080, 5070 Ti,
  5070 and the RTX 5090 images (FE, ASUS, XOC, Lightning). The other rails hold
  min/max trees (see [VMIN set per chip](#vmin-set-per-chip-tree-roots-and-per-chip-equations-_vmin_fixed)),
  and the RTX 5080/5070 Ti MSVDD constant (800 mV) lies above the lowest MSVDD REL value
  (760.2 mV, see below), so it stays read-only.
- Ada and Ampere: a float voltage equation whose clamp minimum equals its maximum,
  which no other equation references and no other role selects. The edit writes the
  clamp minimum and maximum in every chain. Corpus: 9 of the 21 parseable Ada images
  (RTX 2000 Ada, RTX 4090 95.02.18, both 4080 images, 4080 SUPER, 4070, 4070 SUPER, RTX 4500 Ada
  and 4070 Ti SUPER, whose compare REL its own clamp bounds) and 21 of the 35
  Ampere images, both rails on nine two-rail GA102 images. The A40 stores
  668088.3125 uV, which an edit in whole uV could not write back, so it stays
  read-only. On the RTX 4090 95.02.3C images another equation links the VMIN
  equation as its next equation; the edit then goes through a copy, see
  [Shared VMIN equation on RTX 4090 95.02.3C](#shared-vmin-equation-on-rtx-4090-95023c).
- GB20x, Ada and Ampere: a tree root or per-chip equation whose VMIN each chip sets
  for itself, through the clamp of that equation; see
  [VMIN set per chip](#vmin-set-per-chip-tree-roots-and-per-chip-equations-_vmin_fixed).

The value goes from 450 mV (GB20x, and any tree root or per-chip equation) or 400 mV
(Ada, Ampere; no voltage device minimum is decoded) up to the lowest value the rail's
REL equation list can take,
less the most the equations chained after the VMIN equation can add, so the
evaluated VMIN never crosses REL. Each equation of a list is clamped to its own
bounds and its next link is added (the RTX 2000 Ada result above); a quadratic
whose slopes are float residue (below 1e-6; the corpus has at most 5e-9) counts
as its constant, other quadratics and the GB20x type 7 REL count as their clamp,
and min/max or compare equations span their children, their own clamp bounding a
child that nothing else bounds (the compare REL of the RTX 4060, 4060 Ti, 4050 Laptop
GPU and 4070 Ti SUPER, clamped to 1015..1090 mV over a chain with an unclamped slope).
A list with an unclamped slope that no clamp bounds, another kind or a cycle has no
bound and keeps the field read-only. On the
RTX 2000 Ada REL is at least 915 mV and the chain after the VMIN clamp adds 70 to
162 mV (the driver showed +90), so VMIN goes up to 753 mV; on the RTX 4080 REL is
1075 mV and the chain adds 146 to 261 mV, so up to 814 mV. On the RTX 5080 and 5070
Ti the MSVDD REL links a compare that can add -139.8 mV, so MSVDD REL can drop to
760.2 mV. The edit guard allows exactly the declared floats of that one equation,
and only through this canonical binding.

### VMIN set per chip: tree roots and per-chip equations (`*_vmin_fixed`)

On many images the evaluated VMIN equation has no single stored value. It is
computed for each chip from fused values (speedo, bin) and changes with the GPU
temperature:

- **GB20x min/max tree roots.** Row+`0x13` selects a min/max equation (type 2,
  output byte 2, no next link) whose output clamp is unclamped (-FLT_MAX, +FLT_MAX)
  over a tree of 106 to 202 equations: fixed floors, a table of values indexed by a
  fused bin chosen by temperature band, and temperature and speedo terms. Corpus: both
  rails of the RTX PRO 6000 Max-Q images (Max-Q, Q325W), the RTX PRO 4000 SFF images and
  the RTX 5080 Laptop GPU image, NVVDD of the RTX PRO 6000 Workstation and RTX 5060 Ti
  images, and MSVDD of every RTX 5090 image. Evaluated with each chip's fuses (saved
  captures, no live access), these trees give the VMIN the driver reported, rounded up to
  5 mV, on all seven tree rails measured: 690/715, 675/690 and 640/640 mV on three RTX
  PRO 6000 Max-Q, 630/655 mV on an RTX PRO 4000 SFF and 880 mV MSVDD on an RTX 5090. On
  the Max-Q the tree gives about 35 to 50 mV less NVVDD and 53 to 69 mV less MSVDD
  above 60 °C than below. A compare root (type 3) is read the same way; no GB20x image
  has one.
- **Ampere compare roots.** Row byte 7 of 13 GA104/GA106 images (desktop RTX 3050,
  3060, 3060 Ti and 3070, RTX A2000 and A4000, and laptop images) selects an unclamped
  compare equation (no next link) that picks one chain per fused bin, each a base value
  plus fuse and temperature terms.
- **Ada per-chip equations.** Row byte 7 of ten Ada images (RTX 5000 Ada, RTX 4000 Ada
  and 4000 Ada SFF, RTX 4060 Ti, 4060, RTX 4050, 4070 and 4080 Laptop GPU) selects the
  quadratic of the RTX 2000 Ada shape (a base value minus a step per fused bin), but its
  fused input spans several bins and its clamp is the quadratic's own range over that
  input (545 to 560 mV, 640 to 780 mV, 680 to 725 mV...). The equations chained after it
  add their per-chip and temperature terms. All but the RTX 4070 Laptop GPU take a
  value (see the gates below). On the RTX 2000 Ada and the other images whose input
  holds a single value, the clamp pins the stock value and the plain `*_vmin_mv` above
  applies.

On these rails `*_vmin_mv` is offered with `current: null` while stock (the GUI shows
"per chip"). A value pins the output clamp of that equation: minimum = maximum = the
value, in every chain, so VMIN no longer follows the chip or its temperature (on Ada the
base value no longer does; the chained terms still add theirs). Values go from 450 mV
up to the lowest REL value, less what the chained equations can add on Ada. A value
below the chip's own stock VMIN can make idle and light-load states unstable; a higher
one raises the idle voltage and power. That is the user's call. The driver rounds VMIN
up to a 5 mV step on GB20x (a typed 662 shows as 665).

`*_vmin_fixed` (a 0/1 switch, experimental) sits next to it: 1 while the clamp is
pinned, 0 = stock. Only 1 -> 0 is offered: it writes the stock clamp bytes back
(unclamped for a tree root, the quadratic's own range for an Ada per-chip equation), so
the copy matches the stock image at those bytes. The value and the switch write the
same bytes and are changed in separate edits (`SEPARATE_EDIT_REQUIRED`). At 0 the switch
is read-only: a value in `*_vmin_mv` sets it. Both descriptors carry `vmin_tree`
(`state` stock or pinned, `kind` min-max, compare or per-chip, `root` index,
`equations` in the tree, `stock_clamp_mv` or `null` when unclamped).

**Gates.** The equation must be in the reviewed shape above, and nothing else may name
it, because a pinned clamp would also change that other use:

- no VFE equation links it as a next equation, a min/max or compare child, or a
  compare criterion (output byte 23 bit 4 set: the u16 at bytes 11..12 names the
  equation whose value is compared; GSP-RM reads it for every entry size);
- no other equation selector of the rail rows holds its index: on GB20x the words at
  +`0x0d` to +`0x17`, +`0x1d` to +`0x23` and +`0x29` to +`0x3f` of both rows (the other
  words are not read), on Ada and Ampere every byte from byte 4 on;
- no table that names VFE equations does, read as a superset where the index bytes are
  not pinned down: the clock programming entries and sub-entries (C+`0x0c`), the FLL
  table (C+`0x10`: every GB20x entry names an equation at byte 7; Ada and Ampere at byte
  9 and the header margin), the voltage policy entries (P+`0x70`, split-rail delta
  equations in nvgpu) and on GB20x the table at P+`0x104` (object 0xa7, which GSP-RM copies
  raw to another firmware: bytes 5..8 name equations on every image; bytes 1..2 hold the
  same small values on images whose equations at those indices differ, 5 and 9 on the RTX
  5090, 5080 and PRO 6000 Workstation, and -58 on the RTX PRO 4000 SFF, so they are not
  read as indices, though no firmware code proves it either way). An absent table names
  nothing; a table at another layout keeps the field read-only. On four enabled images
  bytes 1..2 of a P+`0x104` entry equal the index of their own VMIN root: the RTX PRO 6000
  Workstation (6, in a disabled type 0 entry), the RTX 5080 Laptop GPU (6) and both RTX
  5060 Ti images (7); if those bytes were an index after all, a fixed VMIN would also
  reach that entry there.

Only the canonical bindings write the equation, and after the edit it must still be the
same shape (stock or a pinned whole-uV clamp). A pinned clamp on such an equation is read
as a value this edit set: an image that shipped one pinned would get a switch that
writes the unclamped bytes (or the quadratic's own range) instead of its own. No image
of the corpus ships a pinned min/max or compare root, nor a pinned quadratic whose input
spans several values.

**Evidence and what is not proven.** GSP-RM 615.78.08 reads the clamp of every equation
kind into the common equation fields before the per-kind switch (VFE parser 0x119dd48),
copies it unchecked (constructor 0x1bfa140) and exports it with every kind: the min/max
(0x16c4f7c), compare (0x16c4ea8), quadratic (0x16c5040) and polynomial (0x16c5104)
exports all call the common export 0x16c4de0, which writes the minimum and maximum for
the evaluator. The evaluator runs in the PMU,
whose code is not readable, so that it applies the clamp of a min/max or compare node is
inferred. NVIDIA ships finite clamps on quadratic, polynomial and compare equations (the
GPC curve roots, Ada compare REL) and none on a min/max equation. The per-chip match
above checks the tree decode (next links, criterion links, variable ranges), not any
output clamp. The only hardware result is the RTX 2000 Ada quadratic: its clamp moved the
driver VMIN. If the evaluator ignores a root's clamp, VMIN simply stays at the stock
per-chip value; removing the override brings the card back. Not hardware-tested on any
tree root or Ada per-chip equation. To check it on a card, read the driver's VMIN at
idle with the stock image and with the copy, at a similar temperature (the stock value
drops above 60 °C on GB20x): a copy that still shows the stock value means the clamp is
ignored.

**Left read-only, with their reason:** the RTX 6000 Ada (row byte 7 selects a MHz
equation that another equation uses), the RTX 4070 Laptop GPU (row byte 12 holds 16 on
every Ada image, the index of its VMIN equation here; its meaning is unknown), the RTX
4060 Laptop GPU (its clamp, 545 to 560 mV, is narrower than its own range, 530 to 560
mV, so the stock clamp could not be written back after a value) and the A40 (a pinned
668088.3125 uV, not a whole uV). Every Turing image already pins its VMIN equation with
its clamp (the plain `*_vmin_mv`); none has a tree root or per-chip equation.

**Import.** From a donor whose VMIN is fixed, the value is imported (pinning the
target). From a donor whose VMIN is set per chip, a fixed target gets `*_vmin_fixed` 0,
its own stock bytes, and `*_vmin_mv` is listed as `per_chip_in_donor`. A constant VMIN
and a tree root are other quantities (`different_meaning`), and so are a VMIN that a
plain clamp fixes and one set per chip, also on Ada where both are quadratics (an RTX
2000 Ada and an RTX 5000 Ada).

### Shared VMIN equation on RTX 4090 95.02.3C

The RTX 4090 95.02.3C images (95.02.3C.40.EA of an MSI RTX 4090 Suprim,
95.02.3C.80.0B and a Dell 95.02.3C.08.5B) keep the 95.02.18 VMIN equation: row
byte 7 selects equation 7, a float quadratic whose clamp pins 811 mV, followed by a
chain that adds 0 to 115 mV. What they add is equation 584, in the first unused slot of the 95.02.18 image: a
voltage constant of 15 mV (type 1, unit uV, minimum = maximum = constant, zero
slopes) whose next link is equation 7. No equation and no rail row byte names 584.
The clock programming entries (C+`0x0c`, VFE index byte 3 | byte 13 << 8) of the
memory clocks from 810 MHz up (810, 5001, 10251 and 10501 MHz) name it, so their
NVVDD floor is VMIN + 15 mV + the VMIN chain (826 to 941 mV with the stock VMIN). On
95.02.18 those entries name equation chains of their own; the 405 MHz entry keeps its
own on both. A new clamp on equation 7 alone would move that memory floor too.

GSP-RM 615.78.08 (`gsp_ga10x.bin`) reads the Ada equation table at 0x119dd48: the
equation count is u16 (1024 on these images), the loop reads every entry, sends
types 0 (unused), 4 and 5 straight to the next index without building an equation,
and builds a type-1 equation in any slot; there is no rule that used slots are
contiguous. The per-kind constructors and any later link check were not traced.

- **Edit.** A value other than the stock 811 mV copies the stock bytes of equation 7
  into the first unused slot (585) and points 584's u16 next link (bytes 2 and 24) at
  the copy, in every chain, then writes the clamp of equation 7 as above. 584 then
  evaluates the same tree as before (the copy is the stock equation with the same next
  chain), so the memory floor keeps its stock value, and only row byte 7 still names
  equation 7. 811 mV again points 584 back at 7 and writes the unused-slot pattern
  into 585: the stock file, byte for byte. Once an earlier edit has made the copy, the
  slot is the one 584 links, not the first unused one.
- **What changes on the card (inferred from the tables, not measured).** A lower VMIN
  shows only while the memory runs at its lowest clock (405 MHz, single-monitor
  idle): there the floor is the new VMIN plus its chain, and the 405 MHz entry's own
  requirement and the GPC clock still apply. From 810 MHz up the floor stays stock
  VMIN + 15 mV + chain, so a lower VMIN does not show there. A higher VMIN shows at
  every memory clock only above 826 mV (stock VMIN + 15 mV); up to that it too shows
  only at 405 MHz.
- **Risk.** No Ada card has run a VFE equation the editor adds (the GPC curve offset
  below adds one too and is also untested). The override might not load or the driver
  might fail to start; removing the override brings the card back. A VMIN below
  stock can also make idle or light-load states unstable.
- **Range.** As for the other Ada images: 400 mV up to the lowest REL value less what
  the chain adds, 400..935 mV on these images, and the stock value has to lie inside
  it so that it can be restored.
- **GPC curve offset.** `gpc_curve_offset_mhz` also takes the first unused slot, so a
  request that changes both is refused (`SEPARATE_EDIT_REQUIRED`). Separate edits
  work in either order and revert to the stock file in either order. With the offset
  set first, the copy goes to 586; removing the offset first then leaves 585 unused
  below the copy, a gap no stock image has and the equation parser skips.
- **Gates.** This exact shape only: equation 7 pinned and linked only by the next link
  of one equation; that equation a pinned voltage constant that no equation references
  and no rail row byte selects; no rail row byte other than byte 7 and no clock
  programming entry naming equation 7 or the slot; the memory clock entries naming the
  constant except one lower entry (the idle clock); the first unused slot holding the
  clean unused pattern (type 0, links 0xffff). On a copy, the constant has to link an
  equation that only it references and that equals equation 7 except the clamp, which
  pins a whole uV value. Anything else keeps the field read-only while equation 7 is
  shared. Across the Ada corpus only the three 95.02.3C images match. A copy whose clamp
  equals equation 7's is not a state an edit makes; there every value keeps the copy
  and its link, so a request for the current value changes nothing.
- **Guard.** Whatever the field registry, the constant and the slot of its copy change
  only at the bytes this canonical binding declares (the copy and the two link bytes,
  in every chain), the shape must still be recognized afterwards with the same
  constant, and the GPC curve guard exempts exactly those slot and link bytes.
- **Descriptor and manifest.** The field carries `vfe_clone` (`state` coupled or
  decoupled, `referrer`, `slot`, `stock_mv`, `constant_mv`, `memory_mhz`,
  `idle_memory_mhz`) and a `firmware-static-analysis` evidence entry. The copy and link
  bytes appear in the manifest `edits` with `stored_units: "raw bytes"`, and their
  `before` and `after` are hex strings. The `gpc_curve_offset_mhz` reason on these
  images says to change VMIN in a separate edit.

## REL floor (`nvvdd_rel_equation_min_mv`, `msvdd_rel_equation_min_mv`)

Every GB20x REL equation (row+`0x0d`) is a type 7 polynomial of the chip's fused leakage
(IDDQ), but the NVVDD one of the vendor XOC images (they select the OV constant), and the
evaluated REL is that value clamped to the equation's output minimum and maximum (+3 and
+7): 875..900 mV on the RTX PRO 6000 Max-Q, 850..850 mV on the RTX PRO 4000 SFF, 900..1080
mV on the RTX PRO 6000 Workstation, 900 to 1100..1120 mV on the GeForce images and
960..1025 mV on the notebooks. The REL ceiling
(`*_rel_equation_max_mv`) writes the maximum: with it at 1125 mV the driver reported REL 990
to 1000 mV on three RTX PRO 6000 Max-Q, the chip value. The floor writes the minimum (float32
uV at +3, nothing else): REL is then the higher of the chip value and the floor, up to the
ceiling, so a floor above the chip value is the REL. A tuning tool's runtime voltage offset
still adds on drivers that apply it; on RTX 50 cards, drivers that ignore runtime rail offsets
leave the VBIOS as the way to raise REL.

The floor is editable with its rail's REL ceiling while REL does not select the rail's OV
equation (on a copy whose REL follows OV it would write the OV constant, see below). It goes
from 850 mV, the lowest REL floor of any GB20x image (or the stored floor, if lower), up to the
stored ceiling and at most the rail's OV value, the clamp minimum of its OV equation (its
1200 mV constant on every GB20x image; or the stored floor, if higher), so REL, and VMIN below
it, stay at or below OV; a higher NVVDD voltage needs REL and ALT to follow OV (see below).
Floor and ceiling form one ordering group (`nvvdd-rel-clamp`, `msvdd-rel-clamp`): requested
together they are checked on the result, so both can be raised in one edit, and a floor above
the ceiling or above OV is refused. A higher floor raises the lowest REL value, which bounds
VMIN. An import treats it like the ceiling, and the two come together.
Experimental: the floor is not hardware-tested (the ceiling is); more voltage means more heat,
power and wear, and removing the override brings the card back.

**Ada.** `nvvdd_rel_equation_min_mv` writes the clamp minimum (+3) of the NVVDD REL equation
(row byte 4) in every chain, where REL is the temperature-derated shape the REL ceiling edits:
a float quadratic on the sensed temperature with no next equation. Its value falls 2.7 to 5.7
mV per °C; with the stock clamps (900..940 mV on the RTX 4000 SFF Ada up to 1060..1100 mV on
the RTX 4070) it stays above the maximum up to about 97 °C and reaches the minimum at about
105 to 110 °C. So the floor is the REL of a hot GPU, and a floor equal to the ceiling holds REL
there at every temperature. It goes from 830 mV, the lowest REL of any Ada image (the constant
REL of an RTX 5000 Ada image), up to the ceiling and at most OV (1200 mV on every Ada image),
with the ceiling in the `nvvdd-rel-clamp` group, as on GB20x. Where each chip sets its own
VMIN, no stored value stands for it, so the checks that keep VMIN below REL cannot hold it: the
floor then stays at or above the highest VMIN of the board (its range plus what its chained
terms add) until VMIN is fixed. On the RTX 5000 Ada that is 1140.5 mV, above its stored 1040 mV
floor, which there only goes up. A constant REL (the newer RTX 4090 image, the RTX 4080, the
RTX 4000 Ada and one RTX 5000 Ada image) takes its value through `nvvdd_rel_fixed_mv` instead,
which the floor's reason names, and a compare REL (RTX 4060 family, RTX 4070 Ti SUPER, laptops)
keeps both read-only. Not hardware-tested (on an RTX 2000 Ada a raised ceiling moved the
evaluated REL).

## REL and ALT follow OV (`nvvdd_rel_alt_follow_ov`, opt-in)

The ASUS RTX 5090 XOC images and the MSI RTX 5090 Lightning image reach
REL = ALT = OV = 1.2 V by pointing the NVVDD REL and ALT selectors (row+`0x0d` and
+`0x0f`) at the OV equation, a constant 1200 mV; their VFE equations and MSVDD row
equal the stock image's. The field writes the same two selectors: 1 points them at
OV, so the voltage limit no longer follows the leakage-dependent REL curve.

The rail table (P+`0x68`) lies in the legacy image, outside the signed data image's
object directory. The legacy image has its own v3 object directory (objects 0xfa and
0xbd first, SHA384 per object, directory digest at legacy+`0x209`): object 0x21 spans
exactly the rail table and the aggregate object 0x35 holds it too. Every hash and the
digest match on every GB20x image of the corpus. Inside the rail table the vendor
XOC and Lightning images differ from the stock image only at the NVVDD REL and ALT
selectors; they update the 0x21 and 0x35 hashes, the digest and the legacy checksum
with them, and also change other legacy objects (0xbd, 0x69, 0x2e, 0x85 and more on
the Lightning) that this field leaves alone. An edit there repairs
every legacy object it touches, the legacy digest and the legacy image checksum, and
the copy must reparse with a valid legacy directory. `inspect` reports that directory
under `integrity.legacy_directory`; it does not change `integrity.valid`. The
legacy image's vendor signature is not regenerated, as with the data image's.
Applied to the stock ASUS RTX 5090 image, the edit gives the rail table and object
0x21 hash of the XOC image byte for byte.

0 -> 1 is offered while REL, ALT (if present) and OV select distinct equations, OV is
a constant voltage equation and the legacy directory is valid: on 12 of the 15 GB20x
images of the corpus (the XOC and Lightning images read 1). The RTX PRO 6000
Workstation, RTX PRO 4000 SFF, Max-Q and notebook images have no ALT selector:
there only REL moves (REL = OV). At 1 the field is
read-only: the image keeps no record of the original REL and ALT selectors, so keep
the source image to go back. The field is edited alone among the voltage fields
(`SEPARATE_EDIT_REQUIRED`), because moving REL changes the equation the REL ceiling
binds. Confirmed on one RTX 5090: the edited copy loaded as an override without
problems. Other GB20x boards have not run it.

**Flat value (`nvvdd_rel_alt_follow_ov_mv`, opt-in).** It reads the OV constant (1200 mV
on every GB20x image) and, on a copy that stores the switch at 1 and on the vendor XOC
images, sets one value for REL = ALT = OV, from 850 to 1560 mV (130 % of the stock
constant). Save the switch first and open the copy: requested with the switch it is refused
with `SEPARATE_EDIT_REQUIRED`. On the RTX 5090, 5070 and 5060 Ti images only the NVVDD OV
selector uses that constant, and the value goes into its minimum, maximum and constant (+3,
+7, +11). On the RTX PRO 6000, RTX PRO 4000 SFF, notebook, RTX 5080 and 5070 Ti images the
clock programming table (with the FLL table, and the MSVDD row word +`0x15` on the two-rail
ones) may name the same equation, so the first edit writes a constant equation with the
value (type 1, the OV equation's variable and output bytes, no next link, zero slopes) into
the first unused VFE slot and points the NVVDD REL, ALT and OV selectors at it; the shared
equation keeps its bytes, and later values go into the copy. The descriptor's
`vfe_copy_slot` names that slot (`null` when the value goes in place). The GPC curve offset
takes the first unused slot too: whichever is saved first takes it and the other the next
one, and requesting both in one edit on such an image is refused with
`SEPARATE_EDIT_REQUIRED`. While REL (and ALT) select a constant OV equation, the NVVDD REL,
ALT and OV ceilings and the REL floor are read-only: they would change the clamp of that
shared constant. Above 1250 mV the value is beyond the GB20x VFE voltage variable range
(450 to 1250 mV), so the VF curve might not use it; board power and current limits still
apply, and more voltage means more heat, power and wear. Not hardware-tested.

**Ada.** The same field moves the u8 REL and ALT selectors (row bytes 4 and 5) of
the Ada rail row. That row also lies in the legacy image, which has no object
directory on Ada: the field writes both selectors in every chain and repairs each
legacy image checksum, so the legacy image must keep the reviewed checksum padding
like the other edited tables. Every parseable Ada image selects a constant 1200 mV
OV equation, so the copy reads REL = ALT = OV = 1200 mV; on the RTX 4080 that is
+125 mV over its fixed 1075 mV REL, a larger step than the +90 mV over the RTX 5090
REL ceiling. The step follows the stored REL, which the field's reason gives: +245 to
+285 mV over the temperature-derated REL of the RTX 2000 Ada, and +225 to +325 mV
over the compare REL (on fused speedo inputs) of the RTX 4080 Laptop image. 0 -> 1
is offered on every parseable Ada image; images without an ALT selector move REL
alone.
The parser reads the result (REL = OV, ALT absent or = OV, VMIN = OV - 1) as 1,
read-only; the REL equation is then the OV constant, whose input variable is not a
temperature, and the `ada-relocated-v2` loader payload still decodes the rail. The
evaluated VMIN may then go up to 1200 mV less what its chained equations add
(939 mV on the RTX 4080). Row byte 10 holds 2, the REL index, on every Ada image; its
meaning is unknown and this field leaves it. No Ada vendor image is known to do
this, and no Ada board has run it: not hardware-tested on Ada.

The flat value works on the Ada copy too, from 830 to 1560 mV, and where each chip sets
its own VMIN at least the highest VMIN of the board until VMIN is fixed (979 mV on the RTX
4060 Ti, 989 mV on the RTX 4060, 1140.5 mV on the RTX 5000 Ada), as for the floor. On
every parseable Ada image the OV constant is used by nothing else (no other rail row
selector or evaluated VMIN byte, VFE equation, clock programming, FLL or voltage policy
entry), so the value goes into its minimum, maximum and constant in every chain; no copy
is written on Ada, so an image whose OV equation something else names keeps the field
read-only. Row byte 20 holds 4 on every Ada image, whatever its OV index (the OV index on
the images without ALT); its meaning is unknown, it is not counted as a selector, and the
field leaves it. While REL follows OV the NVVDD REL and OV ceilings, `nvvdd_rel_max_mv`
and the REL floor are read-only, as on GB20x. Not hardware-tested on Ada.

**Ampere and Turing.** The switch moves the REL and ALT selectors (row bytes 4 and 5) of
the Ampere NVVDD row (the MSVDD row of the two-rail GA102 images keeps its own) and of the
Turing 1x row, in the legacy image of every chain. On these families the legacy image is
not among the tables whose padding every field needs, so the switch checks it itself: on
the RTX 2080 image whose legacy image lacks the padding it stays read-only. Every Ampere
image selects a constant 1100 mV OV equation on each rail, every Turing image a 1125 mV
one, and 0 -> 1 is offered on all of them but that RTX 2080 and the Galax HOF XOC image,
whose REL and ALT already select OV: it reads 1, read-only. The parser accepts REL = OV
(ALT absent or = OV, VMIN slot = OV - 1) on the Ampere NVVDD row only. The flat
value goes into the OV constant in every chain, as on Ada, from 900 to 1430 mV on Ampere
and from 950 to 1462 mV on Turing (the lowest REL of the family's images up to 130 % of
its OV); on Turing it also stays at or above the stored boot voltage and the highest
VMIN (its clamp plus what its chained equations add) and joins the `nvvdd-rel-alt`
ordering group, as the fixed REL and ALT values do. Nothing else uses the OV constant on
any image of either corpus: no other rail row selector (on Turing the boot voltage and
VMIN limit bytes included), evaluated VMIN byte or VFE equation, and no clock
programming, FLL or voltage policy entry. On Turing those tables are read at the nvgpu
layouts: clock programming 3.5 (C+`0x0c`: the VF and secondary VF sub-entries; bytes 3
and 4 hold PLL parameters there), FLL descriptor 1.0 (C+`0x10`: entry byte 9, and header
byte 6 only with a 7-byte header; a 6-byte one has no margin equation) and voltage policy
1x (P+`0x70`). Ampere row byte 10 holds 2 on the NVVDD row and 3 on the MSVDD row,
whatever equation that index holds; it is not counted as a selector. While REL follows
OV the NVVDD REL, ALT and OV ceilings, `nvvdd_rel_max_mv` and the NVVDD fixed values are
read-only with the follow reason. Not hardware-tested on Ampere or Turing.

## Fixed REL and ALT values (`nvvdd_rel_fixed_mv`, `nvvdd_alt_fixed_mv`)

On some Ada images REL or ALT is a constant equation: REL and ALT of the newer RTX 4090
image (1050 and 1070 mV) and of both RTX 4080 images (1075 and 1095 mV), REL of the RTX
4000 Ada (950 mV, no ALT), and ALT alone on the 4080 SUPER, 4070 Ti SUPER and 4060
(1100 mV). A ceiling edit cannot move a constant, so these fields set its value: the
edit writes the constant (byte 11) and the clamp maximum (byte 7) in every chain.
The clamp minimum (byte 3) is kept; it is the lowest value offered (the stored value
on every image of the corpus), so an edited copy can be set back byte for byte. The highest value is the OV value
(1200 mV). REL stays at most the lowest ALT value and ALT at least the highest REL
value (a compare REL counts with its clamp maximum), so raising REL past ALT needs
ALT in the same edit: both fields form one ordering group. Every voltage edit is
checked against the result: the requested voltage fields must lie in their new
ranges, and an edit that would leave another editable voltage field outside its new
range (and so read-only) is refused, for example lowering REL below a raised VMIN or
raising a temperature-derated REL ceiling past a fixed ALT; change both together.

A field is offered for a constant (type 1, unit 2, zero slopes, no link, no
reference from another equation) that holds its constant at its clamp maximum,
when no other role and not the evaluated VMIN select it and OV is a constant. On a
copy whose REL and ALT follow OV it is read-only, and it is saved apart from
`nvvdd_rel_alt_follow_ov`. Raising REL lets the GPU request a higher voltage on its
VF curve; the board power and thermal limits still apply, and the VMIN bound rises
with the lowest REL value. Row byte 10 (the REL index on every image) reads the same
equation, as it did when a REL ceiling (a temperature-derated REL) was raised on the
RTX 2000 Ada. Experimental: no board has run a fixed value. While the NVVDD REL follows
OV its fixed fields are read-only with the follow reason: the flat value sets that constant.

Ampere uses the same fields, opt-in, on every rail: `nvvdd_rel_fixed_mv` and
`nvvdd_alt_fixed_mv`, and on the two-rail GA102 images `msvdd_rel_fixed_mv` and
`msvdd_alt_fixed_mv`, each rail in its own ordering group (`nvvdd-rel-alt`,
`msvdd-rel-alt`), written in every chain. REL is a constant on every image (900 to
1087.5 mV) and ALT (1100 mV) on the desktop GeForce ones; OV is 1100 mV on every rail,
so REL goes up to 1100 mV and an ALT already at OV keeps its value (the flat follow-OV
value goes higher). An equation another rail's row also selects keeps the field
read-only. The VMIN rules are Ada's. Not hardware-tested on Ampere.

Turing uses the same fields, opt-in, on the REL and ALT constants its 1x rail row
selects (1068.75 and 1093.75 mV on most images, OV 1125 mV; see
[Turing fields](#turing-fields)): the same bytes are written in both banks, with the
same bounds. Turing adds its own rules: REL and ALT also stay at or above the stored
boot voltage and the highest evaluated VMIN (its clamp plus what its chained
equations can add), `nvvdd_vmin_mv` joins their ordering group (so VMIN can be raised
past the old REL together with REL), ALT needs a constant REL, and a REL or ALT
equation that is not a constant, or that another equation uses, keeps a read-only
field with the reason. Not hardware-tested on Turing.

## Output-OCP association and narrow gate

Saved GET evidence preserves policy indices in134/134 records. All seven
Blackwell sources independently show rows13/14 of ROM type7, reported as RM
type 18 and API type 19, discriminator1, unique monitor class6 and output rail IDs
1(NVVDD) /16(MSVDD). Their saved GET limit unit is 1, which the third-party notes
under [Provenance](#provenance) identify as mA.
Rows5/6 also have type7 but fail the output gate; type alone is insufficient.

The offline implementation requires recognized power headers40/38-or-3d/66/20,
unique object13 ownership and a reviewed PCI identity. It compares immutable
102-byte row shapes, excluding range bytes13:25, against four reviewed templates.
This validates discriminator, monitor index and remaining identity/flag bytes
without pinning factory limits or a complete ROM hash. Shapes were independently
checked against all seven original corpus ROMs and their saved monitor records.
Unknown shapes or devices produce read-only descriptors with unknown units in
`raw_bounds`, and never become writable merely because their row index/type fits.
The only exception is the NVVDD row 13 of the listed single-rail images: a fifth
template plus the power channel/device chain described under
[Single-rail images](#single-rail-images-rtx-pro-6000-workstation-rtx-5060-ti-rtx-5070).

The SFF source exposes ceilings90000mA and60000mA. Other reviewed sources have
maximum5001000mA, with differing rated/default values. These are stored policy
bounds, not hardware-safe current ratings or measured current.

The OCP enforced from boot is the **rated** value, not the maximum. In the saved GET,
CONTROL current equals the rated value of rows 13/14 on all seven sources, for
example 480000/180000 mA on the 5090. A third-party run that lowered those values to
100 A under load clamped GPC/XBAR. `*_output_ocp_max_ma` (row+21) therefore only
widens what a runtime client may request. On six of the seven sources it is already
5001000 mA. The experimental `*_output_ocp_rated_ma` fields write row+17. Each
rail's rated and maximum fields form one ordering group
(`nvvdd-output-ocp`, `msvdd-output-ocp`). No reviewed profile carries entries for
policies 13/14, and the rated fields are read-only when a profile table cannot be
decoded. XOC and 2500 W vendor images store rated values of 2000000/1000000 mA.
Lowering only the NVVDD rated value may act as a boot-persistent cap on core current;
whether XBAR or memory clocks are affected is unknown, and nothing here is
hardware-tested.

`rail_identity` separates namespaces. A reviewed MSVDD OCP example is:

```json
{
  "key": "msvdd_output_ocp_max_ma",
  "current": 60000,
  "units": "mA",
  "factory_rated_ma": 60000,
  "rail_identity": {
    "logical_rail_id": "MSVDD",
    "vbios_row_index": 1,
    "vbios_policy_index": 14,
    "api_rail_index": 1,
    "power_monitor_rail_id": 16,
    "api_index_scope": "saved Linux GET mask bits; no live GPU association"
  },
  "policy_types": {"vbios": 7, "rm": 18, "api": 19},
  "monitor": {"index": 12, "class": 6, "rail_id": 16}
}
```

The API rail index, monitor index, monitor rail ID and VBIOS policy index are
independent integers. No runtime index is derived from a logical label for an
unreviewed layout. Row 9 is ROM type11/RM30/API25 in the reviewed capture, with a
class8 union. It is **not output OCP**: its reviewed shape is the separate 12 V
input-current policy described below, and unrecognized shapes keep unknown units.
Generic `current_limit_a` and `ocp_limit_a` placeholders stay read-only/unknown;
the per-rail output and input-current fields do not silently assign them a mapping. Ada shows its
NVVDD output-current row read-only (see [Ada fields](#ada-fields)), without implying absence of
hardware protection.

## Offline board power floor

`power_min_w` is the encoded board/TGP minimum in W, stored as uint32 mW.
It accepts exact 1 mW increments from **1 W** through the TGP rated default,
which stays unchanged unless `power_default_w` is requested too. The writer
enforces `minimum <= default <= maximum`;
the existing `power_max_w` lower bound continues to protect every rated/default
value in its coordinated policy group. These are encoding and preservation
bounds, not a promise of hardware acceptance or a measured runtime minimum.
Both controls display the ROM's rated default in the GUI.

On the reviewed Blackwell V40 `40/38-or-3d/66` layout, the floor is the type 12
TGP policy **row 8**, at row+13. Rows 2/7 participate in the existing coordinated
maximum edit, but their distinct permissive minima remain unchanged. The real
corpus stores 1 mW in rows 2/7 while row 8 stores the 60–400 W board floor; assuming
all three source minima agree would reject the reviewed ROMs. The descriptor
includes `policy_indices` and `format_scope` to make the narrower minimum scope
explicit. Row 9 input-current policy and all other rows are preserved.

Blackwell profiles must still use the reviewed complete matching maximum/default
selectors. Those profiles contain no validated minimum override and remain
byte-for-byte unchanged during a floor-only edit. Unknown selectors, including
selector 2, malformed/duplicate selectors, unsupported profile types, and a
nonempty table with no complete base-matching profile prevent power edits,
except for the top-level profile binding described next.
The writer does not infer minimum semantics for an unknown selector or silently
ignore an unknown profile alongside a valid one.

**Top-level override profile (ASUS XOC-style images).** Two selection rows precede
the 16 profiles: stage 1 (+0x0A, header `01 08 00 00 00`) maps a code 0..3 to a
power value, and stage 2 (+0x47, header `02 00 00 00 00`) maps that power value to a
profile. On the stock FE and both ASUS XOC images, the top code 3 gives 600 W, which
selects profile 7. The code is probably the 12V-2x6 sense level, but that is inferred,
not proven. The two XOC images keep the base rows at 2001 W / 5001 A, and no profile
matches them. In that case, and only then, the power and 12 V input fields bind to
the profile the chain reaches from the top code (`BlackwellRom.selected_top_profile`).
Every one of these conditions must hold, or the fields stay hidden as before:

- both stage headers are exact, every stage entry has type 0 or 1, and the top code
  is unique;
- its power value is nonzero and is exactly one stage 2 key;
- that key names an enabled profile with all eight 2/7/8/9 maximum/default entries;
- each default is at or below its maximum, and the 2/7/8 maxima are equal;
- every value is at or below the same base value, and 8/9 defaults are at or above
  the base row 8/9 minima;
- no entry of another profile exceeds the same entry of the bound profile.

The bound fields write only that profile's entries. The maximum and rated values of
base rows 2/7/8/9 are never written; each bound field is capped by the same base
value (a rated field also by the base rated value), and a value above it is refused
with `OUT_OF_BOUNDS`. `power_min_w`
still writes base row 8 and is capped by the profile's `(8, default)`;
`input_current_policy7_limit_ma` still writes row 7+61. The descriptors carry
`bound_profile` and `base_values`, are experimental, and their reason names the
profile and the base value. Which copy the firmware enforces (profile or base) has
not been tested on hardware.

Ada V3x `30/34/5b`, `30/32/53` and `30/2c/4b` and Ampere V3x `30/2c/47`, `30/2c/43` and `30/32/47` locate the
TGP policy using header byte 10 (notebooks: byte 13), validate its type1/mW flags, bounds and power
channel, and write its row+2 minimum in every validated duplicate chain. Nonempty Ada profiles are accepted only
in the cable sense layout described under [Ada fields](#ada-fields), where the floor stays at or below every
profile value of the TGP row; other nonempty Ada profiles, and any on Ampere or Turing, keep the power fields
hidden. The Ampere BIT P token has no profile-table pointer (or a null one). Neither format
inherits a Blackwell row index or unit association for unrelated policies.

Only the canonical `power_min_w` request with the complete reviewed offsets,
encoding and scale authorizes a minimum change. Extension registries and aliases
cannot relax its 1 W/default bounds, change an unrelated minimum, or edit base
or profile factory/rated defaults; only the canonical rated-default requests below
may change a rated value. Full power headers, row identities and opaque
row/profile bytes are preserved. The manifest identifies the requested floor,
changed offsets and repaired integrity bytes; runtime fields remain `unknown`.
For original floors within the supported edit range, an unchanged floor is an
exact no-op, and restoring that floor reproduces the original archival bytes.
An original floor below 1 W remains inspectable but is outside the edit range.

```sh
./nvbios edit original.rom modified.rom --set power_min_w=1 --dry-run
./nvbios edit original.rom modified.rom --set power_min_w=1 --set power_max_w=100 --dry-run
```

The second command succeeds only if 100 W also meets that ROM's protected-default
maximum bound. Removing `--dry-run` saves a new copy and JSON manifest; it does
not deploy or activate the image.

## Experimental boot default power, 12 V input current and clock ranges

Offline encoding, ownership, hashes and reparsing are verified like the other
fields. **No edited value of these fields has
been booted on hardware**, so each descriptor carries `experimental: true` and the
GUI labels say "experimental" in English and Spanish. Runtime capability stays
`unknown`.

### Boot default power (`power_default_w`)

The rated value of the TGP policy is the limit the firmware applies at boot when no
client sets a cap. On reviewed Blackwell images that is row 8 at row+17, written
together with the `(8, default)` entry of every complete matching profile (on a
top-level profile binding, only that profile's `(8, default)` entry). Ada and
Ampere write the header-indexed TGP row+6 in every validated duplicate chain (on an
Ada image with cable sense profiles, also the rated entry of the top-level profile).
A read-only NVML capture (`nvmlDeviceGetPowerManagementDefaultLimit`) showed the
default power limit equal to this stored value in the deployed payload tables on
the seven reviewed Blackwell devices and on the reviewed Ada device. The capture
is not distributed.

Rows 2 and 7 keep their own rated values, which equal their stored maxima in every
reviewed source. They behave as fixed policies (current = rated). Whether they bind
when the TGP default or ceiling is raised above them is **untested**; check NVML and
the measured board power before relying on a raised default.

### 12 V input current (`input_current_rated_ma`, `input_current_max_ma`)

Row 9 is the board input-current policy (ROM type 11, RM 30, API 25), not the
NVVDD/MSVDD output OCP of rows 13/14. A row is recognized only for a reviewed PCI
identity whose 102-byte row shape matches one of two templates (monitor index 9,
or 2 on Max-Q). The shape check excludes the range bytes 13:25. Row byte 1, the
unit discriminator, must be 1. In the saved GET capture INFO+8 is 1 for rows 9-14
(mA, as on the output-OCP rows 13/14) and 0 for the mW rows. Values are
integer mA stored as uint32, for example 80000 mA on the 5090 Matrix and 6600 mA on
the SFF.

The client API does not raise this policy. Its arbitrated limit can still be lower
than the rated value: a third-party STATUS read showed a limit of 80 A and an
arbitrated 62 A. Raising the rated value needs `input_current_rated_ma` and, when
above the stored ceiling, `input_current_max_ma` in the same request. Both write the
base row and the `(9, default)`/`(9, maximum)` entries of complete matching profiles
(on a top-level profile binding, only that profile's entries, which the editor keeps at
or below the base row).
These are stored policy values, not hardware-safe current ratings. Connector, slot
and cable limits still apply, for example on a slot-powered card.

Policy 7 also stores a limit linked to policy 9, exposed as the separate field
`input_current_policy7_limit_ma`:

- row 7 byte 33 is 9, and its value at row+61 equals the row 9 limit on every
  reviewed source;
- saved GET INFO of policy 7 references policy 9, and its CONTROL carries policy 9's
  current value;
- a third-party XOC image raised this value from 80 A to 160 A while setting row 9 to
  5001 A.

Raising row 9 alone may therefore leave the effective limit at the policy 7 value,
so a raise should set this field too, as the XOC image did. Which value binds is
still to be measured on hardware.

The field is recognized only when row 9 is recognized, row 7 has type 13 and
byte 33 = 9, and the 102-byte row 7 shape matches the reviewed template. The shape
check excludes the range bytes 13:25 and the value bytes 61:65. The value is integer
mA stored as uint32 at row+61, from 1 to 0x7FFFFFFF, with no order imposed against
row 9. Only the canonical binding may write those four bytes. The rest of row 7
keeps its existing protection: only `power_max_w` (or an extension binding on a
maximum) writes its maximum at row+21. An unrecognized row 9 keeps the read-only
`input_policy_9_max_raw` field with unknown units.

The reviewed vendor XOC and 2500 W images agree with this model:

- On the two ASUS XOC images, the base row 9 is 5001000 mA, while profile 7 (the one
  reached at the top selection level) sets policy 9 to 120000 and 160000 mA. The row 7
  value equals that profile value. The editor shows and edits these profile values.
- The MSI 2500 W image has no profiles. It stores 250000 mA in both row 9 and row 7.
- Both vendors also raise the rated values of rows 2/7 together with their maxima.

### Fixed board policies 2/7, opt-in (`board_fixed_rated_w`)

Rows 2 and 7 are fixed board policies: in the saved GET their CONTROL current equals
their rated value, even on boots where their maxima had been raised (MaxQ3 at
325000 of 350000 mW, the SFF at 70000 of 100000 mW). `power_max_w` raises only their
maxima. The ASUS XOC and MSI 2500 W images instead store rated = maximum in both
rows. Raising the ceiling above the factory rated value may therefore stay capped
until this rated value follows it. Whether that cap applies is untested.

`board_fixed_rated_w` writes the rated value (row+17) of rows 2 and 7, which must
be equal in the source, plus the `(2, default)` and `(7, default)` entries of
complete matching profiles; on a top-level profile binding it writes only that
profile's `(2, default)` and `(7, default)`. It is in the `board-power` ordering group, so it can
never exceed the ceiling of the same result. A typical XOC-style request sets it
together with `power_max_w`, for example to 1000 W on the 5090. The descriptor has
`opt_in: true`. The GUI hides it until **Show advanced XOC-style fields** is ticked;
the box is off by default. CLI and API callers opt in by naming the key.

### PCIe slot power (`slot_power_rated_w`, `slot_power_max_w`)

The reviewed RTX PRO 4000 SFF carries policy row 19: type 2, a mW policy
(byte 1 = 0 and GET INFO+8 = 0) on power-monitor channel 1, the PCIe slot input.
It stores 1/66000/66000 mW, and the saved GET shows a current of 66000. It
therefore probably caps the slot-powered card near 66 W even when the TGP ceiling
is higher. Recognition requires the SFF identity 0x2C33, type 2, monitor 1 and the
reviewed 102-byte shape, excluding range bytes 13:25. The RTX 5060 Ti (0x2D04)
holds the same shape at row 18 (0/66000/66000 mW) and is accepted there by that
comparison alone, without saved GET. The fields use W, stored as uint32 mW, and
form the `slot-power` ordering group.

Raising them lets the board draw more than the PCIe slot rating, which is only
appropriate with hardware that can supply that power. The fields are read-only when
a profile table cannot be decoded. The 12 V
input-current values (6600 mA on the SFF) may also bind and should be raised with
them. Nothing here is hardware-tested.

### Auxiliary power connector input, opt-in (`connector_1_power_rated_w`, `connector_1_power_max_w`)

Some boards store a power policy on the input of their auxiliary power connector, apart
from the board power limit. On a board with one 8-pin connector it most likely holds
that connector at 150 W, so the board stops below a raised board power limit (inferred,
not hardware-tested). One RTX 4070 with one 8-pin connector, its board power limit raised
to 240 W, stopped at about 195-198 W under load with 142.6 W on the 8-pin input and
52.5 W on the slot; its normalized power reading (95.3 %) is close to 142.6 / 150
(95.1 %). A similar stop was reported on an RTX 5060 Ti with one 8-pin connector (no
readings).

On GB20x the row is recognized by its shape and channel, whatever the device:

- it has the shape of the GET-reviewed SFF slot policy (row 19: type 2, byte 1 = 0 for
  mW, every byte but the range bytes 13:25 and the monitor byte 5);
- its monitor's power channel is byte-identical to the auxiliary connector input
  channel `05 da 00 1b b7 00 00 10`, then zero bytes with byte 15 = 1 (a class-5 single
  input at 12 V, rail 0xda, provider byte 1). The saved GET reports that channel as
  monitor 2 (class 8, rail 218) on every connector-powered reviewed source (RTX PRO 6000
  Max-Q, RTX 5090, 5080, 5070 Ti), where the Max-Q 12 V input policy (row 9) reads it, and
  no such monitor on the slot-powered RTX PRO 4000 SFF. Every connector-powered GB20x image
  of the corpus stores it as channel 2;
- it is not one of rows 2/7/8/9, the only policies an override profile entry names.

The rail does not name the connector type: 8-pin and 12V-2x6 boards both use 0xda. Only
the RTX 5060 Ti images have such a row: row 17, 0/150000/150000 mW (the corpus holds two
different images, one of them from a board with one 8-pin connector). Where more than
one row matched, every value would stay read-only, since which row binds is unknown. The
keys follow the numbered Ampere connector channels (`connector_1_*`). The values are in
W, stored as uint32 mW, in the `connector-1-power` ordering group: the ceiling goes from
the rated value up to the encoding maximum and the rated value up to the ceiling, so set
both in one edit to go past the stored ceiling. No override profile names this row, so
the base row alone is written, and the fields are read-only when the profiles do not
decode. They are opt-in (shown under **Show advanced XOC-style fields**) and
experimental: no edited value has been booted.

On the RTX PRO 6000 Max-Q and the RTX 5070 images the 12 V input current policy (row 9)
reads this connector input channel too, not the whole 12 V input: there it limits the
current through the connector alone, without the slot (25 A on the RTX 5070, about 300 W
at 12 V). Their `input_current_*` reasons say so. Neither has a connector power row.

The ROM does not store the connector type. A PCIe 8-pin connector is rated 150 W and a
12V-2x6 cable is rated for the level its sense pins report. Going past what the connector
and its cable are rated for puts the cable, the connector and the power supply at risk;
that is the user's call. The board power limit, the slot limit (`slot_power_*`) and the
12 V input current limit (`input_current_*` and `input_current_policy7_limit_ma`; 18 A on
the RTX 5060 Ti, about 216 W at 12 V) still apply and may bind next. To raise the
connector limit of an RTX 5060 Ti to 200 W (above the 150 W rating of an 8-pin
connector) together with a 220 W board limit and a 25 A input current limit
(`board_fixed_rated_w` raises the rated value of the fixed board policies 2/7 with the
ceiling):

```sh
./nvbios edit original.rom modified.rom --set power_max_w=220 --set power_default_w=220 \
  --set board_fixed_rated_w=220 --set connector_1_power_max_w=200 --set connector_1_power_rated_w=200 \
  --set input_current_max_ma=25000 --set input_current_rated_ma=25000 --set input_current_policy7_limit_ma=25000
```

### Maximum operating temperature (`max_operating_temp_c`)

The thermal policy table (P+0x50, object 0x1b) has version 0x20, a 12-byte header (22
bytes on the RTX PRO 4000 SFF) and 15 entries of 48 bytes. GSP-RM 615.78.08 unpacks each
entry as `2b3w10d`: byte 0 is the policy class, and an entry with class 0 is skipped;
bytes 2..7 are three temperatures in 1/32 °C that the parser shifts into 1/256 °C and
hands to the policy together. Entry 0 is class 1 with byte 1 = 1 on every image and
stores three equal temperatures, one value per product:

| Product (PCI device) | Entry 0 |
| --- | --- |
| RTX 5090 (2b85), every vendor image | 90 °C |
| RTX 5080 (2c02), RTX 5070 Ti (2c05) | 88 °C |
| RTX 5070 (2f04) | 85 °C |
| RTX 5060 Ti (2d04) | 87 °C |
| RTX PRO 6000 Max-Q (2bb4) | 92 °C |
| RTX PRO 6000 Workstation (2bb1) | 93 °C |
| RTX PRO 4000 SFF (2c33) | 96 °C |
| RTX 5080 Laptop GPU (2c59), RTX 5090 Laptop GPU (2c18) | 89 °C |

A read-only `nvidia-smi` capture on five devices (two RTX PRO 6000 Max-Q, an RTX 5080,
an RTX 5070 Ti and an RTX PRO 4000 SFF) showed "GPU Current Temp" plus "GPU Current
T.Limit Temp" equal to this value, so it is the limit the driver measures the GPU's
temperature headroom against (its maximum operating temperature). The capture is not
distributed. Entries 1 and 4 store 105 °C (entry 4: 103 °C on the RTX 5080 and 5090 Laptop
GPUs); what they do was not traced. The RTX 5080 and 5090 Laptop GPU images alone also store
a second class 1 entry with byte 1 = 1, entry 2 at 87/75/87 °C, below their entry 0 (89 °C).
Its role was not traced and no notebook was in the capture, so on those products the lower
entry may limit the GPU first and a raised value may have no effect; the field stays editable
there, and its `reason` names the other entry.

- **Edit.** One field writes the three temperatures together, in steps of 1/32 °C.
  Byte 0, byte 1 and every other entry stay as stored, whatever the field registry, and
  object 0x1b's hash is repaired.
- **Range.** Down to 40 °C, and up to 3 °C above the product's stock value in the table
  above (93 °C on an RTX 5090). The ceiling comes from the product, not from the value
  stored in the ROM, so a ROM lowered earlier can go back up, and repeated edits cannot
  creep higher. A product without a reviewed stock value (for example an RTX 5090 D) can
  only lower it. A stored value already above the ceiling may stay or go down.
- **Read-only cases.** The ASUS XOC and MSI Lightning images set byte 0 of entries 0, 1
  and 4 to 0, so the driver skips those policies: the field is read-only there, and the
  editor never enables an entry. An entry 0 whose three temperatures differ, or that is
  not the class 1 entry with byte 1 = 1, is read-only too.
- **Expected effect (inferred).** A lower value should make the driver limit the clocks
  sooner to keep the GPU below it (a cooler, quieter card); a raised one eats into the
  thermal margin. Not hardware-tested.
- **Import.** `import_fields` never copies it (skip reason `product_specific`): each
  product has its own limit.

**Turing, Ampere and Ada.** These images store a version 0x10 table at P+0x50: a
10-byte header (11 bytes on Ada) and four (Turing) or five 40-byte entries. GSP-RM
615.78.08 (`gsp_tu10x.bin` for Turing, `gsp_ga10x.bin` for Ampere and Ada) reads each
entry as `2b3w8d`, with the class byte (0 skips the entry, 1 is read) and the three
temperatures in 1/32 °C of GB20x; byte 1 is the thermal channel. Which entry holds the
maximum operating temperature is not fixed. The parser keeps header bytes 4, 5, 6 and 9
as four policy indices (0xff: none), in the fields the version 0x20 parser fills from
its header bytes 7..10, and at load the driver drops the index from byte 9 when it does
not name a policy it read. On GB20x that index (header byte 10 there) names entry 0, the entry the
capture above matched, on every image but the XOC-style ones (0xff). So on these families
the editor takes the entry header byte 9 names:

| Images | Named entry | Temperature |
| --- | --- | --- |
| Desktop and workstation, every family | entry 0 (channel 0) | 86-98 °C, one value per product |
| Turing laptop and Max-Q | entry 0 (channel 1) | 102 °C |
| Ampere laptop | entry 0 (channel 1) | 105 °C |
| Ada laptop | entry 1 (channel 1) | 105 °C |
| Turing XOC (two RTX 2080 Ti images) | none (0xff) | every entry disabled |

A read-only `nvidia-smi` capture on an RTX 2000 Ada (95.07.47.00.19, running an override
with the same table) showed "GPU Current Temp" plus "GPU Current T.Limit Temp" equal to
96 °C, the temperature of entry 0, which header byte 9 names, and "GPU Target Temperature
Specification" equal to 88 °C, the first temperature of entry 2, which header byte 4
names. No laptop and no Turing or Ampere board was in the capture.

- **Edit, range and import.** As on GB20x: the three temperatures of that entry, together
  and in every chain, from 40 °C up to 3 °C above the product's stock value (the editor
  keeps one per PCI device from the corpus, for example 89 °C on an RTX 2080 Ti, 93 °C on
  an RTX 3090, 90 °C on an RTX 4090 and 96 °C on an RTX 2000 Ada); never imported. The
  table's other bytes stay as stored, whatever the field registry, and the checksum of its
  image (the data image of the power and fan tables) is repaired.
- **Read-only cases.** Header byte 9 = 0xff (the Turing XOC images, whose entries are all
  disabled), a named entry that is disabled, not class 1 or holds three different
  temperatures, and the Ampere and Ada laptop images: besides the named 105 °C entry
  (channel 1) they store an enabled 89 °C entry (channel 0) that no header byte names, and
  which of the two limits the GPU first is not known, so both stay as stored. The Turing
  laptop and Max-Q images store no such entry and stay editable, although the
  `nvidia-smi` relation above was only checked on a desktop entry (channel 0), not on
  their channel 1 entry.
- Not hardware-tested.

### Clock offset ranges

The GB20x clock table (object 3) stores a signed 16-bit minimum and maximum offset
for each structurally identified domain row: GPC, XBAR, DRAM, SYS and VID.

| Field | Public unit | Relation to the table |
| --- | --- | --- |
| `gpc_offset_min_mhz`, `gpc_offset_max_mhz` | MHz | NVML = table MHz |
| `memory_offset_min_mhz` | MHz | NVML = 2 × table MHz; must be even |
| `dram_min_table_mhz` | table MHz | GUI-hidden alias of `memory_offset_min_mhz` |
| `xbar/sys/vid_min_table_mhz`, `xbar/sys/vid_max_table_mhz` | table MHz | No runtime alias |

The GPC and memory relations come from read-only `nvmlDeviceGetGpcClkMinMaxVfOffset`
and `nvmlDeviceGetMemClkMinMaxVfOffset` on the seven reviewed devices: GPC
-1000..1000 for table -1000..1000, memory minimum -2000 for table -1000, and memory
maxima 12000/13000 for tables 6000/6500. Every range must keep 0 inside it, so a
minimum is at most 0 and a maximum at least 0. The existing
`memory_offset_max_mhz`/`dram_max_table_mhz` ceiling keeps its hardware-validated
status. Ada and Ampere rows are named by their GV HAL position (see [Ada fields](#ada-fields)
and [Ampere fields](#ampere-fields)).

### GPC curve offset (`gpc_curve_offset_mhz`, opt-in)

The VBIOS stores no list of GPC VF points. The clocks table GPC row (C+0x08) names one
clock programming entry (C+0x0c), and that entry names the root of a VFE equation tree
(P+0x20) that gives the GPC clock (MHz) from the voltage, the chip's fuses and the
temperature. The root is a compare equation with MHz output that no other equation
references and that links no next equation, on every Ada, Ampere and GB20x image of the
corpus. The GPC frequency delta stored in the clocks table row does not help: GSP-RM
615.78.08 ignores it by default and, when a client enables it, takes the larger of it
and 0, so it cannot lower the curve.

- **Edit.** A value other than 0 writes a constant MHz equation (type 1, the root's
  variable, minimum = maximum = constant = value, zero slopes, no next link) into the
  first unused VFE slot and links it as the root's next equation; 0 restores the
  unused slot and the empty link, byte for byte. The editor's voltage fields rely on
  the driver adding an equation's next equation to its clamped value; applied to the
  GPC root, every point of the curve should move by the value (inferred: the curve
  evaluation was not traced). The constant is added after the root's own clamp, so the
  root's floor and cap (Ampere 210..2100 MHz, Ada 210..3450, GB20x 180..3450) move with
  it. No stock image links a constant to the GPC root. NVIDIA shifts a curve between
  SKUs of one chip inside it instead: the RTX 2080 Ti and TITAN RTX curves differ by
  +45 MHz in the constant term of one polynomial, under the curve's floor and cap, so
  up to about 550 mV they match. Vendor factory-OC images in the corpus keep the
  reference curve.
- **Range and interactions.** -500..+500 MHz in whole MHz, at the user's discretion:
  values far from 0 can make the card unstable, and below about 450-500 mV the curve's
  floor (180-210 MHz) plus a large negative value is not meaningful. A tuning tool's
  GPC offset still applies on top, and so does the factory GPC offset of a factory-OC
  image (`factory_gpc_offset_mhz`, below), a separate mechanism. `nvidia-smi` max clocks
  and the rated base and boost clocks come from other tables and do not change.
- **Gates.** The GPC row names a single programming entry, no other VFE-driven entry
  names the same root, every VFE equation kind is one the editor reads (0-4 and 7),
  and the first unused slot is clean and unreferenced (below 0xff on Ampere's u8
  links). Writes go to every image chain; on GB20x they stay in object 0x14, whose
  hash is repaired. After every edit, the root equation and that slot of every chain
  may differ only at the bytes of the reviewed binding, whatever the field registry,
  or at the copy and link bytes of a VMIN edit on the RTX 4090 95.02.3C images, which
  takes the same first unused slot (one or the other per edit, see
  [Shared VMIN equation on RTX 4090 95.02.3C](#shared-vmin-equation-on-rtx-4090-95023c)),
  or at the copy a GB20x flat follow-OV value writes there (`nvvdd_rel_alt_follow_ov_mv`,
  likewise in a separate edit). Turing is not covered. Not hardware-tested.

### Factory GPC and memory offsets (`factory_gpc_offset_mhz`, `factory_memory_offset_mhz`) and rated boost (`factory_rated_boost_mhz`)

The factory clock record (P+0x98) holds a header, then array A and array B, two `{u8
flag, u32 kHz}` entries each. It is 27 bytes with the header `10 07 05 02 05 02 00` on
GB20x (object 0x26), Ampere and Ada (byte 6 is 1 on three Ada factory-OC images, two RTX
4090 and an RTX 4080), and 26 bytes with the 6-byte header `10 06 05 02 05 02` on Turing.
GSP-RM 615.78.08 reads it at boot, with the same code in `gsp_tu10x.bin` and
`gsp_ga10x.bin`:

- The header must have version 0x10; a 6-byte header is read as `6b`, a longer one as
  `7b` (byte 6 is kept as a clock flag). Each array-A entry is mapped to a clock domain
  through a descriptor table chosen by the clocks table HAL, the same table in both
  firmware images. For the GV HAL of the Turing (v0x35), Ampere and Ada (v0x40) clocks
  tables and for the GB20x HAL, **A0 maps to the GPC domain** (its value is copied to the
  companion domain too) and **A1 to the memory clock domain**. A flag of 0 skips the entry,
  1 stores its value as the domain's static frequency delta, and any other flag fails the
  read.
- The delta is stored for the domain class the clocks table gives programmable rows and
  refused for fixed rows. The GPC and memory clock rows have the same usage on every image
  (usage 2 on GB20x, 1 elsewhere), so the driver accepts A1 wherever it accepts A0, which
  vendor images of every family enable. On Turing, whose clocks table loader was not
  traced, two vendor images ship with A1 enabled.
- The function that applies a static delta to a clock loads the 32-bit value
  sign-extended, divides it by 1000 with a signed division (truncating toward zero to
  whole MHz), adds it to the clock in MHz and returns 0 if the sum is negative. So both are
  **signed** kHz offsets: a negative value lowers the clock.
- Each array-B entry whose flag is 1 is written, in MHz (kHz / 1000), into a
  performance-state clock entry; B1 is the rated boost clock.

What the corpus stores (A0/B1 in MHz):

| Family | Factory-OC images | Other images |
| --- | --- | --- |
| GB20x | 120/2655 (RTX 5090 Aorus Master), 195/2730 (three other RTX 5090), 45/2580 (ASUS XOC), 30/2640 (RTX 5080), 120/2572 (RTX 5070 Ti), 60/2572 (RTX 5070), 30/2602 (two RTX 5060 Ti) | zeros with flag 0 |
| Ada | 60/2625 (three RTX 4090), 15/2595 and 75/2640 (RTX 4080), 15/2565 (RTX 4070 SUPER) | A0 flag 1 with 0 MHz on the RTX 4060 and 4060 Ti; B1 alone on an RTX 4080 SUPER and an RTX 4070; zeros elsewhere |
| Ampere | 15 to 45 (RTX 3060 to 3090 Ti) | A0 flag 1 with 0 MHz on two RTX 3060 Ti and an RTX 3070; B1 alone on an RTX 3060; zeros elsewhere |
| Turing | 75/1650, 135/1800 and 120/1680 (RTX 2080 Ti), 120/1890 (RTX 2080), 30/1845 (RTX 2080 SUPER), 15 to 60 (RTX 2060/2070, GTX 16) | A0 flag 1 with 0 MHz on a GTX 1660 Ti laptop; 60 MHz with flag 0 (skipped) on the TITAN RTX; zeros elsewhere |

A1 is enabled on two Turing images only: 400 MHz on an RTX 2080 Ti, and 70 MHz on an RTX
2080 whose vendor rates it at 1890 MHz boost (its B1) and 14140 MT/s memory, that is
7000 + 70 = 7070 MHz of memory clock. So A1 is in the memory clock that `nvidia-smi` and
MSI Afterburner show (7000 MHz on 14 Gbps GDDR6), half the transfer rate. Tools that show
the transfer rate, such as nvidia-settings, and this editor's memory offset floor and
ceiling (`memory_offset_min/max_mhz`) use twice this number: +500 MHz here is +1000 MHz
there. The GUI shows that number next to the field.

- **Value.** Each field shows the entry's effective value: the stored value while the
  flag is 1, and 0 while it is 0, whatever value bytes are stored (as on the TITAN RTX).
- **Edit.** `factory_gpc_offset_mhz` takes -500..+500 MHz and
  `factory_memory_offset_mhz` -5000..+5000 MHz, in whole MHz (stored as kHz; the driver
  drops any fraction of a MHz), on every image whose record has the reviewed header and
  flags and whose clocks table the editor reads. A value other than 0 writes flag 1 and
  the kHz value. On a ROM that stores no offset (Founders Edition, reference, workstation
  and laptop ROMs) that turns one on, which was not tested on such ROMs. 0 on an entry
  that already reads 0 (flag 0 whatever it stores, or flag 1 with 0 kHz) leaves its five
  bytes as they were; 0 on an entry with an offset writes flag 0 with 0 kHz, how ROMs
  without the offset store it, so a saved copy of such a ROM set back to 0 is
  byte-identical to it again. The few ROMs that store flag 1 with 0 kHz, and the TITAN RTX
  with its skipped 60 MHz, come back as flag 0 with 0 kHz instead, also no offset for the
  driver; a saved copy cannot tell which of the two a ROM shipped with. A stored value
  outside the range may stay as it is. The header, the other entries, array B and, on
  GB20x, the rest of object 0x26 stay as stored, whatever the field registry. GB20x
  repairs object 0x26's hash; the other families write every chain and repair the
  checksum of the record's image (the data image of the power and fan tables).
- **Read-only cases.** A stored value that is not a whole number of MHz (no reviewed image
  has one), a record with another header or with a flag other than 0 or 1 (the driver
  refuses both; the field then shows no value), and a clocks table the editor does not
  read.
- **Rated boost.** `factory_rated_boost_mhz` shows B1, read-only, where its flag is 1. It
  stays stock when an offset changes, so the advertised boost clock does not follow it.
- **Interactions.** The factory GPC offset is not the GPC curve offset
  (`gpc_curve_offset_mhz`), which links a VFE equation to the curve root: the two are
  separate mechanisms and both apply. Whether a tuning tool's offset adds to a factory
  offset or replaces it (both are clock domain frequency deltas) was not traced. The
  stored GPC offset range (-1000..+1000 MHz or wider on every image) holds the whole
  -500..+500 MHz range. The memory range is wide on purpose; memory seldom runs stable
  far above stock, and a value far from the stock one can make the card unstable or keep
  it from starting. Not hardware-tested: zeroing the GPC offset on a factory-OC card and
  comparing the GPC clock at a fixed voltage, and a small memory offset (+50 MHz) read
  back with `nvidia-smi -q -d CLOCK`, are the expected first checks.
- **Import.** `import_fields` copies both with the other clock offsets (section `clocks`,
  not opt-in), through `edit` with the target's bounds. A donor that stores none gives
  0 MHz; a target that stores none takes the donor's value, with the flag set. A donor
  value that is not a whole number of MHz leaves the target's own (`read_only_in_donor`).
  The rated boost (B1) stays the target's. A factory offset from another board may not be
  stable on this one.

### Memory levels that follow the offset (`memory_point_K_follows_offset`, opt-in)

The DRAM row of the clocks table (C+0x08) names a run of entries in the clock
programming table (C+0x0c; version 0x40 on Ada and Ampere, 0x50 on GB20x, an 8-byte
header): one per memory clock the performance states use, rising, each starting with
a flag byte (0x03 or 0x13) and the clock in MHz (u16). Bit 4 of the flag byte is set
on the top memory levels of every image whose entries take this shape (all but the
passive RTX A40; it is also set on the GPC and XBAR entries) and never on the 405 and
810 MHz idle levels. GSP-RM 615.78.08 decodes it as a per-entry
boolean; the code that applies an offset was not traced.

- **What a memory offset does (inferred).** The offset seems to move only the top
  levels, which carry the bit on stock images. An offset that takes the memory below the highest level without it
  drops the memory to a lower stored level instead of running in between. On an RTX
  3050 Laptop GPU (levels 405, 810, 5501 and 6001 MHz, only 6001 with the bit) the
  memory ran down to 5501 MHz with a -500 MHz offset (table scale) and left for the
  810 MHz level below that; larger offsets crashed. An RTX 5090 (levels 7001, 13801
  and 14001 MHz, the top two with the bit) ran continuously down to 10801 MHz with a
  -3000 MHz offset (table scale); its next lower level is 6800 MHz further down.
  Some laptop images (RTX 3060, 3070 and 3080 Laptop GPU) ship their intermediate
  level with the bit set.
- **Fields.** One 0/1 field per level between the 810 MHz idle level and the top
  level, numbered from the lowest; its label names the clock. Setting it was expected
  to let the offset move that level too, so the memory can run between it and the next lower
  level; lower the memory offset floor (`memory_offset_min_mhz`) as well for larger
  offsets. The levels with the bit stay the top ones, so a level can take the bit only
  when the one above has it and lose it only when the one below does not (one ordering
  group: change several together). Each write keeps the other flag bits, goes to every
  image chain and repairs the checksums (GB20x: object 4's hash). The first Ada and
  Ampere data image, which holds this table, ends with x86 filler (`2e 8b c0`) and its
  checksum byte on most corpus images (the others use the 0xff padding); that tail is
  accepted as a checksum slot.
- **Hardware result.** On the RTX 3050 Laptop GPU above, with the override verified
  byte for byte, bit 4 set on the 5501 MHz level and the memory offset floor lowered to
  -2000 MHz (table scale, which MSI Afterburner reached), the memory still dropped to
  810 MHz below a -500 MHz offset. On that card the bit does not decide the drop; what
  does is unknown.
- **Not covered.** Turing (version 0x35, another flag bit, signed digest list), images
  whose table holds another shape (the passive RTX A40) and the idle and top levels.
  Changing the memory clocks themselves is not offered.

### Joint validation

`power_min_w`, `power_default_w` and `power_max_w` form the `board-power` ordering
group (with `board_fixed_rated_w`, and on the GB20x notebook layout with
`notebook_base_tgp_w`, see [Notebook images](#notebook-images-rtx-5080-and-rtx-5090-laptop-gpu));
the two input-current fields form `input-current-12v`; each output-OCP rail's
rated and maximum fields form `nvvdd-output-ocp` or `msvdd-output-ocp`; the slot
power fields form `slot-power`; each GB20x rail's REL ceiling and floor, and the Ada NVVDD
ones, form `nvvdd-rel-clamp` or `msvdd-rel-clamp`; and the fan fields form `fan-speed` (every RPM limit and
curve speed), `fan-level` (every % limit and curve level) and `fan-temperature` (every
curve temperature and zero RPM temperature), across channels, because the extra curves
serve every channel and an upper zero RPM temperature stays at most point 1 of its own
curve. A
single-field request
is checked against the static bounds in its descriptor, which hold the partners'
current values. When partners are requested together, each value is first checked
against `bounds.encoding_minimum`/`encoding_maximum`, and then against the reviewed
bounds recomputed on the edited result. A broken minimum <= default <= maximum
order returns `OUT_OF_BOUNDS`, and so does a requested notebook base TGP that ends up
outside default <= base <= maximum. The base TGP bounds no other field: an edit without
it is checked as if it did not exist. For example, raising the default to 900 W and the
ceiling to 1000 W in one request is accepted, while the same default alone is
refused. Clock rows are reparsed after every edit: their identities must be
unchanged, and each range that contained 0 must still contain it.

A binding with the reviewed key, offsets, encoding and scale always uses the
reviewed bounds, even when an extension supplies it. Other extension bindings keep
their own bounds, as before. Only a canonical `power_min_w`, `power_default_w`,
`input_current_rated_ma`, `*_output_ocp_rated_ma`, `slot_power_rated_w`,
`slot_current_threshold_rated_ma`, `nvvdd_power_threshold_rated_w`,
`connector_N_power_rated_w`, `connector_sum_power_rated_w`,
`connector_N_current_threshold_rated_ma` or `board_fixed_rated_w` binding may change
a minimum or rated value, and only the
canonical `input_current_policy7_limit_ma` binding may write row 7's opaque bytes
61:65 (the canonical `notebook_base_tgp_w` binding, likewise, row 2's bytes 73:77 on the
GB20x notebook layout). Any other binding with one of these keys fails with `INVALID_FIELD_EVIDENCE`.
Aliases, partial offsets, other rows and non-matching profiles stay protected.
Override profiles that matched the base must still match after the edit, and no
profile may end with a policy default above its maximum. On a top-level profile
binding, the edited image must still bind the same profile through the same chain:
an edit that would let another profile exceed it, or make it equal the base table
(it would then become a matching profile and later edits would write the base), is
refused with `OUT_OF_BOUNDS`, a message naming the profile and entry, and
`details.field` set to the field of that entry; a plain order mistake gets the usual
ordering message. On Ada, a profile entry changes only through a canonical binding of
the same request (the top-level profile of the cable sense layout, written with the
base), in every duplicate chain; the other profiles keep their bytes. When a rated value
changes, the manifest sets `preservation.factory_defaults` to `false` and lists the
fields in `preservation.changed_rated_defaults`. Both describe that edit relative to
the image it received, not the original archive of a chain of edits.

```sh
./nvbios edit original.rom modified.rom --set power_default_w=900 --set power_max_w=1000 --dry-run
./nvbios edit original.rom modified.rom --set memory_offset_min_mhz=-4000 --set gpc_offset_min_mhz=-2000 --dry-run
./nvbios edit original.rom modified.rom --set input_current_rated_ma=100000 --set input_current_max_ma=100000 \
  --set input_current_policy7_limit_ma=100000 --dry-run
```

### Provenance

@pantsoftime's GB202 tool and research notes were reviewed as untrusted input:
read, never executed; the author permitted reuse. They corroborate these findings:

- object 0x03 holds per-domain s16 offset ranges; only a DRAM maximum edit was
  verified on hardware there;
- RM INFO entry 8 limitMin/limitRated/limitMax equal row 8;
- RM INFO entry 9 is type 0x1e, channel 9, limitUnit 1 (mA);
- lowering the rated OCP of entries 13/14 under load clamped GPC/XBAR, and power
  monitor channel 1 is the PCIe slot input.

No third-party code or fixed file offsets are used. Descriptors cite this as
`third-party-research` evidence next to this repository's own GET correlations.

## Single-rail images (RTX PRO 6000 Workstation, RTX 5060 Ti, RTX 5070)

Three images differ from the seven reviewed sources in their rail and clock tables:

| Image | PCI ID | BIOS |
|---|---|---|
| GB202 RTX PRO 6000 Workstation | `10de:2bb1` | `98.02.81.00.07` |
| GB206 RTX 5060 Ti (MSI Ventus 3X) | `10de:2d04` | `98.06.39.00.B2` |
| GB205 RTX 5070 (Palit GamingPro) | `10de:2f04` | `98.05.28.00.1B` |

- **Rail table.** The rail v0x30 table has one row, with header byte 4 = 0. The
  MSVDD voltage devices are disabled, so the firmware controls no MSVDD rail on these
  boards. The NVVDD row keeps the reviewed identity, REL/ALT/OV/VMIN selector offsets
  and boot offset.
  - NVVDD fields work as on the split-rail images.
  - `msvdd_rel_max_mv` is reported read-only with the single-rail reason, and no
    other MSVDD voltage field exists.
- **Clock offset table.** The table packs the same 15-byte rows with 1-byte
  sub-entries, an 18-byte stride instead of 21. The clock range fields, XBAR, SYS
  and VID included, read only the base row and are unchanged.

There is no saved GET for these devices. Their power rows are accepted by static
comparison, and the descriptors carry a `structural-row-comparison` evidence entry
with `runtime_get: false`:

- **12 V input current.** Row 9 equals a GET-reviewed template: the non-Max-Q one
  on the Workstation and the 5060 Ti, the Max-Q one (monitor 2) on the 5070. Each
  device ID is tied to one template. The policy-7 linked field additionally needs
  row 7 to match the reviewed linked-limit shape, as on every other image.
- **Output OCP.** Rows 13 and 14 both use monitor 26. Row 13 is accepted as the NVVDD
  output OCP only when the whole chain matches:
  - the row equals the single-rail shape;
  - power channel 26 (P+0x3c, object 0x16) is byte-identical to the NVVDD output
    channel of all seven GET-reviewed sources (channel 13, or 27 on Max-Q);
  - the power device that channel reads (P+0x28 entry 9, object 0x12) is identical
    to theirs.

  The MSVDD channel and device are disabled. Row 14 holds no MSVDD limit, so
  `msvdd_output_ocp_max_ma` stays read-only with the single-rail reason. Stock rated
  NVVDD OCP: 660 A on the Workstation, 170 A on the 5060 Ti, 240 A on the 5070.
- **PCIe slot power (5060 Ti).** Row 18 has the immutable shape of the GET-reviewed
  SFF row 19 slot policy (type 2, mW, monitor 1, 66 W), so `slot_power_*` edits
  row 18 there. Row 17 has the same shape on monitor 2, the auxiliary connector input
  (150 W), and is offered as the opt-in `connector_1_power_*` (see the auxiliary power
  connector input above).
- `api_rail_index` stays unknown. No edited value has been booted on these boards.

## Notebook images (RTX 5080 and RTX 5090 Laptop GPU)

| Image | PCI ID | BIOS |
|---|---|---|
| GB203 RTX 5080 Laptop GPU (Lenovo Legion 7 Pro) | `10de:2c59` | `98.03.5C.00.F2` |
| GB203 RTX 5090 Laptop GPU | `10de:2c18` | `98.03.5C.00.72` |

The notebook fields below are recognized by the tables, not by the device ID, so another
image with this layout and these rows gets them too. Only the owner's `nvidia-smi`
reading belongs to one product (the RTX 5080 Laptop GPU). The stock maximum operating
temperature (89 °C) and GR rail gating are listed for these two devices: on another
device ID the temperature can only be lowered, and the GR rail gating switch covers the
entries the image enables, so a copy saved with Off no longer shows it
([LPWR](#lpwr-idle-power-switches-and-idle-times)).

The rail and VFE tables are the split-rail ones, so the NVVDD and MSVDD voltage
fields work unchanged (REL 1025 mV, OV 1200 mV, rail INFO VMIN slot 700 mV on both
rails; the evaluated VMIN equations are min/max trees that take a value through their
clamp, see [VMIN set per chip](#vmin-set-per-chip-tree-roots-and-per-chip-equations-_vmin_fixed)). The
power policy table keeps the v0x40 format but places its rows differently:

- **TGP in row 2.** Every desktop and Max-Q source has policy header bytes 21..23 =
  `ff 08 ff` and its TGP in row 8 (type 12). The notebooks have `ff ff 02`, rows 7 and 8
  of type 0 with zero limits, and row 2 (type 1) holding 5000/80000/175000 mW
  (5000/95000/175000 mW on the RTX 5090 Laptop GPU). `nvidia-smi -q -d POWER` on an RTX 5080
  Laptop GPU running the same VBIOS reports Min 5 W, Default 80 W and Max 175 W (public
  readings of RTX 5090 Laptop GPUs: 5, 95 and 175 W). `power_min_w`,
  `power_default_w` and `power_max_w` edit row 2 at +13, +17 and +21. Override profiles on
  this layout are unreviewed; an image with any profile offers no power fields. The
  fixed-policy opt-in field does not exist here.
- **Running limit.** On a laptop Dynamic Boost (the NVIDIA platform framework on Windows,
  `nvidia-powerd` on Linux, working from the system BIOS's data) requests the running
  limit at runtime. The VBIOS ceiling only caps that request, while monitoring tools show
  the stored ceiling. Raising `power_max_w` alone therefore usually does not raise the
  running limit. The output OCP, the cooling and the laptop's VRM can also keep power
  lower. The header also stores 55000/45000/35000/25000 at bytes 24..39 (RTX 5090 Laptop
  GPU: 40000/35000/25000/15000), whose meaning is unknown.
- **Hardware result: raise the three together.** One user tested edited copies of the RTX
  5090 Laptop GPU image (`98.03.5C.00.72`, stock row 2 5000/95000/175000 mW, +73 150000 mW)
  through the Windows loader, with a 400 W adapter:

  | Edit | Running limit |
  |---|---|
  | `power_max_w` 225 | 175 W, power cap (the tools showed 225 W) |
  | `power_max_w` 225, `power_default_w` raised | 175 W |
  | `power_max_w` 190, `notebook_base_tgp_w` 165 (default left at 95 W) | about 172-175 W, power cap (the tools showed the 190 W ceiling) |
  | `power_max_w` 190, `power_default_w` 110, `notebook_base_tgp_w` 165 | about 185 W under load |

  In the third test no rail was near its limit (NVVDD output about 120 A of its 180 A
  OCP, MSVDD well under 60 A, about 8.6 A at 19.5 V on the input side). A rule consistent
  with all four, inferred from this one laptop (the firmware is closed and was not traced):
  running limit ≈ min(boot default + the platform's configurable TGP (cTGP) offset, base
  TGP) + Dynamic Boost, capped by the ceiling. On this laptop the offset looks like +55 W
  (95 -> 150) and Dynamic Boost +25 W: stock min(95 + 55, 150) + 25 = 175 W, the second
  test min(default + 55, 150) + 25 = 175 W, the third min(95 + 55, 165) + 25 = 175 W and
  the fourth min(110 + 55, 165) + 25 = 190 W (measured about 185 W). So raise
  `power_max_w`, `power_default_w` and `notebook_base_tgp_w` together, `power_default_w`
  by as many watts as you raise the base TGP; keep the base TGP at or below the ceiling
  and expect the ceiling to stay the cap. The offset and the boost most likely come from
  the laptop's system BIOS and can differ between models; the RTX 5080 Laptop GPU and
  other laptops are not tested. The laptop's VRM, cooling and power adapter were sized for the stock limit.
  The adapter feeds the CPU and the GPU at full load together, and a battery that drains
  while plugged in is the sign that it falls short. On the notebook layout `power_max_w`,
  `power_default_w` and `notebook_base_tgp_w` carry this as a `hardware-test` evidence
  entry (`set_tested: true`) whose scope names that one laptop.
- **Base TGP, experimental and opt-in (`notebook_base_tgp_w`).** Row 2 +73 holds 150000 mW
  on both notebooks, the only 150000 in each image, and 0 on every desktop and Max-Q row 2.
  A public log from another RTX 5090 Laptop GPU shows the firmware's TGP policy base at
  150000 mW while the running limit was that base + 25 W of Dynamic Boost. On the laptop
  above, +73 behaved as that base: raised with the ceiling and the boot default it raised
  the running limit, raised with the ceiling alone it did not. That rests on one laptop
  (the firmware is closed). The field exists only when row 2 bytes 0..12 equal
  the reviewed notebook bytes `010200000000012b07000ccc10` and the stored value lies
  between the rated value and the maximum of row 2. Its bounds are the stored
  `power_default_w` and `power_max_w`, so a base above the ceiling takes a higher ceiling
  in the same edit (`board-power` ordering group), for example `power_max_w=225` with
  `notebook_base_tgp_w=200`; a request with the base is refused when the result leaves it
  outside default <= base <= maximum. It bounds neither of them: without the base in the
  request, `power_max_w` and `power_default_w` keep their usual bounds, and an edit that
  puts the ceiling below the stored base or the boot default above it leaves +73 as it was
  and the edited image without this field. The laptop's VRM, cooling and power adapter
  were sized for the stock limit.
- **Output OCP.** Rows 13 and 14 equal the GET-reviewed Max-Q rows byte for byte
  (range bytes excluded), monitors 27 and 28. Each monitor's power channel and the
  power device it reads are byte-identical to the reviewed NVVDD (channel 13, device 9)
  or MSVDD (channel 12, device 8) output on all seven GET-reviewed sources. The notebook
  layout (above) with the two-row (NVVDD and MSVDD) rail table, the Max-Q rows and the
  chain are required, not a device ID, and the chain is checked on every device, a
  GET-reviewed desktop ID included: another image with this layout whose rows and chains
  match is recognized the same way, and one whose rows or chains differ, or whose rail
  table has one row, keeps them read-only. Rows 13 and 14 of both images are
  byte-identical. Stock rated values: NVVDD 180 A, MSVDD 60 A, each with rated =
  maximum.
- **Row 9** is type 3 with unit byte 1 and value 11375 (RTX 5090 Laptop GPU: 12434), not
  the type 11 input-current row of the desktop cards. It stays read-only
  (`input_policy_9_max_raw`).
- **Clock offsets.** The table equals the desktop one except bit 12 of the DRAM row
  descriptor (`0x1182` instead of `0x182`). That one bit is accepted on that row only.
- **Fans.** The cooler list is empty and every per-channel enable is 0: the laptop's
  fans belong to the system, so no fan field is offered.
- **Idle power.** Every LPWR table of the two images is byte-identical. Both enable GR
  rail gating on entries 0..2 (`lpwr_gr_rail_gating`, with its idle time, see
  [LPWR idle power switches](#lpwr-idle-power-switches-and-idle-times)).

There is no saved GET for a notebook. On one RTX 5090 Laptop GPU edited ceilings showed in
the monitoring tools, and the running limit moved only with the ceiling, the boot default
and the base TGP raised together (above); no other edited field has been tested on a
Blackwell notebook (Ampere laptops have, see Ampere fields).
The power and OCP descriptors carry `structural-row-comparison` evidence with
`runtime_get: false`.

## Fan tables (`fan_channels`, `fan_pwm_frequency_hz`, `fan_N_*`, `fan_extra_M_*`)

Five BIT P tables hold one entry per fan channel i (0..3). They have the same shape on
all fourteen Blackwell sources in the corpus:

| Pointer | Object | Shape | Entry i |
|---|---|---|---|
| P+0x58 cooler | 0x1d | v0x10, 9-byte header, four 26-byte rows | byte 0 enable; header bytes 4..7 list the active rows |
| P+0x5c policy | 0x1e | v0x20, 4-byte header, eleven 51-byte entries | byte 0 enable; byte 1 = 1 for a stored policy |
| P+0x64 mapping | 0x20 | v0x10, 4-byte header, four 5-byte entries | byte 0 enable; byte 1 the cooler row it drives |
| P+0xdc control | 0x80 | v0x10, 4-byte header, four 13-byte entries | byte 0 enable; byte 2 = i and byte 5 = 0x30 or 1 << i when stored |
| P+0xe0 speed | 0x83 | v0x10, 4-byte header, four 6-byte entries | byte 0 enable; byte 1 = i when stored (0xff otherwise); bytes 2..3 a per-fan value |

A channel is *stored* when all four non-cooler entries say so. On every source the
active rows are listed from 0 upward and ended by 0xff, the five enable sets agree,
and every active channel is stored. Fan fields are offered only when that holds.

- **Channels.** The listed count equals the read-only `nvmlDeviceGetNumFans` value on
  the five reviewed Blackwell boards: Max-Q 1, 5090 Matrix 3, 5080 2, 5070 Ti 2, SFF 1.
  `fan_channels` sets that count, for using or loading an image (offline edit, then
  override) on a board with another fan count: the 3-channel Matrix image on a
  2-channel Astral, for example. It writes
  only the cooler list and byte 0 of entries 0..3 in the five tables, and offers only
  counts that can be undone byte for byte:
  - Lowering the count drops the last channels in all five tables. It goes down only
    while each channel it clears has its own cooler configuration, channel 0's
    enable byte in every table and maximums at or above the extra curves (below), so
    raising again rebuilds it exactly. The Matrix lowered to 2 then has the same
    list and enables as the Astral XOC image, which
    keeps the third channel stored but off. Its other bytes stay its own: the cooler enable
    value (2 on the Matrix, 1 on the XOC and Lightning images; meaning unknown),
    duty bytes and policy curves.
  - Raising the count enables the next stored channels, each with channel 0's enable
    byte in every table. The cooler row must also have its own configuration (row
    bytes 4..5 and 10 unlike every earlier row), the active PWM frequency, byte
    13 = 0 and speed and level maximums at or above every enabled extra curve: those
    curves serve every active channel, so an extra curve raised above a stored row's
    maximum keeps that row off. The extra curves may start below a stored row's
    minimums, as below the active ones. The scan stops at the first channel that
    does not qualify.
  - Lowering and raising again restores the original bytes.
  - Resulting limits: Matrix, Astral XOC and Lightning 3; FE, 5080, 5070 Ti, 5070
    and Workstation 2; Max-Q and 5060 Ti 1, read-only, because their second
    channel holds only placeholder entries; SFF 1, read-only, because its extra
    curves (3600-7300 RPM) top out above the 3375 RPM maximum of its stored second
    row (1375-3375 RPM).
- **PWM frequency.** Cooler row bytes 11..13 hold the PWM frequency in Hz. It is
  25000 on the active rows of the 5090 Matrix and the Asus XOC images, and 27000
  elsewhere. On the Matrix, mVolt's BIOS override view shows the same 25 kHz and 3
  channels. The field is offered when the active rows share one value inside the
  21-28 kHz band of 4-wire PWM fans and byte 13 is 0. A
  write sets bytes 11..12 of the active rows and of the stored rows the channel count
  may enable, so those rows stay eligible. The GUI shows kHz.
- **Channel limits.** Each active cooler row stores a minimum and maximum speed
  (bytes 14..15 and 16..17, u16 RPM) and level (bytes 2 and 3, u8 %). Policy entry i
  stores the channel's curve: three level points (bytes 14..16) and three (temperature
  in 1/32 °C, RPM) points from byte 18. Enabled policy entries past the cooler rows
  (4 and 5 on every source) store further curves. On every active row of the corpus
  the row limits hold the channel's own curve, and on most of them the curve's end
  points equal the limits. The driver's fan percent maps linearly from 30 % at the
  row's minimum speed to 100 % at its maximum: RPM = min + (pct - 30) / 70 × (max -
  min). Read-only NVML readings match it on every board on the maintainers' machine
  (expected value in parentheses): RTX 5080 (1050-3500 RPM) 73 % -> 2556 (2555),
  79 % -> 2761-2774 (2765); RTX PRO 4000 SFF (3600-7300) 92 % -> 6887 (6877), 84 % ->
  6438 (6454); RTX 5070 Ti (1050-3200) 68 % -> 2206-2213 (2217); RTX PRO 6000 Max-Q
  (1000-3350) 96 % -> 3213 (3216), 90 % -> 3010 (3014). Static analysis of GSP-RM
  615.78.08 (with the GA102-GA107 settings) shows the same map: bit 0 of the policy
  flag byte (0x32), set on every enabled entry of the corpus but those of the ASUS
  XOC and MSI Lightning images (0x16/0x06), selects a control that clamps a manual
  percent to 30-100 %, turns it into an RPM target on that line and reports the
  speeds on the same scale, using only the speed limits. GSP-RM validates the level
  bytes and sends them to the fan controller, but uses them itself only where bit 0
  is clear (a manual percent then sets the PWM as a share of the level maximum). The
  driver's 30-100 % range does not follow byte 2 (10-30 on the corpus), so the
  meaning of the level bytes is unconfirmed. Hardware test on that RTX 5080 (both
  channels, fans under manual control): with the speed maximum raised from 3500 to 4000 RPM, 72 % gave 2820 RPM
  and 30 % gave 1050 RPM, as the linear map predicts; with the level minimum lowered
  from 20 to 10 %, the driver's fan range stayed 30-100 %. In that test, the 30 % setting
  matched the unchanged 1050 RPM row minimum. A lowered minimum did not lower the fans on another
  RTX 5080 (Zotac, both channels): a copy with both minimums and the first point of
  every curve lowered from 1050 to 900 RPM loaded through the Windows loader (Verify
  matched byte for byte), but at 30 % the fans still ran at 1053 and 1109 RPM. Whether
  the driver, the fan controller or the fans hold that floor is not known. The other
  limits, the curve points and other boards are not hardware-tested.
  `fan_N_min_rpm`, `fan_N_max_rpm`, `fan_N_min_pct` and `fan_N_max_pct`
  (N = row index + 1, active channels only) edit these bytes:
  - A minimum may go from 0 up to the first point of the channel's own curve, and
    below its maximum. The enabled extra curves may start below it: a stock RTX 3090
    blower image stores both of its extra curves at 1000/2203/3541 RPM and 30/55/80 %,
    starting below its 3000 RPM / 60 % minimums, so the firmware accepts them there.
    In GSP-RM 615.78.08 the policy validator checks each curve only against itself
    (temperatures rising strictly, levels and RPMs never falling), the cooler row
    validator each row only against itself (each maximum not below its minimum, the
    level maximum at most 100 %), and no load, validation or export path compares curve
    points with the row limits. The fan controller most likely runs the highest
    request of the curves that serve a fan, inside the row limits, but its code is
    encrypted, so this is not verified. A maximum may go from the highest
    top point of the channel's curve and of every enabled extra curve, and above its
    minimum, up to 32767 RPM (the signed 16-bit range of the driver's fan-curve RPM
    values) or 100 %. The speed limits also keep the channel's speed-table value
    (speed entry bytes 2..3, when that entry is enabled) inside them: it is 0.51-0.79
    of the row maximum on the corpus, and its meaning is unknown. Alone, a limit can
    therefore widen, or narrow as far as the curves that hold it and the speed value,
    but never cut into them.
  - A side with no room (a level maximum of 100 with a curve reaching 100 %, or the
    0 % / 0 RPM minimum of an Ampere board that stops its fan) stays editable with
    equal bounds: alone it keeps its value, and it moves together with the curve
    points (below). Each side is read-only when the row or a curve holds another
    shape (curve temperatures not rising strictly, speeds or levels falling,
    minimum not below maximum, the channel's curve or the speed value below the
    minimum, a curve or the speed value above the maximum, a maximum or a curve
    above the ceiling). Bounds are always numeric, so a joint request that breaks
    the order is refused on the edited result.
- **Curve points.** `fan_N_curve_K_temp_c`, `fan_N_curve_K_rpm` and `fan_N_curve_K_pct`
  (K = 1..3) edit point K of channel N's own policy entry: the temperature at byte
  18 + 4(K-1) (`<H`, 1/32 °C; the field is in °C, so 60.5 is stored as 1936 and 60.01
  is refused as `UNREPRESENTABLE_VALUE`), the speed at byte 20 + 4(K-1) (`<H`, RPM)
  and the level at byte 14 + (K-1) (`<B`, %). `fan_extra_M_curve_K_*` edit the
  enabled policy entries past the cooler rows, numbered M = 1.. in entry order (GB20x
  entries 4 and 5, Ada and Ampere entry 2 and, on most images, 3; on the RTX 3050 6GB
  and 8GB the extra curve is entry 1, see the Ampere fans). On the corpus the
  channel curves span 43-97 °C and the extra curves 92-108 °C; three Ampere boards
  store a point off a whole degree (49.90625, 51.90625 and 59.90625 °C).
  - Temperatures rise strictly: point K stays between its neighbors plus or minus
    1/32 °C, from 0 °C for point 1 up to 110 °C for point 3. Two points may never
    share a temperature.
  - Speeds and levels never fall: point K stays between its neighbors (equal is
    allowed) and inside the containment, from its floor for point 1 up to its
    ceiling for point 3. A channel curve is contained by its own row limits; an extra curve
    serves every active channel, so it stays at or below the lowest maximum of the
    active rows, from 0 up: it may sit below their minimums. The ceilings stay 32767
    RPM and 100 %.
  - A point is read-only when its curve holds another shape (as above, or a value
    above its ceiling) or when it sits outside its bounds; a point with no room
    stays editable like a limit. A stored point above the containment does not
    widen its neighbor's range. On the corpus every point is editable except the
    top speeds of the extra curves of the RTX 4080 Super and an RTX 3080 Ti, which
    top out above a channel maximum. The level points are opt-in, like the level
    limits.
  - **Lowering a maximum.** A maximum and the curves contain each other, so a maximum
    goes below a stored curve only in one request that also moves every point above
    the new maximum, of the channel's curve and of every extra curve; the fields
    share the `fan-speed` group, so the request is checked on the edited result. For
    example, on a board whose curves top out at 3500 RPM, `fan_1_max_rpm`,
    `fan_1_curve_3_rpm`, `fan_extra_1_curve_3_rpm` and `fan_extra_2_curve_3_rpm` all
    set to 3000 are accepted together; the maximum alone, or with the channel's own
    curve only, is refused (`OUT_OF_BOUNDS`). The maximum never goes below the
    channel's enabled speed-table value. Raising a minimum works the same way with
    the points of the channel's own curve below it; the extra curves may stay below
    the new minimum. Fields with no room take part too: a level maximum of 100
    lowers with the top level points, the 0 RPM minimum of a board that stops its
    fan rises with the first speed point of its curve, and the same keys undo a
    request in one edit, points left flush with the new limit included.
  - The level fields are opt-in (behind the GUI's advanced toggle) because their
    meaning is unconfirmed. Byte 3 is 100 on every active row, so `fan_N_max_pct`
    moves alone only where the curves top out lower (RTX 5060 Ti 81 %, RTX 5070
    92 %); elsewhere it lowers with the top level points.
- `fan_channels` and a channel limit, curve point, `fan_zero_rpm` or zero RPM
  temperature are refused together (`SEPARATE_EDIT_REQUIRED`): the count adds or
  removes channel fields, changes the maximums the extra curves must stay under and
  which policy entries the zero-RPM flag reads, so save it first and edit the limits,
  curves, flag and temperatures on the copy.
  The PWM frequency combines with them.
- **Preserved.** Speed values, the other policy entry bytes and the remaining bytes.

`fan_channels` uses a data-only layout binding: for each allowed count it lists the
byte written at each offset, so the manifest's `edits` entries show raw layout bytes
(`stored_units: "layout byte"`) and `affected_fields` shows the count. Any other change
to the five tables, including one made through an extension binding, is refused with
`PRESERVED_FIELD_CHANGED`. They must still decode and agree after an edit. The guard
covers the reviewed table size at every fan pointer: when the tables do not decode or
agree in the source, including a table with another header, no byte of them may
change. All fan fields are
reviewed resolvers: an extension binding cannot unlock them, relax the band or the
curve bounds, redirect their bytes or substitute a layout. Only the RTX 5080 limit
test above and the zero RPM test below have booted a fan edit on hardware.

### Zero RPM (`fan_zero_rpm`, opt-in)

Byte `0x32`, the last byte of each 51-byte policy entry, is a flag byte.

- **Firmware (static analysis).** GSP-RM 615.78.08 (`gsp_ga10x.bin`) contains its own
  parser for this entry. It unpacks each entry with the schema `2b12d1b` (2 bytes, 12
  dwords, 1 byte), decodes only entries whose byte 0 is 1 and reads the flag byte bit
  by bit: bits 1 and 2 become two separate booleans, kept with the temperature pair at
  bytes 30..33 (1/32 °C) and byte 46 of the same entry. The contribution that proposed
  the field reports the same decode in the Windows driver (nvlddmkm.sys 617.42,
  booleans at structure offsets +0x80 and +0x81). With bit 1 set, the policy validator
  (0x1b20c44) also checks the fan-stop block at bytes 30..46: a per-chip capability
  byte, upper >= lower, word 44..45 nonzero and, unless byte 46 is 0xff, dword 38..41
  >= dword 34..37 and word 42..43 nonzero; bit 2 without bit 1 is refused. The policy
  control reads and writes bit 2 only, so bit 1 most likely marks the entry as
  supporting fan stop and bit 2 sets whether it is on by default (inferred). Bytes
  34..46 most likely gate fan stop on a power reading (byte 46 an object index with
  0xff for none, the dwords in mW, word 44 a hold time in ms), but the comparison runs
  in the fan controller, outside GSP-RM, so the editor never exposes them: it keeps
  them, or copies a reviewed block whole (templates, below).
- **Ada and Ampere.** Their policy tables have the same version (0x20) and 51-byte
  entries. The version byte selects the parser with no chip check above it, so Ada and
  Ampere tables take the same parser and validator, and the GA102-GA107 and AD102-AD107
  initializers set the capability byte as the GB202-GB207 one does. That these boards
  run fan stop the same way is inferred from the shared code.
- **Corpus.** Every GeForce GB20x image sets both bits on every enabled entry: 0x17
  on the channel entries and 0x07 on the extra curves, or 0x16/0x06 (bit 0 clear) on
  the ASUS XOC and MSI Lightning images. Every RTX PRO GB20x image clears both:
  0x11/0x01 on the PRO 4000 SFF, 0x01 on the PRO 6000 Workstation and Max-Q. Bytes
  30..33 hold two rising temperatures (43/50, 50/55 or 50/60 °C on the channel
  entries) and byte 46 holds 0, except on the RTX PRO 6000 Max-Q, which stores zeros
  and 0xff there. On Ada, every GeForce image sets both bits; the RTX 4000, 4000 SFF,
  4500 and 2000 Ada store blocks the validator accepts with both bits clear
  (0x11/0x01), and the RTX 5000 and 6000 Ada store zeros and 0xff (0x01). On Ampere,
  most GeForce images set both bits (the RTX 3050 6GB and 8GB 0x17 on their channel
  entry and on their extra curve at entry 1, the only Ada or Ampere extra curve that
  keeps bit 4 set as the channel entries do; the 6GB stores its pairs, 52/55 °C, with
  byte 46 = 0xff); an RTX 3080, an RTX 3060 Ti and the GA106 RTX 3050
  store accepted blocks with both bits clear; an RTX 3090, an RTX 3070 and the RTX
  3060 8GB set bit 1 alone (0x13/0x03), so GSP-RM checks their blocks at every boot
  (the channel entry of the RTX 3060 8GB stores 40/40 °C, an upper equal to its lower,
  which the validator accepts); one RTX 3060 stores 0x13 on its channel entry and 0x07
  on its extra curve, and a stock RTX 3090 blower image 0x13 on both channel entries
  and 0x07 on both extra curves; the RTX A2000 stores no usable block on its third
  entry (zeros, word 44 = 0); the RTX A1000, A4000, A4500, A5000, A5500 and A6000
  store zeros and 0xff (0x01). No blower board ships with fan stop on its channel
  entries (the RTX 3090 blower image sets it on its extra curves only).
- **Owner reports.** The contribution came with owner reports for images outside the
  reviewed corpus: the fans stand still at idle on the Palit GameRock RTX 5090, the
  ASUS TUF RTX 5090 and the ASUS TUF RTX 5070 Ti (0x17/0x07), and keep turning at
  about 1100 RPM on the HP Omen RTX 5090 (0x11/0x01). "1 lets the fans stand still at
  low temperature" was an inferred meaning until the hardware test below.
- **Hardware test.** On that HP Omen RTX 5090 (three fan channels), a copy with
  `fan_zero_rpm` set to 1 (0x17/0x07 on the five enabled entries, written by the
  editor build that came with the contribution, which writes the same bytes) loaded
  through the Windows loader: all three fans stood still at idle, started under load
  and stopped again after cooling down. Its entries store the same fan-stop
  temperatures as the RTX 5090 Founders Edition image (43/50 °C on the channel
  entries). Ada, Ampere and the Max-Q template are not hardware-tested.
- **Field.** `fan_zero_rpm` covers the active channels' entries and the extra curves
  (the enabled curves past the cooler rows, and entry 1 of the RTX 3050 6GB and 8GB),
  in every duplicate image chain (Ada, Ampere). Like the PWM
  frequency, a write also covers the stored channel entries a larger `fan_channels`
  count may enable (the third channel of the ASUS XOC and MSI Lightning images, whose
  bits already match), so the count and the flag can change in either order. It
  changes only bits 1 and 2 of each flag byte; every other bit stays as stored,
  bit 4 included. The manifest lists the flag bytes as layout bytes.
  - It reads 1 when every entry sets both bits. On GB20x it reads 0 when every entry
    clears both; on Ada and Ampere when none sets bit 2 and bit 1 is the same on all
    of them (both clear, or bit 1 alone).
  - 1 sets both bits. 0 clears both on an image that reads 1, and only bit 2
    otherwise, so asking for the stored value never changes a byte and a stock image
    comes back byte for byte. A copy saved at 1 of a board that stores bit 1 alone
    (the RTX 3090, RTX 3070 and RTX 3060 8GB above) comes back at 0 with both bits
    clear (0x11/0x01 instead of 0x13/0x03), which loses only bit 1; keep the original
    image to return to its exact bytes.
  - The value 1 is offered only when every written entry already sets bit 1 (Ada,
    Ampere), stores a block the validator accepts (two nonzero temperatures with the
    upper at least the lower and word 44 nonzero; on GB20x also byte 46 other than
    0xff, dword 38 >= dword 34 and word 42 nonzero; on Ada and Ampere, as the
    validator has it, the dwords and word 42 only where byte 46 is not 0xff: the RTX
    3050 6GB ships 52/55 °C with byte 46 = 0xff and both bits set, so a copy saved at
    0 can go back to 1), or a reviewed template supplies one (below). An image that
    sets the bits without such a block (none in the corpus) still offers 0, but the
    copy is then read-only at 0, so that change cannot be undone in the editor.
  - Read-only: an entry with bit 2 alone (on GB20x, with either bit alone), entries
    that disagree about bit 1 (on GB20x, about either bit), chains that disagree, a
    stored channel entry whose bits differ from the enabled ones, and an entry without
    an accepted block where no template applies (the RTX A2000, whose third entry
    stores zeros). The RTX 3060 and the RTX 3090 blower image that store 0x13 and
    0x07 are read-only too: zero RPM is on for some entries and off for the others,
    so the field has no value (`current` `null`, `flag_state` `mixed`); the GUI
    shows it as Mixed.
  - The window shows the field, like the other 0/1 fields, as a switch behind the
    advanced toggle.
- **Templates for blower boards that store no block.** The RTX PRO 6000 Max-Q and
  Q325W (0x2BB4), the RTX 5000 and 6000 Ada (0x26B2, 0x26B1) and the RTX A1000, A4000,
  A4500, A5000, A5500 and A6000 (0x25B0, 0x24B0, 0x2232, 0x2231, 0x2233, 0x2230) store
  zeros and 0xff in bytes 30..46 of their enabled entries, so the flag bits alone would
  fail the validator (word 44 = 0). There, 1 also writes the blocks NVIDIA stores on
  another board (the donor below), entry for entry and in every chain, and 0 on such a
  copy writes the stock zeros and 0xff back, so the copy returns byte for byte, also
  after a zero RPM temperature edit. The template applies only to the stock entries (the same enabled
  entries and bytes 0..1, bytes 47..49 = 0); the copy is recognized by both bits set
  and the template's bytes 34..46 (the pair may have been edited). The descriptor
  carries `fan_stop_template` (`donor`, `state` `stock` or `copy`, and each entry's
  pair), and the evidence names the donor.

  | Boards | Donor (NVIDIA's own blocks) | Pairs written (°C) |
  | --- | --- | --- |
  | RTX PRO 6000 Max-Q, Q325W (entries 0, 4, 5) | RTX PRO 6000 Workstation (same GB202 chip; the RTX 5090 Founders Edition runs the same blocks with both bits set) | 43/50, 63/70, 60/70 |
  | RTX 5000 Ada, RTX 6000 Ada (entries 0, 2, 3) | RTX 4000, 4000 SFF, 4500 and 2000 Ada (the same three blocks on each, stored with both bits clear) | 40/50, 50/72, 60/70 |
  | RTX A1000, A4000, A4500, A5000, A5500, A6000 (entries 0, 2, 3) | RTX 3080 Ti Founders Edition (both bits set) | 38.875/60, 50/72, 60/70 |

  Every block also holds dwords 30000 and 100000, words 61 and 5000 and byte 46 = 0, as
  the RTX 3080 Ti Founders Edition, the RTX 4000, 4000 SFF, 4500 and 2000 Ada, the RTX
  4070 SUPER, the RTX PRO 6000 Workstation and the RTX 5090 Founders Edition images
  store them (other boards store other dwords, for example 50000/100000 on an RTX 4080
  and 30000/50000 on an RTX 4090), and each passes the validator. The donor entries
  have the same bytes 0..1 (enable and thermal channel role), and the thermal channel
  entries those roles name are the same on donor and target. Power channel 0, which
  byte 46 = 0 most likely names, is the same on the Max-Q, the Workstation and the RTX
  5090 Founders Edition; on Ada and Ampere it is the total board power channel of
  every image, with board-specific inputs. The RTX A6000 is a PG133 board like its
  donor and the A4500, A5000 and A5500 share its GA102 chip; the A4000 (GA104) and
  A1000 (GA107) share neither, so their template rests on the boards named above
  storing the same parameters. The template keeps bit 4 clear, as the Workstation copy
  already does (flags 0x01 -> 0x07): no shipped image stores bits 1 and 2 with bit 4
  clear on a channel entry, and no hardware test covered that form. Its temperature
  fields appear once a copy with the template is saved.
- **Risks.** No blower card ships with fan stop on. A stopped blower most likely moves
  no air through the card, memory and power stages included, until the card passes the
  upper temperature. A restart of a blower from 0 RPM is untested, and dense multi-GPU
  builds may see heat soak into the neighbours and stop/start cycling. A power
  criterion that never lets an idle card stop and what the fan does after a driver
  unload while stopped were not tested either. A fan tool that holds manual control
  keeps the fans running whatever the field says. Not hardware-tested on Ada, Ampere
  or the Max-Q.
- **Notes.** The reason of the field and the window, under the switch, add:
  - on a template board, the values it writes and the blower risks above;
  - on any other ROM that ships with zero RPM off (every RTX PRO and RTX A-series
    board, some GeForce Ampere ones), the same risks for a card with a blower fan;
  - where a written channel entry keeps bit 4 clear (the RTX PRO 6000 Workstation and
    Max-Q and the template boards), that with zero RPM on it holds bits 1 and 2 with
    bit 4 clear, a form no shipped ROM runs zero RPM with, so whether the fans stop
    is untested (descriptor `channel_bit4_clear`);
  - on an enabled entry that stores the same lower and upper temperature (the RTX
    3060 8GB channel entry, 40/40 °C), that zero RPM has no hysteresis there, so the
    fans may stop and start often around that temperature, and to set the lower a few
    degrees below (descriptor `zero_rpm_flat_pairs`: the lower field and the
    temperature of each such entry);
  - where a disabled channel keeps a copy of an active channel's entry (an HP OEM
    RTX 3060 12 GB, see the Ampere fans), that the editor writes the copy the same way
    (descriptor `fan_policy_copies`);
  - on Ada and Ampere, that it is not hardware-tested there, and on every board that a
    fan tool that holds manual control keeps the fans running.
- **Extension bindings.** An extension binding cannot write a fan-stop block, not even
  next to a `fan_zero_rpm` request: the fan table guard admits only the set the
  requested value writes, only when the request changes the field, and only with those
  exact bytes in the result, so another binding over the same bytes is refused
  (`PRESERVED_FIELD_CHANGED`, or `CONFLICTING_FIELDS` when both write them).

The other policy entry bytes are preserved. Setting 1 is hardware-tested on that one
HP Omen RTX 5090; other boards and setting 0 are not.

### Zero RPM temperatures (`fan_N_zero_rpm_low_temp_c`, `fan_N_zero_rpm_high_temp_c`, opt-in)

Bytes 30..33 of a policy entry hold two `<H` temperatures in 1/32 °C, the lower first.

- **Firmware (static analysis).** In GSP-RM 615.78.08 (`gsp_ga10x.bin`) the entry
  parser above reads the two words (kept in 1/256 °C) together with the zero RPM
  booleans and byte 46, for every enabled entry: the channel entries and the curves
  past the cooler rows go through the same path. The policy constructor copies all
  of them into the policy's configuration, and its configuration export passes them
  on together. The analysis did not reach a comparison with a measured temperature,
  so it does not show which value stops the fans and which starts them, which sensor
  they apply to, or how the policies combine. Byte 46 is passed on unchanged; its
  meaning is unknown.
- **Corpus.** Every GPU-driven GB20x image except the RTX PRO 6000 Max-Q stores a
  rising nonzero pair and byte 46 = 0 on each enabled entry: 43/50, 50/55 or 50/60 °C
  on the channel entries and 60-80/70-90 °C on the extra curves, including the RTX
  PRO images, whose zero RPM bits are clear. The Max-Q stores zeros and 0xff.
- **Hardware test.** On a Zotac RTX 5080 (43/50 °C on its channel entries, an image
  outside the reviewed corpus) the idle fans started at about 52 °C. The owner loaded
  a copy with the upper value set to 60 °C through the Windows loader, and at 59 °C
  during video playback the fans stayed at 0 RPM. So raising the upper value kept idle
  fans stopped past the stored 50 °C on that board. A start at 60 °C was not observed,
  which entries were edited and whether the lower value changed were not reported, and
  "stop below the lower" is still inferred.
- **Fields.** Each active channel (`fan_N_...`) and each enabled extra curve
  (`fan_extra_M_...`, numbered as in the curve fields) gets a lower and an upper
  field, only where the entry stores a nonzero pair whose upper is at least its lower
  and byte 46 is not 0xff: nothing is offered or synthesized for zeros (a stock
  template board gets its fields once a copy with the template is saved), and the RTX
  3050 6GB, which stores 52/55 °C with byte 46 = 0xff on both entries, gets none. Stored
  channels that a larger `fan_channels` count enables keep their bytes and get their
  fields once enabled. Values are exact in 1/32 °C. An edit keeps the lower above 0 °C
  and below the upper. The upper stays at most point 1 of the same entry's fan curve
  (bytes 18..19) and at most 110 °C, an editor limit as for the curve temperatures,
  not a tested firmware limit (a stored upper above 110 °C leaves the pair read-only).
  That bound holds with zero RPM on or off, so turning zero RPM on later never meets an
  upper the editor let through. A stored upper above point 1 shows as stored and can
  only come down to it.
  - Where the stored lower is at or above point 1, no upper is both above the lower
    and at most point 1: the extra curves of an RTX 3080 (100/105 °C under 95 and
    97 °C), the GA106 RTX 3050 (50/55 °C under 43 °C) and three RTX 4090 partner images
    (60/70 °C on 60 °C). There the upper's range starts at what an edit that also
    lowers the lower allows, 0.0625 °C, so no field shows a minimum above its maximum
    (a read-only pair shows its range the same way, as on the RTX 3060 that mixes the
    bits), and the upper moves only with the lower. An upper requested at or below its lower,
    alone or together with it, is refused (`OUT_OF_BOUNDS`) with the lower as
    `details.field`, its range in `details.bounds` and both in
    `details.joint_fields`; the message says to set the lower below the upper.
  - The channel entry of the RTX 3060 8GB stores 40/40 °C, the same lower and upper,
    which the validator accepts. Its fields show the pair as stored (the lower above
    its range, the upper below its range): the lower can come down and the upper go
    up, and no edit stores such a pair.
  - The pair and every curve temperature form the `fan-temperature` ordering group,
    so a pair and point 1 can move past the stored values in one edit (for example,
    point 1 and the upper raised together). No pair is copied to another channel or
    curve. An edit leaves the flag byte, byte 46, the curves and every other byte as
    they are.
  - The fields are editable only where the entry's block passes the validator (word 44
    nonzero, dword 38 >= dword 34 and word 42 nonzero), and read-only otherwise. On
    GB20x they do not depend on `fan_zero_rpm`: they stay editable with the bits clear
    or mixed.
  - On Ada and Ampere a pair is editable where the entry stores a block the validator
    accepts and `fan_zero_rpm` is offered on the image, whatever the bits, so an
    upper can be lowered in the same edit that turns zero RPM on (an RTX 3090:
    55 °C above point 1 at 51.90625 °C; an RTX 3060 Ti: 60 °C above 43 °C). Where
    `fan_zero_rpm` is read-only (the RTX A2000, and the RTX 3060 and the RTX 3090
    blower image with mixed bits) the pairs are read-only too. Writes go to every
    duplicate image chain.
- **Start temperature rule.** With zero RPM on, the upper (start) temperature of an
  enabled entry may be at most point 1 of the same entry's fan curve, so idle fans
  never stay stopped past the temperature where their curve starts them. `edit`
  checks it on the result against the source, on GB20x, Ada and Ampere, for every
  enabled entry with both bits set after the edit, whatever wrote the bytes: an upper,
  point 1, `fan_zero_rpm` turning the bits on (with or without a template) or an
  import. An entry that GSP-RM ran in the source (an active channel's entry or an
  enabled curve past them) with both bits set, and whose upper and point 1 are
  unchanged, is exempt, so stock images that ship the upper above point 1 keep every
  other edit: three RTX 4090 partner images (70 °C over 60 °C) and an MSI RTX 3090
  (60 °C over 59 °C). Their point 1 moves only with the upper brought down to it, and
  a copy of them saved with zero RPM off turns it on again only with the upper
  lowered, since nothing stored exempts it any more.
  - A refusal is `ZERO_RPM_ABOVE_CURVE`; the message names the upper and point 1 of
    each entry, their values and the highest allowed upper, and `details.field` is the
    field to change, with the range it may take in this edit in `details.bounds`: the
    upper where it is editable and the request moves it or turns zero RPM on (an RTX
    3090 turned on alone names `fan_1_zero_rpm_high_temp_c`, at most 51.90625 °C),
    point 1 where the upper stays (a GeForce point 1 lowered under its upper; where no
    field edits the upper, as on the RTX 3050 6GB, the message also names turning
    `fan_zero_rpm` off in the same edit), and `fan_zero_rpm` where the switch brings an
    upper that no field holds: a template's (a template board whose point 1 is under the
    template's upper: point 1 goes back up with the switch, and both can move lower
    together on the saved copy) or a stored pair the editor does not offer (a copy of
    the RTX 3050 6GB saved with zero RPM off and point 1 lowered: point 1 goes back up
    to 55 °C with the switch, or zero RPM stays off).
  - Where the lower of such an entry is at or above point 1, the message also says to
    set the lower below the new upper in the same edit, `details.joint_fields` lists
    the lower, and the upper's range starts at 0.0625 °C: turning zero RPM on with an
    RTX 3080's extra curves at 95 and 97 °C and their lowers below, or the GA106 RTX 3050's
    uppers at 43 °C with their lowers below, passes. The window marks the lower too.
  - Entries the firmware does not run (disabled channel entries) are not checked until
    a larger `fan_channels` count enables one with its stored bytes; it is then
    checked like any other entry, and nothing it stores counts as shipped. A count that
    enables such an entry with zero RPM on and its upper above point 1 is refused with
    `details.field` `fan_channels` and `details.channel_count`: `separate-edits` where
    what works is turning zero RPM off, raising the count on that copy and turning zero
    RPM on again with the entry's upper lowered (each in its own edit, the message
    names the field and its value), `none` where that cannot be done and the count
    cannot be raised on that image. On the RTX 3060 8GB, whose stored second channel
    holds 40/60 °C under a 49.90625 °C point 1, a copy with zero RPM on is not raised
    to two channels; with zero RPM off first, or the count raised before zero RPM is
    turned on, zero RPM goes on with `fan_2_zero_rpm_high_temp_c` at 49.90625 °C or
    less. The RTX 3060 that mixes 0x13 and 0x07 stores its second channel entry with
    zero RPM on and 61 °C over a 45 °C point 1, and its `fan_zero_rpm` is read-only, so
    its count cannot be raised (`none`). On the RTX 4090 partner images and the MSI
    RTX 3090, a count lowered and raised again with zero RPM on is refused too: the
    entry it enables again is not one GSP-RM ran in the source.
  - Turing has no zero RPM fields and no image sets the bits there, so the rule does
    not apply.
- **Effect.** Setting a higher upper value does not promise that the fans start at
  exactly that temperature: other fan policies, the extra curves and sensors may
  still decide. Hardware-tested on that one RTX 5080 only; not hardware-tested on Ada
  or Ampere.
- **Ada and Ampere.** Their policy tables have the same version (0x20) and 51-byte
  entries as GB20x, and the version byte is what selects the entry parser, both in
  GSP-RM (`gsp_ga10x.bin` is built for GA10x, AD10x and GB20x) and in the Windows
  driver (617.42), which decode bytes 30..33 and 46 the same way. No chip check was
  found above that dispatch, so that these boards run the parser is inferred. In the
  corpus, every GeForce Ada image and most GeForce Ampere images store rising pairs
  with both zero RPM bits set (0x17/0x07): 40/50 to 60/70 °C on the Ada channel
  entries, 38.875-55/55-60 °C on the Ampere ones. The other boards store their pairs
  as listed under the zero RPM field above.
- **Turing.** Its 54-byte entries hold the same block three bytes later (the pair at
  entry bytes 33..36, byte 49 for byte 46, the flags in byte 1), the same validator
  checks it, but every Turing image in the corpus stores zeros and 0xff there with
  the bits clear, so the fan controller never ran it on Turing. No template is
  offered: no Turing image provides a block to copy, and on TU102-TU116 power channel 0
  is not the total board power channel (the TGP row reads channel 9), so byte 46 = 0
  would most likely name another quantity. No zero RPM field is offered. Turing fans
  stop through the curve instead, with the existing fields: 7 of the 18 Turing images
  with fan fields ship that way (the row minimum at 0 RPM and 0 %, point 1 at 0 RPM
  and 0 %, and point 2 between a fraction of a degree and 2 °C above it at the lowest
  running speed). The RTX 2060 SUPER also stores point 1 at 0 RPM but keeps a 10 %
  level floor (30 % at point 1). On the other images with fan fields, one joint edit
  sets it up: `fan_N_min_rpm`, `fan_N_min_pct`, `fan_N_curve_1_rpm` and
  `fan_N_curve_1_pct` to 0, and point 2 at the fan's lowest running speed (the row
  minimum it had, or its own speed where that minimum is already 0) at the temperature
  where the fan should start. The editor accepts that edit on the other 10 images with
  fan fields, the RTX 2060 SUPER among them. The MSI GTX 1650 stores RPM limits of 0,
  so its RPM fields and curve points are read-only and it cannot be set up that way.
  Below point 1 the fans stand still, and they start at point 2, with no hysteresis
  between the two: the same temperature stops and starts them.

## Advanced section: performance controllers and idle power

These fields tune two families of tables: PERF_CF, the controllers that decide how the
driver raises and lowers the GPC, memory and video clocks with load, and LPWR, the
power-saving features that act at idle. They are read on GB20x and, with their own table
layouts, on Ada, Ampere and Turing (see
[Turing, Ampere and Ada](#turing-ampere-and-ada-performance-controllers-and-idle-power)).
Each descriptor carries `section: "advanced"`.
The GUI shows them in their own collapsed section after the Fans card and before the
read-only fields, labelled "Advanced: performance controllers and idle power", in two
cards (clock controllers, idle power saving); they are not opt-in, so the
XOC-style toggle does not hide them. Every field is experimental and none is
hardware-tested. Import from another ROM never copies them: `IMPORT_SECTIONS` stays
`power`, `voltage`, `clocks`, `current` and `fans`. All reader findings below are from
GSP-RM 615.78.08 and need checking again with each new driver.

### Switches and dependent fields (`depends_on`)

A field that only matters while a switch is on carries `depends_on: {"field": <switch
key>, "value": 1}`. `edit` changes it only while that switch is 1, as stored or as
requested in the same edit; otherwise it refuses with `DEPENDENT_FIELD_DISABLED`
(`details` names the `field` and its `depends_on`). Requesting the stored value again is
accepted and changes nothing. Turning a switch off never changes its dependent values:
they stay as stored and apply again when the switch is back on. The GUI greys such rows
out, with the reason, while the switch is off, stored or as a pending change, and puts a
value typed there back to the stored one. A switch that is read-only on an image (see
below) leaves its dependent fields read-only too.

### PERF_CF utilization policy and controllers

On GB20x the controller table (P+0xa8, object 0x60) has version 0x10, a 6-byte header (14 bytes
on the RTX PRO 4000 SFF) and 20 entries of 57 bytes; the policy table (P+0xac, object
0x61) has version 0x10, a 5-byte header and 9 entries of 10 bytes. On the RTX PRO 4000
SFF object 0x60 also covers the 5-byte header of the policy table; no field writes those
bytes, and the editor repairs every object a write touches.

GSP-RM unpacks each controller entry as `3b5d1b2d1b4d1b1d`. For the utilization
controllers (type 1, and its subclass type 5 with the same offsets) bytes 3..6 are the
target and 7..10 the jump threshold, both FXP20.12 fractions (0x1000 = 100 %), byte 19
the clock domain (0 GPC, 2 DRAM, 4 video, inferred from the sensors the controllers read)
and bytes 20 and 21 the increase and decrease hysteresis counts. The validator run at
load requires a target of 1..0x1000, a jump threshold of at most 0x1000 and nonzero
hysteresis counts, and the runtime control handler sets exactly these fields (with the
two gains and one flag bit), so the driver treats them as tunables. Each policy entry
is unpacked as `2b2d`: the low nibble of byte 0 must be 1, bit 7 is the policy's active
flag, then a conflict mask and a controller mask; a policy's type comes from its
position, so the order never changes.

| Key | Bytes | Range | Stock on every GB20x image |
| --- | --- | --- | --- |
| `perf_cf_util_policy` | bit 7 of policy entry 0 | 1 on, 0 off | 1 (0x81), controllers 0, 1, 2 and 13 |
| `perf_cf_gpc/dram/vid_target_pct` | controller 0/1/2, bytes 3..6 | 10 % up to the jump threshold - 1 % | 40 / 52 / 65 % |
| `perf_cf_gpc/dram/vid_jump_pct` | bytes 7..10 | the target + 1 % up to 100 % | 75 / 64 / 85 % |
| `perf_cf_gpc/dram/vid_hysteresis_down` | byte 21 | 0.5x..4x stock: 5..36, 2..16, 5..36 | 9 / 4 / 9 |
| `perf_cf_gpc/dram/vid_hysteresis_up` | byte 20 | 1..4 | 1 |

- **Percent.** The fractions are shown in whole percent (raw / 40.96, rounded). A
  percent left unchanged keeps its stored fraction. Some stock fractions are truncated
  rather than the nearest ones, so going back to a stock percent stores the stock
  fraction. On GB20x that is each field's stock percent (the stock DRAM target 0x851 is
  51.98 %, not 0x852 for 52 %). Turing, Ampere and Ada store 55, 58, 60 and 80 % as
  0x8cc, 0x947, 0x999 and 0xccc, and since their stock percents vary per product, a
  request for one of these percents (or 52 %, as 0x851) stores that fraction on any
  controller. Any other percent stores its nearest fraction.
  The firmware accepts at most 100 %, so 100 % is the ceiling here rather than a
  multiple of stock.
- **Target and jump threshold together.** They form one ordering group per controller:
  alone, each moves only as far as the other allows; requested together they may cross
  the stored values, and the result must keep the target below the jump threshold
  (`OUT_OF_BOUNDS` otherwise).
- **Gates.** Policy entry 0 must be the reviewed utilization policy (type nibble 1,
  controllers 0, 1 and 2 in its mask), else every PERF_CF field is read-only.
  Controllers 0..2 must be type 1 or 5 with their clock domain, a target below the
  jump threshold in whole percent and nonzero hysteresis counts, else that
  controller's fields are read-only. Every other byte of objects 0x60 and 0x61 stays as
  stored, whatever the field registry: the gains, flags, indices, sampling multipliers,
  the header, controllers 3..19 (including the type 3 and type 8 ones), the other
  policies, every mask and the policy order. The controller fields depend on
  `perf_cf_util_policy` (see above).
- **Expected effect (inferred).** A lower target raises the clock sooner at partial load
  (more power and heat), a higher one keeps it lower; above the jump threshold the clock
  is expected to jump up at once instead of in steps; the decrease hysteresis is how
  long the load stays below the target before the clock steps down (a high count keeps
  the clocks up longer, a low one drops them sooner and may stutter), the increase
  hysteresis the same before stepping up. With the policy off the driver probably stops
  scaling these clocks with load.
- **Not proven.** GSP-RM skips the VBIOS controllers when a per-chip flag is set, and
  what sets it on GB20x was not traced: if it is set, these fields do nothing. The
  cheapest check is on a card that is not in production use: GPC target 40 % to 90 %
  with the jump threshold at 95 %, then compare the GPC clock at light load (for
  example with `nvidia-smi dmon`) against stock, and check the kernel log for GSP errors
  at load.

### LPWR idle power switches and idle times

The GB20x tables:

| Key | Table (BIT P offset, object, header, entry size, enable word) | Entries the switch covers in the corpus |
| --- | --- | --- |
| `lpwr_gr_power_gating` | P+0x80, 0x39, 10, 5, u32 | 0..1; 0..2 on the RTX 5080, RTX 5070 Ti, RTX PRO 4000 SFF and the notebook |
| `lpwr_mscg` (memory system clock gating) | P+0x84, 0x3a, 7, 16, u32 | 0..2; 0..1 on the RTX PRO 6000 Workstation, RTX 5070 and RTX 5060 Ti |
| `lpwr_nvdec_gating`, `lpwr_nvenc_gating`, `lpwr_ofa_gating`, `lpwr_nvjpg_gating` | P+0x11c, 0x120, 0x124, 0x128; 0xb4..0xb7; 10, 2, u16 | all five |
| `lpwr_difr` | P+0xe8, 0x8e, 11, 18, u32 | entry 0 |
| `lpwr_gr_rail_gating` | P+0xd4, 0x7e, 12, 1, u8 | RTX PRO 4000 SFF entry 0, RTX 5080 and 5090 Laptop GPU entries 0..2; no other image enables it |

GSP-RM's LPWR initialization checks each table version (0x10) and parses every entry;
an entry whose bit 0 is clear is skipped, for each of these features.

- **Values.** 1 is Stock, 0 is Off. Off clears bit 0 of every entry the switch covers
  and Stock sets it again; no other bit or entry changes, so Off and back is
  byte-identical. A switch covers the entries the image enables in stock: for GR power
  gating and MSCG every entry whose value without bit 0 differs from the disabled-entry
  value of the corpus (0xfffffe00 and 0xfffff000), for the video engines every entry,
  for DIFR entry 0 when it is not the disabled value 0xfffff800. A switched-off entry
  keeps its other bits, so a ROM saved with Off still shows which entries Stock turns
  back on. Covered entries that are partly enabled leave the switch read-only. GR power
  gating, MSCG and DIFR never cover an entry that holds the disabled value, so they never
  enable one. One limit: the video engine switches cover every entry, so a ROM whose
  NVDEC, NVENC, OFA or NVJPG entries all ship disabled reads as Off, and Stock then
  enables them; no corpus image ships like that.
- **GR rail gating.** Disabled entries store 0xfc, but the GeForce desktops store 0xfe
  on entry 0 (RTX 5090) or entries 0..1 (RTX 5080, 5070 Ti), the same byte a
  switched-off enabled entry stores, so the bytes cannot tell those apart. On the
  products whose stock entries are reviewed (PCI device 2c33: entry 0; 2c59 and 2c18,
  whose GR rail gating tables are byte-identical: entries 0..2) the switch covers those
  entries, also in a copy saved with Off, and only while they store 0xff or 0xfe. Each
  laptop rests on one image, so an image of either that ships entries 0..2 as 0xfe would
  read as Off, and Stock would enable them. On any
  other product it covers the entries the image enables (bit 0 set), offered only while
  each of them stores 0xff; its descriptor carries `lpwr_coverage: "enabled-entries"`
  and its state is always Stock. Off clears bit 0 of exactly those entries, so the Off
  copy enables none and shows no switch (nor its idle time): an entry shipped disabled
  looks the same, so Stock there could enable an entry the vendor ships disabled. Keep
  the original ROM to go back. An image that enables no entry has no switch, and an
  enabled entry with another value leaves it read-only. Forcing GR rail gating on is not
  offered. On every corpus image this rule gives the same switches as the reviewed list.
- **Idle times.** Absolute values in their units, from 0.5x to 4x the stock value, and
  editable only while their switch is Stock (`depends_on`). GSP-RM copies them without
  conditions into the idle thresholds of their controllers, which become counter cycles
  as frequency x time / 1e6, so their unit is most likely microseconds (inferred).

| Key | Stored at | Shown as | Stock | Range |
| --- | --- | --- | --- | --- |
| `lpwr_difr_dfpr_idle_ms` | DIFR header +5, u16; the driver multiplies it by 1000 | ms | 1000 | 500..4000 |
| `lpwr_difr_sw_asr_idle_us` | DIFR header +7, u16 | µs | 15 | 8..60 |
| `lpwr_difr_cg_idle_us` | DIFR header +9, u16 (clock gating) | µs | 15 | 8..60 |
| `lpwr_gr_rail_gating_idle_us` | GR rail gating header +5, u16 times 10 | µs, steps of 10 | 500 | 250..2000 |

- **Guards.** Each LPWR object changes only at the bytes of the canonical bindings,
  whatever the field registry: sub-feature bits, rail masks, the other header bytes and
  every disabled entry stay as stored.
- **Expected effect (inferred).** These features engage at idle or light load; which
  LPWR entry each performance state uses was read from an older table layout, so that
  full load is unaffected is inferred too. Off keeps the feature from engaging (a little
  more idle power; it may avoid idle stutter or flicker, DIFR in particular on a static
  desktop). Shorter idle times save more power but can cause stutter or, rarely, a black
  screen at idle. Removing the override restores stock.

### Turing, Ampere and Ada: performance controllers and idle power

The same keys, ranges, switches, dependencies and guards as on GB20x, read from the
layouts these families store. Each table changes only at the bytes of the canonical
bindings, in every duplicate chain, and the additive checksum of each touched image is
repaired; the tables join the edited-table list of the checksum tail check
(`ADA_EDITED_TABLES`, `TURING_EDITED_TABLES`). They sit in the same data image as the
power table on every image of the corpus (25 Turing, 38 Ampere and 25 Ada images), so
no image loses or gains editability.

- **PERF_CF tables.** The controller table has a 6-byte header and 8 or 12 entries of
  24 or 28 bytes (Turing), 24, 32 or 49 bytes (Ampere) or 49 bytes (Ada); the policy
  table is the GB20x one (8 or 9 entries). GSP-RM (`gsp_tu10x.bin` for Turing,
  `gsp_ga10x.bin` for Ampere and Ada) unpacks an entry by its size: 23 bytes as `3b5d`,
  24..27 as `3b5d1b`, 28..31 as `3b5d1b1d`, 32..40 as `3b5d1b2d`, 41..53 as
  `3b5d1b2d1b2d`, so the target, jump threshold, clock domain and hysteresis bytes are
  where they are on GB20x, and the same utilization decoder and load validator read
  them. Other entry sizes are not read (the section reports an unsupported layout).
- **Clock domain by row.** Byte 19 names a row of the clocks table (C+8). On every
  image of these families controllers 0, 1 and 2 name rows 0, 2 and 5, the GPC, DRAM
  and VID rows of the GV HAL order (GB20x stores 0, 2 and 4: its VID row is 4). A
  controller is recognized only when the row it names has its domain's name, so the
  video controller is found by its row, not by a fixed byte value; a clocks table the
  editor does not read leaves the controllers read-only.
- **Stock values.** Policy 0 is active and runs controllers 0..2 on every image, with
  increase hysteresis 1 and decrease hysteresis 9, 4 and 9 as on GB20x. The targets and
  jump thresholds vary per product: GPC 40 % with 55 to 75 %, DRAM 40 to 65 % with 55 to
  80 %, VID 60 to 75 % with 80 to 90 % (every Ada image: 40/75, 65/80 and 65/85 %).
  Their descriptors carry no `stock` value.
- **Not proven.** As on GB20x: whether a per-chip flag makes GSP-RM skip the VBIOS
  controllers on these chips was not traced.

| Key | Table (BIT P offset, header, entry size, enable word) | Families | Entries the switch covers in the corpus |
| --- | --- | --- | --- |
| `lpwr_gr_power_gating` | P+0x80, 10, 5, u32 | all three | Turing 0, 1, 4 (TU102/TU104/TU106 desktops) or 0, 1, 3, 4 (their laptop chips, TU116, TU117); Ampere 0..1 or 0, 1, 3 (0 on one image); Ada 0..2 |
| `lpwr_mscg` | P+0x84, 7, 15, u32 | all three | 0..1 (0 on one Ampere image) |
| `lpwr_gr_rail_gating` | P+0xd4, 9, 1, u8 | Ampere, Ada | GA102 RTX 3080, 3080 Ti, 3090 and RTX A4500, A5000, A5500, A6000 entries 0..1, A40 entry 0; no other image enables it (no Ada image) |
| `lpwr_difr` | P+0xe8, 11, 17, u32 | Ada | entry 0 on 14 of the 25 images |

GSP-RM reads 15-byte MSCG entries as `1d2w1b3w`, a 9-byte GR rail gating header as
`5b2w` and 17-byte DIFR entries as `1d1b6w` (GB20x: 16, 12 and 18 bytes), checks the
version and at most 5 entries, and skips every entry whose bit 0 is clear;
`gsp_tu10x.bin` reads GR power gating and MSCG the same way. The Turing token ends
before the GR rail gating and DIFR pointers, the Ampere one before DIFR; no image has
the video engine tables.

- **Which entries a switch covers.** On Ampere and Ada a stock-disabled GR power gating
  entry stores 0xffffff80 or 0xffffffc0 and a disabled MSCG entry 0xfffffc00, values no
  enabled entry stores with bit 0 cleared, so the GB20x rule applies with these values.
  Elsewhere a stock-disabled entry stores exactly what an enabled one stores switched
  off: GR rail gating 0xfe, Ada DIFR 0xfffffffe or 0xffffffee, Turing GR power gating
  0xffffffe6 and MSCG 0xffffffec. There, as for GR rail gating on GB20x, a reviewed
  product's switch covers the entries it enables in stock (PCI devices listed by the
  editor), while each covered entry stores one of the reviewed values with or without
  bit 0. On any other product the switch covers the entries the image enables, while each
  of them stores one of those values (`lpwr_coverage: "enabled-entries"`, always Stock):
  its Off copy enables none and shows neither the switch nor its idle times, and an
  image that enables none has no switch. On every corpus image this gives the same
  switches as the reviewed list. It applies only to the tables named here: no corpus
  image has DIFR on Ampere, or GR rail gating or DIFR on Turing, and such a table with an
  enabled entry stays read-only.
- **Two RTX 4090 images** (factory-OC boards) store GR power gating entry 2 like an
  enabled entry switched off: their switch is read-only, since its entries disagree.
- **Idle times.** The DIFR words (header +5, +7, +9: 1000, 15 and 15 on every Ada image)
  and the GR rail gating word (header +5, times 10) are the GB20x fields: the same parser
  code reads them. The GR rail gating word stores 500 on every Ampere and Ada image
  (5000 µs, ten times the GB20x value), so its range is 2500..20000 µs; it is listed
  where the switch is (Ampere). The GR power gating and MSCG idle times are left out for
  the GB20x reason (copied only when an LPWR state flag is set).

### Left out on purpose

- **CLFC.** The real CLFC table (C+0x18, object 0x63) stores 20 type-0 (disabled)
  entries on every GB20x image, holding only templates, so there is nothing to tune.
  The table at P+0x104 (object 0xa7) is not CLFC: it holds only IDs, equation indices
  and masks, and GSP-RM copies it unchanged into a bundle for another firmware.
- **Kept read-only or not exposed.** The PERF_CF gains, sampling multipliers and flag
  bits, the type 3 and type 8 controllers, the other policies (GSP-RM forces some of
  them on or off), every type nibble, index, mask and the table headers; the GR, MSCG and
  video idle times (GSP-RM copies them only when an LPWR state flag is set, and what
  sets it was not traced); the LPWR sub-feature bits and rail masks, the DIFR entries
  1..4, the EI, PCIe (the driver's `RMDisableGpuASPMFlags` registry key covers ASPM), GC6
  and rail tables.

## Ada fields

Every Ada rule is structural and was checked on each parseable image of the Ada
corpus (20 of 21 images; the RTX 4090 Laptop image has no EFI image and is
refused by the image-chain parser). Writes go to the same field in every
duplicate chain, and the additive checksum of each touched image is repaired.
Only the RTX 2000 Ada (10de:28b0, 95.07.47.00.19) runs edited images on the maintainers' Linux machine: its
power ceiling/floor and REL ceiling keep their reviewed status; every other Ada
field, and every field on any other Ada image, is marked experimental. The
RTX 4070 Laptop image (95.06.15) ends its last data image with the empty closing
table and three 0xff bytes instead of the 15-byte padding; that tail is also
accepted as a checksum slot (see `editor-api.md`), so its fields are no longer
all read-only. No loader payload fits an Ada laptop image yet (`normalize` refuses
it with `RELOCATION_DOES_NOT_FIT`), so an edited copy cannot be loaded.

**Power policy table (BIT P+0x2C).** Versions `30/34/5b` and `30/32/53` share
the 0x53-byte entry prefix (the larger variant adds zero bytes). `30/2c/4b` (RTX 4090
VBIOS 95.02.18) holds the first 0x2c header and 0x4b entry bytes of `30/32/53`; its
policy rows are matched as the 0x53 rows they truncate (eight more zero bytes). The TGP row is
header byte 10; notebook headers store `ff ff ff 02` in bytes 10..13 and name
row 2 through the D-notifier index. The TGP row must be class 1 in mW on power
channel 0, which must be the class-2 sum on rail 0xf5 (the total board power
monitor in the Ada and GB20x GET readings). The rated values equal the published
board power of all fifteen desktop and workstation images. Other policies are
identified by their immutable row shape (bytes 0..1 and 14..0x52, range bytes
excluded) and the exact power-channel entry they read:

| Field | Row | Basis |
| --- | --- | --- |
| `slot_power_rated_w`, `slot_power_max_w` | class 4 mW on the slot channel (byte-identical to GB20x slot channel 1) | RTX 2000 Ada GET: policy 5, 66 W, current = rated |
| `slot_current_threshold_rated_ma`, `_max_ma` (opt-in) | class 5 hardware threshold, mA, slot channel | RTX 2000 Ada GET: policy 8, unit mA, 8.25 A, current = rated |
| `input_current_rated_ma`, `_max_ma` (opt-in) | class 5 hardware thresholds 0 and 1, mA, on the 12 V input channel (byte-identical to GB20x channel 9), written together | Structural only (no Ada GET of these rows); editable only while both rows hold the same value |
| `nvvdd_power_threshold_rated_w`, `_max_w` (opt-in) | class 5 mW on the NVVDD output power channel 18 | RTX 2000 Ada GET: policy 16, mW, monitor rail 1, current = rated |
| `nvvdd_output_ocp_max_ma` | class 0 mA on the NVVDD output current channel 19 | Read-only: absent from the RTX 2000 Ada runtime policy list, so enforcement is unproven. On the other Ada images and every Ampere image row 12 names rows 13 and 18 in the policy relationship entries; on the RTX 2000 Ada and RTX 4000 Ada (and SFF) row 12 is class 0 with unused entries, which may be why row 13 is absent there (inferred) |
| `connector_1_power_rated_w`, `_max_w` (opt-in) | class 4 mW with the slot row shape (its channel byte excluded) on a board input that channel 0 adds: a class-5 single input at 12 V on a connector rail (0xda, 0xdb, 0xdc, 0xfa, 0xfb, 0xfc, 0xe4), no parameter but the provider byte 15 (0..2); the auxiliary power connector input | Structural (no Ada GET of these rows); readings from one RTX 4070 with one 8-pin connector are consistent with its 150 W value binding (not hardware-tested) |

Class-5 rows are hardware thresholds: their fields carry
`policy_class: "hardware-threshold"`, are opt-in (shown under **Show advanced
XOC-style fields**) and the GUI labels them "threshold", also for the Ada 12 V
input current (the GB20x type-11 input policy keeps its "limit" labels). The 11
images with the 12 V input rows store 16-45 A rated, about 1.2-1.69 × rated
TGP / 12 V; thresholds 0 and 1 hold equal rated values on all of them, but the
RTX 4500 Ada maxima differ (22000/21000 mA), so only its rated value is editable.
The NVVDD threshold rated value is above the rated TGP on every image (122-650 W;
the RTX 4050 Laptop GPU's 122 W is below its 140 W TGP ceiling).

A field stays read-only when another row of the same class and unit reads the
same power channel (`same_channel_rows` in the descriptor), because that row may
bind instead. Only the RTX 4060 has one: besides row 16 (threshold index 0,
140 W) it stores row 17, a class-5 mW row on channel 18 with parameter byte 0 =
4 and 1/100/100 W minimum/rated/maximum. Which of the two
the firmware enforces is unknown, so both NVVDD threshold values stay read-only
there; raising row 16 alone could leave the 100 W row in force.

Raising the slot power or slot current threshold of a slot-powered board exceeds
the PCIe CEM slot rating. Laptop-only rows and placeholder rows stay unexposed.

**Auxiliary power connector input (opt-in).** A row qualifies by the slot row shape (its
channel byte excluded) on a board input channel: a class-5 single input at 12 V that
channel 0 (the class-2 board total, rail 0xf5) adds with weight 1.0, on rail 0xda, 0xdb,
0xdc, 0xfa, 0xfb, 0xfc or 0xe4, with no parameter but the provider byte 15 (0..2).
Notebook images are left out: their DC input channel holds the same bytes. The images of
seven products have one such row, all on channel 5: 150 W on the RTX 4070 (rail 0xfa),
the RTX 4060 Ti 8 GB and 16 GB and the RTX 4000 Ada (rail 0xda), and 300 W on the RTX
4500 Ada (row 6) and the RTX 5000 and 6000 Ada (row 5; rail 0xda). Rail 0xda is the
auxiliary connector input that the GB20x saved GET identifies (see the GB20x auxiliary
power connector input above), and 0xfa is the first connector channel rail of Ampere,
whose rows there hold 150-175 W. The rail does not name the connector type: the 8-pin
RTX 4060 Ti and the 16-pin boards both use 0xda. The RTX 4090, 4080, 4080 SUPER, 4070 Ti
SUPER and 4070 SUPER images read their connector channel only with class-0 rows of
unknown meaning, so they get no field; the RTX 4070 also keeps its class-0 mA row 8
(58 A rated, 75 A maximum) on that channel. The fields follow the other Ada policy rows:
the keys and numbering of the Ampere connector channels (`connector_1_*`, then
`connector_2_*` on an image with a second such row), every duplicate chain written,
read-only while another class-4 mW row reads the same channel or a class-4 mW row of
another shape reads another connector input channel, and the cable sense profiles
handled as for the TGP (a top-level profile entry on this row is written with it,
lower-level entries bound it). The ceiling goes from the rated value up to the encoding
maximum and the rated value up to the ceiling.

On a board with one 8-pin connector this row most likely holds the connector at 150 W
even with a higher board power limit: readings from one RTX 4070 with its board limit
raised to 240 W, stopped at about 195-198 W with 142.6 W on the 8-pin input, are
consistent with it (95.3 % in its normalized power reading, close to 142.6 / 150 =
95.1 %; not hardware-tested). The ROM does not store the connector type: a PCIe 8-pin
connector is rated 150 W and a 12V-2x6 cable for the level its sense pins report. Going
past what the connector and its cable are rated for puts the cable, the connector and
the power supply at risk; that is the user's call. The board power limit and, where the
image stores them, the slot limit and the 12 V input current thresholds (20 A on the
RTX 4070, about 240 W at 12 V) still apply and may bind next; the RTX 5000 and 6000 Ada
store no slot row. The RTX 4000 Ada has no 12 V input current rows but keeps a class-5
mA hardware threshold on the connector channel itself (row 9, 12.34 A, about 148 W at
12 V). It has no field, the descriptor lists it in `threshold_rows` and the GUI notes it:
it probably holds the connector near 148 W whatever the connector power limit. Nothing
here is hardware-tested. To raise the connector limit of an RTX 4070 to 200 W (above the
150 W rating of an 8-pin connector) together with a 240 W board limit and a 25 A input
current threshold:

```sh
./nvbios edit original.rom modified.rom --set power_max_w=240 --set power_default_w=240 \
  --set connector_1_power_max_w=200 --set connector_1_power_rated_w=200 \
  --set input_current_max_ma=25000 --set input_current_rated_ma=25000
```

**Override profiles picked by the cable sense pins (P+0xF4, experimental).** One Ada
image, an MSI RTX 4090 (95.02.3C.40.EA), stores override profiles; every other Ada
image of the corpus keeps them empty. The table has the GB20x layout, and GSP-RM 615.78.08
parses it with the same code for Ada and GB20x. A profile entry names a power row
and a limit (0 maximum, 1 rated). Static analysis shows that the selected entry
replaces that row's value instead of clamping it: the firmware applies it with the
same client it uses for the row value. The editor accepts exactly this selection
chain:

| Part | Stored | Meaning |
| --- | --- | --- |
| Selection row 0 | `01 08 00 00 00`, codes 0..3 | Reads two sense inputs into a code and votes that code's value: 0 and 1 vote nothing, 2 votes 450 W, 3 votes 520 W |
| Selection row 1 | `02 00 00 00 00`, thresholds 150/300/450/520 W | The vote selects the profile of the last threshold at or below it: profiles 4, 5, 6 and 7 |
| Rows 2 and 3 | off | |
| Profiles 4 and 5 | TGP maximum 150 W and 300 W | Not reached by any code |
| Profile 6 (code 2) | TGP 450 W maximum and rated, 12 V input thresholds rated 45 A | The 450 W level |
| Profile 7 (code 3) | TGP 520 W maximum, 480 W rated | Equal to the base row 2 |

Code 3 is read with both sense inputs asserted. That it is the 600 W state of a
12V-2x6 cable is inferred from the RTX PRO 6000 Max-Q images, which map codes 0..3
to 150/300/450/600 W; it was not measured. With codes 0 and 1 no profile gets a vote
and the firmware fails the power setup (static reading, not tested). The DCB GPIO
functions 0xee/0xed of this image also appear on a GB202 image without selection
rows, so they do not identify the sense inputs by themselves.

Because a selected profile replaces the base value, raising only the base would
most likely be undone at the top level (static reading, not tested). So
`power_max_w` and `power_default_w` write the base TGP row and the matching entry of
the top-level profile together, in both chains. The other profiles keep their values
and set the bounds: the ceiling stays at or above every other profile value on the
row (480 W, the rated value, on this image), the rated value at or above their
rated values (450 W), and `power_min_w` at or below all of them. A profile that no
sense code selects (profiles 4 and 5 here) counts with twice its value as an upper
bound and half as a lower one, so profile 4's 150 W lets the floor go up to 300 W;
profile 6, selected at code 2, counts with its own values. The 12 V
input current fields follow the same rule: profile 6 holds only their rated value (45 A), so
both the rated value and the ceiling stay at or above it.
`power_max_w` keeps no upper bound but the encoding. Its reason, and notes in the
GUI, say that the top level is most likely a 600 W cable, that going past 600 W is
the user's call, and that the 12 V input current thresholds (rated 48 A, about
576 W at 12 V) may limit first, so `input_current_rated_ma` (opt-in) should be raised
with it. Descriptors carry `override_profiles` (top profile, its sense code, the
inferred 600 W level and the other profiles) and an evidence entry of kind
`firmware-static-analysis`.

Anything else keeps the power fields hidden (the Power card then says some fields
are not shown) and the slot, 12 V input and NVVDD threshold fields read-only: other
selection headers (such as the presence gate bit), a used row 2 or 3, codes other
than 0..3, a threshold param other than 0xff, thresholds out of order or naming a
disabled profile, a profile entry with field 2 (minimum) or a malformed or
duplicate entry, and a top-level profile that differs from the base table. A lower
profile entry outside the stored range of its base row (below the floor, above the
ceiling, or a rated entry above the rated value) also hides the power fields, or
keeps that policy's fields read-only, because the stored value could not be requested
again within the bounds. No image of the corpus has one.

**Voltage (rail P+0x68, VFE P+0x20).** One V20 logic rail (NVVDD). Row selectors
are u8: REL +4, ALT +5, OV +6 and VMIN +11 (0xff = absent); the RTX 2000 Ada runtime
INFO selectors REL 2, ALT absent, OV 4 and VMIN 3 equal those bytes. Every
parseable image keeps REL < ALT < VMIN = OV - 1, as the GET-reviewed GB20x rows,
and the rule is required; the only other order accepted is the follow-OV result
(REL = OV, ALT absent or = OV). The VFE equation count is the u16 at header bytes 5/10
and equation links are u16 (bytes 2 and 24). A ceiling edit is offered only for a
REL or ALT equation of the hardware-tested REL shape: float quadratic in uV on a
sensed-temperature variable, nonzero slope, no link and no reference from another
equation. Read-only kinds carry `equation_kind`:

| Kind | Images | Why read-only |
| --- | --- | --- |
| `constant` | every OV; REL of the RTX 4090, 4080 and RTX 4000 Ada; ALT of 4090, 4080, 4080 SUPER, 4070 Ti SUPER, 4060 | A ceiling-only edit keeps the evaluated value; a constant REL or ALT takes a fixed value instead (see [Fixed REL and ALT values](#fixed-rel-and-alt-values-nvvdd_rel_fixed_mv-nvvdd_alt_fixed_mv)) |
| `compare` | REL of the 4070 Ti SUPER, 4060 Ti, 4060 and laptops | The value comes from child terms on fused (speedo) inputs |
| `fixed-point` | every VMIN slot (byte 11) | Output scale unverified; the selector is shown. It is the rail INFO VMIN slot, not the evaluated VMIN: changing it did not move the driver VMIN (see [Evaluated VMIN](#evaluated-vmin-nvvdd_vmin_mv-msvdd_vmin_mv)) |

**Clocks (BIT C+8).** Version 0x40 with header `40 0d 0f 0a 03 01 03 e8 03` (GV HAL,
one rail), ten 18-byte rows ending at the C+0x20 table. Rows are named by their
nvgpu GV HAL position (GPC, XBAR, DRAM, SYS, HUB, VID = NVD, PWR, DISP, PCIEGEN,
HOST) after per-row gates (usage, ordering byte, rail sub-entry type and fixed
bytes); programming indices are not used for names, so the shifted indices of the
RTX 4080 Laptop image keep their names. Fields mirror GB20x: GPC MHz = table
(NVML), memory MHz = 2 × table (NVML; `dram_*_table_mhz` are table MHz), XBAR/SYS/VID
in table MHz. The RTX 2000 Ada booted a GPC ceiling of 1500 and a memory floor of
-5000 MHz as reported NVML ranges; applied offsets were not tested, so the clock
fields stay experimental. HUB, PWR, DISP, PCIEGEN and HOST stay unexposed.

**Fans (P+0x58, 0x5C, 0x64, 0xDC, 0xE0).** The GB20x table set with a 6-byte cooler
header and two entries per table. An Ada channel is stored when its mapping,
control (byte 5 = channel 0's flags with its own channel bit) and speed entries
name it and its policy byte 1 equals channel 0's. `fan_pwm_frequency_hz` is offered
on the 15 desktop and workstation images with GPU-driven fans; `fan_channels` is editable on
7 of the 8 two-channel images (not the RTX 4080 Super, below). Laptop images list no
channel and get no fan field. Fan bytes are guarded in both chains. Channel limits and
curve points follow the GB20x rules, with enabled extra curves in policy entry 2 (and 3
on most images), and are written to both chains. Every active channel gets editable speed and level limits,
and every curve point is editable, except on the RTX 4080 Super: its second channel's
3000 RPM maximum is below the extra curves' 3200 RPM, so that maximum and the extra
curves' top speeds are read-only (out of shape), and so is the channel count (one
channel could not be raised back to two). `fan_zero_rpm` and the zero RPM pairs are
offered as described under [Zero RPM](#zero-rpm-fan_zero_rpm-opt-in): on every GeForce
image (on), the RTX 4000, 4000 SFF, 4500 and 2000 Ada (off, flag bits alone) and the RTX
5000 and 6000 Ada (off, with a reviewed template).

**Thermal policy table (P+0x50) and factory clock record (P+0x98).** Both sit in the
data image of the power and fan tables and are written in both chains. See [Maximum
operating temperature](#maximum-operating-temperature-max_operating_temp_c) and [Factory
GPC and memory offsets](#factory-gpc-and-memory-offsets-factory_gpc_offset_mhz-factory_memory_offset_mhz-and-rated-boost-factory_rated_boost_mhz).

`ada-relocated-v2` compares `power_rows`, `clock_ranges`, `rail_limits`,
`rail_equations` and `fan_coolers` between the source and the relocated payload.

## Ampere fields

Ampere GA102-GA107 images use the Ada table set with narrower rows. Every rule
below is structural and was checked on the 35 images of the Ampere corpus (desktop,
workstation, datacenter and laptop); all are recognized. No Ampere board runs on
the maintainers' Linux machine, so **every Ampere field is experimental** and none
has a runtime reading there. An RTX A2000 took an edited power floor through the
Windows loader. An RTX 3050 6GB Laptop GPU (75 W HP BIOS) took a 70 W ceiling and a
55 W boot default the same way, and the driver reported a 70 W limit. On the same
laptop a 95 W ceiling with an 80 W boot default let it draw above its stock 75 W (about
92 W at most in a monitoring tool); on an RTX 3050 Ti Laptop GPU (stock 55 W) the same
kind of raise gained only a few watts, likely because of its low NVVDD output current
row (45 A; the 80 W image of the same GPU stores 90 A; see [NVVDD output current limit](#ampere-nvvdd-output-current-limit-nvvdd_output_ocp_rated_ma-nvvdd_output_ocp_max_ma-opt-in)).
Writes go to every duplicate chain and repair the additive checksum of each touched image.

**Image chains.** Laptop and headless dumps (A40, RTX 3070/3060/3050 Ti/3050
Laptop) have no EFI image: the legacy image is marked last and the data images
follow it, and table pointers then need no EFI offset. GA102, GA104 and GA106 data
images all carry NPDS ID `0x2200` (GA103 `0x2400`, GA107 `0x2580`), so an Ampere
data image may carry its own chip ID or `0x2200`, and every data image of a chain
the same ID. Ada keeps requiring the EFI image. `10de:2501` (RTX 3060, PG190 SKU 50)
is not in NVIDIA's product table; the editor recognizes it from pci.ids
(`EDITOR_ONLY` in `families.py`, evidence kind `pci-ids-entry`), while the loader
and enrollment keep it out of scope. The RTX 3050 6GB (94.07.91) and RTX 3060
Laptop (94.06.22) images end their last data image with the empty closing table
and two or no 0xff bytes instead of the 15-byte padding; that tail is also
accepted as a checksum slot (see `editor-api.md`), so their fields are no longer
all read-only.

**Power policy table (P+0x2C).** `30/2c/47`, `30/2c/43` (RTX 3080 2206: the same
bytes 0..0x42) and `30/32/47` (six more header bytes). The TGP row (row 2 on every
image) follows the Ada rule, including the notebook header and the class-2 sum on
rail 0xf5 behind channel 0. Power channel entries are 22 or 26 bytes (the last
four zero). Other rows are identified by class, unit and the channel they read;
a single input channel is class 5 at 12 V with no parameter but its provider
byte 15:

| Field | Row | Notes |
| --- | --- | --- |
| `slot_power_rated_w`, `_max_w` | class 4 mW on the slot channel (byte-identical to the Ada one) | Row 5, 66 W rated |
| `connector_N_power_rated_w`, `_max_w` | class 4 mW on a connector channel, rails 0xfa, 0xfb, 0xfc, 0xe4 | One per connector sense channel, numbered in row order; 150-175 W or 75-87.5 W rated. The PCIe CEM 8-pin (150 W) and 6-pin (75 W) ratings are a hint, not an identity: one physical connector can span several channels (RTX A6000 and A40 EPS 8-pin: two at 150 W; RTX 3090 Ti 16-pin: three at 162 W) |
| `connector_sum_power_rated_w`, `_max_w` | class 4 mW on a class-2 channel with the 12 V bytes of a connector channel that adds only connector channels, at least two, each with weight 1.0 | Only where exactly one such row exists: row 11 of two RTX 3080 Ti images (300 W rated / 350 W maximum over two connector channels; 450 W over three) and of the RTX A6000 (280 W over two) |
| `slot_current_threshold_rated_ma`, `_max_ma` (opt-in) | class 5 mA on the slot channel | Hardware threshold, as on Ada |
| `input_current_rated_ma`, `_max_ma` (opt-in) | class 5 mA on the 12 V input channel, rail 0xe0 | Every such row written together (two on the RTX 3090 Ti) |
| `connector_N_current_threshold_rated_ma`, `_max_ma` (opt-in) | class 5 mA on the channel of connector N | Rows 9 and 10 (threshold index 1 and 2 in parameter byte 0); 13-22.75 A rated, 13-32 A maximum; a field only where the channel carries one connector power row and one such row (none on the 3-connector RTX 3080 Ti channel 7, the RTX 3070 0xfc channel and the laptops) |
| `nvvdd_output_ocp_rated_ma`, `_max_ma` (opt-in) | 13: class 0 mA on the NVVDD output current channel 19 (class 1, rail 1, sensor byte 14 = 6), the lowest such row | 54-445 A rated on the 40 corpus images (45 A on the reported RTX 3050 Ti Laptop image); values stay below 5001 A; see [NVVDD output current limit](#ampere-nvvdd-output-current-limit-nvvdd_output_ocp_rated_ma-nvvdd_output_ocp_max_ma-opt-in) |

With the slot policy, the connector-channel policies probably cap the board power
below a TGP raised past their sum (inferred, untested). A class-2 power channel sums
the channels its relationship entries name (bytes 14..15 give the first and last
entry; the 46- or 31-byte relationship table follows the channel entries, header
bytes 4/5). Each entry a sum names holds 1 in byte 0, a channel index in byte 1 and
a signed weight in bytes 2..5, read as 20.12 fixed point (inferred): 0x1000 (1.0)
on most entries, 0xfffff000 (-1.0) on the others (channel 12 subtracts channel 11
on most images).
A class-4 mW row on a sum that adds a connector channel is listed in that field's
`summed_cap_rows` and reason, and may bind before the per-channel limits: one
RTX 3080 Ti image caps channels 5-6 at 300 W rated, 350 W maximum (2 x 162 W =
324 W rated), another channels 5-7 at 450 W (3 x 162 W = 486 W), and the RTX A6000
channels 5-6 at 280 W (2 x 150 W = 300 W), so raising a connector channel alone
may have no effect there. Where the sum adds only connector channels, at least two,
each with weight 1.0, its channel holds the 12 V bytes of a connector channel and no
other parameter (channel 1 of the three-connector RTX 3080 Ti adds channels 6 and 7
but holds 0x11c7 in bytes 6..7), and exactly one row reads it, that row is the
`connector_sum_power_*_w` field, and the connector reasons and the GUI connector
rows name it; any other sum row stays without a field. The same-channel rule of
Ada applies, and rows must keep minimum <= rated <= maximum.
Not exposed: the two rows on the NVVDD
power channel (12.5-250 W, mostly class 5; some above the TGP, as on the GA103
RTX 3060 Ti and the RTX 3070 Ti Laptop; class 0 on the RTX 3090 Ti, row 16, and
the A2000, row 17; meaning unknown; the NVVDD output current reasons name them),
the MSVDD output-current row of the two-rail boards and the laptop rows.

### Ampere NVVDD output current limit (`nvvdd_output_ocp_rated_ma`, `nvvdd_output_ocp_max_ma`, opt-in)

Row 13 is a class-0 mA row on the NVVDD output current channel 19 on every Ampere
image examined (54-445 A rated on the 40 corpus images; the reported RTX 3050 Ti Laptop
image below stores 45 A, the lowest seen). The field takes the lowest class-0 mA row on
the NVVDD output current channel (channel bytes 0..1 = `01 01`, sensor byte 14 = 6)
whose maximum is below 5001 A, which is row 13 on all 40 Ampere images examined (the
corpus grew after the 35-image checks above). Its ceiling goes from the stored rated
value up to 5000.999 A and its rated value from the stored minimum up to the ceiling;
both form the ordering group `nvvdd-output-ocp`. The ceiling can be raised alone; a
rated value above the stored ceiling needs the ceiling raised in the same edit (for
example `--set nvvdd_output_ocp_max_ma=90000 --set nvvdd_output_ocp_rated_ma=90000`,
the value of the 80 W image below; the GUI takes amps). The edit writes the rated value
and the maximum of row 13 in every duplicate chain, keeps its minimum and repairs the
image checksums. Both fields are experimental, opt-in (**Show advanced XOC-style
fields**) and not hardware-tested: whether the firmware enforces the row is unproven on
Ampere. It likely protects the core VRM, which was sized for the stock value, so the
stored number is a policy value, not a hardware-safe VRM rating.

On every Ampere image row 12 (class 1 mA, 5001 A, on channel 19 or, on GA102, on the
sum channel 17) names rows 13 and 18 in the relationship entries of the power policy
table, which suggests a combined policy over them (inferred). On the RTX 2000 Ada, RTX
4000 Ada and RTX 4000 Ada SFF row 12 is class 0 and names unused entries, which may be
why row 13 is absent from the RTX 2000 Ada runtime list; enforcement stays unproven.

**No-limit rows.** 5001000 stored as both the rated value and the maximum (5001 A or
5001 W) is the value Ampere power rows hold where they set no limit: on the 40 Ampere
images examined, 269 rows hold 5001000, always as both values, 6 or 7 per image (200
class 0/1 mW rows on sum and input channels, 40 class 1 mA rows, 29 class 0 mA rows),
and no other row stores more than 1001000. 29 images store such a class-0 mA row 18
on channel 19 next to row 13. A row of the same class, unit and channel with that
value is listed in `unlimited_rows` and the reason and does not make the field
read-only. Any other row of the same class, unit and channel is a second real limit
and keeps both values read-only (`same_channel_rows`), as does a class-0 mA limit on
another output current channel, because which row binds is unknown and editing one
alone may have no effect; an edit therefore never moves the field to another row.
Values at or above 5001 A are refused: row 13 would no longer be the lowest limit on
its channel, and at 5001 A for both values it would itself read as a no-limit row and
lose its field.

**Rows that may bind first.** Rows 16 and 17 read the other NVVDD channel 18 (sensor
byte 14 = 5; class 5 mW, or class 0 on the RTX 3090 Ti row 16 and the RTX A2000 row
17; meaning unknown). Class 5 is the hardware-threshold class, as for the Ada row of
the same shape (`nvvdd_power_threshold_*_w`), so a trip there would show as a hardware
slowdown rather than a power limit (inferred). The reasons and `other_nvvdd_rows` name
these other rows on an NVVDD channel; they have no field and may bind first.
Same-channel limits and no-limit rows are listed apart (`same_channel_rows`,
`unlimited_rows`). Once row 13 is raised, the reliability voltage ceiling
(`nvvdd_rel_max_mv`, read-only on Ampere) may be the next limit.

**Report behind the field.** On one RTX 3050 Ti Laptop GPU (10de:25a0, 50 W rated /
55 W maximum), a 72-75 W ceiling and a 70 W boot default loaded with the loader still
stopped at about 60-64 W with power limit as the reason, also at low CPU load, while
the same laptop reached 80 W flashed with an 80 W image of the same GPU (on an older
driver). That image stores 90 A in row 13 where the stock image stores 45 A (rows 16
and 17: 28.125/21.5 W against 18.75/12.5 W). At 0.85-0.90 V, 45 A is about 38-41 W of
core power, which fits a 60-64 W board power, so the 45 A row is the likely cap; that
is inferred, not proven. The 80 W image also raises the reliability voltage ceiling
from 900 to 1081.25 mV (read-only here), so after a row 13 raise the GPU may stop at
0.9 V, which is reported as a voltage reason rather than as power. It also stores other
power sensor bytes, so its 80 W reading may not compare 1:1 with the stock image.

**Voltage (P+0x68, P+0x20).** Rail table `20 05 11 01 00` (NVVDD) or `20 05 11 02 01`
(GA102 except the RTX 3090 Ti: NVVDD and MSVDD, the second name inferred from the
clock domains). Rows are the first 17 bytes of the Ada row, with the same
selectors and order rule on every rail. VFE equations are 24 bytes with a u8 count
(header byte 5) and u8 links. REL and OV are `constant` equations on all 35 images
(REL 900-1087.5 mV, OV 1100 mV); ALT is constant (1100 mV) on the 18 desktop
GeForce images and absent (selector 0xff) on the 17 workstation and laptop images.
The REL, ALT and OV ceiling fields are therefore read-only: a ceiling-only edit would
not change the voltage. The opt-in fixed REL and ALT values of each rail write the
constant itself (see [Fixed REL and ALT values](#fixed-rel-and-alt-values-nvvdd_rel_fixed_mv-nvvdd_alt_fixed_mv)),
and the opt-in NVVDD follow-OV switch and flat value move REL and ALT to OV and set
it (see [REL and ALT follow OV](#rel-and-alt-follow-ov-nvvdd_rel_alt_follow_ov-opt-in)).

**Clocks (C+8).** Header `40`, size `0b` or `0c`, `0d 0a 03`, rails `01` or `02`,
`03 e8 03`; 13-byte rows with one 3-byte rail sub-entry per rail, of which exactly
one has a nonzero type (VID: type 2). Rows keep the GV HAL names and the Ada field
set and units (GPC MHz = table, memory MHz = 2 × table, by analogy only: no Ampere
NVML reading). Every image stores GPC -1000..1000 and DRAM -1000..3000 except the
A40, whose ranges are all 0..0: its clock fields stay read-only. An edit may not
collapse a wider Ampere range to 0..0 (OUT_OF_BOUNDS), since that state reads as
disabled and could not be reverted. The RTX 2050 has
fixed HUB and DISP rows, which no field uses.

**Fans.** The Ada tables and rules, except that the speed table may be unused
(disabled on every channel: RTX 3080/3090 boards except the RTX 3080 Ti with two
connector channels, RTX 3060 8GB, RTX 3050 6GB and 8GB). PWM frequency on 28 images
with GPU-driven fans, channel count on 16 of the 18 that store a second channel (not
that RTX 3080 Ti, whose extra curves top out at 4000 RPM, above both channel maxima,
nor the HP OEM RTX 3060 12 GB below).
The A40 (passive) tables disagree and keep no fan field; laptops list no channel. An
HP OEM RTX 3060 12 GB (94.06.2F.00.ED) disables its second channel in the cooler,
mapping, control and speed tables but keeps policy entry 1 enabled, byte for byte the
channel 0 entry, while its enabled control entry masks entries 0 and 2 (byte 5 = 0x05;
the single-channel RTX 3060s store the same with entry 1 disabled). In GSP-RM
615.78.08 a control entry names its cooler row in byte 2 and its policy entries in two
masks (bytes 5..8 and 9..12), and a v0x20 policy entry names no cooler, so an enabled
entry that no enabled control entry names is built and validated but drives no fan
there (what the PMU does with it was not examined). The editor reads entry 1 as such a
copy, most likely unused: a copy is accepted only when the whole 51-byte entry equals
an active channel's and no enabled control entry sets its bit in either mask, every
write into the channel 0 entry (curve points, `fan_zero_rpm`, the zero RPM pair) goes
to both entries in every chain, which also keeps the copy valid, no fan-stop template
is offered and `fan_channels` stays read-only (a channel count writes every channel's
enable bytes, which would disable the copy or turn its channel on). Should the fan
controller use entry 1 after all, it holds the same values as entry 0. The RTX 3050
6GB and 8GB (GA107) disable their second channel in the same tables and keep policy
entry 1 enabled too, with its own curve (thermal channel 1, 95/100/103 °C), but their
enabled control entry masks entries 0 and 1 (byte 5 = 0x03). In GSP-RM the first mask
names the policy entries a control entry combines for its cooler, so entry 1 is an
extra curve linked to the one fan, as entries 2 and 3 are on the other images. The
editor accepts such an entry (a low extra curve) only when its channel is disabled in
the cooler, mapping, control and speed tables and its bit is set in the first mask of
every enabled control entry, and then expects the active channel's control entry to
set that bit next to its own (a copy has its bit in neither mask). It lists entry 1 as
`fan_extra_1`: its points stay at or below the channel maximum, which holds it,
`fan_zero_rpm` covers it (both ship with zero RPM on) and so does a zero RPM pair
where shown (on the 8GB; see Zero RPM for the 6GB), and `fan_channels` stays read-only
(a channel count writes entry 1's enable byte, which would disable the curve or turn
its channel on). An import maps `fan_extra_1` by key, so the extra curve 1 of another
RTX 30 image (entry 2, also thermal channel 1) lands in entry 1 here and the other way
round. Anything else that disagrees, such as entry 1 enabled while the mask leaves it
out or its channel enabled in the mapping or control table, still keeps the fan fields
hidden.
Channel limits and curve points as on Ada; the speed value holds the maximum only
where the speed table is enabled. A stock RTX 3090 blower image (PG132 SKU 10,
94.02.26.48.D6) stores both extra curves at 1000/2203/3541 RPM and 30/55/80 %,
starting below its 3000 RPM / 60 % row minimums, the only image of the corpus whose
extra curves start below a minimum: the channel curves alone hold the minimums, so
its minimums, every extra curve point and its channel count (1 or 2; a stored
channel needs only its maximums at or above the extra curves) are editable, while
`fan_zero_rpm` (0x13 on the channel entries, 0x07 on the extra curves) and its zero
RPM pairs stay read-only. Boards that stop the fan (RTX
3080, 3090, GA104 3060 Ti, 3070, GA106 3050 and 3060 8GB) store 0 % and 0 RPM as
minimum and curve start: those minimums rise only together with point 1 of their
own curve, which stays editable (the extra curves, also at 0, may stay there). The
GA103 3060 Ti, RTX 3050 8GB, A4000 and A2000 curves top
out below 100 % (97, 96, 81 and 95 %), so their level maximum also moves alone. `fan_zero_rpm` and the
zero RPM pairs: see [Zero RPM](#zero-rpm-fan_zero_rpm-opt-in) (on most GeForce images,
off with flag bits alone or a reviewed template elsewhere, read-only on the RTX A2000 and
on the RTX 3060 and RTX 3090 blower images with mixed bits).

**Thermal policy table (P+0x50) and factory clock record (P+0x98).** As on Ada, except
that the thermal policy header is 10 bytes (11 on Ada); see [Maximum operating
temperature](#maximum-operating-temperature-max_operating_temp_c) and [Factory GPC and
memory offsets](#factory-gpc-and-memory-offsets-factory_gpc_offset_mhz-factory_memory_offset_mhz-and-rated-boost-factory_rated_boost_mhz).

**Load path.** GA102-GA107 load `gsp_ga10x.bin`, the same GSP firmware as Ada, which
loads at most 512 KiB counted from the legacy image; a larger payload is ignored and
the stock VBIOS boots. The current normalizer accepts 34 of the 35 images; their
payloads keep the whole bank and exceed that capacity. The examined A40 dump is already refused
because its primary-bank padding is unrecognized. The chain itself (legacy to last data image) fits only on the A40 and the
four EFI-less laptops (20-76 KiB too large elsewhere) and would fit on all 35
without the EFI image. The experimental `ampere-relocated-v1` representation
exports exactly that: legacy and E0 images unchanged, EFI and trailing bank bytes
dropped, refused unless every check passes. 34 images verify; on hardware, an RTX
A2000 and one RTX 3050 6GB Laptop GPU loaded it. The loader rejects GA10x and AD10x
payloads above 512 KiB from the selected legacy image, in both profile
preparation and direct enrollment/reconciliation validation, so plain
`normalize` output of an Ampere ROM is not loadable. GA100 uses different GSP
firmware whose limit is unknown; this check does not infer it.

## Turing fields

Turing TU102-TU117 images (BIOS 90.xx) are recognized for their board power, per-input
power and current rows, voltage minimum, clock offset ranges and fans. The rules below
were checked on the 25 images of the Turing corpus (desktop, laptop, Max-Q, Quadro,
TITAN and two XOC images). One RTX 2080 Ti (ROG Matrix BIOS) ran edited images through
the Windows loader (driver 617.70, GSP 615.78.08): `nvidia-smi` reported the edited TGP
(500 W default and maximum), but the card stopped near 300 W under load until the
connector power rows were raised too (250 W each); it then reached about 458 W, and the
voltage limiters (Reliability Voltage, Max Operating Voltage) triggered, not the power
limiter. No other Turing field has run on hardware, so **every Turing field is
experimental**. The tester guide is in [turing.md](turing.md).

**Image chains.** Each bank holds legacy + EFI + two E0 images (laptops without EFI:
legacy marked last + two E0 images), and the second E0 image is not flagged last: a
small type-0x70 NPDS image flagged last (NBSI signature in its body) ends the chain.
The editor accepts that tail for Turing only; no table is read from it. Table pointers
follow the GA10x rule (logical view = legacy + E0 images, EFI length added past the
legacy image). BIT tokens are smaller than on Ampere (P 0xC4, or 0xE0 on the GTX 1630;
C 0x1C, M 0x1D, i 0x68): pointers past a token's end are absent.

**Power policy table (P+0x2C).** `30/2c/42`, and `30/27/42` on one RTX 2080 image (the
first 0x27 header bytes of `30/2c/42`). Rows hold minimum/rated/maximum at bytes 2/6/10
as on Ampere; the TGP row is row 2 on every image (header byte 10, or byte 13 with the
notebook header `ff ff ff 02`). It must read the board-total power channel, the only
class-2 sum on rail 0xf5 of the 20-entry, 22-byte channel table (P+0x3C): channel 9 on
the desktop TU10x/TU116 images (channel 0 there is another sum, rail 0xdf), channel 0
on TU117 and the laptops. `power_max_w`, `power_default_w` and `power_min_w` keep the
Ampere bounds.

**Per-input rows.** The other rows follow the Ampere rule (class, unit and channel; a
single input channel is class 5 at 12 V with no parameter but its provider byte 15),
except that Turing connector channels may hold a current correction offset at bytes
10..13 (nvgpu `curr_corr_offset`; 200 and 300 on the RTX 2070 connector channels),
accepted on Turing connector channels only; the slot channel stays byte-identical to
the Ada one. Threshold rows carry their index in parameter byte 0: 0 slot, 1 and 2
connectors, as on Ampere; a connector threshold field needs index 1 or 2. The Ampere
12 V input role (rail 0xe0, `input_current_*_ma`) is not used on Turing.

| Field | Row | Notes |
| --- | --- | --- |
| `slot_power_rated_w`, `_max_w` | 3: class 4 mW on the slot channel 3 (byte-identical to the Ada one); class 1 mW, the TGP's class, on the MSI GTX 1650 image | 16 desktop and workstation images; 63-64 W rated, 63-76 W maximum on the stock images. The slot-powered MSI GTX 1650 stores 30/63/74 W with the first parameter byte and the tail bytes of its TGP row (only the TGP sets flag 0x40 and parameter byte 22 = 6, which name the 3.3 V channel, inferred); its board power stopped near 66 W under a 75 W and a 90 W TGP while a load log read 62.5 W on the slot 12 V input, at the 63 W rated value (plus the 3.3 V channel, 1 W or 4 W by P-state, inferred), so this row is the limit. No other Turing, Ampere or Ada image has a class-1 row on a slot channel |
| `connector_N_power_rated_w`, `_max_w` | 4 and 5: class 4 mW on channels 4 and 5 (rails 0xfa, 0xfb, 0xfc); a third, row 6 (rail 0xe4), on the Galax HOF XOC image | Two on the TU10x boards, one on the GTX 1660, 1660 SUPER, 1660 Ti and 1650 SUPER; 70-167 W rated, 82-172 W maximum on the stock images |
| `slot_current_threshold_rated_ma`, `_max_ma` (opt-in) | 7: class 5 mA on the slot channel, threshold 0 | 10-11 A rated, 11-16.5 A maximum |
| `connector_N_current_threshold_rated_ma`, `_max_ma` (opt-in) | 8 and 9: class 5 mA on the channel of connector N, thresholds 1 and 2 | 14.5-22.5 A rated, 14.5-33.75 A maximum; a field only where the channel carries one connector power row and one such row |
| `nvvdd_output_ocp_rated_ma`, `_max_ma` (opt-in) | 13: class 10 mA on channel 19, whose 22 bytes equal the Ada NVVDD current sensor channel | 24 images, 40.25-350.94 A rated on the stock images; class 10 is not described in nvgpu |

On the RTX 2080 Ti the relationship entries of the TGP policy name rows 3, 4, 5, 7, 8, 9
and 13 (meaning of the link unknown); on the GTX 1630 and 1650 images they name none of
them, yet the MSI GTX 1650's slot row still caps its board. With stock values the slot
and connector rows sum to about the stock board power, so a TGP raised past that sum needs them raised too. On the RTX 2080 Ti
above, a 500 W TGP alone stopped near 300 W; with both connector rows at 250 W the card
reached about 458 W. The ASUS RTX 2080 Ti XOC image raises rows 3/4/5 (372.8/648/648 W)
with its 1000 W TGP and turns rows 7, 8, 9 and 13 into class 0; those rows then give no
field, and the editor does not reproduce such a change. The Galax HOF XOC image (three
8-pin connectors) sets the TGP and rows 3/4/5 to 2000 W and rows 7, 8, 9 and 13 to 2000
A, but leaves its third connector row 6 at 143/167 W. Five images (RTX 2060, GTX 1660,
1660 SUPER, 1660 Ti, 1650 SUPER) also store a class-5 mA row 12 on another NVVDD channel
(sensor 5, provider 2; 155.88 A, 276 A on the RTX 2060): it has no field and is named in
the NVVDD reason and in `nvvdd_threshold_rows`. The Max-Q and laptop images read the
slot rows through another rail (0xf1) and have no slot or connector field; the Ampere
class-0 NVVDD rule is not used on Turing. Not decoded: the class-8 row 11 on the sum of
the inputs, the 5001 W and 1001 W rows on other sums, the relationship table entries,
the TGP flag byte and the power sensor table (P+0x28).

**Voltage (P+0x68, P+0x20).** Rail table `10 05 0e 01 00`: one 14-byte nvgpu 1x row
(`vbios_voltage_rail_table_1x_entry`) in the legacy image, with selectors REL +4, ALT +5,
OV +6, power equation +7, boot voltage +8, VMIN limit +9 and voltage margin limit +10
(u8, 0xff absent). Every image but one keeps REL < ALT (if present) < BOOT = OV - 1 and
VMIN = OV + 1 with no margin limit equation; the Galax HOF XOC image points REL and ALT
at the OV equation (REL = ALT = OV = 1125 mV, BOOT and VMIN as stock), which is also
accepted. Another order, or a margin limit, is refused.
VFE `30 09 19 14 18` (20 variables) with the Ampere 24-byte equations, u8 count and u8
links. REL, ALT and OV are `constant` equations on all 25 images (REL 1068.75 mV,
950 mV on three Max-Q and laptop images; ALT 1093.75 mV, 1118.25 mV on one partner RTX
2080 image, absent on the Quadro RTX 8000 and six Max-Q and laptop images; OV 1125 mV),
so the REL/ALT/OV ceiling fields, selectors and boot voltage are read-only, as on Ampere.
On the HOF XOC image the fixed REL and ALT fields are read-only too (their equation is
OV's) and VMIN and the flat follow-OV value stay editable. `nvvdd_rel_alt_follow_ov` and
`nvvdd_rel_alt_follow_ov_mv` (opt-in) point REL and ALT at OV and set it, as on Ada (see
[REL and ALT follow OV](#rel-and-alt-follow-ov-nvvdd_rel_alt_follow_ov-opt-in)).
An edit may not change the equation the boot voltage selector picks.
`nvvdd_rel_fixed_mv` and `nvvdd_alt_fixed_mv` (opt-in) set the REL or ALT constant as
on Ada (see [Fixed REL and ALT values](#fixed-rel-and-alt-values-nvvdd_rel_fixed_mv-nvvdd_alt_fixed_mv)): the
edit writes the constant and the clamp maximum (bytes 11 and 7) in both banks and keeps
the clamp minimum (byte 3, the stored value), so a value goes from the stored value up
to the OV constant, with REL <= ALT, and an edited copy can be set back byte for byte.
Only a constant that no other selector or equation uses is editable. REL and ALT also
stay at or above the stored boot voltage and the highest evaluated VMIN (its clamp
plus the chain maximum); REL, ALT and `nvvdd_vmin_mv` form the ordering group
`nvvdd-rel-alt`, checked on the joint result. The edit's effect is untested; the VF
curve and the other limits still apply.
`nvvdd_vmin_mv` edits the equation selected at row byte 9: a float voltage output whose
clamp pins 668-703.75 mV, used by no other equation or selector (the boot selector
included), with chained equations that add -112.5 to +75 mV; the Ada VMIN rule then
applies (400 mV up to the lowest REL value less the chain maximum, the clamp minimum and
maximum written in both banks). How it relates to the driver VMIN on Turing is unknown.

**Clocks (C+8).** Header `35 09 0b 0a 03 e8 03 00 00`: the nvgpu v0x35 table
(`vbios_clocks_table_35`), ten 11-byte rows in the GV HAL order, in the legacy image.
Each row is gated by its usage (1 master: GPC, DRAM, DISP; 2 slave; 0 PWR), its ordering
byte, byte 8 = 0 and `ff ff` at bytes 9..10. Master rows store the signed MHz offset
minimum/maximum at bytes 3/5 (nvgpu parameter 1): GPC -1000..1000 and DRAM -1000..3000
on every image but the Quadro RTX 8000 (0..0, read-only) and the ASUS and Galax HOF XOC
images (GPC maximum 8000, DRAM maximum 5000). The slave rows (XBAR, SYS, VID) store
other parameters there and have no field. Units as on Ampere (GPC MHz = table, memory
MHz = 2 x table, by analogy). An edit may not collapse a range to 0..0.

**Fans.** The Ada cooler (P+0x58) and mapping (P+0x64) tables, and a policy table v0x10
(P+0x5C, `10 06 36 02`) with its own channel list (header bytes 4..5) and two 54-byte
entries. The entries keep the Ada and Ampere entry layout three bytes later (entry byte
5 = Ada byte 2), so the curve levels sit at entry bytes 17..19 and the three (1/32 C,
RPM) points from byte 21. The P token ends before the control and speed table pointers.
The policy list must equal the cooler list; a listed channel needs nonzero enables in
all three tables, policy byte 2 and mapping byte 1 equal to its index and policy bytes
9..16 = `23 2b 0a 01 00 02 80 00` (every active entry; Ada bytes 6..13, the same bytes
on most Ada and Ampere images); an unlisted one is disabled in all three. PWM
frequency (25 or 27 kHz), channel limits and curve points then follow the Ada rules
(18 GPU-driven images). The MSI GTX 1650 stores 135 kHz and RPM limits of 0 in its
active row: its PWM frequency, RPM limits and curve points stay read-only and only the
percent limits are offered. The disabled entries hold bytes unlike the active ones and
there is no control or speed table, so `fan_channels` is read-only. The Max-Q and
laptop images list no channel and enable none (no fan field); the GTX 1650 SUPER
disables its fan 0 mapping entry while the other tables list it and keeps no fan field.
There is no zero RPM field: Turing fans stop through the curve (see the Turing note
under [Zero RPM temperatures](#zero-rpm-temperatures-fan_n_zero_rpm_low_temp_c-fan_n_zero_rpm_high_temp_c-opt-in)).

**Checksum padding.** The checksum padding is checked on the images of the edited
tables in the second E0 image (power, VFE, fans: padded on all 25 images). The clock
table sits in the legacy image, which lacks the padding on one RTX 2080 image: its
clock fields and the follow-OV switch (the rail table sits there too) alone stay
read-only, with that reason. Writes go to both banks and repair the checksum of each
touched image.

**Thermal policy table (P+0x50) and factory clock record (P+0x98).** Both sit in the
second E0 image (10-byte thermal header, 6-byte factory record header) and are written
in both banks; the GSP-RM readers are those of `gsp_tu10x.bin`. See [Maximum operating
temperature](#maximum-operating-temperature-max_operating_temp_c) and [Factory GPC and
memory offsets](#factory-gpc-and-memory-offsets-factory_gpc_offset_mhz-factory_memory_offset_mhz-and-rated-boost-factory_rated_boost_mhz).
Like every Turing write, they leave the signed digest list below stale.

**Signed digest list.** The type-0x70 image at the end of each bank's chain holds a
signed list of 16-byte digests (algorithm unknown). Its chunks cover the E0 images and
the legacy image, except three small gaps just after the clock table, so every Turing
write leaves it stale; the editor cannot update it. On Ampere and Ada the same kind of
list sits before the legacy image and is not sent to GSP; on Turing it is inside the
loaded bytes. The RTX 2080 Ti readings above show that the driver used an edited TGP
and edited connector power rows with a stale list; for the other tables it is not known.

**Load path.** TU10x/TU11x load `gsp_tu10x.bin`, whose override receiver matches the
GA10x/AD10x one with the same 512 KiB capacity (static emulation of the 615.78.08
firmware, not hardware). Plain `normalize` keeps the first bank with the type-0x70
image: 260-355 KB from the legacy image. The experimental `turing-e0-end-v1`
representation keeps the same bank up to the end of the second E0 image, sets its NPDS
(byte 0x15) and NPDE (byte 0x0a) last-image bits as GA10x/AD10x mark their last E0
image, repairs its checksum, and drops the type-0x70 image and the rest of the bank
(7.5-12.5 KiB less). Whether GSP on Turing needs the type-0x70 image is unknown; the
GUI saves both shapes (`<name>-loader.bin`, `<name>-loader-e0end.bin`). The Linux
kernel patch lists TU102, TU104, TU106, TU116 and TU117 in its chip scope.

## Preservation, aliases and manifests

Edits preserve selector/boot identity, equation minima and all expression bytes
outside the maximum float, including temperature curves and opaque equation7
payloads; the Turing boot voltage equation keeps every byte. They preserve
unrequested power minima and rated/default values, unrelated policies, unknown
bytes and board records. Affected object/directory
SHA384 and bounded additive checksums are repaired, then the image is reparsed and
verified.

`shared_references` enumerates every rail/role referring to one equation. Editing
one ceiling changes that shared expression for all references; the manifest's
`affected_fields` includes these implicit changes and compatibility aliases with
`requested=false`. Requests that overlap bytes fail `CONFLICTING_FIELDS`, even
when their values agree. Existing typed errors and schema version1 remain intact.
No edited OCP maximum may fall below its unchanged rated/default value.

```python
from nvidia_vbios.editor import load, plan

image = load("reviewed.rom")
# Choose values from this ROM's field descriptors and preserved lower bounds.
proposal = plan(image, {"msvdd_ov_equation_max_mv": 1300,
                        "nvvdd_output_ocp_max_ma": 100000})
print(proposal.manifest["affected_fields"])
```

This example generates verified bytes in memory and makes no deployment or
runtime request. It does not establish that either new ceiling will affect the
running firmware.

## Evidence and tests

No research file is required at package runtime. Each descriptor's `evidence`
names its kind (for example `saved-get-selector-correlation`,
`saved-get-policy-monitor-correlation`, `read-only-nvml-correlation`,
`structural-row-comparison` or `third-party-research`), its scope and the
schema/format version it covers, and whether a SET was tested. The saved captures
and reference ROMs behind it are not distributed. Driver-version-specific SET
behavior stays unknown. Runtime GET and physical provenance remain separately
qualified.

The tests generate small structured images; no ROM file, GPU or driver is needed:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_extended_fields.py'
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_thermal_factory_fields.py'
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_advanced_fields.py'
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_ada_fields.py'
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_ampere_fields.py'
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_turing.py'
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_rail_vmin.py'
```

They cover full u16 selectors, both output-OCP ceilings, exact allowed byte ranges,
hashes/checksums, shared references and preservation. The maintainers also check
real reference ROMs, which cover every Ada, Ampere and Turing image listed above; those ROMs
are not distributed, and the suite here is synthetic only.
