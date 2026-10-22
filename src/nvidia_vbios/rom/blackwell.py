"""Reviewed GB20x object-directory v3 format.

Migrated from the project's original inspection script. Table
interpretations retain their original evidence gates, without dump-size
or filename gates. The directory SHA384 envelope at metadata+0x209 remains an
explicit supported layout constraint; unknown envelopes are read-only.
"""
import hashlib
import math
import re
import struct
from .errors import FormatError
from .structure import dram_points, fan_curve, gpc_curve_slot, scan_images, parse_bit, vfe_range

def unpack(blob, fmt, at):
    size = struct.calcsize(fmt)
    if at < 0 or at + size > len(blob):
        raise FormatError(f"read outside ROM: {at:#x}, {size} bytes")
    return struct.unpack_from(fmt, blob, at)


def positions(blob, needle, start=0, end=None):
    end = len(blob) if end is None else end
    at = blob.find(needle, start, end)
    while at >= 0:
        yield at
        at = blob.find(needle, at + 1, end)


# Single-rail images (NVVDD only) accepted by static comparison; no saved GET.
# 0x2BB1 RTX PRO 6000 Workstation, 0x2D04 RTX 5060 Ti, 0x2F04 RTX 5070.
SINGLE_RAIL_IDS = (0x2BB1, 0x2D04, 0x2F04)
# The NVVDD output monitor's power channel and the power device it reads,
# byte-identical in all seven GET-reviewed sources (channel 13, or 27 on
# Max-Q) and in the single-rail images (channel 26).
NVVDD_CHANNEL = bytes.fromhex('0101001bb7000010000000000000090000000000000000000000')
NVVDD_POWER_DEVICE = bytes.fromhex('0200000000140200090000ff60000000000100000000000000')
# The MSVDD output monitor's channel and power device, likewise identical in
# the seven GET-reviewed sources (channel 12, or 28 on Max-Q).
MSVDD_CHANNEL = bytes.fromhex('0110001bb7000010000000000000080000000000000000000000')
MSVDD_POWER_DEVICE = bytes.fromhex('02200000001402ff000000016d000000000100000000000000')
OUTPUT_CHAINS = {'NVVDD': (NVVDD_CHANNEL, NVVDD_POWER_DEVICE), 'MSVDD': (MSVDD_CHANNEL, MSVDD_POWER_DEVICE)}
# Notebook images accepted by static comparison; no saved GET.
# 0x2C59 RTX 5080 Laptop GPU (98.03.5C.00.F2, Lenovo Legion 7 Pro).
NOTEBOOK_IDS = (0x2C59,)
# u16 words of a rail row that may select a VFE equation: REL, ALT, OV, the evaluated VMIN
# (+0x13), +0x15, +0x17, the rail INFO VMIN slot (+0x21), the words +0x1D/+0x1F/+0x23 (0xffff
# in the corpus) and the trailing block +0x29..+0x3F (voltage equations on the Max-Q, RTX PRO
# 4000 SFF, RTX 5060 Ti and notebook rows). +0x1B is the boot voltage's high half.
RAIL_SELECTORS = (0x0D, 0x0F, 0x11, 0x13, 0x15, 0x17, 0x1D, 0x1F, 0x21, 0x23) + tuple(range(0x29, 0x41, 2))
VMIN_SELECTOR = 0x13
# Per-fan-channel tables: name -> (BIT P offset, header, header size, entry size, entries, object).
FAN_TABLES = {
    'cooler': (0x58, bytes((0x10, 9, 0x1A, 4)), 9, 0x1A, 4, 0x1D),
    'policy': (0x5C, bytes((0x20, 4, 0x33, 0x0B)), 4, 0x33, 0x0B, 0x1E),
    'mapping': (0x64, bytes((0x10, 4, 5, 4)), 4, 5, 4, 0x20),
    'control': (0xDC, bytes((0x10, 4, 0x0D, 4)), 4, 0x0D, 4, 0x80),
    'speed': (0xE0, bytes((0x10, 4, 6, 4)), 4, 6, 4, 0x83),
}
# Policy entry byte 0x32, the last byte of the 51-byte entry: the entry's flag byte.
FAN_POLICY_FLAG_OFFSET = 0x32
# Thermal policy table (P+0x50, object 0x1b): version 0x20, header 12 bytes (22 on the RTX PRO
# 4000 SFF), 48-byte entries.
THERMAL_POLICY_SIZES = (0x20, (12, 22), 48)
# Factory clock record (P+0x98, object 0x26): version 0x10, header size 7, then array A (2 x 5
# bytes) and array B (2 x 5 bytes); header byte 6 is 0 on every GB20x image.
FACTORY_CLOCK_HEADER = bytes((0x10, 7, 5, 2, 5, 2, 0))
# PERF_CF controller table (P+0xa8, object 0x60): version 0x10, header 6 bytes (14 on the RTX
# PRO 4000 SFF, whose object 0x60 also covers the 5-byte header of the policy table), 57-byte
# entries. PERF_CF policy table (P+0xac, object 0x61): version 0x10, header 5 bytes (byte 4 is
# 0), 10-byte entries.
PERF_CF_CONTROLLERS = (0x10, (6, 14), 57, 0x60)
PERF_CF_POLICIES = (0x10, 5, 10, 0x61)
# LPWR feature tables (version 0x10): name -> (BIT P offset, object, header size, entry size,
# format of the entry's enable word, whose bit 0 enables the entry).
LPWR_TABLES = {
    'gr_pg': (0x80, 0x39, 10, 5, '<I'),      # GR power gating
    'ms': (0x84, 0x3A, 7, 16, '<I'),         # memory system clock gating (MSCG)
    'gr_rg': (0xD4, 0x7E, 12, 1, '<B'),      # GR rail gating
    'difr': (0xE8, 0x8E, 11, 18, '<I'),      # DIFR
    'nvdec': (0x11C, 0xB4, 10, 2, '<H'),     # video engine power gating
    'nvenc': (0x120, 0xB5, 10, 2, '<H'),
    'ofa': (0x124, 0xB6, 10, 2, '<H'),
    'nvjpg': (0x128, 0xB7, 10, 2, '<H'),
}


