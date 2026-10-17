"""Offline graphical editor. GTK is imported only when main is called."""


def main(argv=None):
    from .arguments import parse_arguments
    from .i18n import Messages
    args = parse_arguments(argv)
    try:
        from .app import run
    except (ImportError, ValueError) as exc:
        import sys
        print(Messages(args.lang)('missing_gtk', error=exc), file=sys.stderr)
        return 2
    return run(args)


__all__ = ['main']
