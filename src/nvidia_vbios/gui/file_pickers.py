"""In-process GTK pickers for displays forwarded over SSH.

GTK imports stay inside the factories so importing this module does not require
GTK. Selection only reports a local path; document validation and I/O belong to
the editor. Gtk.FileChooserDialog is deliberately used despite its GTK4
deprecation: unlike native dialogs, its widgets live in this process.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


def _gtk():
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Gdk', '4.0')
    from gi.repository import Gdk, Gio, GLib, Gtk
    return Gdk, Gio, GLib, Gtk


def _windows_path(value):
    """A drive or UNC path on Windows, never mistaken for a URI scheme."""
    return os.name == 'nt' and re.match(r'^(?:[A-Za-z]:[\\/]|\\\\)', value) is not None


def _local_path(value: str) -> Path:
    """Normalize a local path without resolving links or inspecting files."""
    if not value.strip() or '\0' in value:
        raise ValueError('Empty or invalid path')
    if not _windows_path(value) and re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', value):
        uri = urlsplit(value)
        if uri.scheme != 'file' or uri.netloc not in ('', 'localhost') or uri.query or uri.fragment:
            raise ValueError('A local path is required')
        value = unquote(uri.path)
        if os.name == 'nt' and re.match(r'^/[A-Za-z]:/', value):
            value = value[1:]  # file:///C:/dir/file.rom
        if not (value.startswith('/') or _windows_path(value)) or '\0' in value:
            raise ValueError('Invalid local file URI')
    # Use HOME directly: expanding ~user could perform a blocking account lookup.
    if value == '~' or value.startswith('~/') or (os.name == 'nt' and value.startswith('~\\')):
        home = os.environ.get('HOME') or (os.environ.get('USERPROFILE') if os.name == 'nt' else None)
        if not home:
            raise ValueError('Home directory is unavailable')
        value = home + value[1:]
    elif value.startswith('~'):
        raise ValueError('Use ~ or an explicit local path')
    return Path(os.path.abspath(value))


class _Lifetime:
    """One completion path, including direct destruction and parent closure."""
    def __init__(self, window, parent, on_selected):
        self.window = window
        self.parent = parent
        self.on_selected = on_selected
        self.done = False
        self.parent_handlers = []
        window.connect('close-request', self._close_request)
        window.connect('destroy', self._destroyed)
        window.connect('unrealize', self._destroyed)
        if parent is not None:
            self.parent_handlers = [
                parent.connect('close-request', self._parent_close),
                parent.connect('destroy', self._parent_close),
                parent.connect('unrealize', self._parent_close),
            ]

    def _detach(self):
        if self.parent is not None:
            for handler in self.parent_handlers:
                if self.parent.handler_is_connected(handler):
                    self.parent.disconnect(handler)
        self.parent_handlers = []
        self.parent = None
        callback, self.on_selected = self.on_selected, None
        return callback

    def finish(self, path=None):
        if self.done:
            return
        self.done = True
        callback = self._detach()
        self.window.destroy()
        if path is not None and callback is not None:
            callback(path)

    def _close_request(self, *_):
        self.finish()
        return True

    def _parent_close(self, *_):
        self.finish()
        return False

    def _destroyed(self, *_):
        if not self.done:
            self.done = True
            self._detach()


def show_builtin_picker(parent, *, save: bool, title, accept_label,
                        cancel_label, all_files_label, initial_path=None,
                        on_selected) -> 'Gtk.FileChooserDialog':
    """Present a GTK widget chooser, never a portal or native file dialog."""
    _Gdk, Gio, GLib, Gtk = _gtk()
    dialog = Gtk.FileChooserDialog(
        title=title, transient_for=parent, modal=True, destroy_with_parent=True,
        action=Gtk.FileChooserAction.SAVE if save else Gtk.FileChooserAction.OPEN,
    )
    dialog.add_button(cancel_label, Gtk.ResponseType.CANCEL)
    dialog.add_button(accept_label, Gtk.ResponseType.ACCEPT)
    dialog.set_default_response(Gtk.ResponseType.ACCEPT)
    rom_filter = Gtk.FileFilter()
    rom_filter.set_name('ROM / BIN')
    for pattern in ('*.rom', '*.bin', '*.ROM', '*.BIN'):
        rom_filter.add_pattern(pattern)
    dialog.add_filter(rom_filter)
    all_filter = Gtk.FileFilter()
    all_filter.set_name(all_files_label)
    all_filter.add_pattern('*')
    dialog.add_filter(all_filter)
    dialog.set_filter(rom_filter)
    if initial_path is not None:
        path = _local_path(os.fspath(initial_path))
        try:
            if save:
                dialog.set_current_folder(Gio.File.new_for_path(str(path.parent)))
                dialog.set_current_name(path.name)
            else:
                # set_file also selects the parent folder. Starting a separate
                # asynchronous set_current_folder can discard this selection.
                dialog.set_file(Gio.File.new_for_path(str(path)))
        except GLib.Error:
            # A vanished initial folder must not prevent selecting another file.
            if save:
                dialog.set_current_name(path.name)
    lifetime = _Lifetime(dialog, parent, on_selected)

    def response(chooser, response_id):
        if lifetime.done:
            return
        path = None
        if response_id == Gtk.ResponseType.ACCEPT:
            selected = chooser.get_file()
            local = selected.get_path() if selected is not None else None
            if local is not None:
                path = Path(local)
        lifetime.finish(path)

    dialog.connect('response', response)
    dialog.present()
    return dialog


def show_path_dialog(parent, *, save: bool, title, accept_label,
                     cancel_label, path_label, hint, error_label,
                     initial_path=None, on_selected) -> 'Gtk.Window':
    """Present an explicit local-path entry without any filesystem I/O."""
    Gdk, _Gio, _GLib, Gtk = _gtk()
    window = Gtk.Window(title=title, transient_for=parent, modal=True,
                        destroy_with_parent=True)
    window.set_default_size(560, -1)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    for edge in ('top', 'bottom', 'start', 'end'):
        getattr(box, f'set_margin_{edge}')(16)
    window.set_child(box)
    box.append(Gtk.Label(label=path_label, xalign=0))
    entry = Gtk.Entry(hexpand=True)
    if initial_path is not None:
        entry.set_text(os.fspath(initial_path))
    box.append(entry)
    hint_widget = Gtk.Label(label=hint, xalign=0, wrap=True)
    hint_widget.add_css_class('dim-label')
    box.append(hint_widget)
    error_widget = Gtk.Label(label=error_label, xalign=0, wrap=True)
    error_widget.add_css_class('error')
    error_widget.set_visible(False)
    box.append(error_widget)
    buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    cancel = Gtk.Button(label=cancel_label)
    accept = Gtk.Button(label=accept_label)
    accept.add_css_class('suggested-action')
    buttons.append(cancel)
    buttons.append(accept)
    box.append(buttons)
    lifetime = _Lifetime(window, parent, on_selected)

    def selected(*_):
        if lifetime.done:
            return
        try:
            path = _local_path(entry.get_text())
        except (ValueError, OSError):
            error_widget.set_visible(True)
            entry.grab_focus()
            return
        lifetime.finish(path)

    def key_pressed(_controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            lifetime.finish()
            return True
        return False

    cancel.connect('clicked', lambda *_: lifetime.finish())
    accept.connect('clicked', selected)
    entry.connect('activate', selected)
    entry.connect('changed', lambda *_: error_widget.set_visible(False))
    keys = Gtk.EventControllerKey()
    keys.connect('key-pressed', key_pressed)
    window.add_controller(keys)
    # Expose the interactive controls for embedding callers and GTK smoke tests.
    window.path_entry = entry
    window.accept_button = accept
    window.cancel_button = cancel
    window.path_error = error_widget
    window.path_keys = keys
    window.present()
    entry.grab_focus()
    return window
