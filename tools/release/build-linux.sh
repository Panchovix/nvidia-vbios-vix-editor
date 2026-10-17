#!/bin/bash
# Runs inside the release container (Containerfile). Inputs: /in/export.zip, a ZIP of the
# editor source tree, /tools (this directory) and VERSION. Outputs go to /out.
set -euo pipefail
: "${VERSION:?set VERSION}"
version_pattern='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z]+([.-][0-9A-Za-z]+)*)?(\+[0-9A-Za-z]+([.-][0-9A-Za-z]+)*)?$'
valid_version() { local LC_ALL=C; [[ "$1" =~ $version_pattern ]]; }
if ! valid_version "$VERSION"; then echo 'invalid release version' >&2; exit 2; fi
name="nvidia-vbios-vix-editor-$VERSION"
work=/work
mkdir -p "$work" /out
cd "$work"
unzip -q /in/export.zip
src=$(echo "$work"/nvidia-vbios-editor-*)
sed -i "s/^__version__ = .*/__version__ = \"$VERSION\"/" "$src/src/nvidia_vbios/__init__.py"

# The sources must pass their test suite before anything is compiled.
(cd "$src" && PYTHONPATH=src python3 -B -m unittest discover -s tests -q)
# Prove the package still works.
(cd "$src" && PYTHONPATH=src:tests python3 -B - <<'PY'
from test_rom_formats import synthetic_blackwell, synthetic_rom
from nvidia_vbios.rom import from_bytes, inspect_image
import nvidia_vbios.gui.messages_es, nvidia_vbios.gui.presentation  # both catalogs must still parse
from nvidia_vbios.editor import edit
for blob in (synthetic_blackwell(fans=True, power_topology=True), synthetic_rom(), synthetic_rom(family='ampere')):
    assert inspect_image(from_bytes(blob))['fields']
image = from_bytes(synthetic_blackwell(fans=True))
assert edit(image, {'fan_pwm_frequency_hz': 25000, 'power_max_w': 120}).manifest['integrity']['valid']
PY
)

cp /tools/entry_cli.py /tools/entry_gui.py "$work/"
export PYTHONPATH="$src/src"
nuitka=(/opt/nuitka/bin/python -m nuitka --assume-yes-for-downloads --lto=yes
        --python-flag=no_docstrings --python-flag=no_asserts --python-flag=no_site --python-flag=isolated
        --nofollow-import-to=tests --nofollow-import-to=unittest --nofollow-import-to=pydoc
        --remove-output)
# Command line: one compressed file, no GTK.
"${nuitka[@]}" --onefile --output-dir="$work/cli" --output-filename=nvbios \
    --nofollow-import-to=gi --nofollow-import-to=nvidia_vbios.gui.app \
    --nofollow-import-to=nvidia_vbios.gui.file_pickers \
    --include-package=nvidia_vbios.rom --include-package=nvidia_vbios.editor entry_cli.py
# Editor window and the same command line: a standalone folder using the system GTK 4.
# PyGObject (LGPL) is not compiled: its original files ship next to the binary
# so they can be replaced; the standard modules it imports are compiled in.
gi_src=/usr/lib/python3/dist-packages/gi
gi_stdlib=$(python3 - "$gi_src" <<'PY'
import ast, pathlib, sys
names = set()
for path in pathlib.Path(sys.argv[1]).rglob('*.py'):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
import importlib.util
tops = sorted({n.split('.')[0] for n in names} & set(sys.stdlib_module_names) - {'__future__', 'sys'})
# Whole top-level packages: a dotted submodule cannot always be located alone.
specs = {t: importlib.util.find_spec(t) for t in tops}  # e.g. fcntl is absent on Windows
print(' '.join(('--include-package=' if spec.submodule_search_locations else '--include-module=') + t
               for t, spec in specs.items() if spec is not None))
PY
)
read -r -a gi_args <<< "$gi_stdlib"
"${nuitka[@]}" --standalone --include-package=nvidia_vbios --nofollow-import-to=gi \
    --include-package=importlib "${gi_args[@]}" \
    --output-dir="$work/gui" --output-filename=nvbios-gui entry_gui.py
