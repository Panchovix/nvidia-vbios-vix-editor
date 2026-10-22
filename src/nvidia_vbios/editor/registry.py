"""Per-format field evidence registry; unvalidated fields stay read-only."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import math
import struct
from ..rom.blackwell import BlackwellRom, FAN_POLICY_FLAG_OFFSET
from ..rom.structure import (DRAM_POINT_OFFSET_BIT, GPC_CURVE_OFFSET_LIMIT, vfe_constant_mhz,
                             vfe_free_slot)
from ..rom.errors import VbiosError, FormatError
from ..rom.image import metadata
from ..rom.tables import SOURCE, TableRom


@dataclass(frozen=True)
class Binding:
    descriptor: dict
    offsets: tuple[int, ...]
    encoding: str
    scale: Decimal
    # Optional ((value, (bytes per offset, ...)), ...) for a field whose stored
    # form differs per offset; only the listed values can be written.
    layout: tuple = ()


class FieldRegistry:
    """Explicit extension point for additional reviewed field resolvers.

    A resolver receives (image, parser), returns Binding objects, and must bound
    offsets using parser ownership checks. Editing rechecks every offset and
    refuses structural/integrity/overlapping writes. Registration never bypasses
    the architecture gate. Evidence must describe units and supported variants.
    """
    def __init__(self):
        self._resolvers = []

    def register(self, resolver):
        self._resolvers.append(resolver)
        return resolver

    def bindings(self, image, parser):
        result, diagnostics = [], []
        for resolver in self._resolvers:
            try:
                result.extend(resolver(image, parser))
            except VbiosError as exc:
                diagnostics.append({'code': exc.code, 'message': str(exc), 'resolver': resolver.__name__})
        keys = [b.descriptor['key'] for b in result]
        if len(keys) != len(set(keys)):
            raise VbiosError('REGISTRY_CONFLICT', 'duplicate field keys in evidence registry')
        return result, diagnostics


registry = FieldRegistry()

# Findings from an independent GB202 tool and its research notes (credited in
# the acknowledgements), used with the author's permission. They corroborate
# the structural parsers below; no third-party offsets or code are used.
THIRD_PARTY_EVIDENCE = {
    'kind': 'third-party-research',
    'source': 'independent GB202 research (see acknowledgements)',
    'use': 'cross-check only; structural parsing and writers are independent'}
# Read-only NVML GET on the enrolled GPUs, correlated with the deployed payload
# tables. Reading proves the unit or default relation only; no edited value of
# these fields has been booted.
NVML_CAPTURE = {'kind': 'read-only-nvml-correlation', 'source': 'read-only NVML capture', 'set_tested': False}
DEFAULT_LIMIT_EVIDENCE = dict(NVML_CAPTURE, relation='NVML default power limit = stored TGP rated value',
                              api='nvmlDeviceGetPowerManagementDefaultLimit',
                              scope='seven reviewed GB202/GB203 devices and the reviewed Ada device')
GPC_UNITS_EVIDENCE = dict(NVML_CAPTURE, relation='NVML MHz = table MHz',
                          api='nvmlDeviceGetGpcClkMinMaxVfOffset', observed='-1000..1000 for table rows -1000..1000',
                          scope='seven reviewed GB202/GB203 devices')
DRAM_MIN_UNITS_EVIDENCE = dict(NVML_CAPTURE, relation='NVML MHz = 2 * table MHz',
                               api='nvmlDeviceGetMemClkMinMaxVfOffset',
                               observed='minimum -2000 for table -1000; maxima 12000/13000 for tables 6000/6500',
                               scope='seven reviewed GB202/GB203 devices')


def field(key, label, units, current, lo, hi, editable, evidence, *, offsets=(),
          encoding='', scale=1, reason=None, stored_units=None, writable_status=None,
          ordering_group=None, encoding_bounds=None, layout=(), **extra):
    desc = dict(key=key, label=label, type='number', units=units, current=current,
                bounds={'minimum': lo, 'maximum': hi, 'kind': 'encoding-and-preserved-defaults',
                        'hardware_safe_maximum': None}, editable=editable,
                capability_status='supported' if editable else 'read-only',
                evidence=evidence, **extra)
    if ordering_group:
        # Static bounds hold the partners' current values. When partners of one
        # group are requested together, the editor checks only these encoding
        # bounds first and then the reviewed bounds of the joint result.
        desc['ordering_group'] = ordering_group
        desc['bounds'].update(encoding_minimum=encoding_bounds[0], encoding_maximum=encoding_bounds[1])
    writable = writable_status or ('verified' if editable else
                                   'unknown' if current is None or not evidence else 'unsupported')
    desc['capability'] = {
        'vbios': {'writable': writable, 'persistence': 'unknown',
                  'effect': 'offline encoded bytes only; firmware acceptance unknown'},
        'runtime': {'writable': 'unknown', 'persistence': 'unknown', 'applied': 'unknown',
                    'evaluated_value': None}}
    if 'runtime_offset' in desc:
        desc['capability']['runtime']['offset'] = dict(desc['runtime_offset'])
    desc['unit_metadata'] = {'symbol': units, 'stored_symbol': stored_units,
                             'storage_encoding': encoding or None,
                             'storage_signed': encoding in ('<h', '<i', '<f') if encoding else None}
    desc.setdefault('value_semantics', 'stored-field-value')
    desc.setdefault('version_metadata', {'schema_version': 1,
                    'format_variant': next((e['format'] for e in evidence if 'format' in e), None)})
    if reason:
        desc['reason'] = reason
    if stored_units:
        desc['stored_units'] = stored_units
    return Binding(desc, tuple(offsets), encoding, Decimal(str(scale)), tuple(layout))


def can_edit(image, parser):
    # The additive checksum is repaired only in the reviewed padded data-image layout.
    return parser.integrity()['valid'] and (not isinstance(parser, TableRom) or parser.checksum_padding_reviewed())


def ada(parser):
    return isinstance(parser, TableRom) and parser.family == 'ada'


def ampere(parser):
    return isinstance(parser, TableRom) and parser.family == 'ampere'


def turing(parser):
    return isinstance(parser, TableRom) and parser.family == 'turing'


# The only Ada board that runs edited images here. Booted edits: TGP ceiling
# 100 W (NVML maximum) and NVVDD REL ceiling 1100 mV (runtime evaluated REL); a
# second image also changed the GPC offset ceiling and the memory offset floor
# (NVML ranges only, so those clock fields stay experimental). The power floor
# keeps its reviewed status (NVML minimum = stored value). Every other Ada
# field and every other Ada image is experimental.
ADA_TESTED_BOARD = (0x28B0, '95.07.47.00.19')
ADA_TESTED_FIELDS = ('power_max_w', 'power_min_w', 'nvvdd_rel_max_mv', 'nvvdd_rel_equation_max_mv')


def ada_tested(image, parser, key):
    """True for the fields of the hardware-tested Ada board that keep their reviewed status."""
    return (ada(parser) and key in ADA_TESTED_FIELDS and parser.legacy['device'] == ADA_TESTED_BOARD[0] and
            ADA_TESTED_BOARD[1] in metadata(image)['versions'])


def experimental_flag(image, parser, key):
    """{'experimental': True} for an Ada field outside the hardware-tested board and every Ampere field, else {}."""
    return {} if not isinstance(parser, TableRom) or ada_tested(image, parser, key) else {'experimental': True}


ADA_POWER_EVIDENCE = {
    'kind': 'nvidia-struct-prefix-and-structural-rule', 'source': SOURCE,
    'format': 'Ada 3x power 30/32/53, 30/34/5b or 30/2c/4b (the first 0x2c header and 0x4b entry bytes of '
              '30/32/53); TGP row = header byte 10 (notebook: byte 13 when bytes 10..12 are ff); class 1 mW on '
              'power channel 0 = class-2 sum on rail 0xf5',
    'observation': 'the TGP row is row 2 on every parseable Ada image; its rated value equals the published board '
                   'power of the reference desktop and workstation boards in the corpus (a partner RTX 4090 '
                   'image, VBIOS 95.02.18, is rated 550 W)'}
ADA_RUNTIME_EVIDENCE = {
    'kind': 'saved-get-policy-correlation', 'source': 'saved runtime GET capture',
    'scope': 'RTX 2000 Ada 95.07.47.00.19 (10de:28b0), stock image', 'set_tested': False}
ADA_STRUCTURAL_EVIDENCE = {
    'kind': 'structural-row-comparison', 'source': 'Ada VBIOS corpus, 19 parseable images',
    'set_tested': False, 'runtime_get': False}
ADA_NOTEBOOK_EVIDENCE = dict(
    ADA_STRUCTURAL_EVIDENCE, format='Ada 3x power notebook header: bytes 10..13 ff ff ff 02; TGP row 2 class 1 mW '
                                    'on channel 0',
    observation='row 2 has the identity of the desktop TGP row; stored minimum/rated/maximum match OEM laptop '
                'TGP plus Dynamic Boost (for example 5/150/175 W on an RTX 4080 Laptop GPU)')
ADA_NOTEBOOK_DEFAULT_REASON = ('experimental: stored notebook rated TGP; taken as the default power limit by '
                               'structural analogy with the GB20x notebook layout, whose nvidia-smi Default Power '
                               'Limit equals its rated value; no Ada laptop reading; the platform requests the '
                               'running limit; not hardware-tested')
ADA_NOTEBOOK_REASON = ('experimental: stored notebook TGP; the platform (Dynamic Boost, nvidia-powerd) requests the '
                       'running limit and may keep it lower; laptop Ada images are not accepted by the loader; '
                       'not hardware-tested')
# Ampere (GA10x): structural rules checked on the 35 images of the Ampere corpus.
# No Ampere board runs here, so no Ampere value has a runtime reading or a boot.
AMPERE_STRUCTURAL_EVIDENCE = {
    'kind': 'structural-row-comparison',
    'source': 'Ampere VBIOS corpus, 35 parseable GA102-GA107 images', 'set_tested': False, 'runtime_get': False}
AMPERE_POWER_EVIDENCE = dict(
    AMPERE_STRUCTURAL_EVIDENCE,
    format='Ampere 3x power 30/2c/47, 30/2c/43 or 30/32/47; TGP row = header byte 10 (notebook: byte 13 when bytes '
           '10..12 are ff); class 1 mW on power channel 0 = class-2 sum on rail 0xf5',
    observation='the TGP row is row 2 on every image; its rated value is the board power of the model on the '
                'desktop and workstation images (for example RTX A6000 300 W, RTX A4000 140 W, RTX 3060 170 W)')
AMPERE_NOTEBOOK_REASON = ('experimental: stored notebook TGP; the platform (Dynamic Boost, nvidia-powerd) requests the '
                          'running limit and may keep it lower; whether the loader accepts an Ampere laptop image is '
                          'untested; not hardware-tested')
AMPERE_NOTEBOOK_DEFAULT_REASON = ('experimental: stored notebook rated TGP; taken as the default power limit by '
                                  'structural analogy with the GB20x notebook layout; no Ampere reading; the platform '
                                  'requests the running limit; not hardware-tested')
# Turing (TU102-TU117): structural rules checked on the 25 images of the Turing corpus.
# On one RTX 2080 Ti (Windows loader) the override loaded and nvidia-smi reported an
# edited TGP despite the stale signed hash list; with the connector power rows raised too,
# the card reached about 458 W under load. On one RTX 2070 a 225 W power limit (stock 200 W)
# loaded and the card reached 225 W. No other Turing field has run on hardware.
TURING_STRUCTURAL_EVIDENCE = {
    'kind': 'structural-row-comparison',
    'source': 'Turing VBIOS corpus, 25 TU102-TU117 images', 'set_tested': False, 'runtime_get': False}
TURING_POWER_EVIDENCE = dict(
    TURING_STRUCTURAL_EVIDENCE,
    format='Turing 3x power 30/2c/42 or 30/27/42 (the first 0x27 header bytes of 30/2c/42); TGP row = header byte '
           '10 (notebook: byte 13 when bytes 10..12 are ff); class 1 mW on the board-total power channel, the only '
           'class-2 sum on rail 0xf5 of the 20-entry channel table (channel 9 on desktop TU10x/TU116, 0 on TU117 and '
           'laptops)',
    observation='the table decodes like the Ampere power table: minimum/rated/maximum u32 mW at row bytes 2/6/10; '
                'the TGP row is row 2 on every image; its rated value is the board power of the model (for example '
                'RTX 2080 Ti 260 W, TITAN RTX 280 W, GTX 1660 SUPER 125 W, GTX 1650 75 W)')
TURING_HASH_EVIDENCE = {
    'kind': 'integrity-observation', 'source': 'Turing VBIOS corpus, 22 TU102-TU117 images',
    'observation': 'the type-0x70 image that ends each Turing chain holds a signed list of 16-byte digests (algorithm '
                   'unknown) covering the data images and the legacy image, this table included; the editor cannot '
                   'update it, and the loader payload carries it; on one RTX 2080 Ti (Windows driver 617.70, GSP '
                   '615.78.08) the override loaded and nvidia-smi reported an edited TGP with the list left stale',
    'set_tested': False}
TURING_NOTE = ('the table decodes like the Ampere one on the Turing images examined; on one RTX 2080 Ti (Windows '
               'loader) the override loaded and nvidia-smi reported an edited TGP although the signed hash list over '
               'this table, which the editor cannot update, was left stale; under load that card stopped near 300 W '
               'with the connector power rows at stock and reached about 458 W with them raised to 250 W each; on '
               'one RTX 2070 a power limit raised from 200 to 225 W loaded (Windows loader) and the card reached 225 W')
# The connector power rows ran on that card with the board power (500 W TGP, 250 W per connector).
TURING_CONNECTOR_TESTED = ('on one RTX 2080 Ti (Windows loader) a 500 W TGP with 250 W per connector channel loaded '
                           'and the card reached about 458 W under load (near 300 W with these rows at stock); the '
                           'signed hash list over this table is left stale')
# Reason ending of the other Turing fields: none of them has run on hardware.
TURING_UNTESTED = ('not hardware-tested on Turing; the signed hash list over this table is left stale, as for the '
                   'board and connector power, whose edits a driver used on one RTX 2080 Ti')
TURING_CHANNEL_FORMAT = ('Turing power row class/unit flags (byte 0) and channel (byte 1); power channel table P+0x3c '
                         'v0x20, 20 entries of 22 bytes: class 5 single input at 12 V (bytes 2..7), rail byte 1, no '
                         'parameter but the current correction offset (bytes 10..13, nvgpu curr_corr_offset) and the '
                         'provider byte 15')
TURING_TGP_LINKS = ('the relationship entries of the TGP policy name rows 3, 4, 5, 7, 8, 9 and 13 on the RTX 2080 Ti '
                    '(the slot and connector power and current rows and the NVVDD current row; meaning of the link '
                    'unknown) and none of them on the GTX 1630 and 1650 images')
# ASUS RTX 2080 Ti XOC image against the stock TU102 images: what it raises or disables.
TURING_XOC_EVIDENCE = {'kind': 'vendor-image-comparison',
                       'source': 'ASUS RTX 2080 Ti XOC vendor image against the stock TU102 images',
                       'set_tested': False}
TURING_SLOT_EVIDENCE = [
    dict(TURING_STRUCTURAL_EVIDENCE,
         format=TURING_CHANNEL_FORMAT + '; class 4 mW row on the PCIe slot channel (rail 0xff)',
         observation='the slot channel 3 is byte-identical (zero padded) to the Ada slot channel of the GET-reviewed '
                     'RTX 2000 Ada policy 5 and to the Ampere one; one such row (row 3) on the 16 desktop and '
                     'workstation images, rated 63-64 W, maximum 63-76 W on the stock ones (2000 W on the Galax HOF '
                     'XOC image); the Max-Q, laptop, GTX 1630 and Gigabyte GTX 1650 images store none; '
                     + TURING_TGP_LINKS),
    dict(TURING_XOC_EVIDENCE, observation='the XOC image stores row 3 at 372.8 W rated and maximum (stock 63/74 W)')]
# An MSI GTX 1650 stores its slot power row in the TGP's class.
TURING_SLOT_CLASS1_EVIDENCE = [
    dict(TURING_STRUCTURAL_EVIDENCE,
         format=TURING_CHANNEL_FORMAT + '; class 1 mW row (the TGP class) on the PCIe slot channel (rail 0xff)',
         observation='one slot-powered MSI GTX 1650 image stores row 3 as class 1, 30/63/74 W, with the first '
                     'parameter byte and the tail bytes of its TGP row (the TGP alone sets flag 0x40 and parameter '
                     'byte 22 = 6, which name the 3.3 V channel, inferred); there the board power stopped near 66 W '
                     'under a 75 W and a 90 W TGP while a load log read 62.5 W on the slot 12 V input, at this '
                     'row\'s 63 W rated value (plus the 3.3 V channel, 1 W or 4 W by P-state, inferred), so this row '
                     'is the limit; no other Turing, Ampere or Ada image of the corpus has a class-1 row on a slot '
                     'channel')]
TURING_CONNECTOR_EVIDENCE = [
    dict(TURING_STRUCTURAL_EVIDENCE,
         format=TURING_CHANNEL_FORMAT + '; class 4 mW rows on the external 12 V connector channels, rails 0xfa, '
                                        '0xfb, 0xfc and 0xe4',
         observation='one row per connector sense channel (rows 4 and 5, channels 4 and 5), numbered in power-row '
                     'order, on the 16 desktop and workstation images: two on the TU10x boards, one on the GTX 1660, '
                     '1660 SUPER, 1660 Ti and 1650 SUPER; rated 70-167 W, maximum 82-172 W on the stock images; the '
                     'Galax HOF XOC image sets rows 4 and 5 to 2000 W and leaves a third (row 6, channel 6, rail 0xe4) '
                     'at 143/167 W; the RTX 2070 channels hold a current correction offset (200 and 300) and are '
                     'accepted on Turing only; rail names are inferred; with the slot row they cap the board power '
                     'below a TGP raised past their sum: on one RTX 2080 Ti a 500 W TGP stopped near 300 W with them '
                     'at stock and reached about 458 W with them at 250 W; ' + TURING_TGP_LINKS),
    dict(TURING_XOC_EVIDENCE, observation='the XOC image stores rows 4 and 5 at 648 W rated and maximum (stock '
                                          '143/167 W) with its 1000 W TGP')]
TURING_SLOT_CURRENT_EVIDENCE = [
    dict(TURING_STRUCTURAL_EVIDENCE,
         format=TURING_CHANNEL_FORMAT + '; class 5 (hardware threshold, nvgpu bios.h) mA row on the PCIe slot '
                                        'channel, threshold index 0 (parameter byte 0)',
         observation='the same class, unit and channel as the GET-reviewed RTX 2000 Ada policy 8 (CONTROL current = '
                     'rated there); row 7 on 16 desktop and workstation images, rated 10-11 A, maximum 11-16.5 A on the '
                     'stock ones (2000 A on the Galax HOF XOC image); the Max-Q and laptop images read another rail '
                     '(0xf1) there and give no field'),
    dict(TURING_XOC_EVIDENCE, observation='the XOC image changes rows 7, 8 and 9 to class 0 (no field), which the '
                                          'editor does not reproduce')]
TURING_CONNECTOR_CURRENT_EVIDENCE = [
    dict(TURING_STRUCTURAL_EVIDENCE,
         format=TURING_CHANNEL_FORMAT + '; class 5 (hardware threshold) mA row on the channel of a connector power row',
         observation='row 8 (channel 4, threshold index 1) on 15 images, rated 14.5-22.5 A, maximum 14.5-33.75 A; '
                     'row 9 (channel 5, threshold index 2) on the 11 two-connector images, rated 17-22.5 A, maximum '
                     '17-33.75 A (2000 A on the Galax HOF XOC image, whose third-connector threshold row 10, 22.5/33.75 '
                     'A, is class 0 and gives no field); the threshold indices (parameter byte 0) run slot 0, '
                     'connector 1, connector 2 as on Ampere'),
    TURING_SLOT_CURRENT_EVIDENCE[1]]
TURING_NVVDD_LIMIT_EVIDENCE = [
    dict(TURING_STRUCTURAL_EVIDENCE,
         format='Turing power row class 10 mA on the NVVDD output current channel (class 1, rail 1, sensor byte '
                '14 = 6)',
         observation='row 13 on 24 images reads channel 19, whose 22 bytes equal the first 22 bytes of the Ada NVVDD '
                     'output current channel 19 (the GB20x NVVDD current sensor identified by saved GET); rated '
                     '40.25-350.94 A (2000 A on the Galax HOF XOC image); class 10 is not described in nvgpu, so '
                     'whether the firmware enforces the row is unknown; ' + TURING_TGP_LINKS),
    dict(TURING_XOC_EVIDENCE, observation='the XOC image changes row 13 to class 0 (no field)')]
TURING_NOTEBOOK_REASON = ('experimental: stored notebook TGP; the platform (Dynamic Boost, nvidia-powerd) requests the '
                          'running limit and may keep it lower; ' + TURING_NOTE)
TURING_NOTEBOOK_DEFAULT_REASON = ('experimental: stored notebook rated TGP; taken as the default power limit by '
                                  'structural analogy with the GB20x notebook layout; no Turing laptop reading; the '
                                  'platform requests the running limit; ' + TURING_NOTE)


@registry.register
def checksum_layout(image, parser):
    """Diagnostic only: an Ada image whose checksum layout keeps every field read-only."""
    if isinstance(parser, TableRom) and parser.integrity()['valid'] and not parser.checksum_padding_reviewed():
        raise FormatError('a data image holding edited tables lacks the reviewed checksum padding; fields are read-only')
    return []


# The notebook image has no saved GET. Its TGP row is identified by layout and
# by the nvidia-smi limits its owner reported on the same VBIOS.
NOTEBOOK_POWER_EVIDENCE = {
    'kind': 'structural-row-comparison', 'source': 'reviewed Blackwell notebook table layout',
    'scope': 'RTX 5080 Laptop GPU 98.03.5C.00.F2 (10de:2c59)',
    'format': 'GB20x power v40 notebook layout: header bytes 21..23 ff ff 02, rows 7/8 empty, TGP row 2 type 1',
    'set_tested': False, 'runtime_get': False}
NOTEBOOK_SMI_EVIDENCE = {
    'kind': 'owner-nvidia-smi-reading',
    'source': 'nvidia-smi -q -d POWER on the same laptop, shared by its owner',
    'relation': 'nvidia-smi Min/Default/Max Power Limit = row 2 minimum/rated/maximum',
    'observed': 'Min 5 W, Default 80 W, Max 175 W (Current 175 W) for row 2 5000/80000/175000 mW',
    'set_tested': False}
# ASUS XOC images: base rows 2/7/8/9 hold 2001 W / 5001 A and no profile matches
# them; the profile reached by the ROM's own selection chain is bound instead.
TOP_PROFILE_EVIDENCE = {
    'kind': 'vendor-image-comparison',
    'source': 'two ASUS RTX 5090 XOC vendor images (no profile matches the base table)',
    'format': 'GB20x override profile bound through selection stage 1 (top code -> mW) and stage 2 (mW -> profile); '
              'no profile matches base rows 2/7/8/9',
    'observation': 'stage 1 top code 3 -> 600 W -> profile 7 on the stock FE and both XOC images; stock FE profiles '
                   '4..7 cap at 150/300/450/600 W; the XOC images keep the base at 2001 W / 5001 A '
                   'and store profile 7 = 1000 W default, 1200/1600 W maximum, 120/160 A, and set the row 7 linked '
                   '12 V limit to the profile 7 value; that the stage 1 code is the 12V-2x6 sense level is inferred',
    'runtime_active_profile': 'inferred from the selection chain; not measured here', 'set_tested': False}


def top_profile_note(top, base):
    """Reason prefix of a field bound to the top-level override profile instead of the base table."""
    return ('value of override profile %d, reached at the top level of the ROM selection table (code %d -> %g W; '
            'probably the highest 12V-2x6 sense level, inferred); the base table holds %s and is preserved; which '
            'copy the firmware enforces is not hardware-tested; '
            % (top['index'], top['selection_code'], top['selection_power_raw'] / 1000, base))


def top_profile_bounds(profiles, top, policies, name):
    """Values of the same entry in every other profile; the bound profile must stay at or above them."""
    return [e['value_raw'] for p in profiles if p['index'] != top['index'] for e in p['entries']
            if e['policy'] in policies and e['field'] == name]


def top_profile_offsets(top, policies, name):
    return [e['value_offset'] for e in top['entries'] if e['policy'] in policies and e['field'] == name]


NOTEBOOK_POWER_REASON = ('stored notebook TGP ceiling; the platform (Dynamic Boost, nvidia-powerd) requests the '
                         'running limit and may keep it lower; output OCP, cooling and the laptop VRM still apply; '
                         'not hardware-tested')


@registry.register
def power(image, parser):
    rows = parser.power_rows()
    profiles = parser.power_profiles()
    matching = parser.matching_power_profiles()
    notebook = isinstance(parser, BlackwellRom) and parser.notebook_power_layout()
    top, maximum_upper, default_lower, default_upper, minimum_evidence = None, 0x7FFFFFFF, None, None, None
    if notebook:
        tgp = rows[2]
        if not 0 <= tgp['minimum_raw'] <= tgp['default_raw'] <= tgp['maximum_raw']:
            raise FormatError('unvalidated notebook TGP policy bounds')
        if profiles:
            raise FormatError('override profiles of the notebook layout are unreviewed')
        policy_indices = (2,)
        minimum = minimum_upper = tgp['default_raw']
        offsets, default_offsets, minimum_offsets = [tgp['offset'] + 21], [tgp['offset'] + 17], [tgp['offset'] + 13]
        minimum_scope = default_scope = 'notebook TGP policy row 2; no override profiles'
        evidence = [dict(NOTEBOOK_POWER_EVIDENCE), dict(NOTEBOOK_SMI_EVIDENCE)]
        default_evidence = evidence
    elif isinstance(parser, BlackwellRom):
        for i, kind in ((2, 1), (7, 13), (8, 12), (9, 11)):
            r = rows[i]
            if r['type'] != kind or not 0 <= r['minimum_raw'] <= r['default_raw'] <= r['maximum_raw']:
                raise FormatError('unvalidated Blackwell board/current power policy identity or bounds')
        if profiles and not matching:
            top = parser.top_power_profile()
            if top is None:
                raise FormatError('no complete override profile matches the base policy')
        if len({rows[i]['maximum_raw'] for i in (2, 7, 8)}) != 1:
            raise FormatError('board policy maximum values disagree')
        # Rows2/7 carry independent permissive minima (1mW in the real
        # corpus). Only row8 is the reviewed TGP floor; coordinating their
        # maxima does not establish a shared minimum value or meaning.
        policy_indices = (8,)
        tgp, minimum = rows[8], max(rows[i]['default_raw'] for i in (2, 7, 8))
        minimum_upper = tgp['default_raw']
        minimum_offsets = [tgp['offset'] + 13]
        minimum_scope = 'base TGP policy8 only; rows2/7 minima preserved; profiles override maximum/default only'
        offsets = [rows[i]['offset'] + 21 for i in (2, 7, 8)]
        offsets.extend(e['value_offset'] for p in matching for e in p['entries']
                       if e['policy'] in (2, 7, 8) and e['field'] == 'maximum')
        # The rated value of row8 is the boot default. Rows2/7 keep their own
        # rated values; whether they bind above that value is untested.
        default_offsets = [tgp['offset'] + 17]
        default_offsets.extend(e['value_offset'] for p in matching for e in p['entries']
                               if e['policy'] == 8 and e['field'] == 'default')
        default_scope = 'base TGP policy8 rated value and complete matching profiles; rows2/7 rated values preserved'
        evidence = [{'kind': 'reviewed-layout', 'format': 'GB20x power v40 rows 2/7/8 and complete matching profiles',
                     'source': 'reviewed table layout',
                     'runtime_active_profile': 'unknown'}]
        default_evidence = evidence + [dict(THIRD_PARTY_EVIDENCE, observation=(
            'RM PWR_POLICIES INFO entry 8 limitMin/limitRated/limitMax equal row8 on a Matrix boot; '
            'limitRated is the limit run without a client cap'))]
        if top is not None:
            # Only the bound profile's entries are written; base rows 2/7/8 cap them.
            values = top['values']
            tgp = dict(rows[8], default_raw=values[(8, 'default')], maximum_raw=values[(8, 'maximum')])
            minimum = max([values[(i, 'default')] for i in (2, 7, 8)] +
                          top_profile_bounds(profiles, top, (2, 7, 8), 'maximum'))
            minimum_upper, maximum_upper = tgp['default_raw'], rows[8]['maximum_raw']
            default_lower = max([tgp['minimum_raw']] + top_profile_bounds(profiles, top, (8,), 'default'))
            default_upper = min(tgp['maximum_raw'], rows[8]['default_raw'])
            offsets = top_profile_offsets(top, (2, 7, 8), 'maximum')
            default_offsets = top_profile_offsets(top, (8,), 'default')
            default_scope = ('override profile %d policy8 rated value only; base row 8 rated value preserved'
                             % top['index'])
            # The bound fields name the profile binding first; the NVML and Matrix row 8
            # correlations were taken where the profile equals the base, so they are dropped.
            minimum_evidence, evidence = evidence, [TOP_PROFILE_EVIDENCE] + evidence
            default_evidence = evidence
    else:
        tgp = rows[parser.tgp_index]
        notebook = parser.notebook_power
        policy_indices = (parser.tgp_index,)
        minimum = minimum_upper = tgp['default_raw']
        minimum_offsets = parser.copy_offsets(tgp['maximum_offset'] - 8, 4)
        minimum_scope = 'header-indexed TGP policy in every validated duplicate chain; no nonempty profiles'
        offsets = parser.copy_offsets(tgp['maximum_offset'], 4)
        default_offsets = parser.copy_offsets(tgp['maximum_offset'] - 4, 4)
        default_scope = 'header-indexed TGP rated value in every validated duplicate chain; no nonempty profiles'
        evidence = [{'kind': 'nvidia-struct-prefix-and-reviewed-variant', 'source': SOURCE,
                     'format': '3x power policy; TGP index from header; limit_unit flag mW',
                     'recognized_variants': ['Ada 30/32/53', 'Ada 30/34/5b', 'Ada 30/2c/4b'] if ada(parser) else
                                            ['Turing 30/2c/42', 'Turing 30/27/42'] if turing(parser) else
                                            ['Ampere 30/2c/47', 'Ampere 30/2c/43', 'Ampere 30/32/47']}]
        if ada(parser):
            evidence = evidence + [dict(ADA_POWER_EVIDENCE)] + ([dict(ADA_NOTEBOOK_EVIDENCE)] if notebook else [])
        elif turing(parser):
            evidence = evidence + [dict(TURING_POWER_EVIDENCE), dict(TURING_HASH_EVIDENCE)]
        else:
            evidence = evidence + [dict(AMPERE_POWER_EVIDENCE)]
        default_evidence = evidence
    default_evidence = default_evidence + ([] if top else [dict(DEFAULT_LIMIT_EVIDENCE, **(
        {'use': 'structural analogy only: no NVML or nvidia-smi reading of an Ada laptop exists'}
        if notebook and ada(parser) else
        {'use': 'structural analogy only: no NVML or nvidia-smi reading of an Ampere board exists'}
        if ampere(parser) else
        {'use': 'one Turing reading: on an RTX 2080 Ti (Windows loader) nvidia-smi reported an edited TGP, 500 W '
                'default and maximum'}
        if turing(parser) else {}))])
    # Ada notebook TGP rows are never the hardware-tested board; Ampere is never tested.
    flags = {'experimental': True} if notebook and ada(parser) else experimental_flag(image, parser, 'power_max_w')
    untested = TURING_NOTE + '; ' if turing(parser) else 'not hardware-tested on this board; ' if flags else ''
    top_extra = {} if top is None else dict(bound_profile=top['index'], base_values={
        'power_max_w': rows[8]['maximum_raw'] / 1000, 'power_default_w': rows[8]['default_raw'] / 1000})
    # A notebook TGP is another quantity than a board TGP: the platform requests the running limit.
    layout = {'notebook_tgp': True} if notebook else {}
    return [field('power_max_w', 'Board power ceiling', 'W', tgp['maximum_raw'] / 1000,
                  minimum / 1000, maximum_upper / 1000, can_edit(image, parser), evidence,
                  offsets=offsets, encoding='<I', scale=1000, stored_units='mW',
                  factory_default=tgp['default_raw'] / 1000,
                  ordering_group='board-power', encoding_bounds=(0, 0x7FFFFFFF / 1000),
                  reason=(ADA_NOTEBOOK_REASON if ada(parser) else AMPERE_NOTEBOOK_REASON if ampere(parser) else
                          TURING_NOTEBOOK_REASON if turing(parser) else NOTEBOOK_POWER_REASON) if notebook else
                  'experimental: encoding ceiling only; ' + untested + 'firmware/current/hardware restrictions remain'
                  if untested else
                  'experimental: ' + top_profile_note(top, '%g W' % (rows[8]['maximum_raw'] / 1000)) +
                  'firmware/current/hardware restrictions remain' if top else
                  'encoding ceiling only; firmware/current/hardware restrictions remain',
                  **layout, **(dict(flags, experimental=True, **top_extra) if top else flags)),
            field('power_default_w', 'Boot default board power', 'W', tgp['default_raw'] / 1000,
                  (tgp['minimum_raw'] if default_lower is None else default_lower) / 1000,
                  (tgp['maximum_raw'] if default_upper is None else default_upper) / 1000,
                  can_edit(image, parser),
                  default_evidence, offsets=default_offsets, encoding='<I', scale=1000, stored_units='mW',
                  policy_indices=list(policy_indices), value_semantics='stored-board-power-rated-default',
                  format_scope=default_scope, experimental=True,
                  ordering_group='board-power', encoding_bounds=(0, 0x7FFFFFFF / 1000),
                  reason=ADA_NOTEBOOK_DEFAULT_REASON if notebook and ada(parser) else
                  AMPERE_NOTEBOOK_DEFAULT_REASON if notebook and ampere(parser) else
                  TURING_NOTEBOOK_DEFAULT_REASON if notebook and turing(parser) else
                  'experimental: notebook default TGP (nvidia-smi Default Power Limit); the platform '
                  'requests the running limit; not hardware-tested' if notebook else
                  'experimental: ' + top_profile_note(top, '%g W' % (rows[8]['default_raw'] / 1000)) +
                  'rated TGP limit used at boot without a client cap' if top else
                  'experimental: rated TGP limit used at boot without a client cap; ' + TURING_NOTE if turing(parser) else
                  'experimental: rated TGP limit used at boot without a client cap; not hardware-tested',
                  **layout, **top_extra),
            field('power_min_w', 'Board power floor', 'W', tgp['minimum_raw'] / 1000,
                  1, minimum_upper / 1000, can_edit(image, parser), minimum_evidence or evidence,
                  offsets=minimum_offsets, encoding='<I', scale=1000, stored_units='mW',
                  factory_default=tgp['default_raw'] / 1000, policy_indices=list(policy_indices),
                  value_semantics='stored-board-power-minimum', format_scope=minimum_scope,
                  ordering_group='board-power', encoding_bounds=(1, 0x7FFFFFFF / 1000),
                  reason='experimental: encoded floor only; ' + untested + 'firmware acceptance and runtime minimum '
                         'remain unknown' if untested else
                  'encoded floor only; firmware acceptance and runtime minimum remain unknown',
                  **layout, **flags)] + fixed_policy_rated(image, parser, rows, matching, top)


def fixed_policy_rated(image, parser, rows, matching, top=None):
    """Opt-in rated value of the fixed board policies 2/7 (Blackwell only).

    Their CONTROL current equals the rated value in saved GET, and vendor XOC and
    2500 W images raise it together with the ceiling. Hidden behind an explicit
    opt-in in the GUI; requires equal rated values in rows 2 and 7 (in the bound
    top-level profile instead when one replaces the base).
    """
    if (not isinstance(parser, BlackwellRom) or parser.notebook_power_layout() or
            rows[2]['default_raw'] != rows[7]['default_raw']):
        return []
    offsets = [rows[i]['offset'] + 17 for i in (2, 7)]
    offsets.extend(e['value_offset'] for p in matching for e in p['entries']
                   if e['policy'] in (2, 7) and e['field'] == 'default')
    current, lower = rows[2]['default_raw'], max(rows[2]['minimum_raw'], rows[7]['minimum_raw'])
    upper, extra, reason = rows[2]['maximum_raw'], {}, ''
    if top is not None:
        values = top['values']
        if values[(2, 'default')] != values[(7, 'default')]:
            return []
        current, upper = values[(2, 'default')], min(values[(2, 'maximum')], rows[2]['default_raw'])
        offsets = top_profile_offsets(top, (2, 7), 'default')
        lower = max([lower] + top_profile_bounds(parser.power_profiles(), top, (2, 7), 'default'))
        extra = dict(bound_profile=top['index'], base_values={'board_fixed_rated_w': rows[2]['default_raw'] / 1000})
        reason = top_profile_note(top, '%g W' % (rows[2]['default_raw'] / 1000))
    evidence = [{'kind': 'reviewed-layout', 'format': 'GB20x power v40 rows 2/7 rated value and complete matching profiles',
                 'source': 'reviewed table layout', 'runtime_active_profile': 'unknown'},
                dict(INPUT_CURRENT_EVIDENCE, kind='saved-get-policy-correlation',
                     observed='policies 2/7: CONTROL current = rated, also when their maxima were raised',
                     units_basis='GET INFO+8 is 0 (mW) on rows 2/7'),
                {'kind': 'vendor-image-comparison',
                 'observed': 'ASUS XOC and MSI 2500 W images store rows 2/7 rated = maximum (2001000/2500000 mW)'}]
    if top is not None:
        evidence.insert(0, TOP_PROFILE_EVIDENCE)
    return [field('board_fixed_rated_w', 'Fixed board policies 2/7 rated power', 'W', current / 1000,
                  lower / 1000, upper / 1000, can_edit(image, parser), evidence, offsets=offsets, encoding='<I',
                  scale=1000, stored_units='mW',
                  policy_indices=[2, 7], value_semantics='stored-board-fixed-policy-rated', experimental=True,
                  opt_in=True, ordering_group='board-power', encoding_bounds=(0, 0x7FFFFFFF / 1000),
                  reason='experimental, opt-in: ' + reason + 'rated value of the fixed board policies 2/7 (current = '
                         'rated); XOC-style images raise it with the ceiling; not hardware-tested', **extra)]


@registry.register
def voltage(image, parser):
    result = []
    for rail in parser.rail_limits():
        label = rail['rail_name_inferred']
        key = label.lower() + '_rel_max_mv'
        offsets = [rail['maximum_offset']] if isinstance(parser, BlackwellRom) else parser.copy_offsets(rail['maximum_offset'], 4)
        known_kind = rail['equation_type'] in (1, 7) if isinstance(parser, BlackwellRom) else rail['editable_ceiling']
        reason = 'float32 exact encoding required; runtime voltage may follow unchanged temperature curve'
        if isinstance(parser, TableRom) and not known_kind:
            reason = 'read-only: ' + ada_equation_reason(rail['equation_kind'])
        elif experimental_flag(image, parser, key):
            reason = ('experimental: float32 exact encoding required; not hardware-tested on this board; runtime '
                      'voltage may follow unchanged temperature curve')
        result.append(field(key, label + ' REL equation ceiling', 'mV',
                            rail['output_maximum_uv'] / 1000, rail['output_minimum_uv'] / 1000,
                            0x7FFFFFFF / 1000, can_edit(image, parser) and known_kind,
                            [{'kind': 'reviewed-voltage-output-equation', 'source': SOURCE,
                              'format': 'GB20x rail v30/object 14' if isinstance(parser, BlackwellRom) else
                                        'Ada single logic rail v20, VFE quadratic temperature equation' if ada(parser)
                                        else 'Turing rail 1x (one 14-byte row), VFE quadratic voltage equation'
                                        if turing(parser) else
                                        'Ampere rails v20 (17-byte rows), VFE quadratic voltage equation'}] +
                            ([dict(SINGLE_RAIL_EVIDENCE)] if single_rail(parser) else []) +
                            ([dict(ADA_VOLTAGE_EVIDENCE)] if ada(parser) else []) +
                            ([dict(AMPERE_VOLTAGE_EVIDENCE)] if ampere(parser) else []) +
                            ([dict(TURING_VOLTAGE_EVIDENCE)] if turing(parser) else []),
                            offsets=offsets, encoding='<f', scale=1000, stored_units='uV',
                            writable_status=None if known_kind else 'unsupported' if isinstance(parser, TableRom) else 'unknown',
                            equation_coefficients=rail.get('equation_coefficients'),
                            thermal_derating_preserved=rail.get('thermal_derating_preserved', True),
                            value_semantics='stored-equation-output-ceiling',
                            alias_of=label.lower() + '_rel_equation_max_mv', ui_visible=False,
                            runtime_offset={'units': 'uV', 'type': 'int32', 'signed': True,
                                            'current': None, 'writable': 'unknown'},
                            reason=reason, **(experimental_flag(image, parser, key) if known_kind else {})))
    return result


# Ada VFE equation kinds that keep a role read-only (see TableRom._ada_equation_kind).
ADA_EQUATION_REASONS = {
    'constant': 'constant equation (zero slopes); a ceiling-only edit would not change the evaluated voltage',
    'compare': 'compare expression; the evaluated voltage comes from child terms on fused (speedo) inputs',
    'fixed-point': 'fixed-point equation with an unverified output scale',
}
ADA_VOLTAGE_EVIDENCE = {
    'kind': 'structural-selector-and-equation-rule', 'source': SOURCE,
    'format': 'Ada rail20/05/1f/01/00 row selectors REL +4, ALT +5, OV +6, VMIN +11 (u8, ff absent); VFE30/0b/19/32/19 '
              'with u16 equation count (header bytes 5/10) and u16 links (bytes 2/24)',
    'observation': 'RTX 2000 Ada runtime INFO selectors REL 2, ALT absent, OV 4, VMIN 3 equal rail bytes +4/+5/+6/+11; '
                   'every parseable Ada image keeps REL < ALT < VMIN = OV - 1 as the GET-reviewed GB20x rows; '
                   'the editable kind is the hardware-tested REL shape: float quadratic in uV on sensed temperature, '
                   'nonzero slope, no link and no reference from another equation',
    'set_tested': False}


AMPERE_VOLTAGE_EVIDENCE = dict(
    AMPERE_STRUCTURAL_EVIDENCE, source=SOURCE,
    format='Ampere rail 20/05/11 with one (01 00) or two (02 01) 17-byte rows; selectors REL +4, ALT +5, OV +6, '
           'VMIN +11 (u8, ff absent) as on Ada; VFE 30/09/19/32/18 with 24-byte equations, u8 count (header byte 5) '
           'and u8 links (byte 2; children bytes 11/12 and 15/16)',
    observation='every rail of every image keeps REL < ALT (if present) < VMIN = OV - 1; REL and OV are constant '
                'equations (value, minimum and maximum one constant) on all 35 images; ALT is constant (1100 mV) on '
                'the 18 desktop GeForce images and absent (selector 0xff) on the 17 workstation and laptop images; '
                'rail 1 of the two-rail GA102 images is named MSVDD by inference only (GPC runs on rail 0; XBAR, '
                'DRAM and DISP on rail 1)')


TURING_VOLTAGE_EVIDENCE = dict(
    TURING_STRUCTURAL_EVIDENCE, source=SOURCE,
    format='Turing rail 10/05/0e/01/00, one 14-byte nvgpu 1x row (vbios_voltage_rail_table_1x_entry): selectors REL '
           '+4, ALT +5, OV +6, boot voltage +8, VMIN limit +9 (u8, ff absent); VFE 30/09/19/14/18 with 20 variables, '
           '24-byte equations, u8 count (header byte 5) and u8 links, as on Ampere',
    observation='every image but one keeps REL < ALT (if present) < BOOT = OV - 1, VMIN = OV + 1; the Galax HOF XOC '
                'image points REL and ALT at the OV equation (REL = ALT = OV = 1125 mV); REL, ALT and OV are '
                'constant equations on all 25 images (REL 1068.75 mV, 950 mV on three Max-Q and laptop images; ALT '
                '1093.75 mV, 1118.25 mV on one partner RTX 2080 image, absent on the Quadro RTX 8000 and six Max-Q '
                'and laptop images; OV 1125 mV); the boot voltage equation is fixed point')
TURING_VMIN_EVIDENCE = dict(
    TURING_STRUCTURAL_EVIDENCE, source=SOURCE,
    format='Turing rail row byte 9 (u8, nvgpu 1x vmin_limit_vfe_equ_idx) selects the VFE equation of the VMIN limit',
    observation='on all 25 images a float voltage output whose clamp pins 668-703.75 mV, referenced by no other '
                'equation or selector, with chained equations adding -112.5 to +75 mV: the shape of the Ada row byte '
                '7 equation whose edit moved the driver VMIN (hardware test)')


# The VMIN role selector is the slot the driver's rail INFO lists as VMIN; the evaluated
# VMIN comes from another selector (evaluated_vmin).
VMIN_SLOT_REASONS = {
    'gb20x': 'rail INFO VMIN slot (row +0x21); the driver reports the evaluated VMIN of the row +0x13 equation '
             '(the *_vmin_mv field) and does not report this one',
    'ada': 'rail INFO VMIN slot (row byte 11); on an RTX 2000 Ada a new value here, in its equation and in the '
           'identical equation 1, did not change the driver VMIN, which follows the row byte 7 equation (nvvdd_vmin_mv)',
    'ampere': 'rail INFO VMIN slot (row byte 11) as on Ada, where a new value here did not change the driver VMIN; '
              'the evaluated VMIN follows the row byte 7 equation (the *_vmin_mv field)'}


def ada_equation_reason(kind):
    return ADA_EQUATION_REASONS.get(kind, 'equation shape outside the reviewed temperature-derated form')


SELECTOR_EVIDENCE = {
    'kind': 'saved-get-selector-correlation', 'source': 'saved runtime GET capture',
    'comparisons': '36/36 fields across six Blackwell rows', 'set_tested': False,
    'format': 'Blackwell rail30/05/41/02 and VFE30/0e/1d/ff/19'}
OCP_EVIDENCE = {
    'kind': 'saved-get-policy-monitor-correlation', 'source': 'saved runtime GET capture',
    'format': 'GB20x power40/38-or-3d/66/14 rows13/14; class6 monitor',
    'set_tested': False, 'indices_matched': '134/134',
    'units_basis': 'saved GET INFO+8 is 1 (mA) on rows 13/14'}
REVIEWED_GB20X_IDS = (0x2BB4, 0x2B85, 0x2C02, 0x2C05, 0x2C33)
# The single-rail image has no saved GET; its NVVDD row is compared statically.
SINGLE_RAIL_EVIDENCE = {
    'kind': 'structural-row-comparison', 'source': 'reviewed single-rail Blackwell table layout',
    'scope': 'RTX PRO 6000 Blackwell Workstation Edition 98.02.81.00.07 (10de:2bb1)',
    'format': 'Blackwell rail30/05/41/01/00 (NVVDD only) and VFE30/0e/1d/ff/19',
    'observation': 'NVVDD row identity, REL/ALT/OV/VMIN selector and boot offsets as in the reviewed '
                   'split-rail row; MSVDD voltage devices disabled', 'set_tested': False}

# Rows accepted on devices without saved GET because they equal a reviewed
# shape byte for byte (range bytes excluded) or follow the reviewed chain.
STRUCTURAL_ROW_EVIDENCE = {
    'kind': 'structural-row-comparison', 'source': 'reviewed Blackwell structural row comparison',
    'scope': 'RTX PRO 6000 Blackwell Workstation Edition 98.02.81.00.07, RTX 5060 Ti 98.06.39.00.B2, '
             'RTX 5070 98.05.28.00.1B',
    'set_tested': False, 'runtime_get': False}
NOTEBOOK_OCP_EVIDENCE = dict(
    STRUCTURAL_ROW_EVIDENCE, source='reviewed Blackwell notebook table layout',
    scope='RTX 5080 Laptop GPU 98.03.5C.00.F2 (10de:2c59)',
    format='GB20x notebook rows13/14 type7; monitors 27/28',
    observation='rows 13/14 equal the GET-reviewed Max-Q rows byte for byte (range bytes excluded); monitors '
                '27/28 -> power channels and devices byte-identical to the reviewed NVVDD/MSVDD outputs')
SINGLE_RAIL_OCP_EVIDENCE = dict(
    STRUCTURAL_ROW_EVIDENCE, format='GB20x single-rail row13 type7; monitor 26',
    observation='row13 monitor 26 -> power channel 26 (P+0x3c) and power device 9 (P+0x28) are byte-identical '
                'to the NVVDD output channel 13 (27 on Max-Q) and its device in all seven GET-reviewed sources; '
                'the MSVDD channel and device are disabled')


def single_rail(parser):
    """True for the recognized Blackwell rail table with one (NVVDD) row."""
    if not isinstance(parser, BlackwellRom):
        return False
    try:
        return parser.rail_count(parser.pointer('P', 0x68)) == 1
    except FormatError:
        return False


def rail_identity(parser, item, *, ocp=False):
    reviewed = isinstance(parser, BlackwellRom) and parser.legacy['device'] in REVIEWED_GB20X_IDS
    index = item.get('rail_index', 0 if item['logical_rail_id'] == 'NVVDD' else 1)
    return {'logical_rail_id': item['logical_rail_id'], 'vbios_row_index': index,
            'api_rail_index': index if reviewed else None,
            'power_monitor_rail_id': item.get('power_monitor_rail_id') if ocp else None,
            'api_index_scope': 'saved Linux GET mask bits; no live GPU association' if reviewed else 'unknown'}


@registry.register
def equation_roles(image, parser):
    records = parser.rail_equations()
    result = []
    for item in records:
        prefix = item['logical_rail_id'].lower()
        role = item['role'].lower()
        key = f'{prefix}_{role}_equation_max_mv'
        identities = rail_identity(parser, item)
        known = item['layout_recognized']
        editable = bool(known and item.get('editable_ceiling') and can_edit(image, parser))
        evidence = [dict(SELECTOR_EVIDENCE)] if isinstance(parser, BlackwellRom) else [
            {'kind': 'nvidia-common-prefix-and-reviewed-ada-rel', 'source': SOURCE,
             'format': 'Ada rail20/05/1f/01 VFE30/0b/19/32/19'}, dict(ADA_VOLTAGE_EVIDENCE)] if ada(parser) else [
            dict(TURING_VOLTAGE_EVIDENCE)] if turing(parser) else [dict(AMPERE_VOLTAGE_EVIDENCE)]
        if single_rail(parser):
            evidence.append(dict(SINGLE_RAIL_EVIDENCE))
        reason = ('selector denotes absence' if item['absent'] else
                  item.get('diagnostic', 'equation clamp only; evaluated voltage and runtime offset remain unknown'))
        flags = {}
        label = f"{item['logical_rail_id']} {item['role']} equation output ceiling"
        if item['role'] == 'VMIN':
            # The rail INFO VMIN slot; the evaluated VMIN is the evaluated_vmin field.
            label = f"{item['logical_rail_id']} rail INFO VMIN-slot equation ceiling (not the evaluated VMIN)"
            editable = False
            if not item['absent']:
                reason = 'read-only: ' + VMIN_SLOT_REASONS[parser.family if isinstance(parser, TableRom) else 'gb20x']
        elif isinstance(parser, TableRom) and not item['absent']:
            if not item.get('editable_ceiling'):
                reason = 'read-only: ' + ada_equation_reason(item.get('equation_kind'))
            elif editable:
                flags = experimental_flag(image, parser, key)
                if flags:
                    reason = ('experimental: equation clamp only; not hardware-tested on this board; evaluated '
                              'voltage and runtime offset remain unknown')
        shared = [{'logical_rail_id': other['logical_rail_id'], 'role': other['role'],
                   'selector_index': other['selector_raw']}
                  for other in records if item['equation_offset'] is not None and
                  other['equation_offset'] == item['equation_offset']]
        status = 'verified' if editable else 'unsupported' if item['absent'] or known else 'unknown'
        # Do not present an unrecognized output-unit code as a voltage value.
        value_known = item['output_minimum_uv'] is not None and item.get('output_unit_code') == 2
        current = item['output_maximum_uv'] / 1000 if value_known else None
        offsets = ()
        if editable:
            offsets = [item['maximum_offset']] if isinstance(parser, BlackwellRom) else parser.copy_offsets(item['maximum_offset'], 4)
        selector = {'raw': item['selector_raw'], 'width_bits': item['selector_width_bits'],
                    'offset': item['selector_offset'], 'absent': item['absent']}
        result.append(field(key, label, 'mV',
                            current, item['output_minimum_uv'] / 1000 if value_known else None,
                            0x7FFFFFFF / 1000 if known else None, editable, evidence,
                            offsets=offsets, encoding='<f' if known else '', scale=1000,
                            stored_units='uV' if value_known else None, writable_status=status,
                            value_semantics='stored-equation-output-ceiling', rail_identity=identities,
                            selector=selector, shared_references=shared, equation_offset=item['equation_offset'],
                            equation_type=item.get('equation_type'), output_flags=item.get('output_flags'),
                            unchanged_output_minimum_uv=item['output_minimum_uv'] if value_known else None,
                            runtime_role_candidate={'ALT': 'VOP', 'VMIN': 'VMIN (rail INFO slot)'}.get(
                                item['role'], item['role']),
                            runtime_offset={'units': 'uV', 'type': 'int32', 'signed': True,
                                            'current': None, 'writable': 'unknown'},
                            reason=reason, **flags,
                            **({'equation_kind': item['equation_kind']} if 'equation_kind' in item else {})))
        result.append(field(f'{prefix}_{role}_selector_index', f"{item['logical_rail_id']} {item['role']} selector", 'index',
                            item['selector_raw'], None, None, False, evidence, writable_status='unsupported' if
                            item['selector_raw'] is not None else 'unknown',
                            encoding='<H' if item['selector_width_bits'] == 16 else '<B' if item['selector_width_bits'] == 8 else '',
                            value_semantics='selector-index', rail_identity=identities, selector=selector,
                            reason='selectors are inspected without edits or runtime evaluation'))
    for index in sorted({r['rail_index'] for r in records}):
        item = next(r for r in records if r['rail_index'] == index)
        result.append(field(item['logical_rail_id'].lower() + '_boot_voltage_uv',
                            item['logical_rail_id'] + ' stored boot voltage', 'uV', item['boot_voltage_uv'],
                            None, None, False, [dict(SELECTOR_EVIDENCE)] if isinstance(parser, BlackwellRom) else
                            [{'kind': 'nvidia-common-prefix', 'source': SOURCE}],
                            writable_status='unsupported', stored_units='uV', encoding='<I',
                            value_semantics='stored-boot-voltage', rail_identity=rail_identity(parser, item),
                            reason='boot/factory values are preserved'))
    return result


VMIN_SEMANTICS = 'stored-evaluated-vmin'
FOLLOW_OV_SEMANTICS = 'stored-rail-selector-layout'
FIXED_SEMANTICS = 'stored-fixed-equation-value'
# The fixed REL and ALT fields, and on Turing the evaluated VMIN, are checked together on a joint result.
FIXED_GROUP = 'nvvdd-rel-alt'
# Lowest VMIN offered: no voltage device minimum is decoded, so a fixed reviewed floor.
VMIN_FLOOR_MV = {'gb20x': 450, 'ada': 400, 'ampere': 400, 'turing': 400}
GB20X_VMIN_EVIDENCE = [
    {'kind': 'read-only-rail-status-correlation', 'source': 'read-only driver rail status', 'set_tested': False,
     'format': 'GB20x rail row +0x13 (u16) selects the VFE equation of the evaluated VMIN',
     'observation': 'the driver VMIN equals that equation on the RTX 5080 (constant 800 mV on both rails) and the RTX '
                    'PRO 4000 SFF (min/max trees, 630 mV NVVDD and 655 mV MSVDD); the rail INFO VMIN slot (+0x21) '
                    'holds a 900 or 750 mV constant that the driver does not report; a third-party driver dump shows '
                    'the VMIN_LOGIC perf limit carrying the +0x13 equation index'},
    {'kind': 'hardware-test', 'source': 'edited image loaded as an override; read-only driver rail status',
     'set_tested': True, 'scope': 'RTX 5080 (10de:2c02), NVVDD',
     'observed': 'equation minimum, maximum and value 800 -> 850 mV: the driver reported VMIN 850 mV and the idle '
                 'voltage was 850 mV'}]
ADA_VMIN_EVIDENCE = [
    {'kind': 'hardware-test', 'source': 'edited image loaded as an override; read-only driver rail status',
     'set_tested': True, 'scope': 'RTX 2000 Ada 95.07.47.00.19 (10de:28b0)',
     'format': 'Ada rail row byte 7 (u8) selects the VFE equation of the evaluated VMIN',
     'observed': 'that equation pins 560 mV with its clamp; driver VMIN 650 mV; with the clamp at 700 mV in both '
                 'chains the driver reported 790 mV, the clamp value plus 90 mV both times; a new row byte 11 '
                 'equation did not change the driver VMIN'}]


@registry.register
def evaluated_vmin(image, parser):
    """Evaluated minimum voltage (VMIN) of each rail: the GB20x row +0x13 equation, the Ada/Ampere row byte 7 one,
    the Turing row byte 9 one (nvgpu 1x VMIN limit).

    A GB20x constant equation takes the value in its minimum, maximum and constant;
    an Ada/Ampere/Turing equation whose clamp pins its value takes it in the clamp
    minimum and maximum (both chains). The value stays from a fixed floor up to the lowest
    value of the REL equation list less the most the VMIN equation's chained
    equations add, so the evaluated VMIN never crosses REL. Other shapes, unbounded
    chains and a stored value that is not a whole uV are read-only.
    """
    if not isinstance(parser, (BlackwellRom, TableRom)):
        return []
    family = parser.family if isinstance(parser, TableRom) else 'gb20x'
    result = []
    for item in parser.rail_vmin():
        name = item['logical_rail_id']
        floor, added = VMIN_FLOOR_MV[family], item['added_uv']
        top = (item['rel_lowest_uv'] - added[1]) / 1000 if added and item['rel_lowest_uv'] is not None else None
        current = item['value_uv'] / 1000 if item['pinned'] else None
        reason = None
        if not item['pinned']:
            reason = 'read-only: the evaluated VMIN equation ' + item['diagnostic'] + '; only a ' + (
                'constant equation takes this edit' if family == 'gb20x' else 'clamp that pins the value takes this edit')
        elif top is None:
            reason = ('read-only: the REL equation list or the equations chained to VMIN have no bounded value, so '
                      'VMIN cannot be kept below REL')
        elif item['value_uv'] != int(item['value_uv']):
            reason = f"read-only: the stored VMIN ({item['value_uv']} uV) is not a whole uV, so it could not be restored"
        elif not floor <= current <= top:
            reason = (f'read-only: the stored VMIN is outside {floor} mV up to {top:g} mV, the lowest REL value less '
                      'what the chained equations can add')
        editable = reason is None and can_edit(image, parser)
        offsets = ()
        if editable:
            offsets = ([item['minimum_offset'], item['maximum_offset'], item['value_offset']] if family == 'gb20x' else
                       parser.copy_offsets(item['minimum_offset'], 4) + parser.copy_offsets(item['maximum_offset'], 4))
        if reason is None:
            chained = (f'its chained equations add {added[0] / 1000:g} to {added[1] / 1000:g} mV, so the value stays '
                       f'at most the lowest REL value less {added[1] / 1000:g} mV')
            reason = {
                'gb20x': 'experimental: constant equation selected at rail row +0x13, the evaluated VMIN; the edit '
                         'writes its minimum, maximum and value; at most the lowest REL value; hardware-tested '
                         'on an RTX 5080 (800 -> 850 mV: the driver reported VMIN 850 mV and the idle voltage was '
                         '850 mV); other boards not hardware-tested',
                'ada': 'experimental: clamp of the equation selected at rail row byte 7, which pins the evaluated '
                       f'VMIN; the edit writes the clamp minimum and maximum; {chained}; on an RTX 2000 Ada the '
                       'driver reported this value plus 90 mV (hardware test), and the offset may differ per board',
                'ampere': 'experimental: clamp of the equation selected at rail row byte 7, the Ada VMIN layout; the '
                          f'edit writes the clamp minimum and maximum; {chained}; on Ada the driver reported the '
                          'value plus its chained equations; not hardware-tested on Ampere',
                'turing': 'experimental: clamp of the equation selected at rail row byte 9 (nvgpu 1x '
                          'vmin_limit_vfe_equ_idx), the shape of the Ada VMIN equation; the edit writes the clamp '
                          f'minimum and maximum; {chained}; on Ada the driver reported the value plus its chained '
                          'equations; the relation to the driver VMIN on Turing is unknown; ' + TURING_UNTESTED}[family]
        selector = {'raw': item['selector_raw'], 'width_bits': 16 if family == 'gb20x' else 8,
                    'offset': item['selector_offset'], 'absent': item['equation_offset'] is None}
        result.append(field(name.lower() + '_vmin_mv', f'{name} minimum voltage (VMIN)', 'mV', current,
                            floor if editable else None, top if editable else None, editable,
                            [dict(e) for e in (GB20X_VMIN_EVIDENCE if family == 'gb20x' else
                                               [TURING_VMIN_EVIDENCE, TURING_VOLTAGE_EVIDENCE] + ADA_VMIN_EVIDENCE
                                               if family == 'turing' else ADA_VMIN_EVIDENCE +
                                               ([AMPERE_VOLTAGE_EVIDENCE] if family == 'ampere' else []))],
                            offsets=offsets, encoding='<f' if editable else '', scale=1000, stored_units='uV',
                            writable_status=None if editable else 'unsupported', experimental=True,
                            value_semantics=VMIN_SEMANTICS, rail_identity=rail_identity(parser, item),
                            selector=selector, equation_offset=item['equation_offset'],
                            equation_type=item['equation_type'], runtime_role_candidate='VMIN', reason=reason,
                            # Turing: checked with the fixed REL/ALT values on a joint result.
                            **(dict(ordering_group=FIXED_GROUP, encoding_bounds=(floor, 0x7FFFFFFF / 1000))
                               if family == 'turing' and editable else {})))
    return result


LEGACY_DIRECTORY_EVIDENCE = {
    'kind': 'structural-table', 'source': 'GB20x VBIOS corpus',
    'format': 'GB20x legacy image v3 object directory (objects 0xfa, 0xbd first), SHA384 per object, directory '
              'digest at legacy+0x209',
    'observation': 'every hash and digest matches on every GB20x image of the corpus; object 0x21 spans exactly the '
                   'rail table (P+0x68) and object 0x35 holds it too; the vendor XOC images update both hashes, the '
                   'digest and the legacy image checksum'}
FOLLOW_OV_EVIDENCE = {
    'kind': 'vendor-image-comparison', 'source': 'ASUS RTX 5090 XOC and MSI RTX 5090 Lightning images',
    'observation': 'against the stock ASUS RTX 5090 image the XOC images point the NVVDD REL and ALT selectors (row '
                   '+0x0d and +0x0f) at the OV equation, a constant 1200 mV, so REL = ALT = OV; their VFE equations '
                   'and MSVDD row are unchanged', 'set_tested': False}
FOLLOW_OV_HARDWARE = {'kind': 'hardware-test', 'source': 'edited image loaded as an override', 'set_tested': True,
                      'scope': 'one RTX 5090',
                      'observed': 'the copy with REL and ALT following OV loaded without problems'}
ADA_FOLLOW_OV_EVIDENCE = {
    'kind': 'structural-selector-rule', 'source': 'Ada VBIOS corpus, 21 parseable images',
    'format': 'Ada rail row REL +4 and ALT +5 (u8) in the legacy image of every chain; additive image checksum',
    'observation': 'every parseable image selects a constant 1200 mV OV equation and keeps REL < ALT < VMIN = OV - 1; '
                   'no Ada image points REL or ALT at OV; row byte 10 holds 2, the REL index, on every image: its '
                   'meaning is unknown and the field leaves it', 'set_tested': False}


def ada_follow_ov(image, parser):
    """rail_follow_ov on Ada: the u8 REL/ALT selectors of the rail row, in the legacy image of every chain."""
    info = parser.rail_fixed()
    selectors, ov = info['selectors'], info['selectors']['OV']
    moved = ['REL'] + ([] if selectors['ALT'] == 0xFF else ['ALT'])
    own = [selectors[role] for role in moved]
    state = 1 if set(own) == {ov} else 0 if len(set(own + [ov])) == len(moved) + 1 else None
    names, flat = (('REL and ALT selectors', 'REL = ALT = OV') if len(moved) == 2 else
                   ('REL selector (this image has no ALT selector)', 'REL = OV'))
    if state == 1:
        reason = (f'read-only: the OV equation is already selected by the NVVDD {names}; the image keeps no record '
                  'of the original selectors, so the editor cannot restore them (edit the original image instead)')
    elif state is None or info['ov_uv'] is None:
        reason = 'read-only: the NVVDD REL, ALT and OV selectors or the OV equation hold another shape'
    else:
        reason = None
    # The step to OV depends on the stored REL: a compare REL on fused inputs can sit well below it.
    rel, stored = info['roles']['REL'], ''
    if state == 0 and rel['lowest_uv'] is not None:
        lo, hi = rel['lowest_uv'] / 1000, rel['highest_uv'] / 1000
        compare = ' (a compare on fused speedo inputs)' if rel['equation_kind'] == 'compare' else ''
        stored = (f'REL is {lo:g} mV' if lo == hi else f'REL spans {lo:g} to {hi:g} mV') + compare + ' in this image; '
    editable = reason is None and can_edit(image, parser)
    offsets, layout = [], ()
    if editable:
        offsets = [at for role in moved for at in parser.copy_offsets(info['roles'][role]['selector_offset'], 1)]
        copies = len(offsets) // len(moved)
        layout = ((0, tuple(bytes((selectors[role],)) for role in moved for _ in range(copies))),
                  (1, (bytes((ov,)),) * len(offsets)))
    return [field('nvvdd_rel_alt_follow_ov', 'REL and ALT follow OV (XOC-style flat voltage limit)', 'flag', state,
                  0 if editable else None, 1 if editable else None, editable,
                  [dict(ADA_FOLLOW_OV_EVIDENCE), dict(FOLLOW_OV_EVIDENCE, use='GB20x analogy'),
                   dict(ADA_VOLTAGE_EVIDENCE)],
                  offsets=offsets, encoding='<B' if editable else '', scale=1, layout=layout,
                  writable_status=None if editable else 'unsupported', experimental=True, opt_in=True,
                  value_semantics=FOLLOW_OV_SEMANTICS,
                  rail_identity=rail_identity(parser, {'logical_rail_id': 'NVVDD', 'rail_index': 0}),
                  reason=reason or f'experimental, opt-in: 1 points the NVVDD {names} at the OV equation '
                                   f"({info['ov_uv'] / 1000:g} mV) in every chain: {flat}, a flat voltage limit, as "
                                   'the ASUS XOC and MSI Lightning RTX 5090 images do (confirmed on one RTX 5090); '
                                   f'{stored}raising REL lets the GPU request a higher voltage on its VF curve, and '
                                   'the board power and thermal limits still apply; the value 1 cannot be undone in '
                                   'the copy; not hardware-tested on Ada')]


@registry.register
def rail_follow_ov(image, parser):
    """XOC-style flat NVVDD voltage limit: REL and ALT select the OV equation (1) or their own (0).

    Opt-in, GB20x and Ada. On GB20x the rail table sits in the legacy image, whose
    objects 0x21/0x35, directory digest and checksum the editor repairs; on Ada its
    u8 selectors are written in the legacy image of every chain (ada_follow_ov).
    The value 1 can be written while REL, ALT (if present) and OV select distinct
    equations, OV a constant voltage. The value 1 is read-only: the image keeps no
    record of the original REL and ALT selectors, so the editor cannot restore them.
    """
    if ada(parser):
        return ada_follow_ov(image, parser)
    if not isinstance(parser, BlackwellRom):
        return []
    roles = {r['role']: r for r in parser.rail_equations() if r['logical_rail_id'] == 'NVVDD'}
    rel, alt, ov = roles['REL'], roles['ALT'], roles['OV']
    moved = [rel] + ([] if alt['absent'] else [alt])
    selectors = [r['selector_raw'] for r in moved]
    state = (1 if set(selectors) == {ov['selector_raw']} else
             0 if len(set(selectors + [ov['selector_raw']])) == len(moved) + 1 else None)
    try:
        rail, length = parser.rail_table()
        owner = parser.legacy_owner(rail, length)
        owned = (owner['id'], owner['data'], owner['size']) == (0x21, rail, length)
    except FormatError:
        owned = False
    ov_value = parser.constant_equation(ov['equation_offset']) if ov['equation_offset'] is not None else None
    # Images without an ALT selector (RTX PRO 6000 Workstation, PRO 4000 SFF, Max-Q, notebook) move REL alone.
    names, flat = (('REL and ALT selectors', 'REL = ALT = OV') if len(moved) == 2 else
                   ('REL selector (this image has no ALT selector)', 'REL = OV'))
    if state == 1:
        reason = (f'read-only: the OV equation is already selected by the NVVDD {names}; the image keeps no record '
                  'of the original selectors, so the editor cannot restore them (edit the original image instead)')
    elif state is None or rel['absent'] or ov_value is None or not all(r['layout_recognized'] for r in moved):
        reason = 'read-only: the NVVDD REL, ALT and OV selectors or the OV equation hold another shape'
    elif not owned:
        reason = ('read-only: the rail table is not the exact legacy-image object 0x21 of a valid legacy directory, '
                  'so its hashes cannot be repaired')
    else:
        reason = None
    editable = reason is None and can_edit(image, parser)
    layout = ()
    if editable:
        own = tuple(struct.pack('<H', r['selector_raw']) for r in moved)
        layout = ((0, own), (1, (struct.pack('<H', ov['selector_raw']),) * len(moved)))
    return [field('nvvdd_rel_alt_follow_ov', 'REL and ALT follow OV (XOC-style flat voltage limit)', 'flag', state,
                  0 if editable else None, 1 if editable else None, editable,
                  [dict(FOLLOW_OV_HARDWARE), dict(FOLLOW_OV_EVIDENCE), dict(LEGACY_DIRECTORY_EVIDENCE),
                   dict(SELECTOR_EVIDENCE)],
                  offsets=[r['selector_offset'] for r in moved] if editable else (),
                  encoding='<H' if editable else '', scale=1, layout=layout,
                  writable_status=None if editable else 'unsupported', experimental=True, opt_in=True,
                  value_semantics=FOLLOW_OV_SEMANTICS, rail_identity=rail_identity(parser, rel),
                  reason=reason or f'experimental, opt-in: 1 points the NVVDD {names} at the OV equation '
                                   f'({ov_value / 1000:g} mV), as the ASUS XOC and MSI Lightning images do: {flat}, a '
                                   'flat voltage limit; the rail table is in the legacy image, whose object hashes, '
                                   'directory digest and checksum the edit repairs; the value 1 cannot be undone in '
                                   'the copy; confirmed on one RTX 5090 (the edited copy loaded as an override without '
                                   'problems)')]


ADA_FIXED_EVIDENCE = {
    'kind': 'structural-selector-and-equation-rule', 'source': SOURCE,
    'format': 'Ada VFE equation selected at rail row byte 4 (REL) or 5 (ALT): float quadratic voltage output with '
              'zero slopes, no link and no reference; clamp maximum (byte 7) and constant (byte 11) written in every '
              'chain, clamp minimum (byte 3) kept',
    'observation': 'REL is such a constant on the RTX 4090, 4080 and RTX 4000 Ada images and ALT on the 4090, 4080, '
                   '4080 SUPER, 4070 Ti SUPER and 4060 ones, each with minimum = maximum = constant; every OV is a '
                   'constant 1200 mV; on an RTX 2000 Ada a REL ceiling edit (a temperature-derated REL) moved the '
                   'evaluated REL', 'set_tested': False}
TURING_FIXED_EVIDENCE = dict(
    TURING_STRUCTURAL_EVIDENCE, source=SOURCE,
    format='Turing rail row selectors REL (+4) and ALT (+5), nvgpu 1x rel_limit_vfe_equ_idx and '
           'alt_rel_limit_vfe_equ_idx, name constant VFE equations: value = clamp maximum (the stock images also '
           'store it as the minimum), no slope, no link and no reference from another equation; clamp maximum '
           '(byte 7) and constant (byte 11) written in every chain, clamp minimum (byte 3) kept',
    observation='REL 1068.75 mV (950 mV on three Max-Q and laptop images), ALT 1093.75 mV (1118.25 mV on one partner '
                'RTX 2080 image), OV 1125 mV on every image, the ASUS XOC image included; the Galax HOF XOC image '
                'selects the OV equation for REL and ALT instead; the values match the commonly reported Turing '
                'voltage caps (not verified here)')


@registry.register
def fixed_voltage(image, parser):
    """Fixed NVVDD REL and ALT values (Ada, Turing): a constant equation's constant and clamp maximum, in every chain.

    A field is listed for a constant REL or ALT equation (Turing: for every REL or ALT
    selector, read-only with the reason unless constant) and is editable when
    TableRom.rail_fixed reports it fixed and OV is a constant. The value goes from the
    clamp minimum, the stored value, which the edit keeps (so it can be written back),
    up to the OV value; REL stays at most the lowest ALT value and ALT at least the
    highest REL value. Both fields form one ordering group. The Turing fields are
    opt-in (their effect is untested); there both also stay at or above the stored
    boot voltage and the highest evaluated VMIN (its clamp plus what its chained
    equations can add), the VMIN field joins the ordering group, and ALT needs a
    constant REL.
    """
    if not (ada(parser) or turing(parser)):
        return []
    tu = turing(parser)
    info = parser.rail_fixed()
    roles, ov = info['roles'], info['ov_uv']
    floor = None
    if tu:
        vmin = next((v for v in parser.rail_vmin() if v['logical_rail_id'] == 'NVVDD'), None)
        if vmin is not None and vmin['pinned'] and vmin['added_uv'] is not None:
            floor = max(vmin['value_uv'] + vmin['added_uv'][1], info['boot_uv'])
    result = []
    for role, other in (('REL', 'ALT'), ('ALT', 'REL')):
        item, partner = roles[role], roles[other]
        if item is None or item['equation_kind'] != 'constant' and not tu:
            continue
        lower, upper = item['minimum_uv'], ov
        if role == 'REL' and partner is not None:
            upper = None if partner['lowest_uv'] is None or ov is None else min(ov, partner['lowest_uv'])
        elif role == 'ALT':
            lower = None if partner['highest_uv'] is None else max(lower, partner['highest_uv'])
        if tu:
            lower = None if lower is None or floor is None else max(lower, floor)
        current = item['value_uv'] if item['equation_kind'] == 'constant' else None
        # Bounds are reported whenever they exist, so a joint result outside them is refused.
        bounded = current is not None and None not in (ov, lower, upper)
        if not item['fixed']:
            reason = f'read-only: the NVVDD {role} equation ' + item['diagnostic']
        elif tu and role == 'ALT' and partner['equation_kind'] != 'constant':
            reason = 'read-only: the REL equation is not a constant, so ALT cannot be kept at or above it'
        elif ov is None:
            reason = 'read-only: the OV equation is not a constant voltage, so it gives no upper bound'
        elif tu and floor is None:
            reason = ('read-only: the VMIN equation or its chained equations have no bounded value, so the value '
                      'cannot be kept above VMIN')
        elif not bounded:
            reason = f'read-only: the {other} equation list has no bounded value, so REL <= ALT cannot be kept'
        elif current != int(current) or item['minimum_uv'] != int(item['minimum_uv']):
            reason = f'read-only: the stored value ({current} uV) is not a whole uV, so it could not be restored'
        elif not lower <= current <= upper:
            reason = f'read-only: the stored value is outside {lower / 1000:g} mV up to {upper / 1000:g} mV'
        else:
            floors = (['the highest REL value'] if role == 'ALT' else []) + ([
                'the stored boot voltage', 'the highest VMIN (VMIN plus what its chained equations add)'] if tu else [])
            span = (f'from its clamp minimum up to the OV value ({ov / 1000:g} mV)' +
                    (' and at most the lowest ALT value' if role == 'REL' and partner is not None else ''))
            if floors:
                span += ', and at least ' + (', '.join(floors[:-1]) + ' and ' if floors[1:] else '') + floors[-1]
            reason = None
        editable = reason is None and can_edit(image, parser)
        offsets = ()
        if editable:
            offsets = parser.copy_offsets(item['maximum_offset'], 4) + parser.copy_offsets(item['value_offset'], 4)
        if reason is None:
            reason = (f"experimental{', opt-in' if tu else ''}: the NVVDD {role} equation is a constant; the edit "
                      'writes its constant and clamp maximum in every chain and keeps its clamp minimum, the lowest '
                      f'value offered; {span}; raising {role} lets the GPU request a higher voltage on its VF curve, '
                      'and the board power and thermal limits still apply; ' +
                      ('more voltage means more heat, power and wear; ' + TURING_UNTESTED if tu else
                       'not hardware-tested on Ada'))
        result.append(field(f'nvvdd_{role.lower()}_fixed_mv', f'NVVDD {role} fixed voltage', 'mV',
                            current / 1000 if current is not None else None,
                            lower / 1000 if bounded else None, upper / 1000 if bounded else None, editable,
                            [dict(TURING_FIXED_EVIDENCE), dict(TURING_VOLTAGE_EVIDENCE)] if tu else
                            [dict(ADA_FIXED_EVIDENCE), dict(ADA_VOLTAGE_EVIDENCE)],
                            offsets=offsets, encoding='<f' if editable else '', scale=1000, stored_units='uV',
                            writable_status=None if editable else 'unsupported', experimental=True,
                            value_semantics=FIXED_SEMANTICS, equation_offset=item['equation_offset'],
                            rail_identity=rail_identity(parser, {'logical_rail_id': 'NVVDD', 'rail_index': 0}),
                            runtime_role_candidate={'ALT': 'VOP'}.get(role, role), reason=reason,
                            **({'opt_in': True} if tu else {}),
                            **(dict(ordering_group=FIXED_GROUP, encoding_bounds=(item['minimum_uv'] / 1000,
                                                                                  ov / 1000)) if editable else {})))
    return result


def profiles_decoded(parser):
    """True when every override profile decodes; decoded entries only target policies 2/7/8/9."""
    try:
        parser.power_profiles()
    except FormatError:
        return False
    return True


def ada_policy_fields(image, parser, items, keys, labels, *, group, evidence, reasons, **extra):
    """Maximum and rated fields of Ada policy rows written together in every duplicate chain.

    items share one role (one row, or the two 12 V input thresholds). A value is
    editable only while every row holds the same value. Units follow the row unit
    flag: W over stored mW, or mA. Both values stay read-only when another row of
    the same class and unit reads the same channel (it may bind instead), and
    class-5 rows carry policy_class 'hardware-threshold'. Ampere rows of the same
    class and unit on a sum channel that adds this one are listed in
    summed_cap_rows and named in the reason: they may bind first. The reason
    names the connector_sum_power fields of a row that has them.
    """
    watts = items[0]['units'] == 'mW'
    scale, units = (1000, 'W') if watts else (1, 'mA')
    editable = can_edit(image, parser)
    maxima, rated = {i['maximum_raw'] for i in items}, {i['default_raw'] for i in items}
    raw = [{'minimum': i['minimum_raw'], 'rated': i['default_raw'], 'maximum': i['maximum_raw'],
            'units': i['units']} for i in items]
    own = {i['vbios_row_index'] for i in items}
    others = sorted({o['row']: o for i in items for o in i['same_channel_rows'] if o['row'] not in own}.values(),
                    key=lambda o: o['row'])
    threshold = items[0]['type'] == 5
    if threshold:
        extra = dict(extra, policy_class='hardware-threshold')
    if others:
        extra = dict(extra, same_channel_rows=[{'row': o['row'], 'parameter_byte_0': o['parameter_byte_0'],
                                                'minimum': o['minimum_raw'], 'rated': o['default_raw'],
                                                'maximum': o['maximum_raw'], 'units': o['units']} for o in others])
    summed = sorted({o['row']: o for i in items for o in i.get('summed_cap_rows', ())}.values(),
                    key=lambda o: o['row'])
    if summed:
        extra = dict(extra, summed_cap_rows=[{'row': o['row'], 'power_channel': o['channel_index'],
                                              'summed_channels': o['summed_channels'], 'minimum': o['minimum_raw'],
                                              'rated': o['default_raw'], 'maximum': o['maximum_raw'],
                                              'units': o['units']} for o in summed])
    common = dict(encoding='<I', scale=scale, stored_units=items[0]['units'],
                  policy_indices=[i['vbios_row_index'] for i in items], experimental=True, ordering_group=group,
                  encoding_bounds=(0, 0x7FFFFFFF / scale), power_channel=items[0]['channel_index'],
                  immutable_row_sha256=[i['immutable_row_sha256'] for i in items],
                  raw_bounds=raw[0] if len(raw) == 1 else raw, **extra)

    def offsets(name):
        return [at for i in items for at in parser.copy_offsets(i[name], 4)]

    def amount(value):
        return f'{value / scale:g} {units}'
    if summed:
        own_field = ampere_policy(parser, 'connector_sum')
        reasons = tuple(r + ''.join(
            f"; row {o['row']} caps the sum of power channels {', '.join(map(str, o['summed_channels']))} at "
            f"{amount(o['default_raw'])} rated, {amount(o['maximum_raw'])} maximum, and may bind first: raising "
            'this limit alone may have no effect' +
            (' (raise connector_sum_power_rated_w and connector_sum_power_max_w too)'
             if own_field and own_field['row'] == o['row'] else '') for o in summed) for r in reasons)
    differ = 'read-only: the rows of this policy hold different values'
    if others:
        kind = 'hardware threshold' if threshold else 'policy row'
        differ = ('read-only: ' + '; '.join(
            f"row {o['row']} (parameter byte 0 = {o['parameter_byte_0']}, rated {amount(o['default_raw'])}, "
            f"maximum {amount(o['maximum_raw'])})" for o in others) +
            (f' is another {kind}' if len(others) == 1 else f' are other {kind}s') +
            ' of the same class and unit on this power channel; which row binds is unknown, '
            'so editing this row alone may have no effect')
    one_max, one_rated = len(maxima) == 1 and not others, len(rated) == 1 and not others
    if not profiles_decoded(parser):
        # As for the TGP: an undecoded override profile may target this policy.
        one_max = one_rated = False
        differ = ('read-only: the power override profiles do not decode, so a profile may override this '
                  'policy; editing it alone may have no effect')
    return [field(keys[0], labels[0], units, max(maxima) / scale if len(maxima) == 1 else None,
                  max(rated) / scale, 0x7FFFFFFF / scale, editable and one_max, [dict(e) for e in evidence],
                  offsets=offsets('maximum_offset'), value_semantics='stored-policy-maximum',
                  writable_status=None if one_max else 'unsupported', reason=reasons[0] if one_max else differ,
                  **common),
            field(keys[1], labels[1], units, max(rated) / scale if len(rated) == 1 else None,
                  max(i['minimum_raw'] for i in items) / scale, min(maxima) / scale, editable and one_rated,
                  [dict(e) for e in evidence], offsets=offsets('default_offset'),
                  value_semantics='stored-policy-rated-default', writable_status=None if one_rated else 'unsupported',
                  reason=reasons[1] if one_rated else differ, **common)]


ADA_SLOT_EVIDENCE = [
    dict(ADA_RUNTIME_EVIDENCE, format='Ada power row class 4 mW on channel 4',
         observation='policy 5: API type 3, monitor 4 (class 8, rail 255), 1000/66000/66000 mW, CONTROL current '
                     '66000; the same identity as the GET-reviewed GB20x SFF slot policy row 19'),
    dict(ADA_STRUCTURAL_EVIDENCE, format='Ada power row shape 830b68bb (range bytes excluded) on a channel '
                                         'byte-identical to the GB20x slot input channel 1',
         observation='66 W (5.5 A x 12 V) on every Ada image with this row')]
ADA_INPUT_EVIDENCE = [
    dict(ADA_STRUCTURAL_EVIDENCE, format='Ada power rows class 5 (hardware threshold, nvgpu bios.h) mA, shapes '
                                         '619656b5/6951b88d, threshold index 0/1 (parameter byte 0), channel 9',
         observation='channel 9 is byte-identical to the GB20x 12 V input-current channel 9 that saved GET '
                     'identifies (policy 9, mA); rated values 16-45 A, about 1.2-1.69 x rated TGP / 12 V on the 11 '
                     'images with these rows; thresholds 0 and 1 hold equal rated values on all 11 and equal maxima '
                     'on 10 (RTX 4500 Ada: 22000/21000 mA), minima differ on two (0/1000 mA); a value is editable '
                     'only where both rows hold it'),
    dict(ADA_RUNTIME_EVIDENCE, observation='units only: the class-5 mA row 8 of this board reports limit unit 1 (mA); '
                                           'the 12 V input rows are not present on this board')]


AMPERE_CHANNEL_FORMAT = ('Ampere power row class/unit flags (byte 0) and channel (byte 1); power channel table P+0x3c '
                         'v0x20 with 22- or 26-byte entries: class 5 single input at 12 V (bytes 2..7), rail byte 1, '
                         'no parameter but the provider byte 15')
AMPERE_SLOT_EVIDENCE = [dict(
    AMPERE_STRUCTURAL_EVIDENCE, format=AMPERE_CHANNEL_FORMAT + '; class 4 mW row on the PCIe slot channel (rail 0xff)',
    observation='the slot channel is byte-identical (zero padded) to the Ada slot channel of the GET-reviewed RTX 2000 '
                'Ada policy 5; one such row (row 5) on every desktop and workstation image that has it, rated 66 W; '
                'laptops, the A1000 and the RTX 3050 8GB store none')]
AMPERE_CONNECTOR_EVIDENCE = [dict(
    AMPERE_STRUCTURAL_EVIDENCE, format=AMPERE_CHANNEL_FORMAT + '; class 4 mW rows on the external 12 V connector '
                                                               'channels, rails 0xfa, 0xfb, 0xfc and 0xe4',
    observation='one row per connector sense channel, numbered in power-row order; rated 150-175 W on rails '
                '0xfa/0xfb/0xe4 and 75-87.5 W on 0xfc; the PCIe CEM 8-pin (150 W) and 6-pin (75 W) ratings are a '
                'hint, not an identity: one physical connector can span several channels (RTX A6000 and A40 EPS '
                '8-pin: two at 150 W; RTX 3090 Ti 16-pin: three at 162 W); rail names are inferred, not read at '
                'runtime; with the slot policy they likely cap the board power below a TGP raised past their sum, '
                'and a class-4 row on a sum of these channels (RTX 3080 Ti 300 or 450 W, RTX A6000 280 W) may bind '
                'first (inferred, untested)')]
AMPERE_CONNECTOR_SUM_EVIDENCE = [dict(
    AMPERE_STRUCTURAL_EVIDENCE, format=AMPERE_CHANNEL_FORMAT + '; class 4 mW row on a class-2 sum channel with the '
                                                               '12 V bytes of a connector channel and no other '
                                                               'parameter whose relationship entries (byte 1: '
                                                               'channel, bytes 2..5: weight, 0x1000 = 1.0) add only '
                                                               'connector channels (rails 0xfa, 0xfb, 0xfc, 0xe4), '
                                                               'at least two, each with weight 1.0',
    observation='one such row (row 11) on three images: an RTX 3080 Ti with two connector channels (channels 5 and 6; '
                '300 W rated, below 2 x 162 W; 350 W maximum, 2 x 175 W), an RTX 3080 Ti with three (channels 5-7; '
                '450 W, below 3 x 162 W) and the RTX A6000 (channels 5 and 6; 280 W, below 2 x 150 W); '
                'none on the other images; the sum channel reads rail 0xe0 on the RTX 3080 Ti and 0xe4 on the A6000, '
                'so it is identified by its members, not its rail; channel 1 of the three-connector RTX 3080 Ti also '
                'adds two connector channels but holds 0x11c7 in bytes 6..7 (only a class-0 row reads it); '
                'enforcement never observed')]
AMPERE_INPUT_EVIDENCE = [dict(
    AMPERE_STRUCTURAL_EVIDENCE, format=AMPERE_CHANNEL_FORMAT + '; class 5 (hardware threshold, nvgpu bios.h) mA rows '
                                                               'on the 12 V input channel, rail 0xe0',
    observation='the Ada 12 V input-current rows and the GB20x input channel 9 read rail 0xe0; one row on most '
                'images (14-37.8 A, about 1.1-1.9 x rated TGP / 12 V), two equal 45 A rows (thresholds 0 and 1) on '
                'the RTX 3090 Ti; none on the RTX 3080/3090, A40, A6000, laptops and slot-powered boards; a value is '
                'editable only where every row holds it')]
AMPERE_SLOT_CURRENT_EVIDENCE = [dict(
    AMPERE_STRUCTURAL_EVIDENCE, format=AMPERE_CHANNEL_FORMAT + '; class 5 (hardware threshold) mA row on the PCIe '
                                                               'slot channel',
    observation='the same class, unit and channel as the GET-reviewed RTX 2000 Ada policy 8 (CONTROL current = rated '
                'there); 7-11.35 A rated (row 8) on the desktop and workstation images')]
AMPERE_CONNECTOR_CURRENT_EVIDENCE = [dict(
    AMPERE_STRUCTURAL_EVIDENCE, format=AMPERE_CHANNEL_FORMAT + '; class 5 (hardware threshold) mA row on the channel '
                                                               'of a connector power row',
    observation='row 9 (threshold index 1, parameter byte 0) on the first connector channel and row 10 (threshold '
                'index 2) on the second, on the desktop and workstation images with connector rows: rated 13-22.75 A, '
                'maximum 13-32 A; a connector channel without such a row (RTX 3080 Ti channel 7, RTX 3070 rail 0xfc) '
                'has no field; the laptop row 9 has no connector power row on its channel (threshold index 0) and no '
                'field; the threshold indices run slot 0, connector 1, connector 2 as on Turing; rows on the 12 V '
                'input channel (rail 0xe0) stay input_current')]


def ampere_policy(parser, role):
    """The single Ampere power row of a role, or None (see TableRom.ampere_policies)."""
    items = parser.ampere_policies(role)
    return items[0] if len(items) == 1 else None


@registry.register
def output_ocp(image, parser):
    if turing(parser):
        # Row 13: class 10 mA on the channel byte-identical to the Ada NVVDD current sensor. The
        # Ampere class-0 rule stays off Turing: the ASUS XOC image turns this row into class 0.
        items = parser.ampere_policies('nvvdd_current_limit')
        if len(items) != 1:
            return []
        others = [{'row': t['vbios_row_index'], 'power_channel': t['channel_index'], 'minimum': t['minimum_raw'],
                   'rated': t['default_raw'], 'maximum': t['maximum_raw'], 'units': 'mA'}
                  for t in parser.ampere_policies('nvvdd_threshold')]
        note = ''.join(f"; row {o['row']} is a class-5 mA threshold on another NVVDD channel ({o['power_channel']}; "
                       f"{o['rated'] / 1000:g} A rated, {o['maximum'] / 1000:g} A maximum; meaning unknown, no field) "
                       'and may bind first' for o in others)
        return ada_policy_fields(
            image, parser, items, ('nvvdd_output_ocp_max_ma', 'nvvdd_output_ocp_rated_ma'),
            ('NVVDD output current limit ceiling', 'NVVDD output current limit (rated)'), group='nvvdd-output-ocp',
            opt_in=True, evidence=TURING_NVVDD_LIMIT_EVIDENCE, **({'nvvdd_threshold_rows': others} if others else {}),
            reasons=('experimental, opt-in: ceiling of the NVVDD output current limit (row 13, class 10, not described '
                     'in nvgpu); SET and enforcement untested; ' + TURING_UNTESTED + note + '; stored value, not a '
                     'hardware-safe VRM rating',
                     'experimental, opt-in: rated NVVDD output current limit (row 13, class 10 on the NVVDD current '
                     'sensor channel); whether the firmware enforces it is unknown; it guards the VRM, so keep it '
                     'unless a load log shows the NVVDD current near it; ' + TURING_UNTESTED + note + '; stored value, '
                     'not a hardware-safe VRM rating'))
    if ampere(parser):
        # Class-0 mA rows on the NVVDD output-current channel (row 13; single-rail images
        # add a 5001 A row 18). As on Ada, whether the firmware enforces them is unproven.
        items = sorted(parser.ampere_policies('nvvdd_current'), key=lambda i: i['maximum_raw'])
        if not items:
            return []
        item = items[0]
        others = [{'row': o['row'], 'minimum': o['minimum_raw'], 'rated': o['default_raw'],
                   'maximum': o['maximum_raw'], 'units': 'mA'} for o in items[1:]]
        return [field('nvvdd_output_ocp_max_ma', 'NVVDD output current policy ceiling', 'mA', item['maximum_raw'],
                      None, None, False, [dict(AMPERE_STRUCTURAL_EVIDENCE, format='Ampere power row class 0 mA on an '
                                                                                  'NVVDD output channel (class 1, rail 1)',
                                               observation='row 13 on every image (54-445 A); the single-rail '
                                                           'images add a 5001 A row 18 on the same channel')],
                      writable_status='unsupported', stored_units='mA', value_semantics='stored-policy-maximum',
                      policy_indices=[item['vbios_row_index']],
                      raw_bounds={'minimum': item['minimum_raw'], 'rated': item['default_raw'],
                                  'maximum': item['maximum_raw'], 'units': 'mA'},
                      **({'same_channel_rows': others} if others else {}),
                      reason='read-only: class-0 NVVDD output-current policy (the lowest ceiling on this channel); '
                             'whether the firmware enforces it is unproven, as on Ada')]
    if ada(parser):
        # Row 13 (class 0, mA) on the NVVDD output-current channel. It is not in the
        # runtime policy list of the RTX 2000 Ada, so its enforcement is unproven.
        item = parser.ada_policy('nvvdd_current')
        if item is None:
            return []
        return [field('nvvdd_output_ocp_max_ma', 'NVVDD output current policy ceiling', 'mA', item['maximum_raw'],
                      None, None, False, [dict(ADA_STRUCTURAL_EVIDENCE, format='Ada power row class 0 mA on channel 19 '
                                                                              '(NVVDD output current sensor, rail 1)'),
                                          dict(ADA_RUNTIME_EVIDENCE, observation='row 13 is absent from the runtime '
                                                                                 'policy list (mask 0x1c13f)')],
                      writable_status='unsupported', stored_units='mA', value_semantics='stored-policy-maximum',
                      policy_indices=[item['vbios_row_index']],
                      raw_bounds={'minimum': item['minimum_raw'], 'rated': item['default_raw'],
                                  'maximum': item['maximum_raw'], 'units': 'mA'},
                      reason='read-only: class-0 NVVDD output-current policy; whether the firmware enforces it is '
                             'unproven (absent from the runtime policy list of the RTX 2000 Ada)')]
    if not isinstance(parser, BlackwellRom):
        return []
    result = []
    # Rated values are enforced from boot only if no undecoded profile overrides them.
    rated_editable = profiles_decoded(parser)
    for item in parser.output_ocp_policies():
        known = item['association_recognized']
        editable = known and can_edit(image, parser)
        evidence = [dict(OCP_EVIDENCE, immutable_row_sha256=item['immutable_row_sha256'])]
        if item.get('association_basis') == 'structural-channel':
            evidence = [dict(SINGLE_RAIL_OCP_EVIDENCE, immutable_row_sha256=item['immutable_row_sha256'])]
        elif item.get('association_basis') == 'structural-notebook':
            evidence = [dict(NOTEBOOK_OCP_EVIDENCE, immutable_row_sha256=item['immutable_row_sha256'])]
        identity = rail_identity(parser, item, ocp=True)
        # Policy row and voltage rail row are different namespaces.
        identity['vbios_policy_index'] = item['vbios_row_index']
        result.append(field(item['logical_rail_id'].lower() + '_output_ocp_max_ma',
                            item['logical_rail_id'] + ' output OCP policy ceiling', 'mA',
                            item['maximum_raw'] if known else None,
                            item['default_raw'] if known else None, 0x7FFFFFFF if known else None,
                            editable, evidence, offsets=[item['maximum_offset']] if editable else (),
                            encoding='<I' if known else '', scale=1, stored_units='mA' if known else None,
                            writable_status='verified' if editable else 'unsupported' if known else 'unknown',
                            value_semantics='stored-policy-maximum', rail_identity=identity,
                            factory_rated_ma=item['default_raw'] if known else None,
                            raw_bounds={'minimum': item['minimum_raw'], 'rated': item['default_raw'],
                                        'maximum': item['maximum_raw'], 'units': item['units']},
                            policy_types={'vbios': item['type'], 'rm': item['rm_policy_type'], 'api': item['api_policy_type']},
                            monitor={'index': item['monitor_index'], 'class': item['monitor_class'],
                                     'rail_id': item['power_monitor_rail_id']},
                            **(dict(ordering_group=item['logical_rail_id'].lower() + '-output-ocp',
                                    encoding_bounds=(0, 0x7FFFFFFF)) if known else {}),
                            reason='static maximum: widens what a runtime client may request; the boot OCP is the rated '
                                   'value; runtime SET and enforcement untested' if known else
                                   'this recognized single-rail layout exposes only logic/NVVDD' if item.get('rail_absent') else
                                   'row shape/device/monitor association is outside reviewed evidence'))
        if known:
            # Saved GET shows CONTROL current = rated on rows13/14 of all seven
            # sources, so the rated value is the OCP enforced from boot.
            result.append(field(item['logical_rail_id'].lower() + '_output_ocp_rated_ma',
                                item['logical_rail_id'] + ' output OCP rated limit', 'mA', item['default_raw'],
                                item['minimum_raw'], item['maximum_raw'], editable and rated_editable,
                                evidence + [dict(THIRD_PARTY_EVIDENCE, observation=(
                                    'rows13/14 rated values are the enforced OCP: lowering them to 100 A clamped '
                                    'GPC/XBAR under load; XOC images raise them to 2000/1000 A'))],
                                offsets=[item['offset'] + 17], encoding='<I', scale=1, stored_units='mA',
                                value_semantics='stored-policy-rated-default',
                                rail_identity=dict(identity), policy_indices=[item['vbios_row_index']],
                                experimental=True, ordering_group=item['logical_rail_id'].lower() + '-output-ocp',
                                encoding_bounds=(0, 0x7FFFFFFF),
                                policy_types={'vbios': item['type'], 'rm': item['rm_policy_type'],
                                              'api': item['api_policy_type']},
                                reason='experimental: rated output OCP enforced from boot (saved GET current = rated); '
                                       'not hardware-tested; stored value, not a hardware-safe current rating'
                                       if item.get('association_basis') == 'saved-get' else
                                       'experimental: rated output OCP; on the GET-reviewed sources it is enforced from '
                                       'boot (current = rated); this notebook image has the Max-Q rows and channel chains '
                                       'but no saved GET; not hardware-tested; stored value, not a hardware-safe current rating'
                                       if item.get('association_basis') == 'structural-notebook' else
                                       'experimental: rated output OCP; on the GET-reviewed sources it is enforced from '
                                       'boot (current = rated); this image matches their NVVDD channel chain but has no '
                                       'saved GET; not hardware-tested; stored value, not a hardware-safe current rating'))
    return result


SLOT_POWER_EVIDENCE = {
    'kind': 'saved-get-policy-correlation', 'source': 'saved runtime GET capture',
    'format': 'GB20x power40/3d/66/14 row19 type2; byte1 0; monitor index 1; class8 monitor',
    'observed': 'policy19 only on the SFF: INFO+8 0 (mW), monitor 1, 1/66000/66000, CONTROL current 66000',
    'set_tested': False}


@registry.register
def slot_power(image, parser):
    """PCIe-slot power policy of the reviewed SFF (row 19), the 5060 Ti (row 18), Ada/Ampere row 5 and Turing row 3."""
    if isinstance(parser, TableRom):
        item = parser.ada_policy('slot_power') if ada(parser) else ampere_policy(parser, 'slot_power')
        if item is None:
            return []
        if turing(parser) and item['type'] == 1:
            reasons = ('experimental: ceiling of the PCIe slot power policy, a class-1 policy like the TGP; SET and '
                       'enforcement untested; ' + TURING_UNTESTED + '; stored value, not a hardware-safe slot rating',
                       'experimental: rated slot power limit, a class-1 policy like the TGP on the slot 12 V channel; '
                       'at stock it held the slot input of one slot-powered GTX 1650 at 62.5 W (63 W rated) and the '
                       'board near 66 W under a raised TGP; an edit of it is ' + TURING_UNTESTED + '; the PCIe CEM rates '
                       'the slot at 66 W (12 V) and 75 W in all; stored value, not a hardware-safe slot rating')
        elif turing(parser):
            reasons = ('experimental: ceiling of the PCIe slot power policy; SET and enforcement untested; '
                       + TURING_UNTESTED + '; stored value, not a hardware-safe slot rating',
                       'experimental: rated slot power limit; on the RTX 2000 Ada the same row is enforced from boot '
                       '(saved GET current = rated); with the connector limits it may cap the board power below a '
                       'raised TGP; ' + TURING_UNTESTED + '; the PCIe CEM rates the slot at 66 W (12 V) and 75 W in '
                       'all; stored value, not a hardware-safe slot rating')
        else:
            reasons = ('experimental: ceiling of the PCIe slot power policy; SET and enforcement untested; '
                       'stored value, not a hardware-safe slot rating',
                       'experimental: rated slot power limit; on the RTX 2000 Ada it is enforced from boot (saved GET '
                       'current = rated) and caps a slot-powered board; not hardware-tested; stored value, not a '
                       'hardware-safe slot rating')
        return ada_policy_fields(
            image, parser, [item], ('slot_power_max_w', 'slot_power_rated_w'),
            ('PCIe slot power ceiling', 'PCIe slot power limit (rated)'), group='slot-power',
            evidence=ADA_SLOT_EVIDENCE if ada(parser) else AMPERE_SLOT_EVIDENCE if not turing(parser) else
            TURING_SLOT_CLASS1_EVIDENCE if item['type'] == 1 else TURING_SLOT_EVIDENCE, reasons=reasons)
    item = parser.slot_power_policy()
    if not item['association_recognized']:
        return []
    editable = can_edit(image, parser) and profiles_decoded(parser)
    index = item['vbios_row_index']
    evidence = [dict(SLOT_POWER_EVIDENCE, immutable_row_sha256=item['immutable_row_sha256']),
                dict(THIRD_PARTY_EVIDENCE, observation=(
                    'power-monitor channel 1 is the PCIe slot input (about 6 W of 555 W on a connector-powered 5090)'))]
    reviewed = index == 19
    if not reviewed:
        # No saved GET for this device: the structural comparison leads.
        evidence.insert(0, dict(STRUCTURAL_ROW_EVIDENCE,
                                format=f'GB20x power40/38-or-3d/66/14 row{index} type2; byte1 0; monitor index 1',
                                observation='same immutable shape as the GET-reviewed SFF row19 slot policy'))
    common = dict(encoding='<I', scale=1000, stored_units='mW', policy_indices=[index], experimental=True,
                  ordering_group='slot-power', encoding_bounds=(0, 0x7FFFFFFF / 1000), vbios_policy_index=index,
                  monitor={'index': item['monitor_index'], 'class': 8},
                  raw_bounds={'minimum': item['minimum_raw'], 'rated': item['default_raw'],
                              'maximum': item['maximum_raw'], 'units': 'mW'})
    return [field('slot_power_max_w', 'PCIe slot power ceiling', 'W', item['maximum_raw'] / 1000,
                  item['default_raw'] / 1000, 0x7FFFFFFF / 1000, editable, evidence,
                  offsets=[item['maximum_offset']], value_semantics='stored-policy-maximum',
                  reason='experimental: ceiling of the PCIe slot power policy; SET and enforcement untested; '
                         'stored value, not a hardware-safe slot rating', **common),
            field('slot_power_rated_w', 'PCIe slot power limit (rated)', 'W', item['default_raw'] / 1000,
                  item['minimum_raw'] / 1000, item['maximum_raw'] / 1000, editable, evidence,
                  offsets=[item['default_offset']], value_semantics='stored-policy-rated-default',
                  reason='experimental: rated slot power limit enforced from boot (saved GET current = rated); '
                         'not hardware-tested; stored value, not a hardware-safe slot rating' if reviewed else
                         'experimental: rated slot power limit; on the GET-reviewed SFF it is enforced from boot '
                         '(current = rated); this image has no saved GET; not hardware-tested; stored value, not a '
                         'hardware-safe slot rating', **common)]


@registry.register
def connector_power(image, parser):
    """Ampere and Turing external 12 V connector-channel power policies (class 4 mW), numbered in power-row order.

    A channel is a sense channel, not a physical connector: one connector may span several.
    """
    if not (ampere(parser) or turing(parser)):
        return []
    tested = TURING_CONNECTOR_TESTED if turing(parser) else 'not hardware-tested'
    result = []
    for number, item in enumerate(parser.ampere_policies('connector_power'), 1):
        result += ada_policy_fields(
            image, parser, [item], (f'connector_{number}_power_max_w', f'connector_{number}_power_rated_w'),
            (f'Connector power channel {number} ceiling', f'Connector power channel {number} limit (rated)'),
            group=f'connector-{number}-power', connector=number, channel_rail=item['channel_rail'],
            evidence=TURING_CONNECTOR_EVIDENCE if turing(parser) else AMPERE_CONNECTOR_EVIDENCE,
            reasons=('experimental: ceiling of the power policy of one external 12 V connector channel (rail '
                     f"{item['channel_rail']:#04x}); " +
                     (TURING_CONNECTOR_TESTED if turing(parser) else 'SET and enforcement untested') +
                     '; stored value, not a hardware-safe connector rating',
                     'experimental: rated power limit of one external 12 V connector channel (rail '
                     f"{item['channel_rail']:#04x}); with the slot limit it may cap the board power below a raised TGP; "
                     f'{tested}; stored value, not a hardware-safe connector rating'))
    return result


@registry.register
def connector_sum_power(image, parser):
    """Ampere power policy on the sum of the external 12 V connector channels (class 4 mW), when one row has it."""
    if not ampere(parser):
        return []
    item = ampere_policy(parser, 'connector_sum')
    if item is None:
        return []
    channels = parser.summed_channels(item['channel_index'])
    names = ', '.join(map(str, channels))
    return ada_policy_fields(
        image, parser, [item], ('connector_sum_power_max_w', 'connector_sum_power_rated_w'),
        ('Connector power sum ceiling', 'Connector power sum limit (rated)'), group='connector-sum-power',
        evidence=AMPERE_CONNECTOR_SUM_EVIDENCE, summed_channels=channels, channel_rail=item['channel_rail'],
        reasons=('experimental: ceiling of the power policy on the sum of the external 12 V connector channels '
                 f'(power channels {names}); SET and enforcement untested; stored value, not a hardware-safe '
                 'connector rating',
                 'experimental: rated power limit of the sum of the external 12 V connector channels (power '
                 f'channels {names}); with the per-connector and slot limits it may cap the board power below a '
                 'raised TGP; not hardware-tested; stored value, not a hardware-safe connector rating'))


INPUT_CURRENT_EVIDENCE = {
    'kind': 'saved-get-policy-correlation', 'source': 'saved runtime GET capture',
    'format': 'GB20x power40/38-or-3d/66/14 row9 type11; unit discriminator1; class8 monitor',
    'indices_matched': 'row9 range/current equal on all seven reviewed sources', 'set_tested': False,
    'units_basis': 'row byte1 and GET INFO+8 are 1 on rows9-14 as on the mA output-OCP rows13/14; '
                   'GET INFO+8 is 0 on every mW row'}


@registry.register
def input_current(image, parser):
    """Row9 12 V board input-current policy (Ada: thresholds 0/1; Ampere: rail 0xe0 thresholds); kept apart from output OCP rows13/14."""
    if isinstance(parser, TableRom):
        items = ([parser.ada_policy('input_current_0'), parser.ada_policy('input_current_1')] if ada(parser) else
                 parser.ampere_policies('input_current') or [None])
        if None in items:
            return []
        return ada_policy_fields(
            image, parser, items, ('input_current_max_ma', 'input_current_rated_ma'),
            ('12 V input current threshold ceiling', '12 V input current threshold (rated)'),
            group='input-current-12v', evidence=ADA_INPUT_EVIDENCE if ada(parser) else AMPERE_INPUT_EVIDENCE,
            opt_in=True,
            reasons=('experimental, opt-in: client ceiling of both 12 V input-current hardware thresholds (written '
                     'together); SET and enforcement untested; stored value, not a hardware-safe current rating',
                     'experimental, opt-in: rated 12 V input-current hardware threshold, thresholds 0 and 1 written '
                     'together; identified by a channel byte-identical to the GB20x 12 V input channel; no Ada GET '
                     'of these rows; not hardware-tested; stored value, not a hardware-safe current rating'
                     if ada(parser) else
                     'experimental, opt-in: rated 12 V input-current hardware threshold (every row on the rail 0xe0 '
                     'channel written together); identified by its channel rail only; no Ampere reading; not '
                     'hardware-tested; stored value, not a hardware-safe current rating'))
    item = parser.input_current_policy()
    known = item['association_recognized']
    raw_bounds = {'minimum': item['minimum_raw'], 'rated': item['default_raw'],
                  'maximum': item['maximum_raw'], 'units': item['units']}
    if not known:
        mapped = item['type'] == 11 and parser.legacy['device'] in REVIEWED_GB20X_IDS
        return [field('input_policy_9_max_raw', 'Input-policy row9 maximum (units unknown)', 'unknown',
                      item['maximum_raw'], None, None, False, [dict(OCP_EVIDENCE)],
                      writable_status='unknown', value_semantics='unknown',
                      policy_types={'vbios': item['type'], 'rm': 30 if mapped else None,
                                    'api': 25 if mapped else None}, raw_bounds=raw_bounds,
                      reason='row9 is not output OCP; class8 union and units are unknown')]
    profiles, matching = parser.power_profiles(), parser.matching_power_profiles()
    top = parser.top_power_profile() if profiles and not matching else None
    if profiles and not matching and top is None:
        raise FormatError('no complete override profile matches the base policy')
    editable = can_edit(image, parser)
    maximum, rated, maximum_lower = item['maximum_raw'], item['default_raw'], item['default_raw']
    maximum_upper, rated_lower, extra, note = 0x7FFFFFFF, item['minimum_raw'], {}, ''
    rated_upper = maximum
    if top is not None:
        # Only the bound profile's row 9 entries are written; base row 9 caps them.
        maximum, rated = top['values'][(9, 'maximum')], top['values'][(9, 'default')]
        rated_upper = min(maximum, item['default_raw'])
        maximum_upper = item['maximum_raw']
        maximum_lower = max([rated] + top_profile_bounds(profiles, top, (9,), 'maximum'))
        rated_lower = max([rated_lower] + top_profile_bounds(profiles, top, (9,), 'default'))
        extra = dict(bound_profile=top['index'], base_values={'input_current_max_ma': item['maximum_raw'],
                                                              'input_current_rated_ma': item['default_raw']})
        note = top_profile_note(top, '%d mA' % item['maximum_raw'] if item['maximum_raw'] == item['default_raw'] else
                                '%d/%d mA (rated/maximum)' % (item['default_raw'], item['maximum_raw']))
    structural = [] if parser.legacy['device'] in REVIEWED_GB20X_IDS else [dict(
        STRUCTURAL_ROW_EVIDENCE, format='GB20x row9 type11' + (' and linked row7' if item['linked_limit_recognized'] else ''),
        observation='row 9 equals a GET-reviewed template (non-Max-Q, or Max-Q with monitor 2)' +
                    ('; row 7 equals the reviewed linked-limit shape' if item['linked_limit_recognized'] else ''))]
    evidence = structural + [dict(INPUT_CURRENT_EVIDENCE, immutable_row_sha256=item['immutable_row_sha256']),
                dict(THIRD_PARTY_EVIDENCE, observation=(
                    'RM PWR_POLICIES INFO entry 9: type 0x1e, channel 9, limitUnit 1 (mA), 1/80000/80000 '
                    'on a Matrix; STATUS channel 9 read 46008 mA at 555 W board power'))]
    common = dict(encoding='<I', scale=1, stored_units='mA', policy_indices=[9], experimental=True,
                  ordering_group='input-current-12v', encoding_bounds=(0, 0x7FFFFFFF),
                  policy_types={'vbios': item['type'], 'rm': item['rm_policy_type'], 'api': item['api_policy_type']},
                  monitor={'index': item['monitor_index'], 'class': item['monitor_class']}, raw_bounds=raw_bounds)

    def offsets(name, base):
        if top is not None:
            return top_profile_offsets(top, (9,), name)
        return [base] + [e['value_offset'] for p in matching for e in p['entries']
                         if e['policy'] == 9 and e['field'] == name]
    bound_evidence = [TOP_PROFILE_EVIDENCE] + evidence if top is not None else evidence
    result = [field('input_current_max_ma', '12 V input current ceiling', 'mA', maximum,
                    maximum_lower, maximum_upper, editable, bound_evidence,
                    offsets=offsets('maximum', item['maximum_offset']), value_semantics='stored-policy-maximum',
                    reason='experimental: ' + note + 'client ceiling of the 12 V input-current policy; SET and '
                           'enforcement untested; stored value, not a hardware-safe current rating',
                    **common, **extra),
              field('input_current_rated_ma', '12 V input current limit (rated)', 'mA', rated,
                    rated_lower, rated_upper, editable, bound_evidence,
                    offsets=offsets('default', item['default_offset']), value_semantics='stored-policy-rated-default',
                    reason='experimental: ' + note + 'rated limit applied without a client request; enforcement not '
                           'hardware-tested; stored value, not a hardware-safe current rating',
                    **common, **extra)]
    if item['linked_limit_recognized']:
        # Raising row9 alone may leave the effective 12 V limit at this value.
        # Kept as a separate field on purpose; which copy binds is still to
        # be measured on hardware.
        result.append(field('input_current_policy7_limit_ma', 'Policy 7 limit linked to the 12 V input policy',
                            'mA', item['linked_limit_raw'], 1, 0x7FFFFFFF, editable,
                            structural + [dict(INPUT_CURRENT_EVIDENCE, linked_row_sha256=item['linked_limit_row_sha256'],
                                  observation='row7 byte33 = 9; GET INFO7+364 = 9 and CONTROL7+1116 = policy9 '
                                              'current; equal to the row9 limit on all seven reviewed sources'),
                             dict(THIRD_PARTY_EVIDENCE, observation=(
                                 'an XOC image raised this value 80000 -> 160000 while setting row9 to 5001000'))],
                            offsets=[item['linked_limit_offset']], encoding='<I', scale=1, stored_units='mA',
                            experimental=True, policy_indices=[7], value_semantics='stored-linked-policy-limit',
                            references_policy=9, vbios_policy_index=7,
                            reason='experimental: policy7 limit linked to the 12 V input policy; it may cap the input '
                                   'current; not hardware-tested; stored value, not a hardware-safe current rating'))
    return result


@registry.register
def power_thresholds(image, parser):
    """Ada hardware-threshold policies with a runtime GET on the RTX 2000 Ada (advanced, opt-in).

    Slot current (row 8, class 5 mA on the slot channel) and NVVDD output power
    (row 16, class 5 mW on the NVVDD power sensor). Their rated value is the
    enforced threshold there (CONTROL current = rated). Ampere and Turing: the
    slot current row by channel (ampere_policies) and the connector current
    thresholds (connector_currents).
    """
    if ampere(parser) or turing(parser):
        slot = ampere_policy(parser, 'slot_current')
        if slot is None:
            return connector_currents(image, parser)
        return ada_policy_fields(
            image, parser, [slot], ('slot_current_threshold_max_ma', 'slot_current_threshold_rated_ma'),
            ('PCIe slot current threshold ceiling', 'PCIe slot current threshold (rated)'),
            group='slot-current', opt_in=True,
            evidence=TURING_SLOT_CURRENT_EVIDENCE if turing(parser) else AMPERE_SLOT_CURRENT_EVIDENCE,
            reasons=('experimental, opt-in: ceiling of the slot current hardware threshold; SET untested; ' +
                     (TURING_UNTESTED + '; ' if turing(parser) else '') + 'stored value, not a hardware-safe slot '
                     'rating',
                     'experimental, opt-in: slot 12 V current hardware threshold; enforced from boot on the RTX 2000 '
                     'Ada' + ('; ' + TURING_UNTESTED if turing(parser) else ', no Ampere reading; not hardware-tested') +
                     '; raising it exceeds the PCIe CEM slot rating on a slot-powered board')) + connector_currents(
            image, parser)
    if not ada(parser):
        return []
    result = []
    slot = parser.ada_policy('slot_current')
    if slot is not None:
        result += ada_policy_fields(
            image, parser, [slot], ('slot_current_threshold_max_ma', 'slot_current_threshold_rated_ma'),
            ('PCIe slot current threshold ceiling', 'PCIe slot current threshold (rated)'),
            group='slot-current', opt_in=True,
            evidence=[dict(ADA_RUNTIME_EVIDENCE, format='Ada power row class 5 (hardware threshold) mA on channel 4',
                           observation='policy 8: API type 4, limit unit 1 (mA), monitor 4 (class 8, rail 255), '
                                       '1000/8250/8250, CONTROL current 8250'),
                      dict(ADA_STRUCTURAL_EVIDENCE, format='Ada power row shape 85465d66 on the slot channel',
                           observation='8.25 A (about 99 W at 12 V) on the two images with this row')],
            reasons=('experimental, opt-in: ceiling of the slot current hardware threshold; SET untested; stored '
                     'value, not a hardware-safe slot rating',
                     'experimental, opt-in: slot 12 V current hardware threshold enforced from boot on the RTX 2000 '
                     'Ada (saved GET current = rated); not hardware-tested; raising it exceeds the PCIe CEM slot '
                     'rating on a slot-powered board'))
    nvvdd = parser.ada_policy('nvvdd_power')
    if nvvdd is not None:
        result += ada_policy_fields(
            image, parser, [nvvdd], ('nvvdd_power_threshold_max_w', 'nvvdd_power_threshold_rated_w'),
            ('NVVDD output power threshold ceiling', 'NVVDD output power threshold (rated)'),
            group='nvvdd-power-threshold', opt_in=True,
            evidence=[dict(ADA_RUNTIME_EVIDENCE, format='Ada power row class 5 (hardware threshold) mW on channel 18',
                           observation='policy 16: API type 4, limit unit 0 (mW), monitor 18 (class 6, rail 1), '
                                       '10000/125983/125983, CONTROL current 125983'),
                      dict(ADA_STRUCTURAL_EVIDENCE, format='Ada power row shapes 9d19198c/f9720229 on the NVVDD '
                                                           'output power channel 18 (rail 1)',
                           observation='rated value above the rated TGP on every Ada image (122-650 W rated; the RTX '
                                       '4050 Laptop GPU 122 W row is below its 140 W TGP ceiling); the RTX 4060 '
                                       'has a second class-5 mW row on channel 18 (parameter byte 0 = 4, 100 W) '
                                       'and keeps both values read-only')],
            reasons=('experimental, opt-in: ceiling of the NVVDD output power hardware threshold; SET untested; '
                     'stored value, not a hardware-safe rating',
                     'experimental, opt-in: NVVDD output power hardware threshold enforced from boot on the RTX 2000 '
                     'Ada (saved GET current = rated); not hardware-tested; stored value, not a hardware-safe rating'))
    return result


def connector_currents(image, parser):
    """Opt-in current threshold of each Ampere/Turing connector power channel (class 5 mA, see ampere_policies).

    Connector n is numbered as in connector_power; it has a field only when its
    channel carries one connector power row and exactly one such threshold row,
    with threshold index 1 or 2 (parameter byte 0; 0 is the slot threshold).
    """
    power, current = parser.ampere_policies('connector_power'), parser.ampere_policies('connector_current')
    result = []
    for number, item in enumerate(power, 1):
        index = item['channel_index']
        rows = [c for c in current if c['channel_index'] == index]
        threshold = parser.blob[rows[0]['offset'] + 14] if len(rows) == 1 else None
        if threshold not in (1, 2) or [p['channel_index'] for p in power].count(index) != 1:
            continue
        untested = TURING_UNTESTED if turing(parser) else 'no Ampere reading; not hardware-tested'
        result += ada_policy_fields(
            image, parser, rows, (f'connector_{number}_current_threshold_max_ma',
                                  f'connector_{number}_current_threshold_rated_ma'),
            (f'Connector channel {number} current threshold ceiling', f'Connector channel {number} current threshold '
                                                                      '(rated)'),
            group=f'connector-{number}-current', opt_in=True, connector=number, channel_rail=item['channel_rail'],
            threshold_index=threshold,
            evidence=TURING_CONNECTOR_CURRENT_EVIDENCE if turing(parser) else AMPERE_CONNECTOR_CURRENT_EVIDENCE,
            reasons=('experimental, opt-in: ceiling of the current hardware threshold of external 12 V connector '
                     f"channel {number} (rail {item['channel_rail']:#04x}); SET untested; {untested}; stored value, "
                     'not a hardware-safe connector rating',
                     'experimental, opt-in: current hardware threshold (index '
                     f"{threshold}) of external 12 V connector channel {number} (rail {item['channel_rail']:#04x}), "
                     'identified by its channel and threshold index; raising it removes connector overcurrent '
                     f'protection; {untested}; stored value, not a hardware-safe connector rating'))
    return result


FAN_EVIDENCE = [
    {'kind': 'structural-table',
     'format': 'GB20x fan cooler table v0x10 at P+0x58 (object 0x1d); 9-byte header, four 26-byte rows',
     'observation': 'header bytes 4..7 list exactly the rows with a nonzero byte 0 on all fourteen Blackwell '
                    'sources; row bytes 11..13 hold 25000 or 27000, equal on the active rows; byte 13 is 0'},
    {'kind': 'read-only-nvml-correlation', 'source': 'read-only NVML capture', 'set_tested': False,
     'api': 'nvmlDeviceGetNumFans', 'relation': 'fan count = listed channels',
     'observed': 'Max-Q 1, 5090 Matrix 3, 5080 2, 5070 Ti 2, SFF 1'},
    {'kind': 'third-party-tool-reading',
     'source': 'mVolt BIOS override view', 'use': 'cross-check only',
     'observation': 'mVolt shows fan layout 3 channels and PWM frequency 25 kHz on the 5090 Matrix, '
                    'whose active rows hold 25000 at bytes 11..13'}]
# 4-wire PWM fan specification band; outside it fans may not regulate.
FAN_PWM_BAND_HZ = (21000, 28000)


def fan_layouts(parser, table):
    """Channel counts this image can hold and restore, with the bytes each writes.

    A count sets the cooler list (header bytes 4..7) and byte 0 of entries
    0..3 in the cooler, policy, mapping, control and speed tables. Every
    offered count can be reached and undone byte for byte:
    - Raising enables the next stored channels only: stored in every table
      (see BlackwellRom.fan_coolers), with their own cooler configuration
      (row bytes 4..5 and 10 unlike every earlier row), the shared PWM
      frequency, byte 13 = 0 and speed and level limits that hold every
      enabled extra curve (those curves serve every active channel, so an
      edited extra curve cannot end up outside a channel enabled later). They
      take channel 0's enable byte in each table.
    - Lowering clears the last channels in all five tables, as the two-channel
      ASUS XOC image does for the Matrix's third channel. It is offered only down
      to the lowest channel above which every active channel has its own
      cooler configuration, channel 0's enable byte in every table and limits
      that hold the extra curves, so raising again restores it.
    """
    b, rows = parser.blob, table['rows']
    active = [r for r in rows if r['active']]
    frequency = active[0]['pwm_frequency_hz']
    identity = lambda r: (b[r['offset'] + 4:r['offset'] + 6], b[r['offset'] + 10])
    first = rows[0]
    holds = lambda r: all(r[low] <= fan_points(c, unit)[0] and fan_points(c, unit)[-1] <= r[high]
                          for c in table['extra_curves']
                          for unit, low, high in (('rpm', 'rpm_minimum', 'rpm_maximum'),
                                                  ('pct', 'level_minimum', 'level_maximum')))
    enables = (('offset', 'enable'), ('policy_offset', 'policy_enable'), ('mapping_offset', 'mapping_enable'),
               ('control_offset', 'control_enable'), ('speed_offset', 'speed_enable'))
    most = len(active)
    for row in rows[most:]:
        if (identity(row) in {identity(r) for r in rows[:row['index']]} or
                row['pwm_frequency_hz'] != frequency or b[row['offset'] + 13] or not row['stored'] or not holds(row)):
            break
        most += 1
    least = len(active)
    for row in reversed(active[1:]):
        if (identity(row) in {identity(r) for r in rows[:row['index']]} or
                any(row[name] != first[name] for _, name in enables) or not holds(row)):
            break
        least -= 1
    n = len(rows)  # list bytes and entries per table: 4 on GB20x, 2 on Ada
    offsets = [table['offset'] + 4 + i for i in range(n)] + [r[at] for at, _ in enables for r in rows]
    layout = []
    for count in range(least, most + 1):
        listed = [i if i < count else 0xFF for i in range(n)]
        on = lambda r, name: (r[name] if r['active'] else first[name]) if r['index'] < count else 0
        values = listed + [on(r, name) for _, name in enables for r in rows]
        layout.append((count, tuple(bytes((v,)) for v in values)))
    return least, most, offsets, tuple(layout)


ADA_FAN_EVIDENCE = [
    {'kind': 'structural-table',
     'format': 'Ada fan cooler table v0x10 at P+0x58; 6-byte header, two 26-byte rows; per-channel policy, mapping, '
               'control and speed tables at P+0x5c/0x64/0xdc/0xe0',
     'observation': 'header bytes 4..5 list exactly the rows with a nonzero byte 0 on the 15 GPU-driven Ada images; '
                    'active rows hold 25000 or 27000 at bytes 11..13 and byte 13 is 0; row configuration bytes equal '
                    'the GB20x rows 0/1; laptop images list no channel and enable none'},
    {'kind': 'public-driver-source', 'source': 'Linux nouveau nvkm/subdev/bios/fan.c (MIT)',
     'observation': 'reads the P+0x58 v0x10 cooler table; PWM frequency = 24-bit value at entry byte 0x0b'},
    {'kind': 'read-only-nvml-correlation', 'source': 'read-only NVML capture', 'set_tested': False,
     'api': 'nvmlDeviceGetNumFans', 'relation': 'fan count = listed channels', 'observed': 'RTX 2000 Ada 1'}]


AMPERE_FAN_EVIDENCE = [
    dict(AMPERE_STRUCTURAL_EVIDENCE, kind='structural-table',
         format='Ampere fan tables: the Ada cooler, policy, mapping, control and speed tables at P+0x58/0x5c/0x64/'
                '0xdc/0xe0 with the same headers and entry sizes',
         observation='header bytes 4..5 list exactly the rows with a nonzero byte 0 on the GPU-driven images; active '
                     'rows hold 25000 or 27000 at bytes 11..13 and byte 13 is 0; the RTX 3080/3090 boards (not the '
                     'RTX 3080 Ti with two connector channels) and the RTX 3060 8GB leave the speed table disabled on '
                     'every channel; laptops list no channel and enable none; the passive A40 and the RTX 3050 '
                     '6GB/8GB tables disagree and keep no fan field'),
    ADA_FAN_EVIDENCE[1]]


TURING_FAN_EVIDENCE = [
    dict(TURING_STRUCTURAL_EVIDENCE, kind='structural-table',
         format='Turing fan tables: the Ada cooler (P+0x58, 10 06 1a 02) and mapping (P+0x64, 10 04 05 02) tables '
                'and a v0x10 policy table (P+0x5c, 10 06 36 02) with its own channel list (header bytes 4..5) and two '
                '54-byte entries that keep the Ada and Ampere entry layout three bytes later (entry bytes 9..16 = 23 '
                '2b 0a 01 00 02 80 00, Ada bytes 6..13): levels at entry bytes 17..19 and three (1/32 C, RPM) curve '
                'points from byte 21; no control or speed table (the P token ends before their pointers)',
         observation='the cooler and policy lists agree and name exactly the enabled entries, with policy byte 2 and '
                     'mapping byte 1 = channel, on the 18 GPU-driven images; active rows hold 25000 or 27000 at bytes '
                     '11..13 and byte 13 is 0, except on the MSI GTX 1650 (135000, RPM limits 0), whose PWM '
                     'frequency, RPM limits and curve points stay read-only; Max-Q and laptop images list no channel '
                     'and enable none; the GTX 1650 '
                     'SUPER disables its fan 0 mapping entry while the other tables list it and keeps no fan field; '
                     'the disabled entries hold bytes unlike the active ones, so the channel count stays read-only'),
    ADA_FAN_EVIDENCE[1],
    dict(TURING_XOC_EVIDENCE, observation='the XOC image changes the PWM frequency 27 -> 25 kHz, the limits 0-100 % / '
                                          '0-3000 RPM -> 30-100 % / 800-3600 RPM and the curve')]
TURING_FAN_CHANNELS_REASON = ('read-only: the Turing fan policy and mapping entries of a disabled channel hold bytes '
                              'unlike the active ones and there is no control or speed table, so no other channel '
                              'count is offered')


def chain_copies(parser, offsets, size, layout=()):
    """Each offset in every duplicate Ada chain (layout bytes repeat per copy); GB20x unchanged."""
    if isinstance(parser, BlackwellRom):
        return list(offsets), layout
    groups = [parser.copy_offsets(at, size) for at in offsets]
    layout = tuple((value, tuple(chunk for chunk, group in zip(chunks, groups) for _ in group))
                   for value, chunks in layout)
    return [at for group in groups for at in group], layout


FAN_LIMIT_EVIDENCE = {
    'kind': 'structural-table',
    'format': 'fan cooler row bytes 2/3 (u8 %) and 14..15/16..17 (u16 RPM); policy entry bytes 14..16 (%) and '
              'three (1/32 C, RPM) curve points from byte 18; speed entry bytes 2..3 (u16 RPM)',
    'observation': 'on every active row of the GB20x, Ada and Ampere corpus the row limits hold the channel\'s own '
                   'policy curve (row minimum <= lowest curve point, highest curve point <= row maximum); the '
                   'enabled policy curves past the cooler rows fit too, except on one Ada board whose second '
                   'channel tops out below them; every curve rises strictly in temperature, RPM and level '
                   '(channel curves 43-97 C, the other curves 92-108 C, three Ampere boards with a point off a '
                   'whole degree); every enabled speed entry holds 0.51-0.79 of its row maximum RPM; byte 3 is '
                   '100; duplicate chains hold the same bytes; Ampere boards that stop the fan store 0 % and 0 RPM'}
FAN_LIMIT_NVML = dict(NVML_CAPTURE, relation='the driver fan percent maps linearly from 30 % = row minimum RPM to '
                                               '100 % = row maximum RPM',
                      observed='RTX 5080 (1050-3500 RPM): 73 % -> 2556 RPM, 79 % -> 2761-2774 (2555 and 2765 '
                               'expected); RTX PRO 4000 SFF (3600-7300): 92 % -> 6887, 84 % -> 6438 (6877, 6454); '
                               'RTX 5070 Ti (1050-3200): 68 % -> 2206-2213 (2217); RTX PRO 6000 Max-Q (1000-3350): '
                               '96 % -> 3213, 90 % -> 3010 (3216, 3014); the driver fan-speed range stays 30-100 % '
                               'while row byte 2 is 10-22')
FAN_LIMIT_HARDWARE = {'kind': 'hardware-test', 'source': 'edited image loaded as an override; read-only NVML',
                      'set_tested': True, 'scope': 'RTX 5080, both fan channels, fans under manual control',
                      'observed': 'speed maximum 3500 -> 4000 RPM: 72 % -> 2820 RPM and 30 % -> 1050 RPM, as the '
                                  'linear 30 % = minimum, 100 % = maximum map gives; level minimum 20 -> 10 %: the '
                                  'driver fan-speed range stays 30-100 %'}
# Reason endings of the limits the hardware test changed; the other limits are untested.
FAN_LIMIT_TESTED = {('max', 'rpm'): 'hardware-tested on an RTX 5080: the driver runs 100 % at this speed and maps '
                                    'the percent linearly down to 30 % at the minimum; other boards not '
                                    'hardware-tested',
                    ('min', 'rpm'): "in the earlier RTX 5080 test, the driver's 30 % setting matched the unchanged "
                                    '1050 RPM minimum; on another RTX 5080 a minimum lowered from 1050 to 900 RPM '
                                    'loaded, but 30 % still ran at about 1050-1110 RPM; what held that floor is '
                                    'unknown; other boards not hardware-tested',
                    ('min', 'pct'): 'on an RTX 5080 a lower value left the driver fan-speed range at 30-100 %; '
                                    'other boards not hardware-tested'}
FAN_SHAPE_REASON = 'fan row or policy curves hold values outside the reviewed shape'
# (key unit, label noun, units, row byte of the minimum, of the maximum, encoding, ceiling). The RPM
# ceiling is the signed 16-bit range of the driver's fan-curve RPM values, not the '<H' encoding.
FAN_LIMITS = (('rpm', 'speed', 'RPM', 14, 16, '<H', 32767), ('pct', 'level', '%', 2, 3, '<B', 100))
# Curve points of a policy entry: (key unit, label noun, units, stored units, entry byte of point 1,
# byte step per point, encoding, scale, ceiling in stored units). Temperatures are stored in 1/32 C.
FAN_CURVE = (('temp_c', 'temperature', 'C', '1/32 C', 18, 4, '<H', 32, 110 * 32),
             ('rpm', 'speed', 'RPM', 'RPM', 20, 4, '<H', 1, 32767), ('pct', 'level', '%', '%', 14, 1, '<B', 1, 100))


def fan_points(curve, unit):
    """Stored values of the three curve points: 1/32 C ('temp_c'), RPM or %."""
    return ([t for t, _ in curve['curve_points']] if unit == 'temp_c' else
            [rpm for _, rpm in curve['curve_points']] if unit == 'rpm' else list(curve['curve_levels']))


def fan_shaped(curve):
    """Reviewed curve shape: temperatures rise strictly (the curve sets a speed per temperature, so two
    points may not share one), RPM and levels never fall, and every value is within its ceiling."""
    temps, rpm, levels = (fan_points(curve, unit) for unit in ('temp_c', 'rpm', 'pct'))
    return (all(a < b for a, b in zip(temps, temps[1:])) and rpm == sorted(rpm) and levels == sorted(levels) and
            all(fan_points(curve, unit)[-1] <= ceiling for unit, *_, ceiling in FAN_CURVE))


def fan_field(writable, parser, key, label, units, current, lo, hi, shaped, at, encoding, scale, ceiling, noun,
              evidence, reason, **extra):
    """One fan limit or curve point, in stored units. It is editable when the image is (writable), its
    row and curves hold the reviewed shape and it sits inside lo..hi. With lo == hi (a curve point flush
    with its limit, a level maximum of 100 under a curve that reaches 100 %) a request for it alone
    keeps its value, but it can move with its partners in a joint edit. Bounds stay numeric, so the
    joint recheck refuses a request that breaks the order on the edited result."""
    inside = shaped and lo <= current <= hi
    editable = inside and writable
    show = (lambda v: v / scale) if scale != 1 else (lambda v: v)
    offsets, _ = chain_copies(parser, [at], struct.calcsize(encoding))
    return field(key, label, units, show(current), show(lo), show(hi), editable, evidence,
                 offsets=offsets if editable else (), encoding=encoding if editable else '', scale=scale,
                 experimental=True, ordering_group=f'fan-{noun}' if editable else None,
                 encoding_bounds=(0, show(ceiling)) if editable else None,
                 writable_status=None if editable else 'unsupported',
                 reason=reason if inside else FAN_SHAPE_REASON, **extra)


def fan_untested(parser, note='not hardware-tested'):
    """Test note ending a fan reason; on Turing the Turing note replaces a bare 'not hardware-tested'."""
    if not turing(parser):
        return note
    return TURING_UNTESTED if note == 'not hardware-tested' else note + '; ' + TURING_UNTESTED


def fan_limits(writable, parser, table, evidence):
    """Speed (RPM) and level (%) limits of each active fan channel, numbered from 1.

    The limits keep containing the stored curves: the channel's own policy curve and
    every enabled policy curve past the cooler rows, and the speed limits also the
    channel's enabled speed-table value. A minimum moves from 0 up to the lowest of
    them and below the maximum; a maximum from the highest of them and above the
    minimum up to the ceiling. A limit moves past a curve only together with the
    curve points (fan_curves), in one joint edit. Each side is read-only when its
    row and curves hold another shape (fan_shaped).
    """
    result = []
    for r in table['rows']:
        if not r['active']:
            continue
        n = r['index'] + 1
        curves = [r] + table['extra_curves']
        shaped = all(fan_shaped(c) for c in curves)
        for unit, noun, units, low_at, high_at, encoding, ceiling in FAN_LIMITS:
            low, high = ((r['rpm_minimum'], r['rpm_maximum']) if unit == 'rpm' else
                         (r['level_minimum'], r['level_maximum']))
            points = [fan_points(c, unit) for c in curves]
            held = [r['speed_rpm']] if unit == 'rpm' and r['speed_enable'] else []
            floor, top = min([p[0] for p in points] + held), max([p[-1] for p in points] + held)
            for side, current, at, lo, hi in (('min', low, low_at, 0, min(floor, high - 1)),
                                              ('max', high, high_at, max(top, low + 1), ceiling)):
                word = 'minimum' if side == 'min' else 'maximum'
                result.append(fan_field(
                    writable, parser, f'fan_{n}_{side}_{unit}', f'Fan {n} {word} {noun}', units, current, lo, hi,
                    shaped, r['offset'] + at, encoding, 1, ceiling, noun,
                    [dict(FAN_LIMIT_EVIDENCE), dict(FAN_LIMIT_NVML), dict(FAN_LIMIT_HARDWARE)] +
                    [dict(e) for e in evidence],
                    f'experimental: {word} fan {noun} of channel {n}; the stored fan curves' +
                    (' and the speed-table value' if unit == 'rpm' and not turing(parser) else '') +
                    ' stay inside the limits, so a '
                    'limit moves past a curve only with its points in one edit; ' +
                    fan_untested(parser, FAN_LIMIT_TESTED.get((side, unit), 'not hardware-tested')),
                    stored_units=units, value_semantics=f'stored-fan-{word}-{noun}', fan_rows=[r['index']],
                    fan_channel=r['index'], **({'opt_in': True} if unit == 'pct' else {})))
    return result


def fan_curves(writable, parser, table, evidence):
    """Points 1..3 of the stored fan curves: temperature (1/32 C), speed (RPM) and level (%).

    The curves are each active channel's own policy entry and the enabled entries past
    the cooler rows, numbered from 1 in entry order (extra curves). Temperatures rise
    strictly from 0 to 110 C; speeds and levels never fall and stay inside the limits:
    the channel's own row limits, or for an extra curve, which serves every active
    channel, the highest minimum and lowest maximum of the active rows. The row limits
    hold the curves the same way (fan_limits), so lowering a maximum below a curve
    takes the limit and the points above it in one joint edit. Every point stays inside
    the containment, so a stored point above it does not widen its neighbor's range.
    """
    active = [r for r in table['rows'] if r['active']]
    if not active:
        return []
    shared = {'rpm': (max(r['rpm_minimum'] for r in active), min(r['rpm_maximum'] for r in active)),
              'pct': (max(r['level_minimum'] for r in active), min(r['level_maximum'] for r in active))}
    curves = [(f'fan_{r["index"] + 1}', f'Fan {r["index"] + 1} curve', f'channel {r["index"] + 1}', r,
               {'rpm': (r['rpm_minimum'], r['rpm_maximum']), 'pct': (r['level_minimum'], r['level_maximum'])},
               dict(fan_channel=r['index'], fan_rows=[r['index']])) for r in active]
    curves += [(f'fan_extra_{m}', f'Extra fan curve {m}', f'extra {m}', c, shared,
                dict(fan_rows=[r['index'] for r in active])) for m, c in enumerate(table['extra_curves'], 1)]
    result = []
    for prefix, name, owner, curve, limits, extra in curves:
        shaped = fan_shaped(curve) and all(low < high for low, high in limits.values())
        for k in range(3):
            for unit, noun, units, stored_units, first, step, encoding, scale, ceiling in FAN_CURVE:
                values = fan_points(curve, unit)
                floor, top = (0, ceiling) if unit == 'temp_c' else (limits[unit][0], min(limits[unit][1], ceiling))
                gap = 1 if unit == 'temp_c' else 0  # temperatures rise by at least 1/32 C
                lo = max(values[k - 1] + gap, floor) if k else floor
                hi = min(values[k + 1] - gap, top) if k < 2 else top
                result.append(fan_field(
                    writable, parser, f'{prefix}_curve_{k + 1}_{unit}', f'{name} point {k + 1} {noun}', units, values[k],
                    lo, hi, shaped, curve['policy_offset'] + first + step * k, encoding, scale, ceiling, noun,
                    [dict(FAN_LIMIT_EVIDENCE)] + [dict(e) for e in evidence],
                    f'experimental: {noun} of point {k + 1} of the stored {owner} fan curve; the points stay in '
                    'order and inside the fan limits' + (' of every active channel' if 'fan_channel' not in extra
                                                         else '') + '; ' + fan_untested(parser),
                    stored_units=stored_units, value_semantics=f'stored-fan-curve-{noun}', fan_policy=curve['index'],
                    **extra, **({'opt_in': True} if unit == 'pct' else {})))
    return result


@registry.register
def fans(image, parser):
    """Fan channel count, the shared PWM frequency of the fan rows, channel limits and curves."""
    if not isinstance(parser, (BlackwellRom, TableRom)):
        return []
    table = parser.fan_coolers()
    if table is None:
        return []
    active = [r for r in table['rows'] if r['active']]
    frequencies = {r['pwm_frequency_hz'] for r in active}
    shared = len(frequencies) == 1 and all(parser.blob[r['offset'] + 13] == 0 for r in active)
    current = active[0]['pwm_frequency_hz'] if shared else None
    in_band = shared and FAN_PWM_BAND_HZ[0] <= current <= FAN_PWM_BAND_HZ[1]
    # Turing has no control or speed table and no reviewed disabled-channel layout: no channel count.
    least, most, layout_offsets, layout = (fan_layouts(parser, table) if shared and not turing(parser) else
                                           (len(active), len(active), [], ()))
    layout_offsets, layout = chain_copies(parser, layout_offsets, 1, layout)
    # The PWM frequency is also kept on rows a larger channel count may enable.
    pwm_rows = table['rows'][:most]
    pwm_offsets, _ = chain_copies(parser, [r['pwm_frequency_offset'] for r in pwm_rows], 2)
    evidence = (FAN_EVIDENCE if isinstance(parser, BlackwellRom) else ADA_FAN_EVIDENCE if ada(parser) else
                TURING_FAN_EVIDENCE if turing(parser) else AMPERE_FAN_EVIDENCE)
    writable = can_edit(image, parser)
    channels_editable = shared and most > least and writable
    editable = in_band and writable
    return [field('fan_channels', 'Fan channels', 'channels', len(table['channels']),
                  least if channels_editable else None, most if channels_editable else None, channels_editable,
                  [dict(e) for e in evidence], offsets=layout_offsets if channels_editable else (),
                  encoding='<B' if channels_editable else '', scale=1, layout=layout if channels_editable else (),
                  writable_status=None if channels_editable else 'unsupported', experimental=True,
                  value_semantics='stored-fan-layout', fan_rows=[r['index'] for r in table['rows'][:most]],
                  reason='experimental: number of active fan channels, for using the image on a board with a '
                         'different fan count; lowering clears the last channels, raising enables stored channels; '
                         'every offered count can be undone byte for byte; not hardware-tested' if shared and most > least else
                         'active fan rows disagree or hold a value outside the reviewed shape' if not shared else
                         TURING_FAN_CHANNELS_REASON if turing(parser) else
                         'no other fan channel layout is stored in this table, or a stored channel\'s limits do not '
                         'hold the extra fan curves'),
            field('fan_pwm_frequency_hz', 'Fan PWM frequency', 'Hz', current,
                  FAN_PWM_BAND_HZ[0] if in_band else None, FAN_PWM_BAND_HZ[1] if in_band else None, editable,
                  [dict(e) for e in evidence], offsets=pwm_offsets if editable else (),
                  encoding='<H' if editable else '', scale=1, stored_units='Hz', experimental=True,
                  value_semantics='stored-fan-pwm-frequency', fan_rows=[r['index'] for r in pwm_rows],
                  reason='experimental: PWM frequency of the fan channels; accepted range is the 4-wire PWM fan '
                         'band (21-28 kHz); ' + fan_untested(parser) if in_band else
                         'active fan rows disagree or hold a value outside the reviewed shape')] + fan_limits(
        writable, parser, table, evidence) + fan_curves(writable, parser, table, evidence)


# Bits 1|2 of the fan policy entry flag byte (0x32): both set (1) or both clear (0).
FAN_ZERO_RPM_BITS = 0x06
FAN_ZERO_RPM_FIRMWARE_EVIDENCE = {
    'kind': 'static-firmware-analysis',
    'source': 'GSP-RM firmware 615.78.08 (gsp_ga10x.bin), fan policy entry parser',
    'observation': 'GSP-RM carries its own parser for this entry: it unpacks every 51-byte policy entry with schema '
                   '2b12d1b (2 bytes, 12 dwords, 1 byte), decodes only entries whose byte 0 is 1 and reads the last '
                   'byte (+0x32) bit by bit; bits 1 and 2 become two separate booleans, kept with the temperature '
                   'pair of bytes 30..33 and byte 46 of the same entry', 'set_tested': False}
FAN_ZERO_RPM_DRIVER_EVIDENCE = {
    'kind': 'static-driver-analysis',
    'source': 'Windows driver nvlddmkm.sys 617.42, GB20x fan policy entry parser (contributed with the field)',
    'observation': 'every 51-byte fan policy entry is read with schema 2b12d1b; the last byte (+0x32) is decoded bit '
                   'by bit and bits 1 and 2 become two separate booleans at driver structure offsets +0x80 and +0x81, '
                   'not an enum value'}
FAN_ZERO_RPM_CORPUS_EVIDENCE = {
    'kind': 'structural-table', 'source': 'GB20x VBIOS corpus',
    'observation': 'every GeForce GB20x image of the corpus sets both bits on every enabled policy entry (0x17 on '
                   'the channel entries and 0x07 on the extra curves; 0x16/0x06 on the ASUS XOC and MSI Lightning '
                   'images) and every RTX PRO image clears both (0x11/0x01 or 0x01); no image sets one alone; the '
                   'HP Omen RTX 5090 image (outside the corpus) clears both; bytes 30..33 hold '
                   'two rising temperatures (43/50, 50/55 or 50/60 C on the channel entries) and byte 46 holds 0, '
                   'except on the RTX PRO 6000 Max-Q: zeros and 0xff'}
FAN_ZERO_RPM_OWNER_EVIDENCE = {
    'kind': 'idle-fan-behavior-correlation',
    'source': 'owner reports contributed with the field; these images are not in the reviewed corpus',
    'observation': 'the fans stand still at idle on the Palit GameRock RTX 5090, the ASUS TUF RTX 5090 and the ASUS '
                   'TUF RTX 5070 Ti, whose images store 0x17/0x07, and keep turning at about 1100 RPM on the HP Omen '
                   'RTX 5090, whose image stores 0x11/0x01', 'set_tested': False}
FAN_ZERO_RPM_HARDWARE = {
    'kind': 'hardware-test', 'source': 'edited image loaded as an override (Windows loader)', 'set_tested': True,
    'scope': 'one HP Omen RTX 5090, three fan channels; its image is outside the reviewed corpus',
    'observed': 'the copy with the field set to 1 (0x11/0x01 -> 0x17/0x07 on the five enabled entries, written by '
                'the editor build contributed with the field, which writes the same bytes) loaded; all three fans '
                'stood still at idle, started under load and stopped again after cooling down'}


def fan_stop_parameters(blob, at):
    """True when the policy entry at `at` stores what GSP-RM decodes next to bits 1|2: two rising
    nonzero temperatures (1/32 C) at bytes 30..33 and a byte 46 other than 0xff (the RTX PRO 6000
    Max-Q stores zeros and 0xff there)."""
    low, high = struct.unpack_from('<HH', blob, at + 30)
    return 0 < low < high and blob[at + 46] != 0xFF


@registry.register
def fan_zero_rpm(image, parser):
    """GB20x: bits 1|2 of the flag byte (0x32) of every enabled fan policy entry, both set (1) or clear (0).

    The entries are the active channels' and the enabled curves past the cooler rows. GSP-RM decodes
    the two bits as separate booleans; in the corpus every GeForce GB20x image sets both and every RTX
    PRO image clears both, and owner reports tie them to fans that stand still at idle. An
    entry with one bit alone, or entries that disagree, leave the field read-only. A write also sets
    the bits on the stored channel entries a larger channel count may enable (fan_layouts), as the
    PWM frequency does, so the count and the flag change in either order; such an entry whose bits
    differ leaves the field read-only. The value 1 is offered only when every written entry stores
    fan-stop parameters (fan_stop_parameters). Each entry keeps its other flag bits. Opt-in; setting 1
    is hardware-tested on one HP Omen RTX 5090 (FAN_ZERO_RPM_HARDWARE).
    """
    if not isinstance(parser, BlackwellRom):
        return []
    table = parser.fan_coolers()
    if table is None:
        return []
    active = [r for r in table['rows'] if r['active']]
    enabled = active + list(table['extra_curves'])
    if not enabled:
        return []
    # The channel counts fan_channels offers (fans): its rows share one PWM frequency and byte 13 = 0.
    shared = (len({r['pwm_frequency_hz'] for r in active}) == 1 and
              all(parser.blob[r['offset'] + 13] == 0 for r in active))
    most = fan_layouts(parser, table)[1] if shared else len(active)
    later = table['rows'][len(active):most]
    entries = table['rows'][:most] + list(table['extra_curves'])
    bits = {e['flag_byte'] & FAN_ZERO_RPM_BITS for e in enabled}
    state = 1 if bits == {FAN_ZERO_RPM_BITS} else 0 if bits == {0} else None
    if bits - {0, FAN_ZERO_RPM_BITS}:
        reason = ('read-only: an enabled fan policy entry sets only one of bits 1 and 2 of its flag byte (0x32); '
                  'GSP-RM reads them as two separate booleans')
    elif state is None:
        reason = 'read-only: the enabled fan policy entries disagree about bits 1 and 2 of their flag byte (0x32)'
    elif any(r['flag_byte'] & FAN_ZERO_RPM_BITS != FAN_ZERO_RPM_BITS * state for r in later):
        reason = ('read-only: a stored fan channel entry that a larger channel count enables differs from the '
                  'enabled entries in bits 1 and 2 of its flag byte (0x32)')
    elif state == 0 and not all(fan_stop_parameters(parser.blob, e['policy_offset']) for e in entries):
        reason = ('read-only: a fan policy entry stores no fan-stop parameters (no two rising nonzero temperatures '
                  'at bytes 30..33, or 0xff at byte 46, as on the RTX PRO 6000 Max-Q), so 1 is not offered')
    else:
        reason = None
    editable = reason is None and can_edit(image, parser)
    flags = [e['flag_byte'] for e in entries]
    layout = ((0, tuple(bytes((b & ~FAN_ZERO_RPM_BITS,)) for b in flags)),
              (1, tuple(bytes((b | FAN_ZERO_RPM_BITS,)) for b in flags)))
    return [field('fan_zero_rpm', 'Fan zero RPM (fans may stand still at low temperature)', 'flag', state,
                  0 if editable else None, 1 if editable else None, editable,
                  [dict(FAN_ZERO_RPM_FIRMWARE_EVIDENCE), dict(FAN_ZERO_RPM_CORPUS_EVIDENCE),
                   dict(FAN_ZERO_RPM_DRIVER_EVIDENCE), dict(FAN_ZERO_RPM_OWNER_EVIDENCE),
                   dict(FAN_ZERO_RPM_HARDWARE)],
                  offsets=[e['flag_offset'] for e in entries] if editable else (),
                  encoding='<B' if editable else '', scale=1, layout=layout if editable else (),
                  writable_status=None if editable else 'unsupported', experimental=True, opt_in=True,
                  value_semantics='stored-fan-zero-rpm', fan_entries=[e['index'] for e in entries],
                  reason=reason or 'experimental, opt-in: bits 1 and 2 of the flag byte (0x32) of every enabled fan '
                                   'policy entry (the channel entries and the enabled curves past them), both set '
                                   '(1) or both clear (0); GSP-RM decodes them as two separate booleans; in the '
                                   'corpus every GeForce GB20x image sets both and every RTX PRO image clears '
                                   'both; each entry keeps its other flag bits, and the stored channel entries a '
                                   'larger channel count enables take the same bits; hardware-tested on one HP '
                                   'Omen RTX 5090: with 1 the fans stood still at idle and started under load; '
                                   'other boards and setting 0 not hardware-tested')]


FAN_ZERO_RPM_TEMPS_FIRMWARE_EVIDENCE = {
    'kind': 'static-firmware-analysis',
    'source': 'GSP-RM firmware 615.78.08 (gsp_ga10x.bin), fan policy entry parser, policy constructor and '
              'configuration export',
    'observation': 'every enabled policy entry, a channel entry or a curve past the cooler rows, is decoded the same '
                   'way: bytes 30..33 become two temperatures (1/32 C words, kept in 1/256 C) next to the two '
                   'booleans of flag bits 1 and 2 and byte 46; the policy constructor copies all of them into the '
                   'policy configuration and its export passes them on together; no comparison against a measured '
                   'temperature was traced, so which value stops and which starts the fans is not established',
    'set_tested': False}
FAN_ZERO_RPM_TEMPS_V2_EVIDENCE = {
    'kind': 'static-firmware-analysis',
    'source': 'GSP-RM firmware 615.78.08 (gsp_ga10x.bin, built for GA10x, AD10x and GB20x) and the Windows driver '
              '617.42 (nvlddmkm.sys), fan policy table dispatch and entry parsers',
    'observation': 'the version byte of the policy table selects the parser: version 0x20 tables with 51-byte '
                   'entries, which every Ada and Ampere image stores as GB20x does, take the same entry parser, '
                   'which decodes bytes 30..33 and 46 with flag bits 1 and 2 as on GB20x; the Windows driver '
                   'decodes the same bytes; no chip check was found above the dispatch, so that Ada and Ampere '
                   'boards run this parser is inferred from the shared table version', 'set_tested': False}
FAN_ZERO_RPM_TEMPS_CORPUS_EVIDENCE = {
    'kind': 'structural-table', 'source': 'GB20x VBIOS corpus',
    'observation': 'every GPU-driven image but the RTX PRO 6000 Max-Q stores a rising nonzero pair and byte 46 = 0 '
                   'on each enabled entry: 43/50, 50/55 or 50/60 C on the channel entries, 60-80/70-90 C on the '
                   'curves past them, also on RTX PRO images with zero RPM off; the Max-Q stores 0/0 and byte 46 = '
                   '0xff'}
ADA_FAN_ZERO_RPM_TEMPS_CORPUS_EVIDENCE = {
    'kind': 'structural-table', 'source': 'Ada VBIOS corpus',
    'observation': 'every GeForce image stores a rising nonzero pair and byte 46 = 0 on each enabled entry, the '
                   'same in both image chains, with flag bits 1 and 2 set (0x17/0x07): 40/50 to 60/70 C on the '
                   'channel entries, 50-80/63-90 C on the extra curves; the RTX 4000, 4000 SFF, 4500 and 2000 Ada '
                   'store pairs with both bits clear (0x11/0x01); the RTX 5000 and 6000 Ada store 0/0 and byte 46 = '
                   '0xff'}
AMPERE_FAN_ZERO_RPM_TEMPS_CORPUS_EVIDENCE = {
    'kind': 'structural-table', 'source': 'Ampere VBIOS corpus',
    'observation': 'most GeForce images store a rising nonzero pair and byte 46 = 0 on each enabled entry, the same '
                   'in every image chain, with flag bits 1 and 2 set (0x17/0x07): 38.875-55/55-60 C on the channel '
                   'entries, 50-67/67-75 C on the extra curves; others store pairs with both bits clear (0x11/0x01: '
                   'an RTX 3080, an RTX 3060 Ti, the RTX 3050 and RTX A2000) or bit 1 alone (0x13/0x03: an RTX 3090, '
                   'an RTX 3070, the RTX 3060 8GB), and one RTX 3060 mixes 0x13 and 0x07; the RTX A1000, A4000, '
                   'A4500, A5000, A5500 and A6000 store 0/0 and byte 46 = 0xff'}
FAN_ZERO_RPM_TEMPS_HARDWARE = {
    'kind': 'hardware-test', 'set_tested': True,
    'source': 'owner report: an edited image loaded as an override (Windows loader)',
    'scope': 'one Zotac RTX 5080; its image is outside the reviewed corpus',
    'observed': 'with the stored 43/50 C the idle fans started at about 52 C; with the upper temperature set to '
                '60 C the fans stayed at 0 RPM at 59 C during video playback; which entries were edited and whether '
                'the lower temperature changed were not reported, and a start at 60 C was not observed'}
FAN_ZERO_RPM_TEMP_CEILING = 110 * 32  # an editor limit, as for the curve temperatures


@registry.register
def fan_zero_rpm_temperatures(image, parser):
    """GB20x, Ada and Ampere: the temperature pair at bytes 30..33 of each enabled fan policy entry, 1/32 C.

    The driver decodes the pair with the zero RPM flag bits (bits 1 and 2 of byte 0x32) and
    byte 46 and passes them on together; idle fans most likely stop below the lower value and
    start again above the upper one (on one RTX 5080 a raised upper value kept them stopped).
    Each active channel entry and each enabled curve past the cooler rows (the extra curves,
    numbered as in fan_curves) gets its own pair of fields, offered only where it stores
    parameters (fan_stop_parameters): none is synthesized for zeros (RTX PRO 6000 Max-Q, RTX
    5000/6000 Ada, most RTX A-series). The pair stays rising, from 1/32 C up to 110 C (an editor
    limit); its two fields form one ordering group, so they can cross the stored values
    together. On GB20x the fields do not depend on the flag bits. Ada and Ampere have no flag
    field, so their pairs are editable only where every enabled entry sets both bits, as the
    GeForce Ada images and most GeForce Ampere ones do; writes go to every duplicate image
    chain. Turing images store no pair
    (zeros and 0xff at the same place in their 54-byte entries) and get no field. Opt-in.
    """
    if not isinstance(parser, (BlackwellRom, TableRom)) or turing(parser):
        return []
    table = parser.fan_coolers()
    if table is None:
        return []
    entries = [(f'fan_{r["index"] + 1}', 'Fan %d' % (r['index'] + 1), 'channel %d' % (r['index'] + 1), r,
                dict(fan_channel=r['index'], fan_rows=[r['index']]))
               for r in table['rows'] if r['active']]
    entries += [(f'fan_extra_{m}', f'Extra fan curve {m}', f'extra curve {m}', c,
                 dict(fan_rows=[r['index'] for r in table['rows'] if r['active']]))
                for m, c in enumerate(table['extra_curves'], 1)]
    blackwell = isinstance(parser, BlackwellRom)
    if blackwell:
        evidence = [FAN_ZERO_RPM_TEMPS_FIRMWARE_EVIDENCE, FAN_ZERO_RPM_TEMPS_CORPUS_EVIDENCE,
                    FAN_ZERO_RPM_TEMPS_HARDWARE]
        tested = ('hardware-tested on one RTX 5080: with the upper raised to 60 C the fans stayed stopped at 59 C; '
                  'the lower value and other boards not hardware-tested')
        flagged = True
    else:
        evidence = [FAN_ZERO_RPM_TEMPS_V2_EVIDENCE, FAN_ZERO_RPM_TEMPS_FIRMWARE_EVIDENCE,
                    ADA_FAN_ZERO_RPM_TEMPS_CORPUS_EVIDENCE if ada(parser) else AMPERE_FAN_ZERO_RPM_TEMPS_CORPUS_EVIDENCE]
        tested = 'not hardware-tested on Ada or Ampere'
        flags = [parser.blob[e['policy_offset'] + FAN_POLICY_FLAG_OFFSET] for *_, e, _ in entries]
        flagged = all(f & FAN_ZERO_RPM_BITS == FAN_ZERO_RPM_BITS for f in flags)
    writable = can_edit(image, parser)
    result = []
    for prefix, name, owner, entry, extra in entries:
        at = entry['policy_offset'] + 30
        if not fan_stop_parameters(parser.blob, entry['policy_offset']):
            continue
        low, high = struct.unpack_from('<HH', parser.blob, at)
        inside = high <= FAN_ZERO_RPM_TEMP_CEILING and flagged
        editable = inside and writable
        for side, word, current, lo, hi, offset in (
                ('low', 'lower', low, 1, high - 1, at), ('high', 'upper', high, low + 1, FAN_ZERO_RPM_TEMP_CEILING,
                                                           at + 2)):
            offsets, _ = chain_copies(parser, [offset], 2)
            result.append(field(
                f'{prefix}_zero_rpm_{side}_temp_c', f'{name} zero RPM {word} temperature', 'C', current / 32,
                lo / 32, hi / 32, editable, [dict(e) for e in evidence],
                offsets=offsets if editable else (), encoding='<H' if editable else '', scale=32,
                stored_units='1/32 C', experimental=True, opt_in=True,
                ordering_group=f'fan-zero-rpm-{prefix}' if editable else None,
                encoding_bounds=(0, FAN_ZERO_RPM_TEMP_CEILING / 32) if editable else None,
                writable_status=None if editable else 'unsupported',
                value_semantics=f'stored-fan-zero-rpm-{word}-temperature', fan_policy=entry['index'], **extra,
                reason=f'experimental, opt-in: the {word} of the two temperatures (bytes 30..33) of the {owner} fan '
                       'policy entry, which the driver reads with the zero RPM flag bits; idle fans most likely stop '
                       'below the lower and start again above the upper one, and other fan policies and sensors may '
                       'still decide what the fans do; the lower stays above 0 C and below the upper, the upper at '
                       f'most 110 C (an editor limit); {tested}' if inside else
                       'read-only: the zero RPM flag bits (1 and 2 of byte 0x32) are not both set on every enabled '
                       'fan policy entry of this image, so the pair may be unused; the editor does not change those '
                       'bits on Ada and Ampere' if not flagged else
                       f'read-only: the upper temperature of the {owner} fan policy entry is above 110 C, outside '
                       'the reviewed shape'))
    return result


DRAM_POINT_FIRMWARE_EVIDENCE = {
    'kind': 'static-firmware-analysis',
    'source': 'GSP-RM firmware 615.78.08 (gsp_ga10x.bin), clock programming table parsers (versions 0x40 and 0x50)',
    'observation': 'the flag byte of each clock programming entry is decoded bit by bit and bit 4 becomes a '
                   'per-entry boolean; the code that applies a clock offset to the entries was not traced, so '
                   'that bit 4 marks the entries an offset moves is inferred', 'set_tested': False}
DRAM_POINT_CORPUS_EVIDENCE = {
    'kind': 'structural-table', 'source': 'Ada, Ampere and GB20x VBIOS corpus',
    'observation': 'the clocks table DRAM row names the DRAM entries of the clock programming table: one per memory '
                   'clock the performance states use, rising, flag byte 0x03 or 0x13; bit 4 is set on the top '
                   'memory levels of every image whose entries take this shape (all but the passive RTX A40) and '
                   'never on the 405 and 810 MHz idle levels; four GA104/GA106 laptop images (RTX 3060, 3070 and '
                   '3080 Laptop GPU) also set it on their intermediate level, which the other images leave clear'}
DRAM_POINT_OWNER_EVIDENCE = {
    'kind': 'owner-report', 'set_tested': False,
    'source': 'RTX 3050 Laptop GPU owner (Windows), memory offset under load',
    'observation': 'down to a -500 MHz offset the memory ran between 6001 and 5501 MHz; below that it left the '
                   '6001 MHz level for the 810 MHz one instead of running lower, and larger offsets crashed; '
                   '5501 MHz is the only level between them, stored without bit 4'}
DRAM_POINT_HARDWARE = {
    'kind': 'hardware-test', 'set_tested': True,
    'source': 'owner report: an edited image loaded as an override (Windows loader, verified byte for byte)',
    'scope': 'one RTX 3050 Laptop GPU (memory levels 405, 810, 5501 and 6001 MHz)',
    'observed': 'with bit 4 set on the 5501 MHz level and the memory offset floor lowered to -2000 MHz (table scale; '
                'MSI Afterburner reached it), the memory still left the 6001 MHz level for the 810 MHz one below a '
                '-500 MHz offset: on that card the bit did not make the level follow the offset'}


DRAM_POINT_SEMANTICS = 'stored-dram-point-offset'


@registry.register
def dram_offset_points(image, parser):
    """Ada, Ampere and GB20x: whether a memory offset moves each intermediate memory level.

    Bit 4 (DRAM_POINT_OFFSET_BIT) of the flag byte of each DRAM entry of the clock
    programming table (parser.dram_points). Stock images set it on the top memory levels
    only, and an offset that takes the memory below the highest level without it drops the
    memory to a lower stored level (inferred from the corpus and an owner report). One flag
    per level between the 810 MHz idle level and the top level: setting it was expected to
    let the offset move that level too. The levels with the bit stay the top ones (one ordering group), the
    idle levels and the top level are not offered, and each write keeps the other flag bits,
    in every image chain. Opt-in. On the one card tested (an RTX 3050 Laptop GPU) setting it
    did not stop the drop, so what decides it is unknown.
    """
    if not isinstance(parser, (BlackwellRom, TableRom)) or (isinstance(parser, TableRom) and turing(parser)):
        return []
    try:
        table = parser.dram_points()
    except FormatError:
        return []  # no reviewed clock programming table: nothing to offer
    points = table['points'][2:-1]
    moved = [bool(p['flags'] & DRAM_POINT_OFFSET_BIT) for p in table['points'][2:]]
    writable = can_edit(image, parser)
    result = []
    for k, point in enumerate(points):
        lo = 1 if k and moved[k - 1] else 0
        hi = 1 if moved[k + 1] else 0
        offsets, layout = chain_copies(parser, [point['offset']], 1, (
            (0, (bytes([point['flags'] & ~DRAM_POINT_OFFSET_BIT]),)),
            (1, (bytes([point['flags'] | DRAM_POINT_OFFSET_BIT]),))))
        result.append(field(
            f'memory_point_{k + 1}_follows_offset', f"Memory clock {point['mhz']} MHz follows the memory offset",
            'flag', 1 if moved[k] else 0, lo if writable else None, hi if writable else None, writable,
            [dict(DRAM_POINT_FIRMWARE_EVIDENCE), dict(DRAM_POINT_CORPUS_EVIDENCE), dict(DRAM_POINT_OWNER_EVIDENCE),
             dict(DRAM_POINT_HARDWARE)],
            offsets=offsets if writable else (), encoding='<B' if writable else '', scale=1,
            layout=layout if writable else (), ordering_group='dram-points' if writable else None,
            encoding_bounds=(0, 1) if writable else None,
            writable_status=None if writable else 'unsupported', experimental=True, opt_in=True,
            value_semantics=DRAM_POINT_SEMANTICS, memory_mhz=point['mhz'],
            reason=f"experimental, opt-in: bit 4 of the flag byte of the {point['mhz']} MHz memory level in the clock "
                   'programming table; stock images set it on the top memory levels, and a memory offset that takes '
                   'the memory below the highest level without it drops it to a lower level instead (on one RTX 3050 '
                   'Laptop GPU to 810 MHz); setting it was expected to let the offset move this level too '
                   '(inferred), but on that card, tested on its 5501 MHz level with a lower memory offset floor, the '
                   'memory still dropped to 810 MHz; the levels with it stay the top ones'))
    return result


GPC_CURVE_SEMANTICS = 'stored-gpc-curve-offset'
GPC_CURVE_FIRMWARE_EVIDENCE = {
    'kind': 'static-firmware-analysis',
    'source': 'GSP-RM firmware 615.78.08 (gsp_ga10x.bin), clocks and clock programming table parsers',
    'observation': 'the clocks table GPC row names one clock programming entry whose equation index is the root '
                   'of the GPC VF curve in the VFE table; the stored GPC frequency deltas of the clocks table are '
                   'ignored by default and could only raise the curve; a VFE equation adds its next equation to '
                   'its clamped value (as the voltage equations show), so a constant linked from the root should '
                   'move every point of the curve (inferred; the curve evaluation was not traced)',
    'set_tested': False}
GPC_CURVE_CORPUS_EVIDENCE = {
    'kind': 'structural-table', 'source': 'Ada, Ampere and GB20x VBIOS corpus',
    'observation': 'the GPC root is a compare equation with MHz output that no other equation references and that '
                   'links no next equation; the first unused VFE slot is clean; compare equations with a next link '
                   'and MHz output are common, and a newer RTX 4090 BIOS fills the older one\'s first unused slot '
                   'with a constant equation (a 15 mV voltage constant no equation references); no image links a '
                   'constant to the GPC root: two SKUs of one chip (RTX 2080 Ti and TITAN RTX) differ by +45 MHz in '
                   'the constant term of one polynomial inside the curve\'s floor and cap, and vendor factory-OC '
                   'images keep the reference curve'}


@registry.register
def gpc_curve_offset(image, parser):
    """GB20x, Ada and Ampere: a default offset of the GPC VF curve, in MHz.

    parser.gpc_curve finds the GPC root equation and the first unused VFE slot. A value
    other than 0 writes a constant MHz equation (vfe_constant_mhz) into that slot and
    links it as the root's next equation; 0 restores the unused slot and the empty link,
    byte for byte. Every point of the stock curve is expected to move by the value
    (inferred, not hardware-tested); a tuning tool's offset still applies on top.
    -500..+500 MHz, at the user's discretion. The bytes go through a layout per value,
    written in 2-byte chunks (the root's link bytes with their neighbours, and slot
    bytes 0..23), in every image chain; only this reviewed binding may write them.
    """
    if not isinstance(parser, (BlackwellRom, TableRom)) or (isinstance(parser, TableRom) and turing(parser)):
        return []
    try:
        curve = parser.gpc_curve()
    except FormatError:
        return []
    size, width, slot, var = curve['size'], curve['width'], curve['slot'], curve['var']
    root_at = curve['root_offset']
    root_bytes = parser.blob[root_at:root_at + size]
    root_parts = [1] + ([23] if width == 2 else [])
    slot_parts = list(range(0, 24, 2))  # bytes 0..23; byte 24 of a 25-byte slot is 0xff either way
    offsets = [root_at + k for k in root_parts] + [curve['slot_offset'] + k for k in slot_parts]

    def chunks(value):
        linked = bytearray(root_bytes)
        linked[2] = slot & 0xFF if value else 0xFF
        if width == 2:
            linked[24] = slot >> 8 if value else 0xFF
        body = vfe_constant_mhz(size, var, value) if value else vfe_free_slot(size)
        return tuple(bytes(linked[k:k + 2]) for k in root_parts) + tuple(body[k:k + 2] for k in slot_parts)
    layout = tuple((value, chunks(value)) for value in range(-GPC_CURVE_OFFSET_LIMIT, GPC_CURVE_OFFSET_LIMIT + 1))
    offsets, layout = chain_copies(parser, offsets, 2, layout)
    writable = can_edit(image, parser)
    return [field('gpc_curve_offset_mhz', 'GPC curve offset', 'MHz', curve['current'],
                  -GPC_CURVE_OFFSET_LIMIT if writable else None, GPC_CURVE_OFFSET_LIMIT if writable else None, writable,
                  [dict(GPC_CURVE_FIRMWARE_EVIDENCE), dict(GPC_CURVE_CORPUS_EVIDENCE)],
                  offsets=offsets if writable else (), encoding='<h' if writable else '', scale=1,
                  layout=layout if writable else (), writable_status=None if writable else 'unsupported',
                  experimental=True, opt_in=True, value_semantics=GPC_CURVE_SEMANTICS,
                  reason='experimental, opt-in: a constant MHz equation linked as the next equation of the GPC VF '
                         'curve root in the VFE table (first unused slot); it is expected to move every point of the '
                         'stock curve by this many MHz (inferred); a tuning tool\'s offset still applies on top, and '
                         'nvidia-smi max clocks and the rated boost do not change; values far from 0 can make the card '
                         'unstable; 0 restores the stock bytes; not hardware-tested')]


@registry.register
def memory(image, parser):
    rows = parser.clock_ranges()
    result = []
    for row in rows:
        if row['domain'] != 'DRAM':
            continue
        if isinstance(parser, BlackwellRom):
            # User-confirmed MHz relationship applies to the recognized GB20x
            # table only. It is never carried over to Ada/Ampere.
            evidence = [{'kind': 'reviewed-domain-identity', 'source': 'reviewed table layout',
                         'format': 'GB20x clock v50 descriptors and two reviewed domain layouts'},
                        {'kind': 'user-hardware-validated-units', 'relation': 'MHz = 2 * table MHz (NVML scale)',
                         'scope': 'reviewed GB202/GB203 corpus'}]
            result.extend([
                field('dram_max_table_mhz', 'Memory offset ceiling (table)', 'table MHz', row['maximum_mhz'],
                      max(0, row['minimum_mhz']), 32767, can_edit(image, parser), evidence,
                      offsets=[row['maximum_offset']], encoding='<h', scale=1, stored_units='table MHz'),
                field('memory_offset_max_mhz', 'Memory offset ceiling', 'MHz', 2 * row['maximum_mhz'],
                      2 * max(0, row['minimum_mhz']), 65534, can_edit(image, parser), evidence,
                      offsets=[row['maximum_offset']], encoding='<h', scale=Decimal('0.5'), stored_units='table MHz')])
            result.extend(clock_offset_ranges(image, parser, rows))
        elif isinstance(parser, TableRom):
            evidence = (ADA_CLOCK_EVIDENCE + [ADA_DRAM_UNITS_EVIDENCE] if ada(parser) else
                        TURING_CLOCK_EVIDENCE + [TURING_DRAM_UNITS_EVIDENCE] if turing(parser) else
                        AMPERE_CLOCK_EVIDENCE + [AMPERE_DRAM_UNITS_EVIDENCE])
            offsets = parser.copy_offsets(row['maximum_offset'], 2)
            blocked = clock_read_only(parser, row)
            editable = can_edit(image, parser) and not blocked
            reason = blocked or 'experimental: firmware memory offset ceiling; ' + (
                TURING_UNTESTED if turing(parser) else 'edit not hardware-tested')
            status = 'unsupported' if blocked else None
            result.extend([
                field('dram_max_table_mhz', 'Memory offset ceiling (table)', 'table MHz', row['maximum_mhz'],
                      max(0, row['minimum_mhz']), 32767, editable, [dict(e) for e in evidence],
                      offsets=offsets, encoding='<h', scale=1, stored_units='table MHz', experimental=True,
                      clock_domain='DRAM', clock_row=row['row'], reason=reason, writable_status=status),
                field('memory_offset_max_mhz', 'Memory offset ceiling', 'MHz', 2 * row['maximum_mhz'],
                      2 * max(0, row['minimum_mhz']), 65534, editable, [dict(e) for e in evidence],
                      offsets=offsets, encoding='<h', scale=Decimal('0.5'), stored_units='table MHz',
                      experimental=True, clock_domain='DRAM', clock_row=row['row'], reason=reason,
                      writable_status=status)])
            result.extend(clock_offset_ranges(image, parser, rows))
        else:
            result.append(field('dram_max_table_mhz', 'Memory offset ceiling (raw table)', 'table units',
                                row['maximum_mhz'], None, None, False,
                                [{'kind': 'read-only-table-probe', 'source': SOURCE}],
                                reason='Ada/Ampere memory units and editor variant lack validated evidence'))
    return result


CLOCK_RANGE_EVIDENCE = [
    {'kind': 'reviewed-domain-identity', 'source': 'reviewed table layout',
     'format': 'GB20x clock v50 descriptors and two reviewed domain layouts'},
    dict(THIRD_PARTY_EVIDENCE, observation=('object 0x03 rows hold signed MHz offset minimum/maximum per domain; '
                                            'only the DRAM maximum edit was verified on hardware there'))]


ADA_CLOCK_EVIDENCE = [
    {'kind': 'nvidia-struct-and-hal-order', 'source': SOURCE,
     'format': 'Ada clocks table C+8 v0x40 (40 0d 0f 0a 03 01 03 e8 03), ten 18-byte rows in the nvgpu GV HAL order '
               'GPC, XBAR, MCLK (DRAM), SYS, HUB, NVD (VID), PWR, DISP, PCIEGEN, HOST',
     'observation': 'row usage, ordering byte, rail sub-entry type and fixed bytes match on every parseable Ada image; '
                    'master rows hold signed MHz offset minimum/maximum at bytes 3/5 (nvgpu PARAM1); both chains written'},
    {'kind': 'saved-runtime-domain-list', 'use': 'cross-check only',
     'source': 'saved RM clock-domain list of the RTX 2000 Ada',
     'observation': 'domain ids by row 0,1,4,2,3,20,19,6,21,5 follow the GV HAL order; the XBAR entry repeats its row'}]
ADA_GPC_UNITS_EVIDENCE = dict(NVML_CAPTURE, relation='NVML MHz = table MHz', api='nvmlDeviceGetGpcClkMinMaxVfOffset',
                              observed='-1000..1000 for table rows -1000..1000', scope='RTX 2000 Ada 95.07.47.00.19')
ADA_DRAM_UNITS_EVIDENCE = dict(NVML_CAPTURE, relation='NVML MHz = 2 * table MHz',
                               api='nvmlDeviceGetMemClkMinMaxVfOffset', observed='-2000..6000 for table -1000..3000',
                               scope='RTX 2000 Ada 95.07.47.00.19')
AMPERE_CLOCK_EVIDENCE = [dict(
    AMPERE_STRUCTURAL_EVIDENCE, kind='nvidia-struct-and-hal-order', source=SOURCE,
    format='Ampere clocks table C+8 v0x40 (40, header size 0b or 0c, 0d 0a 03, one or two rails, 03 e8 03), ten '
           '13-byte rows with one 3-byte rail sub-entry per rail, in the nvgpu GV HAL order GPC, XBAR, MCLK (DRAM), '
           'SYS, HUB, NVD (VID), PWR, DISP, PCIEGEN, HOST',
    observation='row usage, ordering byte and fixed bytes match on every image and exactly one sub-entry per row has '
                'a nonzero type, as on Ada except VID (type 2); the table ends at the next C-token table; master rows '
                'hold signed MHz offset minimum/maximum at bytes 3/5; GPC -1000..1000 and DRAM -1000..3000 on every '
                'image except the A40 (0..0 on every domain); every duplicate chain written')]
AMPERE_GPC_UNITS_EVIDENCE = dict(AMPERE_STRUCTURAL_EVIDENCE, kind='unit-analogy', relation='NVML MHz = table MHz',
                                 use='analogy with the Ada and GB20x NVML readings; no Ampere NVML reading')
AMPERE_DRAM_UNITS_EVIDENCE = dict(AMPERE_STRUCTURAL_EVIDENCE, kind='unit-analogy', relation='NVML MHz = 2 * table MHz',
                                  use='analogy with the Ada and GB20x NVML readings; no Ampere NVML reading')
AMPERE_DISABLED_RANGE_REASON = ('read-only: the stored offset range of this domain is 0..0 (offsets disabled on this '
                                'board, as on the A40); whether a wider range would take effect is unknown')
TURING_CLOCK_EVIDENCE = [
    dict(TURING_STRUCTURAL_EVIDENCE, kind='nvidia-struct-and-hal-order', source=SOURCE,
         format='Turing clocks table C+8 v0x35 (35 09 0b 0a 03 e8 03 00 00) in the legacy image, ten 11-byte rows '
                '(nvgpu vbios_clocks_table_35) in the nvgpu GV HAL order GPC, XBAR, MCLK (DRAM), SYS, HUB, NVD (VID), '
                'PWR, DISP, PCIEGEN, HOST',
         observation='row usage (1 master: GPC, DRAM, DISP; 2 slave; 0 PWR), ordering byte and fixed bytes match on '
                     'every image; master rows hold signed MHz offset minimum/maximum at bytes 3/5 (nvgpu parameter '
                     '1): GPC -1000..1000 and DRAM -1000..3000 on every image except the Quadro RTX 8000 (0..0) and '
                     'the ASUS (below) and Galax HOF XOC images (GPC maximum 8000, DRAM maximum 5000); the slave rows '
                     'store other parameters there and give no field; every duplicate chain written'),
    dict(TURING_XOC_EVIDENCE, observation='the XOC image raises the GPC offset maximum 1000 -> 8000 and the DRAM '
                                          'maximum 3000 -> 5000 (table MHz)')]
TURING_GPC_UNITS_EVIDENCE = dict(TURING_STRUCTURAL_EVIDENCE, kind='unit-analogy', relation='NVML MHz = table MHz',
                                 use='analogy with the Ada and GB20x NVML readings; no Turing NVML reading')
TURING_DRAM_UNITS_EVIDENCE = dict(TURING_STRUCTURAL_EVIDENCE, kind='unit-analogy', relation='NVML MHz = 2 * table MHz',
                                  use='analogy with the Ada and GB20x NVML readings; no Turing NVML reading')
TURING_DISABLED_RANGE_REASON = ('read-only: the stored offset range of this domain is 0..0 (offsets disabled on this '
                                'board, as on the Quadro RTX 8000 image); whether a wider range would take effect is '
                                'unknown')
TURING_UNPADDED_CLOCK_REASON = ('read-only: the legacy image holding the clock table lacks the reviewed checksum '
                                'padding, so its checksum is not repaired; the other fields stay editable')


def disabled_range(parser, row):
    """True for an Ampere or Turing clock row whose stored offset range is 0..0."""
    return (ampere(parser) or turing(parser)) and row['minimum_mhz'] == row['maximum_mhz'] == 0


def clock_read_only(parser, row):
    """Why an Ada/Ampere/Turing clock range stays read-only, or None.

    A 0..0 range reads as disabled; on Turing the clock table sits in the legacy
    image, outside the tables checksum_padding_reviewed covers, so it is checked here.
    """
    if disabled_range(parser, row):
        return TURING_DISABLED_RANGE_REASON if turing(parser) else AMPERE_DISABLED_RANGE_REASON
    if turing(parser) and not parser.padded(parser.pointer('C', 8)):
        return TURING_UNPADDED_CLOCK_REASON
    return None


ADA_CLOCK_BOOT_EVIDENCE = {
    'kind': 'boot-readback', 'source': 'NVML clock offset ranges after booting an edited image',
    'scope': 'RTX 2000 Ada 95.07.47.00.19',
    'observed': 'table GPC maximum 1500 -> NVML core maximum 1500; table DRAM minimum -2500 -> NVML memory minimum -5000',
    'applied_offsets_tested': False}


def clock_offset_ranges(image, parser, rows):
    """Experimental GB20x, Ada, Ampere and Turing offset ranges beyond the hardware-validated GB20x DRAM ceiling.

    Domain names come from the structurally gated rows (GB20x rows 0-4, Ada,
    Ampere and Turing GV HAL positions). A range must keep 0 inside it, so minima
    are <= 0 and maxima >= 0 independently of each other. Only GPC and DRAM have
    an observed NVML unit relation (Ampere and Turing: by analogy only); the other
    domains have no runtime alias and stay in table MHz, and the Turing slave rows
    (XBAR, SYS, VID) store no range. Ada, Ampere and Turing write every duplicate
    chain. An Ampere or Turing range stored as 0..0 stays read-only, and api.edit
    refuses to collapse a wider one to 0..0.
    """
    editable = can_edit(image, parser)
    named = {row['domain']: row for row in rows}
    blackwell = isinstance(parser, BlackwellRom)
    base = (CLOCK_RANGE_EVIDENCE if blackwell else ADA_CLOCK_EVIDENCE if ada(parser) else
            TURING_CLOCK_EVIDENCE if turing(parser) else AMPERE_CLOCK_EVIDENCE)
    gpc_units = (GPC_UNITS_EVIDENCE if blackwell else ADA_GPC_UNITS_EVIDENCE if ada(parser) else
                 TURING_GPC_UNITS_EVIDENCE if turing(parser) else AMPERE_GPC_UNITS_EVIDENCE)
    dram_units = (DRAM_MIN_UNITS_EVIDENCE if blackwell else ADA_DRAM_UNITS_EVIDENCE if ada(parser) else
                  TURING_DRAM_UNITS_EVIDENCE if turing(parser) else AMPERE_DRAM_UNITS_EVIDENCE)
    booted = [ADA_CLOCK_BOOT_EVIDENCE] if ada(parser) else []

    def bound(key, label, row, side, units, factor, evidence, **extra):
        # factor converts stored table MHz to the public MHz unit (memory = 2x).
        if side == 'max':
            current, lo, hi, at = row['maximum_mhz'], max(0, row['minimum_mhz']), 32767, row['maximum_offset']
        else:
            current, lo, hi, at = row['minimum_mhz'], -32768, min(0, row['maximum_mhz']), row['minimum_offset']
        blocked = None if blackwell else clock_read_only(parser, row)
        return field(key, label, units, factor * current, factor * lo, factor * hi, editable and not blocked,
                     [dict(item) for item in evidence],
                     offsets=[at] if blackwell else parser.copy_offsets(at, 2), encoding='<h',
                     scale=Decimal(1) / factor, stored_units='table MHz',
                     value_semantics=f'stored-offset-range-{side}imum', experimental=True,
                     clock_domain=row['domain'], clock_row=row['row'],
                     reason=blocked or f"experimental: firmware offset {'ceiling' if side == 'max' else 'floor'}; " +
                     (TURING_UNTESTED if turing(parser) else 'edit not hardware-tested'),
                     **({'writable_status': 'unsupported'} if blocked else {}), **extra)
    dram, gpc = named['DRAM'], named['GPC']
    result = [bound('memory_offset_min_mhz', 'Memory offset floor', dram, 'min', 'MHz', 2,
                    base + [dram_units] + booted),
              bound('dram_min_table_mhz', 'Memory offset floor (table)', dram, 'min', 'table MHz', 1,
                    base + booted, alias_of='memory_offset_min_mhz'),
              bound('gpc_offset_max_mhz', 'Core (GPC) offset ceiling', gpc, 'max', 'MHz', 1,
                    base + [gpc_units] + booted),
              bound('gpc_offset_min_mhz', 'Core (GPC) offset floor', gpc, 'min', 'MHz', 1,
                    base + [gpc_units])]
    for domain in ('XBAR', 'SYS', 'VID'):
        if not named[domain].get('range_stored', True):
            continue
        for side, word in (('max', 'ceiling'), ('min', 'floor')):
            result.append(bound(f'{domain.lower()}_{side}_table_mhz', f'{domain} offset {word} (table)',
                                named[domain], side, 'table MHz', 1, base))
    return result


MAX_TEMP_SEMANTICS = 'stored-max-operating-temperature'
# Entry 0 of the thermal policy table on each reviewed GB20x product (PCI device), in C. The
# limit can be raised at most MAX_TEMP_RAISE_C above this value; a product without a stored
# value here can only be lowered.
MAX_TEMP_STOCK_C = {0x2B85: 90, 0x2BB1: 93, 0x2BB4: 92, 0x2C02: 88, 0x2C05: 88, 0x2C33: 96, 0x2C59: 89,
                    0x2D04: 87, 0x2F04: 85}
MAX_TEMP_FLOOR_C = 40
MAX_TEMP_RAISE_C = 3
MAX_TEMP_FIRMWARE_EVIDENCE = {
    'kind': 'static-firmware-analysis',
    'source': 'GSP-RM firmware 615.78.08 (gsp_ga10x.bin), thermal policy table parser (version 0x20)',
    'observation': 'each 48-byte entry is unpacked as 2b3w10d; byte 0 is the policy class and an entry with class 0 '
                   'is skipped; the three words after byte 1 are shifted left by 3 (1/32 C to 1/256 C) and handed to '
                   'the policy together', 'set_tested': False}
MAX_TEMP_CORPUS_EVIDENCE = {
    'kind': 'structural-table', 'source': 'GB20x VBIOS corpus',
    'observation': 'entry 0 is class 1 with byte 1 = 1 on every image and stores three equal temperatures: 90 C on '
                   'every RTX 5090, 88 C on the RTX 5080 and 5070 Ti, 85 C on the RTX 5070, 87 C on the RTX 5060 Ti, '
                   '92 C on the RTX PRO 6000 Max-Q, 93 C on the RTX PRO 6000 Workstation, 96 C on the RTX PRO 4000 '
                   'SFF and 89 C on the RTX 5080 Laptop GPU; entries 1 and 4 store 105 C (entry 4: 103 C on the '
                   'notebook); the notebook alone stores a second class 1 entry with byte 1 = 1, entry 2 at 87/75/87 '
                   'C, whose role was not traced; the ASUS XOC and MSI Lightning images keep the temperatures and set '
                   'byte 0 of entries 0, 1 and 4 to 0'}
MAX_TEMP_NVML_EVIDENCE = dict(
    NVML_CAPTURE, source='read-only nvidia-smi capture',
    relation="'GPU Current Temp' + 'GPU Current T.Limit Temp' = stored entry 0 temperature",
    scope='five reviewed GB20x devices: two RTX PRO 6000 Max-Q, an RTX 5080, an RTX 5070 Ti and an RTX PRO 4000 SFF')
MAX_TEMP_DISABLED_REASON = ('read-only: thermal policy entry 0 is disabled on this image (byte 0 = 0, as on XOC-style '
                           'images), so its temperature is not applied; the editor does not enable it')
MAX_TEMP_UNEQUAL_REASON = ('read-only: the three temperatures of thermal policy entry 0 differ on this image; the '
                           'editor writes them only together')
MAX_TEMP_UNRECOGNIZED_REASON = ('read-only: thermal policy entry 0 is not the class 1 entry with byte 1 = 1 that '
                                'every reviewed image stores')


def _other_limits(table):
    """The other enabled class 1 entries with byte 1 = 1 (the notebook's entry 2), as 'entry N (T C)' texts."""
    return ['entry %d (%s C)' % (e['index'], '/'.join('%g' % (Decimal(t) / 32) for t in e['temperatures_raw']))
            for e in table['entries'][1:] if e['policy_class'] == 1 and e['byte1'] == 1]


@registry.register
def max_operating_temperature(image, parser):
    """GB20x: the maximum operating temperature, entry 0 of the thermal policy table (P+0x50), in C.

    Entry 0 (class 1, byte 1 = 1) stores three s16 temperatures in 1/32 C, equal on every
    image of the corpus; the driver reports the GPU's temperature headroom against this value
    (nvidia-smi current temperature + T.Limit equals it on five boards). One field writes the
    three together; byte 0 and every other entry are never written. The value can be lowered
    to 40 C and raised at most 3 C above the product's stock value (MAX_TEMP_STOCK_C); an
    unlisted product can only lower it. Entry 0 with byte 0 = 0 (skipped by the driver, as on
    the XOC-style images) or three different temperatures stay read-only. Where another class 1
    entry with byte 1 = 1 exists (the notebook's entry 2, 87/75/87 C, untraced), the reason says
    that it may apply first. Not hardware-tested.
    """
    if not isinstance(parser, BlackwellRom):
        return []
    table = parser.thermal_policies()
    if table is None:
        return []
    entry = table['entries'][0]
    raw = entry['temperatures_raw']
    current = Decimal(raw[0]) / 32
    stock = MAX_TEMP_STOCK_C.get(parser.legacy['device'])
    if entry['policy_class'] == 0:
        reason = MAX_TEMP_DISABLED_REASON
    elif entry['policy_class'] != 1 or entry['byte1'] != 1 or not 0 < raw[0]:
        reason = MAX_TEMP_UNRECOGNIZED_REASON
    elif len(set(raw)) != 1:
        reason = MAX_TEMP_UNEQUAL_REASON
    else:
        reason = None
    editable = reason is None and can_edit(image, parser)
    ceiling = max(current, stock + MAX_TEMP_RAISE_C if stock is not None else current)
    floor = min(current, MAX_TEMP_FLOOR_C)
    limits = ('from 40 C up to 3 C above the stock %d C of this product' % stock if stock is not None else
              'from 40 C up to the stored value (this product has no reviewed stock value, so it can only be '
              'lowered)')
    others = _other_limits(table)
    caveat = ('; this image also stores ' + ', '.join(others) + ', a policy of the same kind whose role was not '
              'traced and that may limit the GPU first, so raising this value may have no effect') if others else ''
    at = entry['temperature_offset']
    return [field('max_operating_temp_c', 'Max operating temperature', 'C', float(current),
                  float(floor) if editable else None, float(ceiling) if editable else None, editable,
                  [dict(MAX_TEMP_FIRMWARE_EVIDENCE), dict(MAX_TEMP_CORPUS_EVIDENCE), dict(MAX_TEMP_NVML_EVIDENCE)],
                  offsets=[at, at + 2, at + 4] if editable else (), encoding='<h' if editable else '', scale=32,
                  stored_units='1/32 C', writable_status=None if editable else 'unsupported', experimental=True,
                  value_semantics=MAX_TEMP_SEMANTICS, thermal_policy=0, stock_c=stock,
                  reason=reason or 'experimental: the three temperatures of thermal policy entry 0 (1/32 C, written '
                                   'together), which the driver reports as the maximum operating temperature '
                                   f'(nvidia-smi current temperature + T.Limit equals it); {limits}; byte 0 and the '
                                   f'other entries stay as stored{caveat}; not hardware-tested')]


FACTORY_OFFSET_SEMANTICS = 'stored-factory-gpc-offset'
FACTORY_OFFSET_LIMIT_MHZ = 500
FACTORY_CLOCK_FIRMWARE_EVIDENCE = {
    'kind': 'static-firmware-analysis',
    'source': 'GSP-RM firmware 615.78.08 (gsp_ga10x.bin), factory clock record readers',
    'observation': 'at boot one reader takes each array-A entry whose flag is 1 and stores its 32-bit kHz value as a '
                   'static frequency delta of the clock domain the entry maps to (entry 0: the GPC domain, copied to '
                   'its companion domain); a flag of 0 skips the entry and any other flag fails the read; the function '
                   'that applies a static delta to a clock loads the 32-bit value sign-extended, divides it by 1000 '
                   'with a signed division (truncating toward zero to whole MHz), adds it to the clock in MHz and '
                   'returns 0 when the sum is negative, so the value is a signed kHz offset and a negative one lowers '
                   'the clock; a second reader writes each array-B entry with flag 1, in MHz, into a '
                   'performance-state clock entry', 'set_tested': False}
FACTORY_CLOCK_CORPUS_EVIDENCE = {
    'kind': 'structural-table', 'source': 'GB20x VBIOS corpus',
    'observation': 'the record header is 10 07 05 02 05 02 00 on every image; vendor factory-OC images set entry A0 '
                   '(flag 1) to their factory GPC offset and entry B1 to their rated boost clock: 120/2655 MHz on an '
                   'RTX 5090 Aorus Master, 195/2730 MHz on three other RTX 5090 images (ASUS ROG, MSI Lightning), '
                   '45/2580 MHz on the ASUS XOC images, 30/2640 MHz on an RTX 5080, 120/2572 MHz on an RTX 5070 Ti, '
                   '60/2572 MHz on an RTX 5070 and 30/2602 MHz on two RTX 5060 Ti; the Founders Edition, reference '
                   'RTX 5070, notebook and RTX PRO images store zeros with flag 0; entries A1 and B0 are 0 everywhere'}
FACTORY_OFFSET_DISABLED_REASON = ('read-only: this image stores no factory GPC offset (entry A0 of the factory clock '
                                  'record is disabled, as on Founders Edition, reference, laptop and RTX PRO images); '
                                  'the editor does not enable it')
FACTORY_OFFSET_FRACTION_REASON = ('read-only: the stored factory GPC offset is not a whole number of MHz, which no '
                                  'reviewed image stores; the driver uses it truncated to whole MHz')
FACTORY_BOOST_REASON = ('read-only: the rated boost clock of the factory clock record (entry B1); the driver writes it '
                        'into a performance-state clock entry, and the editor keeps it as stored')


def _mhz(khz):
    return khz // 1000 if khz % 1000 == 0 else khz / 1000


@registry.register
def factory_clocks(image, parser):
    """GB20x: the vendor factory GPC offset (entry A0 of the factory clock record, P+0x98) and its rated boost.

    A0 is a signed kHz offset that GSP-RM applies at boot as the GPC clock domain's static
    frequency delta, when its flag is 1 (vendor factory-OC images); the driver truncates it
    toward zero to whole MHz. It is editable in whole MHz, -500..+500 (a layout of kHz
    values), only where that flag is already 1 and the stored value is whole MHz; the flag,
    the rest of the record and the rated boost (B1, written into a performance-state clock
    entry) stay as stored. It is a separate mechanism from gpc_curve_offset_mhz (a VFE
    equation): both apply. B1 is listed read-only where its flag is 1. Not hardware-tested.
    """
    if not isinstance(parser, BlackwellRom):
        return []
    record = parser.factory_clocks()
    if record is None:
        return []
    offset, boost = record['offsets'][0], record['clocks'][1]
    enabled = offset['flag'] == 1
    whole = offset['khz'] % 1000 == 0
    editable = enabled and whole and can_edit(image, parser)
    current = _mhz(offset['khz'])
    lo, hi = (min(-FACTORY_OFFSET_LIMIT_MHZ, current), max(FACTORY_OFFSET_LIMIT_MHZ, current)) if whole else (0, 0)
    # Whole MHz only (the driver truncates the kHz value to whole MHz): each MHz value writes its kHz.
    layout = tuple((mhz, (struct.pack('<i', mhz * 1000),)) for mhz in range(lo, hi + 1)) if editable else ()
    evidence = [dict(FACTORY_CLOCK_FIRMWARE_EVIDENCE), dict(FACTORY_CLOCK_CORPUS_EVIDENCE)]
    reason = (None if whole else FACTORY_OFFSET_FRACTION_REASON) if enabled else FACTORY_OFFSET_DISABLED_REASON
    result = [field('factory_gpc_offset_mhz', 'Factory GPC offset (vendor overclock)', 'MHz', current,
                    lo if editable else None, hi if editable else None, editable, evidence,
                    offsets=[offset['value_offset']] if editable else (), encoding='<i' if editable else '',
                    scale=1, layout=layout, stored_units='kHz', writable_status=None if editable else 'unsupported',
                    experimental=True, value_semantics=FACTORY_OFFSET_SEMANTICS,
                    rated_boost_mhz=_mhz(boost['khz']) if boost['flag'] == 1 else None,
                    reason=reason or 'experimental: the vendor factory GPC offset (entry A0 of the factory clock '
                                     'record, signed kHz), which the driver applies at boot as the GPC clock frequency '
                                     'delta; -500..+500 MHz in whole MHz (the driver truncates to whole MHz); a '
                                     'negative value lowers the clock; a separate mechanism from the GPC curve offset, '
                                     'so both apply; the rated boost (entry B1) stays as stored; values far from the '
                                     'stock one can make the card unstable; not hardware-tested')]
    if boost['flag'] == 1:
        result.append(field('factory_rated_boost_mhz', 'Factory rated boost clock', 'MHz', _mhz(boost['khz']),
                            None, None, False, [dict(e) for e in evidence], writable_status='unsupported',
                            value_semantics='stored-factory-rated-boost', reason=FACTORY_BOOST_REASON))
    return result


# The Advanced section (GB20x): PERF_CF controllers and LPWR idle power features. Its fields carry
# section='advanced'; a field that only matters while a switch is on carries depends_on={'field':
# <switch key>, 'value': 1}, and edit() changes it only while that switch is 1, stored or requested
# in the same edit. The section is not part of the import from another ROM.
ADVANCED_SECTION = 'advanced'
PERF_CF_SWITCH_KEY = 'perf_cf_util_policy'
PERF_CF_SWITCH_SEMANTICS = 'stored-perf-cf-policy-switch'
PERF_CF_TARGET_SEMANTICS = 'stored-perf-cf-target'
PERF_CF_JUMP_SEMANTICS = 'stored-perf-cf-jump'
PERF_CF_HYSTERESIS_SEMANTICS = 'stored-perf-cf-hysteresis'
LPWR_SWITCH_SEMANTICS = 'stored-lpwr-switch'
LPWR_TIME_SEMANTICS = 'stored-lpwr-idle-time'
ADVANCED_SEMANTICS = (PERF_CF_SWITCH_SEMANTICS, PERF_CF_TARGET_SEMANTICS, PERF_CF_JUMP_SEMANTICS,
                      PERF_CF_HYSTERESIS_SEMANTICS, LPWR_SWITCH_SEMANTICS, LPWR_TIME_SEMANTICS)
# The utilization controllers of PERF_CF policy 0: (controller index, key part, clock domain name,
# domain byte 19, then the stock decrease hysteresis count, target and jump threshold fractions,
# identical on every reviewed image). The stock DRAM target 0x851 (51.98 %) is not the fraction
# nearest to 52 % (0x852): writing a stock percent stores the stock fraction, so going back to
# stock gives the stock bytes.
PERF_CF_CONTROLLERS = ((0, 'gpc', 'GPC', 0, 9, 0x0666, 0x0C00), (1, 'dram', 'DRAM', 2, 4, 0x0851, 0x0A3D),
                       (2, 'vid', 'VID', 4, 9, 0x0A66, 0x0D9A))
PERF_CF_FXP_ONE = 0x1000          # FXP20.12 1.0: 100 %
PERF_CF_TARGET_FLOOR_PCT = 10
PERF_CF_HYSTERESIS_UP = (1, 4)
PERF_CF_FIRMWARE_EVIDENCE = {
    'kind': 'static-firmware-analysis',
    'source': 'GSP-RM firmware 615.78.08 (gsp_ga10x.bin), PERF_CF controller and policy parsers, load validator and '
              'control handler',
    'observation': 'each 57-byte controller entry is unpacked as 3b5d1b2d1b4d1b1d; for the utilization controllers '
                   '(type 1 and its subclass type 5) bytes 3..6 become the target and 7..10 the jump threshold '
                   '(FXP20.12, 0x1000 = 100 %) and bytes 20 and 21 the increase and decrease hysteresis counts; the '
                   'validator run at load requires a target of 1..0x1000, a jump threshold of at most 0x1000 and '
                   'nonzero hysteresis counts, and the runtime control handler sets exactly these fields, the two '
                   'gains and one flag bit; each 10-byte policy entry is unpacked as 2b2d, its low nibble must be 1 '
                   'and bit 7 is read as the policy\'s active flag; a per-chip flag can make GSP-RM skip the VBIOS '
                   'controllers and what sets it on GB20x was not traced, so that these tables take effect on GB20x '
                   'is not proven', 'set_tested': False}
PERF_CF_CORPUS_EVIDENCE = {
    'kind': 'structural-table', 'source': 'GB20x VBIOS corpus',
    'observation': 'every image stores 20 controller and 9 policy entries; policy 0 is active (0x81) and names '
                   'controllers 0, 1, 2 and 13; controllers 0, 1 and 2 are the GPC, DRAM and video utilization '
                   'controllers (clock domain bytes 0, 2 and 4) with targets of 40, 52 and 65 %, jump thresholds of '
                   '75, 64 and 85 %, increase hysteresis 1 and decrease hysteresis 9, 4 and 9 on every image; the '
                   'notebook stores controller 0 as type 5; the controller header is 14 bytes on the RTX PRO 4000 SFF '
                   '(6 elsewhere), where object 0x60 also covers the policy table header'}
PERF_CF_POLICY_UNRECOGNIZED_REASON = ('read-only: policy entry 0 of the PERF_CF policy table is not the reviewed '
                                      'utilization policy (type nibble 1, naming controllers 0, 1 and 2)')
PERF_CF_CONTROLLER_UNRECOGNIZED_REASON = ('read-only: this PERF_CF controller is not the reviewed utilization '
                                          'controller (type 1 or 5, its clock domain, a target below its jump '
                                          'threshold and nonzero hysteresis counts)')
PERF_CF_GATE = 'editable only while the utilization policy is on (stored or in the same edit)'
PERF_CF_UNPROVEN = ('that the driver uses these tables on GB20x is not proven; not hardware-tested')


def fxp_percent(raw):
    """A FXP20.12 fraction (0x1000 = 100 %) in whole percent, rounded half up."""
    return int((Decimal(raw) * 100 / PERF_CF_FXP_ONE).to_integral_value(rounding=ROUND_HALF_UP))


def percent_fxp(percent):
    """Whole percent as the nearest FXP20.12 fraction."""
    return int((Decimal(percent) * PERF_CF_FXP_ONE / 100).to_integral_value(rounding=ROUND_HALF_UP))


def percent_layout(raw, stock_raw, low, high):
    """Layout of a FXP20.12 percent field: every whole percent from low to high as its nearest fraction; the
    stored percent keeps its stored fraction and the stock percent takes the stock fraction."""
    exact = {fxp_percent(stock_raw): stock_raw, fxp_percent(raw): raw}
    return tuple((p, (struct.pack('<I', exact.get(p, percent_fxp(p))),)) for p in range(low, high + 1))


def stock_multiple(stock, current):
    """0.5x..4x a stock value (rounded inward), widened to hold the stored one."""
    return min(math.ceil(stock / 2), current), max(4 * stock, current)


@registry.register
def perf_cf_controllers(image, parser):
    """GB20x Advanced section: the PERF_CF utilization policy switch and its GPC, DRAM and video controllers.

    perf_cf_util_policy is bit 7 (active) of policy entry 0, which runs controllers 0..2. Per
    controller: the target and the jump threshold (FXP20.12 at bytes 3 and 7, in whole
    percent; the stored fraction is kept when the percent is unchanged) and the increase and
    decrease hysteresis counts (bytes 20 and 21). Target: 10 % up to the jump threshold - 1 %;
    jump: the target + 1 % up to 100 % (GSP-RM refuses more), one ordering group per
    controller; decrease hysteresis 0.5x..4x its stock count, increase 1..4. The controller
    fields depend on the switch (depends_on): edit() changes them only while it is on. Policy
    or controller entries outside the reviewed shape stay read-only. Experimental: that the
    driver uses these tables on GB20x is not proven, and nothing is hardware-tested.
    """
    if not isinstance(parser, BlackwellRom):
        return []
    tables = parser.perf_cf()
    if tables is None:
        return []
    writable = can_edit(image, parser)
    evidence = [PERF_CF_FIRMWARE_EVIDENCE, PERF_CF_CORPUS_EVIDENCE]
    policy = tables['policies']['entries'][0]
    policy_ok = policy['kind'] == 1 and policy['controllers'] & 0b111 == 0b111
    editable = policy_ok and writable
    flags = policy['flags']
    result = [field(PERF_CF_SWITCH_KEY, 'Utilization clock policy', 'flag', 1 if policy['active'] else 0,
                    0 if editable else None, 1 if editable else None, editable, [dict(e) for e in evidence],
                    offsets=[policy['offset']] if editable else (), encoding='<B' if editable else '', scale=1,
                    layout=((0, (bytes((flags & 0x7F,)),)), (1, (bytes((flags | 0x80,)),))) if editable else (),
                    writable_status=None if editable else 'unsupported', experimental=True,
                    section=ADVANCED_SECTION, value_semantics=PERF_CF_SWITCH_SEMANTICS, perf_cf_policy=0,
                    perf_cf_controllers=[0, 1, 2],
                    reason='experimental: bit 7 (active) of PERF_CF policy entry 0, the utilization policy that '
                           'raises and lowers the GPC, DRAM and video clocks with load through controllers 0..2; '
                           'off is expected to stop that scaling (inferred); the other bits stay as stored, and the '
                           'targets, jump thresholds and hysteresis counts of controllers 0..2 are editable only '
                           'while it is on; ' + PERF_CF_UNPROVEN if policy_ok else PERF_CF_POLICY_UNRECOGNIZED_REASON)]
    depends = {'field': PERF_CF_SWITCH_KEY, 'value': 1}
    for index, part, name, domain, stock_down, stock_target, stock_jump in PERF_CF_CONTROLLERS:
        entry = tables['controllers']['entries'][index]
        target, jump = fxp_percent(entry['target_raw']), fxp_percent(entry['jump_raw'])
        recognized = (entry['type'] in (1, 5) and entry['domain'] == domain and 0 < entry['target_raw'] and
                      entry['jump_raw'] <= PERF_CF_FXP_ONE and target < jump and entry['hysteresis_up'] and
                      entry['hysteresis_down'])
        reason = None if recognized and policy_ok else (PERF_CF_CONTROLLER_UNRECOGNIZED_REASON if policy_ok else
                                                         PERF_CF_POLICY_UNRECOGNIZED_REASON)
        editable = reason is None and writable
        common = dict(writable_status=None if editable else 'unsupported', experimental=True,
                      section=ADVANCED_SECTION, depends_on=dict(depends), perf_cf_controller=index,
                      clock_domain=name)
        group = f'perf-cf-{part}' if editable else None
        floor = min(PERF_CF_TARGET_FLOOR_PCT, target)
        target_layout = percent_layout(entry['target_raw'], stock_target, floor, max(99, target))
        jump_layout = percent_layout(entry['jump_raw'], stock_jump, min(floor + 1, jump), max(100, jump))
        result.append(field(
            f'perf_cf_{part}_target_pct', f'{name} utilization target', '%', target,
            floor if editable else None, jump - 1 if editable else None, editable, [dict(e) for e in evidence],
            offsets=[entry['target_offset']] if editable else (), encoding='<I' if editable else '', scale=1,
            layout=target_layout if editable else (), ordering_group=group,
            encoding_bounds=(floor, max(99, target)) if editable else None, stored_units='FXP20.12 fraction',
            value_semantics=PERF_CF_TARGET_SEMANTICS, stored_raw=entry['target_raw'],
            stock=fxp_percent(stock_target), **common,
            reason=reason or f'experimental: the {name} utilization target of PERF_CF controller {index} (FXP20.12 '
                             'at entry byte 3, shown in whole percent; the stored fraction is kept while the percent '
                             f'is unchanged): the load the driver keeps the {name} clock near; lower raises the '
                             'clock sooner at partial load (more power and heat), higher keeps it lower (inferred); '
                             f'{PERF_CF_TARGET_FLOOR_PCT} % up to 1 % below the jump threshold; {PERF_CF_GATE}; '
                             + PERF_CF_UNPROVEN))
        result.append(field(
            f'perf_cf_{part}_jump_pct', f'{name} jump threshold', '%', jump,
            target + 1 if editable else None, max(100, jump) if editable else None, editable,
            [dict(e) for e in evidence], offsets=[entry['jump_offset']] if editable else (),
            encoding='<I' if editable else '', scale=1, layout=jump_layout if editable else (),
            ordering_group=group, encoding_bounds=(min(floor + 1, jump), max(100, jump)) if editable else None,
            stored_units='FXP20.12 fraction', value_semantics=PERF_CF_JUMP_SEMANTICS, stored_raw=entry['jump_raw'],
            stock=fxp_percent(stock_jump), **common,
            reason=reason or f'experimental: the {name} jump threshold of PERF_CF controller {index} (FXP20.12 at '
                             'entry byte 7, whole percent): above this load the driver is expected to raise the clock '
                             'at once instead of in steps (inferred); 1 % above the target up to 100 %, the most the '
                             f'driver accepts; {PERF_CF_GATE}; ' + PERF_CF_UNPROVEN))
        low, high = stock_multiple(stock_down, entry['hysteresis_down'])
        result.append(field(
            f'perf_cf_{part}_hysteresis_down', f'{name} clock-down hysteresis', 'samples', entry['hysteresis_down'],
            low if editable else None, high if editable else None, editable, [dict(e) for e in evidence],
            offsets=[entry['hysteresis_down_offset']] if editable else (), encoding='<B' if editable else '',
            scale=1, stored_units='samples', value_semantics=PERF_CF_HYSTERESIS_SEMANTICS, stock=stock_down,
            **common,
            reason=reason or f'experimental: the decrease hysteresis count of the {name} PERF_CF controller {index} '
                             '(entry byte 21, samples, inferred): how long the load stays below the target before '
                             'the clock steps down; higher keeps clocks up longer, lower drops them sooner and may '
                             f'stutter; {low}..{high} (0.5x to 4x the stock {stock_down}); {PERF_CF_GATE}; '
                             + PERF_CF_UNPROVEN))
        low, high = min(PERF_CF_HYSTERESIS_UP[0], entry['hysteresis_up']), max(PERF_CF_HYSTERESIS_UP[1],
                                                                               entry['hysteresis_up'])
        result.append(field(
            f'perf_cf_{part}_hysteresis_up', f'{name} clock-up hysteresis', 'samples', entry['hysteresis_up'],
            low if editable else None, high if editable else None, editable, [dict(e) for e in evidence],
            offsets=[entry['hysteresis_up_offset']] if editable else (), encoding='<B' if editable else '',
            scale=1, stored_units='samples', value_semantics=PERF_CF_HYSTERESIS_SEMANTICS, stock=1, **common,
            reason=reason or f'experimental: the increase hysteresis count of the {name} PERF_CF controller {index} '
                             '(entry byte 20, samples, inferred): how long the load stays above the target before '
                             f'the clock steps up; 1..4 (stock 1); {PERF_CF_GATE}; ' + PERF_CF_UNPROVEN))
    return result


# LPWR feature switches: (key, table, label, the value a disabled entry of the table stores with bit 0
# clear, or None when every entry belongs to the switch, effect). A switch covers the entries the
# image enables in stock: every entry whose value without bit 0 differs from the disabled value
# (DIFR: entry 0 only). Off clears bit 0 of each covered entry, Stock sets it again.
LPWR_SWITCHES = (
    ('lpwr_gr_power_gating', 'gr_pg', 'GR power gating', 0xFFFFFE00,
     'Off keeps the graphics engine powered at idle'),
    ('lpwr_mscg', 'ms', 'Memory system clock gating (MSCG)', 0xFFFFF000,
     'Off keeps the memory system clocks running at idle'),
    ('lpwr_nvdec_gating', 'nvdec', 'NVDEC power gating', None, 'Off keeps the video decoder powered while idle'),
    ('lpwr_nvenc_gating', 'nvenc', 'NVENC power gating', None, 'Off keeps the video encoder powered while idle'),
    ('lpwr_ofa_gating', 'ofa', 'OFA power gating', None, 'Off keeps the optical flow engine powered while idle'),
    ('lpwr_nvjpg_gating', 'nvjpg', 'NVJPG power gating', None, 'Off keeps the JPEG engine powered while idle'),
    ('lpwr_difr', 'difr', 'DIFR', 0xFFFFF800,
     'Off may help with flicker or idle oddities on a static desktop (inferred)'),
    ('lpwr_gr_rail_gating', 'gr_rg', 'GR rail gating', None, 'Off keeps the GR rail powered at idle'),
)
# GR rail gating: the entries each reviewed product enables in stock (RTX PRO 4000 SFF and the
# RTX 5080 Laptop GPU). Its bit 1 is set on stock-disabled GeForce entries too, so an entry
# switched off looks like a stock-disabled one: only these products get the switch.
LPWR_GR_RG_STOCK = {0x2C33: (0,), 0x2C59: (0, 1, 2)}
# Idle times: (key, table, header offset, switch, units, multiplier into units, stock stored value, label).
LPWR_TIMES = (
    ('lpwr_difr_dfpr_idle_ms', 'difr', 5, 'lpwr_difr', 'ms', 1, 1000, 'DIFR DFPR idle time'),
    ('lpwr_difr_sw_asr_idle_us', 'difr', 7, 'lpwr_difr', 'us', 1, 15, 'DIFR SW-ASR idle time'),
    ('lpwr_difr_cg_idle_us', 'difr', 9, 'lpwr_difr', 'us', 1, 15, 'DIFR clock gating idle time'),
    ('lpwr_gr_rail_gating_idle_us', 'gr_rg', 5, 'lpwr_gr_rail_gating', 'us', 10, 50, 'GR rail gating idle time'),
)
LPWR_FIRMWARE_EVIDENCE = {
    'kind': 'static-firmware-analysis',
    'source': 'GSP-RM firmware 615.78.08 (gsp_ga10x.bin), LPWR VBIOS initialization and table parsers',
    'observation': 'the LPWR initialization checks each table version (0x10) and parses every entry; an entry whose '
                   'enable bit (bit 0) is clear is skipped, for GR power gating, MSCG, GR rail gating, DIFR and '
                   'NVDEC/NVENC/OFA/NVJPG power gating; the DIFR header words at +5 (DFPR, times 1000), +7 (SW-ASR) '
                   'and +9 (clock gating) and the GR rail gating word at +5 (times 10) are copied without conditions '
                   'into the idle thresholds of their controllers, which become counter cycles as frequency x time / '
                   '1e6, so their unit is most likely microseconds (inferred)', 'set_tested': False}
LPWR_CORPUS_EVIDENCE = {
    'kind': 'structural-table', 'source': 'GB20x VBIOS corpus',
    'observation': 'each table has the same version, header and entry sizes and five entries on every image; GR power '
                   'gating is enabled on entries 0 and 1 (also 2 on the RTX 5080, RTX 5070 Ti, RTX PRO 4000 SFF and '
                   'the notebook), MSCG on entries 0..2 (0..1 on the RTX PRO 6000 Workstation, RTX 5070 and RTX 5060 '
                   'Ti), NVDEC/NVENC/OFA/NVJPG on every entry and DIFR on entry 0; disabled GR, MSCG and DIFR entries '
                   'store 0xfffffe00, 0xfffff000 and 0xfffff800; GR rail gating is enabled only on the RTX PRO 4000 '
                   'SFF (entry 0) and the notebook (entries 0..2); the DIFR words store 1000, 15 and 15 and the GR '
                   'rail gating word 50 on every image'}
LPWR_MIXED_REASON = ('read-only: the entries this switch covers are neither all enabled nor all disabled on this '
                     'image')
LPWR_GR_RG_UNREVIEWED_REASON = ('read-only: GR rail gating is enabled on this image, but which entries this product '
                                'enables in stock is not reviewed')
LPWR_GR_RG_UNRECOGNIZED_REASON = ('read-only: a GR rail gating entry this product enables in stock does not store '
                                  'the reviewed value (0xff, or 0xfe when switched off)')
LPWR_TIME_SWITCH_REASON = 'read-only: the switch this idle time belongs to is read-only on this image'
LPWR_UNTESTED = ('acts only at idle or light load (inferred); low idle times save more power but can cause stutter '
                 'or, rarely, a black screen at idle; not hardware-tested')


def lpwr_covered(parser, key, table, disabled):
    """(entries the switch covers, read-only reason or None); no entries means no switch."""
    entries = table['entries']
    if key == 'lpwr_gr_rail_gating':
        stock = LPWR_GR_RG_STOCK.get(parser.legacy['device'])
        if stock is None:
            return ([], None) if not any(e['value'] & 1 for e in entries) else (
                [e for e in entries if e['value'] & 1], LPWR_GR_RG_UNREVIEWED_REASON)
        covered = [entries[i] for i in stock if i < len(entries)]
        if len(covered) != len(stock) or any(e['value'] & 0xFE != 0xFE for e in covered):
            return covered, LPWR_GR_RG_UNRECOGNIZED_REASON
        return covered, None
    if key == 'lpwr_difr':
        entries = entries[:1]
    return [e for e in entries if disabled is None or e['value'] & ~1 != disabled], None


@registry.register
def lpwr_features(image, parser):
    """GB20x Advanced section: Stock/Off switches of the LPWR idle power features and their idle times.

    Each switch (LPWR_SWITCHES) covers the entries of its table the image enables in stock
    (lpwr_covered); 1 (Stock) sets bit 0 of each of them, 0 (Off) clears it, and every other
    bit and entry stays as stored, so Off and back is byte-identical. Entries that do not all
    agree leave the switch read-only. GR power gating, MSCG and DIFR never cover an entry
    holding the disabled value; the video engine switches cover every entry, so a ROM that
    ships them all disabled reads as Off and Stock would enable them (no reviewed image does).
    GR rail gating is offered only on the products whose stock entries are reviewed
    (LPWR_GR_RG_STOCK). The idle
    times (LPWR_TIMES) are absolute values in their units, 0.5x..4x the stock value, and
    depend on their switch (depends_on). Experimental, not hardware-tested.
    """
    if not isinstance(parser, BlackwellRom):
        return []
    writable = can_edit(image, parser)
    evidence = [LPWR_FIRMWARE_EVIDENCE, LPWR_CORPUS_EVIDENCE]
    result, switches, tables = [], {}, {}
    for key, name, label, disabled, effect in LPWR_SWITCHES:
        table = parser.lpwr_table(name)
        if table is None:
            continue
        covered, reason = lpwr_covered(parser, key, table, disabled)
        if not covered:
            continue
        bits = {e['value'] & 1 for e in covered}
        state = 1 if bits == {1} else 0 if bits == {0} else None
        reason = reason or (LPWR_MIXED_REASON if state is None else None)
        editable = reason is None and writable
        switches[key], tables[name] = editable, table
        fmt = table['format']
        layout = ((0, tuple(struct.pack(fmt, e['value'] & ~1) for e in covered)),
                  (1, tuple(struct.pack(fmt, e['value'] | 1) for e in covered)))
        result.append(field(
            key, label, 'flag', state, 0 if editable else None, 1 if editable else None, editable,
            [dict(e) for e in evidence], offsets=[e['offset'] for e in covered] if editable else (),
            encoding=fmt if editable else '', scale=1, layout=layout if editable else (),
            writable_status=None if editable else 'unsupported', experimental=True, section=ADVANCED_SECTION,
            switch='stock-off', value_semantics=LPWR_SWITCH_SEMANTICS, lpwr_table=name,
            lpwr_entries=[e['index'] for e in covered],
            reason=reason or f'experimental: bit 0 (enable) of the {label} entries this image enables in stock '
                             f'(entries {", ".join(str(e["index"]) for e in covered)} of its LPWR table); 0 (Off) '
                             'clears it, so the driver skips them, and 1 (Stock) sets it again; every other bit '
                             f'and entry stays as stored; {effect}, at a little more idle power; ' + LPWR_UNTESTED))
    for key, name, at, switch, units, multiplier, stock, label in LPWR_TIMES:
        if switch not in switches:
            continue
        table = tables[name]
        offset = table['offset'] + at
        stored = struct.unpack_from('<H', parser.blob, offset)[0]
        editable = switches[switch]
        low, high = stock_multiple(stock, stored)
        stored_units = units if multiplier == 1 else f'{multiplier} {units}'
        # What the driver does with the stored word: DIFR DFPR (ms) times 1000, GR rail gating times 10.
        factor = 1000 if units == 'ms' else multiplier
        driver = (f'the driver multiplies it by {factor} into' if factor != 1 else 'the driver copies it into')
        result.append(field(
            key, label, units, stored * multiplier, low * multiplier if editable else None,
            high * multiplier if editable else None, editable, [dict(e) for e in evidence],
            offsets=[offset] if editable else (), encoding='<H' if editable else '',
            scale=Decimal(1) / multiplier, stored_units=stored_units,
            writable_status=None if editable else 'unsupported', experimental=True, section=ADVANCED_SECTION,
            depends_on={'field': switch, 'value': 1}, value_semantics=LPWR_TIME_SEMANTICS, lpwr_table=name,
            stock=stock * multiplier,
            reason=f'experimental: the {label} (LPWR table header word +{at}, stored in {stored_units}: {driver} '
                   'an idle threshold most likely in microseconds, inferred): how long the feature waits at idle '
                   f'before it engages; {low * multiplier}..{high * multiplier} {units} (0.5x to 4x the stock '
                   f'{stock * multiplier}); editable only while its switch is Stock (stored or in the same edit); '
                   + LPWR_UNTESTED if editable or not writable else LPWR_TIME_SWITCH_REASON))
    return result


@registry.register
def unknown_fields(image, parser):
    current_reason = 'per-policy units/semantics require independent evidence'
    try:
        if any(b.descriptor['key'] == 'input_current_rated_ma' for b in input_current(image, parser)):
            current_reason = 'generic current mapping unknown; the reviewed 12 V input policy uses input_current_*_ma'
    except VbiosError:
        pass
    result = [field('current_limit_a', 'Input current limit', 'A', None, None, None, False, [],
                    reason=current_reason),
              field('ocp_limit_a', 'Overcurrent protection limit', 'A', None, None, None, False, [],
                    reason='generic OCP mapping unknown; reviewed per-rail output ceilings use *_output_ocp_max_ma')]
    family = metadata(image)['architecture']['family']
    try:
        # A recognized Ada/Ampere/Turing clock table provides the real memory ceiling field.
        known_memory = family in ('ada', 'ampere', 'turing') and any(b.descriptor['key'] == 'memory_offset_max_mhz'
                                                                     for b in memory(image, parser))
    except VbiosError:
        known_memory = False
    if family in ('ada', 'ampere', 'turing') and not known_memory:
        result.append(field('memory_offset_max_mhz', 'Memory offset ceiling', 'MHz',
                            None, None, None, False, [],
                            reason='memory domain and MHz/table conversion need independent validation'))
    try:
        # A recognized single Ampere rail is NVVDD only, as on Ada; the Turing rail table holds one row.
        single = (ampere(parser) or turing(parser)) and len({r['rail_index'] for r in parser.rail_equations()}) == 1
    except VbiosError:
        single = False
    if metadata(image)['architecture']['family'] == 'ada' or single_rail(parser) or single:
        result.append(field('msvdd_rel_max_mv', 'MSVDD REL ceiling', 'mV', None, None, None, False, [],
                            writable_status='unsupported',
                            reason='this recognized single-rail layout exposes only logic/NVVDD'))
    return result


def describe(image, parser):
    bindings, diagnostics = registry.bindings(image, parser)
    return [dict(b.descriptor) for b in bindings], diagnostics
