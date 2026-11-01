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

    def test_rel_floor_and_flat_voltage_labels_sit_under_their_partners(self):
        from nvidia_vbios.editor.sections import SECTIONS
        labels = {(key, language): field_label({'key': key}, language)
                  for key in ('nvvdd_rel_equation_min_mv', 'msvdd_rel_equation_min_mv', 'nvvdd_rel_alt_follow_ov_mv')
                  for language in ('en', 'es')}
        self.assertEqual(labels, {('nvvdd_rel_equation_min_mv', 'en'): 'NVVDD REL floor',
                                  ('nvvdd_rel_equation_min_mv', 'es'): 'Piso REL de NVVDD',
                                  ('msvdd_rel_equation_min_mv', 'en'): 'MSVDD REL floor',
                                  ('msvdd_rel_equation_min_mv', 'es'): 'Piso REL de MSVDD',
                                  ('nvvdd_rel_alt_follow_ov_mv', 'en'): 'NVVDD flat voltage (REL = ALT = OV)',
                                  ('nvvdd_rel_alt_follow_ov_mv', 'es'): 'Voltaje plano de NVVDD (REL = ALT = OV)'})
        voltage = dict(SECTIONS)['voltage']
        for partner, key in (('nvvdd_rel_equation_max_mv', 'nvvdd_rel_equation_min_mv'),
                             ('msvdd_rel_equation_max_mv', 'msvdd_rel_equation_min_mv'),
                             ('nvvdd_rel_alt_follow_ov', 'nvvdd_rel_alt_follow_ov_mv'),
                             ('msvdd_rel_max_mv', 'msvdd_rel_fixed_mv'), ('msvdd_rel_fixed_mv', 'msvdd_alt_fixed_mv')):
            self.assertEqual(voltage.index(key), voltage.index(partner) + 1)
        # The Ampere MSVDD fixed values (opt-in) take the NVVDD labels with their rail.
        self.assertEqual(field_label({'key': 'msvdd_alt_fixed_mv', 'opt_in': True}),
                         'MSVDD ALT fixed voltage (advanced, experimental)')
        self.assertEqual(field_label({'key': 'msvdd_rel_fixed_mv', 'opt_in': True}, 'es'),
                         'Voltaje fijo REL de MSVDD (avanzado, experimental)')
        # Their read-only reasons name the rows the user changes instead, in both languages; on a ROM without ALT
        # only REL follows OV.
        from nvidia_vbios.editor.registry import (FOLLOW_OV_CLAMP_REASON, FOLLOW_OV_REL_CLAMP_REASON,
                                                  FOLLOW_OV_SWITCH_OFF_REASON)
        alone = {'en': 'REL follows OV in this ROM, so REL and OV share',
                 'es': 'En esta ROM REL sigue a OV, así que REL y OV comparten'}
        for language, flat, switch in (('en', 'NVVDD flat voltage (REL = ALT = OV)', 'NVVDD REL and ALT follow OV'),
                                       ('es', 'Voltaje plano de NVVDD (REL = ALT = OV)',
                                        'REL y ALT de NVVDD siguen a OV')):
            with self.subTest(language=language):
                self.assertIn(flat, read_only_reason({'reason': FOLLOW_OV_CLAMP_REASON}, language))
                self.assertIn(switch, read_only_reason({'reason': FOLLOW_OV_SWITCH_OFF_REASON}, language))
                rel = read_only_reason({'reason': FOLLOW_OV_REL_CLAMP_REASON}, language)
                self.assertTrue(rel.startswith(alone[language]) and flat in rel, rel)
        # A refused REL floor above its ceiling is explained by the voltage order hint.
        self.assertIn('VMIN < REL floor ≤ REL ≤ ALT', Messages()('order_hint_voltage'))
        self.assertIn('VMIN < piso REL ≤ REL ≤ ALT', Messages('es')('order_hint_voltage'))

    def test_runtime_power_limit_switch_label_and_notes(self):
        from nvidia_vbios.editor.sections import SECTIONS
        from nvidia_vbios.gui.presentation import row_title, runtime_limit_notes
        field = {'key': 'runtime_power_limit_unlock', 'units': 'flag', 'experimental': True, 'opt_in': True}
        self.assertEqual(row_title(field), ('Expose runtime power limit (nvidia-smi -pl, Afterburner)', True))
        self.assertEqual(row_title(field, 'es'),
                         ('Permitir cambiar el límite de potencia en uso (nvidia-smi -pl, Afterburner)', True))
        power = dict(SECTIONS)['power']
        self.assertEqual(power.index('runtime_power_limit_unlock'), power.index('notebook_base_tgp_w') + 1)
        # What it writes and what still limits the result, the hardware result of the family (one Turing laptop),
        # then its driver precedent.
        for family, tested, precedent in (('turing', 'runtime_limit.turing', 'runtime_limit.r525'),
                                          ('ampere', 'runtime_limit.untested', 'runtime_limit.r525'),
                                          ('blackwell-gb20x', 'runtime_limit.untested', 'runtime_limit.gb20x')):
            for language in ('en', 'es'):
                text = Messages(language)
                self.assertEqual(runtime_limit_notes(field, family, language),
                                 [text('runtime_limit.note'), text(tested), text(precedent)])
        self.assertEqual(runtime_limit_notes({'key': 'power_max_w'}, 'turing'), [])
        english, spanish = (runtime_limit_notes(field, 'ampere', language) for language in ('en', 'es'))
        # For more, the ceiling alone (the boot default is the slider's 100 %), which also caps the platform.
        for part in ('nvidia-smi -pl', 'Off writes the empty entry back', 'Board power floor and Board power ceiling',
                     "raise only Board power ceiling: Boot default board power, which is 100 % on MSI Afterburner's "
                     'slider, can stay at stock', 'Dynamic Boost', 'the lowest request wins',
                     'a higher value has no effect', 'capped by the ceiling too', 'On battery',
                     'sized for the stock limit'):
            self.assertIn(part, english[0])
        for part in ('nvidia-smi -pl', 'Desactivado vuelve a dejar la entrada vacía', 'el piso y el techo de potencia '
                     'de la placa', 'sube solo el techo de potencia de la placa: la potencia por defecto al arrancar, '
                     'que es el 100 % del deslizador de MSI Afterburner, puede quedar de fábrica', 'Dynamic Boost',
                     'gana el pedido más bajo', 'un valor más alto no tiene efecto', 'limitado por el techo',
                     'Con batería', 'el límite de fábrica'):
            self.assertIn(part, spanish[0])
        self.assertEqual((english[1], spanish[1]), ('Not tested on hardware.', 'Sin probar en hardware.'))
        self.assertIn('R525', english[2])
        self.assertIn('R525', spanish[2])
        self.assertIn('RTX 50', runtime_limit_notes(field, 'blackwell-gb20x', 'es')[2])
        english, spanish = (runtime_limit_notes(field, 'turing', language)[1] for language in ('en', 'es'))
        for part in ('one RTX 2070 Laptop GPU on Windows (driver 621.01)', 'power limit slider', '64 % (73.6 W)',
                     '71.1 W under load', 'Nothing above the stock limit was tried'):
            self.assertIn(part, english)
        for part in ('una RTX 2070 Laptop GPU con Windows (driver 621.01)', 'deslizador del límite de potencia',
                     '64 % (73,6 W)', '71,1 W bajo carga', 'No se probó nada por encima del límite de fábrica'):
            self.assertIn(part, spanish)


if __name__ == '__main__':
    unittest.main()
