#!/usr/bin/env bash
# Build Tcl/Tk 9 (with Xft fonts) and a CPython linked against it, on Linux.
#
#   ./build-python-tk9.sh            # installs under ~/.local/opt, links ~/.local/bin/python3-tk9
#
# Needs a C toolchain plus the X11/Xft/fontconfig and usual CPython headers
# (Arch: base-devel libxft libxss fontconfig openssl zlib libffi sqlite xz bzip2
# readline gdbm mpdecimal expat). Takes a few minutes.
#
# Why not a prebuilt Python? mise/uv's python-build-standalone ships Tk 9
# without Xft, so every font falls back to the X11 bitmap "fixed" font.
set -euo pipefail

TCLTK_VERSION=${TCLTK_VERSION:-9.0.4}
PYTHON_VERSION=${PYTHON_VERSION:-3.14.10}
TCLTK=${TCLTK:-$HOME/.local/opt/tcltk9}
PREFIX=${PREFIX:-$HOME/.local/opt/python${PYTHON_VERSION%.*}-tk9}
WORK=${WORK:-$(mktemp -d)}
JOBS=$(nproc)

cd "$WORK"
for p in tcl tk; do
    curl -sSfLO "https://prdownloads.sourceforge.net/tcl/${p}${TCLTK_VERSION}-src.tar.gz"
    tar xzf "${p}${TCLTK_VERSION}-src.tar.gz"
done

# Bundled libtommath: a system one leaves Tcl without the TclBN_* symbols
# that Python's _tkinter links against.
(cd "tcl${TCLTK_VERSION}/unix"
 ./configure --prefix="$TCLTK" --without-system-libtommath
 # The bundled packages run the fresh tclsh during the build.
 LD_LIBRARY_PATH=$PWD make -j"$JOBS"
 make install)

(cd "tk${TCLTK_VERSION}/unix"
 ./configure --prefix="$TCLTK" --with-tcl="$TCLTK/lib" --enable-xft --enable-xss
 make -j"$JOBS"
 make install)

curl -sSfLO "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tar.xz"
tar xJf "Python-${PYTHON_VERSION}.tar.xz"
(cd "Python-${PYTHON_VERSION}"
 PKG_CONFIG_PATH="$TCLTK/lib/pkgconfig" ./configure --prefix="$PREFIX" --with-ensurepip=install \
     TCLTK_CFLAGS="-I$TCLTK/include" \
     TCLTK_LIBS="-L$TCLTK/lib -ltcl9tk9.0 -ltcl9.0 -Wl,-rpath,$TCLTK/lib"
 make -j"$JOBS"
 make install)

mkdir -p "$HOME/.local/bin"
ln -sf "$PREFIX/bin/python${PYTHON_VERSION%.*}" "$HOME/.local/bin/python3-tk9"
python3-tk9 -c "import tkinter as tk; r = tk.Tk(); r.withdraw(); print('Tk', r.tk.call('info', 'patchlevel'), '-', len(r.tk.call('font', 'families')), 'font families')"
