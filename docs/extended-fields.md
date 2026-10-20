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
| `*_alt_equation_max_mv` | VFE output clamp maximum addressed by ALT selector | Reviewed Blackwell when present; Ada temperature-derated ALT (experimental) |
| `*_ov_equation_max_mv` | VFE output clamp maximum addressed by OV selector | Reviewed Blackwell |
| `*_vmin_equation_max_mv` | VFE output clamp maximum addressed by the rail INFO VMIN slot (GB20x row+`0x21`, Ada/Ampere row byte 11); **not** the evaluated VMIN | Read-only |
| `*_vmin_mv` | Evaluated minimum voltage (VMIN): the equation at GB20x row+`0x13`, Ada/Ampere row byte 7, Turing row byte 9 | Experimental, constant (GB20x) or clamp-pinned (Ada/Ampere/Turing) equations only, kept below the lowest REL value |
| `nvvdd_rel_alt_follow_ov` | 1 when the NVVDD REL and ALT selectors (REL alone without ALT) point at the OV equation (XOC-style) | Experimental, opt-in, GB20x and Ada; only 0 -> 1 |
| `nvvdd_rel_fixed_mv`, `nvvdd_alt_fixed_mv` | Value of a constant NVVDD REL or ALT equation: its constant and clamp maximum | Experimental, Ada and Turing (opt-in); from the clamp minimum up to the OV value, REL <= ALT; on Turing also at least the boot voltage and the highest VMIN |
| `fan_zero_rpm` | Bits 1\|2 of byte `0x32` of every enabled fan policy entry: 1 both set, 0 both clear (inferred meaning: the fans may stand still at low temperature) | Experimental, opt-in, GB20x; 1 only where the entries store fan-stop parameters; read-only when an entry sets one bit alone or the entries disagree |
| `fan_N_zero_rpm_low_temp_c`, `fan_N_zero_rpm_high_temp_c`, `fan_extra_M_zero_rpm_*_temp_c` | The two temperatures at bytes 30..33 (1/32 °C) of a channel's or an extra curve's fan policy entry, read with the zero RPM bits (inferred meaning: idle fans stop below the lower and start above the upper) | Experimental, opt-in, GB20x; only where the entry stores a rising nonzero pair and byte 46 is not 0xff; lower > 0, lower < upper <= 110 °C |
| `*_rel/alt/ov/vmin_selector_index` | Full stored selector index | Read-only |
| `*_boot_voltage_uv` | Stored boot voltage | Read-only, preserved |
| `*_output_ocp_max_ma` | Reviewed output-OCP policy maximum (client ceiling) | Reviewed Blackwell rows13/14; NVVDD row 13 on single-rail images; Turing NVVDD row 13 (class 10, experimental, opt-in) |
| `*_output_ocp_rated_ma` | Reviewed output-OCP rated value, enforced from boot | Experimental, reviewed Blackwell rows13/14; NVVDD row 13 on single-rail images; Turing NVVDD row 13 (opt-in) |
| `slot_power_rated_w`, `slot_power_max_w` | PCIe slot power policy: row 19 (SFF), row 18 (5060 Ti), Ada and Ampere row 5, Turing row 3 | Experimental, reviewed row shapes only |
| `connector_N_power_rated/max_w`, `connector_N_current_threshold_rated/max_ma` | Power policy and current hardware threshold of external 12 V connector sense channel N, numbered in power-row order | Experimental, Ampere and Turing; current thresholds opt-in |
| `slot_current_threshold_rated/max_ma`, `nvvdd_power_threshold_rated/max_w` | Hardware-threshold policies (slot 12 V current; Ada NVVDD output power) | Experimental, opt-in; slot current on Ada, Ampere and Turing, NVVDD power on Ada only |
| `board_fixed_rated_w` | Rated value of the fixed board policies 2/7 | Experimental, opt-in (hidden in the GUI by default) |
| `input_current_rated_ma`, `input_current_max_ma` | 12 V board input-current policy, row 9 (Ada: thresholds 0/1, rows 9/10) | Experimental, reviewed row shapes |
| `input_current_policy7_limit_ma` | Policy 7 limit linked to the 12 V input policy | Experimental, reviewed Blackwell row shape |
| `input_policy_9_max_raw` | Row 9 raw maximum; units unknown | Read-only, only when row 9 is unrecognized |
| `fan_channels` | Active fan channels across the five fan tables | Experimental, Blackwell, Ada and Ampere, up to the stored channels; read-only on Turing |
| `fan_pwm_frequency_hz` | PWM frequency of every active fan channel | Experimental, Blackwell, Ada, Ampere and Turing, 21-28 kHz |
| `fan_N_min/max_rpm`, `fan_N_min/max_pct` | Speed (RPM) and level (%) limits of active fan channel N, numbered from 1 | Experimental, Blackwell, Ada, Ampere and Turing; move alone only as far as the stored fan curves, past them together with the curve points; level limits opt-in |
| `fan_N_curve_K_temp_c/rpm/pct`, `fan_extra_M_curve_K_temp_c/rpm/pct` | Point K (1..3) of channel N's stored fan curve or of extra curve M: temperature (°C, 1/32 °C steps), speed (RPM), level (%) | Experimental, Blackwell, Ada, Ampere and Turing; points stay in order and inside the limits; levels opt-in |
| `power_default_w` | Rated TGP value used at boot | Experimental; Blackwell, Ada, Ampere, Turing |
| `gpc_offset_min/max_mhz`, `memory_offset_min_mhz` | Clock offset range in MHz (NVML scale) | Experimental, reviewed Blackwell and Ada; Ampere and Turing by analogy |
| `xbar/sys/vid_min/max_table_mhz`, `dram_min_table_mhz` | Clock offset range in table MHz | Experimental, reviewed Blackwell and Ada; Ampere; Turing `dram_min_table_mhz` only (its XBAR/SYS/VID rows store no range) |

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
  min/max trees, and the RTX 5080/5070 Ti MSVDD constant (800 mV) lies above the
  lowest MSVDD REL value (760.2 mV, see below): all read-only.
