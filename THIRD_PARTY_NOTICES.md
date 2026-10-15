# Third-party notices

This file covers the Windows programs (nvbios-gui.exe, nvbios.exe). The Linux package
carries its own THIRD_PARTY_NOTICES.md inside the tar.gz.

nvbios.exe and nvbios-gui.exe are compiled with Nuitka (Apache License 2.0) and contain
the CPython runtime (Python Software Foundation License) with the libraries listed
below. nvbios-gui.exe also carries the MSYS2 UCRT64 builds of GTK 4 and its
dependencies, and unpacks them to
`%LOCALAPPDATA%\NVIDIA VBIOS Vix Editor\<version>\gtk` when it starts. Each license
text is in `third_party/`.

GTK, GLib and the other GNU LGPL libraries stay separate DLLs, and PyGObject ships
unmodified as the `gi` package in that folder. To use modified versions, copy the
`gtk` folder, replace what you need in the copy, and set the environment variable
`NVBIOS_GTK_RUNTIME` to the copy before starting nvbios-gui.exe.

Field locations for the recognized power and rail tables follow NVIDIA-authored
nvgpu `bios.h` structure definitions (MIT). No NVIDIA source file is included.

| Package | License | License files | Files |
|---|---|---|---|
| mingw-w64-ucrt-x86_64-brotli | MIT | third_party/mingw-w64-ucrt-x86_64-brotli/ | libbrotlicommon.dll libbrotlidec.dll |
| mingw-w64-ucrt-x86_64-bzip2 | custom | third_party/mingw-w64-ucrt-x86_64-bzip2/ | libbz2-1.dll |
| mingw-w64-ucrt-x86_64-cairo | LGPL-2.1-or-later OR MPL-1.1 | third_party/mingw-w64-ucrt-x86_64-cairo/ | libcairo-2.dll libcairo-gobject-2.dll libcairo-script-interpreter-2.dll |
| mingw-w64-ucrt-x86_64-expat | MIT | third_party/mingw-w64-ucrt-x86_64-expat/ | libexpat-1.dll |
| mingw-w64-ucrt-x86_64-fontconfig | custom | third_party/mingw-w64-ucrt-x86_64-fontconfig/ | libfontconfig-1.dll |
| mingw-w64-ucrt-x86_64-freetype | GPL-2.0-or-later OR FTL | third_party/mingw-w64-ucrt-x86_64-freetype/ | libfreetype-6.dll |
| mingw-w64-ucrt-x86_64-fribidi | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-fribidi/ | libfribidi-0.dll |
| mingw-w64-ucrt-x86_64-gdk-pixbuf2 | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-gdk-pixbuf2/ | libgdk_pixbuf-2.0-0.dll GdkPixbuf-2.0.typelib |
| mingw-w64-ucrt-x86_64-gettext-runtime | GPL-3.0-or-later AND LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-gettext-runtime/ | libintl-8.dll |
| mingw-w64-ucrt-x86_64-glib2 | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-glib2/ | libgio-2.0-0.dll libgirepository-2.0-0.dll libglib-2.0-0.dll libgmodule-2.0-0.dll libgobject-2.0-0.dll Gio-2.0.typelib GioWin32-2.0.typelib GLib-2.0.typelib GLibWin32-2.0.typelib GModule-2.0.typelib GObject-2.0.typelib |
| mingw-w64-ucrt-x86_64-gobject-introspection-runtime | LGPL-2.0-only | third_party/mingw-w64-ucrt-x86_64-gobject-introspection-runtime/ (standard text) | cairo-1.0.typelib freetype2-2.0.typelib |
| mingw-w64-ucrt-x86_64-graphene | MIT | third_party/mingw-w64-ucrt-x86_64-graphene/ | libgraphene-1.0-0.dll Graphene-1.0.typelib |
| mingw-w64-ucrt-x86_64-graphite2 | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-graphite2/ | libgraphite2.dll |
| mingw-w64-ucrt-x86_64-gst-plugins-bad-libs | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-gst-plugins-bad-libs/ (standard text) | libgstd3d12-1.0-0.dll libgstd3dshader-1.0-0.dll libgstplay-1.0-0.dll |
| mingw-w64-ucrt-x86_64-gst-plugins-base | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-gst-plugins-base/ | libgstallocators-1.0-0.dll libgstaudio-1.0-0.dll libgstgl-1.0-0.dll libgstpbutils-1.0-0.dll libgsttag-1.0-0.dll libgstvideo-1.0-0.dll |
| mingw-w64-ucrt-x86_64-gstreamer | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-gstreamer/ (standard text) | libgstbase-1.0-0.dll libgstreamer-1.0-0.dll |
| mingw-w64-ucrt-x86_64-gtk4 | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-gtk4/ | libgtk-4-1.dll Gdk-4.0.typelib Gsk-4.0.typelib Gtk-4.0.typelib |
| mingw-w64-ucrt-x86_64-harfbuzz | MIT | third_party/mingw-w64-ucrt-x86_64-harfbuzz/ | libharfbuzz-0.dll libharfbuzz-gobject-0.dll libharfbuzz-subset-0.dll HarfBuzz-0.0.typelib |
| mingw-w64-ucrt-x86_64-jbigkit | GPL-2.0 | third_party/mingw-w64-ucrt-x86_64-jbigkit/ | libjbig-0.dll |
| mingw-w64-ucrt-x86_64-lerc | Apache-2.0 | third_party/mingw-w64-ucrt-x86_64-lerc/ | libLerc.dll |
| mingw-w64-ucrt-x86_64-libdatrie | LGPL | third_party/mingw-w64-ucrt-x86_64-libdatrie/ | libdatrie-1.dll |
| mingw-w64-ucrt-x86_64-libdeflate | MIT | third_party/mingw-w64-ucrt-x86_64-libdeflate/ | libdeflate.dll |
| mingw-w64-ucrt-x86_64-libepoxy | MIT | third_party/mingw-w64-ucrt-x86_64-libepoxy/ | libepoxy-0.dll |
| mingw-w64-ucrt-x86_64-libffi | MIT | third_party/mingw-w64-ucrt-x86_64-libffi/ | libffi-8.dll |
| mingw-w64-ucrt-x86_64-libgcc | GPL-3.0-or-later WITH GCC-exception-3.1 AND GFDL-1.3-or-later | third_party/mingw-w64-ucrt-x86_64-libgcc/ | libgcc_s_seh-1.dll |
| mingw-w64-ucrt-x86_64-libiconv | LGPL-2.1-or-later  documentation:GPL-3.0-or-later | third_party/mingw-w64-ucrt-x86_64-libiconv/ | libiconv-2.dll |
| mingw-w64-ucrt-x86_64-libjpeg-turbo | custom:BSD-like | third_party/mingw-w64-ucrt-x86_64-libjpeg-turbo/ | libjpeg-8.dll |
| mingw-w64-ucrt-x86_64-libpng | custom | third_party/mingw-w64-ucrt-x86_64-libpng/ | libpng16-16.dll |
| mingw-w64-ucrt-x86_64-libstdc++ | GPL-3.0-or-later WITH GCC-exception-3.1 AND GFDL-1.3-or-later | third_party/mingw-w64-ucrt-x86_64-libstdc++/ | libstdc++-6.dll |
| mingw-w64-ucrt-x86_64-libthai | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-libthai/ | libthai-0.dll |
| mingw-w64-ucrt-x86_64-libtiff | MIT | third_party/mingw-w64-ucrt-x86_64-libtiff/ | libtiff-6.dll |
| mingw-w64-ucrt-x86_64-libwebp | BSD-3-Clause | third_party/mingw-w64-ucrt-x86_64-libwebp/ | libsharpyuv-0.dll libwebp-7.dll |
| mingw-w64-ucrt-x86_64-libwinpthread | MIT AND BSD-3-Clause | third_party/mingw-w64-ucrt-x86_64-libwinpthread/ | libwinpthread-1.dll |
| mingw-w64-ucrt-x86_64-lzo2 | GPL-2.0-or-later | third_party/mingw-w64-ucrt-x86_64-lzo2/ | liblzo2-2.dll |
| mingw-w64-ucrt-x86_64-mpdecimal | BSD-2-Clause | third_party/mingw-w64-ucrt-x86_64-mpdecimal/ | libmpdec-4.dll |
| mingw-w64-ucrt-x86_64-openssl | Apache-2.0 | third_party/mingw-w64-ucrt-x86_64-openssl/ | libcrypto-3-x64.dll libssl-3-x64.dll |
| mingw-w64-ucrt-x86_64-orc | custom | third_party/mingw-w64-ucrt-x86_64-orc/ | liborc-0.4-0.dll |
| mingw-w64-ucrt-x86_64-pango | LGPL-2.1 | third_party/mingw-w64-ucrt-x86_64-pango/ | libpango-1.0-0.dll libpangocairo-1.0-0.dll libpangoft2-1.0-0.dll libpangowin32-1.0-0.dll Pango-1.0.typelib PangoCairo-1.0.typelib |
| mingw-w64-ucrt-x86_64-pcre2 | BSD-3-Clause | third_party/mingw-w64-ucrt-x86_64-pcre2/ | libpcre2-8-0.dll |
| mingw-w64-ucrt-x86_64-pixman | MIT | third_party/mingw-w64-ucrt-x86_64-pixman/ | libpixman-1-0.dll |
| mingw-w64-ucrt-x86_64-python | PSF-2.0 | third_party/mingw-w64-ucrt-x86_64-python/ | libpython3.14.dll (Python runtime and standard library compiled into the programs) |
| mingw-w64-ucrt-x86_64-python-gobject | LGPL-2.1-or-later | third_party/mingw-w64-ucrt-x86_64-python-gobject/ (standard text) | _gi.cp314-mingw_x86_64_ucrt_gnu.pyd _gi_cairo.cp314-mingw_x86_64_ucrt_gnu.pyd |
| mingw-w64-ucrt-x86_64-vulkan-loader | Apache-2.0 | third_party/mingw-w64-ucrt-x86_64-vulkan-loader/ | vulkan-1.dll |
| mingw-w64-ucrt-x86_64-xz | 0BSD AND LGPL-2.1-or-later AND GPL-2.0-or-later | third_party/mingw-w64-ucrt-x86_64-xz/ | liblzma-5.dll |
| mingw-w64-ucrt-x86_64-zlib | Zlib | third_party/mingw-w64-ucrt-x86_64-zlib/ | zlib1.dll |
| mingw-w64-ucrt-x86_64-zstd | BSD-3-Clause OR GPL-2.0-or-later | third_party/mingw-w64-ucrt-x86_64-zstd/ | libzstd.dll |
