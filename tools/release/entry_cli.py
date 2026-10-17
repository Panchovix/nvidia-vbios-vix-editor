"""Release entry point: the JSON command line without the GTK GUI."""
import os
import sys

# The compiled runtime cannot use CPython's debug allocator: restart without it.
if os.name != 'nt' and (os.environ.get('PYTHONDEVMODE') or os.environ.get('PYTHONMALLOC')):
    os.execve('/proc/self/exe', sys.argv,
              {k: v for k, v in os.environ.items() if k not in ('PYTHONDEVMODE', 'PYTHONMALLOC')})


def run():
    if len(sys.argv) > 1 and sys.argv[1] == 'gui':
        print('This is the command-line build. Run nvbios-gui from the release package for the editor window.',
              file=sys.stderr)
        return 2
    from nvidia_vbios.cli import main
    return main()


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
    print(f'nvbios: unexpected error: {type(exc).__name__}: {exc}', file=sys.stderr)
    code = 70
raise SystemExit(code)
