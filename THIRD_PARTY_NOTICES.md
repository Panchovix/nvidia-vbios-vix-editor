# Third-party notices

This file covers the Windows programs (nvbios-gui.exe, nvbios.exe). The Linux package
carries its own THIRD_PARTY_NOTICES.md inside the tar.gz.

nvbios.exe and nvbios-gui.exe are compiled with Nuitka. The Nuitka runtime compiled
into them is licensed under the GNU AGPL v3 with the Nuitka Runtime Library Exception 1.0 (`third_party/nuitka.*`);
their onefile bootstrap includes Zstandard (BSD, `third_party/nuitka-inline-zstd.LICENSE`).
They contain the CPython 3.14 runtime (Python Software Foundation License; the licenses
of software incorporated in CPython, such as the Mersenne Twister, dtoa, SipHash and HACL*,
are in `third_party/python-3.14-incorporated.txt`) with the libraries
listed below. nvbios-gui.exe also carries the MSYS2 UCRT64 builds of GTK 4 and its
dependencies, and unpacks them to
`%LOCALAPPDATA%\NVIDIA VBIOS Vix Editor\<version>\gtk` when it starts. Each license
text is in `third_party/`.

Both programs are built with Zig and statically link parts of the MinGW-w64 runtime
(`third_party/mingw-w64-runtime.COPYING`) and Zig's compiler runtime (MIT,
`third_party/zig.LICENSE`).

GTK, GLib and the other GNU LGPL libraries stay separate DLLs, and PyGObject ships
unmodified as the `gi` package in that folder. To use modified versions, copy the
`gtk` folder, replace what you need in the copy, and set the environment variable
`NVBIOS_GTK_RUNTIME` to the copy before starting nvbios-gui.exe.

Field locations for the recognized power and rail tables follow NVIDIA-authored
nvgpu `bios.h` structure definitions (MIT). No NVIDIA source file is included.