dist="$work/gui/entry_gui.dist"
cp -a "$gi_src" "$dist/gi"
find "$dist/gi" -name __pycache__ -type d -prune -exec rm -rf {} +
cp -a /usr/lib/x86_64-linux-gnu/girepository-1.0 "$dist/girepository"

pkg="$work/package/$name"
mkdir -p "$pkg/lib" "$pkg/third_party"
cp -a "$work/gui/entry_gui.dist" "$pkg/lib/nvbios-gui"
cp "$work/cli/nvbios" "$pkg/nvbios"
ln -s lib/nvbios-gui/nvbios-gui "$pkg/nvbios-gui"
cp "$src/README.md" "$src/LICENSE" "$src/CHANGELOG.md" "$pkg/"

# Third-party notices: the Debian package behind every bundled file.
declare -A owners sources
while IFS= read -r -d '' file; do
    base=$(basename "$file")
    case "$file" in */gi/*) case "$base" in _gi*.so) ;; *) continue ;; esac ;; esac
    case "$base" in
        *.typelib) owner=$( (dpkg -S "girepository-1.0/$base" 2>/dev/null || true) | head -1 | cut -d: -f1) ;;
        lib*.so*) owner=$( (dpkg -S "*/$base" 2>/dev/null || true) | head -1 | cut -d: -f1) ;;
        *) case "$file" in
            */gi/*) owner=$( (dpkg -S "/usr/lib/python3/dist-packages/gi/$base" 2>/dev/null || true) | head -1 | cut -d: -f1) ;;
            *) owner=libpython3.12-stdlib ;;
        esac ;;
    esac
    if [ -z "$owner" ]; then echo "release notices: no Debian package owner for $file" >&2; exit 1; fi
    owners[$owner]+="$base "
done < <(find "$pkg/lib/nvbios-gui" -type f ! -name nvbios-gui -print0)
owners[libpython3.12-stdlib]+="(Python runtime linked into nvbios and nvbios-gui) "
owners[python3-gi]+="(the gi/ Python package, unmodified) "
# Code incorporated in CPython (Doc/license.rst) has its own notices; the text is kept per minor version.
py_minor=$(/opt/nuitka/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])')
incorporated="/tools/licenses/python-$py_minor-incorporated.txt"
[ -f "$incorporated" ] || { echo "release notices: add tools/release/licenses/python-$py_minor-incorporated.txt" >&2; exit 1; }
{
    echo "# Third-party notices"
    echo
    echo "nvbios and nvbios-gui are compiled with Nuitka (Apache License 2.0) and contain the"
    echo "CPython $py_minor runtime (Python Software Foundation License; the licenses of software"
    echo "incorporated in CPython, such as the Mersenne Twister, dtoa, SipHash and HACL*, are in"
    echo "\`third_party/python-$py_minor-incorporated.txt\`). The editor window also"
    echo "bundles the components below. Each license text is in \`third_party/\`."
    echo "Nuitka's license is \`third_party/nuitka.LICENSE\`. The single-file \`nvbios\` starts"
    echo "through Nuitka's onefile bootstrap, which includes Zstandard (BSD,"
    echo "\`third_party/nuitka-inline-zstd.LICENSE\`). References to"
    echo "\`/usr/share/common-licenses/<name>\` in Debian notices resolve to the bundled"
    echo "\`third_party/common-licenses/<name>\` text."
    echo
    echo "PyGObject (GNU LGPL 2.1 or later) ships unmodified as separate files: the \`gi\`"
    echo "Python package and its \`_gi\` modules in \`lib/nvbios-gui/gi/\`. You can replace them"
    echo "with modified versions; GObject typelibs are in \`lib/nvbios-gui/girepository/\`."
    echo
    echo "Field locations for the recognized power and rail tables follow NVIDIA-authored"
    echo "nvgpu \`bios.h\` structure definitions (MIT). No NVIDIA source file is included."
    echo
    echo "| Package | Version | License file | Files |"
    echo "|---|---|---|---|"
    for owner in $(printf '%s\n' "${!owners[@]}" | sort); do
        doc="/usr/share/doc/$owner/copyright"
        if [ ! -f "$doc" ]; then echo "release notices: missing copyright notice for $owner: $doc" >&2; exit 1; fi
        cp -L "$doc" "$pkg/third_party/$owner.copyright"
        lic="third_party/$owner.copyright"
        # The exact installed build and the Ubuntu source package it was built from.
        version='' source='' source_version=''
        IFS=$'\t' read -r version source source_version < <(
            dpkg-query -W -f='${Version}\t${source:Package}\t${source:Version}\n' "$owner" 2>/dev/null | head -1) || true
        if [ -z "${version:-}" ] || [ -z "${source:-}" ] || [ -z "${source_version:-}" ]; then
            echo "release notices: no installed version or source package for $owner" >&2; exit 1
        fi
        sources[$source]=$source_version
        echo "| $owner | $version | $lic | ${owners[$owner]}|"
    done
    echo
    echo "## Corresponding source"
    echo
    echo "nvbios and nvbios-gui are free software under the GNU General Public License v3.0 or"
    echo "later (\`LICENSE\`). Their source code is at"
    echo "https://github.com/Panchovix/nvidia-vbios-vix-editor: tag \`v$VERSION\` is this release,"
    echo "including \`tools/release/\`, the scripts that build these programs."
    echo
    echo "The packages above are unmodified Ubuntu 24.04 builds, at the versions listed. Ubuntu"
    echo "publishes the complete source of each one, including the GNU GPL and LGPL components,"
    echo "as the source packages below: run \`apt-get source <source package>=<version>\` on"
    echo "Ubuntu, or download the files from the Launchpad page."
    echo
    echo "For at least three years after each release, panchovix will also provide the complete"
    echo "corresponding source of these packages on request: open an issue in the repository above."
    echo
    echo "| Source package | Version | Download |"
    echo "|---|---|---|"
    for source in $(printf '%s\n' "${!sources[@]}" | sort); do
        echo "| $source | ${sources[$source]} | https://launchpad.net/ubuntu/+source/$source/${sources[$source]} |"
    done
} > "$pkg/THIRD_PARTY_NOTICES.md"
cp -L /usr/share/doc/python3.12/copyright "$pkg/third_party/python3.12.copyright"
cp "$incorporated" "$pkg/third_party/"
/opt/nuitka/bin/python -I /tools/license_texts.py "$pkg/third_party"

# The compiled programs must not print local paths, file names or dates.
(cd "$src" && PYTHONPATH=src:tests python3 -B - "$work" <<'PY'
import pathlib, re, subprocess, sys
from test_rom_formats import synthetic_blackwell, synthetic_rom
markers = re.compile(r'/(home|root|var/tmp)/|tools/|[\w-]\.json\b|\b20\d\d-\d\d-\d\d\b', re.I)
work = pathlib.Path(sys.argv[1])
for i, blob in enumerate((synthetic_blackwell(fans=True, power_topology=True), synthetic_rom(), synthetic_rom(family='ampere'))):
    rom = work / f'lint{i}.rom'
    rom.write_bytes(blob)
    for binary in (work / 'cli/nvbios', work / 'gui/entry_gui.dist/nvbios-gui'):
        out = subprocess.run([str(binary), 'fields', str(rom)], capture_output=True, text=True, check=True).stdout
        hit = markers.search(out)
        assert not hit, f'{binary.name} prints an internal marker: {hit.group()!r}'
PY
)

cd "$work/package"
tar --sort=name --owner=0 --group=0 --numeric-owner -czf "/out/$name-linux-x86_64.tar.gz" "$name"
cp "$work/cli/nvbios" "/out/nvbios-$VERSION-linux-x86_64"
cd /out
sha256sum "$name-linux-x86_64.tar.gz" "nvbios-$VERSION-linux-x86_64" > SHA256SUMS
cat SHA256SUMS
