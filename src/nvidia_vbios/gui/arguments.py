"""GTK-free language and ROM argument routing for all GUI launchers."""
import argparse
import os
import sys
from .i18n import Messages

THEMES = ('auto', 'light', 'dark')


def parse_arguments(argv=None):
    # Resolve explicit language before constructing localized help. The default
    # is always English, including when LANG/LC_ALL request another language.
    language_parser = argparse.ArgumentParser(add_help=False)
    language_parser.add_argument('--lang', choices=('en', 'es'), default='en')
    initial, _ = language_parser.parse_known_args(argv)
    text = Messages(initial.lang)
    class LocalizedHelp(argparse.HelpFormatter):
        def _format_usage(self, usage, actions, groups, prefix=None):
            return super()._format_usage(usage, actions, groups, prefix or text('cli_usage'))

    parser = argparse.ArgumentParser(description=text('cli_description'), add_help=False,
                                     formatter_class=LocalizedHelp)
    parser._positionals.title = text('cli_positionals')
    parser._optionals.title = text('cli_options')
    parser.add_argument('-h', '--help', action='help', help=text('cli_help'))
    parser.add_argument('--lang', choices=('en', 'es'), default='en', help=text('cli_language'))
    parser.add_argument('--file-dialog', choices=('auto', 'builtin', 'system'), default='auto', help=text('cli_file_dialog'))
    parser.add_argument('--theme', choices=THEMES, default='auto', help=text('cli_theme'))
    parser.add_argument('rom', nargs='?', help=text('cli_rom'))
    return parser.parse_args(argv)


def resolve_file_dialog(mode='auto', environment=None):
    """Choose the in-process picker for SSH without changing desktop settings."""
    if mode not in ('auto', 'builtin', 'system'):
        raise ValueError('unknown file dialog mode')
    if mode != 'auto':
        return mode
    environment = os.environ if environment is None else environment
    return 'builtin' if any(environment.get(key) for key in ('SSH_CONNECTION', 'SSH_CLIENT', 'SSH_TTY')) else 'system'


def windows_dark_mode():
    """True when Windows asks apps for the dark mode (Settings > Personalization > Colors)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            value, kind = winreg.QueryValueEx(key, 'AppsUseLightTheme')
    except (ImportError, OSError):
        return False
    return kind == winreg.REG_DWORD and value == 0


def resolve_theme(mode='auto', platform=None, dark_mode=windows_dark_mode):
    """'light' or 'dark' for the window, or None to keep the desktop's GTK theme.

    auto follows the Windows app mode; on other systems GTK already follows the desktop.
    """
    if mode not in THEMES:
        raise ValueError('unknown theme')
    if mode != 'auto':
        return mode
    if (platform or sys.platform) == 'win32':
        return 'dark' if dark_mode() else 'light'
    return None
