"""Versioned JSON command line for offline VBIOS editing."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from . import __version__

LICENSE_NOTICE = ('Copyright (C) 2026 panchovix\n'
                  'License GPL-3.0-or-later <https://www.gnu.org/licenses/gpl-3.0.html>\n'
                  'This is free software: you are free to change and redistribute it.\n'
                  'There is NO WARRANTY, to the extent permitted by law.')


class UsageError(ValueError):
    code = 'INVALID_ARGUMENT'


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def emit(value):
    print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))


def changes_from_args(args):
    changes = {}
    if args.changes:
        try:
            changes = json.loads(args.changes.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise UsageError(f'cannot read changes JSON: {exc}') from exc
        if not isinstance(changes, dict):
            raise UsageError('changes JSON must be an object mapping field keys to values')
    for assignment in args.set_values:
        key, separator, text = assignment.partition('=')
        if not separator or not key or not text:
            raise UsageError('--set requires FIELD=VALUE')
        if key in changes:
            raise UsageError(f'field supplied more than once: {key}')
        try:
            value = json.loads(text)
        except ValueError:
            value = text
        changes[key] = value
    if not changes:
        raise UsageError('provide at least one --set or a changes JSON object')
    return changes


def parser():
    # Raw text keeps the line breaks of the --version notice.
    root = Parser(prog='nvbios', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    root.add_argument('--version', action='version', version=f'nvbios {__version__}\n{LICENSE_NOTICE}')
    root.add_argument('--json', action='store_true', help='JSON is the default command output')
    commands = root.add_subparsers(dest='command', required=True)
    for name, help_text in [('inspect', 'inspect identity, format, integrity and capabilities'),
                            ('fields', 'list typed editable and read-only fields'),
                            ('verify', 'validate all integrity checks known for this format')]:
        p = commands.add_parser(name, help=help_text)
        p.add_argument('input', type=Path)
        p.add_argument('--json', action='store_true')
    p = commands.add_parser('memory', help='read-only memory configurations, clock bands, timings and board profile')
    p.add_argument('input', type=Path)
    p.add_argument('--compare', type=Path, metavar='ROM', help='report per section whether ROM is identical or differs')
    p.add_argument('--raw', action='store_true', help='add the undecoded board profile bytes (with --compare: '
                                                      'both reports)')
    p.add_argument('--json', action='store_true')
    p = commands.add_parser('edit', help='stage changes and save a new archival ROM')
    root.intermixed = {'edit': p}
    p.add_argument('input', type=Path)
    p.add_argument('output', type=Path, nargs='?')
    p.add_argument('--set', dest='set_values', action='append', default=[], metavar='FIELD=VALUE')
    p.add_argument('--changes', type=Path, help='JSON object containing field values')
    p.add_argument('--expect-sha256', help='require this source SHA-256')
    p.add_argument('--dry-run', action='store_true', help='validate and show the manifest without writing')
    p.add_argument('--json', action='store_true')
    p = root.intermixed['import'] = commands.add_parser('import', help='copy the editable values of chosen sections '
                                                                       'from another ROM of the same family and save '
                                                                       'a new archival ROM')
    p.add_argument('input', type=Path, help='ROM to change')
    p.add_argument('donor', type=Path, help='ROM to copy the values from')
    p.add_argument('output', type=Path, nargs='?', help='new ROM to write (not needed with --dry-run)')
    p.add_argument('--sections', required=True, metavar='LIST',
                   help='comma-separated: power, voltage, clocks, current, fans')
    p.add_argument('--include-opt-in', action='store_true', help='also import opt-in (advanced) fields')
    p.add_argument('--dry-run', action='store_true', help='report what would be imported without writing')
    p.add_argument('--json', action='store_true')
    p = commands.add_parser('normalize', help='export a validated single-chain driver payload')
    p.add_argument('input', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--representation', choices=('ada-relocated-v1', 'ada-relocated-v2', 'ampere-relocated-v1',
                                                'turing-e0-end-v1'),
                   help='Ada: relocate tables so the loaded image fits the 512 KiB GSP limit; v1: reviewed '
                        'layouts only; v2: experimental, layout derived from the ROM, refused unless verified. '
                        'ampere-relocated-v1: experimental GA102-GA107 export without the EFI image. '
                        'turing-e0-end-v1: experimental Turing export whose chain ends at its last data image')
    p.add_argument('--json', action='store_true')
    commands.add_parser('gui', help='open the standalone graphical VBIOS editor', add_help=False)
    return root


def execute(args):
    from .editor import VbiosError, inspect, load, edit, import_fields, save, normalize, normalize_manifest
    if args.command in ('inspect', 'fields', 'verify'):
        report = inspect(args.input)
        if args.command == 'fields':
            return {key: report[key] for key in ('schema_version', 'sha256', 'architecture', 'format', 'capabilities', 'fields', 'diagnostics')}
        if args.command == 'verify' and report['integrity'].get('valid') is not True:
            raise VbiosError('INTEGRITY_NOT_VERIFIED', 'full known-format integrity could not be verified', details=report)
        return report
    source = load(args.input)
    if args.command == 'memory':
        from .rom.memory import compare, memory_report
        report = memory_report(source, raw=args.raw or args.compare is not None)
        if args.compare is None:
            return report
        other = memory_report(load(args.compare), raw=True)
        return dict(compare(report, other), reports=[report, other]) if args.raw else compare(report, other)
    if args.command == 'normalize':
        result = normalize(source, representation=args.representation)
        return save(result, args.output, manifest=normalize_manifest(source, result, args.representation, args.input))
    if args.command == 'import':
        if not args.dry_run and args.output is None:
            raise UsageError('provide an output path or --dry-run')
        report, result = import_fields(source, load(args.donor), [s.strip() for s in args.sections.split(',')],
                                       include_opt_in=args.include_opt_in, dry_run=args.dry_run)
        report['manifest'] = None if result is None else result.to_dict()
        if not args.dry_run:
            if result is None:
                raise VbiosError('NOTHING_TO_IMPORT', 'no value of these sections can be imported from the donor',
                                 details=report)
            report['publication'] = save(result, args.output)
        return report
    if args.expect_sha256 and source.sha256 != args.expect_sha256.lower():
        raise VbiosError('SOURCE_HASH_MISMATCH', 'source SHA-256 differs from --expect-sha256')
    if not args.dry_run and args.output is None:
        raise UsageError('provide an output path or --dry-run')
    result = edit(source, changes_from_args(args), dry_run=args.dry_run)
    report = result.to_dict()
    if not args.dry_run:
        report['publication'] = save(result, args.output)
    return report


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Keep forwarding independent of the offline editor argument grammar.
    if argv and argv[0] == 'gui':
        from .gui import main as gui_main
        return gui_main(argv[1:])
    operation = None
    try:
        root = parser()
        lead = 0
        while argv[lead:lead + 1] == ['--json']:
            lead += 1
        if argv[lead:lead + 1] and argv[lead] in root.intermixed and '--' not in argv[lead + 1:]:
            # OUTPUT may follow the options. Older argparse (Python 3.11, and 3.12.3 in the Linux build image)
            # leaves it unrecognized there, so edit and import parse their own arguments intermixed; that
            # parser drops a '--' separator, so arguments with one keep the plain parse.
            args = root.intermixed[argv[lead]].parse_intermixed_args(argv[lead + 1:])
            args.command = argv[lead]
        else:
            args = root.parse_args(argv)
        operation = args.command
        result = execute(args)
        emit(dict(schema_version=1, ok=True, operation=operation, result=result))
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        emit(dict(schema_version=1, ok=False, operation=operation,
                  error=dict(code=getattr(exc, 'code', 'IO_ERROR' if isinstance(exc, OSError) else 'OPERATION_FAILED'),
                             message=str(exc), details=getattr(exc, 'details', {}))))
        return 2
    except KeyboardInterrupt:
        emit(dict(schema_version=1, ok=False, operation=operation,
                  error=dict(code='INTERRUPTED', message='operation interrupted', details={})))
        return 130
