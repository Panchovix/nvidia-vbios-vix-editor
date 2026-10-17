"""Closed Ada runtime representation: no enrollment, GPU calls or ROM publication."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_rom_formats import synthetic_rom, synthetic_blackwell
from nvidia_vbios.editor import edit, FieldRegistry
from nvidia_vbios.rom import VbiosError, from_bytes, inspect_image, load, normalize
from nvidia_vbios.rom.image import backend
from nvidia_vbios.rom import ada_relocated as A, ada_general as G, _ada_relocation as recipe

ROOT = Path(__file__).resolve().parents[1]


class RelocationScopeTests(unittest.TestCase):
    def test_ordinary_normalization_and_editing_remain_unchanged(self):
        image = from_bytes(synthetic_rom(copies=2))
        before = normalize(image)
        self.assertEqual(before.blob, image.blob[512:11776])
        self.assertEqual(normalize(before).blob, before.blob)
        self.assertTrue(inspect_image(image)['capabilities']['edit']['status'] == 'supported')
        self.assertTrue(edit(image, {'power_min_w': 1}).manifest['integrity']['valid'])
        blackwell = from_bytes(synthetic_blackwell())
        self.assertIs(normalize(blackwell), blackwell)
        with self.assertRaises(VbiosError) as exc:
            normalize(blackwell, representation=A.REPRESENTATION)
        self.assertEqual(exc.exception.code, 'UNREVIEWED_RELOCATION_SOURCE')

    def test_explicit_selector_rejects_unreviewed_source_and_unknown_names(self):
        image = from_bytes(synthetic_rom())
        with self.assertRaises(VbiosError) as exc:
            normalize(image, representation=A.REPRESENTATION)
        self.assertEqual(exc.exception.code, 'UNREVIEWED_RELOCATION_SOURCE')
        for name in ('ada-relocated-v3', 'raw', '', {'name': A.REPRESENTATION}):
            with self.subTest(name=name), self.assertRaises(VbiosError) as exc:
                normalize(image, representation=name)
            self.assertEqual(exc.exception.code, 'UNKNOWN_REPRESENTATION')
        with self.assertRaises(VbiosError) as exc:
            normalize(b'not BiosImage', representation=A.REPRESENTATION)
        self.assertEqual(exc.exception.code, 'INVALID_IMAGE')

    def test_generic_no_efi_chains_remain_unsupported_even_with_correct_checksums(self):
        source = synthetic_rom()
        # Remove the intact EFI image. Remaining bounded images keep their checksums.
        blob = source[:512 + 2048] + source[512 + 2560:]
        image = from_bytes(blob, 'ada-relocated-v1.rom')
        report = inspect_image(image)
        self.assertTrue(all(item['checksum'] == 0 for item in report['integrity']['image_checksums']))
        self.assertIsNone(report['format'])
        self.assertIsNot(report['integrity']['valid'], True)
        self.assertEqual(report['capabilities']['normalize']['status'], 'unsupported')
        for representation in (None, A.REPRESENTATION):
            with self.subTest(representation=representation), self.assertRaises(VbiosError):
                normalize(image, representation=representation)
        with self.assertRaises(VbiosError):
            backend(image)

    def test_experimental_general_selector_refuses_unverifiable_sources_cleanly(self):
        for blob, code in ((synthetic_rom(), 'RELOCATION_VERIFICATION_FAILED'),
                           (synthetic_rom(copies=2), 'RELOCATION_VERIFICATION_FAILED'),
                           (synthetic_rom(family='ampere'), 'UNREVIEWED_RELOCATION_SOURCE'),
                           (synthetic_blackwell(), 'UNREVIEWED_RELOCATION_SOURCE')):
            with self.subTest(code=code, size=len(blob)), self.assertRaises(VbiosError) as exc:
                normalize(from_bytes(blob), representation=G.REPRESENTATION)
            self.assertEqual(exc.exception.code, code)

    def test_signature_rule_tolerates_only_preexisting_headerless_signatures(self):
        view = bytearray(0x1000)
        view[0x400:0x402] = b'\x55\xaa'                    # pre-existing, no PCIR header
        new = bytearray(view)
        self.assertEqual(recipe.unexpected_signatures(view, new, (), True), ([], [0x400]))
        self.assertEqual(recipe.unexpected_signatures(view, new, (), False), ([0x400], []))
        new[0x600:0x602] = b'\x55\xaa'                     # new in the relocated view
        self.assertEqual(recipe.unexpected_signatures(view, new, (), True), ([0x600], [0x400]))
        for side in ('source', 'relocated'):                # a PCI image is never tolerated
            source, relocated = bytearray(view), bytearray(view)
            pci = source if side == 'source' else relocated
            pci[0x418], pci[0x420:0x424] = 0x20, b'PCIR'
            with self.subTest(side=side):
                self.assertEqual(recipe.unexpected_signatures(source, relocated, (), True), ([0x400], []))
        vn = bytearray(view)
        vn[0x400:0x402] = b'VN'                             # VN: only inside the legacy image (before 0x800)
        self.assertEqual(recipe.unexpected_signatures(vn, vn, (), True), ([0x400], []))
        self.assertEqual(recipe.unexpected_signatures(vn, vn, (0x400,), True), ([], []))
        self.assertEqual(recipe.unexpected_signatures(vn, vn, (0x800,), True), ([], [0x400]))
        self.assertEqual(recipe.unexpected_signatures(vn, vn, (0x800,), False), ([0x400], []))
        self.assertEqual(recipe.unexpected_signatures(vn, vn, (0x200,), True), ([0x400], []))
        self.assertEqual(recipe.unexpected_signatures(view, vn, (0x800,), True), ([0x400], []))
        for name in (b'NPDS', b'PCIR'):                     # a header behind it is never tolerated
            for side in ('source', 'relocated'):
                source, relocated = bytearray(vn), bytearray(vn)
                image = source if side == 'source' else relocated
                image[0x418], image[0x420:0x424] = 0x20, name
                with self.subTest(header=name, side=side):
                    self.assertEqual(recipe.unexpected_signatures(source, relocated, (0x800,), True), ([0x400], []))

    def test_recognition_has_no_name_size_or_caller_registry_shortcut(self):
        impostor = from_bytes(bytes(A.PAYLOAD_SIZE), A.REPRESENTATION)
        self.assertIsNone(A.recognize_payload(impostor.blob))
        self.assertIsNone(inspect_image(impostor)['format'])
        self.assertEqual(A.PAYLOAD_SIZE - A.HOST_SKIP, A.GSP_BYTES)
        self.assertLessEqual(A.GSP_BYTES, 512 * 1024)
        self.assertGreater(A.PAYLOAD_SIZE, 512 * 1024)


if __name__ == '__main__':
    unittest.main()
