"""Launch argument routing and immutable localization require no GTK."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
import string
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from nvidia_vbios.gui.arguments import parse_arguments
from nvidia_vbios.gui.i18n import MESSAGES_EN, Messages
from nvidia_vbios.gui.messages_es import MESSAGES_ES
from nvidia_vbios.gui.presentation import field_label, read_only_reason


class LanguageTests(unittest.TestCase):
    def test_default_is_english_even_under_spanish_host_locale(self):
        with patch.dict(os.environ, {'LANG': 'es_CL.UTF-8', 'LC_ALL': 'es_CL.UTF-8'}):
            args = parse_arguments(['source.rom'])
            self.assertEqual((args.lang, args.rom), ('en', 'source.rom'))
            self.assertEqual(Messages()('open'), 'Open ROM…')
            self.assertEqual(field_label({'key': 'power_max_w'}), 'Board power ceiling')
            self.assertEqual(field_label({'key': 'power_min_w'}), 'Board power floor')
            self.assertEqual(field_label({'key': 'power_min_w'}, 'es'), 'Piso de potencia de la placa')

    def test_language_and_optional_rom_route_through_public_launcher(self):
        from nvidia_vbios.gui import main
        observed = []
        backend = SimpleNamespace(run=lambda args: observed.append((args.lang, args.rom)) or 17)
        cases = (([], ('en', None)), (['file.rom'], ('en', 'file.rom')),
                 (['--lang', 'en'], ('en', None)), (['--lang', 'es'], ('es', None)),
                 (['--lang', 'es', 'file with spaces.rom'], ('es', 'file with spaces.rom')),
                 (['file.rom', '--lang', 'es'], ('es', 'file.rom')))
        with patch.dict(sys.modules, {'nvidia_vbios.gui.app': backend}):
            for argv, expected in cases:
                with self.subTest(argv=argv):
                    self.assertEqual(main(argv), 17)
                    self.assertEqual(observed[-1], expected)

    def test_other_languages_are_rejected_before_importing_gtk(self):
        from nvidia_vbios.gui import main
        for lang in ('fr', 'es_CL', 'EN', ''):
            with self.subTest(lang=lang), redirect_stderr(StringIO()), self.assertRaises(SystemExit) as exc:
                main(['--lang', lang])
            self.assertEqual(exc.exception.code, 2)

    def test_help_is_localized_and_needs_no_gtk(self):
        from nvidia_vbios.gui import main
        for argv, expected in ((['--help'], 'Offline NVIDIA VBIOS graphical editor'),
                               (['--lang', 'en', '--help'], 'Offline NVIDIA VBIOS graphical editor'),
                               (['--lang', 'es', '--help'], MESSAGES_ES['cli_description'])):
            output = StringIO()
            with redirect_stdout(output), self.assertRaises(SystemExit) as exc:
                main(argv)
            self.assertEqual(exc.exception.code, 0)
            self.assertIn(expected, output.getvalue())
            self.assertIn('--lang {en,es}', output.getvalue())
            if 'es' in argv:
                self.assertIn(MESSAGES_ES['cli_help'], output.getvalue())
                self.assertIn(MESSAGES_ES['cli_options'] + ':', output.getvalue())
                self.assertTrue(output.getvalue().startswith(MESSAGES_ES['cli_usage']))
                self.assertNotIn('show this help message', output.getvalue())

    def test_catalogs_cover_same_messages_and_format_placeholders(self):
        self.assertEqual(MESSAGES_EN.keys(), MESSAGES_ES.keys())
        def placeholders(value):
            return {field for _, field, _, _ in string.Formatter().parse(value) if field is not None}
        for key in MESSAGES_EN:
            with self.subTest(key=key):
                self.assertEqual(placeholders(MESSAGES_EN[key]), placeholders(MESSAGES_ES[key]))
        with self.assertRaises(TypeError):
            MESSAGES_EN['open'] = 'changed'

    def test_license_note_names_copyright_license_warranty_and_source(self):
        for language, warranty in (('en', 'NO WARRANTY'), ('es', 'SIN GARANTÍA')):
            with self.subTest(language=language):
                note = Messages(language)('license_note', version='9.9.9')
                for part in ('9.9.9', 'Copyright (C) 2026 panchovix', 'GNU GPL v3', warranty,
                             'https://github.com/Panchovix/nvidia-vbios-vix-editor'):
                    self.assertIn(part, note)

    def test_messages_and_field_descriptors_keep_language_local(self):
        english, spanish = Messages(), Messages('es')
        field = {'key': 'nvvdd_rel_equation_max_mv', 'label': 'raw API label'}
        self.assertEqual(field_label(field), 'NVVDD REL equation ceiling')
        self.assertEqual(field_label(field, 'es'), spanish('field.equation', rail='NVVDD', role='REL'))
        self.assertEqual(english('open'), 'Open ROM…')
        self.assertNotEqual(spanish('open'), english('open'))
        reason = {'reason': 'no validated OCP field mapping'}
        self.assertIn('unvalidated', read_only_reason(reason))
        self.assertEqual(read_only_reason(reason, 'es'), spanish('reason.ocp'))
        self.assertEqual(field, {'key': 'nvvdd_rel_equation_max_mv', 'label': 'raw API label'})

    def test_vmin_labels_keep_the_evaluated_vmin_apart_from_the_info_slot(self):
        english, spanish = Messages(), Messages('es')
        self.assertEqual(field_label({'key': 'msvdd_vmin_mv'}), 'MSVDD minimum voltage (VMIN, experimental)')
        self.assertEqual(field_label({'key': 'msvdd_vmin_mv'}, 'es'), spanish('field.vmin', rail='MSVDD'))
        slot = field_label({'key': 'nvvdd_vmin_equation_max_mv'})
        self.assertIn('not the evaluated VMIN', slot)
        self.assertNotEqual(slot, english('field.equation', rail='NVVDD', role='VMIN'))
        self.assertIn('no es el VMIN evaluado', field_label({'key': 'nvvdd_vmin_equation_max_mv'}, 'es'))
        for language in ('en', 'es'):
            self.assertIn('XOC', field_label({'key': 'nvvdd_rel_alt_follow_ov'}, language))


if __name__ == '__main__':
    unittest.main()
