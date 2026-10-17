"""Opt-in in-process picker tests; run with VBIOS_GUI_SMOKE=1 on a display."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch


class PathRuleTests(unittest.TestCase):
    """Typed paths without GTK: POSIX rules unchanged, Windows drive, UNC and file URIs."""

    @unittest.skipIf(os.name == 'nt', 'POSIX rule')
    def test_posix_keeps_rejecting_drive_letters(self):
        from nvidia_vbios.gui.file_pickers import _local_path
        with self.assertRaises(ValueError):
            _local_path('C:\\roms\\a.rom')
        self.assertEqual(_local_path('file:///tmp/a%20b.rom'), Path('/tmp/a b.rom'))

    @unittest.skipUnless(os.name == 'nt', 'Windows paths')
    def test_windows_drive_unc_uri_and_home(self):
        from nvidia_vbios.gui.file_pickers import _local_path
        self.assertEqual(_local_path('C:\\roms\\a.rom'), Path('C:/roms/a.rom'))
        self.assertEqual(_local_path('D:/roms/a.rom'), Path('D:/roms/a.rom'))
        self.assertEqual(_local_path('file:///C:/roms/a%20b.rom'), Path('C:/roms/a b.rom'))
        self.assertEqual(_local_path('\\\\server\\share\\a.rom'), Path('\\\\server\\share\\a.rom'))
        environment = {k: v for k, v in os.environ.items() if k != 'HOME'}
        environment['USERPROFILE'] = 'C:\\Users\\me'
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(_local_path('~\\a.rom'), Path('C:/Users/me/a.rom'))
        with self.assertRaises(ValueError):
            _local_path('http://example.com/a.rom')


@unittest.skipUnless(os.environ.get('VBIOS_GUI_SMOKE') == '1', 'opt-in GTK display smoke test')
class FilePickerSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi
        gi.require_version('Gtk', '4.0')
        gi.require_version('Gdk', '4.0')
        from gi.repository import Gdk, Gio, GLib, Gtk
        from nvidia_vbios.gui.file_pickers import show_builtin_picker, show_path_dialog
        cls.Gdk, cls.Gio, cls.GLib, cls.Gtk = Gdk, Gio, GLib, Gtk
        cls.builtin = staticmethod(show_builtin_picker)
        cls.path_dialog = staticmethod(show_path_dialog)
        Gtk.init()

    def setUp(self):
        self.parent = self.Gtk.Window(title='Picker test parent')
        self.parent.present()
        self.dialogs = []
        self.selected = []
        self.until(self.parent.get_mapped)

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.destroy()
        self.parent.destroy()
        self.drain()

    def drain(self):
        context = self.GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

    def until(self, condition):
        deadline = time.monotonic() + 5
        while not condition():
            self.drain()
            if time.monotonic() >= deadline:
                self.fail('GTK picker operation did not complete')
            time.sleep(.01)

    def chooser(self, *, save=False, initial_path=None):
        dialog = self.builtin(
            self.parent, save=save, title='Choose ROM', accept_label='Save' if save else 'Open',
            cancel_label='Cancel', all_files_label='All files', initial_path=initial_path,
            on_selected=self.selected.append,
        )
        self.dialogs.append(dialog)
        self.until(dialog.get_mapped)
        return dialog

    def path(self, *, save=False, initial_path=None):
        dialog = self.path_dialog(
            self.parent, save=save, title='Linux path', accept_label='Save' if save else 'Open',
            cancel_label='Cancel', path_label='Path', hint='Path on the SSH host',
            error_label='Invalid local path', initial_path=initial_path,
            on_selected=self.selected.append,
        )
        self.dialogs.append(dialog)
        self.until(dialog.get_mapped)
        return dialog

    def test_builtin_is_embedded_with_filters_and_no_native_or_portal_dialog(self):
        with patch.object(self.Gtk, 'FileDialog', side_effect=AssertionError('portal dialog')), \
                patch.object(self.Gtk, 'FileChooserNative', side_effect=AssertionError('native dialog')):
            dialog = self.chooser()
        self.assertIsInstance(dialog, self.Gtk.FileChooserDialog)
        self.assertEqual(dialog.get_action(), self.Gtk.FileChooserAction.OPEN)
        self.assertIs(dialog.get_transient_for(), self.parent)
        self.assertTrue(dialog.get_modal())
        self.assertTrue(dialog.get_destroy_with_parent())
        filters = dialog.get_filters()
        self.assertEqual(filters.get_n_items(), 2)
        self.assertEqual(filters.get_item(1).get_name(), 'All files')
        for pattern in ('*.rom', '*.bin', '*.ROM', '*.BIN'):
            self.assertIn(pattern, filters.get_item(0).to_gvariant().print_(False))
        dialog.response(self.Gtk.ResponseType.CANCEL)
        self.assertEqual(self.selected, [])
        self.assertFalse(dialog.get_visible())

    def test_builtin_open_reports_local_path_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a file.rom'
            path.touch()
            dialog = self.chooser(initial_path=path)
            self.until(lambda: dialog.get_file() is not None and dialog.get_file().get_path() == str(path))
            dialog.response(self.Gtk.ResponseType.ACCEPT)
            self.until(lambda: bool(self.selected))
            self.assertEqual(self.selected, [path])
            dialog.emit('response', self.Gtk.ResponseType.ACCEPT)
            self.assertEqual(self.selected, [path])
            self.assertFalse(dialog.get_visible())

    def test_builtin_save_suggests_separate_name_and_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'new file.bin'
            dialog = self.chooser(save=True, initial_path=path)
            self.assertEqual(dialog.get_action(), self.Gtk.FileChooserAction.SAVE)
            self.assertEqual(dialog.get_current_name(), path.name)
            self.until(lambda: dialog.get_current_folder() is not None)
            self.assertEqual(dialog.get_current_folder().get_path(), folder)
            dialog.response(self.Gtk.ResponseType.ACCEPT)
            self.until(lambda: bool(self.selected))
            self.assertEqual(self.selected, [path])
            self.assertFalse(path.exists())

    def test_builtin_ignores_nonlocal_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.rom'
            path.touch()
            dialog = self.chooser(initial_path=path)
            self.until(lambda: dialog.get_file() is not None)
            # Keep the underlying widget's valid local selection so GTK lets
            # the response through, then simulate a remote result for our code.
            with patch.object(dialog, 'get_file', return_value=self.Gio.File.new_for_uri('sftp://example.com/a.rom')):
                dialog.response(self.Gtk.ResponseType.ACCEPT)
                self.until(lambda: not dialog.get_visible())
            self.assertEqual(self.selected, [])

    def test_path_blank_and_nonlocal_url_keep_dialog_open_with_localized_error(self):
        dialog = self.path()
        for value in ('', '   ', 'https://example.com/a.rom', 'sftp://example.com/a.rom', 'file://example.com/a.rom', 'https:example.com/a.rom', 'data:text/plain,rom'):
            with self.subTest(value=value):
                dialog.path_entry.set_text(value)
                dialog.accept_button.emit('clicked')
                self.assertTrue(dialog.get_visible())
                self.assertTrue(dialog.path_error.get_visible())
                self.assertEqual(dialog.path_error.get_text(), 'Invalid local path')
                self.assertEqual(self.selected, [])
        # GTK entries cannot contain a literal NUL, so exercise path validation
        # directly for that input rather than losing the NUL at the GTK boundary.
        from nvidia_vbios.gui.file_pickers import _local_path
        with self.assertRaises(ValueError):
            _local_path('/tmp/a\0.rom')

    def test_path_expands_home_preserves_spaces_and_accepts_enter_once(self):
        with tempfile.TemporaryDirectory(prefix='picker home ') as home:
            with patch.dict(os.environ, {'HOME': home}):
                dialog = self.path(save=True, initial_path='~/new output.rom')
                self.assertEqual(dialog.path_entry.get_text(), '~/new output.rom')
                dialog.path_entry.emit('activate')
                dialog.accept_button.emit('clicked')
                self.assertEqual(self.selected, [Path(home) / 'new output.rom'])
                self.assertFalse(dialog.get_visible())
                self.assertFalse(self.selected[0].exists())

    def test_path_relative_path_and_local_file_uri(self):
        for value, expected in (
                ('relative file.bin', Path.cwd() / 'relative file.bin'),
                ('file:///tmp/local%20file.rom', Path('/tmp/local file.rom'))):
            with self.subTest(value=value):
                dialog = self.path(initial_path=value)
                dialog.accept_button.emit('clicked')
                self.assertEqual(self.selected[-1], expected)
                self.assertIsInstance(self.selected[-1], Path)

    def test_path_cancel_escape_and_window_close_never_select(self):
        for action in ('cancel', 'escape', 'close'):
            with self.subTest(action=action):
                dialog = self.path(initial_path='/tmp/unused.rom')
                if action == 'cancel':
                    dialog.cancel_button.emit('clicked')
                elif action == 'escape':
                    self.assertTrue(dialog.path_keys.emit('key-pressed', self.Gdk.KEY_Escape, 0, self.Gdk.ModifierType(0)))
                else:
                    dialog.close()
                self.drain()
                dialog.accept_button.emit('clicked')
                self.assertEqual(self.selected, [])
                self.assertFalse(dialog.get_visible())

    def test_direct_window_destruction_cancels_selection(self):
        path = self.path(initial_path='/tmp/unused.rom')
        path.destroy()
        self.drain()
        path.accept_button.emit('clicked')
        self.assertEqual(self.selected, [])
        self.assertFalse(path.get_visible())

    def test_parent_close_and_destroy_cancel_both_picker_types(self):
        for destroy in (False, True):
            with self.subTest(destroy=destroy):
                chooser = self.chooser()
                path = self.path(initial_path='/tmp/unused.rom')
                if destroy:
                    self.parent.destroy()
                else:
                    self.parent.close()
                self.drain()
                self.assertFalse(chooser.get_visible())
                self.assertFalse(path.get_visible())
                path.accept_button.emit('clicked')
                chooser.emit('response', self.Gtk.ResponseType.CANCEL)
                self.assertEqual(self.selected, [])
                self.parent = self.Gtk.Window(title='Another picker test parent')
                self.parent.present()
                self.until(self.parent.get_mapped)


if __name__ == '__main__':
    unittest.main()