- Ada and Ampere: a float voltage equation whose clamp minimum equals its maximum,
  which no other equation references and no other role selects. The edit writes the
  clamp minimum and maximum in every chain. Corpus: 8 of the 21 parseable Ada images
  (RTX 2000 Ada, RTX 4090 95.02.18, both 4080 images, 4080 SUPER, 4070, 4070 SUPER, RTX 4500 Ada;
  the newer RTX 4090 image chains another equation into it, and a compare REL on
  fused inputs gives no bound on the 4070 Ti SUPER) and 21 of the 35 Ampere images,
  both rails on nine two-rail GA102 images. The A40 stores 668088.3125 uV, which an
  edit in whole uV could not write back, so it stays read-only.

The value goes from 450 mV (GB20x) or 400 mV (Ada, Ampere; no voltage device
minimum is decoded) up to the lowest value the rail's REL equation list can take,
less the most the equations chained after the VMIN equation can add, so the
evaluated VMIN never crosses REL. Each equation of a list is clamped to its own
bounds and its next link is added (the RTX 2000 Ada result above); a quadratic
whose slopes are float residue (below 1e-6; the corpus has at most 5e-9) counts
as its constant, other quadratics and the GB20x type 7 REL count as their clamp,
and min/max or compare equations span their children. A list with an unclamped
slope, another kind or a cycle has no bound and keeps the field read-only. On the
RTX 2000 Ada REL is at least 915 mV and the chain after the VMIN clamp adds 70 to
162 mV (the driver showed +90), so VMIN goes up to 753 mV; on the RTX 4080 REL is
1075 mV and the chain adds 146 to 261 mV, so up to 814 mV. On the RTX 5080 and 5070
Ti the MSVDD REL links a compare that can add -139.8 mV, so MSVDD REL can drop to
760.2 mV. The edit guard allows exactly the declared floats of that one equation,
and only through this canonical binding.

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
is offered on every parseable Ada image except the RTX 4070 Laptop image (no
checksum padding); images without an ALT selector move REL alone.
The parser reads the result (REL = OV, ALT absent or = OV, VMIN = OV - 1) as 1,
read-only; the REL equation is then the OV constant, whose input variable is not a
temperature, and the `ada-relocated-v2` loader payload still decodes the rail. The
evaluated VMIN may then go up to 1200 mV less what its chained equations add
(939 mV on the RTX 4080). Row byte 10 holds 2, the REL index, on every Ada image; its
meaning is unknown and this field leaves it. No Ada vendor image is known to do
this, and no Ada board has run it: not hardware-tested on Ada.

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
RTX 2000 Ada. Experimental: no board has run a fixed value.

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
channel, and write its row+2 minimum in every validated duplicate chain. Nonempty Ada profiles remain unsupported;
the Ampere BIT P token has no profile-table pointer (or a null one). Neither format
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
Ampere write the header-indexed TGP row+6 in every validated duplicate chain.
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
(on a top-level profile binding, only that profile's entries, capped by the base row).
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

### Joint validation

`power_min_w`, `power_default_w` and `power_max_w` form the `board-power` ordering
group; the two input-current fields form `input-current-12v`; each output-OCP rail's
rated and maximum fields form `nvvdd-output-ocp` or `msvdd-output-ocp`; the slot
power fields form `slot-power`; and the fan fields form `fan-speed` (every RPM limit and
curve speed), `fan-level` (every % limit and curve level) and `fan-temperature` (every
curve temperature), across channels, because the extra curves serve every channel. A
single-field request
is checked against the static bounds in its descriptor, which hold the partners'
current values. When partners are requested together, each value is first checked
against `bounds.encoding_minimum`/`encoding_maximum`, and then against the reviewed
bounds recomputed on the edited result. A broken minimum <= default <= maximum
order returns `OUT_OF_BOUNDS`. For example, raising the default to 900 W and the
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
61:65. Any other binding with one of these keys fails with `INVALID_FIELD_EVIDENCE`.
Aliases, partial offsets, other rows and non-matching profiles stay protected.
Override profiles that matched the base must still match after the edit, and no
profile may end with a policy default above its maximum. On a top-level profile
binding, the edited image must still bind the same profile through the same chain:
an edit that would let another profile exceed it, or make it equal the base table
(it would then become a matching profile and later edits would write the base), is
refused with `OUT_OF_BOUNDS`, a message naming the profile and entry, and
`details.field` set to the field of that entry; a plain order mistake gets the usual
ordering message. When a rated value
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
  row 18 there. Row 17 (type 2, monitor 2, 150 W, likely the 8-pin input) has no
  reviewed template and is not offered.
- `api_rail_index` stays unknown. No edited value has been booted on these boards.

## Notebook image (RTX 5080 Laptop GPU)

| Image | PCI ID | BIOS |
|---|---|---|
| GB203 RTX 5080 Laptop GPU (Lenovo Legion 7 Pro) | `10de:2c59` | `98.03.5C.00.F2` |

The rail and VFE tables are the split-rail ones, so the NVVDD and MSVDD voltage
fields work unchanged (REL 1025 mV, OV 1200 mV, rail INFO VMIN slot 700 mV on both
rails; the evaluated VMIN equations are min/max trees, read-only). The
power policy table keeps the v0x40 format but places its rows differently:

- **TGP in row 2.** Every desktop and Max-Q source has policy header bytes 21..23 =
  `ff 08 ff` and its TGP in row 8 (type 12). The notebook has `ff ff 02`, rows 7 and 8
  of type 0 with zero limits, and row 2 (type 1) holding 5000/80000/175000 mW.
  `nvidia-smi -q -d POWER` on a laptop running the same VBIOS reports Min 5 W, Default
  80 W and Max 175 W. `power_min_w`, `power_default_w` and `power_max_w` edit row 2 at +13, +17
  and +21. Override profiles on this layout are unreviewed; an image with any profile
  offers no power fields. The fixed-policy opt-in field does not exist here.
- **Running limit.** On a laptop the platform (the system BIOS's Dynamic Boost data
  and, on Linux, `nvidia-powerd`) requests the running limit. A raised ceiling is only
  a ceiling; the request, the output OCP, the cooling and the laptop's VRM can all keep
  power lower. The header also stores 55000/45000/35000/25000 at bytes 24..39, whose
  meaning is unknown.
- **Output OCP.** Rows 13 and 14 equal the GET-reviewed Max-Q rows byte for byte
  (range bytes excluded), monitors 27 and 28. Each monitor's power channel and the
  power device it reads are byte-identical to the reviewed NVVDD (channel 13, device 9)
  or MSVDD (channel 12, device 8) output on all seven GET-reviewed sources. The chain
  is required, and so is device ID `0x2C59`. Stock rated values: NVVDD 180 A, MSVDD
  60 A, each with rated = maximum.
- **Row 9** is type 3 with unit byte 1 and value 11375, not the type 11 input-current
  row of the desktop cards. It stays read-only (`input_policy_9_max_raw`).
- **Clock offsets.** The table equals the desktop one except bit 12 of the DRAM row
  descriptor (`0x1182` instead of `0x182`). That one bit is accepted on that row only.
- **Fans.** The cooler list is empty and every per-channel enable is 0: the laptop's
  fans belong to the system, so no fan field is offered.

There is no saved GET for a notebook, and no edited value has been booted on a
Blackwell one (one Ampere laptop has, see Ampere fields).
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
    enable byte in every table and limits that hold the extra curves (below), so
    raising again rebuilds it exactly. The Matrix lowered to 2 then has the same
    list and enables as the Astral XOC image, which
    keeps the third channel stored but off. Its other bytes stay its own: the cooler enable
    value (2 on the Matrix, 1 on the XOC and Lightning images; meaning unknown),
    duty bytes and policy curves.
  - Raising the count enables the next stored channels, each with channel 0's enable
    byte in every table. The cooler row must also have its own configuration (row
    bytes 4..5 and 10 unlike every earlier row), the active PWM frequency, byte
    13 = 0 and speed and level limits that hold every enabled extra curve: those
    curves serve every active channel, so an extra curve edited past a stored row
    keeps that row off. The scan stops at the first channel that does not qualify.
  - Lowering and raising again restores the original bytes.
  - Resulting limits: Matrix, Astral XOC and Lightning 3; FE, 5080, 5070 Ti, 5070
    and Workstation 2; Max-Q and 5060 Ti 1, read-only, because their second
    channel holds only placeholder entries; SFF 1, read-only, because its extra
    curves (3600-7300 RPM) do not fit its stored second row (1375-3375 RPM).
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
  (1000-3350) 96 % -> 3213 (3216), 90 % -> 3010 (3014). The driver's 30-100 % range
  does not follow byte 2 (10-30 on the corpus), so the meaning of the level bytes is
  unconfirmed. Hardware test on that RTX 5080 (both channels, fans under manual
  control): with the speed maximum raised from 3500 to 4000 RPM, 72 % gave 2820 RPM
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
  - A minimum may go from 0 up to the lowest first point of the channel's curve and
    of every enabled extra curve, and below its maximum. A maximum may go from the
    highest top point of those curves, and above its minimum, up to 32767 RPM (the
    signed 16-bit range of the driver's fan-curve RPM values) or 100 %. The speed
    limits also keep the channel's speed-table value (speed entry bytes 2..3, when
    that entry is enabled) inside them: it is 0.51-0.79 of the row maximum on the
    corpus, and its meaning is unknown. Alone, a limit can therefore widen, or narrow
    as far as the stored curves and the speed value, but never cut into them.
  - A side with no room (a level maximum of 100 with a curve reaching 100 %, or the
    0 % / 0 RPM minimum of an Ampere board that stops its fan) stays editable with
    equal bounds: alone it keeps its value, and it moves together with the curve
    points (below). Each side is read-only when the row or a curve holds another
    shape (curve temperatures not rising strictly, speeds or levels falling,
    minimum not below maximum, a curve or the speed value outside the limits, a
    maximum or a curve above the ceiling). Bounds are always numeric, so a joint
    request that breaks the order is refused on the edited result.
- **Curve points.** `fan_N_curve_K_temp_c`, `fan_N_curve_K_rpm` and `fan_N_curve_K_pct`
  (K = 1..3) edit point K of channel N's own policy entry: the temperature at byte
  18 + 4(K-1) (`<H`, 1/32 °C; the field is in °C, so 60.5 is stored as 1936 and 60.01
  is refused as `UNREPRESENTABLE_VALUE`), the speed at byte 20 + 4(K-1) (`<H`, RPM)
  and the level at byte 14 + (K-1) (`<B`, %). `fan_extra_M_curve_K_*` edit the
  enabled policy entries past the cooler rows, numbered M = 1.. in entry order (GB20x
  entries 4 and 5, Ada and Ampere entry 2 and, on most images, 3). On the corpus the
  channel curves span 43-97 °C and the extra curves 92-108 °C; three Ampere boards
  store a point off a whole degree (49.90625, 51.90625 and 59.90625 °C).
  - Temperatures rise strictly: point K stays between its neighbors plus or minus
    1/32 °C, from 0 °C for point 1 up to 110 °C for point 3. Two points may never
    share a temperature.
  - Speeds and levels never fall: point K stays between its neighbors (equal is
    allowed) and inside the containment, from its floor for point 1 up to its
    ceiling for point 3. A channel curve is contained by its own row limits; an extra curve
    serves every active channel, so it is contained by the highest minimum and the
    lowest maximum of the active rows. The ceilings stay 32767 RPM and 100 %.
  - A point is read-only when its curve holds another shape (as above, or a value
    above its ceiling) or when it sits outside its bounds; a point with no room
    stays editable like a limit. A stored point above the containment does not
    widen its neighbor's range. On the corpus every point is editable except the
    top speeds of the RTX 4080 Super's extra curves, which top out above its second
    channel's maximum. The level points are opt-in, like the level limits.
  - **Lowering a maximum.** A limit and the curves contain each other, so a maximum
    goes below a stored curve only in one request that also moves every point above
    the new maximum, of the channel's curve and of every extra curve; the fields
    share the `fan-speed` group, so the request is checked on the edited result. For
    example, on a board whose curves top out at 3500 RPM, `fan_1_max_rpm`,
    `fan_1_curve_3_rpm`, `fan_extra_1_curve_3_rpm` and `fan_extra_2_curve_3_rpm` all
    set to 3000 are accepted together; the maximum alone, or with the channel's own
    curve only, is refused (`OUT_OF_BOUNDS`). The maximum never goes below the
    channel's enabled speed-table value. Raising a minimum works the same way with
    the first points. Fields with no room take part too: a level maximum of 100
    lowers with the top level points, the 0 RPM minimum of a board that stops its
    fan rises with the first speed points, and the same keys undo a request in one
    edit, points left flush with the new limit included.
  - The level fields are opt-in (behind the GUI's advanced toggle) because their
    meaning is unconfirmed. Byte 3 is 100 on every active row, so `fan_N_max_pct`
    moves alone only where the curves top out lower (RTX 5060 Ti 81 %, RTX 5070
    92 %); elsewhere it lowers with the top level points.
- `fan_channels` and a channel limit, curve point, `fan_zero_rpm` or zero RPM
  temperature are refused together (`SEPARATE_EDIT_REQUIRED`): the count adds or
  removes channel fields, changes the limits the extra curves must fit and which
  policy entries the zero-RPM flag reads, so save it first and edit the limits,
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
  booleans at structure offsets +0x80 and +0x81).
- **Corpus.** In the corpus, every GeForce GB20x image sets both bits on every
  enabled entry: 0x17 on the channel entries and 0x07 on the extra curves, or
  0x16/0x06 (bit 0 clear) on the ASUS XOC and MSI Lightning images. Every RTX PRO
  image clears both: 0x11/0x01 on the PRO 4000 SFF, 0x01 on the PRO 6000
  Workstation and Max-Q. No image sets one bit alone. Bytes 30..33 hold two rising temperatures (43/50, 50/55 or 50/60 °C on the
  channel entries) and byte 46 holds 0, except on the RTX PRO 6000 Max-Q, which stores
  zeros and 0xff there.
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
  entries).
