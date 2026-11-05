"""GB20x runtime voltage-offset hooks (runtime_voltage_offsets): generated images, and reference ROMs when available.

The hook bytes are rebuilt here from the layout alone (mvolt_style), independently of the editor, and the
invariants and evaluated limits are checked with this module's own readers.
"""
import hashlib
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nvidia_vbios.editor import IMPORT_SECTIONS, edit, import_fields
from nvidia_vbios.editor.registry import FOLLOW_OV_HOOKS_REASON
from nvidia_vbios.gui.i18n import Messages
from nvidia_vbios.gui.presentation import read_only_reason, runtime_offsets_notes
from nvidia_vbios.rom import FormatError, VbiosError, from_bytes, inspect_image, load
from nvidia_vbios.rom.blackwell import BlackwellRom, HOOK_PARTIAL_DIAGNOSTIC
from nvidia_vbios.rom.image import backend
from nvidia_vbios.rom.structure import vfe_free_slot, vfe_range
from test_extended_fields import custom_registry, descriptors
from test_rail_vmin import blackwell_vmin
from test_rom_formats import synthetic_rom
from test_turing import synthetic_turing

# The layout, written out independently of the editor's constants.
TEMPLATE = bytes((9,)) + bytes(8) + bytes((7, 8, 0, 4)) + bytes(5) + bytes((0x10,)) + bytes(10)
FREE_VARIABLE = bytes(9) + b'\xff' + bytes(8) + b'\x10' + bytes(10)
BODY = struct.pack('<5f', -1250000.0, 1250000.0, 0.0, 1.0, 0.0)
HEADER = bytes.fromhex('300e1dff19001400000108050020')
SLOT_OFFSETS = (0x0D, 0x0F, 0x11, 0x13)
# A constant 0 uV equation on variable 14 with no next link (an equation in use that nothing references).
UNUSED_CONSTANT = bytes((1, 14, 0xFF)) + bytes(20) + bytes((2, 0xFF))
# Every u16 word of a rail row that may select a VFE equation (BlackwellRom RAIL_SELECTORS, written out).
ROW_WORDS = (0x0D, 0x0F, 0x11, 0x13, 0x15, 0x17, 0x1D, 0x1F, 0x21, 0x23) + tuple(range(0x29, 0x41, 2))
# The fields a hook install may change besides the switch: the follow-OV switch and flat value turn read-only.
HOOK_AFFECTED = {'runtime_voltage_offsets', 'nvvdd_rel_alt_follow_ov', 'nvvdd_rel_alt_follow_ov_mv'}


def tables(blob):
    """(VFE variables, VFE equations, equation count, rail table, rows) of a GB20x image, located without the
    editor's hook code."""
    parsed = BlackwellRom(blob)
    vfe, rail = parsed.pointer('P', 0x20), parsed.pointer('P', 0x68)
    variables = vfe + blob[vfe + 1]
    return variables, variables + 29 * 255, blob[vfe + 5] | blob[vfe + 10] << 8, rail, blob[rail + 3]


def word(blob, at):
    return struct.unpack_from('<H', blob, at)[0]


def slot_words(blob):
    """The rail row offsets of the REL, ALT, OV and VMIN (+0x13) words that name an equation (below the equation
    count, as mVolt+ reads them), NVVDD then MSVDD."""
    _, _, count, rail, rows = tables(blob)
    return [rail + 5 + 65 * r + k for r in range(rows) for k in SLOT_OFFSETS if word(blob, rail + 5 + 65 * r + k) < count]


def links(e):
    """Equation indices a 25-byte GB20x VFE equation links: next, min/max and compare children, compare criterion."""
    if not e[0]:
        return []
    result = [e[2] | e[24] << 8]
    if e[0] == 2:
        result += [e[11] | e[15] << 8, e[12] | e[16] << 8]
    elif e[0] == 3:
        result += [e[15] | e[19] << 8, e[16] | e[20] << 8] + ([e[11] | e[12] << 8] if e[23] & 0x10 else [])
    return [x for x in result if x != 0xFFFF]


