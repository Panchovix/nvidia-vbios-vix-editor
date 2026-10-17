import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_rom_formats import synthetic_rom
from nvidia_vbios.rom import BiosImage, VbiosError, from_bytes, inspect_image, load, normalize
from nvidia_vbios.editor import edit, plan, save, Binding, FieldRegistry
from nvidia_vbios.editor import api
from nvidia_vbios.editor.registry import power


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.image = from_bytes(synthetic_rom(copies=2))

    def test_immutable_staging_revert_defaults_coefficients_identity(self):
        original = self.image.blob
        staged = edit(self.image, {'power_max_w': 100, 'nvvdd_rel_max_mv': 1100})
        self.assertEqual(self.image.blob, original)
        capabilities = inspect_image(staged.image)['capabilities']
        self.assertEqual(capabilities['vbios']['writable'], 'verified')
        self.assertIn('power_max_w', capabilities['vbios']['editable_fields'])
        self.assertEqual(capabilities['runtime']['applied'], 'unknown')
        self.assertIsNone(capabilities['runtime']['evaluated_values'])
        self.assertTrue(inspect_image(staged.image)['integrity']['valid'])
        self.assertEqual(staged.image.blob[-16:], original[-16:])
        before = {f['key']: f for f in staged.manifest['before']['fields']}
        after = {f['key']: f for f in staged.manifest['after']['fields']}
        self.assertEqual(after['power_max_w']['factory_default'], 70)
        self.assertEqual(after['nvvdd_rel_max_mv']['equation_coefficients'],
                         before['nvvdd_rel_max_mv']['equation_coefficients'])
        reverted = edit(staged.image, {'power_max_w': 70, 'nvvdd_rel_max_mv': 955})
        self.assertEqual(reverted.blob, original)
        self.assertEqual(normalize(staged.image).blob, staged.image.blob[512:11776])
        json.dumps(staged.manifest, allow_nan=False)

    def test_plan_builds_same_verified_bytes_without_writes(self):
        changes = {'power_max_w': 100}
        self.assertEqual(plan(self.image, changes).blob, edit(self.image, changes).blob)
        self.assertEqual(plan(self.image, changes).manifest['operation'], 'plan')
        self.assertEqual(edit(self.image, {}).manifest['changed_bytes'], 0)

    def test_single_rail_and_unknown_current_ocp_memory_refusals(self):
        for field in ('msvdd_rel_max_mv', 'ocp_limit_a', 'current_limit_a', 'nvvdd_ov_equation_max_mv',
                      'nvvdd_vmin_equation_max_mv'):
            with self.subTest(field=field), self.assertRaises(VbiosError) as exc:
                edit(self.image, {field: 1000})
            self.assertEqual(exc.exception.code, 'FIELD_READ_ONLY')
        with self.assertRaises(VbiosError) as exc:
            edit(self.image, {'made_up': 1})
        self.assertEqual(exc.exception.code, 'UNKNOWN_FIELD')
        self.assertEqual(exc.exception.to_dict()['schema_version'], 1)

    def test_nonfinite_inexact_boolean_and_default_lower_bound(self):
        cases = ((True, 'INVALID_VALUE'), ('nan', 'INVALID_VALUE'), ('inf', 'INVALID_VALUE'),
                 ('100.0001', 'UNREPRESENTABLE_VALUE'), (69, 'OUT_OF_BOUNDS'))
        for value, code in cases:
            with self.subTest(value=value), self.assertRaises(VbiosError) as exc:
                edit(self.image, {'power_max_w': value})
            self.assertEqual(exc.exception.code, code)
        with self.assertRaises(VbiosError) as exc:
            edit(self.image, {'nvvdd_rel_max_mv': '17000.001'})
        self.assertEqual(exc.exception.code, 'UNREPRESENTABLE_VALUE')

    def test_one_duplicate_copy_corruption_refuses_edits(self):
        blob = bytearray(self.image.blob)
        blob[12288 + 512 + 5300] ^= 1
        with self.assertRaises(VbiosError) as exc:
            edit(from_bytes(blob), {'power_max_w': 100})
        self.assertEqual(exc.exception.code, 'INTEGRITY_FAILED')

    def test_unrecognized_rom_edit_refusal_has_typed_error(self):
        with self.assertRaises(VbiosError) as exc:
            edit(from_bytes(b'raw'), {'power_max_w': 100})
        self.assertEqual(exc.exception.code, 'UNSUPPORTED_ARCHITECTURE')

    def test_save_without_hard_links_publishes_exclusive_copies(self):
        result = edit(self.image, {'power_max_w': 100})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch('nvidia_vbios.editor.api.os.link', side_effect=PermissionError('no hard links here')):
                published = save(result, root / 'copy.rom')
                self.assertEqual((root / 'copy.rom').read_bytes(), result.blob)
                manifest = json.loads(Path(published['manifest']).read_text(encoding='utf-8'))
                self.assertEqual(manifest['output_sha256'], result.manifest['output_sha256'])
                with self.assertRaises(VbiosError) as exc:
                    save(result, root / 'copy.rom')
                self.assertEqual(exc.exception.code, 'OUTPUT_EXISTS')
                # A manifest that cannot be published removes only the ROM this save created.
                real, calls = api._publish, []

                def flaky(*args):
                    calls.append(args[1])
                    if len(calls) == 2:
                        raise OSError('disk full')
                    return real(*args)
                with patch('nvidia_vbios.editor.api._publish', side_effect=flaky):
                    with self.assertRaises(VbiosError) as exc:
                        save(result, root / 'rollback.rom')
                self.assertEqual(exc.exception.code, 'IO_ERROR')
                self.assertFalse((root / 'rollback.rom').exists())
                self.assertFalse((root / 'rollback.rom.json').exists())

    def test_exclusive_copy_failure_after_creation_leaves_no_partial_file(self):
        import errno
        import shutil
        result = edit(self.image, {'power_max_w': 100})
        real = shutil.copyfileobj
        for failing_call, name in ((1, 'rom'), (2, 'manifest')):
            with self.subTest(failing=name), tempfile.TemporaryDirectory() as tmp:
                output, calls = Path(tmp) / 'out.rom', []

                def partial(source, target):
                    calls.append(target)
                    if len(calls) == failing_call:
                        target.write(source.read(5))
                        raise OSError(errno.ENOSPC, 'No space left on device')
                    return real(source, target)
                with patch('nvidia_vbios.editor.api.os.link', side_effect=PermissionError('no hard links')), \
                        patch('nvidia_vbios.editor.api.shutil.copyfileobj', side_effect=partial):
                    with self.assertRaises(VbiosError) as exc:
                        save(result, output)
                self.assertEqual(exc.exception.code, 'IO_ERROR')
                self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), [])

    def manifest_failure(self, result, output, hard_links, other_writer):
        """Save with a manifest publication that fails after other_writer touched the ROM."""
        real, calls = api._publish, []

        def failing(*args):
            calls.append(args[1])
            if len(calls) == 2:
                other_writer()
                raise OSError('manifest failed')
            return real(*args)
        link = os.link if hard_links else PermissionError('no hard links')
        with patch('nvidia_vbios.editor.api.os.link', side_effect=link), \
                patch('nvidia_vbios.editor.api._publish', side_effect=failing):
            with self.assertRaises(VbiosError):
                save(result, output)

    def test_rollback_keeps_a_replaced_rom_with_the_same_bytes(self):
        result = edit(self.image, {'power_max_w': 100})
        for hard_links in (True, False):
            if os.name == 'nt' and not hard_links:
                continue  # nobody else can delete the copy while the save holds it open
            with self.subTest(hard_links=hard_links), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / 'out.rom'

                def replace():  # another writer puts a different file with the same bytes
                    output.unlink()
                    output.write_bytes(result.blob)
                self.manifest_failure(result, output, hard_links, replace)
                self.assertEqual(output.read_bytes(), result.blob)

    def test_rollback_keeps_a_rom_overwritten_in_place(self):
        result = edit(self.image, {'power_max_w': 100})
        for hard_links in (True, False):
            with self.subTest(hard_links=hard_links), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / 'out.rom'

                def overwrite():  # same file, another writer's bytes
                    with open(output, 'r+b') as stream:
                        stream.write(b'OTHER WRITER')
                        stream.truncate()
                self.manifest_failure(result, output, hard_links, overwrite)
                self.assertEqual(output.read_bytes(), b'OTHER WRITER')

    def test_failed_copy_is_removed_without_file_numbers_or_reported(self):
        import errno
        import shutil
        result = edit(self.image, {'power_max_w': 100})

        def partial(source, target):
            target.write(source.read(5))
            raise OSError(errno.ENOSPC, 'No space left on device')

        def numberless(real):
            return lambda *a, **k: os.stat_result((real(*a, **k).st_mode, 0, 0) + tuple(real(*a, **k))[3:10])
        no_links = patch('nvidia_vbios.editor.api.os.link', side_effect=PermissionError('no hard links'))
        failing_copy = patch('nvidia_vbios.editor.api.shutil.copyfileobj', side_effect=partial)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'out.rom'
            with no_links, failing_copy, \
                    patch('nvidia_vbios.editor.api.os.fstat', side_effect=numberless(os.fstat)), \
                    patch('nvidia_vbios.editor.api.os.lstat', side_effect=numberless(os.lstat)):
                with self.assertRaises(VbiosError):
                    save(result, output)
            self.assertFalse(output.exists())
            with no_links, failing_copy, \
                    patch('nvidia_vbios.editor.api._unlink', return_value=False):
                with self.assertRaises(VbiosError) as exc:
                    save(result, output)
            self.assertIn('could not remove the incomplete', str(exc.exception))
            self.assertIn(str(output), str(exc.exception))

    def test_close_failures_remove_every_file_of_the_save(self):
        import builtins
        import errno
        result = edit(self.image, {'power_max_w': 100})
        real_open = builtins.open

        class Handle:
            """An exclusive copy whose close fails after closing the file."""
            def __init__(self, handle):
                self._handle = handle

            def __getattr__(self, name):
                return getattr(self._handle, name)

            def close(self):
                self._handle.close()
                raise OSError(errno.EIO, 'close failed')

        def partial(source, target):
            target.write(source.read(5))
            raise OSError(errno.ENOSPC, 'No space left on device')
        cases = (('out.rom', None), ('out.rom.json', None), ('out.rom', partial), ('out.rom.json', partial))
        for failing, copy in cases:
            with self.subTest(failing=failing, partial=bool(copy)), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / 'out.rom'

                def opener(path, mode='r', *args, **kwargs):
                    handle = real_open(path, mode, *args, **kwargs)
                    return Handle(handle) if mode == 'xb' and Path(path).name == failing else handle
                patches = [patch('nvidia_vbios.editor.api.os.link', side_effect=PermissionError('no hard links')),
                           patch('nvidia_vbios.editor.api.open', side_effect=opener, create=True)]
                if copy:
                    real_copy = __import__('shutil').copyfileobj
                    patches.append(patch('nvidia_vbios.editor.api.shutil.copyfileobj',
                                         side_effect=lambda src, dst: (copy if dst.name.endswith(failing) and
                                                                       isinstance(dst, Handle) else real_copy)(src, dst)))
                with patches[0], patches[1], (patches[2] if copy else patch.dict({})):
                    with self.assertRaises(VbiosError) as exc:
                        save(result, output)
                self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), [])
                self.assertIn('No space left' if copy else 'close failed', str(exc.exception))

    def test_existing_manifest_with_an_unremovable_rom_names_both(self):
        import errno
        result = edit(self.image, {'power_max_w': 100})
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'out.rom'
            real = os.link

            def link(source, target):
                if str(target).endswith('.json'):
                    raise FileExistsError(errno.EEXIST, 'File exists', str(target))
                return real(source, target)
            with patch('nvidia_vbios.editor.api.os.link', side_effect=link), \
                    patch('nvidia_vbios.editor.api._unlink', return_value=False):
                with self.assertRaises(VbiosError) as exc:
                    save(result, output)
            self.assertEqual(exc.exception.code, 'OUTPUT_EXISTS')
            self.assertIn(str(output) + '.json', str(exc.exception))
            self.assertIn(f'could not remove the incomplete {output}', str(exc.exception))

    def test_windows_order_full_disk_flush_and_close_still_remove_the_copy(self):
        import builtins
        import errno
        import io
        result = edit(self.image, {'power_max_w': 100})
        real_open = builtins.open

        class FullDisk(io.FileIO):
            """Accepts five bytes, then reports a full disk on every write."""
            def write(self, data):
                if self.tell() >= 5:
                    raise OSError(errno.ENOSPC, 'No space left on device')
                return super().write(bytes(data[:5 - self.tell()]))

        def opener(path, mode='r', *args, **kwargs):
            if mode == 'xb':
                return io.BufferedWriter(FullDisk(path, 'x'), buffer_size=64)
            return real_open(path, mode, *args, **kwargs)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'out.rom'
            with patch('nvidia_vbios.editor.api.os.link', side_effect=PermissionError('no hard links')), \
                    patch('nvidia_vbios.editor.api.open', side_effect=opener, create=True), \
                    patch.object(api, '_WINDOWS', True):
                with self.assertRaises(VbiosError) as exc:
                    save(result, output)
            self.assertIn('No space left', str(exc.exception))
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), [])

    def test_exclusive_save_source_symlinks_and_source_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.rom'
            source.write_bytes(self.image.blob)
            image = load(source)
            result = edit(image, {'power_max_w': 100})
            with self.assertRaises(VbiosError) as exc:
                save(result, source)
            self.assertEqual(exc.exception.code, 'SOURCE_OVERWRITE')
            output = root / 'output.rom'
            published = save(result, output)
            self.assertEqual(output.read_bytes(), result.blob)
            self.assertEqual(json.loads(Path(published['manifest']).read_text())['schema_version'], 1)
            with self.assertRaises(VbiosError) as exc:
                save(result, output)
            self.assertEqual(exc.exception.code, 'OUTPUT_EXISTS')
            if os.name != 'nt':  # symlinks need extra privileges on Windows
                link = root / 'symlink.rom'
                link.symlink_to(root / 'missing')
                with self.assertRaises(VbiosError) as exc:
                    save(result, link)
                self.assertEqual(exc.exception.code, 'OUTPUT_EXISTS')
            source.write_bytes(b'changed')
            with self.assertRaises(VbiosError) as exc:
                save(result, root / 'changed.rom')
            self.assertEqual(exc.exception.code, 'SOURCE_CHANGED')

    def test_failed_manifest_publication_rolls_back_our_rom(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'image.rom'
            actual = __import__('os').link
            def link(source, destination):
                if str(destination).endswith('.json'):
                    raise FileExistsError('racing writer')
                actual(source, destination)
            with patch('nvidia_vbios.editor.api.os.link', side_effect=link):
                with self.assertRaises(VbiosError) as exc:
                    save(edit(self.image, {'power_max_w': 100}), output)
            self.assertEqual(exc.exception.code, 'OUTPUT_EXISTS')
            self.assertFalse(output.exists())

    def test_ampere_power_variant_is_independent_of_blackwell(self):
        image = from_bytes(synthetic_rom(family='ampere'))
        result = edit(image, {'power_max_w': 90})
        fields = {f['key']: f for f in result.manifest['after']['fields']}
        self.assertEqual(fields['power_max_w']['current'], 90)
        self.assertTrue(fields['power_max_w']['experimental'])
        # Constant REL equations: a ceiling-only edit would not change the voltage.
        self.assertFalse(fields['nvvdd_rel_max_mv']['editable'])
        self.assertFalse(any(f['key'].endswith('_policy7_limit_ma') or f['key'] == 'board_fixed_rated_w'
                             for f in fields.values()))

    def test_extension_cannot_change_factory_defaults_or_thermal_coefficients(self):
        import struct
        from decimal import Decimal
        for kind in ('default', 'coefficient'):
            custom = FieldRegistry()
            @custom.register
            def forbidden(image, parser):
                at = (parser.power_rows()[parser.tgp_index]['maximum_offset'] - 4
                      if kind == 'default' else parser.rail_limits()[0]['maximum_offset'] + 4)
                encoding = '<I' if kind == 'default' else '<f'
                current = struct.unpack_from(encoding, image.blob, at)[0]
                descriptor = dict(key='forbidden', label='test', type='number', units='raw',
                                  current=current, bounds={'minimum': 0, 'maximum': 2000000},
                                  editable=True, evidence=[{'kind': 'synthetic-test'}])
                return [Binding(descriptor, tuple(parser.copy_offsets(at, 4)), encoding, Decimal(1))]
            with self.subTest(kind=kind), self.assertRaises(VbiosError) as exc:
                edit(self.image, {'forbidden': 1000000 if kind == 'coefficient' else 60000}, field_registry=custom)
            self.assertEqual(exc.exception.code, 'FACTORY_DEFAULT_CHANGED' if kind == 'default' else 'PRESERVED_FIELD_CHANGED')

    def test_registry_extension_reparses_evidence_and_rejects_overlap(self):
        custom = FieldRegistry()
        custom.register(power)
        result = edit(self.image, {'power_max_w': 100}, field_registry=custom)
        self.assertEqual(result.manifest['after']['fields'][0]['current'], 100)
        @custom.register
        def duplicate(image, parser):
            original = power(image, parser)[0]
            desc = dict(original.descriptor, key='other_power')
            return [Binding(desc, original.offsets, original.encoding, original.scale)]
        with self.assertRaises(VbiosError) as exc:
            edit(self.image, {'power_max_w': 100, 'other_power': 100}, field_registry=custom)
        self.assertEqual(exc.exception.code, 'CONFLICTING_FIELDS')




class BlackwellEditorTests(unittest.TestCase):
    def test_sha384_profiles_units_and_unchanged_current_policy(self):
        from test_rom_formats import synthetic_blackwell
        from nvidia_vbios.rom.image import backend
        image = from_bytes(synthetic_blackwell(shared_objects=True))
        source = backend(image)
        result = edit(image, {'power_max_w': 150, 'nvvdd_rel_max_mv': 1100,
                              'msvdd_rel_max_mv': 1125, 'memory_offset_max_mhz': 10000})
        target = backend(result.image)
        self.assertTrue(target.integrity()['valid'])
        self.assertEqual(target.power_rows()[9], source.power_rows()[9])
        for row in (2, 7, 8):
            self.assertEqual(target.power_rows()[row]['maximum_raw'], 150000)
            self.assertEqual(target.power_rows()[row]['default_raw'], 70000)
        self.assertEqual(target.power_profiles()[0]['entries'][0]['value_raw'], 150000)
        fields = {f['key']: f for f in result.manifest['after']['fields']}
        self.assertEqual(fields['dram_max_table_mhz']['current'], 5000)
        self.assertEqual(fields['memory_offset_max_mhz']['current'], 10000)
        self.assertEqual(target.blob[-23:], image.blob[-23:])
        self.assertEqual(target.legacy, source.legacy)
        self.assertEqual(target.objects, source.objects)

    def test_memory_unit_alias_conflict_and_unknown_domain_refusal(self):
        from test_rom_formats import synthetic_blackwell
        image = from_bytes(synthetic_blackwell())
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'dram_max_table_mhz': 5000, 'memory_offset_max_mhz': 10000})
        self.assertEqual(exc.exception.code, 'CONFLICTING_FIELDS')
        with self.assertRaises(VbiosError) as exc:
            edit(image, {'memory_offset_max_mhz': 9999})
        self.assertEqual(exc.exception.code, 'UNREPRESENTABLE_VALUE')

    def test_corrupt_digest_and_invalid_active_profile_fail_explicitly(self):
        from test_rom_formats import synthetic_blackwell
        blob = bytearray(synthetic_blackwell())
        blob[3072 + 0x209] ^= 1
        with self.assertRaises(VbiosError) as exc:
            edit(from_bytes(blob), {'power_max_w': 150})
        self.assertEqual(exc.exception.code, 'INTEGRITY_FAILED')


if __name__ == "__main__":
    unittest.main()