- **Field.** `fan_zero_rpm` is 1 when both bits are set on every enabled entry (the
  active channels' entries and the enabled curves past the cooler rows) and 0 when
  both are clear. A write sets or clears both bits on all of them at once, the only
  forms the images store, and keeps the other bits of each flag byte; the manifest
  lists the flag bytes as layout bytes. Like the PWM frequency, a write also covers
  the stored channel entries a larger `fan_channels` count may enable (the third
  channel of the ASUS XOC and MSI Lightning images, whose bits already match), so the
  count and the flag can change in either order. The field is read-only when an entry
  sets only one of the two bits (some Ampere images store 0x13/0x03, and the firmware
  reads the bits separately), when the enabled entries disagree or when such a stored
  channel entry differs from them. The value 1 is offered only when every written
  entry stores two rising nonzero temperatures at bytes 30..33 and a byte 46 other
  than 0xff, so the Max-Q stays read-only at 0. An image that sets the bits without
  those parameters (none in the corpus) still offers 0, but the copy is then read-only
  at 0, so that change cannot be undone in the editor. The window shows the field,
  like the other 0/1 fields, as a switch behind the advanced toggle.

The other policy entry bytes are preserved. Setting 1 is hardware-tested on that one
board; other boards and setting 0 are not.

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
- **Owner report.** On a Zotac RTX 5080 (43/50 °C on its channel entries) the owner
  sees idle fans start at about 52 °C, which fits "stop below the lower, start above
  the upper". This is a correlation, not a test of an edit.
- **Fields.** Each active channel (`fan_N_...`) and each enabled extra curve
  (`fan_extra_M_...`, numbered as in the curve fields) gets a lower and an upper
  field, only where the entry stores a rising nonzero pair and byte 46 is not 0xff:
  nothing is offered or synthesized for the Max-Q's zeros. Stored channels that a
  larger `fan_channels` count enables keep their bytes and get their fields once
  enabled. Values are exact in 1/32 °C. The lower stays above 0 °C and below the
  upper; the upper at most 110 °C, an editor limit as for the curve temperatures, not
  a tested firmware limit (a stored upper above it leaves the pair read-only). The
  two fields of an entry form one ordering group, so both can move past the stored
  values in one edit. No pair is copied to another channel or curve. The fields do
  not depend on `fan_zero_rpm`: they stay editable with the bits clear or mixed, and
  an edit leaves the flag byte, byte 46, the curves and every other byte as they are.
- **Effect.** Setting a higher upper value does not promise that the fans start at
  that temperature: other fan policies, the extra curves and sensors may still decide.
  Not hardware-tested.

## Ada fields

Every Ada rule is structural and was checked on each parseable image of the Ada
corpus (20 of 21 images; the RTX 4090 Laptop image has no EFI image and is
refused by the image-chain parser). Writes go to the same field in every
duplicate chain, and the additive checksum of each touched image is repaired.
Only the RTX 2000 Ada (10de:28b0, 95.07.47.00.19) runs edited images on the maintainers' Linux machine: its
power ceiling/floor and REL ceiling keep their reviewed status; every other Ada
field, and every field on any other Ada image, is marked experimental. The
RTX 4070 Laptop image lacks the reviewed checksum padding in its data image, so
all its fields stay read-only with a diagnostic.

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
| `nvvdd_output_ocp_max_ma` | class 0 mA on the NVVDD output current channel 19 | Read-only: absent from the RTX 2000 Ada runtime policy list, so enforcement is unproven |

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
the PCIe CEM slot rating. Auxiliary-connector rows, laptop-only rows and
placeholder rows stay unexposed.

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
channel could not be raised back to two).

