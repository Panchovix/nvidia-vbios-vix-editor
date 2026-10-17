"""Collect complete license texts for the release's third-party notices."""
import hashlib
from importlib import metadata
from pathlib import Path
import re
import shutil
import sys


class NoticeError(RuntimeError):
    pass


def copy_nuitka_license(destination, distribution=None):
    distribution = distribution if distribution is not None else metadata.distribution('Nuitka')
    candidates = []
    for entry in distribution.files or ():
        path = Path(str(entry))
        if not any(part.endswith('.dist-info') for part in path.parts):
            continue
        if path.name.lower() not in {'license', 'license.txt', 'license.rst', 'copying'}:
            continue
        source = Path(distribution.locate_file(entry))
        text = source.read_text()
        if (re.search(r'Apache\s+License\s+Version 2\.0', text)
                and 'TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION' in text
                and 'END OF TERMS AND CONDITIONS' in text):
            candidates.append(source)
    if len(candidates) != 1:
        raise NoticeError(f'expected one canonical Apache 2.0 Nuitka distribution license, found {len(candidates)}')
    shutil.copyfile(candidates[0], destination / 'nuitka.LICENSE')


# Reviewed full texts of Nuitka 4.x (SHA-256 of the files in its .dist-info). A Nuitka
# release with other texts fails the build until they are reviewed and added here.
NUITKA_AGPL_TEXTS = {
    '0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0': 'GNU AGPL v3',
}
NUITKA_RUNTIME_EXCEPTIONS = {
    '20ff0ae581adf436a7b06e50e67a6c8913aec1ea4e60dba138d0a0bee7ee520c': 'Nuitka Runtime Library Exception 1.0',
}
ZSTD_LICENSE = 'nuitka/build/inline_copy/zstd/LICENSE.txt'


def _is_apache(text):
    return bool(re.search(r'Apache\s+License\s+Version 2\.0', text)
                and 'TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION' in text
                and 'END OF TERMS AND CONDITIONS' in text)


def copy_nuitka_licenses(destination, distribution=None, agpl_texts=None, runtime_exceptions=None):
    """Copy Nuitka's own license files and return the terms of its compiled runtime.

    Every license or notice file in Nuitka's .dist-info is classified first. The
    accepted sets are one Apache 2.0 text (Nuitka 2.x), or one reviewed AGPLv3 text
    with one reviewed Nuitka Runtime Library Exception (Nuitka 4.x, which lets
    compiled programs be conveyed under any terms), each with at most one NOTICE.
    Anything else, unknown, missing or ambiguous, fails.
    """
    agpl_texts = NUITKA_AGPL_TEXTS if agpl_texts is None else agpl_texts
    runtime_exceptions = NUITKA_RUNTIME_EXCEPTIONS if runtime_exceptions is None else runtime_exceptions
    distribution = distribution if distribution is not None else metadata.distribution('Nuitka')
    found = {'apache': [], 'agpl': [], 'exception': [], 'notice': [], 'unknown': []}
    for entry in distribution.files or ():
        path = Path(str(entry))
        name = path.name.lower()
        if not any(part.endswith('.dist-info') for part in path.parts):
            continue
        if not name.startswith(('license', 'licence', 'copying', 'notice')):
            continue
        source = Path(distribution.locate_file(entry))
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if name.startswith('notice'):
            kind = 'notice'
        elif digest in agpl_texts:
            kind = 'agpl'
        elif digest in runtime_exceptions:
            kind = 'exception'
        elif _is_apache(raw.decode('utf-8', 'replace')):
            kind = 'apache'
        else:
            kind = 'unknown'
        found[kind].append((source, digest))
    counts = {kind: len(items) for kind, items in found.items()}
    licenses = (counts['apache'], counts['agpl'], counts['exception'])
    if counts['unknown'] or counts['notice'] > 1:
        licenses = None
    if licenses == (1, 0, 0):
        terms = 'the Apache License 2.0'
        copies = [(found['apache'][0][0], 'nuitka.LICENSE')]
    elif licenses == (0, 1, 1):
        terms = (f"the {agpl_texts[found['agpl'][0][1]]} with the "
                 f"{runtime_exceptions[found['exception'][0][1]]}")
        copies = [(found['agpl'][0][0], 'nuitka.LICENSE'), (found['exception'][0][0], 'nuitka.LICENSE-RUNTIME')]
    else:
        raise NoticeError('expected one Apache 2.0 license, or one reviewed AGPLv3 text with one reviewed Nuitka '
                          f'Runtime Library Exception, found {counts}')
    copies += [(source, 'nuitka.NOTICE') for source, _ in found['notice']]
    for source, name in copies:
        shutil.copyfile(source, destination / name)
    return terms


def copy_nuitka_onefile_licenses(destination, distribution=None):
    """Onefile bootstraps compile Nuitka's inline copy of Zstandard (BSD)."""
    distribution = distribution if distribution is not None else metadata.distribution('Nuitka')
    found = [entry for entry in distribution.files or () if Path(str(entry)).as_posix() == ZSTD_LICENSE]
    if len(found) != 1:
        raise NoticeError(f"expected one license of Nuitka's inline Zstandard, found {len(found)}")
    source = Path(distribution.locate_file(found[0]))
    text = source.read_text(encoding='utf-8', errors='replace')
    if not ('BSD License' in text and 'For Zstandard software' in text):
        raise NoticeError(f'unexpected inline Zstandard license text in {source}')
    shutil.copyfile(source, destination / 'nuitka-inline-zstd.LICENSE')


COMMON_REFERENCE = re.compile(r'/usr/share/common-licenses/(\{[^}]+\}|[A-Za-z0-9][A-Za-z0-9.+_-]*)')


def copy_common_licenses(destination, source_directory=Path('/usr/share/common-licenses')):
    copyrights = sorted(destination.glob('*.copyright'))
    if not copyrights:
        raise NoticeError('no bundled dependency copyright notices found')
    references = set()
    for notice in copyrights:
        for match in COMMON_REFERENCE.finditer(notice.read_text()):
            value = match.group(1)
            names = value[1:-1].split(',') if value.startswith('{') else [value]
            references.update(name.strip().rstrip('.') for name in names)
    target = destination / 'common-licenses'
    target.mkdir(exist_ok=True)
    for name in sorted(references):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+_-]*', name):
            raise NoticeError(f'invalid common-license reference: {name!r}')
        source = source_directory / name
        if not source.is_file():
            raise NoticeError(f'missing referenced license text: {source}')
        shutil.copyfile(source, target / name)
    (target / 'README.md').write_text(
        '# Complete license texts\n\n'
        'References to `/usr/share/common-licenses/<name>` in the bundled Debian\n'
        'copyright notices refer to the copy at `third_party/common-licenses/<name>`\n'
        'in this release.\n')


def main(argv):
    if len(argv) != 2:
        print('usage: license_texts.py THIRD_PARTY_DIRECTORY', file=sys.stderr)
        return 2
    try:
        destination = Path(argv[1])
        copy_nuitka_license(destination)
        copy_nuitka_onefile_licenses(destination)
        copy_common_licenses(destination)
    except (NoticeError, OSError, metadata.PackageNotFoundError) as exc:
        print(f'release notices: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
