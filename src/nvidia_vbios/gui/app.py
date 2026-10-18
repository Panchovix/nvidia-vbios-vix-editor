"""Native GTK4 view. Import this module only from the GUI entry point."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
import sys

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk

from .. import __version__
from .arguments import parse_arguments, resolve_file_dialog, resolve_theme
from .i18n import Messages
from .file_pickers import show_builtin_picker, show_path_dialog
from .controller import (Controller, controls, loader_messages, open_document, reset_document,
                         save_document, stage_document)
from .presentation import (classify_number, display_units, field_label, field_section, number, opt_in_field_keys,
                           parse_number,
                           primary_preview, read_only_reason, row_title, section_order, shunt_real, shunt_scaled,
                           technical_field_keys, to_display, to_stored, windows_value)

# Typing pauses this long before the copy is rebuilt and verified.
LIVE_DELAY_MS = 350

CSS = """
.vb-content { padding: 18px 18px 8px 18px; }
.vb-card { background-color: alpha(currentColor, 0.035); border: 1px solid alpha(currentColor, 0.10);
           border-radius: 12px; }
.vb-device { padding: 16px 18px; }
.vb-product { font-size: 1.3em; font-weight: 800; }
.vb-chip { font-size: 0.85em; padding: 2px 9px; border-radius: 999px; background-color: alpha(currentColor, 0.08); }
.vb-ok { color: #26a269; font-weight: 700; }
.vb-bad { color: #e5484d; font-weight: 700; }
.vb-section { font-weight: 800; font-size: 0.95em; margin: 10px 4px 2px 4px; }
.vb-note { font-size: 0.88em; opacity: 0.65; }
.vb-row { padding: 10px 16px; border-left: 3px solid transparent; }
.vb-row.changed { border-left-color: #3584e4; background-color: alpha(#3584e4, 0.07); }
.vb-row.invalid { border-left-color: #e5484d; background-color: alpha(#e5484d, 0.08); }
.vb-sep { opacity: 0.5; }
.vb-title { font-weight: 600; }
.vb-badge { font-size: 0.72em; font-weight: 700; padding: 1px 7px; border-radius: 999px;
            color: #b5835a; background-color: alpha(#e5a50a, 0.16); }
.vb-entry { font-feature-settings: "tnum"; min-width: 110px; }
.vb-unit { opacity: 0.7; min-width: 30px; }
.vb-delta { color: #3584e4; font-weight: 700; font-feature-settings: "tnum"; }
.vb-error { color: #e5484d; font-weight: 600; }
.vb-bar { padding: 10px 18px 12px 18px; border-top: 1px solid alpha(currentColor, 0.12);
          background-color: alpha(currentColor, 0.03); }
.vb-change-name { opacity: 0.85; }
.vb-change-value { font-weight: 700; font-feature-settings: "tnum"; }
.vb-welcome { padding: 28px 18px; }
"""
_css_installed = False


def install_css():
    global _css_installed
    display = Gdk.Display.get_default()
    if _css_installed or display is None:
        return
    provider = Gtk.CssProvider()
    if hasattr(provider, 'load_from_string'):
        provider.load_from_string(CSS)
    else:
        provider.load_from_data(CSS.encode())
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_installed = True


_desktop_theme = None


def apply_theme(theme):
    """Use the light or dark GTK style for every window; None restores the desktop's choice."""
    global _desktop_theme
    settings = Gtk.Settings.get_default()
    if settings is None:
        return
    names = {p.name for p in Gtk.Settings.list_properties()}
    scheme = 'gtk-interface-color-scheme' in names and hasattr(Gtk, 'InterfaceColorScheme')
    key = 'gtk-interface-color-scheme' if scheme else 'gtk-application-prefer-dark-theme'
    if _desktop_theme is None:
        _desktop_theme = settings.get_property(key)
    if theme is None:
        value = _desktop_theme
    elif scheme:
        value = Gtk.InterfaceColorScheme.DARK if theme == 'dark' else Gtk.InterfaceColorScheme.LIGHT
    else:
        value = theme == 'dark'
    settings.set_property(key, value)


def label(text='', *, wrap=False, css=(), xalign=0, selectable=True):
    widget = Gtk.Label(label=text, xalign=xalign)
    widget.set_wrap(wrap)
    widget.set_selectable(selectable)
    for name in css:
        widget.add_css_class(name)
    return widget


def clear(box):
    child = box.get_first_child()
    while child:
        following = child.get_next_sibling()
        box.remove(child)
        child = following


def texts(widget):
    """Every label text under a widget, depth first (tests, accessibility checks)."""
    found = [widget.get_text()] if isinstance(widget, Gtk.Label) else []
    child = widget.get_first_child()
    while child:
        found.extend(texts(child))
        child = child.get_next_sibling()
    return found


class FlagSwitch(Gtk.Switch):
    """Gtk.Switch speaking the text surface of the field entries: a flag field stores 0 and 1."""

    def get_text(self):
        return '1' if self.get_active() else '0'

    def set_text(self, text):
        self.set_active(str(text).strip() == '1')


class EditorWindow(Gtk.ApplicationWindow):
    def __init__(self, application, initial_path=None, language='en', file_dialog='auto', theme='auto'):
        self.text = Messages(language)
        self.language = language
        self.file_dialog = resolve_file_dialog(file_dialog)
        self.file_picker = None
        super().__init__(application=application, title=self.text('window_title'))
        install_css()
        apply_theme(resolve_theme(theme))
        self.theme = theme
        self.set_default_size(760, 920)
        self.controller = Controller()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='vbios-editor')
        self.generation = 0
        self.busy = False
        self.saving = False
        self.dirty = False
        self.closed = False
        self.verifying = False
        self.verify_source = 0
        self.quiet_verify = False
        self.input_revision = 0
        self.entries = {}
        self.rows = {}
        self.readonly_rows = {}
        self.shunt_notes = {}
        self.pending_text = {}
        self.hidden_text = {}
        self.connect('close-request', self._close)

        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        self.open_button = self._button(self.text('open'), 'open')
        header.pack_start(self.open_button)
        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        heading.set_valign(Gtk.Align.CENTER)
        title = label(self.text('app_title'), selectable=False, xalign=.5)
        title.add_css_class('title')
        self.subtitle = label(self.text('no_file'), selectable=False, xalign=.5, css=('vb-note',))
        heading.append(title)
        heading.append(self.subtitle)
        header.set_title_widget(heading)
        file_menu = Gio.Menu()
        for key, action in (('open_builtin', 'open-builtin'), ('save_builtin', 'save-builtin'),
                            ('open_path', 'open-path'), ('save_path', 'save-path')):
            file_menu.append(self.text(key), 'win.' + action)
        themes = Gio.Menu()
        for mode in ('auto', 'light', 'dark'):
            themes.append(self.text('theme.' + mode), f'win.theme::{mode}')
        file_menu.append_submenu(self.text('theme'), themes)
        self.file_options = Gtk.MenuButton(label=self.text('file_options'))
        self.file_options.set_menu_model(file_menu)
        header.pack_end(self.file_options)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(outer)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        outer.append(scroll)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.add_css_class('vb-content')
        scroll.set_child(content)

        # Device card: identity, integrity and the copy notice.
        device = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        device.add_css_class('vb-card')
        device.add_css_class('vb-device')
        self.product = label(self.text('no_file'), wrap=True, css=('vb-product',), selectable=False)
        device.append(self.product)
        self.chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=6, row_spacing=6)
        self.chips.set_max_children_per_line(8)
        device.append(self.chips)
        self.identity = label(self.text('open_prompt'), wrap=True, css=('vb-note',), selectable=False)
        device.append(self.identity)
        self.integrity = label('', wrap=True, selectable=False)
        device.append(self.integrity)
        device.append(label(self.text('copy_note'), wrap=True, css=('vb-note',), selectable=False))
        content.append(device)

        # Opt-in (XOC-style) fields stay hidden until the user enables this.
        options = Gtk.Box(spacing=10)
        options.set_margin_start(4)
        options.set_margin_end(4)
        advanced_label = label(self.text('show_advanced'), wrap=True, selectable=False)
        advanced_label.set_hexpand(True)
        self.advanced_toggle = Gtk.Switch()
        self.advanced_toggle.set_valign(Gtk.Align.CENTER)
        self.advanced_toggle.set_active(False)
        self.advanced_toggle.update_property([Gtk.AccessibleProperty.LABEL], [self.text('show_advanced')])
        self.advanced_toggle.connect('notify::active', self._advanced_toggled)
        options.append(advanced_label)
        options.append(self.advanced_toggle)
        content.append(options)

        # Display-only shunt-mod multiplier, kept while the window is open:
        # rows read through the 12 V input shunts also show the real amount.
        shunt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        shunt.set_margin_start(4)
        shunt.set_margin_end(4)
        shunt_line = Gtk.Box(spacing=10)
        shunt_label = label(self.text('shunt_multiplier'), wrap=True, selectable=False)
        shunt_label.set_hexpand(True)
        # A plain entry like the fields: '.' decimals whatever the host locale, no scroll-wheel changes.
        self.shunt_entry = Gtk.Entry()
        self.shunt_entry.set_width_chars(9)
        self.shunt_entry.set_max_width_chars(14)
        self.shunt_entry.set_alignment(1.0)
        self.shunt_entry.set_valign(Gtk.Align.CENTER)
        self.shunt_entry.add_css_class('vb-entry')
        self.shunt_entry.set_input_purpose(Gtk.InputPurpose.NUMBER)
        self.shunt_entry.set_text('1')
        self.shunt_entry.update_property([Gtk.AccessibleProperty.LABEL], [self.text('shunt_multiplier')])
        self.shunt_entry.connect('changed', lambda *_: self._mark_shunt())
        shunt_line.append(shunt_label)
        shunt_line.append(self.shunt_entry)
        shunt.append(shunt_line)
        self.shunt_help = label(self.text('shunt_help'), wrap=True, css=('vb-note',), selectable=False)
        self.shunt_help.set_visible(False)
        shunt.append(self.shunt_help)
        content.append(shunt)

        self.field_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.append(self.field_box)
        self._welcome()
        # Copyright, license and no-warranty notice (GPL appropriate legal notices).
        content.append(label(self.text('license_note', version=__version__), wrap=True, xalign=.5,
                             css=('vb-note',), selectable=False))

        # Live changes bar: always visible below the scrolled fields.
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        bar.add_css_class('vb-bar')
        outer.append(bar)
        status_box = Gtk.Box(spacing=10)
        self.spinner = Gtk.Spinner()
        # Shown only while spinning, so the stopped spinner leaves no gap.
        self.spinner.bind_property('spinning', self.spinner, 'visible', 0)
        self.spinner.set_visible(False)
        status_box.append(self.spinner)
        self.status = label(self.text('ready_help'), wrap=True)
        self.status.set_hexpand(True)
        status_box.append(self.status)
        bar.append(status_box)
        self.changes_grid = Gtk.Grid(column_spacing=16, row_spacing=4)
        changes_scroll = Gtk.ScrolledWindow()
        changes_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        changes_scroll.set_propagate_natural_height(True)
        changes_scroll.set_max_content_height(150)
        changes_scroll.set_child(self.changes_grid)
        bar.append(changes_scroll)
        buttons = Gtk.Box(spacing=10)
        self.reset_button = self._button(self.text('reset'), 'reset')
        self.reset_button.set_hexpand(True)
        self.reset_button.set_halign(Gtk.Align.START)
        buttons.append(self.reset_button)
        self.save_button = self._button(self.text('save'), 'save')
        self.save_button.add_css_class('suggested-action')
        buttons.append(self.save_button)
        bar.append(buttons)
        self._actions(application)
        self._show_changes([])
        self._sensitivity()
        if initial_path:
            self.open_path(initial_path)

    def _button(self, text, action):
        button = Gtk.Button(label=text)
        button.set_action_name('win.' + action)
        return button

    def _actions(self, application):
        for name, callback, keys in (
            ('open', self._choose_open, ['<Primary>o']),
            ('save', self._choose_save, ['<Primary>s']),
            ('open-builtin', lambda *_: self._choose_builtin(False), []),
            ('save-builtin', lambda *_: self._choose_builtin(True), []),
            ('open-path', lambda *_: self._choose_path(False), ['<Primary><Shift>o']),
            ('save-path', lambda *_: self._choose_path(True), ['<Primary><Shift>s']),
            ('stage', self._stage, ['<Primary>Return']),
            ('reset', self._reset, ['<Primary>r']),
            ('quit', lambda *_: self.close(), ['<Primary>q']),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', callback)
            self.add_action(action)
            application.set_accels_for_action('win.' + name, keys)
        theme = Gio.SimpleAction.new_stateful('theme', GLib.VariantType.new('s'), GLib.Variant('s', self.theme))
        theme.connect('activate', self._theme_chosen)
        self.add_action(theme)

    def _theme_chosen(self, action, value):
        action.set_state(value)
        self.theme = value.get_string()
        apply_theme(resolve_theme(self.theme))

    def _can_save(self):
        doc = self.controller.document
        return bool(not self.busy and not self.verifying and not self.dirty and doc and doc.proposal)

    def _sensitivity(self):
        doc = self.controller.document
        editable = bool(doc and any(f['editable'] for f in controls(doc.report)))
        for name, enabled in (
            ('open', not self.saving),
            ('save', self._can_save()),
            ('open-builtin', not self.saving), ('open-path', not self.saving),
            ('save-builtin', self._can_save()),
            ('save-path', self._can_save()),
            ('stage', bool(not self.busy and editable)),
            ('reset', bool(doc and not self.saving)),
        ):
            action = self.lookup_action(name)
            if action:
                action.set_enabled(enabled)
        # Live verification never locks the inputs; opening and saving do.
        for entry in self.entries.values():
            entry.set_sensitive(not self.busy)

    def _run(self, operation, work, *, saving=False):
        self._cancel_verify()
        self.generation += 1
        generation = self.generation
        self.busy = True
        self.saving = saving
        self.spinner.start()
        self._status_error(False)
        self.status.set_text(operation)
        self._sensitivity()
        future = self.executor.submit(work)

        def finished(job):
            try:
                result, error = job.result(), None
            except Exception as exc:
                result, error = None, exc
            GLib.idle_add(self._complete, generation, result, error)
        future.add_done_callback(finished)

    def _status_error(self, failed):
        for name in ('error', 'vb-bad'):
            (self.status.add_css_class if failed else self.status.remove_css_class)(name)

    def _error_text(self, error):
        code = getattr(error, 'code', type(error).__name__)
        if 'error.' + code in self.text.catalog:
            message = self.text('error.' + code)
        else:                                # no translation: keep the backend's own explanation
            message = f"{self.text('failure_generic')}: {error}"
        return code, self.text('failure', message=message, code=code)

    def _complete(self, generation, document, error):
        # A newer open/reset owns the view. Old results never replace its state.
        if self.closed or generation != self.generation:
            return GLib.SOURCE_REMOVE
        self.busy = self.saving = False
        self.spinner.stop()
        if error is not None:
            self._status_error(True)
            code, message = self._error_text(error)
            self.status.set_text(message)
            if self.dirty and self.controller.document is not None:
                # The kept document still has unverified edits: resume their
                # check without hiding this error.
                self._schedule_verify(quiet=True)
        else:
            opened = self.controller.document is None or document.original is not self.controller.document.original
            self.controller.document = document
            self.dirty = False
            if opened:
                self.pending_text = {}
                self.hidden_text = {}
                self._render()
            else:
                self._refresh()
            if document.last_saved:
                saved = document.last_saved
                text = self.text('saved', output=saved['output'], manifest=saved['manifest'])
                for key, arguments in loader_messages(saved):
                    text += '\n' + self.text(key, **arguments)
                self.status.set_text(text)
            elif document.proposal:
                self.status.set_text(self.text('verified'))
            else:
                self.status.set_text(self.text('loaded'))
        self._sensitivity()
        return GLib.SOURCE_REMOVE

    def open_path(self, path):
        if not self.closed and not self.saving:
            self._run(self.text('loading'), lambda: open_document(path))

    def _dialog(self, title):
        dialog = Gtk.FileDialog(title=title, modal=True)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        rom_filter = Gtk.FileFilter(name='ROM / BIN')
        rom_filter.add_pattern('*.rom')
        rom_filter.add_pattern('*.bin')
        all_filter = Gtk.FileFilter(name=self.text('all_files'))
        all_filter.add_pattern('*')
        filters.append(rom_filter)
        filters.append(all_filter)
        dialog.set_filters(filters)
        return dialog

    def _choose_open(self, *_):
        if self.file_dialog == 'builtin':
            return self._choose_builtin(False)
        dialog = self._dialog(self.text('open_dialog'))
        dialog.set_accept_label(self.text('open_accept'))
        dialog.open(self, None, self._opened)

    def _opened(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except GLib.Error as exc:
            self._dialog_error(exc)
            return
        path = file.get_path()
        if path:
            self.open_path(path)
        else:
            self.status.set_text(self.text('local_file'))

    def _choose_save(self, *_):
        if self.file_dialog == 'builtin':
            return self._choose_builtin(True)
        dialog = self._dialog(self.text('save_dialog'))
        dialog.set_accept_label(self.text('save_accept'))
        name = Path(self.controller.document.original.name)
        dialog.set_initial_name(name.stem + '-edited' + (name.suffix or '.rom'))
        document = self.controller.document
        dialog.save(self, None, lambda chooser, result: self._saved_path(chooser, result, document))

    def _saved_path(self, dialog, result, expected_document):
        try:
            file = dialog.save_finish(result)
        except GLib.Error as exc:
            self._dialog_error(exc)
            return
        self._accept_save_path(file.get_path(), expected_document)

    def _accept_save_path(self, path, expected_document):
        # Shared by system, built-in and path-only dialogs; no backend bypasses
        # stale-document/preview checks or the editor's no-overwrite writer.
        if self.closed:
            return
        if self.controller.document is not expected_document:
            self.status.set_text(self.text('stale_dialog'))
            return
        if self.busy or self.verifying or self.dirty or not expected_document or not expected_document.proposal:
            self.status.set_text(self.text('preview_first'))
            return
        if not path:
            self.status.set_text(self.text('new_destination'))
            return
        self._run(self.text('saving'), lambda: save_document(expected_document, path), saving=True)

    def _initial_picker_path(self, saving):
        document = self.controller.document
        if document is None:
            return None
        path = Path(document.original.source_path or document.original.name).expanduser().absolute()
        return path.with_name(path.stem + '-edited' + (path.suffix or '.rom')) if saving else path

    def _picker_ready(self, saving):
        if self.closed or self.saving:
            return False
        if saving and not self._can_save():
            self.status.set_text(self.text('preview_first'))
            return False
        if self.file_picker is not None and self.file_picker.get_visible():
            self.file_picker.present()
            return False
        return True

    def _choose_builtin(self, saving):
        if not self._picker_ready(saving):
            return
        document = self.controller.document
        callback = ((lambda path: self._accept_save_path(path, document)) if saving else self.open_path)
        self.file_picker = show_builtin_picker(self, save=saving,
            title=self.text('save_dialog' if saving else 'open_dialog'),
            accept_label=self.text('save_accept' if saving else 'open_accept'),
            cancel_label=self.text('cancel'), all_files_label=self.text('all_files'),
            initial_path=self._initial_picker_path(saving), on_selected=callback)
        return self.file_picker

    def _choose_path(self, saving):
        if not self._picker_ready(saving):
            return
        document = self.controller.document
        callback = ((lambda path: self._accept_save_path(path, document)) if saving else self.open_path)
        self.file_picker = show_path_dialog(self, save=saving,
            title=self.text('save_path' if saving else 'open_path'),
            accept_label=self.text('save_accept' if saving else 'open_accept'),
            cancel_label=self.text('cancel'), path_label=self.text('path_label'),
            hint=self.text('path_hint'), error_label=self.text('path_error'),
            initial_path=self._initial_picker_path(saving), on_selected=callback)
        return self.file_picker

    def _dialog_error(self, error):
        if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
            self.status.set_text(str(error))

    # Live editing ---------------------------------------------------------

    def _values(self):
        doc = self.controller.document
        # Hidden opt-in fields keep their staged or typed values.
        fields = {f['key']: f for f in controls(doc.report)}
        values = {key: value for key, value in doc.changes.items() if key not in self.entries}
        # Rows hold display units (A for mA); the backend gets stored units.
        values.update({key: to_stored(fields[key], text) if key in fields else text
                       for key, text in self.hidden_text.items()})
        values.update({key: to_stored(self.rows[key]['field'], entry.get_text().strip())
                       for key, entry in self.entries.items()})
        return values

    def _input_changed(self, *_):
        self.dirty = True
        self.input_revision += 1
        if self.controller.document is not None:
            self._mark_rows()
            self._show_changes(self._typed_changes(), checking=True)
            self._schedule_verify()
        self._sensitivity()

    def _cancel_verify(self):
        if self.verify_source:
            GLib.source_remove(self.verify_source)
            self.verify_source = 0
        self.verifying = False
        self.spinner.stop()

    def _schedule_verify(self, delay=LIVE_DELAY_MS, *, quiet=False):
        if self.verify_source:
            GLib.source_remove(self.verify_source)
        self.verifying = True
        self.quiet_verify = quiet
        self.spinner.start()
        if not quiet:
            self._status_error(False)
            self.status.set_text(self.text('live_checking'))
        self.verify_source = GLib.timeout_add(delay, self._verify_now)

    def _verify_now(self, *_):
        self.verify_source = 0
        doc = self.controller.document
        if self.closed or doc is None or self.busy:
            self.verifying = False
            self.spinner.stop()
            return GLib.SOURCE_REMOVE
        if any(parse_number(entry.get_text()) is None for entry in self.entries.values()):
            # The rows already say what to fix; the backend is not asked.
            self.verifying = False
            self.spinner.stop()
            if not self.quiet_verify:
                self._status_error(True)
                self.status.set_text(self.text('fix_fields'))
            self._sensitivity()
            return GLib.SOURCE_REMOVE
        values, revision, generation = self._values(), self.input_revision, self.generation
        future = self.executor.submit(stage_document, doc, values)

        def finished(job):
            try:
                result, error = job.result(), None
            except Exception as exc:
                result, error = None, exc
            GLib.idle_add(self._verified, generation, revision, result, error)
        future.add_done_callback(finished)
        return GLib.SOURCE_REMOVE

    def _verified(self, generation, revision, document, error):
        # Results for older inputs are dropped: a newer check is already queued.
        if self.closed or generation != self.generation or revision != self.input_revision:
            return GLib.SOURCE_REMOVE
        self.verifying = False
        self.spinner.stop()
        quiet, self.quiet_verify = self.quiet_verify, False
        if error is not None:
            if not quiet:
                self._status_error(True)
                code = getattr(error, 'code', type(error).__name__)
                message = self.text('error.' + code) if 'error.' + code in self.text.catalog else str(error)
                self.status.set_text(self.text('live_failure', message=message, code=code))
            details = getattr(error, 'details', {}) or {}
            owner = details.get('field') if isinstance(details.get('field'), str) else None
            invalid = {owner} if owner else set()
            # joint_fields lists every requested group; only partners in the
            # failing field's ordering group are marked.
            group = self.rows[owner]['field'].get('ordering_group') if owner in self.rows else None
            if group:
                invalid |= {key for key in details.get('joint_fields') or ()
                            if key in self.rows and self.rows[key]['field'].get('ordering_group') == group}
            self._mark_rows(invalid=invalid, owner=owner, bounds=details.get('bounds'))
            self._show_changes(self._typed_changes())
        else:
            self.controller.document = document
            self.dirty = False
            if not quiet:
                self._status_error(False)
            self._refresh(announce=not quiet)
        self._sensitivity()
        return GLib.SOURCE_REMOVE

    def _stage(self, *_):
        if self.controller.document is None or self.busy:
            return
        self.dirty = True
        self.input_revision += 1
        self._schedule_verify(0)
        self._sensitivity()

    def _advanced_toggled(self, *_):
        if self.controller.document is None:
            return
        # Keep values typed but not yet verified, including those of fields
        # the toggle hides, across the re-render.
        typed = {key: entry.get_text() for key, entry in self.entries.items()}
        self.pending_text = {**self.hidden_text, **typed}
        self._render()
        if self.dirty:
            self._mark_rows()
            self._show_changes(self._typed_changes(), checking=self.verifying)
        self._sensitivity()

    def _reset(self, *_):
        self._cancel_verify()
        self.generation += 1
        self.busy = False
        self.controller.document = reset_document(self.controller.document)
        self.dirty = False
        self.pending_text = {}
        self.hidden_text = {}
        self._render()
        self._status_error(False)
        self.status.set_text(self.text('reset_done'))
        self._sensitivity()

    # Rendering ------------------------------------------------------------

    def _welcome(self):
        clear(self.field_box)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        card.add_css_class('vb-card')
        card.add_css_class('vb-welcome')
        card.append(label(self.text('welcome'), wrap=True, xalign=.5))
        button = self._button(self.text('open'), 'open')
        button.add_css_class('suggested-action')
        button.set_halign(Gtk.Align.CENTER)
        card.append(button)
        self.field_box.append(card)

    def _chip(self, text):
        chip = label(text, css=('vb-chip',), selectable=False)
        self.chips.append(chip)

    def _render_identity(self, doc):
        report = doc.report
        arch = report.get('architecture', {})
        name = Path(doc.original.name).name
        self.subtitle.set_text(name)
        self.product.set_text(arch.get('product') or name)
        clear(self.chips)
        for text in (name, f"{report['size']:,} bytes", f"PCI {report.get('pci_device') or self.text('unknown')}",
                     f"BIOS {', '.join(report.get('versions', [])) or self.text('unknown_version')}",
                     arch.get('family', self.text('unknown'))):
            self._chip(text)
        self.identity.set_text(self.text('format', format=report.get('format') or self.text('unrecognized')))
        valid = report.get('integrity', {}).get('valid')
        summary = self.text({True: 'integrity_verified', False: 'integrity_failed', None: 'integrity_unknown'}[valid])
        mark = {True: '✓ ', False: '✗ ', None: ''}[valid]
        self.integrity.set_text(mark + self.text('integrity', summary=summary))
        for name in ('vb-ok', 'vb-bad', 'error'):
            self.integrity.remove_css_class(name)
        if valid is True:
            self.integrity.add_css_class('vb-ok')
        elif valid is False:
            self.integrity.add_css_class('vb-bad')
            self.integrity.add_css_class('error')

    def _section(self, name):
        heading = label(self.text('section.' + name), css=('vb-section',), selectable=False)
        self.field_box.append(heading)
        if name == 'voltage':
            self.field_box.append(label(self.text('section.voltage_note'), wrap=True, css=('vb-note',)))
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class('vb-card')
        self.field_box.append(card)
        return card

    def _editable_row(self, field, text):
        title, experimental = row_title(field, self.language)
        units = display_units(field)
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        row.add_css_class('vb-row')
        top = Gtk.Box(spacing=12)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        left.set_hexpand(True)
        title_line = Gtk.Box(spacing=8)
        name = label(title, wrap=True, css=('vb-title',))
        title_line.append(name)
        if experimental:
            badge = label(self.text('badge.experimental'), css=('vb-badge',), selectable=False)
            badge.set_valign(Gtk.Align.CENTER)
            title_line.append(badge)
        left.append(title_line)
        sub = [self.text('original', value=number(to_display(field, field['current'])), units=units).rstrip()]
        hint = windows_value(field, field['current'])
        if hint is not None:
            sub.append(self.text('windows_equivalent', value=hint))
        left.append(label(' · '.join(sub), wrap=True, css=('vb-note',)))
        top.append(left)
        if field['units'] == 'flag':
            # A 0/1 flag reads better as a switch than as a number entry.
            entry = FlagSwitch()
            entry.set_valign(Gtk.Align.CENTER)
            entry.set_halign(Gtk.Align.CENTER)
        else:
            entry = Gtk.Entry()
            entry.set_width_chars(9)
            entry.set_max_width_chars(14)
            entry.set_alignment(1.0)
            entry.set_valign(Gtk.Align.CENTER)
            entry.add_css_class('vb-entry')
            entry.set_input_purpose(Gtk.InputPurpose.NUMBER)
        entry.set_text(text)
        entry.update_property([Gtk.AccessibleProperty.LABEL], [field_label(field, self.language)])
        entry.set_tooltip_text((field['key'] + ' · ' + units).rstrip(' ·'))
        entry.connect('notify::active' if isinstance(entry, Gtk.Switch) else 'changed', self._input_changed)
        name.set_mnemonic_widget(entry)
        top.append(entry)
        unit = label(units, css=('vb-unit',), selectable=False)
        unit.set_valign(Gtk.Align.CENTER)
        top.append(unit)
        row.append(top)
        delta = label('', xalign=1, css=('vb-delta',))
        delta.set_visible(False)
        row.append(delta)
        self._shunt_note(row, field)
        self.entries[field['key']] = entry
        self.rows[field['key']] = dict(row=row, delta=delta, field=field)
        return row

    def _readonly_row(self, field):
        title, _ = row_title(field, self.language)
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        row.add_css_class('vb-row')
        top = Gtk.Box(spacing=12)
        name = label(title, wrap=True, css=('vb-title',))
        name.set_hexpand(True)
        top.append(name)
        value = number(to_display(field, field['current'])) if field['current'] is not None else None
        units = display_units(field) if value is not None and field['units'] not in ('unknown', 'index') else ''
        top.append(label(f"{value if value is not None else self.text('unknown')} {units}".strip(), css=('vb-note',)))
        row.append(top)
        row.append(label(read_only_reason(field, self.language), wrap=True, css=('vb-note',)))
        self._shunt_note(row, field)
        self.readonly_rows[field['key']] = row
        return row

    def _shunt_note(self, row, field):
        if shunt_scaled(field):
            note = label('', wrap=True, xalign=1, css=('vb-note',))
            note.set_visible(False)
            row.append(note)
            self.shunt_notes[field['key']] = (note, field)

    def _mark_shunt(self):
        """Real amounts for the shunt multiplier; display only, nothing is staged or verified."""
        amount = parse_number(self.shunt_entry.get_text())
        (self.shunt_entry.add_css_class if amount is None else self.shunt_entry.remove_css_class)('error')
        # 1 or less is off; at most x10, two decimals.
        factor = round(min(amount, Decimal(10)), 2) if amount is not None and amount > 1 else Decimal(1)
        for key, (note, field) in self.shunt_notes.items():
            value = self.entries[key].get_text() if key in self.entries else to_display(field, field['current'])
            real = shunt_real(field, value, factor)
            if real is not None:
                note.set_text(self.text('shunt_real', value=real, units=display_units(field), factor=number(factor)))
            note.set_visible(real is not None)
        self.shunt_help.set_visible(factor > 1)

    def _render(self):
        doc = self.controller.document
        report = doc.report
        self._render_identity(doc)
        clear(self.field_box)
        self.entries.clear()
        self.rows.clear()
        self.readonly_rows.clear()
        self.shunt_notes.clear()
        fields = controls(report)
        if not fields:
            self.field_box.append(label(self.text('no_fields'), wrap=True))
        hidden = technical_field_keys(report)
        if not self.advanced_toggle.get_active():
            hidden |= opt_in_field_keys(report)
        pending, self.pending_text = self.pending_text, {}
        visible = [f for f in section_order(fields) if f['key'] not in hidden]
        card, current = None, None
        for field in visible:
            if not field['editable']:
                continue
            section = field_section(field)
            if section != current:
                card, current = self._section(section), section
            elif card.get_last_child() is not None:
                separator = Gtk.Separator()
                separator.add_css_class('vb-sep')
                card.append(separator)
            staged = doc.changes.get(field['key'], field['current'])
            text = pending.get(field['key'], number(to_display(field, staged)))
            card.append(self._editable_row(field, text))
        readonly = [f for f in visible if not f['editable']]
        if readonly:
            expander = Gtk.Expander(label=self.text('section.readonly', count=len(readonly)))
            expander.set_margin_top(6)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.add_css_class('vb-card')
            box.set_margin_top(6)
            for i, field in enumerate(readonly):
                if i:
                    separator = Gtk.Separator()
                    separator.add_css_class('vb-sep')
                    box.append(separator)
                box.append(self._readonly_row(field))
            expander.set_child(box)
            self.field_box.append(expander)
        self.hidden_text = {key: value for key, value in pending.items() if key not in self.entries}
        self._refresh()

    def _refresh(self, announce=True):
        """Rows, change list and details for the current document; entries keep their text."""
        doc = self.controller.document
        self._mark_rows()
        if self.dirty:
            self._show_changes(self._typed_changes(), checking=self.verifying)
        elif doc.proposal:
            preview = primary_preview(doc)
            self._show_changes([(row_title(before, self.language)[0], to_display(before, before['current']),
                                 to_display(after, after['current']), display_units(after))
                                for before, after in preview])
            if announce and not self.verifying and not self.busy:
                self.status.set_text(self.text('live_ok', count=len(preview),
                                               bytes=doc.proposal.manifest['changed_bytes'])
                                     if preview else self.text('live_same'))
        else:
            self._show_changes([])

    def _typed_changes(self):
        """Changes as typed, before verification: (label, before, after, units)."""
        changes = []
        for key, info in self.rows.items():
            field = info['field']
            amount = parse_number(self.entries[key].get_text())
            current = to_display(field, field['current'])
            if amount is not None and amount != current:
                changes.append((row_title(field, self.language)[0], current, amount, display_units(field)))
        fields = {f['key']: f for f in controls(self.controller.document.report)}
        # Staged values are stored units; typed hidden values are display units.
        hidden = {key: to_display(fields[key], value) for key, value in self.controller.document.changes.items()
                  if key in fields}
        hidden.update({key: parse_number(text) for key, text in self.hidden_text.items() if key in fields})
        for key, value in hidden.items():
            if key not in self.rows and value is not None:
                changes.append((row_title(fields[key], self.language)[0], to_display(fields[key], fields[key]['current']),
                                value, display_units(fields[key])))
        return changes

    def _mark_rows(self, invalid=(), owner=None, bounds=None):
        for key, info in self.rows.items():
            field, row, delta = info['field'], info['row'], info['delta']
            amount, problem = classify_number(self.entries[key].get_text())
            current = to_display(field, field['current'])
            row.remove_css_class('changed')
            row.remove_css_class('invalid')
            delta.remove_css_class('vb-error')
            message = ''
            if amount is None or current is None:
                row.add_css_class('invalid')
                delta.add_css_class('vb-error')
                message = self.text(problem or 'out_of_range')
            elif amount != current:
                row.add_css_class('changed')
                change = amount - current
                sign = '+' if change > 0 else ''
                message = f"{number(current)} → {number(amount)} {display_units(field)}  ({sign}{number(change)})"
                hint = windows_value(field, amount)
                if hint is not None:
                    message += ' · ' + self.text('windows_short', value=hint)
            if key in invalid:
                row.add_css_class('invalid')
                delta.add_css_class('vb-error')
                # Bounds belong to the failing field only; partners get the order hint.
                message = self.text('order_hint')
                if key == owner and isinstance(bounds, dict):
                    minimum, maximum = to_display(field, bounds.get('minimum')), to_display(field, bounds.get('maximum'))
                    # Encoding limits (about 2^31) are not a useful maximum to show.
                    key_text = 'range_hint' if maximum is not None and abs(maximum) < 10 ** 6 else 'range_min'
                    message = self.text(key_text, minimum=number(minimum), maximum=number(maximum),
                                        units=display_units(field))
            delta.set_text(message)
            delta.set_visible(bool(message))
        self._mark_shunt()

    def _show_changes(self, changes, *, checking=False):
        clear(self.changes_grid)
        if not changes:
            self.changes_grid.attach(label(self.text('live_none'), wrap=True, css=('vb-note',)), 0, 0, 2, 1)
            return
        for i, (name, before, after, units) in enumerate(changes):
            left = label(name, wrap=True, css=('vb-change-name',))
            left.set_hexpand(True)
            self.changes_grid.attach(left, 0, i, 1, 1)
            value = label(f'{number(before)} → {number(after)} {units}', xalign=1, css=('vb-change-value',))
            if checking:
                value.add_css_class('vb-note')
            self.changes_grid.attach(value, 1, i, 1, 1)

    def preview_text(self):
        """Plain text of the change list, for tests and copying."""
        return '\n'.join(texts(self.changes_grid))

    def _close(self, *_):
        self.closed = True
        self._cancel_verify()
        if self.file_picker is not None:
            self.file_picker.destroy()
        self.generation += 1
        self.executor.shutdown(wait=False, cancel_futures=True)
        return False


def run(args):
    app = Gtk.Application(application_id='org.nvidia_vbios.Editor', flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect('activate', lambda application: EditorWindow(
        application, args.rom, args.lang, getattr(args, 'file_dialog', 'auto'), getattr(args, 'theme', 'auto')).present())
    return app.run([sys.argv[0]])


def main(argv=None):
    return run(parse_arguments(argv))