`ada-relocated-v2` compares `power_rows`, `clock_ranges`, `rail_limits`,
`rail_equations` and `fan_coolers` between the source and the relocated payload.

## Ampere fields

Ampere GA102-GA107 images use the Ada table set with narrower rows. Every rule
below is structural and was checked on the 35 images of the Ampere corpus (desktop,
workstation, datacenter and laptop); all are recognized. No Ampere board runs on
the maintainers' Linux machine, so **every Ampere field is experimental** and none
has a runtime reading there. An RTX A2000 took an edited power floor through the
Windows loader. An RTX 3050 6GB Laptop GPU (75 W HP BIOS) took a 70 W ceiling and a
55 W boot default the same way, and the driver reported a 70 W limit; a raised
ceiling is not tested on a laptop. Writes go to every duplicate chain and repair the
additive checksum of each touched image.

**Image chains.** Laptop and headless dumps (A40, RTX 3070/3060/3050 Ti/3050
Laptop) have no EFI image: the legacy image is marked last and the data images
follow it, and table pointers then need no EFI offset. GA102, GA104 and GA106 data
images all carry NPDS ID `0x2200` (GA103 `0x2400`, GA107 `0x2580`), so an Ampere
data image may carry its own chip ID or `0x2200`, and every data image of a chain
the same ID. Ada keeps requiring the EFI image. `10de:2501` (RTX 3060, PG190 SKU 50)
is not in NVIDIA's product table; the editor recognizes it from pci.ids
(`EDITOR_ONLY` in `families.py`, evidence kind `pci-ids-entry`), while the loader
and enrollment keep it out of scope. The RTX 3050 6GB image lacks the
reviewed checksum padding in its last data image: all its fields stay read-only.

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
| `nvvdd_output_ocp_max_ma` | class 0 mA on the NVVDD output channel | Read-only, as on Ada |

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
the A2000, row 17; meaning unknown), the MSVDD output-current row of the two-rail
boards and the laptop rows.

