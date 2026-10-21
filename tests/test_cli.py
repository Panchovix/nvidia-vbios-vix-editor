"""CLI boundary tests; hardware fixtures remain external to the repository."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from nvidia_vbios import cli


class CliCallMixin:
    def call(self, args):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = cli.main(args)
        return code, json.loads(stream.getvalue())


class CliTests(CliCallMixin, unittest.TestCase):
    def test_bad_arguments_have_a_versioned_error(self):
        code, report = self.call(['edit'])
        self.assertEqual(code, 2)
        self.assertFalse(report['ok'])
        self.assertEqual(report['schema_version'], 1)
        self.assertEqual(report['error']['code'], 'INVALID_ARGUMENT')

    def test_version_names_the_copyright_holder_and_license(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), self.assertRaises(SystemExit) as done:
            cli.parser().parse_args(['--version'])
        self.assertEqual(done.exception.code, 0)
        lines = stream.getvalue().splitlines()
        self.assertEqual(lines[:3], [f'nvbios {cli.__version__}', 'Copyright (C) 2026 panchovix',
                                     'License GPL-3.0-or-later <https://www.gnu.org/licenses/gpl-3.0.html>'])
        self.assertEqual(lines[-1], 'There is NO WARRANTY, to the extent permitted by law.')

    def test_missing_file_reports_io_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            code, report = self.call(['inspect', str(Path(directory) / 'missing.rom')])
        self.assertEqual(code, 2)
        self.assertEqual(report['error']['code'], 'IO_ERROR')

    def test_duplicate_assignment_does_not_silently_override_json(self):
        with tempfile.TemporaryDirectory() as directory:
            changes = Path(directory) / 'changes.json'
            changes.write_text('{"power_max_w":100}')
            args = cli.parser().parse_args(['edit', 'input.rom', '--changes', str(changes),
                                           '--set', 'power_max_w=200', '--dry-run'])
            with self.assertRaises(cli.UsageError):
                cli.changes_from_args(args)

    def test_memory_reports_and_compares_without_writing(self):
        from test_rom_formats import synthetic_rom
        with tempfile.TemporaryDirectory() as directory:
            source, other = Path(directory) / 'memory.rom', Path(directory) / 'other.rom'
            source.write_bytes(synthetic_rom(memory=True))
            other.write_bytes(synthetic_rom())
            code, report = self.call(['memory', str(source)])
            self.assertEqual((code, report['operation']), (0, 'memory'), report)
            entries = {t['index']: t for t in report['result']['timings']['items']}
            self.assertEqual(entries[1]['decoded']['tRC'], 79)
            self.assertEqual(report['result']['board_profile']['status'], 'not-applicable')
            code, report = self.call(['memory', str(source), '--compare', str(source)])
            self.assertEqual(code, 0, report)
            self.assertEqual({s['status'] for s in report['result']['sections'].values()},
                             {'identical', 'not-applicable'})
            self.assertNotIn('reports', report['result'])
            code, report = self.call(['memory', str(source), '--compare', str(other), '--raw'])
            self.assertEqual(report['result']['sections']['timings']['status'], 'unavailable')
            self.assertEqual([r['file'] for r in report['result']['reports']], [str(source), str(other)])
            code, report = self.call(['memory', str(source), '--compare', str(Path(directory) / 'missing.rom')])
            self.assertEqual((code, report['error']['code']), (2, 'IO_ERROR'))
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ['memory.rom', 'other.rom'])

    def test_import_dry_run_writes_nothing_and_saves_like_edit(self):
        from test_rom_formats import synthetic_blackwell
        from nvidia_vbios.editor import edit, inspect
        from nvidia_vbios.rom import from_bytes
        blob = synthetic_blackwell(fans=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, donor, output = root / 'board.rom', root / 'other board.rom', root / 'new folder' / 'fans.rom'
            source.write_bytes(blob)
            donor.write_bytes(edit(from_bytes(blob), {'fan_pwm_frequency_hz': 25000, 'power_max_w': 120}).blob)
            code, report = self.call(['import', str(source), str(donor), str(output), '--sections', 'fans',
                                      '--dry-run'])
            self.assertEqual((code, report['operation']), (0, 'import'), report)
            self.assertEqual(report['result']['changes'], {'fan_pwm_frequency_hz': 25000})
            self.assertEqual(report['result']['manifest']['operation'], 'plan')
            self.assertFalse(output.parent.exists())
            code, report = self.call(['import', str(source), str(donor), str(output), '--sections', 'fans, power'])
            self.assertEqual(code, 0, report)
            self.assertEqual(report['result']['publication']['output'], str(output))
            self.assertEqual(json.loads(output.with_name('fans.rom.json').read_text())['operation'], 'edit')
            fields = {f['key']: f['current'] for f in inspect(output)['fields']}
            self.assertEqual((fields['fan_pwm_frequency_hz'], fields['power_max_w']), (25000, 120))
            self.assertEqual(source.read_bytes(), blob)
            for args, error in ((['--sections', 'fans', str(root / 'same.rom')], 'NOTHING_TO_IMPORT'),
                                (['--sections', 'fans'], 'INVALID_ARGUMENT'),
                                (['--sections', 'fan', '--dry-run'], 'INVALID_SECTIONS')):
                with self.subTest(args=args):
                    donor_path = source if error == 'NOTHING_TO_IMPORT' else donor
                    code, report = self.call(['import', str(source), str(donor_path), *args])
                    self.assertEqual((code, report['error']['code']), (2, error))
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['board.rom', 'new folder', 'other board.rom'])

    def test_output_may_follow_the_options_after_a_leading_json_flag(self):
        from test_rom_formats import synthetic_blackwell
        from nvidia_vbios.editor import edit
        from nvidia_vbios.rom import from_bytes
        blob = synthetic_blackwell(fans=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, donor = root / 'board.rom', root / 'other.rom'
            source.write_bytes(blob)
            donor.write_bytes(edit(from_bytes(blob), {'fan_pwm_frequency_hz': 25000}).blob)
            code, report = self.call(['--json', 'import', str(source), str(donor), '--sections', 'fans',
                                      str(root / 'imported.rom')])
            self.assertEqual(code, 0, report)
            code, report = self.call(['--json', 'edit', str(source), '--set', 'fan_pwm_frequency_hz=25000',
                                      str(root / 'edited.rom')])
            self.assertEqual(code, 0, report)
            self.assertEqual((root / 'imported.rom').read_bytes(), (root / 'edited.rom').read_bytes())
            # A '--' separator still ends the options, so a file name may start with a dash.
            (root / '-dash.rom').write_bytes(blob)
            previous = os.getcwd()
            os.chdir(root)
            try:
                code, report = self.call(['edit', '--set', 'fan_pwm_frequency_hz=25000', '--', '-dash.rom',
                                          '-out.rom'])
            finally:
                os.chdir(previous)
            self.assertEqual(code, 0, report)
            self.assertEqual((root / '-out.rom').read_bytes(), (root / 'edited.rom').read_bytes())

    def test_gui_forwards_explicit_language_and_rom_without_parsing_editor_options(self):
        for arguments in ([], ['--lang', 'es'], ['--lang', 'en', 'source with spaces.rom'],
                          ['source.rom', '--lang', 'es']):
            with self.subTest(arguments=arguments), patch('nvidia_vbios.gui.main', return_value=0) as gui:
                self.assertEqual(cli.main(['gui', *arguments]), 0)
                gui.assert_called_once_with(arguments)


if __name__ == '__main__':
    unittest.main()
