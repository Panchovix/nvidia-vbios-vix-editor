#!/bin/bash
# Windows release build. Runs in an MSYS2 UCRT64 shell (GitHub Actions or a
# local MSYS2) from a checkout that holds the editor sources at its top or in an
# editor/ folder. Needs: python, python-gobject, gtk4, gcc, ntldd, zip (UCRT64
# packages), Nuitka and Zig. Usage: VERSION=0.1.2 tools/release/build-windows.sh
set -euo pipefail
: "${VERSION:?set VERSION}"
version_pattern='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z]+([.-][0-9A-Za-z]+)*)?(\+[0-9A-Za-z]+([.-][0-9A-Za-z]+)*)?$'
# ASCII classes in any locale; Windows file versions take parts up to 65535.
valid_version() {
    local LC_ALL=C major minor patch
    [[ $1 =~ $version_pattern ]] || return 1
    IFS=. read -r major minor patch <<< "${1%%[-+]*}"
    (( ${#major} <= 5 && ${#minor} <= 5 && ${#patch} <= 5 )) || return 1  # no arithmetic overflow
    (( 10#$major <= 65535 && 10#$minor <= 65535 && 10#$patch <= 65535 ))
}
if ! valid_version "$VERSION"; then echo 'invalid release version' >&2; exit 2; fi
root=$(cd "$(dirname "$0")/../.." && pwd)
tools="$root/tools/release"
work="$root/build-windows"
out="$root/dist-windows"
rm -rf "$work" "$out"
mkdir -p "$work" "$out"
from=$root
[ -d "$root/editor/src" ] && from=$root/editor
mkdir -p "$work/editor"
cp -a "$from/src" "$from/tests" "$from/LICENSE" "$work/editor/"
src="$work/editor"
sed -i "s/^__version__ = .*/__version__ = \"$VERSION\"/" "$src/src/nvidia_vbios/__init__.py"

# Same gates as the Linux build: tests, smoke test, lint.
(cd "$src" && PYTHONPATH=src python -B -m unittest discover -s tests -q)
(cd "$src" && PYTHONPATH="src;tests" python -B - <<'PY'
from test_rom_formats import synthetic_blackwell, synthetic_rom
from nvidia_vbios.rom import from_bytes, inspect_image
import nvidia_vbios.gui.messages_es, nvidia_vbios.gui.presentation  # both catalogs must still parse
from nvidia_vbios.editor import edit
for blob in (synthetic_blackwell(fans=True, power_topology=True), synthetic_rom(), synthetic_rom(family='ampere')):
    assert inspect_image(from_bytes(blob))['fields']
assert edit(from_bytes(synthetic_blackwell(fans=True)), {'fan_pwm_frequency_hz': 25000})
PY
)

cp "$tools/entry_cli.py" "$tools/entry_gui.py" "$work/"
cd "$work"
export PYTHONPATH="$src/src"
metadata=(--company-name="panchovix" --product-name="NVIDIA VBIOS Vix Editor"
          --file-version="${VERSION%%[-+]*}" --product-version="${VERSION%%[-+]*}"
          --copyright="Copyright (C) 2026 panchovix")
# MSYS2 Python uses "/" as os.sep while MSYSTEM is set; Nuitka needs "\\".
nuitka=(env -u MSYSTEM python -m nuitka --assume-yes-for-downloads --zig
        --python-flag=no_docstrings --python-flag=no_asserts --python-flag=no_site --python-flag=isolated
        --nofollow-import-to=tests --nofollow-import-to=unittest --nofollow-import-to=pydoc
        --remove-output "${metadata[@]}")
# Command line: one file, console program, no GTK.
"${nuitka[@]}" --onefile --windows-console-mode=force --output-dir="$(cygpath -w "$work/cli")" --output-filename=nvbios.exe \
    --report="$(cygpath -w "$work/cli-report.xml")" \
    --file-description="NVIDIA VBIOS Vix Editor command line" \
    --nofollow-import-to=gi --nofollow-import-to=nvidia_vbios.gui.app \
    --nofollow-import-to=nvidia_vbios.gui.file_pickers \
    --include-package=nvidia_vbios.rom --include-package=nvidia_vbios.editor entry_cli.py

# Editor window: one program that unpacks its GTK 4 runtime into a cache folder,
# %LOCALAPPDATA%\NVIDIA VBIOS Vix Editor\<version>\gtk, and checks it at each
# start; no console window unless started from one. PyGObject (LGPL) ships in
# that runtime as its original, replaceable files, imported at run time: Nuitka 4
# must allow that import of the excluded gi.
gi_src=$(python -c 'import gi, os; print(os.path.dirname(gi.__file__))')
gi_stdlib=$(python - "$gi_src" <<'PY'
import ast, pathlib, sys
names = set()
for path in pathlib.Path(sys.argv[1]).rglob('*.py'):
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
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
runtime="$work/gtk"
mkdir -p "$runtime/girepository"
cp -a "$gi_src" "$runtime/gi"
find "$runtime/gi" -name __pycache__ -type d -prune -exec rm -rf {} +
prefix=/ucrt64
# Only the typelibs the editor loads: the GTK 4 namespaces and their dependencies.
for typelib in $(python - <<'PY' | tr -d '\r'
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk
repo = gi.Repository.get_default()
names = {f'{ns}-{repo.get_version(ns)}' for ns in repo.get_loaded_namespaces()}
for ns in repo.get_loaded_namespaces():
    names.update(repo.get_dependencies(ns))
print(' '.join(sorted(names)))
PY
); do
    cp "$prefix/lib/girepository-1.0/$typelib.typelib" "$runtime/girepository/"
done
mkdir -p "$runtime/share/glib-2.0/schemas" "$runtime/share/icons"
cp "$prefix/share/glib-2.0/schemas/gschemas.compiled" "$runtime/share/glib-2.0/schemas/"
cp -a "$prefix/share/icons/hicolor" "$runtime/share/icons/" 2>/dev/null || true
# GTK and every DLL it needs from the UCRT64 prefix (GObject loads them by name).
roots=("$runtime"/gi/_gi*.pyd "$prefix/bin/libgtk-4-1.dll")
for typelib in "$runtime"/girepository/*.typelib; do
    for library in $(strings "$typelib" | grep -oE 'lib[A-Za-z0-9_.+-]*-[0-9]+\.dll' | sort -u); do
        [ -f "$prefix/bin/$library" ] && roots+=("$prefix/bin/$library")
    done
done
for dll in $(ntldd -R "${roots[@]}" 2>/dev/null | grep -oiE '[A-Z]:\\[^ ]*\\ucrt64\\bin\\[^ ]*\.dll' | sort -u); do
    cp -n "$(cygpath -u "$dll")" "$runtime/"
done
for library in "${roots[@]}"; do case "$library" in "$prefix"/bin/*) cp -n "$library" "$runtime/" ;; esac; done

"${nuitka[@]}" --onefile --onefile-tempdir-spec="{CACHE_DIR}/NVIDIA VBIOS Vix Editor/{VERSION}" \
    --windows-console-mode=attach --output-dir="$(cygpath -w "$work/gui")" --output-filename=nvbios-gui.exe \
    --file-description="NVIDIA VBIOS Vix Editor" --no-deployment-flag=excluded-module-usage \
    --include-raw-dir="$(cygpath -w "$runtime")=gtk" --report="$(cygpath -w "$work/gui-report.xml")" \
    --include-package=nvidia_vbios --nofollow-import-to=gi --include-package=importlib "${gi_args[@]}" entry_gui.py

# Third-party notices, published with the programs: the MSYS2 package that owns
# every file of the GTK runtime and every DLL Nuitka put into either program.
notices="$work/notices"
mkdir -p "$notices/third_party"
declare -A owners seen
add_owner() {  # FILE OWNER
    [ -n "${seen[$1]:-}" ] && return
    seen[$1]=1
    owners[${2:-unknown}]+="$1 "
}
for file in "$runtime"/*.dll "$runtime"/gi/_gi*.pyd "$runtime"/girepository/*.typelib; do
    base=$(basename "$file")
    case "$file" in
        */gi/*) add_owner "$base" mingw-w64-ucrt-x86_64-python-gobject ;;
        *.typelib) add_owner "$base" "$( (pacman -Qqo "$prefix/lib/girepository-1.0/$base" 2>/dev/null || true) | head -1)" ;;
        *) add_owner "$base" "$( (pacman -Qqo "$prefix/bin/$base" 2>/dev/null || true) | head -1)" ;;
    esac
done
for base in $(python - "$work/cli-report.xml" "$work/gui-report.xml" <<'PY' | tr -d '\r'
import sys, xml.etree.ElementTree as ET
names = set()
for report in sys.argv[1:]:
    names |= {node.get('name') for node in ET.parse(report).getroot().iter('included_dll')
              if node.get('source_path') != '{generated}'}  # not the compiled program itself
print(' '.join(sorted(names)))
PY
); do
    add_owner "$base" "$( (pacman -Qqo "$prefix/bin/$base" 2>/dev/null || true) | head -1)"
done
owners[mingw-w64-ucrt-x86_64-python]+="(Python runtime and standard library compiled into the programs) "
# Nuitka's own license texts from its .dist-info (Apache 2.0 for 2.x; AGPLv3 with
# the Nuitka Runtime Library Exception for 4.x) and the inline Zstandard of the
# onefile bootstrap. Missing or ambiguous texts fail the build.
nuitka_terms=$(python -I - "$notices/third_party" "$tools" <<'PY' | tr -d '\r'
import pathlib, sys
sys.path.insert(0, sys.argv[2])
from license_texts import copy_nuitka_licenses, copy_nuitka_onefile_licenses
destination = pathlib.Path(sys.argv[1])
print(copy_nuitka_licenses(destination))
copy_nuitka_onefile_licenses(destination)
PY
)
[ -n "$nuitka_terms" ] || { echo 'Nuitka license texts not found' >&2; exit 1; }
# Code incorporated in CPython (Doc/license.rst) has its own notices; the text is kept per minor version.
py_minor=$(python -c 'import sys; print("%d.%d" % sys.version_info[:2])' | tr -d '\r')
incorporated="$tools/licenses/python-$py_minor-incorporated.txt"
[ -f "$incorporated" ] || { echo "release notices: add tools/release/licenses/python-$py_minor-incorporated.txt" >&2; exit 1; }
cp "$incorporated" "$notices/third_party/"
# Zig builds both programs and links parts of the MinGW-w64 runtime and its own
# compiler runtime into them: COPYING.MinGW-w64-runtime.txt of the mingw-w64
# project, and Zig's LICENSE (MIT) as shipped in the ziglang wheel.
cp "$tools/licenses/mingw-w64-runtime.COPYING" "$tools/licenses/zig.LICENSE" "$notices/third_party/"
# Exact versions and package bases (the name of the MSYS2 source archive).
dbpath=$( (pacman-conf DBPath 2>/dev/null || true) | head -1 | tr -d '\r')
dbpath=${dbpath:-/var/lib/pacman/}
declare -A source_archives
{
    echo "# Third-party notices (Windows)"
    echo
    echo "nvbios.exe and nvbios-gui.exe are compiled with Nuitka. The Nuitka runtime compiled"
    echo "into them is licensed under $nuitka_terms (\`third_party/nuitka.*\`);"
    echo "their onefile bootstrap includes Zstandard (BSD, \`third_party/nuitka-inline-zstd.LICENSE\`)."
    echo "They contain the CPython $py_minor runtime (Python Software Foundation License; the licenses"
    echo "of software incorporated in CPython, such as the Mersenne Twister, dtoa, SipHash and HACL*,"
    echo "are in \`third_party/python-$py_minor-incorporated.txt\`) with the libraries"
    echo "listed below. nvbios-gui.exe also carries the MSYS2 UCRT64 builds of GTK 4 and its"
    echo "dependencies, and unpacks them to"
    echo "\`%LOCALAPPDATA%\\NVIDIA VBIOS Vix Editor\\<version>\\gtk\` when it starts. Each license"
    echo "text is in \`third_party/\`."
    echo
    echo "Both programs are built with Zig and statically link parts of the MinGW-w64 runtime"
    echo "(\`third_party/mingw-w64-runtime.COPYING\`) and Zig's compiler runtime (MIT,"
    echo "\`third_party/zig.LICENSE\`)."
    echo
    echo "GTK, GLib and the other GNU LGPL libraries stay separate DLLs, and PyGObject ships"
    echo "unmodified as the \`gi\` package in that folder. To use modified versions, copy the"
    echo "\`gtk\` folder, replace what you need in the copy, and set the environment variable"
    echo "\`NVBIOS_GTK_RUNTIME\` to the copy before starting nvbios-gui.exe."
    echo
    echo "Field locations for the recognized power and rail tables follow NVIDIA-authored"
    echo "nvgpu \`bios.h\` structure definitions (MIT). No NVIDIA source file is included."
    echo
    echo "| Package | Version | License | License files | Files |"
    echo "|---|---|---|---|---|"
    for owner in $(printf '%s\n' "${!owners[@]}" | sort); do
        spdx=$( (pacman -Qi "$owner" 2>/dev/null || true) | sed -n 's/^Licenses *: *//p' | sed 's/spdx://g' | tr -d '\r')
        version=$( (pacman -Q "$owner" 2>/dev/null || true) | head -1 | cut -d' ' -f2 | tr -d '\r')
        base=$( (sed -n '/^%BASE%$/{n;p;q}' "${dbpath%/}/local/$owner-$version/desc" 2>/dev/null || true) | tr -d '\r')
        [ -n "$base" ] || base="mingw-w64-${owner#mingw-w64-ucrt-x86_64-}"
        if [ -n "$version" ]; then
            source_archives[$base]=$version
        elif grep -q 'GPL' <<< "$spdx"; then
            echo "release notices: no installed version of $owner ($spdx)" >&2; exit 1
        fi
        dest="$notices/third_party/$owner"
        if [ -d "$prefix/share/licenses/${owner#mingw-w64-ucrt-x86_64-}" ]; then
            cp -a "$prefix/share/licenses/${owner#mingw-w64-ucrt-x86_64-}" "$dest"
        else
            # No share/licenses folder: the LICENSE/COPYING files the package installs.
            for file in $( (pacman -Qlq "$owner" 2>/dev/null || true) | grep -iE '/(licen[cs]e|copying)[^/]*$' | head -5); do
                [ -f "$file" ] && mkdir -p "$dest" && cp "$file" "$dest/"
            done
        fi
        licenses="(not found)"
        [ -d "$dest" ] && licenses="third_party/$owner/"
        if [ ! -d "$dest" ]; then
            # Last resort: the standard text of each license pacman names.
            for id in $(grep -oE '\bL?GPL-[0-9.]+[0-9]' <<< "$spdx" | sort -u); do
                [ -f "$tools/licenses/$id.txt" ] && mkdir -p "$dest" && cp "$tools/licenses/$id.txt" "$dest/"
            done
            [ -d "$dest" ] && licenses="third_party/$owner/ (standard text)"
        fi
        echo "| $owner | ${version:-unknown} | ${spdx:-unknown} | $licenses | ${owners[$owner]}|"
    done
    echo
    echo "## Corresponding source"
    echo
    echo "nvbios.exe and nvbios-gui.exe are free software under the GNU General Public License"
    echo "v3.0 or later (\`LICENSE\`). Their source code is at"
    echo "https://github.com/Panchovix/nvidia-vbios-vix-editor: tag \`v$VERSION\` is this release,"
    echo "including \`tools/release/\`, the scripts that build these programs."
    echo
    echo "The MSYS2 packages above are unmodified UCRT64 builds, at the versions listed. MSYS2"
    echo "publishes the complete source of each build, including the GNU GPL and LGPL ones such"
    echo "as GTK, GLib and PyGObject: each source archive below holds the upstream sources with"
    echo "the PKGBUILD and patches of that version. The build recipes and their history are also"
    echo "in https://github.com/msys2/MINGW-packages, in the folder named after each package base."
    echo
    echo "For at least three years after each release, panchovix will also provide the complete"
    echo "corresponding source of these packages on request: open an issue in the repository above."
    echo
    echo "| Package base | Version | Source archive |"
    echo "|---|---|---|"
    for base in $(printf '%s\n' "${!source_archives[@]}" | sort); do
        version=${source_archives[$base]}
        # Archive names write a version epoch (1:2.0-1) as 1~2.0-1.
        echo "| $base | $version | https://repo.msys2.org/mingw/sources/$base-${version//:/\~}.src.tar.zst |"
    done
} > "$notices/THIRD_PARTY_NOTICES.md"
# Output lint, as on Linux: neither program may print local paths, file names or dates.
mkdir -p "$work/package"
(cd "$src" && PYTHONPATH="src;tests" python -B - "$work" <<'PY'
import pathlib, re, subprocess, sys
from test_rom_formats import synthetic_blackwell, synthetic_rom
markers = re.compile(r'/(home|root|var/tmp)/|tools/|[\w-]\.json\b|\b20\d\d-\d\d-\d\d\b', re.I)
work = pathlib.Path(sys.argv[1])
for i, blob in enumerate((synthetic_blackwell(fans=True, power_topology=True), synthetic_rom(), synthetic_rom(family='ampere'))):
    rom = work / 'package' / f'lint{i}.rom'
    rom.write_bytes(blob)
    for binary in (work / 'cli' / 'nvbios.exe', work / 'gui' / 'nvbios-gui.exe'):
        out = subprocess.run([str(binary), 'fields', str(rom)], capture_output=True, text=True, check=True).stdout
        assert '"ok": true' in out, f'{binary.name} failed on lint{i}'
        hit = markers.search(out)
        assert not hit, f'{binary.name} prints an internal marker: {hit.group()!r}'
PY
)

# Release files: the two programs, their checksums, and the license with the
# notices for the public repository.
cp "$work/gui/nvbios-gui.exe" "$work/cli/nvbios.exe" "$out/"
cp "$src/LICENSE" "$notices/LICENSE"
(cd "$notices" && zip -qr -9 "$out/third-party-notices-windows.zip" .)
cd "$out"
sha256sum nvbios-gui.exe nvbios.exe > SHA256SUMS-windows
cat SHA256SUMS-windows