| Package | Version | License | License files | Files |
|---|---|---|---|---|
| mingw-w64-ucrt-x86_64-brotli | 1.2.0-1 | MIT | third_party/mingw-w64-ucrt-x86_64-brotli/ | libbrotlicommon.dll libbrotlidec.dll |
| mingw-w64-ucrt-x86_64-bzip2 | 1.0.8-4 | custom | third_party/mingw-w64-ucrt-x86_64-bzip2/ | libbz2-1.dll |
| mingw-w64-ucrt-x86_64-cairo | 1.18.6-2 | LGPL-2.1-or-later OR MPL-1.1 | third_party/mingw-w64-ucrt-x86_64-cairo/ | libcairo-2.dll libcairo-gobject-2.dll libcairo-script-interpreter-2.dll |
| mingw-w64-ucrt-x86_64-expat | 2.9.0-1 | MIT | third_party/mingw-w64-ucrt-x86_64-expat/ | libexpat-1.dll |
| mingw-w64-ucrt-x86_64-fontconfig | 2.18.3-1 | custom | third_party/mingw-w64-ucrt-x86_64-fontconfig/ | libfontconfig-1.dll |
| mingw-w64-ucrt-x86_64-freetype | 2.15.0-1 | GPL-2.0-or-later OR FTL | third_party/mingw-w64-ucrt-x86_64-freetype/ | libfreetype-6.dll |
| mingw-w64-ucrt-x86_64-fribidi | 1.0.17-1 | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-fribidi/ | libfribidi-0.dll |
| mingw-w64-ucrt-x86_64-gdk-pixbuf2 | 2.44.8-1 | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-gdk-pixbuf2/ | libgdk_pixbuf-2.0-0.dll GdkPixbuf-2.0.typelib |
| mingw-w64-ucrt-x86_64-gettext-runtime | 1.0-1 | GPL-3.0-or-later AND LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-gettext-runtime/ | libintl-8.dll |
| mingw-w64-ucrt-x86_64-glib2 | 2.90.1-1 | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-glib2/ | libgio-2.0-0.dll libgirepository-2.0-0.dll libglib-2.0-0.dll libgmodule-2.0-0.dll libgobject-2.0-0.dll Gio-2.0.typelib GioWin32-2.0.typelib GLib-2.0.typelib GLibWin32-2.0.typelib GModule-2.0.typelib GObject-2.0.typelib |
| mingw-w64-ucrt-x86_64-gobject-introspection-runtime | 1.86.0-4 | LGPL-2.0-only | third_party/mingw-w64-ucrt-x86_64-gobject-introspection-runtime/ (standard text) | cairo-1.0.typelib freetype2-2.0.typelib |
| mingw-w64-ucrt-x86_64-graphene | 1.10.8-3 | MIT | third_party/mingw-w64-ucrt-x86_64-graphene/ | libgraphene-1.0-0.dll Graphene-1.0.typelib |
| mingw-w64-ucrt-x86_64-graphite2 | 1.3.15-1 | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-graphite2/ | libgraphite2.dll |
| mingw-w64-ucrt-x86_64-gst-plugins-bad-libs | 1.28.8-2 | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-gst-plugins-bad-libs/ (standard text) | libgstd3d12-1.0-0.dll libgstd3dshader-1.0-0.dll libgstplay-1.0-0.dll |
| mingw-w64-ucrt-x86_64-gst-plugins-base | 1.28.8-1 | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-gst-plugins-base/ | libgstallocators-1.0-0.dll libgstaudio-1.0-0.dll libgstgl-1.0-0.dll libgstpbutils-1.0-0.dll libgsttag-1.0-0.dll libgstvideo-1.0-0.dll |
| mingw-w64-ucrt-x86_64-gstreamer | 1.28.8-1 | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-gstreamer/ (standard text) | libgstbase-1.0-0.dll libgstreamer-1.0-0.dll |
| mingw-w64-ucrt-x86_64-gtk4 | 4.24.1-1 | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-gtk4/ | libgtk-4-1.dll Gdk-4.0.typelib Gsk-4.0.typelib Gtk-4.0.typelib |
| mingw-w64-ucrt-x86_64-harfbuzz | 14.6.0-1 | MIT | third_party/mingw-w64-ucrt-x86_64-harfbuzz/ | libharfbuzz-0.dll libharfbuzz-gobject-0.dll libharfbuzz-subset-0.dll HarfBuzz-0.0.typelib |
| mingw-w64-ucrt-x86_64-jbigkit | 2.1-6 | GPL-2.0 | third_party/mingw-w64-ucrt-x86_64-jbigkit/ | libjbig-0.dll |
| mingw-w64-ucrt-x86_64-lerc | 4.1.1-1 | Apache-2.0 | third_party/mingw-w64-ucrt-x86_64-lerc/ | libLerc.dll |
| mingw-w64-ucrt-x86_64-libdatrie | 0.2.14-1 | LGPL | third_party/mingw-w64-ucrt-x86_64-libdatrie/ | libdatrie-1.dll |
| mingw-w64-ucrt-x86_64-libdeflate | 1.26-1 | MIT | third_party/mingw-w64-ucrt-x86_64-libdeflate/ | libdeflate.dll |
| mingw-w64-ucrt-x86_64-libepoxy | 1.5.10-7 | MIT | third_party/mingw-w64-ucrt-x86_64-libepoxy/ | libepoxy-0.dll |
| mingw-w64-ucrt-x86_64-libffi | 3.8.0-1 | MIT | third_party/mingw-w64-ucrt-x86_64-libffi/ | libffi-8.dll |
| mingw-w64-ucrt-x86_64-libgcc | 16.2.0-6 | GPL-3.0-or-later WITH GCC-exception-3.1 AND GFDL-1.3-or-later | third_party/mingw-w64-ucrt-x86_64-libgcc/ | libgcc_s_seh-1.dll |
| mingw-w64-ucrt-x86_64-libiconv | 1.19-1 | LGPL-2.1-or-later  documentation:GPL-3.0-or-later | third_party/mingw-w64-ucrt-x86_64-libiconv/ | libiconv-2.dll |
| mingw-w64-ucrt-x86_64-libjpeg-turbo | 3.2.0-1 | custom:BSD-like | third_party/mingw-w64-ucrt-x86_64-libjpeg-turbo/ | libjpeg-8.dll |
| mingw-w64-ucrt-x86_64-libpng | 1.6.59-1 | custom | third_party/mingw-w64-ucrt-x86_64-libpng/ | libpng16-16.dll |
| mingw-w64-ucrt-x86_64-libstdc++ | 16.2.0-6 | GPL-3.0-or-later WITH GCC-exception-3.1 AND GFDL-1.3-or-later | third_party/mingw-w64-ucrt-x86_64-libstdc++/ | libstdc++-6.dll |
| mingw-w64-ucrt-x86_64-libthai | 0.1.30-1 | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-libthai/ | libthai-0.dll |
| mingw-w64-ucrt-x86_64-libtiff | 4.7.2-2 | MIT | third_party/mingw-w64-ucrt-x86_64-libtiff/ | libtiff-6.dll |
| mingw-w64-ucrt-x86_64-libwebp | 1.6.0-1 | BSD-3-Clause | third_party/mingw-w64-ucrt-x86_64-libwebp/ | libsharpyuv-0.dll libwebp-7.dll |
| mingw-w64-ucrt-x86_64-libwinpthread | 14.0.0.r426.g4564ee4b5-2 | MIT AND BSD-3-Clause | third_party/mingw-w64-ucrt-x86_64-libwinpthread/ | libwinpthread-1.dll |
| mingw-w64-ucrt-x86_64-lzo2 | 2.10-3 | GPL-2.0-or-later | third_party/mingw-w64-ucrt-x86_64-lzo2/ | liblzo2-2.dll |
| mingw-w64-ucrt-x86_64-mpdecimal | 4.0.1-3 | BSD-2-Clause | third_party/mingw-w64-ucrt-x86_64-mpdecimal/ | libmpdec-4.dll |
| mingw-w64-ucrt-x86_64-openssl | 3.6.5-1 | Apache-2.0 | third_party/mingw-w64-ucrt-x86_64-openssl/ | libcrypto-3-x64.dll libssl-3-x64.dll |
| mingw-w64-ucrt-x86_64-orc | 0.4.44-1 | custom | third_party/mingw-w64-ucrt-x86_64-orc/ | liborc-0.4-0.dll |
| mingw-w64-ucrt-x86_64-pango | 1.58.2-1 | LGPL-2.1 | third_party/mingw-w64-ucrt-x86_64-pango/ | libpango-1.0-0.dll libpangocairo-1.0-0.dll libpangoft2-1.0-0.dll libpangowin32-1.0-0.dll Pango-1.0.typelib PangoCairo-1.0.typelib |
| mingw-w64-ucrt-x86_64-pcre2 | 10.49-1 | BSD-3-Clause | third_party/mingw-w64-ucrt-x86_64-pcre2/ | libpcre2-8-0.dll |
| mingw-w64-ucrt-x86_64-pixman | 0.46.4-3 | MIT | third_party/mingw-w64-ucrt-x86_64-pixman/ | libpixman-1-0.dll |
| mingw-w64-ucrt-x86_64-python | 3.14.8-1 | PSF-2.0 | third_party/mingw-w64-ucrt-x86_64-python/ | libpython3.14.dll (Python runtime and standard library compiled into the programs) |
| mingw-w64-ucrt-x86_64-python-gobject | 3.58.1-1 | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-python-gobject/ (standard text) | _gi.cp314-mingw_x86_64_ucrt_gnu.pyd _gi_cairo.cp314-mingw_x86_64_ucrt_gnu.pyd |
| mingw-w64-ucrt-x86_64-vulkan-loader | 1~1.4.363.0-1 | Apache-2.0 | third_party/mingw-w64-ucrt-x86_64-vulkan-loader/ | vulkan-1.dll |
| mingw-w64-ucrt-x86_64-xz | 5.8.4-1 | 0BSD AND LGPL-2.1-or-later AND GPL-2.0-or-later | third_party/mingw-w64-ucrt-x86_64-xz/ | liblzma-5.dll |
| mingw-w64-ucrt-x86_64-zlib | 1.3.2-2 | Zlib | third_party/mingw-w64-ucrt-x86_64-zlib/ | zlib1.dll |
| mingw-w64-ucrt-x86_64-zstd | 1.5.7-2 | BSD-3-Clause OR GPL-2.0-or-later | third_party/mingw-w64-ucrt-x86_64-zstd/ | libzstd.dll |

