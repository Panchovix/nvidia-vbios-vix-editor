"""PCI/BIT/NPDS table layout of the Ada, Ampere (GA10x) and Turing ROMs.

Field locations derive from NVIDIA-authored nvgpu bios.h 3x power/1x rail/clock
prefixes and VFE output equations; every rule below is structural and was
checked on each parseable image of the Ada corpus and of the 35-image Ampere
corpus. Ampere shares the Ada table set with narrower rows (power 0x47/0x43,
rail 0x11, VFE equations of 24 bytes with 8-bit links) and up to two rails.
Turing (25-image corpus) reads its power policy and input channels like
Ampere (0x42-byte rows, 22-byte channels), its rail (nvgpu 1x row), VFE (as
Ampere with 20 variables), clock (nvgpu v35) and fan tables (the Ada cooler and
mapping tables, a v0x10 policy table) through Turing variants below.
No board serial, complete-file size, table-address, or source-hash pins.
"""
import copy
import hashlib
import math
import struct
from .structure import (VFE_CRITERION_EQUATION, VFE_UNCLAMPED, dram_points, fan_curve, gpc_curve_slot, scan_images,
                        image_chains, parse_bit, quadratic_span, read, vfe_clamp_state, vfe_free_slot, vfe_range,
                        vfe_referrers, vfe_tree)
from .errors import FormatError

SOURCE = 'https://github.com/OE4T/linux-nvgpu/blob/patches-rel-36/drivers/gpu/nvgpu/include/nvgpu/bios.h'

# Ada 3x power policy variants (version, header size, entry size). They share the
# 0x53-byte entry prefix; 34/5b adds two 0xff header bytes and eight zero entry bytes.
# 2c/4b (RTX 4090 VBIOS 95.02.18) holds the first 0x2c header and 0x4b entry bytes of
# 32/53, which adds 00 00 00 00 ff ff to the header and eight zero bytes to each entry.
ADA_POWER_VARIANTS = ((0x30, 0x32, 0x53), (0x30, 0x34, 0x5B), (0x30, 0x2C, 0x4B))
ADA_POWER_ENTRY = 0x53
# Power channel entries (P+0x3c, 26 bytes) byte-identical to channels that saved
# GET identifies on GB20x: the PCIe slot input (rail 0xff), the 12 V board input
# current (rail 0xe0), and the NVVDD output power/current sensors (rail 1).
SLOT_CHANNEL = bytes.fromhex('05ff001bb7000010' + '00' * 18)
INPUT_12V_CHANNEL = bytes.fromhex('05e0001bb7000010' + '00' * 7 + '0e' + '00' * 10)
NVVDD_POWER_CHANNEL = bytes.fromhex('0101001bb7000010' + '00' * 6 + '05' + '00' * 11)
NVVDD_CURRENT_CHANNEL = bytes.fromhex('0101001bb7000010' + '00' * 6 + '06' + '00' * 11)
# Ada policy rows by immutable shape: sha256 over entry bytes 0..1 (class/unit
# flags, channel index) and 14..0x52 (parameters), the range bytes 2..13
# excluded; the row must also read the exact channel entry named here.
ADA_POLICIES = {
    'slot_power': (('830b68bb520fd6faeba192d232c4e7ad7348f678b381205b51e8ee6ec2677d2e',), SLOT_CHANNEL, 'mW'),
    'slot_current': (('85465d66d4ecc2254ab7289a60fb0850f70a98d87894c8e04cad62411685e66f',), SLOT_CHANNEL, 'mA'),
    'input_current_0': (('619656b5bd542e74f9ee95037ea1a783c9259a9b893ddbbea6f75cee0b65cc2b',),
                        INPUT_12V_CHANNEL, 'mA'),
    'input_current_1': (('6951b88da34cafedf535fd5a1156bbf1113b025c30c7c781d44471c479bd9d85',),
                        INPUT_12V_CHANNEL, 'mA'),
    'nvvdd_power': (('9d19198c80cdab80086e534f5798abfbd94b2a63bebec446f4f95e16b15a0e90',
                     'f9720229d16ba7765dee7d475d514604fa6fabb72a99de272c2a1e30c371768c'), NVVDD_POWER_CHANNEL, 'mW'),
    'nvvdd_current': (('066b0f41c3bce11684cee4c8b2682d738a02e12e9d991e1f18444becebea3465',
                       '93d3c5c1448196872068413a3c76d5d6a981e70d1f8383b02b75dea5970daaba'),
                      NVVDD_CURRENT_CHANNEL, 'mA'),
}
# Auxiliary power connector input rows (TableRom.ada_connector_policies): the slot_power row shape
# with its channel byte excluded (sha256 over entry byte 0 and bytes 14..0x52; class 4 mW), on a
# board input: a class-5 single input at 12 V that channel 0 (the class-2 board total) adds with
# weight 1.0, on a connector rail, with no parameter but the provider byte 15 (0..2). Rail 0xda is
# the auxiliary connector input that saved GET identifies on every connector-powered GB20x source
# (monitor class 8, rail 218); 0xdb/0xdc are the next inputs (the spare Ada channels 26..28 list
# da/db/dc on providers 0/1/2; the MSI 2500 W GB20x image adds a 0xdb input on provider 2). 0xfa,
# 0xfb, 0xfc and 0xe4 are the Ampere connector channel rails (AMPERE_CONNECTOR_RAILS); the RTX 4070
# image uses 0xfa. The rail does not name the connector type: the 8-pin RTX 4060 Ti uses 0xda too.
ADA_CONNECTOR_SHAPE = 'e48af26eb4a825082b0d78339ae3ec74adfc17de9718493db5dbe39435fbe085'
ADA_CONNECTOR_RAILS = (0xDA, 0xDB, 0xDC, 0xFA, 0xFB, 0xFC, 0xE4)
# Power override profile table (P+0xF4), version 0x10, parsed for Ada and GB20x by the same GSP-RM
# 615.78.08 code (0x17cd67c, gsp_ga10x.bin): a 10-byte header, four 0x3d-byte selection rows (5-byte
# header {u8 type, u32 param}, eight 7-byte entries {u8 flags, u8 profile, u32 value, u8 param}) and
# sixteen 0x49-byte profiles (u8 flag, eight 9-byte entries {u8 kind, u32 selector, u32 value}).
# A selector names a power policy row (bits 0..7) and a limit (bits 8..9: 0 maximum, 1 rated,
# 2 minimum). The profile apply (0x17bc69c) passes the value to the policy through vtable +0x2d0,
# the wrapper 0x17b2340, which calls the limit setter 0x177fd2c (client 0xfe) and then a notify
# method. The policy constructor (0x178aa44) seeds the same limits from the row with the same client
# 0xfe, so a selected profile value replaces the row value (it does not clamp it). Field 2 has no
# corpus example and is refused.
PROFILE_HEADER = bytes.fromhex('10 0a 05 04 07 08 01 10 09 08')
PROFILE_BYTES = 0xFE + 16 * 0x49
ADA_PROFILE_FIELDS = {0: 'maximum', 1: 'default'}
# The reviewed Ada selection chain (MSI RTX 4090 Suprim, 95.02.3C.40.EA). Row 0 (type 1, param 8:
# GPIO set 0, votes into row 1, no presence gate; evaluated by 0x17c72a0) reads two sense inputs
# into a code (bit 0 | bit 1 << 1) and votes the value of the entry holding that code (0: no vote).
# Row 1 (type 2, param 0; 0x17bc09c) applies the profile of the last entry whose threshold is at or
# below the vote. Rows 2 and 3 are off. Unused entries hold 00 ff 00 00 00 00 00.
ADA_SELECTION_HEADERS = (bytes.fromhex('01 08 00 00 00'), bytes.fromhex('02 00 00 00 00'))
SELECTION_UNUSED = bytes.fromhex('00 ff 00 00 00 00 00')
# The code read with both sense inputs asserted, the top level. That it is the 600 W state of a
# 12V-2x6 cable is inferred: the RTX PRO 6000 Max-Q images map codes 0..3 to 150/300/450/600 W.
TOP_SENSE_CODE = 3
ADA_RAIL_HEADER = bytes.fromhex('20 05 1f 01 00')
ADA_VFE_PREFIX = bytes.fromhex('30 0b 19 32 19')
# V20 rail row selectors (u8, 0xff = absent). REL/ALT/OV follow the nvgpu 1x prefix;
# VMIN is byte 11, the slot of the reviewed board's runtime rail INFO VMIN selector.
ADA_ROLE_OFFSETS = (('REL', 4), ('ALT', 5), ('OV', 6), ('VMIN', 11))
# Byte 7 selects the equation of the evaluated VMIN: on the RTX 2000 Ada a new clamp
# there moved the driver's VMIN, a new byte-11 equation did not (hardware tests).
ADA_VMIN_OFFSET = 7
# Bytes 0..3 of the V20 row hold the boot voltage; bytes 4..0x1e may select VFE equations.
ADA_ROW_SELECTOR_BYTES = range(4, 0x1F)
# VFE variable type of a fused input (nvgpu SINGLE_SENSED_FUSE): the input of a per-chip VMIN equation.
VFE_FUSE_VARIABLE = 4
# Ada and Ampere tables outside the VFE and rail tables that name VFE equations (TableRom.equation_index_names):
# name -> BIT pointer, and per family the reviewed (version, header size, entry size).
EQUATION_INDEX_POINTERS = {'clock programming': ('C', 0x0C), 'FLL': ('C', 0x10), 'voltage policy': ('P', 0x70)}
EQUATION_INDEX_LAYOUTS = {
    'ada': {'clock programming': (0x40, 8, 15), 'FLL': (0x10, 8, 16), 'voltage policy': (0x10, 5, 19)},
    'ampere': {'clock programming': (0x40, 8, 13), 'FLL': (0x10, 7, 15), 'voltage policy': (0x10, 5, 17)},
}
# Clocks table (BIT C+8) v0x40 with the GV HAL (header byte 6 = 3). nvgpu fixes the
# GV row order; each row is also gated by its usage (0 fixed, 1 master), the low
# byte of its ordering word and its rail sub-entry type. NVD is named VID as on GB20x.
ADA_CLOCK_HEADER = bytes.fromhex('40 0d 0f 0a 03 01 03 e8 03')
ADA_CLOCK_ROWS = (('GPC', 1, 0x13, 1), ('XBAR', 1, 0x24, 1), ('DRAM', 1, 0x62, 1), ('SYS', 1, 0x35, 2),
                  ('HUB', 1, 0x71, 2), ('VID', 1, 0x46, 1), ('PWR', 0, 0xFF, 0), ('DISP', 1, 0x80, 1),
                  ('PCIEGEN', 1, 0x08, 2), ('HOST', 1, 0x57, 2))
# Ada fan tables: (BIT P offset, header, header size, entry size, entries). Entries
# 0..1 belong to fan channels 0..1; policy entries 2..7 are not per channel.
ADA_FAN_TABLES = {
    'cooler': (0x58, bytes((0x10, 6, 0x1A, 2)), 6, 0x1A, 2),
    'policy': (0x5C, bytes((0x20, 4, 0x33, 8)), 4, 0x33, 8),
    'mapping': (0x64, bytes((0x10, 4, 5, 2)), 4, 5, 2),
    'control': (0xDC, bytes((0x10, 4, 0x0D, 2)), 4, 0x0D, 2),
    'speed': (0xE0, bytes((0x10, 4, 6, 2)), 4, 6, 2),
}
ADA_FAN_CHANNELS = 2
# Thermal policy table (P+0x50), version 0x10: (header size, entry size) per family. GSP-RM 615.78.08
# reads the header as 7b1w1b (10 bytes: Turing, Ampere) or 7b1w2b (11 bytes: Ada) and each 40-byte
# entry as 2b3w8d: byte 0 is the policy class (0 skips the entry, 1 is read), byte 1 the thermal
# channel, bytes 2..7 three temperatures in 1/32 C. Header bytes 4, 5, 6 and 9 name policy entries
# by role (0xff: none); byte 9 names the maximum operating temperature policy (THERMAL_MAX_TEMP_BYTE).
THERMAL_POLICY_LAYOUTS = {'turing': (0x0A, 0x28), 'ampere': (0x0A, 0x28), 'ada': (0x0B, 0x28)}
THERMAL_ROLE_BYTES = (4, 5, 6, 9)
THERMAL_MAX_TEMP_BYTE = 9
# Factory clock record (P+0x98): version 0x10, then array A and array B, two {u8 flag, u32 kHz}
# entries each. Turing stores the 6-byte header GSP-RM reads as 6b; Ampere and Ada the 7-byte header
# it reads as 7b, whose byte 6 it keeps as a clock flag (1 on three Ada images, 0 elsewhere).
FACTORY_CLOCK_HEADERS = {'turing': (bytes.fromhex('10 06 05 02 05 02'),),
                         'ampere': (bytes.fromhex('10 07 05 02 05 02 00'),),
                         'ada': (bytes.fromhex('10 07 05 02 05 02 00'), bytes.fromhex('10 07 05 02 05 02 01'))}