def repair(blob):
    """Rehash every object of both directories, both digests and the image checksums of a GB20x image."""
    blob = bytearray(blob)
    parsed = BlackwellRom(bytes(blob))
    for objects, directory in ((parsed.objects, parsed.directory),
                               (parsed.legacy_objects, parsed.legacy_directory)):
        for o in objects:
            blob[o['hash_offset']:o['hash_offset'] + 48] = hashlib.sha384(blob[o['data']:o['data'] + o['size']]).digest()
        if directory:
            at = directory['digest_offset']
            blob[at:at + 48] = hashlib.sha384(blob[directory['header']:directory['data_base']]).digest()
    for start, end in list(parsed.image_regions) + [(parsed.legacy['start'], parsed.legacy['end'])]:
        blob[end - 1] = (blob[end - 1] - sum(blob[start:end])) & 255
    return bytes(blob)


def mvolt_style(blob):
    """The hooks as the layout describes them, built without the editor: per present word, in order, the first
    unused variable gets the template and the first unused equation the hook linking the word's equation."""
    b = bytearray(blob)
    variables, equations, count, _, _ = tables(blob)
    free_v = [i for i in range(255) if not b[variables + 29 * i]]
    free_e = [i for i in range(count) if not b[equations + 25 * i]]
    for k, at in enumerate(slot_words(blob)):
        old, var, hook = word(b, at), free_v[k], free_e[k]
        b[variables + 29 * var:variables + 29 * var + 29] = TEMPLATE
        b[equations + 25 * hook:equations + 25 * hook + 25] = bytes((1, var, old & 0xFF)) + BODY + bytes((2, old >> 8))
        struct.pack_into('<H', b, at, hook)
    return repair(b)


