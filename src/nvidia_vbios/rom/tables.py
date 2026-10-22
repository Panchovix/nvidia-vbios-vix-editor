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
from .structure import dram_points, fan_curve, gpc_curve_slot, scan_images, image_chains, parse_bit, read, vfe_range
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
ADA_RAIL_HEADER = bytes.fromhex('20 05 1f 01 00')
ADA_VFE_PREFIX = bytes.fromhex('30 0b 19 32 19')
# V20 rail row selectors (u8, 0xff = absent). REL/ALT/OV follow the nvgpu 1x prefix;
# VMIN is byte 11, the slot of the reviewed board's runtime rail INFO VMIN selector.
ADA_ROLE_OFFSETS = (('REL', 4), ('ALT', 5), ('OV', 6), ('VMIN', 11))
# Byte 7 selects the equation of the evaluated VMIN: on the RTX 2000 Ada a new clamp
# there moved the driver's VMIN, a new byte-11 equation did not (hardware tests).
ADA_VMIN_OFFSET = 7
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
# Tables the Ada and Ampere fields write; their data images must end with a reviewed checksum tail (checksum_tail).
ADA_EDITED_TABLES = (('P', 0x2C), ('P', 0x20), ('C', 8)) + tuple(('P', t[0]) for t in ADA_FAN_TABLES.values())
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
# Tables the Turing fields write: power policy, VFE and fans, all in the second data
# image. The clock table sits in the legacy image, which lacks the padding on one RTX
# 2080 image; the clock fields check it themselves (padded), so power stays editable.
TURING_EDITED_TABLES = (('P', 0x2C), ('P', 0x20), ('P', 0x58), ('P', 0x5C), ('P', 0x64))


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
        at = self.profile_table()
        if at is None:
            return []
        if self.blob[at:at + 10] != bytes.fromhex('10 0a 05 04 07 08 01 10 09 08'):
            raise FormatError('unvalidated power profile header')
        self.owner(at, 0xFE + 16 * 0x49)
        if any(self.blob[at + 0xFE:at + 0xFE + 16 * 0x49]):
            raise FormatError('nonempty Ada override profiles require additional evidence')
        return []

    def matching_power_profiles(self):
        return self.power_profiles()

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
        11/12 | 15/16 << 8. Ampere links are the low bytes alone (0xff = none).
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
        equation list (vfe_range).
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
            rel = vfe_range(self.blob, base, size, width, count, selectors['REL'])  # _selectors: REL present
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
                        added_uv=vfe_range(self.blob, base, size, width, count, link, frozenset((selector,))))
            selected = ([r for r in roles if r['equation_offset'] == at] or
                        [r for _, _, r, _ in rails if r != row and self.blob[r + offset] == selector] or
                        (turing and self.blob[row + TURING_BOOT_OFFSET] == selector))
            if self.blob[at] != 1 or self.blob[at + 23] & 15 != 2:
                diagnostic = 'is not a float voltage output'
            elif not (math.isfinite(lo) and lo == hi):
                diagnostic = 'has a clamp that does not pin its value'
            elif refs is None or selector in refs or selected:
                diagnostic = 'is used by another equation or role'
            else:
                item.update(value_uv=lo, pinned=True, minimum_offset=at + 3, maximum_offset=at + 7)
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