FACTORY_CLOCK_ENTRY = 5
# PERF_CF controller table (P+0xa8), version 0x10, 6-byte header. GSP-RM 615.78.08 (gsp_ga10x.bin and
# gsp_tu10x.bin) unpacks each entry by its size: 23 bytes as 3b5d, 24..27 as 3b5d1b, 28..31 as 3b5d1b1d,
# 32..40 as 3b5d1b2d, 41..53 as 3b5d1b2d1b2d (54 and more as on GB20x), so bytes 0..22 (type, target, jump
# threshold, gains, clock domain, hysteresis counts) sit at the same place in every size. Reviewed entry
# sizes: Turing 24 and 28, Ampere 24, 32 and 49, Ada 49. The policy table (P+0xac) is the GB20x one:
# version 0x10, a 5-byte header whose byte 4 is 0, 10-byte entries.
LEGACY_PERF_CF_CONTROLLERS = (0x10, 6, (24, 28, 32, 49))
LEGACY_PERF_CF_POLICIES = (0x10, 5, 10)
# LPWR feature tables (version 0x10): name -> (BIT P offset, header size, entry size, format of the entry's
# enable word, whose bit 0 enables the entry). GSP-RM reads MSCG entries of 15 bytes as 1d2w1b3w, a 9-byte
# GR rail gating header as 5b2w and DIFR entries of 17 bytes as 1d1b6w. Turing has GR power gating and MSCG
# (its P token ends before the other pointers), Ampere adds GR rail gating and Ada DIFR.
LEGACY_LPWR_TABLES = {
    'gr_pg': (0x80, 10, 5, '<I'),      # GR power gating
    'ms': (0x84, 7, 15, '<I'),         # memory system clock gating (MSCG)
    'gr_rg': (0xD4, 9, 1, '<B'),       # GR rail gating
    'difr': (0xE8, 11, 17, '<I'),      # DIFR
}
ADVANCED_TABLES = (('P', 0xA8), ('P', 0xAC)) + tuple(('P', t[0]) for t in LEGACY_LPWR_TABLES.values())
# Tables the Ada and Ampere fields write; their data images must end with a reviewed checksum tail (checksum_tail).
ADA_EDITED_TABLES = ((('P', 0x2C), ('P', 0x20), ('C', 8)) + tuple(('P', t[0]) for t in ADA_FAN_TABLES.values()) +
                     (('P', 0x50), ('P', 0x98)) + ADVANCED_TABLES)
# Reviewed tails before the checksum byte that ends an image (the PCI image length counts
# 512-byte blocks, so the bytes after the last table are 0xff fill up to that byte).
# 15 0xff bytes: the padding of every family. On every Ampere and Ada corpus image the power
# table's image ends with the table BIT token i+0x6a names, an 8-byte header with no
# entries; the fill after it runs from 0 to 498 bytes across the corpus. Fewer than 15
# fill bytes after that exact header (RTX 3060 Laptop 94.06.22, RTX 3050 6GB 94.07.91 and
# RTX 4070 Laptop 95.06.15: 0, 2 and 3) are the second tail; 15 or more are the first.
CHECKSUM_PADDING = b'\xff' * 15
EMPTY_TABLE_TAIL = bytes.fromhex('10 08 00 00 00 00 00 00')
# Ampere GA10x variants. Power: 30/2c/47, its 0x43-byte rows (the same bytes
# 0..0x42; 0x47 only adds four zero bytes) and the 30/32/47 header with six more
# bytes. Rails: one (NVVDD) or two (NVVDD, MSVDD) 17-byte rows, the first 17
# bytes of the Ada row. VFE: 24-byte equations, u8 count and links (0xff = none).
AMPERE_POWER_VARIANTS = ((0x30, 0x2C, 0x47), (0x30, 0x2C, 0x43), (0x30, 0x32, 0x47))
AMPERE_RAIL_HEADERS = {bytes.fromhex('20 05 11 01 00'): 1, bytes.fromhex('20 05 11 02 01'): 2}
AMPERE_RAIL_NAMES = ('NVVDD', 'MSVDD')
AMPERE_VFE_PREFIX = bytes.fromhex('30 09 19 32 18')
# Clocks table C+8 v0x40, GV HAL (byte 6 = 3), header size 0x0b or 0x0c, 13-byte
# rows and one 3-byte rail sub-entry per rail (byte 5). Rows as ADA_CLOCK_ROWS
# except the VID sub-entry type (2).
AMPERE_CLOCK_RAIL_TYPES = {'VID': 2}
# Power channel entry bytes 2..7 of a single input channel: 12 V (u32 uV) and 0x1000.
CHANNEL_12V = bytes.fromhex('00 1b b7 00 00 10')
# Rails of the external 12 V connector sense channels. Names are inferred: rated
# values 150-175 W on 0xfa/0xfb/0xe4 and 75-87.5 W on 0xfc suggest the PCIe CEM
# 8-pin/6-pin ratings, but one connector can span several channels (A6000/A40
# EPS 8-pin: two; RTX 3090 Ti 16-pin: three).
AMPERE_CONNECTOR_RAILS = (0xFA, 0xFB, 0xFC, 0xE4)
# Power channel relationship weight 1.0 (bytes 2..5 of a relationship entry, see relationships()).
UNIT_WEIGHT = bytes.fromhex('00 10 00 00')
# Turing power policy 30/2c/42 and 30/27/42 (the first 0x27 header bytes of 30/2c/42),
# rows 0..0x41 as Ampere's. The power channel table has 20 entries of 22 bytes; the TGP
# row reads the board-total channel (class-2 sum on rail 0xf5), which is channel 9 on
# the desktop TU10x/TU116 images (channel 0 there is another sum) and 0 on TU117 and laptops.
# Turing connector channels may hold a current correction offset in bytes 10..13 (nvgpu
# curr_corr_offset; 200 and 300 on the RTX 2070 connector channels).
TURING_POWER_VARIANTS = ((0x30, 0x2C, 0x42), (0x30, 0x27, 0x42))
# Turing rail table: one nvgpu 1x row of 14 bytes (vbios_voltage_rail_table_1x_entry):
# REL +4, ALT +5, OV +6, power equation +7, boot voltage equation +8, VMIN limit
# equation +9, voltage margin limit equation +10 (u8, 0xff = absent; the margin is
# absent on every image). VFE as Ampere (24-byte equations, u8 count and links) with
# 20 variables.
TURING_RAIL_HEADER = bytes.fromhex('10 05 0e 01 00')
TURING_VFE_PREFIX = bytes.fromhex('30 09 19 14 18')
TURING_ROLE_OFFSETS = (('REL', 4), ('ALT', 5), ('OV', 6))
TURING_BOOT_OFFSET, TURING_VMIN_OFFSET, TURING_MARGIN_OFFSET = 8, 9, 10
# Turing clocks table C+8 v0x35 (nvgpu vbios_clocks_table_35): ten 11-byte rows in the
# GV HAL order, each (name, usage, ordering byte). Usage 1 (master) rows store the
# signed MHz offset minimum/maximum at bytes 3/5; usage 2 (slave) rows store other
# parameters there.
TURING_CLOCK_HEADER = bytes.fromhex('35 09 0b 0a 03 e8 03 00 00')
TURING_CLOCK_ROWS = (('GPC', 1, 0x13), ('XBAR', 2, 0x24), ('DRAM', 1, 0x62), ('SYS', 2, 0x35), ('HUB', 2, 0x71),
                     ('VID', 2, 0x46), ('PWR', 0, 0xFF), ('DISP', 1, 0x80), ('PCIEGEN', 2, 0x08), ('HOST', 2, 0x57))
# Turing fan tables: the Ada cooler and mapping tables and a v0x10 policy table with
# its own channel list (header bytes 4..5) and two 54-byte entries. Policy entries keep
# the Ada entry layout three bytes later (entry byte 5 = Ada byte 2), so the Ada curve
# offsets apply from entry + 3; every active entry holds TURING_POLICY_BYTES at bytes
# 9..16 (Ada entry bytes 6..13, the same bytes on most Ada and Ampere images).
# The P token ends before the control and speed table pointers (0xdc, 0xe0).
TURING_FAN_TABLES = {
    'cooler': ADA_FAN_TABLES['cooler'],
    'policy': (0x5C, bytes((0x10, 6, 0x36, 2)), 6, 0x36, 2),
    'mapping': ADA_FAN_TABLES['mapping'],
}
TURING_CURVE_SHIFT = 3
TURING_POLICY_BYTES = bytes.fromhex('23 2b 0a 01 00 02 80 00')
# Tables the Turing fields write: power policy, VFE, fans, the thermal policy table, the
# factory clock record and the PERF_CF and LPWR tables, all in the second data image. The clock
# table sits in the legacy image, which lacks the padding on one RTX 2080 image; the clock
# fields check it themselves (padded), so power stays editable.
TURING_EDITED_TABLES = ((('P', 0x2C), ('P', 0x20), ('P', 0x58), ('P', 0x5C), ('P', 0x64), ('P', 0x50), ('P', 0x98)) +
                        ADVANCED_TABLES)


def checksum_tail(blob, end, family):
    """Number of reviewed tail bytes before the checksum byte blob[end - 1] of an image, or None.

    The editor repairs an image's additive checksum by rewriting only that byte, and only
    after one of these tails: 15 0xff bytes, or on Ampere and Ada the empty closing table
    (EMPTY_TABLE_TAIL) and 0..14 0xff bytes. Callers also require the image to sum to 0
    (integrity valid) and refuse fields that write tail bytes.
    """
    if blob[end - 16:end - 1] == CHECKSUM_PADDING:
        return len(CHECKSUM_PADDING)
    if family not in ('ampere', 'ada'):
        return None
    fill = 0
    while fill < len(CHECKSUM_PADDING) and blob[end - 2 - fill] == 0xFF:
        fill += 1
    header = end - 1 - fill - len(EMPTY_TABLE_TAIL)
    if fill < len(CHECKSUM_PADDING) and blob[header:end - 1 - fill] == EMPTY_TABLE_TAIL:
        return len(EMPTY_TABLE_TAIL) + fill
    return None


# A profile of the Ada override table that no cable sense code selects still bounds a power edit, relaxed by
# this factor (owner's choice): half its value as a lower bound, twice it as an upper one.
UNREACHED_PROFILE_FACTOR = 2