**Voltage (P+0x68, P+0x20).** Rail table `20 05 11 01 00` (NVVDD) or `20 05 11 02 01`
(GA102 except the RTX 3090 Ti: NVVDD and MSVDD, the second name inferred from the
clock domains). Rows are the first 17 bytes of the Ada row, with the same
selectors and order rule on every rail. VFE equations are 24 bytes with a u8 count
(header byte 5) and u8 links. REL and OV are `constant` equations on all 35 images
(REL 900-1087.5 mV, OV 1100 mV); ALT is constant (1100 mV) on the 18 desktop
GeForce images and absent (selector 0xff) on the 17 workstation and laptop images.
Every voltage field is therefore
read-only: a ceiling-only edit would not change the voltage, and writing the
constant itself is an unreviewed kind of edit.

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
connector channels, RTX 3060 8GB). PWM frequency on 24 images with GPU-driven fans,
channel count on 15 of the 16 that store a second channel (not that RTX 3080 Ti,
whose extra curves top out at 4000 RPM, above both channel maxima).
The A40 (passive) and the RTX 3050 6GB/8GB tables disagree and keep no fan field;
laptops list no channel. Channel limits and curve points as on Ada; the speed value
holds the maximum only where the speed table is enabled. Boards that stop the fan (RTX
3080, 3090, GA104 3060 Ti, 3070, GA106 3050 and 3060 8GB) store 0 % and 0 RPM as
minimum and curve start: those minimums rise only together with the first curve
points, which stay editable. The GA103 3060 Ti, A4000 and A2000 curves top out below
100 % (97, 81 and 95 %), so their level maximum also moves alone.

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
also OV's) and VMIN stays editable.
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

**Checksum padding.** The checksum padding is checked on the images of the edited
tables in the second E0 image (power, VFE, fans: padded on all 25 images). The clock
table sits in the legacy image, which lacks the padding on one RTX 2080 image: its
clock fields alone stay read-only, with that reason. Writes go to both banks and
repair the checksum of each touched image.

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
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_ada_fields.py'
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_ampere_fields.py'
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_turing.py'
```

They cover full u16 selectors, both output-OCP ceilings, exact allowed byte ranges,
hashes/checksums, shared references and preservation. The maintainers also check
real reference ROMs, which cover every Ada, Ampere and Turing image listed above; those ROMs
are not distributed, and the suite here is synthetic only.