class BlackwellRom:
    def __init__(self, blob, name="<memory>"):
        self.blob, self.name = bytes(blob), str(name)
        self.pci_images = self._pci_images()
        legacy = [p for p in self.pci_images if p["type"] == 0 and p["vendor"] == 0x10DE]
        if len(legacy) != 1:
            raise FormatError("expected one NVIDIA legacy PCI image")
        self.legacy = legacy[0]
        efi = [p for p in self.pci_images if p["start"] == self.legacy["end"] and p["type"] == 3]
        if len(efi) != 1:
            raise FormatError("expected an EFI image immediately after the legacy image")
        self.efi = efi[0]
        # Reviewed GB20x dumps use a portable GOP with PCI identity 0000:0000.
        if (self.efi['vendor'], self.efi['device']) not in ((0, 0), (0x10DE, 0),
                                                                         (0x10DE, self.legacy['device'])):
            raise FormatError('EFI PCI identity disagrees with the legacy image')
        meta = [p for p in self.pci_images if p["start"] == self.efi["end"] and p["type"] == 0xE0]
        if len(meta) != 1:
            raise FormatError("expected the signed data image after EFI")
        self.meta = meta[0]
        if self.meta['vendor'] != 0x10DE or self.meta['device'] & 0xFF80 != self.legacy['device'] & 0xFF80:
            raise FormatError('metadata chip identity disagrees with the legacy image')
        extended = [p for p in scan_images(self.blob)[1]
                    if p['start'] == self.meta['end'] and p['type'] == 0xE0]
        if len(extended) != 1 or extended[0]['vendor'] != 0x10DE:
            raise FormatError('expected one bounded NPDS data image after signed metadata')
        if not extended[0]['last'] or extended[0]['device'] != self.meta['device']:
            raise FormatError('NPDS identity or last-image flag is inconsistent')
        self.extended_images = extended
        self.image_regions = [(self.meta['start'], self.meta['end']),
                              (extended[0]['start'], extended[0]['end'])]
        self.directory, self.objects = self._directory()
        self.legacy_directory, self.legacy_objects = self._legacy_directory()
        self.tokens = self._bit()

    def _pci_images(self):
        return scan_images(self.blob)[0]

    def _directory(self):
        b, candidates = self.blob, []
        marker = struct.pack("<II", 3, 16)
        for at in positions(b, marker, self.meta["start"], self.meta["pcir"]):
            _, header_size, count, device = unpack(b, "<IIII", at)
            if not 2 <= count <= 1024 or device != self.legacy["device"]:
                continue
            base = at + header_size + count * 60
            if not at < base <= self.meta["pcir"]:
                continue
            entries = []
            for index in range(count):
                header = at + header_size + index * 60
                oid, offset, size = unpack(b, "<III", header)
                data = base + offset
                if not size or data < base or data + size > self.image_regions[1][1]:
                    break
                entries.append(dict(index=index, id=oid, header=header,
                                    data=data, size=size, hash_offset=header + 12))
            if len(entries) != count or entries[0]["id"] != 0xFB or entries[1]["id"] != 0xBE:
                continue
            if entries[1]["data"] != self.meta["pcir"]:
                continue
            candidates.append((dict(header=at, header_size=header_size, count=count,
                                    data_base=base, digest_offset=self.meta["start"] + 0x209), entries))
        if len(candidates) != 1:
            raise FormatError(f"expected one object directory, found {len(candidates)}")
        directory, entries = candidates[0]
        if directory['digest_offset'] + 48 > directory['header']:
            raise FormatError('object directory digest overlaps directory')
        if len({o['id'] for o in entries}) != len(entries):
            raise FormatError('duplicate object IDs')
        # Reviewed directories may have hash aliases and partially shared data.
        # Every digest is checked, and editing repairs every intersecting owner.
        return directory, entries

    def _legacy_directory(self):
        """The legacy image's own v3 object directory, or (None, []) when it is not recognized.

        It has the layout of the signed data image's directory: the same header and
        60-byte entries, objects 0xfa and 0xbd first (0xbd data at the PCIR) and its
        SHA384 digest at legacy+0x209. Its objects hash the legacy tables, the rail
        table (P+0x68) among them: object 0x21 spans exactly that table and object
        0x35 holds it too. Every hash and digest matches on every GB20x image of the
        corpus, the vendor XOC images included. Integrity reports it; only edits
        inside the legacy image require it.
        """
        b, legacy, candidates = self.blob, self.legacy, []
        for at in positions(b, struct.pack("<II", 3, 16), legacy["start"], legacy["pcir"]):
            _, header_size, count, device = unpack(b, "<IIII", at)
            base = at + header_size + count * 60
            if not 2 <= count <= 1024 or device != legacy["device"] or not at < base <= legacy["pcir"]:
                continue
            entries = []
            for index in range(count):
                header = at + header_size + index * 60
                oid, offset, size = unpack(b, "<III", header)
                if not size or base + offset + size > legacy["end"]:
                    break
                entries.append(dict(index=index, id=oid, header=header, data=base + offset,
                                    size=size, hash_offset=header + 12))
            if (len(entries) == count and [e["id"] for e in entries[:2]] == [0xFA, 0xBD] and
                    entries[1]["data"] == legacy["pcir"] and len({e["id"] for e in entries}) == count):
                candidates.append((dict(header=at, header_size=header_size, count=count, data_base=base,
                                        digest_offset=legacy["start"] + 0x209), entries))
        if len(candidates) != 1 or candidates[0][0]["digest_offset"] + 48 > candidates[0][0]["header"]:
            return None, []
        return candidates[0]

    def legacy_integrity(self):
        """Hash and digest check of the legacy directory, or None when it is not recognized."""
        b, d = self.blob, self.legacy_directory
        if not d:
            return None
        return dict(object_count=len(self.legacy_objects),
                    bad_object_ids=[o["id"] for o in self.legacy_objects
                                    if hashlib.sha384(b[o["data"]:o["data"] + o["size"]]).digest()
                                    != b[o["hash_offset"]:o["hash_offset"] + 48]],
                    directory_sha384_valid=hashlib.sha384(b[d["header"]:d["data_base"]]).digest()
                    == b[d["digest_offset"]:d["digest_offset"] + 48])

    def legacy_valid(self):
        """True when the legacy directory is recognized and every hash and its digest match."""
        report = self.legacy_integrity()
        return bool(report) and not report["bad_object_ids"] and report["directory_sha384_valid"]

    def legacy_owner(self, at, size):
        """The smallest legacy object holding at..at+size; every legacy object it touches holds it whole."""
        if not self.legacy_valid():
            raise FormatError("no valid legacy object directory owns legacy-image bytes")
        touched = [o for o in self.legacy_objects if o["data"] < at + size and at < o["data"] + o["size"]]
        if not touched or any(not o["data"] <= at <= at + size <= o["data"] + o["size"] for o in touched):
            raise FormatError(f"expected legacy objects holding {at:#x}+{size}")
        return min(touched, key=lambda o: o["size"])

    def rail_table(self):
        """(offset, size) of the rail table (P+0x68): the header and its 65-byte rows."""
        rail = self.pointer("P", 0x68)
        return rail, 5 + 65 * self.rail_count(rail)

    def write_owner(self, at, size):
        """The hashed object an edit of at..at+size changes. In the legacy image only the rail table is editable."""
        if self.legacy["start"] <= at < self.legacy["end"]:
            rail, length = self.rail_table()
            if not rail <= at <= at + size <= rail + length:
                raise FormatError("legacy-image edits are limited to the rail table")
            return self.legacy_owner(at, size)
        return self.object_for(at, size)

    def _bit(self):
        return parse_bit(self.blob, self.legacy)

    def pointer(self, token, byte_offset):
        if token not in self.tokens:
            raise FormatError(f"BIT token {token!r} is absent")
        t = self.tokens[token]
        if token in ("P", "C") and t["version"] != 2:
            raise FormatError("unsupported BIT pointer-token version")
        if byte_offset < 0 or byte_offset + 4 > t["size"]:
            raise FormatError("BIT pointer is outside token")
        ptr = unpack(self.blob, "<I", t["data"] + byte_offset)[0]
        if not ptr:
            raise FormatError("requested table is absent")
        # Observed virtual BIOS excludes EFI. Cross-checked against object hashes.
        at = self.legacy["start"] + ptr
        if ptr >= self.legacy["size"]:
            at += self.efi["size"]
        if at < self.legacy["start"] or at + 16 > self.image_regions[1][1]:
            raise FormatError("table pointer is outside BIOS data")
        # Each decoder validates full-table ownership. Small header prefixes
        # can legitimately have multiple hash owners in reviewed directories.
        return at

    def object_for(self, at, size=1):
        owners = [o for o in self.objects if o["data"] <= at and at + size <= o["data"] + o["size"]]
        if len(owners) != 1:
            raise FormatError(f"expected one object for {at:#x}+{size}")
        return owners[0]

    def integrity(self):
        b, d = self.blob, self.directory
        mismatches = [o["id"] for o in self.objects
                      if hashlib.sha384(b[o["data"]:o["data"] + o["size"]]).digest()
                      != b[o["hash_offset"]:o["hash_offset"] + 48]]
        directory_ok = hashlib.sha384(b[d["header"]:d["data_base"]]).digest() == b[d["digest_offset"]:d["digest_offset"] + 48]
        sums = [sum(b[start:end]) & 255 for start, end in self.image_regions]
        pci_sums = [dict(start=p["start"], checksum=sum(b[p["start"]:p["end"]]) & 255)
                    for p in self.pci_images]
        return dict(object_count=len(self.objects), bad_object_ids=mismatches,
                    directory_sha384_valid=directory_ok, image_checksums=sums,
                    pci_image_checksums=pci_sums, legacy_directory=self.legacy_integrity(),
                    valid=not mismatches and directory_ok and sums == [0, 0]
                    and all(p["checksum"] == 0 for p in pci_sums),
                    cryptographic_signature="not verified")

    def clock_ranges(self):
        at = self.pointer("C", 8)
        if self.object_for(at)["id"] != 3 or self.blob[at] != 0x50:
            raise FormatError("unsupported clock offset table")
        hs, entry_size, count, subcount, subsize = self.blob[at + 1:at + 6]
        stride = entry_size + subcount * subsize
        # The 6000 Workstation image (98.02.81) packs the same 15-byte rows
        # with 1-byte sub-entries; only the base row fields are read.
        if (hs, entry_size, count, subcount) != (13, 15, 9, 3) or subsize not in (1, 2):
            raise FormatError("unsupported clock offset rows")
        self.object_for(at, hs + stride * count)
        # Domain indices are references into a per-ROM clock table, not a
        # universal enumeration. The newer SFF ROM has one fewer DRAM domain.
        # Gate both observed layouts and the stable row identity descriptors
        # before assigning names; do not mistake SFF VID for GB202 GPC.
        ranges = tuple(tuple(self.blob[at + hs + stride * i + 1:
                                      at + hs + stride * i + 3]) for i in range(count))
        layouts = (
            ((13, 13), (17, 17), (8, 12), (15, 15), (14, 14), (16, 16),
             (22, 26), (0, 7), (18, 21)),
            ((12, 12), (16, 16), (8, 11), (14, 14), (13, 13), (15, 15),
             (21, 25), (0, 7), (17, 20)),
        )
        descriptors = (0x43, 0x84, 0x182, 0xC5, 0x106, 0x147, 0x8, 0x200, 0x1C1)
        # The notebook image sets bit 12 on the DRAM row; its other bytes equal the desktop row.
        flagged = {2: 0x1182}
        if ranges not in layouts:
            raise FormatError("unsupported clock domain index layout")
        names = ("GPC", "XBAR", "DRAM", "SYS", "VID")
        rows = []
        for i in range(count):
            row = at + hs + stride * i
            first, last = self.blob[row + 1:row + 3]
            if self.blob[row] != 2 or unpack(self.blob, "<H", row + 9)[0] not in (descriptors[i], flagged.get(i)):
                raise FormatError("unsupported clock domain identity descriptor")
            lo, hi = unpack(self.blob, "<hh", row + 3)
            rows.append(dict(row=i, domain=names[i] if i < len(names) else f"{first:#x}..{last:#x}",
                             minimum_mhz=lo, maximum_mhz=hi, minimum_offset=row + 3, maximum_offset=row + 5))
        return rows

    def dram_points(self):
        """The DRAM entries of the clock programming table (C+0x0c, version 0x50, object 4).

        See structure.dram_points; the clocks table DRAM row names them.
        """
        rows = [r for r in self.clock_ranges() if r["domain"] == "DRAM"]
        if len(rows) != 1:
            raise FormatError("no single DRAM clock row")
        row = rows[0]["minimum_offset"] - 3
        at = self.pointer("C", 0x0C)
        if self.object_for(at)["id"] != 4:
            raise FormatError("clock programming pointer does not address object 4")
        result = dram_points(self.blob, at, self.blob[row + 1], self.blob[row + 2], 0x50)
        self.object_for(at, result["size"])
        return result

    def gpc_curve(self):
        """Where a default GPC curve offset lives (structure.gpc_curve_slot).

        The clocks table GPC row names one clock programming entry (C+0x0c, version
        0x50, object 4); its u16 at byte 3 is the root of the GPC VF curve in the VFE
        table (P+0x20, object 0x14). No other VFE-driven programming entry (flag low
        nibble 1) may name the same root.
        """
        rows = [r for r in self.clock_ranges() if r["domain"] == "GPC"]
        if len(rows) != 1:
            raise FormatError("no single GPC clock row")
        row = rows[0]["minimum_offset"] - 3
        first, last = self.blob[row + 1], self.blob[row + 2]
        b, at = self.blob, self.pointer("C", 0x0C)
        if self.object_for(at)["id"] != 4:
            raise FormatError("clock programming pointer does not address object 4")
        hs, size, count, c1, s1, c2, s2 = b[at + 1:at + 8]
        stride = size + c1 * s1 + c2 * s2
        if b[at] != 0x50 or hs != 8 or size < 5 or first != last or first >= count:
            raise FormatError("unreviewed GPC clock programming entry")
        self.object_for(at, hs + stride * count)
        root = unpack(b, "<H", at + hs + stride * first + 3)[0]
        if any(unpack(b, "<H", at + hs + stride * i + 3)[0] == root for i in range(count)
               if i != first and b[at + hs + stride * i] & 0x0F == 1):
            raise FormatError("another clock programming entry names the GPC root")
        vfe = self.pointer("P", 0x20)
        if b[vfe:vfe + 5] != bytes((0x30, 14, 29, 255, 25)) or self.object_for(vfe)["id"] != 0x14:
            raise FormatError("unvalidated Blackwell VFE output layout")
        base = vfe + b[vfe + 1] + b[vfe + 2] * b[vfe + 3]
        vcount = b[vfe + 5] | b[vfe + 10] << 8
        self.object_for(vfe, base + 25 * vcount - vfe)
        return gpc_curve_slot(b, base, 25, 2, vcount, root)

    def thermal_policies(self):
        """Thermal policy table (P+0x50, object 0x1b), or None when no table is referenced.

        GSP-RM 615.78.08 reads a version 0x20 table: the header as 5b1w4b (version, header
        size, entry size, entry count, flags) and each 48-byte entry as 2b3w10d. Entry byte
        0 is the policy class: 0 skips the entry (the ASUS XOC and MSI Lightning images
        store 0 on entries 0, 1 and 4), 1..5 pick the decoder. Bytes 2..7 are three
        temperatures in 1/32 C that the parser shifts left by 3 into 1/256 C. Byte 1 is
        1 on entry 0 of every image (a channel or sub-type; inferred).
        """
        try:
            at = self.pointer("P", 0x50)
        except FormatError:
            return None  # no thermal policy table referenced
        b = self.blob
        version, header_size, entry_size, count = b[at:at + 4]
        expected_version, header_sizes, expected_entry = THERMAL_POLICY_SIZES
        if version != expected_version or header_size not in header_sizes or entry_size != expected_entry or not count:
            raise FormatError("unsupported thermal policy table")
        if self.object_for(at, header_size + entry_size * count)["id"] != 0x1B:
            raise FormatError("thermal policy table does not address object 0x1b")
        entries = []
        for i in range(count):
            entry = at + header_size + entry_size * i
            entries.append(dict(index=i, offset=entry, policy_class=b[entry], byte1=b[entry + 1],
                                temperature_offset=entry + 2, temperatures_raw=unpack(b, "<3h", entry + 2)))
        return dict(offset=at, header_size=header_size, entries=entries)

    def factory_clocks(self):
        """Factory clock record (P+0x98, object 0x26), or None when no record is referenced.

        After the 7-byte header come array A and array B, two {u8 flag, u32 kHz} entries
        each. GSP-RM 615.78.08 applies an A entry whose flag is 1 as a static frequency
        delta of the clock domain it maps to (A0: GPC), reading the value as signed; a
        flag of 0 skips the entry and any other flag fails the read. A B entry with flag 1
        is written, in MHz, into a performance-state clock entry (B1: the rated boost).
        Vendor factory-OC images set A0 and B1; the other images store zeros.
        """
        try:
            at = self.pointer("P", 0x98)
        except FormatError:
            return None  # no factory clock record referenced
        b = self.blob
        if b[at:at + 7] != FACTORY_CLOCK_HEADER:
            raise FormatError("unsupported factory clock record")
        if self.object_for(at, 27)["id"] != 0x26:
            raise FormatError("factory clock record does not address object 0x26")

        def entries(start, fmt):
            return [dict(index=i, offset=start + 5 * i, flag=b[start + 5 * i], value_offset=start + 5 * i + 1,
                         khz=unpack(b, fmt, start + 5 * i + 1)[0]) for i in range(2)]
        offsets, clocks = entries(at + 7, "<i"), entries(at + 17, "<I")
        if any(e["flag"] not in (0, 1) for e in offsets + clocks):
            raise FormatError("unsupported factory clock entry flag")
        return dict(offset=at, offsets=offsets, clocks=clocks)

    def perf_cf(self):
        """PERF_CF controller (P+0xa8, object 0x60) and policy (P+0xac, object 0x61) tables, or None.

        GSP-RM 615.78.08 reads each 57-byte controller entry as 3b5d1b2d1b4d1b1d. For the
        utilization controllers (type nibble 1, or 5 on the notebook's controller 0, a
        subclass with the same offsets) bytes 3..6 are the target and 7..10 the jump
        threshold, both FXP20.12 fractions (0x1000 = 100 %); byte 19 is the clock domain
        (0 GPC, 2 DRAM, 4 video; inferred from the sensors it reads), bytes 20 and 21 the
        increase and decrease hysteresis counts. Each 10-byte policy entry is read as 2b2d:
        the low nibble of byte 0 must be 1, bit 7 is the policy's active flag, bytes 2..5
        the conflict mask and 6..9 the controller mask; a policy's type is its position.
        None when either table is not referenced.
        """
        try:
            controllers_at, policies_at = self.pointer("P", 0xA8), self.pointer("P", 0xAC)
        except FormatError:
            return None  # no PERF_CF tables referenced
        b = self.blob
        version, header_size, entry_size, count = b[controllers_at:controllers_at + 4]
        expected_version, header_sizes, expected_entry, owner = PERF_CF_CONTROLLERS
        if version != expected_version or header_size not in header_sizes or entry_size != expected_entry or count < 3:
            raise FormatError("unsupported PERF_CF controller table")
        if self.object_for(controllers_at, header_size + entry_size * count)["id"] != owner:
            raise FormatError("PERF_CF controller table does not address object 0x60")
        controllers = []
        for i in range(count):
            e = controllers_at + header_size + entry_size * i
            target, jump = unpack(b, "<II", e + 3)
            controllers.append(dict(index=i, offset=e, type=b[e] & 0x0F, target_raw=target, jump_raw=jump,
                                    domain=b[e + 19], hysteresis_up=b[e + 20], hysteresis_down=b[e + 21],
                                    target_offset=e + 3, jump_offset=e + 7, hysteresis_up_offset=e + 20,
                                    hysteresis_down_offset=e + 21))
        p_version, p_header, p_entry, p_owner = PERF_CF_POLICIES
        version, header_size, entry_size, p_count = b[policies_at:policies_at + 4]
        if (version, header_size, entry_size) != (p_version, p_header, p_entry) or not p_count or b[policies_at + 4]:
            raise FormatError("unsupported PERF_CF policy table")
        if self.object_for(policies_at, p_header + p_entry * p_count)["id"] != p_owner:
            raise FormatError("PERF_CF policy table does not address object 0x61")
        policies = []
        for i in range(p_count):
            e = policies_at + p_header + p_entry * i
            conflicts, members = unpack(b, "<II", e + 2)
            policies.append(dict(index=i, offset=e, flags=b[e], kind=b[e] & 0x0F, active=bool(b[e] & 0x80),
                                 conflicts=conflicts, controllers=members))
        return dict(controllers=dict(offset=controllers_at, header_size=b[controllers_at + 1], entries=controllers),
                    policies=dict(offset=policies_at, header_size=p_header, entries=policies))

    def lpwr_table(self, name):
        """One LPWR feature table (LPWR_TABLES), or None when it is not referenced.

        GSP-RM 615.78.08 checks the version (0x10) and parses every entry; an entry whose
        enable word has bit 0 clear is skipped. Each entry reports its enable word.
        """
        pointer, owner, header_size, entry_size, fmt = LPWR_TABLES[name]
        try:
            at = self.pointer("P", pointer)
        except FormatError:
            return None  # no table referenced (or past the BIT P token)
        b = self.blob
        version, hs, es, count = b[at:at + 4]
        if (version, hs, es) != (0x10, header_size, entry_size) or not count:
            raise FormatError(f"unsupported LPWR {name} table")
        if self.object_for(at, hs + es * count)["id"] != owner:
            raise FormatError(f"LPWR {name} table does not address object {owner:#x}")
        entries = [dict(index=i, offset=at + hs + es * i, value=unpack(b, fmt, at + hs + es * i)[0])
                   for i in range(count)]
        return dict(name=name, offset=at, header_size=hs, entry_size=es, format=fmt, object_id=owner,
                    entries=entries)

    def power_rows(self):
        at = self.pointer("P", 11 * 4)
        version, hs, size, count = self.blob[at:at + 4]
        if (version, hs, size) not in ((0x40, 0x38, 0x66), (0x40, 0x3D, 0x66)) or count != 20:
            raise FormatError("unsupported power policy table")
        if self.object_for(at, hs + size * count)["id"] != 0x13:
            raise FormatError("power policy pointer does not address object 0x13")
        result = []
        for i in range(count):
            row = at + hs + size * i
            lo, default, hi = unpack(self.blob, "<III", row + 13)
            result.append(dict(row=i, type=self.blob[row], offset=row,
                               minimum_raw=lo, default_raw=default, maximum_raw=hi))
        return result

    def output_ocp_policies(self):
        """Reviewed row/monitor shapes, with no assertion of SET/enforcement.

        Fingerprints cover the immutable 102-byte row except range bytes13:25;
        they never pin factory/current values or a complete source ROM hash.
        Monitor indices and discriminator1 were independently matched to saved
        class6/rail1-or16 GET records on all seven reviewed Blackwell sources.

        Single-rail images have no saved GET. Their row 13 is accepted only when
        its monitor's power channel and that channel's power device are
        byte-identical to the reviewed NVVDD ones; row 14 has no MSVDD there.
        """
        rows = self.power_rows()
        device = self.legacy['device']
        notebook = device in NOTEBOOK_IDS and self.notebook_power_layout()
        # The notebook rows 13/14 are byte for byte the Max-Q rows (range bytes excluded).
        maxq = device == 0x2BB4 or notebook
        reviewed = device in (0x2BB4, 0x2B85, 0x2C02, 0x2C05, 0x2C33)
        single = device in SINGLE_RAIL_IDS and self.single_rail()
        fingerprints = (
            ('89498b5f7f781ecf5243a36499bcf6122498f9329b6efe03d6c0a4adf37da99f',
             'ae80a96ab922206ba9ccff0ab634e3f926d095040c51d04f400eeab6c3a1d5a1') if maxq else
            ('ad14cb826607972a1efca1069c575afaf906ddae4142a4fa01c5c7c3a6f9e688', None) if single else
            ('d1437df9c34f8b9431a2e93eb6c9918910c2a48132020a962b46dcf46b056d79',
             '8647926a8ed6d777cad5e927b6b1e911f8820c8bf478033163af335c0f5e2548'))
        result = []
        for i, (index, label, monitor_rail_id) in enumerate(((13, 'NVVDD', 1), (14, 'MSVDD', 16))):
            row = rows[index]
            raw = self.blob[row['offset']:row['offset'] + 102]
            fingerprint = hashlib.sha256(raw[:13] + raw[25:]).hexdigest()
            discriminator = unpack(raw, '<I', 1)[0]
            shape = (row['type'] == 7 and discriminator == 1 and fingerprints[i] is not None and
                     fingerprint == fingerprints[i] and
                     0 <= row['minimum_raw'] <= row['default_raw'] <= row['maximum_raw'])
            basis = None
            if shape and reviewed:
                basis = 'saved-get'
            elif shape and single and self.nvvdd_channel_chain(raw[5]):
                basis = 'structural-channel'
            elif shape and notebook and self.output_channel_chain(raw[5], label):
                basis = 'structural-notebook'
            recognized = basis is not None
            result.append(dict(row, logical_rail_id=label, vbios_row_index=index,
                               monitor_index=raw[5], unit_discriminator_raw=discriminator,
                               immutable_row_sha256=fingerprint, association_recognized=recognized,
                               association_basis=basis, rail_absent=single and label == 'MSVDD',
                               rm_policy_type=18 if recognized else None,
                               api_policy_type=19 if recognized else None,
                               monitor_class=6 if recognized else None,
                               power_monitor_rail_id=monitor_rail_id if recognized else None,
                               units='mA' if recognized else 'unknown', maximum_offset=row['offset'] + 21))
        return result

    def notebook_power_layout(self):
        """Notebook power policy layout: the TGP is row 2, rows 7 and 8 are empty.

        Every desktop and Max-Q source has policy header bytes 21..23 = ff 08 ff
        and its TGP in row 8 (type 12). The RTX 5080 Laptop image has ff ff 02,
        rows 7 and 8 of type 0 with zero limits, and row 2 (type 1) holds
        5000/80000/175000 mW: the minimum, default and maximum nvidia-smi
        reports on that laptop.
        """
        at = self.pointer("P", 11 * 4)
        rows = self.power_rows()
        return (self.blob[at + 21:at + 24] == bytes((0xFF, 0xFF, 2)) and rows[2]['type'] == 1 and
                all(rows[i]['type'] == 0 and not rows[i]['maximum_raw'] for i in (7, 8)))

    def single_rail(self):
        """True for the recognized rail table with one (NVVDD) row."""
        try:
            return self.rail_count(self.pointer("P", 0x68)) == 1
        except FormatError:
            return False

    def power_channel(self, index):
        """One 26-byte entry of the 32-row power channel table (P+0x3c, object 0x16)."""
        b, at = self.blob, self.pointer("P", 0x3C)
        if b[at:at + 4] != bytes((0x20, 0x11, 0x1A, 0x20)):
            raise FormatError("unsupported power channel table")
        if self.object_for(at, 0x11 + 0x1A * 0x20)["id"] != 0x16:
            raise FormatError("power channel table does not address object 0x16")
        if not 0 <= index < 0x20:
            raise FormatError("power channel index is outside the table")
        start = at + 0x11 + 0x1A * index
        return b[start:start + 0x1A]

    def power_device(self, index):
        """One 25-byte entry of the 11-row power device table (P+0x28, object 0x12)."""
        b, at = self.blob, self.pointer("P", 0x28)
        if b[at:at + 4] != bytes((0x30, 0x18, 0x19, 0x0B)):
            raise FormatError("unsupported power device table")
        if self.object_for(at, 0x18 + 0x19 * 0x0B)["id"] != 0x12:
            raise FormatError("power device table does not address object 0x12")
        if not 0 <= index < 0x0B:
            raise FormatError("power device index is outside the table")
        start = at + 0x18 + 0x19 * index
        return b[start:start + 0x19]

    def nvvdd_channel_chain(self, monitor):
        """Monitor -> channel -> power device equal to the reviewed NVVDD output."""
        return self.output_channel_chain(monitor, 'NVVDD')

    def output_channel_chain(self, monitor, rail):
        """Monitor -> channel -> power device equal to the reviewed output of this rail."""
        channel_bytes, device_bytes = OUTPUT_CHAINS[rail]
        try:
            channel = self.power_channel(monitor)
            return channel == channel_bytes and self.power_device(channel[14]) == device_bytes
        except FormatError:
            return False

    def input_current_policy(self):
        """Row 9 board input-current policy; shape-gated, with no SET/enforcement claim.

        Row byte 1 is 1 only on the mA rows 9-14, where saved GET INFO+8 is 1 as
        on the mA output-OCP rows 13/14; GET INFO+8 is 0 on every mW
        row. The fingerprint excludes range bytes 13:25 and pins type 11, byte 1,
        the monitor index (2 on Max-Q, 9 otherwise) and every other byte, without
        pinning factory limits.

        Row 7 also references policy 9 (byte 33) and stores a limit at +61 equal
        to the row 9 limit on every reviewed source; saved GET CONTROL of policy 7
        carries policy 9's current value there. It is reported, not interpreted.

        The single-rail images have no saved GET. They are accepted because
        their rows 9 and 7 match a reviewed fingerprint: the non-Max-Q one on
        0x2BB1 and 0x2D04, the Max-Q one (monitor 2) on 0x2F04.
        """
        rows = self.power_rows()
        row, linked_row = rows[9], rows[7]
        raw = self.blob[row['offset']:row['offset'] + 102]
        fingerprint = hashlib.sha256(raw[:13] + raw[25:]).hexdigest()
        maxq_template = '7c11cc9ad24243005ea2b2db09655814eec3c75314d8de29b39b5f5742d1a6e3'
        other_template = '7c5a98dbd3611f9d253b399e6e23658374fdcd2462cb66148a9fac0c67e80116'
        expected = {0x2BB4: maxq_template, 0x2F04: maxq_template, 0x2B85: other_template,
                    0x2C02: other_template, 0x2C05: other_template, 0x2C33: other_template,
                    0x2BB1: other_template, 0x2D04: other_template}.get(self.legacy['device'])
        recognized = (expected is not None and
                      row['type'] == 11 and raw[1] == 1 and fingerprint == expected and
                      0 <= row['minimum_raw'] <= row['default_raw'] <= row['maximum_raw'])
        linked = self.blob[linked_row['offset']:linked_row['offset'] + 102]
        linked_fingerprint = hashlib.sha256(linked[:13] + linked[25:61] + linked[65:]).hexdigest()
        link = (recognized and linked_row['type'] == 13 and linked[33] == 9 and
                linked_fingerprint == '4540611a94541f1567e29ead43584850b9df10e10f6723c417d9f636931ab581')
        return dict(row, vbios_row_index=9, monitor_index=raw[5], unit_discriminator_raw=raw[1],
                    immutable_row_sha256=fingerprint, association_recognized=recognized,
                    rm_policy_type=30 if recognized else None, api_policy_type=25 if recognized else None,
                    monitor_class=8 if recognized else None, units='mA' if recognized else 'unknown',
                    default_offset=row['offset'] + 17, maximum_offset=row['offset'] + 21,
                    linked_limit_recognized=link, linked_limit_row_sha256=linked_fingerprint,
                    linked_limit_offset=linked_row['offset'] + 61,
                    linked_limit_raw=unpack(linked, '<I', 61)[0] if link else None)

    def fan_regions(self):
        """(start, size) of every byte range the fan table pointers address.

        Ranges use the reviewed table sizes whether or not a table decodes,
        so a table with an unexpected header or owner stays protected too.
        """
        regions = []
        for pointer, header, header_size, entry_size, entries, owner in FAN_TABLES.values():
            try:
                at = self.pointer("P", pointer)
            except FormatError:
                continue
            regions.append((at, min(header_size + entry_size * entries, len(self.blob) - at)))
        return regions

    def fan_coolers(self):
        """Fan channels across the five per-channel fan tables.

        Cooler table (P+0x58, object 0x1d): header bytes 4..7 list the active
        rows (0xff ends the list); exactly those rows have a nonzero byte 0.
        The listed count equals NVML's fan count on all five reviewed
        Blackwell boards. Row bytes 11..13 hold the PWM frequency in Hz: 25000
        on the active rows of the 5090 Matrix (mVolt also reads 25 kHz) and
        the Asus XOC images, 27000 on the other sources. Byte 13 is 0 on every
        source.

        Entry i of the policy (P+0x5c), mapping (P+0x64), control (P+0xdc)
        and speed (P+0xe0) tables belongs to channel i; byte 0 is its enable.
        A stored channel i has a stored policy (byte 1 = 1), a mapping naming
        row i (byte 1), a control entry with byte 2 = i and byte 5 =
        0x30 | 1 << i, and a speed entry with byte 1 = i. On every source the
        five enable sets agree and every active channel is stored.

        Row limits: bytes 2/3 hold the minimum/maximum level (%), bytes
        14..15/16..17 the minimum/maximum speed (RPM, '<H'). Policy entry i
        stores the channel's curve (structure.fan_curve); enabled entries past
        the cooler rows (4 and 5 on every source) store further curves, listed
        in extra_curves. On every active row the row limits hold the channel's
        own curve and the extra curves. Speed entry bytes 2..3 hold an RPM
        value inside the channel's row limits (meaning unknown). Policy entry
        byte 0x32 is the entry's flag byte; rows and extra curves carry its
        offset and raw value as flag_offset and flag_byte.
        """
        b = self.blob
        try:
            at = self.pointer("P", 0x58)
        except FormatError:
            return None  # no fan cooler table referenced
        tables = {}
        for name, (pointer, header, header_size, entry_size, entries, owner) in FAN_TABLES.items():
            start = at if name == 'cooler' else self.pointer("P", pointer)
            if b[start:start + 4] != header:
                raise FormatError(f"unsupported fan {name} table")
            if self.object_for(start, header_size + entry_size * entries)["id"] != owner:
                raise FormatError(f"fan {name} table does not address object {owner:#x}")
            tables[name] = lambda i, start=start, header_size=header_size, entry_size=entry_size: (
                start + header_size + entry_size * i)
        header = list(b[at + 4:at + 8])
        if header == [0xFF] * 4 and not any(b[tables[name](i)] for name in tables for i in range(4)):
            return None  # no GPU-driven fan (the notebook's fans belong to the system)
        end = header.index(0xFF) if 0xFF in header else 4
        listed = header[:end]
        if any(i != 0xFF for i in header[end:]) or listed != list(range(len(listed))) or not listed:
            raise FormatError("unrecognized fan channel list")
        rows = []
        for i in range(4):
            row, pol, mapped = tables['cooler'](i), tables['policy'](i), tables['mapping'](i)
            control, speed = tables['control'](i), tables['speed'](i)
            rows.append(dict(index=i, offset=row, enable=b[row], active=i in listed,
                             pwm_frequency_hz=int.from_bytes(b[row + 11:row + 14], "little"),
                             pwm_frequency_offset=row + 11,
                             level_minimum=b[row + 2], level_maximum=b[row + 3],
                             rpm_minimum=unpack(b, '<H', row + 14)[0], rpm_maximum=unpack(b, '<H', row + 16)[0],
                             **fan_curve(b, pol),
                             policy_offset=pol, policy_enable=b[pol], mapping_offset=mapped,
                             mapping_enable=b[mapped], mapping_row=b[mapped + 1],
                             control_offset=control, control_enable=b[control],
                             speed_offset=speed, speed_enable=b[speed], speed_rpm=unpack(b, '<H', speed + 2)[0],
                             flag_offset=pol + FAN_POLICY_FLAG_OFFSET, flag_byte=b[pol + FAN_POLICY_FLAG_OFFSET],
                             stored=(b[pol + 1] == 1 and b[mapped + 1] == i and b[control + 2] == i and
                                     b[control + 5] == 0x30 | 1 << i and b[speed + 1] == i)))
        if [r["index"] for r in rows if r["enable"]] != listed:
            raise FormatError("fan channel list disagrees with the enabled rows")
        for r in rows:
            if any(bool(r[k]) != r["active"] for k in ("policy_enable", "mapping_enable", "control_enable", "speed_enable")):
                raise FormatError("fan channel enables disagree across the fan tables")
            if r["active"] and not r["stored"]:
                raise FormatError("an active fan channel is not stored in every fan table")
        policies = b[tables['policy'](0) - 1]  # entry count, header byte 3
        extra = [dict(index=k, policy_offset=tables['policy'](k),
                      flag_offset=tables['policy'](k) + FAN_POLICY_FLAG_OFFSET,
                      flag_byte=b[tables['policy'](k) + FAN_POLICY_FLAG_OFFSET], **fan_curve(b, tables['policy'](k)))
                 for k in range(len(rows), policies) if b[tables['policy'](k)]]
        return dict(offset=at, policy_offset=tables['policy'](0) - 4, mapping_offset=tables['mapping'](0) - 4,
                    control_offset=tables['control'](0) - 4, speed_offset=tables['speed'](0) - 4,
                    channels=listed, rows=rows, extra_curves=extra)

    def slot_power_policy(self):
        """PCIe-slot power policy: row 19 on the reviewed SFF, row 18 on the 5060 Ti.

        Saved GET reports policy 19 there with INFO+8 = 0 (mW), monitor index 1
        (the slot input channel) and current = rated = 66000. The fingerprint
        excludes range bytes 13:25 and pins type 2, byte 1 = 0, the monitor
        index and every other byte, without pinning the limits.
        """
        # The RTX 5060 Ti (0x2D04, no saved GET) holds the same row shape at 18.
        index = {0x2C33: 19, 0x2D04: 18}.get(self.legacy['device'], 19)
        row = self.power_rows()[index]
        raw = self.blob[row['offset']:row['offset'] + 102]
        fingerprint = hashlib.sha256(raw[:13] + raw[25:]).hexdigest()
        recognized = (self.legacy['device'] in (0x2C33, 0x2D04) and row['type'] == 2 and raw[1] == 0 and raw[5] == 1 and
                      fingerprint == '49a8b1d3fa593e9e002d2097969b1ee7c899928f575a680cb90087de20daf471' and
                      0 <= row['minimum_raw'] <= row['default_raw'] <= row['maximum_raw'])
        return dict(row, vbios_row_index=index, monitor_index=raw[5], immutable_row_sha256=fingerprint,
                    association_recognized=recognized, units='mW' if recognized else 'unknown',
                    default_offset=row['offset'] + 17, maximum_offset=row['offset'] + 21)

    def power_profiles(self):
        """Decode the power table's override profiles (P+0xF4).

        Selectors 0 and 1 mean maximum and default respectively. A profile
        matching the base table is not proof of the firmware's active choice.
        """
        at = self.pointer("P", 0xF4)
        if self.blob[at:at + 10] != bytes.fromhex("10 0a 05 04 07 08 01 10 09 08"):
            raise FormatError("unsupported power override profile table")
        self.object_for(at, 0xFE + 16 * 0x49)
        profiles = []
        for i in range(16):
            row = at + 0xFE + i * 0x49
            flag = self.blob[row] & 15
            if flag == 0:
                continue
            if flag != 1:
                raise FormatError("unsupported power override profile type")
            entries, seen = [], set()
            for j in range(8):
                entry = row + 1 + j * 9
                kind = self.blob[entry] & 15
                if kind == 0:
                    continue
                selector, value = unpack(self.blob, "<II", entry + 1)
                policy, field = selector & 255, selector >> 8
                if kind != 1 or policy not in (2, 7, 8, 9) or field not in (0, 1):
                    raise FormatError("unsupported power override entry")
                if (policy, field) in seen:
                    raise FormatError("duplicate power override selector")
                seen.add((policy, field))
                entries.append(dict(policy=policy, field="maximum" if field == 0 else "default",
                                    value_raw=value, value_offset=entry + 5))
            profiles.append(dict(index=i, offset=row, entries=entries))
        return profiles

    def matching_power_profiles(self):
        rows = self.power_rows()
        expected = {(i, field): rows[i][field + "_raw"]
                    for i in (2, 7, 8, 9) for field in ("maximum", "default")}
        return [p for p in self.power_profiles()
                if {(e["policy"], e["field"]): e["value_raw"] for e in p["entries"]} == expected]

    def selected_top_profile(self):
        """Override profile the table's own selection chain reaches at its top level.

        Two selection rows precede the profiles (+0x0A and +0x47: 5-byte header,
        8 entries {u8 type, u8 profile, u32 mW, u8 param}). Stage 1 maps a code
        0..3 (probably the 12V-2x6 sense level; inferred) to a power value, and
        stage 2 maps that value to a profile. Used only when profiles exist and
        none matches the base (ASUS XOC: base 2001 W / 5001 A, profile 7 lower).
        The profile must be complete, ordered, at or below the base and at or
        above every other profile entry. Raises FormatError naming the failed
        condition (fail closed).
        """
        profiles = self.power_profiles()
        if not profiles:
            raise FormatError("no override profiles")
        if self.matching_power_profiles():
            raise FormatError("a profile matches the base table")
        at, b = self.pointer("P", 0xF4), self.blob
        stages = []
        for row, header in ((at + 0x0A, "01 08 00 00 00"), (at + 0x47, "02 00 00 00 00")):
            if b[row:row + 5] != bytes.fromhex(header):
                raise FormatError("profile selection stages are off or unrecognized")
            entries = [b[row + 5 + 7 * j:row + 12 + 7 * j] for j in range(8)]
            if any(e[0] not in (0, 1) for e in entries):
                raise FormatError("unrecognized profile selection entry")
            stages.append([(e[1], unpack(e, "<I", 2)[0], e[6]) for e in entries if e[0] == 1])
        codes = [code for _, _, code in stages[0]]
        if not codes or codes.count(max(codes)) != 1:
            raise FormatError("profile selection stage 1 has no unique top code")
        power = next(value for _, value, code in stages[0] if code == max(codes))
        targets = [profile for profile, value, _ in stages[1] if value == power]
        if not power or len(targets) != 1:
            raise FormatError("the top selection level reaches no single profile")
        top = next((p for p in profiles if p["index"] == targets[0]), None)
        if top is None:
            raise FormatError(f"selected override profile {targets[0]} is not enabled")
        rows, index = self.power_rows(), top["index"]
        values = {(e["policy"], e["field"]): e["value_raw"] for e in top["entries"]}
        if set(values) != {(i, f) for i in (2, 7, 8, 9) for f in ("maximum", "default")}:
            raise FormatError(f"override profile {index} lacks policy 2/7/8/9 maximum/default entries")
        # details name the failing entry (policy, field); ordering marks a plain
        # minimum/default/maximum order failure.
        for i in (2, 7, 8, 9):
            if values[(i, "default")] > values[(i, "maximum")]:
                raise FormatError(f"override profile {index} has a default above its maximum",
                                  details=dict(policy=i, field="default", ordering=True))
        if len({values[(i, "maximum")] for i in (2, 7, 8)}) != 1:
            raise FormatError(f"override profile {index} board maxima disagree",
                              details=dict(policy=2, field="maximum"))
        for (i, f), v in values.items():
            if v > rows[i][f + "_raw"]:
                raise FormatError(f"override profile {index} policy {i} {f} exceeds the base table",
                                  details=dict(policy=i, field=f))
        for i in (8, 9):
            if values[(i, "default")] < rows[i]["minimum_raw"]:
                raise FormatError(f"override profile {index} default is below the base minimum",
                                  details=dict(policy=i, field="default", ordering=True))
        for p in profiles:
            for e in p["entries"] if p["index"] != index else ():
                if e["value_raw"] > values[(e["policy"], e["field"])]:
                    raise FormatError(f"override profile {p['index']} policy {e['policy']} {e['field']} exceeds "
                                      f"the same entry of override profile {index}",
                                      details=dict(policy=e["policy"], field=e["field"]))
        return dict(top, values=values, selection_power_raw=power, selection_code=max(codes))

    def top_power_profile(self):
        """selected_top_profile(), or None when any of its conditions fails."""
        try:
            return self.selected_top_profile()
        except FormatError:
            return None

    def rail_count(self, rail):
        """Rows of the rail v0x30 table: NVVDD and MSVDD, or NVVDD alone.

        The 6000 Workstation image (98.02.81) has one row with header byte 4 = 0
        and disables the MSVDD voltage devices, so MSVDD is not a rail the
        firmware controls there. Its NVVDD row has the reviewed role offsets.
        """
        header = self.blob[rail:rail + 5]
        if header[:3] != bytes((0x30, 5, 0x41)) or header[3] not in (1, 2) or header[3] == 1 and header[4] != 0:
            raise FormatError("unsupported rail table; v0x30 with one or two rows is required")
        if rail + 5 + 0x41 * header[3] > self.legacy["end"]:
            raise FormatError("rail table exceeds legacy image")
        return header[3]

    def rail_equations(self):
        """Static selector/bounds inspection; never evaluate or apply runtime offsets.

        Role offsets are corroborated by saved RM/API GET transport and six
        cross-ROM rows. FFFF denotes absence and selectors remain full u16.
        Every writable equation has a unique object14 owner and reviewed output
        prefix. Unknown equation kinds remain inspectable/read-only.
        """
        b = self.blob
        rail, vfe = self.pointer("P", 0x68), self.pointer("P", 0x20)
        try:
            count = self.rail_count(rail)
        except FormatError:
            raise FormatError('unvalidated Blackwell rail selector layout') from None
        if b[vfe:vfe + 5] != bytes((0x30, 14, 29, 255, 25)):
            raise FormatError('unvalidated Blackwell VFE output layout')
        if self.object_for(vfe)['id'] != 0x14:
            raise FormatError('rail/VFE ownership or extent is invalid')
        equations = vfe + b[vfe + 1] + b[vfe + 2] * b[vfe + 3]
        self.object_for(vfe, equations - vfe)
        result = []
        for i, label in enumerate(('NVVDD', 'MSVDD')[:count]):
            row = rail + 5 + 65 * i
            if b[row:row + 2] != bytes((1, i + 1)):
                raise FormatError('unvalidated rail logical identity')
            for role, offset in (('REL', 0x0D), ('ALT', 0x0F), ('OV', 0x11), ('VMIN', 0x21)):
                selector = unpack(b, '<H', row + offset)[0]
                item = dict(logical_rail_id=label, rail_index=i, rail_entry=row, role=role,
                            selector_offset=row + offset, selector_width_bits=16, selector_raw=selector,
                            absent=selector == 0xFFFF, boot_voltage_uv=unpack(b, '<I', row + 0x19)[0],
                            equation_offset=None, maximum_offset=None, equation_size=25,
                            output_minimum_uv=None, output_maximum_uv=None, layout_recognized=False)
                if not item['absent']:
                    at = equations + selector * 25
                    try:
                        if self.object_for(at, 25)['id'] != 0x14:
                            raise FormatError('selector does not address object14')
                        lo, hi = unpack(b, '<ff', at + 3)
                        item.update(equation_offset=at, maximum_offset=at + 7,
                                    equation_type=b[at], output_unit_code=b[at + 23] & 15,
                                    output_flags=b[at + 23], output_minimum_uv=lo,
                                    output_maximum_uv=hi)
                        if not all(math.isfinite(x) for x in (lo, hi)) or lo > hi:
                            # Non-finite raw encodings cannot enter JSON numbers.
                            item.update(output_minimum_uv=None, output_maximum_uv=None)
                            raise FormatError('invalid VFE output clamp bounds')
                        kinds = (1, 7) if role == 'REL' else (1,)
                        if b[at] not in kinds or b[at + 23] & 15 != 2:
                            raise FormatError('unreviewed equation kind or output unit')
                        item['layout_recognized'] = True
                        item['editable_ceiling'] = True
                    except FormatError as exc:
                        item['diagnostic'] = str(exc)
                result.append(item)
        return result

    def constant_equation(self, at):
        """Value (uV) of a constant voltage equation at at, else None.

        Constant: type 1, output unit 2, no next link, finite minimum = maximum =
        value (bytes 3/7/11) and zero coefficients (bytes 15/19), in object 0x14.
        """
        b = self.blob
        try:
            if self.object_for(at, 25)["id"] != 0x14:
                return None
        except FormatError:
            return None
        lo, hi, c0, c1, c2 = unpack(b, "<5f", at + 3)
        if (b[at] != 1 or b[at + 23] & 15 != 2 or (b[at + 2] | b[at + 24] << 8) != 0xFFFF or
                not math.isfinite(lo) or not lo == hi == c0 or c1 or c2):
            return None
        return lo

    def equation_references(self, equations, count):
        """Equation indices another VFE equation references, or None for an unreviewed kind.

        Every kind links its next equation (bytes 2 | 24 << 8, 0xffff = none);
        min/max (2) children are bytes 11/12 | 15/16 << 8 and compare (3)
        children bytes 15/16 | 19/20 << 8. Quadratic (1) and the type 7 REL
        polynomial have no other equation link (type 7 terms name variables).
        """
        b, refs = self.blob, set()
        for i in range(count):
            e = b[equations + 25 * i:equations + 25 * i + 25]
            if e[0] not in (0, 1, 2, 3, 7):
                return None
            links = [e[2] | e[24] << 8] if e[0] else []
            if e[0] == 2:
                links += [e[11] | e[15] << 8, e[12] | e[16] << 8]
            elif e[0] == 3:
                links += [e[15] | e[19] << 8, e[16] | e[20] << 8]
            refs.update(x for x in links if x != 0xFFFF)
        return refs

    def rail_vmin(self):
        """Per rail, the equation selected at row +0x13, which gives the driver's evaluated VMIN.

        On the RTX 5080 (constant 800 mV on both rails) and the RTX PRO 4000 SFF
        (min/max trees) the driver's rail status VMIN equals this equation, not the
        rail INFO VMIN slot (+0x21). A constant equation (constant_equation) that no
        other equation references and no other rail row word (RAIL_SELECTORS) selects
        can take a new value; other shapes are reported only. rel_lowest_uv is the
        lowest value of the REL equation list (vfe_range); a constant adds no
        chained equations (added_uv 0, 0).
        """
        b = self.blob
        rail, vfe = self.pointer("P", 0x68), self.pointer("P", 0x20)
        rows = self.rail_count(rail)
        if b[vfe:vfe + 5] != bytes((0x30, 14, 29, 255, 25)) or self.object_for(vfe)["id"] != 0x14:
            raise FormatError("unvalidated Blackwell VFE output layout")
        equations = vfe + b[vfe + 1] + b[vfe + 2] * b[vfe + 3]
        count = b[vfe + 5] | b[vfe + 10] << 8
        self.object_for(vfe, equations + 25 * count - vfe)
        refs = self.equation_references(equations, count)
        rows = [rail + 5 + 65 * i for i in range(rows)]
        selected = [unpack(b, "<H", row + offset)[0] for row in rows for offset in RAIL_SELECTORS]
        result = []
        for i, (label, row) in enumerate(zip(("NVVDD", "MSVDD"), rows)):
            if b[row:row + 2] != bytes((1, i + 1)):
                raise FormatError("unvalidated rail logical identity")
            selector, rel = unpack(b, "<H", row + VMIN_SELECTOR)[0], unpack(b, "<H", row + 0x0D)[0]
            rel = None if rel == 0xFFFF else vfe_range(b, equations, 25, 2, count, rel)
            item = dict(logical_rail_id=label, rail_index=i, rail_entry=row, selector_offset=row + VMIN_SELECTOR,
                        selector_raw=selector, equation_offset=None, equation_size=25, equation_type=None,
                        value_uv=None, pinned=False, rel_lowest_uv=rel and rel[0], added_uv=(0.0, 0.0))
            if selector >= count:
                result.append(dict(item, diagnostic="is absent or outside the equation table"))
                continue
            at = equations + 25 * selector
            item.update(equation_offset=at, equation_type=b[at])
            value = self.constant_equation(at)
            if value is None:
                item["diagnostic"] = ("is a min/max equation tree" if b[at] == 2 else
                                      "is not a constant voltage equation in object 0x14")
            elif refs is None or selector in refs or selected.count(selector) > 1:
                item["diagnostic"] = "is used by another equation or rail selector"
            else:
                item.update(value_uv=value, pinned=True, minimum_offset=at + 3, maximum_offset=at + 7,
                            value_offset=at + 11)
            result.append(item)
        return result

    def rail_limits(self):
        b = self.blob
        rail, vfe = self.pointer("P", 26 * 4), self.pointer("P", 8 * 4)
        count = self.rail_count(rail)
        if b[vfe:vfe + 5] != bytes((0x30, 14, 29, 255, 25)):
            raise FormatError("unsupported VFE header")
        owner = self.object_for(vfe)
        if owner["id"] != 0x14:
            raise FormatError("VFE pointer does not address object 0x14")
        equations = vfe + b[vfe + 1] + b[vfe + 2] * b[vfe + 3]
        self.object_for(vfe, equations - vfe)

        results = []
        for i, label in enumerate(("NVVDD", "MSVDD")[:count]):
            row = rail + 5 + i * 0x41
            if b[row] != 1 or b[row + 1] != i + 1:
                raise FormatError("unrecognized rail identity fields")
            eq = unpack(b, "<H", row + 0x0D)[0]
            at = equations + eq * 25
            if self.object_for(at, 25)["id"] != 0x14 or b[at + 23] & 15 != 2:
                raise FormatError("rail equation is not a voltage output in object 0x14")
            lo, hi = unpack(b, "<ff", at + 3)
            if not all(math.isfinite(x) for x in (lo, hi)) or not 0 <= lo <= hi:
                raise FormatError("invalid voltage equation bounds")
            results.append(dict(rail_index=i, rail_name_inferred=label, rail_entry=row,
                                rel_index_offset=row + 0x0D, rel_equation_index_inferred=eq,
                                equation_offset=at, equation_type=b[at],
                                output_minimum_uv=lo, output_maximum_uv=hi,
                                maximum_offset=at + 7))
        return results

    def report(self):
        power = self.power_rows()
        return dict(file=self.name, size=len(self.blob), sha256=hashlib.sha256(self.blob).hexdigest(),
                    versions=sorted({m.group().decode() for m in re.finditer(rb"9[0-9]\.[0-9A-Fa-f]{2}\.[0-9A-Fa-f]{2}\.[0-9A-Fa-f]{2}\.[0-9A-Fa-f]{2}", self.blob)}),
                    pci_device=f"10de:{self.legacy['device']:04x}",
                    integrity=self.integrity(), directory=self.directory,
                    clock_ranges=self.clock_ranges(), power_policy_rows=power,
                    power_override_profiles=self.power_profiles(),
                    profiles_matching_base_bounds=[p["index"] for p in self.matching_power_profiles()],
                    board_budget_candidate_watts={k: power[8][f"{k}_raw"] / 1000 for k in ("minimum", "default", "maximum")},
                    rail_equation_limits=self.rail_limits(),
                    interpretation="Rail v0x30 field names and board row 8 are static inferences cross-checked with the supplied images; no runtime validation.")
