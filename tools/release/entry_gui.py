"""Release entry point: the GTK editor, or the command line when a CLI command is given."""
import os
import sys

# The compiled runtime cannot use CPython's debug allocator: restart without it.
if os.name != 'nt' and (os.environ.get('PYTHONDEVMODE') or os.environ.get('PYTHONMALLOC')):
    os.execve('/proc/self/exe', sys.argv,
              {k: v for k, v in os.environ.items() if k not in ('PYTHONDEVMODE', 'PYTHONMALLOC')})

CLI_COMMANDS = {'inspect', 'fields', 'verify', 'edit', 'normalize', '--version', '--json'}


def prepare_gtk(here):
    """Point PyGObject and GTK at the files shipped next to the binary."""
    sys.path.insert(0, here)
    typelibs = os.path.join(here, 'girepository')
    if os.path.isdir(typelibs):
        os.environ['GI_TYPELIB_PATH'] = typelibs + os.pathsep + os.environ.get('GI_TYPELIB_PATH', '')
    if os.name == 'nt':
        # GTK's DLLs come from the runtime folder only (then the system folders);
        # GObject loads some of them by name.
        import ctypes
        ctypes.windll.kernel32.SetDefaultDllDirectories(0x1000)  # LOAD_LIBRARY_SEARCH_DEFAULT_DIRS
        os.add_dll_directory(here)
        share = os.path.join(here, 'share')
        if os.path.isdir(share):
            os.environ['GSETTINGS_SCHEMA_DIR'] = os.path.join(share, 'glib-2.0', 'schemas')
            os.environ['XDG_DATA_DIRS'] = share + os.pathsep + os.environ.get('XDG_DATA_DIRS', '')
        # GTK's OpenGL renderer aborts (exit code 3) on some NVIDIA desktops; the
        # software cairo renderer avoids the GPU driver and its overlay layers.
        os.environ.setdefault('GSK_RENDERER', 'cairo')


def gtk_runtime():
    """Linux: next to the binary. Windows: the runtime unpacked with the program, or
    the replacement folder named by NVBIOS_GTK_RUNTIME (modified LGPL libraries)."""
    if os.name != 'nt':
        return os.path.dirname(os.path.realpath('/proc/self/exe'))
    replacement = os.environ.get('NVBIOS_GTK_RUNTIME')
    if replacement and os.path.isdir(replacement):
        return replacement
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gtk')


def run():
    if len(sys.argv) > 1 and sys.argv[1] in CLI_COMMANDS:
        from nvidia_vbios.cli import main
        return main()
    prepare_gtk(gtk_runtime())
    from nvidia_vbios.gui import main
    return main(sys.argv[1:])


try:
    code = run()
    if sys.stdout:
        sys.stdout.flush()
except KeyboardInterrupt:
    code = 130
except BrokenPipeError:  # output closed early, e.g. piped into head
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    code = 1
except Exception as exc:  # unexpected: one line, no traceback
    print(f'nvbios-gui: unexpected error: {type(exc).__name__}: {exc}', file=sys.stderr)
    code = 70
raise SystemExit(code)