def hooks_fixture():
    """blackwell_vmin(legacy=True) grown to the GB20x VFE layout: 2048 equations (16 used, the rest clean unused),
    variables 0..19 used (4 and 5 hold the template), 20..254 unused. Words: NVVDD REL 0, ALT 1, OV 2 (constant
    1200 mV), VMIN 8 (constant 800 mV); MSVDD REL 4, ALT 5, OV 6, VMIN 9 (an unclamped min/max root). Equations
    10 and 12..15 hold constants nothing uses, so the unused equations form one end block."""
    blob = bytearray(blackwell_vmin(legacy=True))
    parsed = backend(from_bytes(bytes(blob)))
    grow = 51200
    blob = blob[:28160] + bytearray(grow) + blob[28160:]
    p = parsed.extended_images[0]
    struct.pack_into('<H', blob, p['npds'] + 16, (p['size'] + grow) // 512)
    owner = next(o for o in parsed.objects if o['id'] == 0x14)
    struct.pack_into('<I', blob, owner['header'] + 8, owner['size'] + grow)
    vfe = parsed.pointer('P', 0x20)
    blob[vfe:vfe + 14] = HEADER
    variables, equations = vfe + 14, vfe + 14 + 29 * 255
    for i in range(255):
        entry = (TEMPLATE if i in (4, 5) else bytes((1,)) + bytes(28) if i < 20 else FREE_VARIABLE)
        blob[variables + 29 * i:variables + 29 * i + 29] = entry
    for i in range(16, 2048):
        blob[equations + 25 * i:equations + 25 * i + 25] = vfe_free_slot(25)
    for i in (10, 12, 13, 14, 15):
        blob[equations + 25 * i:equations + 25 * i + 25] = UNUSED_CONSTANT
    blob[p['end'] - 1] = 0
    return repair(blob)


def patched(blob, at, data):
    blob = bytearray(blob)
    blob[at:at + len(data)] = data
    return repair(blob)


def evaluated(blob):
    """Per present slot word, the evaluated range of the equation it selects (vfe_range), with every runtime hook
    variable at 0 (the variables of the type-1 equations the words select directly)."""
    variables, equations, count, _, _ = tables(blob)
    result = []
    for at in slot_words(blob):
        index = word(blob, at)
        e = blob[equations + 25 * index:equations + 25 * index + 25]
        zero = {e[1]: 0.0} if e[0] == 1 and e[3:23] == BODY else {}
        result.append(vfe_range(blob, equations, 25, 2, count, index, clamped_children=True, variables=zero))
    return result


def stable_fields(image):
    return {k: (f['current'], f['editable'], f['bounds']) for k, f in descriptors(image).items() if k not in HOOK_AFFECTED}


def check_installed(test, before, after):
    """The layout and its invariants on `after`, installed on `before`: hooks in the first unused entries in word
    order, unused entries one end block, each hook named once and linked by nothing, no other equation reading a
    hook variable, the original equations and stock template variables untouched, valid integrity, and no other
    byte changed but the hashes, digests and checksums."""
    variables, equations, count, _, _ = tables(after)
    free_v = [i for i in range(255) if not before[variables + 29 * i]]
    free_e = [i for i in range(count) if not before[equations + 25 * i]]
    templates = [i for i in range(255) if before[variables + 29 * i:variables + 29 * i + 29] == TEMPLATE]
    words = slot_words(before)
    hooks, used, allowed = [], [], set()
    for k, at in enumerate(words):
        old, var, hook = word(before, at), free_v[k], free_e[k]
        test.assertEqual(word(after, at), hook)
        test.assertEqual(after[equations + 25 * hook:equations + 25 * hook + 25],
                         bytes((1, var, old & 0xFF)) + BODY + bytes((2, old >> 8)))
        test.assertEqual(after[variables + 29 * var:variables + 29 * var + 29], TEMPLATE)
        test.assertEqual(after[equations + 25 * old:equations + 25 * old + 25],
                         before[equations + 25 * old:equations + 25 * old + 25])
        hooks.append(hook)
        used.append(var)
        allowed |= set(range(at, at + 2)) | set(range(variables + 29 * var, variables + 29 * var + 29))
        allowed |= set(range(equations + 25 * hook, equations + 25 * hook + 25))
    after_v = [i for i in range(255) if not after[variables + 29 * i]]
    after_e = [i for i in range(count) if not after[equations + 25 * i]]
    test.assertEqual((after_v, after_e), (free_v[len(words):], free_e[len(words):]))
    test.assertEqual(after_v, list(range(255 - len(after_v), 255)))
    test.assertEqual(after_e, list(range(count - len(after_e), count)))
    _, _, _, rail, rows = tables(after)
    named = [word(after, rail + 5 + 65 * r + k) for r in range(rows) for k in ROW_WORDS]
    linked = [x for i in range(count) for x in links(after[equations + 25 * i:equations + 25 * i + 25])]
    readers = [i for i in range(count) if i not in hooks and after[equations + 25 * i] and
               after[equations + 25 * i + 1] in used]
    test.assertEqual(([named.count(h) for h in hooks], [h for h in hooks if h in linked], readers),
                     ([1] * len(hooks), [], []))
    test.assertTrue(templates and not set(templates) & set(used))
    for t in templates:
        test.assertEqual(after[variables + 29 * t:variables + 29 * t + 29], TEMPLATE)
    parsed = BlackwellRom(after)
    test.assertTrue(parsed.integrity()['valid'] and parsed.legacy_valid())
    for objects, directory in ((parsed.objects, parsed.directory), (parsed.legacy_objects, parsed.legacy_directory)):
        allowed |= {at for o in objects for at in range(o['hash_offset'], o['hash_offset'] + 48)}
        allowed |= set(range(directory['digest_offset'], directory['digest_offset'] + 48))
    allowed |= {end - 1 for _, end in list(parsed.image_regions) + [(parsed.legacy['start'], parsed.legacy['end'])]}
    test.assertLessEqual({i for i, (a, b) in enumerate(zip(before, after)) if a != b}, allowed)


def removed(test, image):
    """The bytes install then removal gives on `image`: the same, but where an unused variable the hooks take holds
    leftover bytes (runtime_hooks dirty; the RTX PRO 6000 Max-Q images), which removal makes the clean ones."""
    dirty = backend(image).runtime_hooks()['dirty']
    if not dirty:
        return image.blob
    variables = tables(image.blob)[0]
    test.assertTrue(all(entry.startswith('variable ') for entry in dirty))
    expected = bytearray(image.blob)
    for var in (int(entry.split()[1]) for entry in dirty):
        test.assertEqual(image.blob[variables + 29 * var], 0)
        expected[variables + 29 * var:variables + 29 * var + 29] = FREE_VARIABLE
    return repair(expected)


def check_evaluated(test, before, after):
    """Every limit evaluates the same with the hook variables at 0, and a hook adds its variable (clamped to
    +-1.25 V) to a constant limit."""
    test.assertEqual(evaluated(before), evaluated(after))
    variables, equations, count, _, _ = tables(after)
    for at, span in zip(slot_words(before), evaluated(before)):
        hook = word(after, at)
        var = after[equations + 25 * hook + 1]
        if span is None or span[0] != span[1]:
            continue
        for offset, added in ((-50000, -50000), (75000, 75000), (2000000, 1250000), (-3000000, -1250000)):
            test.assertEqual(vfe_range(after, equations, 25, 2, count, hook, clamped_children=True,
                                       variables={var: offset}), (span[0] + added, span[1] + added))


class RuntimeVoltageOffsetTests(unittest.TestCase):
    def setUp(self):
        self.stock = from_bytes(hooks_fixture())

    def test_switch_installs_the_layout_and_removal_gives_back_stock(self):
        field = descriptors(self.stock)['runtime_voltage_offsets']
        self.assertEqual((field['current'], field['editable'], field['opt_in'], field['experimental']),
                         (0, True, True, True))
        self.assertEqual((field['bounds']['minimum'], field['bounds']['maximum']), (0, 1))
        for text in ('mVolt+-compatible', 'clamped to +-1.25 V', 'nothing changes', 'not hardware-tested'):
            self.assertIn(text, field['reason'])
        hooked = edit(self.stock, {'runtime_voltage_offsets': 1})
        check_installed(self, self.stock.blob, hooked.blob)
        check_evaluated(self, self.stock.blob, hooked.blob)
        self.assertEqual(hooked.blob, mvolt_style(self.stock.blob))
        after = descriptors(hooked.image)['runtime_voltage_offsets']
        self.assertEqual((after['current'], after['editable']), (1, True))
        hooks = after['runtime_hooks']
        self.assertEqual((hooks['state'], hooks['reference_variable'], hooks['limit_uv']), ('on', 4, 1250000))
        self.assertEqual([(s['rail'], s['role'], s['word'], s['hook'], s['variable'], s['target']) for s in hooks['slots']],
                         [('NVVDD', 'REL', 16, 16, 20, 0), ('NVVDD', 'ALT', 17, 17, 21, 1),
                          ('NVVDD', 'OV', 18, 18, 22, 2), ('NVVDD', 'VMIN', 19, 19, 23, 8),
                          ('MSVDD', 'REL', 20, 20, 24, 4), ('MSVDD', 'ALT', 21, 21, 25, 5),
                          ('MSVDD', 'OV', 22, 22, 26, 6), ('MSVDD', 'VMIN', 23, 23, 27, 9)])
        self.assertEqual(stable_fields(self.stock), stable_fields(hooked.image))
        back = edit(hooked.image, {'runtime_voltage_offsets': 0})
        self.assertEqual(back.blob, self.stock.blob)
        # The same value again changes nothing.
        self.assertEqual(edit(hooked.image, {'runtime_voltage_offsets': 1}).blob, hooked.blob)

    def test_voltage_fields_follow_the_hooks(self):
        hooked = edit(self.stock, {'runtime_voltage_offsets': 1}).image
        before, after = descriptors(self.stock), descriptors(hooked)
        rel = after['nvvdd_rel_equation_max_mv']
        self.assertEqual(rel['selector']['raw'], 0)
        self.assertEqual(rel['selector']['runtime_hook']['hook'], 16)
        self.assertEqual(rel['equation_offset'], before['nvvdd_rel_equation_max_mv']['equation_offset'])
        self.assertNotIn('runtime_hook', before['nvvdd_rel_equation_max_mv']['selector'])
        # Every voltage field of a hooked word names the hook in its selector, raw the equation it links.
        for key, raw, stored in (('nvvdd_rel_equation_min_mv', 0, 16), ('nvvdd_rel_selector_index', 0, 16),
                                 ('nvvdd_vmin_mv', 8, 19), ('msvdd_vmin_mv', 9, 23), ('msvdd_ov_equation_max_mv', 6, 22)):
            selector = after[key]['selector']
            self.assertEqual((selector['raw'], selector['runtime_hook']['word'], selector['runtime_hook']['target']),
                             (raw, stored, raw), key)
            self.assertEqual(word(hooked.blob, selector['offset']), stored, key)
            self.assertNotIn('runtime_hook', before[key]['selector'], key)
        for key in ('nvvdd_rel_equation_max_mv', 'nvvdd_rel_equation_min_mv', 'nvvdd_ov_equation_max_mv',
                    'nvvdd_vmin_mv', 'msvdd_vmin_mv', 'nvvdd_rel_max_mv'):
            self.assertEqual((after[key]['current'], after[key]['editable']),
                             (before[key]['current'], before[key]['editable']), key)
        # A value on the hooked copy writes the original equation, as on the stock image.
        for change in ({'nvvdd_vmin_mv': 850}, {'nvvdd_rel_equation_max_mv': 1100, 'nvvdd_rel_equation_min_mv': 950}):
            on_stock = edit(self.stock, change)
            on_hooked = edit(hooked, change)
            self.assertEqual([e['offset'] for e in on_stock.manifest['edits']],
                             [e['offset'] for e in on_hooked.manifest['edits']])
            self.assertEqual(edit(on_hooked.image, {'runtime_voltage_offsets': 0}).blob, on_stock.blob)

    def test_order_of_edits_does_not_matter(self):
        values = {'nvvdd_rel_equation_max_mv': 1125, 'nvvdd_rel_equation_min_mv': 1100, 'nvvdd_vmin_mv': 850}
        together = edit(self.stock, dict(values, runtime_voltage_offsets=1)).blob
        values_first = edit(edit(self.stock, values).image, {'runtime_voltage_offsets': 1}).blob
        switch_first = edit(edit(self.stock, {'runtime_voltage_offsets': 1}).image, values).blob
        self.assertEqual(together, values_first)
        self.assertEqual(together, switch_first)
        undone = edit(from_bytes(together), {'runtime_voltage_offsets': 0}).blob
        self.assertEqual(undone, edit(self.stock, values).blob)

    def test_follow_ov_and_first_slot_fields_change_apart(self):
        hooked = edit(self.stock, {'runtime_voltage_offsets': 1}).image
        follow = descriptors(hooked)['nvvdd_rel_alt_follow_ov']
        self.assertEqual((follow['current'], follow['editable'], follow['reason']), (0, False, FOLLOW_OV_HOOKS_REASON))
        with self.assertRaises(VbiosError) as exc:
            edit(self.stock, {'runtime_voltage_offsets': 1, 'nvvdd_rel_alt_follow_ov': 1})
        self.assertEqual(exc.exception.code, 'SEPARATE_EDIT_REQUIRED')
        # A field requested at its current value does not count.
        self.assertEqual(edit(self.stock, {'runtime_voltage_offsets': 1, 'nvvdd_rel_alt_follow_ov': 0}).blob,
                         edit(self.stock, {'runtime_voltage_offsets': 1}).blob)
        # REL and ALT following OV select one equation: each word gets its own hook linking it, as mVolt+ installs.
        followed = edit(self.stock, {'nvvdd_rel_alt_follow_ov': 1}).image
        field = descriptors(followed)['runtime_voltage_offsets']
        self.assertEqual((field['current'], field['editable']), (0, True))
        on = edit(followed, {'runtime_voltage_offsets': 1})
        check_installed(self, followed.blob, on.blob)
        check_evaluated(self, followed.blob, on.blob)
        self.assertEqual(on.blob, mvolt_style(followed.blob))
        hooks = descriptors(on.image)['runtime_voltage_offsets']['runtime_hooks']
        self.assertEqual([s['target'] for s in hooks['slots'][:3]], [word(followed.blob, at) for at in
                                                                     slot_words(followed.blob)[:3]])
        self.assertEqual(len({s['target'] for s in hooks['slots'][:3]}), 1)
        self.assertEqual(descriptors(on.image)['nvvdd_rel_alt_follow_ov']['current'], 1)
        self.assertEqual(edit(on.image, {'runtime_voltage_offsets': 0}).blob, followed.blob)

    def test_words_that_share_an_equation_get_one_hook_each(self):
        variables, equations, count, rail, _ = tables(self.stock.blob)
        # NVVDD ALT and OV on the REL equation, as the vendor XOC images select one equation for the three.
        shared = patched(patched(self.stock.blob, rail + 5 + 0x0F, struct.pack('<H', 0)), rail + 5 + 0x11,
                         struct.pack('<H', 0))
        image = from_bytes(shared)
        field = descriptors(image)['runtime_voltage_offsets']
        self.assertEqual((field['current'], field['editable']), (0, True))
        on = edit(image, {'runtime_voltage_offsets': 1})
        check_installed(self, shared, on.blob)
        check_evaluated(self, shared, on.blob)
        self.assertEqual(on.blob, mvolt_style(shared))
        slots = descriptors(on.image)['runtime_voltage_offsets']['runtime_hooks']['slots']
        self.assertEqual([(s['hook'], s['variable'], s['target']) for s in slots[:3]],
                         [(16, 20, 0), (17, 21, 0), (18, 22, 0)])
        self.assertEqual(edit(on.image, {'runtime_voltage_offsets': 0}).blob, shared)

    def test_words_past_the_equation_table_are_skipped(self):
        variables, equations, count, rail, _ = tables(self.stock.blob)
        # The MSVDD VMIN word names no equation (0x0900 >= 2048): no slot there, as for mVolt+.
        outside = patched(self.stock.blob, rail + 5 + 65 + 0x13, struct.pack('<H', 0x0900))
        image = from_bytes(outside)
        self.assertEqual(len(backend(image).runtime_hooks()['slots']), 7)
        on = edit(image, {'runtime_voltage_offsets': 1})
        check_installed(self, outside, on.blob)
        self.assertEqual(on.blob, mvolt_style(outside))
        self.assertEqual(word(on.blob, rail + 5 + 65 + 0x13), 0x0900)
        made = descriptors(from_bytes(mvolt_style(outside)))['runtime_voltage_offsets']
        self.assertEqual((made['current'], made['editable'], made['runtime_hooks']['state']), (1, True, 'on'))
        self.assertEqual(edit(on.image, {'runtime_voltage_offsets': 0}).blob, outside)

    def test_mvolt_made_hooks_read_on(self):
        made = from_bytes(mvolt_style(self.stock.blob))
        field = descriptors(made)['runtime_voltage_offsets']
        self.assertEqual((field['current'], field['editable']), (1, True))
        self.assertEqual(edit(made, {'runtime_voltage_offsets': 0}).blob, self.stock.blob)
        # Shared equations, as an mVolt+ install on a ROM whose REL and ALT follow OV: read 1, and removable.
        followed = edit(self.stock, {'nvvdd_rel_alt_follow_ov': 1}).image
        shared = from_bytes(mvolt_style(followed.blob))
        fields = descriptors(shared)
        self.assertEqual((fields['runtime_voltage_offsets']['current'], fields['runtime_voltage_offsets']['editable']),
                         (1, True))
        self.assertEqual(fields['nvvdd_rel_alt_follow_ov']['current'], 1)
        self.assertEqual(edit(shared, {'runtime_voltage_offsets': 0}).blob, followed.blob)

    def test_partial_or_foreign_hooks_are_read_only(self):
        made = mvolt_style(self.stock.blob)
        parsed = BlackwellRom(made)
        variables, equations, count, rail, _ = tables(made)
        nvvdd = rail + 5
        hook = equations + 25 * 16
        cases = {
            # One word back on its original equation.
            'partial': patched(made, nvvdd + 0x0D, struct.pack('<H', 0)),
            # A hook variable that is not the template.
            'variable': patched(made, variables + 29 * 20 + 9, b'\x06'),
            # Another equation links a hook.
            'linked': patched(made, equations + 25 * 10, bytes((1, 14, 16)) + bytes(20) + bytes((2, 0))),
            # Another rail row word names a hook.
            'named': patched(made, nvvdd + 0x15, struct.pack('<H', 16)),
            # A hook with another slope.
            'slope': patched(made, hook + 15, struct.pack('<f', 2.0)),
        }
        for name, blob in cases.items():
            with self.subTest(name):
                image = from_bytes(blob)
                hooks = backend(image).runtime_hooks()
                self.assertEqual(hooks['state'], 'partial', hooks)
                fields = descriptors(image)
                self.assertEqual((fields['runtime_voltage_offsets']['current'],
                                  fields['runtime_voltage_offsets']['editable']), (None, False))
                self.assertIn('incomplete or foreign set of hooks', fields['runtime_voltage_offsets']['reason'])
                # The voltage fields of a word that selects a hook-shaped equation stay read-only.
                if name != 'partial':
                    self.assertFalse(fields['nvvdd_rel_equation_max_mv']['editable'])
                    self.assertIn(HOOK_PARTIAL_DIAGNOSTIC, fields['nvvdd_rel_equation_max_mv']['reason'])
                    self.assertNotIn('nvvdd_rel_max_mv', fields)
                self.assertFalse(fields['msvdd_ov_equation_max_mv']['editable'])
                self.assertFalse(fields['nvvdd_rel_alt_follow_ov']['editable'])
        self.assertEqual(parsed.runtime_hooks()['state'], 'on')

    def test_install_refusals(self):
        blob = self.stock.blob
        variables, equations, count, rail, _ = tables(blob)
        used = UNUSED_CONSTANT
        crowded, no_template = bytearray(blob), bytearray(blob)
        for i in range(16, 2043):
            crowded[equations + 25 * i:equations + 25 * i + 25] = used
        for i in (4, 5):
            no_template[variables + 29 * i:variables + 29 * i + 29] = bytes((1,)) + bytes(28)
        # Another VFE header: runtime tools would not accept the hooks, and the switch is not offered.
        other = from_bytes(patched(blob, backend(self.stock).pointer('P', 0x20) + 13, b'\x21'))
        self.assertNotIn('runtime_voltage_offsets', descriptors(other))
        self.assertFalse(backend(other).runtime_hooks()['layout'])
        cases = {
            'hole': (patched(blob, equations + 25 * 100, used), 'one block at the end'),
            'room': (repair(crowded), 'need 8 of each'),
            'template': (repair(no_template), 'no stock template variable'),
            'unused target': (patched(blob, rail + 5 + 0x0F, struct.pack('<H', 1000)), 'no equation in use'),
            'reader': (patched(blob, equations + 25 * 10, bytes((1, 20, 0xFF)) + bytes(20) + bytes((2, 0xFF))),
                       'named by an equation'),
        }
        for name, (case, text) in cases.items():
            with self.subTest(name):
                field = descriptors(from_bytes(case))['runtime_voltage_offsets']
                self.assertEqual((field['current'], field['editable']), (0, False))
                self.assertIn(text, field['reason'])
        # Another table that names equations (clock programming, FLL, voltage policy, P+0x104) names the first unused
        # equation, or cannot be read: the hooks would be named twice, or that cannot be ruled out.
        for name, names, text in (('named', lambda self: {16: ['P+0x104']}, 'named by the P+0x104 table'),
                                  ('unreadable', mock.Mock(side_effect=FormatError('the table at P+0x104 has an '
                                                                                   'unreviewed layout')),
                                   'cannot be ruled out')):
            with self.subTest(name), mock.patch.object(BlackwellRom, 'equation_index_names', names):
                field = descriptors(from_bytes(blob))['runtime_voltage_offsets']
                self.assertEqual((field['current'], field['editable']), (0, False))
                self.assertIn(text, field['reason'])

    def test_removal_waits_for_later_entries(self):
        hooked = edit(self.stock, {'runtime_voltage_offsets': 1}).blob
        variables, equations, count, _, _ = tables(hooked)
        later = patched(hooked, equations + 25 * 24, bytes((1, 14, 0xFF)) + bytes(20) + bytes((2, 0xFF)))
        field = descriptors(from_bytes(later))['runtime_voltage_offsets']
        self.assertEqual((field['current'], field['editable']), (1, False))
        self.assertIn('set it back first', field['reason'])

    def test_gui_texts(self):
        es, en = Messages('es'), Messages('en')
        # A partial set and a removal that waits read their own texts; other refusals the switch's generic one.
        partial = descriptors(from_bytes(patched(mvolt_style(self.stock.blob), tables(self.stock.blob)[3] + 5 + 0x0D,
                                                 struct.pack('<H', 0))))
        hooked = edit(self.stock, {'runtime_voltage_offsets': 1}).blob
        later = descriptors(from_bytes(patched(hooked, tables(hooked)[1] + 25 * 24,
                                               bytes((1, 14, 0xFF)) + bytes(20) + bytes((2, 0xFF)))))
        hole = descriptors(from_bytes(patched(self.stock.blob, tables(self.stock.blob)[1] + 25 * 100,
                                              UNUSED_CONSTANT)))
        for fields, key in ((partial, 'reason.runtime_offsets_partial'), (later, 'reason.runtime_offsets_remove_waits'),
                            (hole, 'reason.runtime_offsets_blocked')):
            field = fields['runtime_voltage_offsets']
            self.assertFalse(field['editable'])
            self.assertEqual(read_only_reason(field, 'es'), es(key))
            self.assertEqual(read_only_reason(field, 'en'), field['reason'] if key.endswith('blocked') else en(key))
        follow = descriptors(from_bytes(hooked))['nvvdd_rel_alt_follow_ov']
        self.assertEqual(read_only_reason(follow, 'es'), es('reason.follow_ov_hooks'))
        self.assertNotIn('ALT', FOLLOW_OV_HOOKS_REASON)
        # Leftover bytes in an unused entry the hooks take: the descriptor lists it and the row notes it.
        variables = tables(self.stock.blob)[0]
        leftover = descriptors(from_bytes(patched(self.stock.blob, variables + 29 * 20 + 9, b'\x00')))
        field = leftover['runtime_voltage_offsets']
        self.assertEqual((field['editable'], field['runtime_hooks']['dirty']), (True, ['variable 20']))
        self.assertEqual(runtime_offsets_notes(field, 'es'),
                         [es('runtime_offsets.note'), es('runtime_offsets.dirty', entries='variable 20')])
        clean = descriptors(self.stock)['runtime_voltage_offsets']
        self.assertEqual((clean['runtime_hooks']['dirty'], runtime_offsets_notes(clean, 'en')),
                         ([], [en('runtime_offsets.note')]))

    def test_hook_bytes_change_only_through_the_switch(self):
        hooked = edit(self.stock, {'runtime_voltage_offsets': 1}).image
        _, equations, _, _, _ = tables(hooked.blob)
        clamp = equations + 25 * 16 + 7
        probe = custom_registry('probe', [clamp], encoding='<f', scale=1, bounds={'minimum': 0, 'maximum': 2e6})
        with self.assertRaises(VbiosError) as exc:
            edit(hooked, {'probe': 1300000}, field_registry=probe)
        self.assertEqual(exc.exception.code, 'PRESERVED_FIELD_CHANGED')

    def test_other_families_do_not_offer_the_switch(self):
        for name, blob in (('ada', synthetic_rom()), ('ampere', synthetic_rom(family='ampere')),
                           ('turing', synthetic_turing())):
            with self.subTest(name):
                self.assertNotIn('runtime_voltage_offsets', descriptors(from_bytes(blob)))


if __name__ == '__main__':
    unittest.main()
