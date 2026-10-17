"""PCI/BIT/NPDS table layout of the Ada and Ampere (GA10x) ROMs.

Field locations derive from NVIDIA-authored nvgpu bios.h 3x power/1x rail/clock
prefixes and VFE output equations; every rule below is structural and was
checked on each parseable image of the Ada corpus and of the 33-image Ampere
corpus. Ampere shares the Ada table set with narrower rows (power 0x47/0x43,
rail 0x11, VFE equations of 24 bytes with 8-bit links) and up to two rails.
No board serial, complete-file size, table-address, or source-hash pins.
"""
import copy
import hashlib
import math
from .structure import scan_images, image_chains, parse_bit, read
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
# VMIN is byte 11 (the reviewed board's runtime INFO VMIN selector is found only there).
ADA_ROLE_OFFSETS = (('REL', 4), ('ALT', 5), ('OV', 6), ('VMIN', 11))
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
# Tables the Ada and Ampere fields write; their data images must keep the reviewed checksum padding.
ADA_EDITED_TABLES = (('P', 0x2C), ('P', 0x20), ('C', 8)) + tuple(('P', t[0]) for t in ADA_FAN_TABLES.values())
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
        owners = [p for p in self.chains[0] if p['start'] <= at and at + size <= p['end']]
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
        """True when every data image holding an edited table ends with 15 0xff bytes and its checksum.

        The editor repairs the additive checksum only in that reviewed layout. The
        RTX 4070 Laptop image, for example, lacks the padding in its last data image.
        """
        if self._padding is None:
            self._padding = self._checksum_padding()
        return self._padding

    def _checksum_padding(self):
        for token, offset in ADA_EDITED_TABLES:
            try:
                image = self.owner(self.pointer(token, offset), 1)
            except FormatError:
                continue
            for copy in self.copy_offsets(image['start'], image['size']):
                end = copy + image['size']
                if self.blob[end - 16:end - 1] != b'\xff' * 15:
                    return False
        return True

    def power_rows(self):
        at = self.pointer('P', 0x2C)
        version, hs, size, count = self.blob[at:at + 4]
        variants = AMPERE_POWER_VARIANTS if self.family == 'ampere' else ADA_POWER_VARIANTS
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
        # board power monitor in the reviewed Ada and GB20x GET readings).
        channel = self.blob[tgp['offset'] + 1]
        if channel != 0 or self.power_channel(0)[:2] != b'\x02\xf5':
            raise FormatError('TGP policy does not read the total board power channel (class 2, rail 0xf5)')
        return rows

    def power_channel(self, index):
        """One entry of the power channel table (P+0x3c, v0x20, 32 entries).

        Ada entries are 26 bytes; Ampere entries are 22 or 26 bytes (the last four zero).
        """
        at = self.pointer('P', 0x3C)
        version, hs, size, count = self.blob[at:at + 4]
        sizes = (0x16, 0x1A) if self.family == 'ampere' else (0x1A,)
        if version != 0x20 or hs not in (6, 0x0A) or size not in sizes or count != 0x20:
            raise FormatError('unvalidated Ada power channel table')
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
        """Ampere power rows of one role, identified by class, unit and power channel.

        Roles: slot_power (class 4 mW) and slot_current (class 5 mA) on the PCIe
        slot channel (byte-identical to the Ada SLOT_CHANNEL); input_current
        (class 5 mA) on the 12 V input channel, rail 0xe0; connector_power (class
        4 mW) on the external connector channels (AMPERE_CONNECTOR_RAILS);
        nvvdd_current (class 0 mA) on an NVVDD output channel (class 1, rail 1).
        Input channels are class 5 at 12 V with no parameter but the provider
        byte 15. Rows must keep 0 <= minimum <= rated <= maximum, as on Ada.
        Returns ada_policy-style items in row order; same_channel_rows lists other
        rows of the same class and unit on a byte-identical channel, and
        summed_cap_rows those on a class-2 sum channel that adds this channel (the
        RTX 3080 Ti and RTX A6000 cap their connector channels together).
        """
        if self.family != 'ampere':
            return []
        cls, units = {'slot_power': (4, 'mW'), 'slot_current': (5, 'mA'), 'input_current': (5, 'mA'),
                      'connector_power': (4, 'mW'), 'nvvdd_current': (0, 'mA')}[role]
        rows, size = self.power_rows(), self.power_entry_size
        count = self.blob[self.pointer('P', 0x3C) + 3]

        def rail(index):
            e = self.power_channel(index)
            if role == 'nvvdd_current':
                return 1 if e[:2] == b'\x01\x01' else None
            if e[0] != 5 or e[2:8] != CHANNEL_12V or any(e[8:15]) or any(e[16:]) or (e[1] == 0xFF and e[15]):
                return None
            return e[1]
        wanted = {'slot_power': (0xFF,), 'slot_current': (0xFF,), 'input_current': (0xE0,),
                  'connector_power': AMPERE_CONNECTOR_RAILS, 'nvvdd_current': (1,)}[role]
        found = [r for r in rows if r['type'] == cls and r['limit_unit'] == units and
                 self.blob[r['offset'] + 1] < count and rail(self.blob[r['offset'] + 1]) in wanted and
                 0 <= r['minimum_raw'] <= r['default_raw'] <= r['maximum_raw']]
        sums = [(o, c, self.summed_channels(c)) for o in rows for c in (self.blob[o['offset'] + 1],)
                if o['type'] == cls and o['limit_unit'] == units and c < count]
        result = []
        for row in found:
            index = self.blob[row['offset'] + 1]
            channel = self.power_channel(index)
            raw = self.blob[row['offset']:row['offset'] + size]
            same = [dict(row=o['row'], parameter_byte_0=self.blob[o['offset'] + 14], minimum_raw=o['minimum_raw'],
                         default_raw=o['default_raw'], maximum_raw=o['maximum_raw'], units=o['limit_unit'])
                    for o in rows if o['row'] != row['row'] and o['type'] == cls and o['limit_unit'] == units and
                    self.blob[o['offset'] + 1] < count and self.power_channel(self.blob[o['offset'] + 1]) == channel]
            summed = [dict(row=o['row'], channel_index=c, summed_channels=members, minimum_raw=o['minimum_raw'],
                           default_raw=o['default_raw'], maximum_raw=o['maximum_raw'], units=o['limit_unit'])
                      for o, c, members in sums if index in members]
            result.append(dict(row, vbios_row_index=row['row'], units=units, channel_index=index,
                               channel_rail=channel[1],
                               immutable_row_sha256=hashlib.sha256(raw[:2] + raw[14:]).hexdigest(),
                               minimum_offset=row['offset'] + 2, default_offset=row['offset'] + 6,
                               same_channel_rows=same, summed_cap_rows=summed))
        return result

    def summed_channels(self, index):
        """Channels a class-2 power channel adds: its relationship entries (bytes 14..15, first..last).

        The relationship table follows the channel entries (header bytes 4/5: entry
        size and count); byte 1 of each entry is a channel index.
        """
        at = self.pointer('P', 0x3C)
        hs, size, count, rsize, rcount = self.blob[at + 1:at + 6]
        entry = self.power_channel(index)
        if entry[0] != 2 or rsize < 2 or not entry[14] <= entry[15] < rcount:
            return []
        base = at + hs + size * count
        self.owner(base, rsize * rcount)
        return [self.blob[base + rsize * i + 1] for i in range(entry[14], entry[15] + 1)]

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
        on every parseable Ada image and on the GET-reviewed GB20x rows.
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
        selectors = {role: b[row + offset] for role, offset in ADA_ROLE_OFFSETS}
        rel, alt, ov, vmin = (selectors[k] for k in ('REL', 'ALT', 'OV', 'VMIN'))
        ordered = rel < vmin and vmin == ov - 1 and (alt == 0xFF or rel < alt < vmin)
        if 0xFF in (rel, ov, vmin) or ov >= count or not ordered:
            family = 'Ada' if self.family == 'ada' else 'Ampere'
            raise FormatError(f'unvalidated {family} rail selectors (expected REL < ALT < VMIN = OV - 1)')
        return selectors

    def _rails(self):
        """([(rail index, inferred name, rail row, selectors)], VFE, equation base, equation count).

        Ada: the single logic rail. Ampere: one or two 17-byte V20 rows; the
        second is named MSVDD by inference only (the GPC clock row runs on rail
        0; XBAR, DRAM and DISP on rail 1). The Ampere VFE count is u8 header
        byte 5. Every rail keeps the selector order of _ada_rail.
        """
        if self.family != 'ampere':
            row, vfe, base, count, selectors = self._ada_rail()
            return [(0, 'NVVDD', row, selectors)], vfe, base, count
        rail, vfe = self.pointer('P', 0x68), self.pointer('P', 0x20)
        b = self.blob
        rails = AMPERE_RAIL_HEADERS.get(bytes(b[rail:rail + 5]))
        if not rails:
            raise FormatError('unvalidated Ampere rail layout; expected one or two V20 rails of 17 bytes')
        if b[vfe:vfe + 5] != AMPERE_VFE_PREFIX:
            raise FormatError('unvalidated Ampere VFE dimensions')
        self.owner(rail, 5 + 0x11 * rails)
        count = b[vfe + 5]
        base = vfe + b[vfe + 1] + b[vfe + 2] * b[vfe + 3]
        if not count:
            raise FormatError('Ampere VFE table has no equations')
        self.owner(vfe, base - vfe + 24 * count)
        rows = [rail + 5 + 0x11 * i for i in range(rails)]
        return ([(i, AMPERE_RAIL_NAMES[i], row, self._selectors(row, count)) for i, row in enumerate(rows)],
                vfe, base, count)

    def _equation_layout(self):
        """(equation size, link width in bytes): Ada 25 bytes with u16 links, Ampere 24 with u8."""
        return (24, 1) if self.family == 'ampere' else (25, 2)

    def _ada_references(self, base, count):
        """Equation indices another VFE equation references, or None for unknown kinds.

        Ada links are u16: next = bytes 2 | 24 << 8 (0xffff = none); compare (3) and
        min/max (2) children are bytes 15/16 | 19/20 << 8 and 11/12 | 19/20 << 8.
        Ampere links are the low bytes alone (0xff = none).
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
                links += [e[11] | high(e, 19), e[12] | high(e, 20)]
            refs.update(link for link in links if link != (1 << 8 * width) - 1)
        return refs

    def _ada_equation_kind(self, vfe, base, index, refs):
        """Classify one VFE output equation; only 'temperature-derated' takes a ceiling edit.

        That kind is a float quadratic in uV (type 1, unit 2) on a sensed
        temperature variable, with a nonzero slope, finite 0 <= min <= max, no
        next link and no reference from another equation, as the hardware-tested
        REL of the reviewed board.
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
        return 'temperature-derated'

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
            if b[variable] != 3:
                raise FormatError('unvalidated REL input variable (expected temperature)')
            kind = self._ada_equation_kind(vfe, base, index, refs)
            result.append(dict(rail_index=rail_index, rail_name_inferred=name, rail_entry=row,
                               rel_equation_index_inferred=index, equation_offset=equation,
                               equation_type=b[equation], output_minimum_uv=lo, output_maximum_uv=hi,
                               maximum_offset=equation + 7, equation_coefficients=list(coefficients),
                               equation_kind=kind, editable_ceiling=kind == 'temperature-derated',
                               thermal_derating_preserved=True, input_variable=dict(index=var_index,
                               offset=variable, type=3, meaning='sensed temperature',
                               thermal_channel=b[variable + 9], units_inferred='degrees Celsius')))
        return result

    def rail_equations(self):
        """REL/ALT/OV/VMIN selector roles of every logic rail (Ada: NVVDD; Ampere: NVVDD, MSVDD).

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
            for role, offset in ADA_ROLE_OFFSETS:
                selector = selectors[role]
                item = dict(logical_rail_id=name, rail_index=rail_index, rail_entry=row, role=role,
                            selector_offset=row + offset, selector_width_bits=8, selector_raw=selector,
                            absent=selector == 0xFF, boot_voltage_uv=read(self.blob, '<I', row)[0],
                            equation_offset=None, maximum_offset=None, equation_size=size,
                            output_minimum_uv=None, output_maximum_uv=None, layout_recognized=False)
                if not item['absent']:
                    at = base + selector * size
                    kind = self._ada_equation_kind(vfe, base, selector, refs)
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

    def fan_regions(self):
        """(start, size) of every Ada/Ampere fan table in every chain, at the reviewed sizes.

        Sizes come from the reviewed layout whether or not a table decodes, so an
        unexpected header stays protected too.
        """
        regions = []
        for pointer, _, header_size, entry_size, entries in ADA_FAN_TABLES.values():
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
        """
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
                             policy_offset=pol, policy_enable=b[pol], mapping_offset=mapped,
                             mapping_enable=b[mapped], mapping_row=b[mapped + 1],
                             control_offset=control, control_enable=b[control],
                             speed_offset=speed, speed_enable=b[speed],
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
        return dict(offset=at, policy_offset=tables['policy'](0) - 4, mapping_offset=tables['mapping'](0) - 4,
                    control_offset=tables['control'](0) - 4, speed_offset=tables['speed'](0) - 4,
                    channels=listed, rows=rows)

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
