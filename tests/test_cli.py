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

    def test_gui_forwards_explicit_language_and_rom_without_parsing_editor_options(self):
        for arguments in ([], ['--lang', 'es'], ['--lang', 'en', 'source with spaces.rom'],
                          ['source.rom', '--lang', 'es']):
            with self.subTest(arguments=arguments), patch('nvidia_vbios.gui.main', return_value=0) as gui:
                self.assertEqual(cli.main(['gui', *arguments]), 0)
                gui.assert_called_once_with(arguments)


if __name__ == '__main__':
    unittest.main()
