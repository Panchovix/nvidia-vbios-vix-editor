"""Unit tests for Volta (GV100) architecture recognition, tables, and memory parsing."""
import os
from pathlib import Path
import unittest

from nvidia_vbios.editor import edit
from nvidia_vbios.families import architecture
from nvidia_vbios.rom import from_bytes, inspect_image, load
from nvidia_vbios.rom.image import metadata, backend
from nvidia_vbios.rom.memory import memory_report, TYPES
from nvidia_vbios.rom.tables import TableRom, VOLTA_POWER_VARIANTS, VOLTA_EDITED_TABLES


class VoltaArchitectureTests(unittest.TestCase):
    def test_volta_device_ids_in_scope(self):
        v100_pcie_32gb = architecture(0x1DB6, ('88.00.7E.00.03',), editor=True)
        self.assertEqual(v100_pcie_32gb['family'], 'volta')
        self.assertEqual(v100_pcie_32gb['product'], 'NVIDIA Tesla V100-PCIE-32GB')
        self.assertTrue(v100_pcie_32gb['in_scope'])
        self.assertTrue(v100_pcie_32gb['bios_family_consistent'])

        v100s_pcie_32gb = architecture(0x1DF6, ('88.00.98.00.01',), editor=True)
        self.assertEqual(v100s_pcie_32gb['family'], 'volta')
        self.assertEqual(v100s_pcie_32gb['product'], 'NVIDIA Tesla V100S-PCIE-32GB')
        self.assertTrue(v100s_pcie_32gb['in_scope'])
        self.assertTrue(v100s_pcie_32gb['bios_family_consistent'])

        titan_v = architecture(0x1D81, ('88.00.4F.00.01',), editor=True)
        self.assertEqual(titan_v['family'], 'volta')
        self.assertEqual(titan_v['product'], 'NVIDIA TITAN V')
        self.assertTrue(titan_v['in_scope'])
        self.assertTrue(titan_v['bios_family_consistent'])

    def test_hbm2_memory_type(self):
        self.assertEqual(TYPES.get(6), 'HBM2')

    def test_volta_power_variants(self):
        self.assertIn((0x30, 0x27, 0x36), VOLTA_POWER_VARIANTS)
        self.assertEqual(VOLTA_EDITED_TABLES, (('P', 0x00), ('P', 0x2C)))


class VoltaRomCorpusTests(unittest.TestCase):
    def setUp(self):
        self.rom_candidates = [
            Path('.roms/g500_0212_907_ab__8800980001.rom'),
            Path('.roms/284099.rom'),
            Path('.roms/V100_32GB_to_V100S_300W.rom')
        ]
        self.available_roms = [p for p in self.rom_candidates if p.exists()]

    def test_volta_rom_parsing_if_available(self):
        if not self.available_roms:
            self.skipTest("No local Volta ROMs found in .roms/")
        for rom_path in self.available_roms:
            with self.subTest(rom=rom_path.name):
                img = load(rom_path)
                info = inspect_image(img)
                self.assertEqual(info['architecture']['family'], 'volta')
                self.assertTrue(info['architecture']['in_scope'])
                self.assertTrue(info['architecture']['bios_family_consistent'])
                self.assertTrue(info['integrity']['valid'])

                # Verify memory parsing
                mem = memory_report(img)
                self.assertEqual(mem['configurations']['status'], 'recognized')
                self.assertEqual(mem['bands']['status'], 'recognized')
                self.assertEqual(mem['timings']['status'], 'recognized')
                types = [item.get('type') for item in mem['configurations']['items']]
                self.assertIn('HBM2', types)

                # Verify fields
                field_keys = {f['key'] for f in info['fields']}
                self.assertIn('power_max_w', field_keys)
                self.assertIn('hbm2_target_mhz', field_keys)

    def test_volta_hbm2_target_toggle(self):
        v100_path = Path('.roms/V100_32GB_backup.rom')
        modded_path = Path('.roms/V100_32GB_to_V100S_300W.rom')
        if not v100_path.exists():
            self.skipTest("V100_32GB_backup.rom not found in .roms/")
        v100 = load(v100_path)
        res_1107 = edit(v100, {'hbm2_target_mhz': 1107, 'power_max_w': 300})
        if modded_path.exists():
            self.assertEqual(res_1107.blob, modded_path.read_bytes())
        res_877 = edit(res_1107.image, {'hbm2_target_mhz': 877, 'power_max_w': 250})
        self.assertEqual(res_877.blob, v100.blob)


if __name__ == '__main__':
    unittest.main()