class TableRom:
    def __init__(self, blob, name='<memory>', *, family='ada'):
        self.family = family
        self.blob, self.name = bytes(blob), str(name)
        self.pci_images, self.extended_images, issues = scan_images(self.blob)
        if issues:
            raise FormatError('invalid image boundaries', details={'issues': issues})
        self.chains = image_chains(self.blob, self.pci_images, self.extended_images, family=family)
        if not self.chains:
            raise FormatError('no complete NVIDIA PCI/NPDS image chain')
        identities = {(c[0]['vendor'], c[0]['device']) for c in self.chains}
        if len(identities) != 1:
            raise FormatError('archive contains different legacy PCI identities')
        # Ampere chains may lack the EFI image (laptop and headless dumps).
        self.legacy = self.chains[0][0]
        self.efi = self.chains[0][1] if self.chains[0][1]['type'] == 3 else None
        self.chain_end = self.chains[0][-1]['end']
        self.tokens = parse_bit(self.blob, self.legacy)
        if self.tokens.get('P', {}).get('version') != 2:
            raise FormatError('BIT performance token must be version 2')
        self.image_regions = [(p['start'], p['end']) for c in self.chains for p in c]
        self.directory, self.objects = None, []
        self._integrity = self._padding = None

    def pointer(self, token, offset):
        entry = self.tokens.get(token)
        if not entry or offset < 0 or offset + 4 > entry['size']:
            raise FormatError('table pointer outside BIT token')
        if token in ('P', 'C') and entry['version'] != 2:
            raise FormatError('unsupported BIT pointer-token version')
        pointer = read(self.blob, '<I', entry['data'] + offset)[0]
        if not pointer:
            raise FormatError('requested table is absent')
        at = self.legacy['start'] + pointer
        if pointer >= self.legacy['size'] and self.efi is not None:
            at += self.efi['size']
        self.owner(at, 16)
        return at

    def owner(self, at, size):
        # The type-0x70 image that ends a Turing chain is never a table owner: no table is read from it.
        owners = [p for p in self.chains[0] if p['start'] <= at and at + size <= p['end'] and p['type'] != 0x70]
        if len(owners) != 1:
            raise FormatError('table is outside or crosses a primary image boundary')
        return owners[0]

    def integrity(self):
        if self._integrity is None:
            # The blob is immutable; callers receive their own copy of the result.
            sums = [dict(start=p['start'], end=p['end'], checksum=sum(self.blob[p['start']:p['end']]) & 255)
                    for c in self.chains for p in c]
            primary = self.blob[self.legacy['start']:self.chain_end]
            same = all(self.blob[c[0]['start']:c[-1]['end']] == primary for c in self.chains)
            self._integrity = dict(valid=all(p['checksum'] == 0 for p in sums) and same,
                                   image_checksums=sums, duplicate_image_chains_identical=same,
                                   cryptographic_signature='not verified',
                                   sha384_object_directory='not recognized in this table layout')
        return copy.deepcopy(self._integrity)

    def checksum_padding_reviewed(self):
        """True when every data image holding an edited table ends with a reviewed tail and its checksum.

        The editor repairs the additive checksum only after the tails checksum_tail accepts:
        15 0xff bytes or, on Ampere and Ada, the empty closing table and fewer 0xff bytes
        (the last data image of the RTX 4070 Laptop and RTX 3060 Laptop images, for example).
        """
        if self._padding is None:
            self._padding = self._checksum_padding()
        return self._padding

    def _checksum_padding(self):
        # Ada fields also write the rail table (P+0x68), which lies in the legacy image.
        tables = (TURING_EDITED_TABLES if self.family == 'turing' else
                  ADA_EDITED_TABLES + ((('P', 0x68),) if self.family == 'ada' else ()))
        for token, offset in tables:
            try:
                at = self.pointer(token, offset)
            except FormatError:
                continue
            if not self.padded(at):
                return False
        return True

    def padded(self, at):
        """True when the data image holding at ends with a reviewed tail (checksum_tail) in every chain."""
        image = self.owner(at, 1)
        return all(checksum_tail(self.blob, copy + image['size'], self.family) is not None
                   for copy in self.copy_offsets(image['start'], image['size']))

    def power_rows(self):
        at = self.pointer('P', 0x2C)
        version, hs, size, count = self.blob[at:at + 4]
        variants = {'ampere': AMPERE_POWER_VARIANTS, 'turing': TURING_POWER_VARIANTS}.get(self.family, ADA_POWER_VARIANTS)
        if (version, hs, size) not in variants or not count:
            raise FormatError('unvalidated 3x power table variant')
        self.owner(at, hs + size * count)
        index, self.notebook_power = self.blob[at + 10], False
        if self.blob[at + 10:at + 14] == bytes((0xFF, 0xFF, 0xFF, 2)):
            # Notebook header: no TGP index (byte 10); the D-notifier index (byte 13,
            # nvgpu header field order tgp/rtp/mxm/dnotifier) names the TGP row.
            index, self.notebook_power = self.blob[at + 13], True
        if index >= count:
            raise FormatError('TGP policy index exceeds power rows')
        self.tgp_index, self.power_entry_size = index, size
        rows = []
        for i in range(count):
            row = at + hs + i * size
            lo, default, hi = read(self.blob, '<III', row + 2)
            rows.append(dict(row=i, type=self.blob[row] & 15, flags=self.blob[row], offset=row,
                             minimum_raw=lo, default_raw=default, maximum_raw=hi,
                             maximum_offset=row + 10, limit_unit='mA' if self.blob[row] & 0x10 else 'mW'))
        tgp = rows[index]
        if tgp['type'] != 1 or tgp['limit_unit'] != 'mW' or not 0 <= tgp['minimum_raw'] <= tgp['default_raw'] <= tgp['maximum_raw']:
            raise FormatError('TGP policy has unknown identity, units, or inconsistent bounds')
        # The TGP row reads channel 0, the class-2 sum on rail 0xf5 (the total
        # board power monitor in the reviewed Ada and GB20x GET readings). On
        # Turing it reads the only such channel, wherever the table puts it.
        channel = self.blob[tgp['offset'] + 1]
        if self.family == 'turing':
            count = self.blob[self.pointer('P', 0x3C) + 3]
            total = [i for i in range(count) if self.power_channel(i)[:2] == b'\x02\xf5'] == [channel]
        else:
            total = channel == 0 and self.power_channel(0)[:2] == b'\x02\xf5'
        if not total:
            raise FormatError('TGP policy does not read the total board power channel (class 2, rail 0xf5)')
        return rows

    def power_channel(self, index):
        """One entry of the power channel table (P+0x3c, v0x20, 32 entries).

        Ada entries are 26 bytes; Ampere entries are 22 or 26 bytes (the last four zero).
        Turing has 20 entries of 22 bytes.
        """
        at = self.pointer('P', 0x3C)
        version, hs, size, count = self.blob[at:at + 4]
        sizes, entries = {'ampere': ((0x16, 0x1A), 0x20), 'turing': ((0x16,), 0x14)}.get(self.family, ((0x1A,), 0x20))
        if version != 0x20 or hs not in (6, 0x0A) or size not in sizes or count != entries:
            raise FormatError(f"unvalidated {'Turing' if self.family == 'turing' else 'Ada'} power channel table")
        self.owner(at, hs + size * count)
        if not 0 <= index < count:
            raise FormatError('power channel index is outside the table')
        start = at + hs + size * index
        return self.blob[start:start + size]

    def ada_policy(self, role):
        """The unique power row with the reviewed Ada shape and channel of role, or None.

        Roles: slot_power, slot_current, input_current_0/1, nvvdd_power and
        nvvdd_current (see ADA_POLICIES). Limits are not pinned; the row must keep
        0 <= minimum <= rated <= maximum. Offsets are those of the primary chain.
        same_channel_rows lists every other row of the same class and unit that
        reads a byte-identical channel entry, whatever its shape: such a row may
        bind instead of this one (the RTX 4060 has a second NVVDD power threshold).
        """
        if self.family != 'ada':
            return None
        templates, channel, units = ADA_POLICIES[role]
        rows, size = self.power_rows(), self.power_entry_size
        found = []
        for row in rows:
            raw = self.blob[row['offset']:row['offset'] + size]
            # A 0x4b entry is hashed as the 0x53 entry it truncates (eight more zero bytes).
            tail = raw[14:ADA_POWER_ENTRY].ljust(ADA_POWER_ENTRY - 14, b'\0')
            digest = hashlib.sha256(raw[:2] + tail).hexdigest()
            if digest in templates and not any(raw[ADA_POWER_ENTRY:]):
                found.append((row, digest))
        if len(found) != 1:
            return None
        row, digest = found[0]
        index = self.blob[row['offset'] + 1]
        if (self.power_channel(index) != channel or
                not 0 <= row['minimum_raw'] <= row['default_raw'] <= row['maximum_raw']):
            return None
        same = []
        for other in rows:
            at = other['offset']
            if (other['row'] != row['row'] and other['type'] == row['type'] and
                    other['limit_unit'] == row['limit_unit'] and self.blob[at + 1] < 0x20 and
                    self.power_channel(self.blob[at + 1]) == channel):
                same.append(dict(row=other['row'], parameter_byte_0=self.blob[at + 14],
                                 minimum_raw=other['minimum_raw'], default_raw=other['default_raw'],
                                 maximum_raw=other['maximum_raw'], units=other['limit_unit']))
        return dict(row, vbios_row_index=row['row'], immutable_row_sha256=digest, units=units,
                    channel_index=index, minimum_offset=row['offset'] + 2, default_offset=row['offset'] + 6,
                    same_channel_rows=same)

    def ada_connector_policies(self):
        """Ada auxiliary power connector input rows (class 4 mW), in row order, as ada_policy items.

        A row qualifies by ADA_CONNECTOR_SHAPE (the slot_power shape without its
        channel byte) and a connector input channel: one that channel 0 adds with
        weight 1.0 (relationships), a class-5 single input at 12 V on an
        ADA_CONNECTOR_RAILS rail with bytes 8..14 and 16..25 zero and the provider
        byte 15 at 0..2. Notebook images (notebook_power) give no row: their DC
        input channel holds the same bytes. Limits are not pinned; the row must
        keep 0 <= minimum <= rated <= maximum. same_channel_rows lists every other
        row of the same class and unit on a byte-identical channel entry, as in
        ada_policy; threshold_rows the class-5 mA rows (hardware current
        thresholds) on it; unrecognized_rows the class-4 mW rows on another
        connector input channel that do not qualify (they may bind instead).
        """
        if self.family != 'ada':
            return []
        rows, size = self.power_rows(), self.power_entry_size
        if self.notebook_power:
            return []
        inputs = {r[1] for r in self.relationships(0) if r[0] == 1 and r[2:6] == UNIT_WEIGHT}

        def connector_input(index):
            if index not in inputs or index >= 0x20:
                return False
            channel = self.power_channel(index)
            return (channel[0] == 5 and channel[1] in ADA_CONNECTOR_RAILS and channel[2:8] == CHANNEL_12V and
                    not any(channel[8:15]) and channel[15] in (0, 1, 2) and not any(channel[16:]))

        def entry(o):
            return dict(row=o['row'], parameter_byte_0=self.blob[o['offset'] + 14], minimum_raw=o['minimum_raw'],
                        default_raw=o['default_raw'], maximum_raw=o['maximum_raw'], units=o['limit_unit'])

        def on(channel, o):
            return self.blob[o['offset'] + 1] < 0x20 and self.power_channel(self.blob[o['offset'] + 1]) == channel
        accepted = []
        for row in rows:
            raw = self.blob[row['offset']:row['offset'] + size]
            tail = raw[14:ADA_POWER_ENTRY].ljust(ADA_POWER_ENTRY - 14, b'\0')
            if (hashlib.sha256(raw[:1] + tail).hexdigest() == ADA_CONNECTOR_SHAPE and not any(raw[ADA_POWER_ENTRY:])
                    and connector_input(raw[1]) and 0 <= row['minimum_raw'] <= row['default_raw'] <= row['maximum_raw']):
                accepted.append((row, raw, tail))
        own = {row['row'] for row, _, _ in accepted}
        loose = [o for o in rows if o['type'] == 4 and o['limit_unit'] == 'mW' and o['row'] not in own and
                 self.blob[o['offset'] + 1] < 0x20 and connector_input(self.blob[o['offset'] + 1])]
        result = []
        for row, raw, tail in accepted:
            index = raw[1]
            channel = self.power_channel(index)
            same = [entry(o) for o in rows if o['row'] != row['row'] and o['type'] == row['type'] and
                    o['limit_unit'] == row['limit_unit'] and on(channel, o)]
            thresholds = [entry(o) for o in rows if o['type'] == 5 and o['limit_unit'] == 'mA' and on(channel, o)]
            unrecognized = [dict(entry(o), channel_index=self.blob[o['offset'] + 1],
                                 channel_rail=self.power_channel(self.blob[o['offset'] + 1])[1])
                            for o in loose if not on(channel, o)]
            result.append(dict(row, vbios_row_index=row['row'], units='mW', channel_index=index,
                               channel_rail=channel[1], immutable_row_sha256=hashlib.sha256(raw[:2] + tail).hexdigest(),
                               minimum_offset=row['offset'] + 2, default_offset=row['offset'] + 6,
                               same_channel_rows=same, threshold_rows=thresholds, unrecognized_rows=unrecognized))
        return result

    def ampere_policies(self, role):
        """Ampere and Turing power rows of one role, identified by class, unit and power channel.

        Roles: slot_power (class 4 mW) and slot_current (class 5 mA) on the PCIe
        slot channel (byte-identical to the Ada SLOT_CHANNEL); connector_power (class
        4 mW) and connector_current (class 5 mA) on the external connector channels
        (AMPERE_CONNECTOR_RAILS); Ampere only: input_current (class 5 mA) on the 12 V
        input channel, rail 0xe0, nvvdd_current (class 0 mA) on an NVVDD output
        channel (class 1, rail 1), and connector_sum (class 4 mW) on a class-2 channel
        that adds at least two distinct connector channels and nothing else, each with
        weight 1.0 (relationships() gives the entry layout; the sum reads rail 0xe0 or
        0xe4, so it is identified by its members, not by its rail), with the 12 V bytes
        of its members and no other parameter (other class-2 sums of connector channels
        hold another value in bytes 6..7); Turing only: nvvdd_current_limit
        (class 10 mA) on the channel whose 22 bytes equal the Ada NVVDD current
        sensor channel, and nvvdd_threshold (class 5 mA) on an NVVDD channel with
        sensor byte 14 = 5. Input channels are class 5 at 12 V with no parameter but
        the provider byte 15 (Turing connector channels: and the current correction
        offset, bytes 10..13). On Turing a slot_power row may also be class 1 mW, the
        TGP's class (one MSI GTX 1650 image); the TGP row itself is never a role row.
        Rows must keep 0 <= minimum <= rated <= maximum, as on Ada.
        Returns ada_policy-style items in row order; same_channel_rows lists other
        rows of the same class and unit on a byte-identical channel, and
        summed_cap_rows those on a class-2 sum channel that adds this channel (the
        RTX 3080 Ti and RTX A6000 cap their connector channels together).
        """
        turing = self.family == 'turing'
        if self.family not in ('ampere', 'turing') or role in (
                ('nvvdd_current', 'input_current', 'connector_sum') if turing else
                ('nvvdd_current_limit', 'nvvdd_threshold')):
            return []
        cls, units = {'slot_power': (4, 'mW'), 'slot_current': (5, 'mA'), 'input_current': (5, 'mA'),
                      'connector_power': (4, 'mW'), 'connector_current': (5, 'mA'), 'connector_sum': (4, 'mW'),
                      'nvvdd_current': (0, 'mA'), 'nvvdd_current_limit': (10, 'mA'), 'nvvdd_threshold': (5, 'mA')}[role]
        rows, size = self.power_rows(), self.power_entry_size
        count = self.blob[self.pointer('P', 0x3C) + 3]

        def rail(index):
            e = self.power_channel(index)
            if role == 'nvvdd_current':
                return 1 if e[:2] == b'\x01\x01' else None
            if role == 'nvvdd_current_limit':
                return 1 if e == NVVDD_CURRENT_CHANNEL[:len(e)] else None
            if role == 'nvvdd_threshold':
                return 1 if e[:2] == b'\x01\x01' and e[14] == 5 else None
            parameters = e[8:10] + e[14:15] if turing and e[1] in AMPERE_CONNECTOR_RAILS else e[8:15]
            if e[0] != 5 or e[2:8] != CHANNEL_12V or any(parameters) or any(e[16:]) or (e[1] == 0xFF and e[15]):
                return None
            return e[1]
        wanted = {'slot_power': (0xFF,), 'slot_current': (0xFF,), 'input_current': (0xE0,),
                  'connector_power': AMPERE_CONNECTOR_RAILS, 'connector_current': AMPERE_CONNECTOR_RAILS,
                  'nvvdd_current': (1,), 'nvvdd_current_limit': (1,), 'nvvdd_threshold': (1,)}.get(role)

        def match(index):
            if role != 'connector_sum':
                return rail(index) in wanted
            entry, members = self.power_channel(index), self.relationships(index)
            channels = [r[1] for r in members]
            return (entry[0] == 2 and entry[2:8] == CHANNEL_12V and not any(entry[8:14]) and not any(entry[16:]) and
                    len(set(channels)) == len(channels) >= 2 and
                    all(r[0] == 1 and r[2:6] == UNIT_WEIGHT and not any(r[6:31]) and r[1] < count and
                        rail(r[1]) in AMPERE_CONNECTOR_RAILS for r in members))
        classes = (cls, 1) if turing and role == 'slot_power' else (cls,)
        found = [r for r in rows if r['type'] in classes and r['limit_unit'] == units and r['row'] != self.tgp_index and
                 self.blob[r['offset'] + 1] < count and match(self.blob[r['offset'] + 1]) and
                 0 <= r['minimum_raw'] <= r['default_raw'] <= r['maximum_raw']]
        sums = [(o, c, self.summed_channels(c)) for o in rows for c in (self.blob[o['offset'] + 1],)
                if o['type'] in classes and o['limit_unit'] == units and o['row'] != self.tgp_index and c < count]
        result = []
        for row in found:
            index = self.blob[row['offset'] + 1]
            channel = self.power_channel(index)
            raw = self.blob[row['offset']:row['offset'] + size]
            same = [dict(row=o['row'], parameter_byte_0=self.blob[o['offset'] + 14], minimum_raw=o['minimum_raw'],
                         default_raw=o['default_raw'], maximum_raw=o['maximum_raw'], units=o['limit_unit'])
                    for o in rows if o['row'] != row['row'] and o['type'] == row['type'] and
                    o['limit_unit'] == units and self.blob[o['offset'] + 1] < count and
                    self.power_channel(self.blob[o['offset'] + 1]) == channel]
            summed = [dict(row=o['row'], channel_index=c, summed_channels=members, minimum_raw=o['minimum_raw'],
                           default_raw=o['default_raw'], maximum_raw=o['maximum_raw'], units=o['limit_unit'])
                      for o, c, members in sums if index in members and o['type'] == row['type']]
            result.append(dict(row, vbios_row_index=row['row'], units=units, channel_index=index,
                               channel_rail=channel[1],
                               immutable_row_sha256=hashlib.sha256(raw[:2] + raw[14:]).hexdigest(),
                               minimum_offset=row['offset'] + 2, default_offset=row['offset'] + 6,
                               same_channel_rows=same, summed_cap_rows=summed))
        return result

    def ampere_nvvdd_rows(self):
        """Ampere power rows on an NVVDD channel (channel bytes 0..1 = 01 01: class 1, rail 1), in row order.

        Every class and unit, values unchecked; each row adds channel_index. On the Ampere
        corpus these are row 13 (and rows 12 and 18 on most images) on the NVVDD output
        current channel 19 (sensor byte 14 = 6) and rows 16 and 17 on channel 18 (sensor
        byte 14 = 5). The TGP row is never one.
        """
        if self.family != 'ampere':
            return []
        count = self.blob[self.pointer('P', 0x3C) + 3]
        return [dict(row, channel_index=index) for row in self.power_rows()
                for index in (self.blob[row['offset'] + 1],)
                if row['row'] != self.tgp_index and index < count and self.power_channel(index)[:2] == b'\x01\x01']

    def relationships(self, index):
        """Relationship entries of a class-2 power channel (its bytes 14..15: first..last entry), else [].

        The relationship table follows the channel entries (header bytes 4/5: entry
        size and count; 46 or 31 bytes on Ampere). Every entry a sum names on the
        Ampere corpus holds 1 in byte 0, a channel index in byte 1, a signed 32-bit
        weight in bytes 2..5 and zeros in bytes 6..30. The weight reads as 20.12 fixed
        point (inferred): 0x1000 = 1.0 on most entries, 0xfffff000 = -1.0 on the others
        (channel 12 subtracts channel 11 on most images). Bytes 31..45 of a 46-byte
        entry hold a second record of unknown meaning.
        """
        at = self.pointer('P', 0x3C)
        hs, size, count, rsize, rcount = self.blob[at + 1:at + 6]
        entry = self.power_channel(index)
        if entry[0] != 2 or rsize < 2 or not entry[14] <= entry[15] < rcount:
            return []
        base = at + hs + size * count
        self.owner(base, rsize * rcount)
        return [self.blob[base + rsize * i:base + rsize * (i + 1)] for i in range(entry[14], entry[15] + 1)]

    def summed_channels(self, index):
        """Channels a class-2 power channel adds: byte 1 of its relationship entries, weights ignored."""
        return [r[1] for r in self.relationships(index)]

    def profile_table(self):
        """Offset of the power profile table, or None when the P token has no (or a null) pointer.

        The 0xfc-byte Ampere P token (GA104 3060 Ti GDDR6X, GA106 3060 8GB, GA107)
        stores a null pointer at P+0xF4: no profiles.
        """
        if self.tokens['P']['size'] < 0xF8:
            # This observed Ampere BIT version has no profile-table pointer.
            return None
        if self.family == 'ampere' and not read(self.blob, '<I', self.tokens['P']['data'] + 0xF4)[0]:
            return None
        return self.pointer('P', 0xF4)

    def power_profiles(self):
        """Enabled override profiles of the power table (P+0xF4), decoded on Ada only (see PROFILE_HEADER).

        Each profile is {index, offset, entries}; an entry is {policy, field ('maximum' or
        'default'), value_raw, value_offset} (primary chain). An Ada image with enabled
        profiles must also hold the reviewed selection chain (profile_selection). Shapes
        are strict: flag 1, contiguous {01, selector, value} entries, fields 0/1, a policy
        row of the table, no duplicate, disabled profiles and unused entries all zero.
        Anything else, and nonempty profiles on Ampere or Turing, raise FormatError.
        """
        at = self.profile_table()
        if at is None:
            return []
        if self.blob[at:at + 10] != PROFILE_HEADER:
            raise FormatError('unvalidated power profile header')
        self.owner(at, PROFILE_BYTES)
        if not any(self.blob[at + 0xFE:at + PROFILE_BYTES]):
            return []
        if self.family != 'ada':
            raise FormatError('nonempty override profiles are reviewed on Ada only')
        count = len(self.power_rows())
        profiles = []
        for i in range(16):
            row = at + 0xFE + i * 0x49
            if not any(self.blob[row:row + 0x49]):
                continue
            if self.blob[row] != 1:
                raise FormatError('unsupported Ada override profile flag')
            entries, seen, ended = [], set(), False
            for j in range(8):
                entry = row + 1 + j * 9
                if not any(self.blob[entry:entry + 9]):
                    ended = True
                    continue
                selector, value = read(self.blob, '<II', entry + 1)
                policy, field = selector & 0xFF, selector >> 8
                # The firmware stops at the first unused entry and rejects a used one after it.
                if ended or self.blob[entry] != 1 or field not in ADA_PROFILE_FIELDS or policy >= count:
                    raise FormatError('unsupported Ada override profile entry')
                if (policy, field) in seen:
                    raise FormatError('duplicate Ada override profile entry')
                seen.add((policy, field))
                entries.append(dict(policy=policy, field=ADA_PROFILE_FIELDS[field], value_raw=value,
                                    value_offset=entry + 5))
            if not entries:
                raise FormatError('Ada override profile without entries')
            profiles.append(dict(index=i, offset=row, entries=entries))
        self.profile_selection(profiles)
        return profiles

    def profile_selection(self, profiles=None):
        """{sense code: profile index or None} through the reviewed Ada selection chain (ADA_SELECTION_HEADERS).

        None means no vote (the firmware then fails the power manager setup) or no
        threshold reached. Raises FormatError for any other selection layout: other row
        headers, a used row 2 or 3, codes other than exactly 0..3, a profile byte on a
        sense entry, a threshold param other than 0xff, thresholds not strictly
        ascending or naming a disabled profile.
        """
        at, b = self.profile_table(), self.blob
        profiles = self.power_profiles() if profiles is None else profiles
        starts = [at + 0x0A + 0x3D * k for k in range(4)]
        if (any(b[s:s + 5] != header for s, header in zip(starts, ADA_SELECTION_HEADERS)) or
                any(b[s:s + 0x3D] != bytes(5) + SELECTION_UNUSED * 8 for s in starts[2:])):
            raise FormatError('unrecognized Ada override profile selection rows')

        def entries(row):
            out, ended = [], False
            for j in range(8):
                e = b[row + 5 + 7 * j:row + 12 + 7 * j]
                if e == SELECTION_UNUSED:
                    ended = True
                    continue
                if ended or e[0] != 1:
                    raise FormatError('unrecognized Ada override profile selection entry')
                out.append((e[1], read(e, '<I', 2)[0], e[6]))
            return out
        sense, thresholds = entries(starts[0]), entries(starts[1])
        if (sorted(code for _, _, code in sense) != [0, 1, 2, 3] or any(p != 0xFF for p, _, _ in sense) or
                any(param != 0xFF for _, _, param in thresholds)):
            raise FormatError('unrecognized Ada override profile selection entry')
        values, enabled = [value for _, value, _ in thresholds], {p['index'] for p in profiles}
        if not values or values != sorted(set(values)) or any(p not in enabled for p, _, _ in thresholds):
            raise FormatError('Ada override profile thresholds are not ascending or name a disabled profile')
        levels = {}
        for _, vote, code in sense:
            reached = [p for p, value, _ in thresholds if value <= vote] if vote else []
            levels[code] = reached[-1] if reached else None
        return levels

    def top_power_profile(self):
        """The enabled profile the top sense code selects (TOP_SENSE_CODE), with selection_code and
        selection_power_raw (that code's vote), or None (no profiles, or no profile at that level)."""
        profiles = self.power_profiles()
        if not profiles:
            return None
        index = self.profile_selection(profiles)[TOP_SENSE_CODE]
        if index is None:
            return None
        at = self.profile_table() + 0x0A + 5
        vote = next(read(self.blob, '<I', at + 7 * j + 2)[0] for j in range(8)
                    if self.blob[at + 7 * j + 6] == TOP_SENSE_CODE)
        return dict(next(p for p in profiles if p['index'] == index), selection_code=TOP_SENSE_CODE,
                    selection_power_raw=vote)

    def matching_power_profiles(self):
        """The profiles written together with the base table: on Ada, the top-level profile when every
        entry equals the base value it replaces. The other profiles replace the base at their own
        sense level whatever their values, so they are never written with it."""
        top = self.top_power_profile()
        if top is None:
            return []
        rows = self.power_rows()
        return [top] if all(e['value_raw'] == rows[e['policy']][e['field'] + '_raw'] for e in top['entries']) else []

    def profile_binding(self, policies):
        """How the Ada override profiles bind the power rows policies for an edit of their base values.

        None when the image has no enabled profile. Raises FormatError unless the top
        sense level selects a profile equal to the base table (matching_power_profiles).
        tied: {'maximum'|'default': value offsets, every duplicate chain} of the top
        profile's entries on these rows, written with the base. The other profiles'
        entries on these rows bound an edit: values (lower bounds) for the ceiling to
        stay at or above, defaults (their rated values) for the rated value, ceilings
        (upper bounds) for the floor to stay at or below. A profile no sense code
        reaches (UNREACHED_PROFILE_FACTOR) bounds it with half its value as a lower
        bound and twice it as an upper one; a profile a code reaches, with its value.
        entries: the stored values, per field, as (profile index, value). outside: the
        other profiles whose bound the stored base row breaks (its floor above an upper
        bound, its ceiling or rated value below a lower one), where the stored values
        could not be requested again. unreached: the profiles no sense code selects.
        """
        profiles = self.power_profiles()
        if not profiles:
            return None
        matching = self.matching_power_profiles()
        if not matching:
            raise FormatError('the top sense level of the Ada override profiles selects no profile equal to the '
                              'base table')
        top, rows = matching[0], self.power_rows()
        tied, values, defaults, ceilings, outside = {'maximum': [], 'default': []}, [], [], [], set()
        entries = {'maximum': [], 'default': []}
        reached = {index for index in self.profile_selection(profiles).values() if index is not None}
        for p in profiles:
            for e in p['entries']:
                if e['policy'] not in policies:
                    continue
                if p['index'] == top['index']:
                    tied[e['field']].extend(self.copy_offsets(e['value_offset'], 4))
                    continue
                row, value = rows[e['policy']], e['value_raw']
                factor = 1 if p['index'] in reached else UNREACHED_PROFILE_FACTOR
                values.append(value // factor)
                ceilings.append(value * factor)
                entries[e['field']].append((p['index'], value))
                if e['field'] == 'default':
                    defaults.append(value // factor)
                # The stored base values must satisfy the same bounds, so they can be requested again.
                if (row['minimum_raw'] > value * factor or row['maximum_raw'] < value // factor or
                        e['field'] == 'default' and row['default_raw'] < value // factor):
                    outside.add(p['index'])
        return dict(top=top['index'], tied=tied, values=values, defaults=defaults, ceilings=ceilings,
                    entries=entries, outside=sorted(outside), unreached=sorted(
                        {p['index'] for p in profiles if p['index'] not in reached and p['index'] != top['index']}))

    def clock_ranges(self):
        at = self.pointer('C', 8)
        b = self.blob
        if self.family == 'turing':
            return self._turing_clock_ranges(at)
        if self.family == 'ampere':
            # Header size 0x0b (no trailing byte) or 0x0c; one 3-byte rail sub-entry per rail.
            if (b[at] != 0x40 or b[at + 1] not in (0x0B, 0x0C) or b[at + 2:at + 5] != bytes((0x0D, 0x0A, 3)) or
                    b[at + 5] not in (1, 2) or b[at + 6:at + 9] != bytes.fromhex('03 e8 03')):
                raise FormatError('unvalidated clock table variant')
        elif self.blob[at:at + len(ADA_CLOCK_HEADER)] != ADA_CLOCK_HEADER:
            raise FormatError('unvalidated clock table variant')
        hs, size, count, subcount, subsize = self.blob[at + 1:at + 6]
        stride = size + subcount * subsize
        self.owner(at, hs + stride * count)
        if self.tokens['C']['size'] >= 0x24 and self.pointer('C', 0x20) != at + hs + stride * count:
            raise FormatError(('Ada' if self.family == 'ada' else 'Ampere') +
                              ' clock table does not end at the next C-token table')
        rows = []
        for i in range(count):
            row = at + hs + i * stride
            first, last = self.blob[row + 1:row + 3]
            lo, hi = read(self.blob, '<hh', row + 3)
            domain = self._ada_clock_row(i, row, size, b[at + 5])
            rows.append(dict(row=i, domain=domain, minimum_mhz=lo, maximum_mhz=hi,
                             minimum_offset=row + 3, maximum_offset=row + 5))
        return rows

    def dram_points(self):
        """Ada and Ampere: the DRAM entries of the clock programming table (C+0x0c, version 0x40).

        See structure.dram_points; the clocks table DRAM row names them. Turing (version
        0x35, another flag bit, signed digest list) is not covered.
        """
        if self.family not in ('ada', 'ampere'):
            raise FormatError('DRAM clock points are reviewed on Ada and Ampere only')
        rows = [r for r in self.clock_ranges() if r['domain'] == 'DRAM']
        if len(rows) != 1:
            raise FormatError('no single DRAM clock row')
        row = rows[0]['minimum_offset'] - 3
        at = self.pointer('C', 0x0C)
        result = dram_points(self.blob, at, self.blob[row + 1], self.blob[row + 2], 0x40)
        self.owner(at, result['size'])
        return result

    def gpc_curve(self):
        """Ada and Ampere: where a default GPC curve offset lives (structure.gpc_curve_slot).

        The clocks table GPC row names one clock programming entry (C+0x0c, version 0x40);
        its byte 3 (| byte 13 << 8 on the 15-byte Ada entries) is the root of the GPC VF
        curve in the VFE table (P+0x20). No other VFE-driven programming entry (flag low
        nibble 1) may name the same root. Turing is not covered.
        """
        if self.family not in ('ada', 'ampere'):
            raise FormatError('the GPC curve offset is reviewed on Ada and Ampere only')
        rows = [r for r in self.clock_ranges() if r['domain'] == 'GPC']
        if len(rows) != 1:
            raise FormatError('no single GPC clock row')
        row = rows[0]['minimum_offset'] - 3
        first, last = self.blob[row + 1], self.blob[row + 2]
        b, at = self.blob, self.pointer('C', 0x0C)
        hs, size, count, c1, s1, c2, s2 = b[at + 1:at + 8]
        stride = size + c1 * s1 + c2 * s2
        if b[at] != 0x40 or hs != 8 or size not in (13, 15) or first != last or first >= count:
            raise FormatError('unreviewed GPC clock programming entry')
        self.owner(at, hs + stride * count)

        def root_of(i):
            e = at + hs + stride * i
            return b[e + 3] | (b[e + 13] << 8 if size == 15 else 0)
        root = root_of(first)
        if any(root_of(i) == root for i in range(count) if i != first and b[at + hs + stride * i] & 0x0F == 1):
            raise FormatError('another clock programming entry names the GPC root')
        vfe = self.pointer('P', 0x20)
        if b[vfe:vfe + 5] not in (ADA_VFE_PREFIX, AMPERE_VFE_PREFIX):
            raise FormatError('unvalidated VFE dimensions')
        esize = b[vfe + 4]
        width = 2 if esize == 25 else 1
        vcount = b[vfe + 5] | (b[vfe + 10] << 8 if width == 2 else 0)
        base = vfe + b[vfe + 1] + b[vfe + 2] * b[vfe + 3]
        self.owner(vfe, base - vfe + esize * vcount)
        return gpc_curve_slot(b, base, esize, width, vcount, root)

    def clock_programming_vfe(self):
        """Ada: {entry: VFE equation index} of every clock programming entry (C+0x0c, version 0x40).

        The 15-byte Ada entries name an equation in byte 3 | byte 13 << 8 (0xffff on unused
        entries), as gpc_curve reads the GPC root; FormatError for any other layout.
        """
        if self.family != 'ada':
            raise FormatError('clock programming VFE indices are reviewed on Ada only')
        b, at = self.blob, self.pointer('C', 0x0C)
        if at + 8 > len(b):
            raise FormatError('clock programming table header exceeds the image')
        hs, size, count, c1, s1, c2, s2 = b[at + 1:at + 8]
        if b[at] != 0x40 or hs != 8 or size != 15:
            raise FormatError('unreviewed Ada clock programming table')
        stride = size + c1 * s1 + c2 * s2
        self.owner(at, hs + stride * count)
        return {i: b[e + 3] | b[e + 13] << 8 for i in range(count) for e in (at + hs + stride * i,)}

    def _turing_clock_ranges(self, at):
        """Rows of the Turing clocks table v0x35, gated by usage, ordering byte and fixed bytes.

        The nvgpu v35 row: usage (byte 0), programming entries (1..2), parameter 1
        (bytes 3..6: on a master row the signed MHz offset minimum/maximum),
        ordering (7), byte 8 = 0 and ff ff (9..10). range_stored marks the master
        rows; the slave rows (XBAR, SYS, VID, ...) follow another domain and store
        other parameters in bytes 3..6.
        """
        b = self.blob
        if b[at:at + len(TURING_CLOCK_HEADER)] != TURING_CLOCK_HEADER:
            raise FormatError('unvalidated clock table variant')
        hs, size, count = b[at + 1:at + 4]
        self.owner(at, hs + size * count)
        rows = []
        for i, (name, usage, ordering) in enumerate(TURING_CLOCK_ROWS):
            row = at + hs + size * i
            if b[row] != usage or b[row + 7] != ordering or b[row + 8] or b[row + 9:row + 11] != b'\xff\xff':
                raise FormatError(f'Turing clock row {i} does not match the GV HAL {name} row')
            lo, hi = read(b, '<hh', row + 3)
            rows.append(dict(row=i, domain=name, minimum_mhz=lo, maximum_mhz=hi, minimum_offset=row + 3,
                             maximum_offset=row + 5, range_stored=usage == 1))
        return rows

    def _ada_clock_row(self, i, row, size, rails=1):
        """GV HAL name of row i after its structural gates; raises on any mismatch.

        Ampere rows carry one 3-byte rail sub-entry per rail; exactly one of them
        has a nonzero type (none on PWR), the VID type is 2, and the HUB and DISP
        rows, which no field uses, may be fixed (usage 0, as on the RTX 2050).
        """
        b = self.blob
        name, usage, ordering, rail = ADA_CLOCK_ROWS[i]
        if self.family == 'ampere':
            rail = AMPERE_CLOCK_RAIL_TYPES.get(name, rail)
            active = [row + size + 3 * k for k in range(rails) if b[row + size + 3 * k]]
            if (b[row] not in ((0, usage) if name in ('HUB', 'DISP') else (usage,)) or b[row + 7] != ordering or
                    b[row + 8] not in ((0, 1) if name == 'DRAM' else (0,)) or b[row + 9:row + 11] != b'\xff\xff' or
                    [b[at] for at in active] != ([rail] if rail else []) or
                    (b[row] == 1 and rail == 1 and b[active[0] + 1:active[0] + 3] != b[row + 1:row + 3])):
                raise FormatError(f'Ampere clock row {i} does not match the GV HAL {name} row')
            return name
        if (b[row] != usage or b[row + 7] != ordering or b[row + 8] not in ((0, 1) if name == 'DRAM' else (0,)) or
                b[row + 9:row + 11] != b'\xff\xff' or b[row + size] != rail or
                (usage == 1 and rail == 1 and b[row + size + 1:row + size + 3] != b[row + 1:row + 3])):
            raise FormatError(f'Ada clock row {i} does not match the GV HAL {name} row')
        return name

    def _ada_rail(self):
        """Structural gates of the V20 rail row and the VFE equation table.

        Returns (rail row, VFE, equation base, equation count, selectors). The
        equation count is u16 header bytes 5 and 10. Selectors must address
        equations and keep the order REL < ALT (if present) < VMIN = OV - 1 found
        on every parseable Ada image and on the GET-reviewed GB20x rows, or the
        order the Ada follow-OV edit leaves: REL = OV, ALT absent or = OV.
        """
        rail, vfe = self.pointer('P', 0x68), self.pointer('P', 0x20)
        b = self.blob
        if b[rail:rail + 5] != ADA_RAIL_HEADER:
            raise FormatError('unvalidated rail layout; expected single V20 logic rail')
        if b[vfe:vfe + 5] != ADA_VFE_PREFIX:
            raise FormatError('unvalidated Ada VFE dimensions')
        self.owner(rail, 5 + 0x1F)
        row = rail + 5
        count = b[vfe + 5] | b[vfe + 10] << 8
        base = vfe + b[vfe + 1] + b[vfe + 2] * b[vfe + 3]
        if not count:
            raise FormatError('Ada VFE table has no equations')
        self.owner(vfe, base - vfe + 25 * count)
        return row, vfe, base, count, self._selectors(row, count)

    def _selectors(self, row, count):
        b = self.blob
        if self.family == 'turing':
            # nvgpu 1x row; Turing images keep REL < ALT (if present) < BOOT = OV - 1, VMIN = OV + 1
            # and no margin limit equation, which could select one of them. The Galax HOF XOC image
            # points REL and ALT at the OV equation instead (BOOT, VMIN and margin as stock).
            rel, alt, ov, boot, vmin = (b[row + k] for k in (4, 5, 6, TURING_BOOT_OFFSET, TURING_VMIN_OFFSET))
            ordered = rel < boot and (alt == 0xFF or rel < alt < boot)
            followed = rel == ov and alt in (0xFF, ov)
            if (0xFF in (rel, ov, boot, vmin) or vmin >= count or boot != ov - 1 or vmin != ov + 1 or
                    not (ordered or followed) or b[row + TURING_MARGIN_OFFSET] != 0xFF):
                raise FormatError('unvalidated Turing rail selectors (expected REL < ALT < BOOT or REL = ALT = OV, '
                                  'BOOT = OV - 1, VMIN = OV + 1, no margin limit)')
            return {'REL': rel, 'ALT': alt, 'OV': ov}
        selectors = {role: b[row + offset] for role, offset in ADA_ROLE_OFFSETS}
        rel, alt, ov, vmin = (selectors[k] for k in ('REL', 'ALT', 'OV', 'VMIN'))
        ordered = rel < vmin and vmin == ov - 1 and (alt == 0xFF or rel < alt < vmin)
        # The Ada follow-OV edit points REL and ALT (if present) at the OV equation.
        followed = self.family == 'ada' and rel == ov and alt in (0xFF, ov) and vmin == ov - 1
        if 0xFF in (rel, ov, vmin) or ov >= count or not (ordered or followed):
            family = 'Ada' if self.family == 'ada' else 'Ampere'
            raise FormatError(f'unvalidated {family} rail selectors (expected REL < ALT < VMIN = OV - 1)')
        return selectors

    def _rails(self):
        """([(rail index, inferred name, rail row, selectors)], VFE, equation base, equation count).

        Ada: the single logic rail. Ampere: one or two 17-byte V20 rows; the
        second is named MSVDD by inference only (the GPC clock row runs on rail
        0; XBAR, DRAM and DISP on rail 1). Turing: one 14-byte 1x row (NVVDD).
        The Ampere and Turing VFE count is u8 header byte 5. Every rail keeps the
        selector order of _selectors.
        """
        if self.family not in ('ampere', 'turing'):
            row, vfe, base, count, selectors = self._ada_rail()
            return [(0, 'NVVDD', row, selectors)], vfe, base, count
        rail, vfe = self.pointer('P', 0x68), self.pointer('P', 0x20)
        b = self.blob
        if self.family == 'turing':
            name, headers, size, prefix = 'Turing', {TURING_RAIL_HEADER: 1}, 0x0E, TURING_VFE_PREFIX
            layout = 'one 1x rail of 14 bytes'
        else:
            name, headers, size, prefix = 'Ampere', AMPERE_RAIL_HEADERS, 0x11, AMPERE_VFE_PREFIX
            layout = 'one or two V20 rails of 17 bytes'
        rails = headers.get(bytes(b[rail:rail + 5]))
        if not rails:
            raise FormatError(f'unvalidated {name} rail layout; expected {layout}')
        if b[vfe:vfe + 5] != prefix:
            raise FormatError(f'unvalidated {name} VFE dimensions')
        self.owner(rail, 5 + size * rails)
        count = b[vfe + 5]
        base = vfe + b[vfe + 1] + b[vfe + 2] * b[vfe + 3]
        if not count:
            raise FormatError(f'{name} VFE table has no equations')
        self.owner(vfe, base - vfe + 24 * count)
        rows = [rail + 5 + size * i for i in range(rails)]
        return ([(i, AMPERE_RAIL_NAMES[i], row, self._selectors(row, count)) for i, row in enumerate(rows)],
                vfe, base, count)

    def _role_offsets(self):
        """Selector roles of a rail row: the Turing 1x row has REL/ALT/OV; Ada and Ampere add the VMIN slot."""
        return TURING_ROLE_OFFSETS if self.family == 'turing' else ADA_ROLE_OFFSETS

    def _equation_layout(self):
        """(equation size, link width in bytes): Ada 25 bytes with u16 links, Ampere and Turing 24 with u8."""
        return (24, 1) if self.family in ('ampere', 'turing') else (25, 2)

    def _ada_references(self, base, count):
        """Equation indices another VFE equation references, or None for unknown kinds.

        Ada links are u16: next = bytes 2 | 24 << 8 (0xffff = none); compare (3)
        children are bytes 15/16 | 19/20 << 8 and min/max (2) children bytes
        11/12 | 15/16 << 8. Ampere links are the low bytes alone (0xff = none). A
        compare whose output byte 23 has bit 4 set also names its criterion
        equation (u16 at bytes 11..12, every entry size; no Ada, Ampere or Turing
        image of the corpus sets it).
        """
        b, refs = self.blob, set()
        size, width = self._equation_layout()
        high = (lambda e, k: e[k] << 8) if width == 2 else (lambda e, k: 0)
        for i in range(count):
            e = b[base + size * i:base + size * i + size]
            if not e[0]:
                continue
            if e[0] > 4:
                return None
            links = [e[2] | high(e, 24)]
            if e[0] == 3:
                links += [e[15] | high(e, 19), e[16] | high(e, 20)]
                if e[23] & VFE_CRITERION_EQUATION:
                    links.append(e[11] | e[12] << 8)
            elif e[0] == 2:
                links += [e[11] | high(e, 15), e[12] | high(e, 16)]
            refs.update(link for link in links if link != (1 << 8 * width) - 1)
        return refs

    def _ada_equation_kind(self, vfe, base, index, refs, roles=()):
        """Classify one VFE output equation; only 'temperature-derated' takes a ceiling edit.

        That kind is a float quadratic in uV (type 1, unit 2) on a sensed
        temperature variable, with a nonzero slope, finite 0 <= min <= max, no
        next link and no reference from another equation, as the hardware-tested
        REL of the reviewed board. Such an equation picked by more than one
        selector of its rail row (roles), as REL = OV, is 'shared' instead: a
        ceiling edit would move every role that picks it.
        """
        b = self.blob
        size, width = self._equation_layout()
        at = base + size * index
        kind = {2: 'min-max', 3: 'compare', 4: 'fixed-point'}.get(b[at], 'unknown')
        if b[at] != 1:
            return kind
        if b[at + 23] & 15 != 2:
            return 'non-voltage'
        lo, hi = read(b, '<ff', at + 3)
        coefficients = read(b, '<fff', at + 11)
        if not all(math.isfinite(x) for x in (lo, hi, *coefficients)) or not 0 <= lo <= hi:
            return 'invalid'
        if (b[at + 2] | (b[at + 24] << 8 if width == 2 else 0)) != (1 << 8 * width) - 1:
            return 'chained'
        if refs is None or index in refs:
            return 'shared'
        if not coefficients[1] and not coefficients[2]:
            return 'constant'
        variable = b[at + 1]
        if variable >= b[vfe + 3] or b[vfe + b[vfe + 1] + variable * b[vfe + 2]] != 3:
            return 'non-temperature'
        return 'shared' if list(roles).count(index) > 1 else 'temperature-derated'

    def rail_limits(self):
        rails, vfe, base, count = self._rails()
        b = self.blob
        size = self._equation_layout()[0]
        refs = self._ada_references(base, count)
        result = []
        for rail_index, name, row, selectors in rails:
            index = selectors['REL']
            equation = base + index * size
            self.owner(equation, size)
            if b[equation] == 3:
                raise FormatError('REL equation is a compare expression on fused inputs; read-only')
            if b[equation] != 1 or b[equation + 23] & 15 != 2:
                raise FormatError('REL equation is not a quadratic voltage output')
            lo, hi = read(b, '<ff', equation + 3)
            coefficients = read(b, '<fff', equation + 11)
            if not all(math.isfinite(x) for x in (lo, hi, *coefficients)) or not 0 <= lo <= hi:
                raise FormatError('invalid REL equation bounds/coefficients')
            var_index = b[equation + 1]
            if var_index >= b[vfe + 3]:
                raise FormatError('REL variable index exceeds VFE variable table')
            variable = vfe + b[vfe + 1] + var_index * b[vfe + 2]
            self.owner(variable, 25)
            # A constant REL (zero slopes) does not read its variable: the OV equation a
            # followed REL selects reads another one.
            constant = not coefficients[1] and not coefficients[2]
            if b[variable] != 3 and not constant:
                raise FormatError('unvalidated REL input variable (expected temperature)')
            kind = self._ada_equation_kind(vfe, base, index, refs, list(selectors.values()))
            sensed = (dict(index=var_index, offset=variable, type=3, meaning='sensed temperature',
                           thermal_channel=b[variable + 9], units_inferred='degrees Celsius') if b[variable] == 3 else
                      dict(index=var_index, offset=variable, type=b[variable], meaning='not read by a constant equation'))
            result.append(dict(rail_index=rail_index, rail_name_inferred=name, rail_entry=row,
                               rel_equation_index_inferred=index, equation_offset=equation,
                               equation_type=b[equation], output_minimum_uv=lo, output_maximum_uv=hi,
                               maximum_offset=equation + 7, equation_coefficients=list(coefficients),
                               equation_kind=kind, editable_ceiling=kind == 'temperature-derated',
                               thermal_derating_preserved=True, input_variable=sensed))
        return result

    def rail_equations(self):
        """REL/ALT/OV/VMIN selector roles of every logic rail (Ada: NVVDD; Ampere: NVVDD, MSVDD; Turing: NVVDD
        with REL/ALT/OV only).

        Only temperature-derated REL and ALT equations take a ceiling edit (see
        _ada_equation_kind). Constant equations (every OV, every Ampere REL/ALT,
        and REL/ALT on some Ada boards) would keep their value under a
        ceiling-only edit; compare REL depends on fused inputs; VMIN is
        fixed-point with an unverified scale.
        """
        rails, vfe, base, count = self._rails()
        refs = self._ada_references(base, count)
        size = self._equation_layout()[0]
        result = []
        for rail_index, name, row, selectors in rails:
            for role, offset in self._role_offsets():
                selector = selectors[role]
                item = dict(logical_rail_id=name, rail_index=rail_index, rail_entry=row, role=role,
                            selector_offset=row + offset, selector_width_bits=8, selector_raw=selector,
                            absent=selector == 0xFF, boot_voltage_uv=read(self.blob, '<I', row)[0],
                            equation_offset=None, maximum_offset=None, equation_size=size,
                            output_minimum_uv=None, output_maximum_uv=None, layout_recognized=False)
                if not item['absent']:
                    at = base + selector * size
                    kind = self._ada_equation_kind(vfe, base, selector, refs, list(selectors.values()))
                    item.update(equation_offset=at, maximum_offset=at + 7, equation_type=self.blob[at],
                                output_unit_code=self.blob[at + 23] & 15, output_flags=self.blob[at + 23],
                                equation_kind=kind)
                    if self.blob[at] == 1 and self.blob[at + 23] & 15 == 2:
                        # Float clamp of a quadratic voltage output. Compare heads and
                        # fixed-point equations are not decoded as a voltage value.
                        lo, hi = read(self.blob, '<ff', at + 3)
                        if all(math.isfinite(x) for x in (lo, hi)) and lo <= hi:
                            item.update(output_minimum_uv=lo, output_maximum_uv=hi, layout_recognized=True)
                    item['editable_ceiling'] = role in ('REL', 'ALT') and kind == 'temperature-derated'
                result.append(item)
        return result

    def _vmin_clone(self, row, base, count, selector):
        """Ada: the constant equation that shares the evaluated VMIN equation (selector), or None.

        The RTX 4090 95.02.3C images fill the first unused VFE slot of the 95.02.18 image with
        a pinned 15 mV voltage constant R whose next link is the row byte 7 equation V, and the
        clock programming entries of the memory clocks from 810 MHz up name R: their voltage floor
        is VMIN + 15 mV + the VMIN chain. A VMIN edit first copies V into an unused slot S and
        links R to the copy ('decoupled'), so R keeps its stock value; the stock VMIN value
        restores R's link and the unused slot ('coupled'). Recognized in exactly this shape:

        - coupled: only the next link of R references V; R is a voltage equation (type 1, unit 2)
          with minimum = maximum = constant and zero slopes that no equation references; S is the
          first unused slot and holds the clean unused pattern;
        - decoupled: no equation references V and exactly one such R links an equation S that
          only R references and that holds V's bytes except its clamp, which pins a whole uV
          value (the stock VMIN);
        - in both: S is referenced by nothing else, no other rail row byte selects V, R or S, no
          clock programming entry names V or S, and the memory clock entries (the clocks table
          DRAM row) name R except exactly one lower entry, the idle clock.

        Returns the state, R and S (index and offset), the stock VMIN (uV), the clone bytes, R's
        constant (uV), the memory clocks (MHz) whose entries name R and the idle memory clock.
        """
        if self.family != 'ada':
            return None
        b, size, none = self.blob, 25, 0xFFFF
        try:
            who = vfe_referrers(b, base, size, 2, count)
            named = self.clock_programming_vfe()
            memory = self.dram_points()['points']
        except FormatError:
            return None

        def equation(i):
            return bytes(b[base + size * i:base + size * i + size])

        def constant(i):
            e = equation(i)
            lo, hi, c0, c1, c2 = read(b, '<5f', base + size * i + 3)
            return (e[0] == 1 and e[23] & 15 == 2 and math.isfinite(c0) and lo == hi == c0 and c1 == 0 and c2 == 0
                    and not who.get(i))
        vmin = equation(selector)
        users = who.get(selector, [])
        if len(users) == 1 and users[0][1] == 'next':
            referrer = users[0][0]
            ref = equation(referrer)
            if referrer == selector or not constant(referrer) or ref[2] | ref[24] << 8 != selector:
                return None
            slot = next((i for i in range(count) if not b[base + size * i]), None)
            if slot is None or slot >= none or equation(slot) != vfe_free_slot(size):
                return None
            state, clone, stock = 'coupled', vmin, read(b, '<f', base + size * selector + 3)[0]
        elif not users:
            found = []
            for i in range(count):
                if b[base + size * i] != 1 or not constant(i):
                    continue
                e = equation(i)
                slot = e[2] | e[24] << 8
                if slot in (none, selector, i) or slot >= count or who.get(slot) != [(i, 'next')]:
                    continue
                copy = equation(slot)
                lo, hi = read(b, '<ff', base + size * slot + 3)
                if copy[:3] + copy[11:] == vmin[:3] + vmin[11:] and math.isfinite(lo) and lo == hi == int(lo):
                    found.append((i, slot, copy, lo))
            if len(found) != 1:
                return None
            (referrer, slot, clone, stock), state = found[0], 'decoupled'
        else:
            return None
        rows = {b[row + k] for k in ADA_ROW_SELECTOR_BYTES if k != ADA_VMIN_OFFSET}
        if who.get(slot, []) not in ([], [(referrer, 'next')]) or {selector, referrer, slot} & rows or \
                {selector, slot} & set(named.values()):
            return None
        # The memory clock entries that name R; exactly one lower entry (the idle clock) names another equation.
        kept = [p['mhz'] for p in memory if named.get(p['index']) == referrer]
        other = [p['mhz'] for p in memory if named.get(p['index']) != referrer]
        if not kept or len(other) != 1 or other[0] >= min(kept):
            return None
        return dict(state=state, referrer=referrer, referrer_offset=base + size * referrer, slot=slot,
                    slot_offset=base + size * slot, stock_uv=stock, clone=clone,
                    constant_uv=read(b, '<f', base + size * referrer + 11)[0], memory_mhz=kept,
                    idle_memory_mhz=other[0])

    def equation_index_names(self):
        """Ada and Ampere: VFE equation index -> [table] for the tables outside the VFE and rail tables that name
        equations, read in the primary chain (integrity requires identical chains) at their reviewed layouts
        (EQUATION_INDEX_LAYOUTS), each as a superset where the index bytes are not pinned down:

        - clock programming (C+0x0c): entry bytes 3 and 4 (Ada: | bytes 13 and 14 << 8), the VF equation
          the GPC curve reads and the byte after it, and every byte of the VF sub-entries (the last
          count x size bytes of an entry), alone and with the next one as u16;
        - FLL (C+0x10, nvgpu fll_descriptor 1.0): header byte 6, the frequency margin equation (Ada: |
          byte 7 << 8), and entry byte 9, the minimum frequency equation (Ada: also | byte 10 << 8 and |
          byte 15 << 8);
        - voltage policy (P+0x70): the four param0 bytes of every entry but a single-rail one (type 1,
          which names a voltage domain only), alone and as u16 pairs: nvgpu reads split-rail delta
          equations there.

        An absent table names nothing; FormatError when a table is not at its reviewed layout.
        """
        if self.family not in EQUATION_INDEX_LAYOUTS:
            raise FormatError('tables naming VFE equations are reviewed on Ada and Ampere only')
        b, names, ada = self.blob, {}, self.family == 'ada'

        def name(index, table):
            names.setdefault(index, []).append(table)
        for table, (token, pointer) in EQUATION_INDEX_POINTERS.items():
            entry = self.tokens.get(token)
            if entry is None or pointer + 4 > entry['size'] or not read(b, '<I', entry['data'] + pointer)[0]:
                continue
            at = self.pointer(token, pointer)
            version, header, size = EQUATION_INDEX_LAYOUTS[self.family][table]
            if tuple(b[at:at + 3]) != (version, header, size):
                raise FormatError(f'the {table} table ({token}+{pointer:#x}) has an unreviewed layout')
            count = b[at + 3]
            stride, vf = size, 0
            if table == 'clock programming':
                c1, s1, c2, s2 = b[at + 4:at + 8]
                stride, vf = size + c1 * s1 + c2 * s2, c2 * s2
            self.owner(at, header + stride * count)
            if table == 'FLL':
                name(b[at + 6] | (b[at + 7] << 8 if ada else 0), table)
            for i in range(count):
                e = at + header + stride * i
                if table == 'clock programming':
                    for k in (3, 4):
                        name(b[e + k] | (b[e + k + 10] << 8 if ada else 0), table)
                    sub = b[e + stride - vf:e + stride]
                    for k in range(vf):
                        name(sub[k], table)
                        if k + 1 < vf:
                            name(sub[k] | sub[k + 1] << 8, table)
                elif table == 'FLL':
                    name(b[e + 9], table)
                    if ada:
                        name(b[e + 9] | b[e + 10] << 8, table)
                        name(b[e + 9] | b[e + 15] << 8, table)
                elif b[e] != 1:
                    for k in range(1, 5):
                        name(b[e + k], table)
                        if k < 4:
                            name(b[e + k] | b[e + k + 1] << 8, table)
        return names

    def _vmin_tree(self, rails, row, base, count, selector, refs):
        """Ada and Ampere: the clamp state of a VMIN equation (row byte 7) that a fixed value can pin and the stock
        bytes can restore, a diagnostic string for such an equation that cannot take it, or None for another shape.

        Two shapes, as GB20x BlackwellRom.vmin_tree:
        - a min/max (2) or compare (3) root with a voltage output (byte 23 = 2, or 0x12 on a compare) and no
          next link, whose clamp is VFE_UNCLAMPED ('stock') or pins a whole uV ('pinned'); the compare roots
          of 13 GA104/GA106 images pick one chain per fused bin, each a base value plus fuse, temperature
          and binning terms;
        - a quadratic (1) voltage equation on a fused input whose own range over that input's stored range
          is not a single value (quadratic_span): 'stock' while its clamp is that range (the stock clamp of
          ten Ada images, per-chip values such as 640 to 780 mV), 'pinned' when the clamp pins a whole uV.
          The equations chained after it still add their terms (added_uv). Where the input's range is a
          single value (RTX 2000 Ada, RTX 4080, ...) the clamp is the stock value itself and rail_vmin keeps
          the pinned-clamp field.

        Pinning the clamp (minimum = maximum = value) fixes the equation's value; the stock bytes
        (stock_clamp) restore it. The equation must be referenced by no other equation (criterion
        links included), selected by no other byte of any rail row (bytes 4 on) and named by no
        table of equation_index_names. Returns state, kind, pinned_uv, nodes and stock_clamp.
        """
        b, size, width = self.blob, *self._equation_layout()
        at = base + size * selector
        kind, stock = {2: 'min-max', 3: 'compare', 1: 'per-chip'}.get(b[at]), None
        link = b[at + 2] | (b[at + 24] << 8 if width == 2 else 0)
        if kind in ('min-max', 'compare'):
            outputs = (2,) if kind == 'min-max' else (2, 2 | VFE_CRITERION_EQUATION)
            if b[at + 23] not in outputs:
                return None
            if link != (1 << 8 * width) - 1:
                return 'is an equation tree with a next equation'
        elif kind == 'per-chip':
            vfe = self.pointer('P', 0x20)
            variables, variable_size = vfe + b[vfe + 1], b[vfe + 2]
            if b[at + 23] != 2 or b[at + 1] >= b[vfe + 3] or b[variables + variable_size * b[at + 1]] != \
                    VFE_FUSE_VARIABLE:
                return None
            span = quadratic_span(b, at, variables, variable_size)
            if span is None or span[0] >= span[1]:
                return None
            stock = struct.pack('<ff', *span)
        else:
            return None
        state, value = vfe_clamp_state(b, at)
        what = 'equation tree' if kind != 'per-chip' else 'per-chip equation (a quadratic on a fused input)'
        if kind == 'per-chip' and b[at + 3:at + 11] == stock:
            state = 'unclamped'
        elif kind == 'per-chip' and state != 'pinned':
            lo, hi = read(b, '<ff', at + 3)
            return (f'is a {what} whose clamp ({lo / 1000:g} to {hi / 1000:g} mV) is not its own range over that '
                    f'input ({span[0] / 1000:g} to {span[1] / 1000:g} mV), so a fixed value could not be set back '
                    'to the stock bytes')
        if state is None:
            return f'is an {what} whose root has an unreviewed output clamp'
        width_row = 0x1F if self.family == 'ada' else 0x11
        others = [k for _, _, r, _ in rails for k in range(4, width_row)
                  if (r, k) != (row, ADA_VMIN_OFFSET) and b[r + k] == selector]
        article = 'an' if kind != 'per-chip' else 'a'
        if refs is None or selector in refs:
            return f'is {article} {what} that another equation uses'
        if others:
            return (f'is {article} {what}, and rail row byte {others[0]} also holds its index ({selector}), so '
                    'it may select it too')
        try:
            names = self.equation_index_names()
            nodes = vfe_tree(b, base, size, width, count, selector)
        except FormatError as exc:
            return f'is {article} {what}, but {exc}, so another user of it cannot be ruled out'
        if selector in names:
            return f'is {article} {what} that the {names[selector][0]} table also names'
        return dict(state='stock' if state == 'unclamped' else 'pinned', kind=kind, pinned_uv=value, nodes=len(nodes),
                    stock_clamp=stock or VFE_UNCLAMPED)

    def rail_vmin(self):
        """Per rail, the equation of the evaluated VMIN (row byte 7; Turing byte 9) and whether its clamp pins it.

        The clamp pins the value when the equation is a float voltage output
        (type 1, unit 2) with a finite clamp minimum equal to its maximum, which
        no other equation references and no other role selects (on Turing the
        boot voltage selector, byte 8, counts as a role); its chained equations
        (next link) add added_uv to the clamped value. The RTX 2000 Ada driver
        reported VMIN 90 mV above this value, at both the stock and an edited
        clamp, inside the 70..162 mV its chain adds. Turing byte 9 is the nvgpu 1x
        vmin_limit_vfe_equ_idx. rel_lowest_uv is the lowest value of the REL
        equation list (vfe_range, a min/max or compare clamp bounding its children).
        On Ada, an equation that only the constant of
        _vmin_clone references pins its value too; the item then carries 'clone'
        (also when that constant already links a copy). On Ada and Ampere a tree root
        or a per-chip equation (_vmin_tree) carries 'tree' instead; its clamp takes a
        fixed value, and pinned and value_uv follow that clamp.
        """
        rails, vfe, base, count = self._rails()
        refs = self._ada_references(base, count)
        size, width = self._equation_layout()
        roles = self.rail_equations()
        turing = self.family == 'turing'
        offset = TURING_VMIN_OFFSET if turing else ADA_VMIN_OFFSET
        result = []
        for rail_index, name, row, selectors in rails:
            selector = self.blob[row + offset]
            rel = vfe_range(self.blob, base, size, width, count, selectors['REL'],  # _selectors: REL present
                            clamped_children=True)
            item = dict(logical_rail_id=name, rail_index=rail_index, rail_entry=row,
                        selector_offset=row + offset, selector_raw=selector, equation_offset=None,
                        equation_size=size, equation_type=None, value_uv=None, pinned=False,
                        rel_lowest_uv=rel and rel[0], added_uv=None)
            if selector == 0xFF or selector >= count:
                result.append(dict(item, diagnostic='is absent or outside the equation table'))
                continue
            at = base + selector * size
            self.owner(at, size)
            lo, hi = read(self.blob, '<ff', at + 3)
            link = self.blob[at + 2] | (self.blob[at + 24] << 8 if width == 2 else 0)
            item.update(equation_offset=at, equation_type=self.blob[at],
                        added_uv=vfe_range(self.blob, base, size, width, count, link, frozenset((selector,)),
                                           clamped_children=True))
            selected = ([r for r in roles if r['equation_offset'] == at] or
                        [r for _, _, r, _ in rails if r != row and self.blob[r + offset] == selector] or
                        (turing and self.blob[row + TURING_BOOT_OFFSET] == selector))
            voltage = self.blob[at] == 1 and self.blob[at + 23] & 15 == 2
            pins = math.isfinite(lo) and lo == hi
            tree = None if turing else self._vmin_tree(rails, row, base, count, selector, refs)
            clone = (self._vmin_clone(row, base, count, selector) if voltage and pins and refs is not None and
                     tree is None else None)
            if isinstance(tree, dict):
                item.update(tree=tree, minimum_offset=at + 3, maximum_offset=at + 7)
                if tree['state'] == 'pinned':
                    item.update(value_uv=tree['pinned_uv'], pinned=True)
                diagnostic = None
            elif tree is not None:
                diagnostic = tree
            elif not voltage:
                diagnostic = 'is not a float voltage output'
            elif not pins:
                diagnostic = 'has a clamp that does not pin its value'
            elif refs is None or selector in refs and clone is None or selected:
                diagnostic = 'is used by another equation or role'
            else:
                item.update(value_uv=lo, pinned=True, minimum_offset=at + 3, maximum_offset=at + 7,
                            **({'clone': clone} if clone else {}))
                diagnostic = None
            if diagnostic:
                item['diagnostic'] = diagnostic
            result.append(item)
        return result

    def rail_boot_equations(self):
        """Turing: per rail, the equation the boot voltage selector (1x row byte 8) picks; other families: none.

        It is not a role of rail_equations, and no field writes it.
        """
        if self.family != 'turing':
            return []
        rails, _, base, _ = self._rails()
        size = self._equation_layout()[0]
        return [dict(logical_rail_id=name, rail_index=index, selector_offset=row + TURING_BOOT_OFFSET,
                     selector_raw=self.blob[row + TURING_BOOT_OFFSET],
                     equation_offset=base + size * self.blob[row + TURING_BOOT_OFFSET], equation_size=size)
                for index, name, row, _ in rails]

    def rail_table(self):
        """(offset, size) of the rail table (P+0x68) in the primary chain: its 5-byte header and rows."""
        rail = self.pointer('P', 0x68)
        header = bytes(self.blob[rail:rail + 5])
        rows = {'ada': {ADA_RAIL_HEADER: 1}, 'turing': {TURING_RAIL_HEADER: 1}}.get(self.family,
                                                                                   AMPERE_RAIL_HEADERS).get(header)
        if not rows:
            raise FormatError('unvalidated rail layout')
        size = 5 + self.blob[rail + 2] * rows
        self.owner(rail, size)
        return rail, size

    def rail_fixed(self):
        """Ada and Turing NVVDD REL and ALT equations that hold a fixed value, and the value of the OV equation.

        A fixed equation is the constant kind of _ada_equation_kind (zero slopes, no link,
        no reference from another equation) whose constant equals its clamp maximum (the
        images store it as the clamp minimum too), and that no other role and not the
        evaluated VMIN (Ada row byte 7, Turing byte 9) selects; on Turing the boot voltage
        selector (byte 8) counts as a role too. Ada row byte 10 holds 2, the REL index, on
        every image; its meaning is unknown and it is not counted as a role (Turing byte 10,
        the voltage margin limit, is absent: _selectors). lowest_uv and highest_uv bound a
        role's equation list (vfe_range; an unlinked equation, such as a compare REL head,
        also by its own clamp). ov_uv is set when OV is a constant voltage equation with
        minimum = maximum = constant; boot_uv is the stored boot voltage (row bytes 0..3).
        """
        if self.family not in ('ada', 'turing'):
            return None
        rails, vfe, base, count = self._rails()
        _, _, row, selectors = rails[0]
        refs = self._ada_references(base, count)
        size, width = self._equation_layout()
        b = self.blob
        turing = self.family == 'turing'
        selected = {{'VMIN': 'the VMIN slot'}.get(k, k): v for k, v in selectors.items()}
        if turing:
            selected['the boot voltage'] = b[row + TURING_BOOT_OFFSET]
        selected['the evaluated VMIN'] = b[row + (TURING_VMIN_OFFSET if turing else ADA_VMIN_OFFSET)]

        def span(index):
            at = base + size * index
            lo, hi = read(b, '<ff', at + 3)
            bounded = vfe_range(b, base, size, width, count, index)
            unlinked = (b[at + 2] | (b[at + 24] << 8 if width == 2 else 0)) == (1 << 8 * width) - 1
            if bounded is None and b[at + 23] & 15 == 2 and unlinked and -1e30 < lo <= hi < 1e30:
                bounded = lo, hi
            return bounded or (None, None)

        roles = {}
        for role in ('REL', 'ALT'):
            index = selectors[role]
            if index == 0xFF:
                roles[role] = None
                continue
            at = base + size * index
            lo, hi, value = read(b, '<fff', at + 3)
            kind = self._ada_equation_kind(vfe, base, index, refs)
            shared = [name for name, other in selected.items() if name != role and other == index]
            diagnostic = ('is used by another equation' if kind == 'shared' else
                          f'is not a constant (a {kind} equation)' if kind != 'constant' else
                          'does not hold its constant at its clamp maximum' if value != hi else
                          'is also selected by ' + ' and '.join(shared) if shared else None)
            lowest, highest = span(index)
            roles[role] = dict(role=role, selector_raw=index, selector_offset=row + dict(self._role_offsets())[role],
                               equation_offset=at, equation_kind=kind,
                               minimum_uv=lo, maximum_uv=hi, value_uv=value, fixed=diagnostic is None,
                               lowest_uv=lowest, highest_uv=highest, maximum_offset=at + 7, value_offset=at + 11,
                               **({'diagnostic': diagnostic} if diagnostic else {}))
        at = base + size * selectors['OV']
        lo, hi, value = read(b, '<fff', at + 3)
        constant = self._ada_equation_kind(vfe, base, selectors['OV'], refs) == 'constant' and lo == hi == value
        return dict(rail_entry=row, selectors=selectors, roles=roles, ov_uv=value if constant else None,
                    boot_uv=read(b, '<I', row)[0])

    def fan_regions(self):
        """(start, size) of every Ada/Ampere/Turing fan table in every chain, at the reviewed sizes.

        Sizes come from the reviewed layout whether or not a table decodes, so an
        unexpected header stays protected too.
        """
        regions = []
        tables = TURING_FAN_TABLES if self.family == 'turing' else ADA_FAN_TABLES
        for pointer, _, header_size, entry_size, entries in tables.values():
            try:
                at = self.pointer('P', pointer)
            except FormatError:
                continue
            relative = at - self.legacy['start']
            for chain in self.chains:
                start = chain[0]['start'] + relative
                regions.append((start, min(header_size + entry_size * entries, len(self.blob) - start)))
        return regions

    def fan_coolers(self):
        """Ada fan channels across the five per-channel fan tables (two entries each).

        Same table set and cooler row layout as GB20x (see BlackwellRom.fan_coolers),
        with an Ada cooler header of 6 bytes (list bytes 4..5). An Ada channel i is
        stored when its mapping names row i (byte 1), its control entry has byte 2 = i
        and byte 5 = (control 0 byte 5 & ~3) | 1 << i, its speed entry has byte 1 = i,
        and its policy byte 1 equals channel 0's. Both header bytes 0xff with every
        channel enable 0 means no GPU-driven fan (laptops); returns None.

        Ampere uses the same tables. Its speed table may be unused: enable 0 on
        every channel (RTX 3080/3090 boards, RTX 3060 8GB); its entries are then
        not compared, and a raised channel count keeps them disabled.

        Rows carry the GB20x row limits, policy curve and speed value. Enabled
        policy entries past the two cooler rows (entry 2, and 3 on most images)
        store further curves, listed in extra_curves. Ampere boards that stop
        the fan store 0 % and 0 RPM as the row minimum. Turing: see
        _turing_fan_coolers.
        """
        if self.family == 'turing':
            return self._turing_fan_coolers()
        b = self.blob
        try:
            at = self.pointer('P', 0x58)
        except FormatError:
            return None
        tables = {}
        for name, (pointer, header, header_size, entry_size, entries) in ADA_FAN_TABLES.items():
            start = at if name == 'cooler' else self.pointer('P', pointer)
            if b[start:start + 4] != header:
                raise FormatError(f'unsupported fan {name} table')
            self.owner(start, header_size + entry_size * entries)
            tables[name] = lambda i, start=start, header_size=header_size, entry_size=entry_size: (
                start + header_size + entry_size * i)
        n = ADA_FAN_CHANNELS
        header = list(b[at + 4:at + 4 + n])
        if header == [0xFF] * n and not any(b[tables[name](i)] for name in tables for i in range(n)):
            return None
        end = header.index(0xFF) if 0xFF in header else n
        listed = header[:end]
        if any(i != 0xFF for i in header[end:]) or listed != list(range(len(listed))) or not listed:
            raise FormatError('unrecognized fan channel list')
        first_control, first_policy = tables['control'](0), tables['policy'](0)
        speed_used = self.family != 'ampere' or any(b[tables['speed'](i)] for i in range(n))
        rows = []
        for i in range(n):
            row, pol, mapped = tables['cooler'](i), tables['policy'](i), tables['mapping'](i)
            control, speed = tables['control'](i), tables['speed'](i)
            rows.append(dict(index=i, offset=row, enable=b[row], active=i in listed,
                             pwm_frequency_hz=int.from_bytes(b[row + 11:row + 14], 'little'),
                             pwm_frequency_offset=row + 11,
                             level_minimum=b[row + 2], level_maximum=b[row + 3],
                             rpm_minimum=read(b, '<H', row + 14)[0], rpm_maximum=read(b, '<H', row + 16)[0],
                             **fan_curve(b, pol),
                             policy_offset=pol, policy_enable=b[pol], mapping_offset=mapped,
                             mapping_enable=b[mapped], mapping_row=b[mapped + 1],
                             control_offset=control, control_enable=b[control],
                             speed_offset=speed, speed_enable=b[speed], speed_rpm=read(b, '<H', speed + 2)[0],
                             stored=(b[pol + 1] == b[first_policy + 1] and b[mapped + 1] == i and
                                     b[control + 2] == i and
                                     b[control + 5] == (b[first_control + 5] & 0xFC) | 1 << i and
                                     (b[speed + 1] == i or not speed_used))))
        if [r['index'] for r in rows if r['enable']] != listed:
            raise FormatError('fan channel list disagrees with the enabled rows')
        enables = ('policy_enable', 'mapping_enable', 'control_enable') + (('speed_enable',) if speed_used else ())
        for r in rows:
            if any(bool(r[k]) != r['active'] for k in enables):
                raise FormatError('fan channel enables disagree across the fan tables')
            if r['active'] and not r['stored']:
                raise FormatError('an active fan channel is not stored in every fan table')
        policies = b[first_policy - 1]  # entry count, header byte 3
        extra = [dict(index=k, policy_offset=tables['policy'](k), **fan_curve(b, tables['policy'](k)))
                 for k in range(n, policies) if b[tables['policy'](k)]]
        return dict(offset=at, policy_offset=tables['policy'](0) - 4, mapping_offset=tables['mapping'](0) - 4,
                    control_offset=tables['control'](0) - 4, speed_offset=tables['speed'](0) - 4,
                    channels=listed, rows=rows, extra_curves=extra)

    def _turing_fan_coolers(self):
        """Turing fan channels across the cooler, policy and mapping tables (TURING_FAN_TABLES).

        The policy table repeats the cooler channel list (header bytes 4..5). A
        listed channel i has a nonzero enable in all three tables, policy byte 2 =
        i, policy bytes 9..16 = TURING_POLICY_BYTES and mapping byte 1 = i; an
        unlisted one is disabled in all three. Both
        lists 0xff with every enable 0 means no GPU-driven fan (Max-Q and laptop
        images); returns None. Rows have the fan_coolers keys: policy_offset is
        the policy entry + TURING_CURVE_SHIFT, where the Ada curve offsets apply,
        and there are no control or speed entries and no extra curves. The disabled
        entries hold bytes that differ from the active ones, so no channel count
        is offered (fan_layouts does not run on Turing).
        """
        b = self.blob
        try:
            at = self.pointer('P', 0x58)
        except FormatError:
            return None
        tables = {}
        for name, (pointer, header, header_size, entry_size, entries) in TURING_FAN_TABLES.items():
            start = at if name == 'cooler' else self.pointer('P', pointer)
            if b[start:start + 4] != header:
                raise FormatError(f'unsupported fan {name} table')
            self.owner(start, header_size + entry_size * entries)
            tables[name] = lambda i, start=start, header_size=header_size, entry_size=entry_size: (
                start + header_size + entry_size * i)
        n = ADA_FAN_CHANNELS
        header, policy_list = list(b[at + 4:at + 4 + n]), list(b[tables['policy'](0) - n:tables['policy'](0)])
        if (header == policy_list == [0xFF] * n and
                not any(b[tables[name](i)] for name in tables for i in range(n))):
            return None
        if policy_list != header:
            raise FormatError('fan policy channel list disagrees with the cooler list')
        end = header.index(0xFF) if 0xFF in header else n
        listed = header[:end]
        if any(i != 0xFF for i in header[end:]) or listed != list(range(len(listed))) or not listed:
            raise FormatError('unrecognized fan channel list')
        rows = []
        for i in range(n):
            row, pol, mapped = tables['cooler'](i), tables['policy'](i), tables['mapping'](i)
            curve = pol + TURING_CURVE_SHIFT
            rows.append(dict(index=i, offset=row, enable=b[row], active=i in listed,
                             pwm_frequency_hz=int.from_bytes(b[row + 11:row + 14], 'little'),
                             pwm_frequency_offset=row + 11,
                             level_minimum=b[row + 2], level_maximum=b[row + 3],
                             rpm_minimum=read(b, '<H', row + 14)[0], rpm_maximum=read(b, '<H', row + 16)[0],
                             **fan_curve(b, curve),
                             policy_offset=curve, policy_enable=b[pol], mapping_offset=mapped,
                             mapping_enable=b[mapped], mapping_row=b[mapped + 1],
                             control_offset=None, control_enable=0, speed_offset=None, speed_enable=0, speed_rpm=0,
                             stored=b[pol + 2] == i and b[mapped + 1] == i))
        if [r['index'] for r in rows if r['enable']] != listed:
            raise FormatError('fan channel list disagrees with the enabled rows')
        for r in rows:
            if any(bool(r[k]) != r['active'] for k in ('policy_enable', 'mapping_enable')):
                raise FormatError('fan channel enables disagree across the fan tables')
            if r['active'] and not r['stored']:
                raise FormatError('an active fan channel is not stored in every fan table')
            entry = tables['policy'](r['index'])
            if r['active'] and b[entry + 9:entry + 17] != TURING_POLICY_BYTES:
                raise FormatError('unrecognized Turing fan policy entry layout')
        return dict(offset=at, policy_offset=tables['policy'](0) - 6, mapping_offset=tables['mapping'](0) - 4,
                    control_offset=None, speed_offset=None, channels=listed, rows=rows, extra_curves=[])

    def thermal_policies(self):
        """Thermal policy table (P+0x50), version 0x10, or None when no table is referenced.

        Layout per family in THERMAL_POLICY_LAYOUTS (at most 16 entries, as GSP-RM 615.78.08
        accepts). Entries carry their class (byte 0), channel (byte 1) and three temperatures in
        1/32 C (bytes 2..7). max_temp_index is header byte 9, the entry GSP-RM keeps as the maximum
        operating temperature policy (0xff: none); role_indices are header bytes 4, 5, 6 and 9.
        """
        try:
            at = self.pointer('P', 0x50)
        except FormatError:
            return None  # no thermal policy table referenced
        b = self.blob
        version, header_size, entry_size, count = b[at:at + 4]
        if (version, header_size, entry_size) != (0x10, *THERMAL_POLICY_LAYOUTS[self.family]) or not 0 < count <= 16:
            raise FormatError('unsupported thermal policy table')
        size = header_size + entry_size * count
        self.owner(at, size)
        entries = []
        for i in range(count):
            entry = at + header_size + entry_size * i
            entries.append(dict(index=i, offset=entry, policy_class=b[entry], byte1=b[entry + 1],
                                temperature_offset=entry + 2, temperatures_raw=read(b, '<3h', entry + 2)))
        return dict(offset=at, header_size=header_size, size=size, entries=entries,
                    max_temp_index=b[at + THERMAL_MAX_TEMP_BYTE], role_indices=[b[at + k] for k in THERMAL_ROLE_BYTES])

    def factory_clocks(self):
        """Factory clock record (P+0x98), or None when no record is referenced.

        Same entries as BlackwellRom.factory_clocks: array A (A0 GPC, A1 memory clock) as signed kHz
        and array B (B1 the rated boost) as unsigned kHz, each with its flag. reviewed is False for a
        header outside FACTORY_CLOCK_HEADERS (no entry is decoded then) or a flag other than 0 or 1,
        which GSP-RM refuses.
        """
        try:
            at = self.pointer('P', 0x98)
        except FormatError:
            return None  # no factory clock record referenced
        b = self.blob
        header_size = b[at + 1]
        header = bytes(b[at:at + min(header_size, 16)])
        if header not in FACTORY_CLOCK_HEADERS[self.family]:
            return dict(offset=at, size=None, reviewed=False, header=header, offsets=[], clocks=[])
        size = header_size + 4 * FACTORY_CLOCK_ENTRY
        self.owner(at, size)

        def entries(start, fmt):
            return [dict(index=i, offset=start + FACTORY_CLOCK_ENTRY * i, flag=b[start + FACTORY_CLOCK_ENTRY * i],
                         value_offset=start + FACTORY_CLOCK_ENTRY * i + 1,
                         khz=read(b, fmt, start + FACTORY_CLOCK_ENTRY * i + 1)[0]) for i in range(2)]
        offsets, clocks = entries(at + header_size, '<i'), entries(at + header_size + 2 * FACTORY_CLOCK_ENTRY, '<I')
        return dict(offset=at, size=size, reviewed=all(e['flag'] in (0, 1) for e in offsets + clocks), header=header,
                    offsets=offsets, clocks=clocks)

    def perf_cf(self):
        """PERF_CF controller (P+0xa8) and policy (P+0xac) tables, or None when either is not referenced.

        Same entries and keys as BlackwellRom.perf_cf, read from the controller sizes in
        LEGACY_PERF_CF_CONTROLLERS: the type nibble (byte 0), the target and jump threshold
        (FXP20.12 at bytes 3 and 7), the clock domain (byte 19: on every reviewed image the row of
        the clocks table C+8 that names it, GPC 0, DRAM 2 and VID 5 in the GV HAL order), the
        increase and decrease hysteresis counts (bytes 20 and 21); policy entries as on GB20x.
        """
        try:
            controllers_at, policies_at = self.pointer('P', 0xA8), self.pointer('P', 0xAC)
        except FormatError:
            return None  # no PERF_CF tables referenced
        b = self.blob
        version, header_size, entry_size, count = b[controllers_at:controllers_at + 4]
        expected_version, expected_header, entry_sizes = LEGACY_PERF_CF_CONTROLLERS
        if (version, header_size) != (expected_version, expected_header) or entry_size not in entry_sizes or count < 3:
            raise FormatError('unsupported PERF_CF controller table')
        self.owner(controllers_at, header_size + entry_size * count)
        controllers = []
        for i in range(count):
            e = controllers_at + header_size + entry_size * i
            target, jump = read(b, '<II', e + 3)
            controllers.append(dict(index=i, offset=e, type=b[e] & 0x0F, target_raw=target, jump_raw=jump,
                                    domain=b[e + 19], hysteresis_up=b[e + 20], hysteresis_down=b[e + 21],
                                    target_offset=e + 3, jump_offset=e + 7, hysteresis_up_offset=e + 20,
                                    hysteresis_down_offset=e + 21))
        version, header_size, entry_size, p_count = b[policies_at:policies_at + 4]
        if (version, header_size, entry_size) != LEGACY_PERF_CF_POLICIES or not p_count or b[policies_at + 4]:
            raise FormatError('unsupported PERF_CF policy table')
        self.owner(policies_at, header_size + entry_size * p_count)
        policies = []
        for i in range(p_count):
            e = policies_at + header_size + entry_size * i
            conflicts, members = read(b, '<II', e + 2)
            policies.append(dict(index=i, offset=e, flags=b[e], kind=b[e] & 0x0F, active=bool(b[e] & 0x80),
                                 conflicts=conflicts, controllers=members))
        return dict(controllers=dict(offset=controllers_at, header_size=b[controllers_at + 1],
                                     entry_size=b[controllers_at + 2], entries=controllers),
                    policies=dict(offset=policies_at, header_size=header_size, entries=policies))

    def lpwr_table(self, name):
        """One LPWR feature table (LEGACY_LPWR_TABLES), or None when this family has none or it is not referenced.

        Same keys as BlackwellRom.lpwr_table (object_id None): GSP-RM 615.78.08 checks the version
        (0x10), reads the header and entry sizes the table states and skips every entry whose enable
        word has bit 0 clear.
        """
        if name not in LEGACY_LPWR_TABLES:
            return None
        pointer, header_size, entry_size, fmt = LEGACY_LPWR_TABLES[name]
        try:
            at = self.pointer('P', pointer)
        except FormatError:
            return None  # no table referenced (or past the BIT P token)
        b = self.blob
        version, hs, es, count = b[at:at + 4]
        if (version, hs, es) != (0x10, header_size, entry_size) or not 0 < count <= 5:
            raise FormatError(f'unsupported LPWR {name} table')
        self.owner(at, hs + es * count)
        entries = [dict(index=i, offset=at + hs + es * i, value=read(b, fmt, at + hs + es * i)[0])
                   for i in range(count)]
        return dict(name=name, offset=at, header_size=hs, entry_size=es, format=fmt, object_id=None,
                    entries=entries)

    def copy_offsets(self, at, size):
        self.owner(at, size)
        relative = at - self.legacy['start']
        return [c[0]['start'] + relative for c in self.chains]

    def override_blob(self):
        if not self.integrity()['valid']:
            raise FormatError('source integrity failed before normalization')
        if len(self.chains) == 1:
            # No duplicate bank needs removal. Preserve all envelope/board data.
            return self.blob
        stride = self.chains[1][0]['start'] - self.legacy['start']
        if self.blob[:4] == b'NVGI':
            # Derive bank boundaries from repeated chain positions and NVGI
            # headers. Prefixes need not be identical: bank metadata can differ.
            if any(c[0]['start'] != self.legacy['start'] + i * stride or
                   self.blob[i * stride:i * stride + 4] != b'NVGI' or
                   c[-1]['end'] > (i + 1) * stride
                   for i, c in enumerate(self.chains)):
                raise FormatError('duplicate NVGI banks do not have a consistent boundary')
            if any(byte != 0xFF for byte in self.blob[self.chain_end:stride]):
                raise FormatError('unrecognized primary-bank padding; cannot normalize')
            return self.blob[:stride]
        # A wrapperless multi-chain container has only the bounded primary PCI
        # chain as a structurally defined extraction. Runtime use is unverified.
        return self.blob[self.legacy['start']:self.chain_end]