## Corresponding source

nvbios.exe and nvbios-gui.exe are free software under the GNU General Public License
v3.0 or later (`LICENSE`). Their source code is at
https://github.com/Panchovix/nvidia-vbios-vix-editor: tag `v0.1.14` is this release,
including `tools/release/`, the scripts that build these programs.

The MSYS2 packages above are unmodified UCRT64 builds, at the versions listed. MSYS2
publishes the complete source of each build, including the GNU GPL and LGPL ones such
as GTK, GLib and PyGObject: each source archive below holds the upstream sources with
the PKGBUILD and patches of that version. The build recipes and their history are also
in https://github.com/msys2/MINGW-packages, in the folder named after each package base.

For at least three years after each release, panchovix will also provide the complete
corresponding source of these packages on request: open an issue in the repository above.

| Package base | Version | Source archive |
|---|---|---|
| mingw-w64-brotli | 1.2.0-1 | https://repo.msys2.org/mingw/sources/mingw-w64-brotli-1.2.0-1.src.tar.zst |
| mingw-w64-bzip2 | 1.0.8-4 | https://repo.msys2.org/mingw/sources/mingw-w64-bzip2-1.0.8-4.src.tar.zst |
| mingw-w64-cairo | 1.18.6-2 | https://repo.msys2.org/mingw/sources/mingw-w64-cairo-1.18.6-2.src.tar.zst |
| mingw-w64-expat | 2.9.0-1 | https://repo.msys2.org/mingw/sources/mingw-w64-expat-2.9.0-1.src.tar.zst |
| mingw-w64-fontconfig | 2.18.3-1 | https://repo.msys2.org/mingw/sources/mingw-w64-fontconfig-2.18.3-1.src.tar.zst |
| mingw-w64-freetype | 2.15.0-1 | https://repo.msys2.org/mingw/sources/mingw-w64-freetype-2.15.0-1.src.tar.zst |
| mingw-w64-fribidi | 1.0.17-1 | https://repo.msys2.org/mingw/sources/mingw-w64-fribidi-1.0.17-1.src.tar.zst |
| mingw-w64-gcc | 16.2.0-6 | https://repo.msys2.org/mingw/sources/mingw-w64-gcc-16.2.0-6.src.tar.zst |
| mingw-w64-gdk-pixbuf2 | 2.44.8-1 | https://repo.msys2.org/mingw/sources/mingw-w64-gdk-pixbuf2-2.44.8-1.src.tar.zst |
| mingw-w64-gettext | 1.0-1 | https://repo.msys2.org/mingw/sources/mingw-w64-gettext-1.0-1.src.tar.zst |
| mingw-w64-glib2 | 2.90.1-1 | https://repo.msys2.org/mingw/sources/mingw-w64-glib2-2.90.1-1.src.tar.zst |
| mingw-w64-gobject-introspection | 1.86.0-4 | https://repo.msys2.org/mingw/sources/mingw-w64-gobject-introspection-1.86.0-4.src.tar.zst |
| mingw-w64-graphene | 1.10.8-3 | https://repo.msys2.org/mingw/sources/mingw-w64-graphene-1.10.8-3.src.tar.zst |
| mingw-w64-graphite2 | 1.3.15-1 | https://repo.msys2.org/mingw/sources/mingw-w64-graphite2-1.3.15-1.src.tar.zst |
| mingw-w64-gst-plugins-bad | 1.28.8-2 | https://repo.msys2.org/mingw/sources/mingw-w64-gst-plugins-bad-1.28.8-2.src.tar.zst |
| mingw-w64-gst-plugins-base | 1.28.8-1 | https://repo.msys2.org/mingw/sources/mingw-w64-gst-plugins-base-1.28.8-1.src.tar.zst |
| mingw-w64-gstreamer | 1.28.8-1 | https://repo.msys2.org/mingw/sources/mingw-w64-gstreamer-1.28.8-1.src.tar.zst |
| mingw-w64-gtk4 | 4.24.1-1 | https://repo.msys2.org/mingw/sources/mingw-w64-gtk4-4.24.1-1.src.tar.zst |
| mingw-w64-harfbuzz | 14.6.0-1 | https://repo.msys2.org/mingw/sources/mingw-w64-harfbuzz-14.6.0-1.src.tar.zst |
| mingw-w64-jbigkit | 2.1-6 | https://repo.msys2.org/mingw/sources/mingw-w64-jbigkit-2.1-6.src.tar.zst |
| mingw-w64-lerc | 4.1.1-1 | https://repo.msys2.org/mingw/sources/mingw-w64-lerc-4.1.1-1.src.tar.zst |
| mingw-w64-libdatrie | 0.2.14-1 | https://repo.msys2.org/mingw/sources/mingw-w64-libdatrie-0.2.14-1.src.tar.zst |
| mingw-w64-libdeflate | 1.26-1 | https://repo.msys2.org/mingw/sources/mingw-w64-libdeflate-1.26-1.src.tar.zst |
| mingw-w64-libepoxy | 1.5.10-7 | https://repo.msys2.org/mingw/sources/mingw-w64-libepoxy-1.5.10-7.src.tar.zst |
| mingw-w64-libffi | 3.8.0-1 | https://repo.msys2.org/mingw/sources/mingw-w64-libffi-3.8.0-1.src.tar.zst |
| mingw-w64-libiconv | 1.19-1 | https://repo.msys2.org/mingw/sources/mingw-w64-libiconv-1.19-1.src.tar.zst |
| mingw-w64-libjpeg-turbo | 3.2.0-1 | https://repo.msys2.org/mingw/sources/mingw-w64-libjpeg-turbo-3.2.0-1.src.tar.zst |
| mingw-w64-libpng | 1.6.59-1 | https://repo.msys2.org/mingw/sources/mingw-w64-libpng-1.6.59-1.src.tar.zst |
| mingw-w64-libthai | 0.1.30-1 | https://repo.msys2.org/mingw/sources/mingw-w64-libthai-0.1.30-1.src.tar.zst |
| mingw-w64-libtiff | 4.7.2-2 | https://repo.msys2.org/mingw/sources/mingw-w64-libtiff-4.7.2-2.src.tar.zst |
| mingw-w64-libwebp | 1.6.0-1 | https://repo.msys2.org/mingw/sources/mingw-w64-libwebp-1.6.0-1.src.tar.zst |
| mingw-w64-lzo2 | 2.10-3 | https://repo.msys2.org/mingw/sources/mingw-w64-lzo2-2.10-3.src.tar.zst |
| mingw-w64-mpdecimal | 4.0.1-3 | https://repo.msys2.org/mingw/sources/mingw-w64-mpdecimal-4.0.1-3.src.tar.zst |
| mingw-w64-openssl | 3.6.5-1 | https://repo.msys2.org/mingw/sources/mingw-w64-openssl-3.6.5-1.src.tar.zst |
| mingw-w64-orc | 0.4.44-1 | https://repo.msys2.org/mingw/sources/mingw-w64-orc-0.4.44-1.src.tar.zst |
| mingw-w64-pango | 1.58.2-1 | https://repo.msys2.org/mingw/sources/mingw-w64-pango-1.58.2-1.src.tar.zst |
| mingw-w64-pcre2 | 10.49-1 | https://repo.msys2.org/mingw/sources/mingw-w64-pcre2-10.49-1.src.tar.zst |
| mingw-w64-pixman | 0.46.4-3 | https://repo.msys2.org/mingw/sources/mingw-w64-pixman-0.46.4-3.src.tar.zst |
| mingw-w64-pygobject | 3.58.1-1 | https://repo.msys2.org/mingw/sources/mingw-w64-pygobject-3.58.1-1.src.tar.zst |
| mingw-w64-python | 3.14.8-1 | https://repo.msys2.org/mingw/sources/mingw-w64-python-3.14.8-1.src.tar.zst |
| mingw-w64-vulkan-loader | 1~1.4.363.0-1 | https://repo.msys2.org/mingw/sources/mingw-w64-vulkan-loader-1~1.4.363.0-1.src.tar.zst |
| mingw-w64-winpthreads | 14.0.0.r426.g4564ee4b5-2 | https://repo.msys2.org/mingw/sources/mingw-w64-winpthreads-14.0.0.r426.g4564ee4b5-2.src.tar.zst |
| mingw-w64-xz | 5.8.4-1 | https://repo.msys2.org/mingw/sources/mingw-w64-xz-5.8.4-1.src.tar.zst |
| mingw-w64-zlib | 1.3.2-2 | https://repo.msys2.org/mingw/sources/mingw-w64-zlib-1.3.2-2.src.tar.zst |
| mingw-w64-zstd | 1.5.7-2 | https://repo.msys2.org/mingw/sources/mingw-w64-zstd-1.5.7-2.src.tar.zst |
