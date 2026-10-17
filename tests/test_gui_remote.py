"""SSH picker routing and actual editor open/save on an isolated GTK display."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from nvidia_vbios.gui.arguments import parse_arguments, resolve_file_dialog, resolve_theme

class DialogModeTests(unittest.TestCase):
    def test_auto_uses_builtin_for_ssh_and_explicit_modes_take_precedence(self):
        self.assertEqual(resolve_file_dialog('auto', {}), 'system')
        for key in ('SSH_CONNECTION', 'SSH_CLIENT', 'SSH_TTY'):
            with self.subTest(key=key):
                self.assertEqual(resolve_file_dialog('auto', {key: 'present'}), 'builtin')
                self.assertEqual(resolve_file_dialog('system', {key: 'present'}), 'system')
        self.assertEqual(resolve_file_dialog('builtin', {}), 'builtin')
        with self.assertRaises(ValueError): resolve_file_dialog('portal-ish', {})

    def test_theme_follows_the_windows_app_mode_only_on_windows(self):
        self.assertEqual(parse_arguments([]).theme, 'auto')
        self.assertEqual(parse_arguments(['--theme', 'dark']).theme, 'dark')
        self.assertEqual(resolve_theme('auto', 'win32', lambda: True), 'dark')
        self.assertEqual(resolve_theme('auto', 'win32', lambda: False), 'light')
        self.assertIsNone(resolve_theme('auto', 'linux', lambda: True))       # GTK follows the desktop
        for mode in ('light', 'dark'):
            self.assertEqual(resolve_theme(mode, 'linux', lambda: True), mode)
            self.assertEqual(resolve_theme(mode, 'win32', lambda: mode == 'light'), mode)
        with self.assertRaises(ValueError): resolve_theme('blue')

    def test_all_modes_parse_with_language_and_optional_rom(self):
        for mode in ('auto','builtin','system'):
            args=parse_arguments(['--lang','es','--file-dialog',mode,'source with spaces.rom'])
            self.assertEqual((args.lang,args.file_dialog,args.rom),('es',mode,'source with spaces.rom'))

@unittest.skipUnless(os.environ.get('VBIOS_GUI_SMOKE') == '1', 'opt-in GTK display smoke test')
class RemoteEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi
        gi.require_version('Gtk','4.0')
        from gi.repository import Gio,GLib,Gtk
        from nvidia_vbios.gui.app import EditorWindow
        cls.Gio,cls.GLib,cls.Gtk,cls.Window=Gio,GLib,Gtk,EditorWindow
        cls.app=Gtk.Application(application_id='org.nvidia_vbios.RemoteSmoke',flags=Gio.ApplicationFlags.NON_UNIQUE)
        assert cls.app.register(None)

    def setUp(self):
        from test_rom_formats import synthetic_blackwell
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.source=Path(self.tmp.name)/'source with spaces.rom'
        self.source.write_bytes(synthetic_blackwell());self.original=self.source.read_bytes()
        self.window=self.Window(self.app,language='es',file_dialog='builtin')
        self.window.present();self.addCleanup(self.window.close)
        self.until(self.window.get_mapped)

    def until(self,condition):
        context=self.GLib.MainContext.default();deadline=time.monotonic()+10
        while not condition():
            while context.pending():context.iteration(False)
            if time.monotonic()>deadline:self.fail('GUI operation did not finish')
            time.sleep(.01)

    def open_path(self):
        picker=self.window._choose_path(False)
        picker.path_entry.set_text(str(self.source));picker.path_entry.emit('activate')
        self.until(lambda: not self.window.busy and self.window.controller.document is not None)

    def stage(self):
        # The preview verifies itself after typing; saving waits for that.
        self.window.entries['power_max_w'].set_text('150')
        self.until(lambda: not self.window.busy and not self.window.verifying and not self.window.dirty)
        self.assertIsNotNone(self.window.controller.document.proposal)
        self.assertEqual(self.window.controller.document.changes, {'power_max_w': '150'})

    def test_builtin_open_and_save_use_the_same_preview_without_portal(self):
        with patch.object(self.Gtk,'FileDialog',side_effect=AssertionError('desktop picker invoked')):
            picker=self.window._choose_open()
            self.assertIsInstance(picker,self.Gtk.FileChooserDialog)
            picker.set_file(self.Gio.File.new_for_path(str(self.source)))
            self.until(lambda:picker.get_file() is not None and picker.get_file().get_path()==str(self.source))
            picker.response(self.Gtk.ResponseType.ACCEPT)
            self.until(lambda:not self.window.busy and self.window.controller.document is not None)
            self.stage()
            dest=Path(self.tmp.name)/'builtin output.rom'
            save=self.window._choose_save();save.set_current_name(dest.name)
            self.until(lambda:save.get_current_folder() is not None and save.get_current_folder().get_path()==self.tmp.name)
            save.response(self.Gtk.ResponseType.ACCEPT)
            self.until(lambda:not self.window.busy and dest.exists())
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertTrue(dest.with_name(dest.name+'.json').is_file())

    def test_path_menu_actions_open_and_save_a_new_copy(self):
        self.window.lookup_action('open-path').activate(None)
        picker=self.window.file_picker
        self.assertEqual(picker.get_title(),self.window.text('open_path'))
        picker.path_entry.set_text(str(self.source));picker.accept_button.emit('clicked')
        self.until(lambda:not self.window.busy and self.window.controller.document is not None)
        self.stage();dest=Path(self.tmp.name)/'path output.rom'
        self.window.lookup_action('save-path').activate(None)
        picker=self.window.file_picker
        self.assertEqual(picker.get_title(),self.window.text('save_path'))
        picker.path_entry.set_text(str(dest));picker.path_entry.emit('activate')
        self.until(lambda:not self.window.busy and dest.exists())
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertTrue(dest.with_name(dest.name+'.json').is_file())

    def test_path_save_keeps_source_and_existing_destinations_immutable(self):
        self.open_path();self.stage()
        existing=Path(self.tmp.name)/'existing.rom';existing.write_bytes(b'KEEP')
        for destination in (self.source,existing):
            with self.subTest(destination=destination.name):
                picker=self.window._choose_path(True)
                picker.path_entry.set_text(str(destination));picker.accept_button.emit('clicked')
                self.until(lambda:not self.window.busy)
                self.assertTrue(self.window.status.has_css_class('error'))
                self.assertIsNone(self.window.controller.document.last_saved)
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertEqual(existing.read_bytes(),b'KEEP')

    def test_stale_save_picker_cannot_save_after_reset(self):
        self.open_path();self.stage();dest=Path(self.tmp.name)/'stale.rom'
        picker=self.window._choose_path(True);self.window._reset()
        picker.path_entry.set_text(str(dest));picker.accept_button.emit('clicked')
        self.assertFalse(dest.exists())
        self.assertEqual(self.window.status.get_text(),self.window.text('stale_dialog'))

    def test_parent_close_cancels_pending_path_selection(self):
        picker=self.window._choose_path(False);self.window.close()
        picker.path_entry.set_text(str(self.source));picker.accept_button.emit('clicked')
        self.assertTrue(self.window.closed)
        self.assertIsNone(self.window.controller.document)

    def test_explicit_system_mode_retains_the_desktop_picker_route(self):
        self.window.file_dialog='system'
        from unittest.mock import Mock
        dialog=Mock()
        with patch.object(self.window,'_dialog',return_value=dialog):
            self.window._choose_open()
        dialog.open.assert_called_once_with(self.window,None,self.window._opened)

if __name__=='__main__':unittest.main()
