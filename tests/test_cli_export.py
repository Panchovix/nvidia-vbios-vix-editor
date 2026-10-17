"""The JSON command line keeps only the offline editor commands."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from nvidia_vbios import cli
from test_rom_formats import synthetic_blackwell, synthetic_rom

EDITOR_COMMANDS = {'inspect', 'fields', 'verify', 'edit', 'normalize', 'gui'}


class ExportCliTests(unittest.TestCase):
    def call(self, args):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = cli.main(args)
        return code, json.loads(stream.getvalue())

    def test_only_editor_commands_are_registered(self):
        commands = next(action for action in cli.parser()._actions if action.dest == 'command')
        self.assertEqual(set(commands.choices), EDITOR_COMMANDS)

    def test_lifecycle_and_driver_commands_are_usage_errors(self):
        for argv in (['system', 'status'], ['driver', 'inspect', 'tree']):
            with self.subTest(argv=argv):
                code, report = self.call(argv)
                self.assertEqual(code, 2)
                self.assertFalse(report['ok'])
                self.assertEqual(report['error']['code'], 'INVALID_ARGUMENT')

    def test_synthetic_roms_round_trip_through_the_cli(self):
        for name, blob in (('ada', synthetic_rom()), ('blackwell', synthetic_blackwell())):
            with self.subTest(rom=name), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / f'{name}.rom'
                source.write_bytes(blob)
                for command in ('inspect', 'verify'):
                    code, report = self.call([command, str(source)])
                    self.assertEqual((code, report['ok']), (0, True), report)
                code, report = self.call(['fields', str(source)])
                fields = {item['key']: item for item in report['result']['fields']}
                self.assertTrue(fields['power_max_w']['editable'])
                value = fields['power_max_w']['current'] + 1
                code, report = self.call(['edit', str(source), '--set', f'power_max_w={value}', '--dry-run'])
                self.assertEqual((code, report['ok']), (0, True), report)
                edited = Path(directory) / f'{name}.edited.rom'
                code, report = self.call(['edit', str(source), str(edited), '--set', f'power_max_w={value}'])
                self.assertEqual((code, report['ok']), (0, True), report)
                self.assertEqual(source.read_bytes(), blob)
                code, report = self.call(['fields', str(edited)])
                fields = {item['key']: item for item in report['result']['fields']}
                self.assertEqual(fields['power_max_w']['current'], value)
                code, report = self.call(['normalize', str(source), str(Path(directory) / f'{name}.payload.bin')])
                self.assertEqual((code, report['ok']), (0, True), report)


if __name__ == '__main__':
    unittest.main()
