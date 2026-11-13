#!/bin/sh
# Build castle-render. Two sandbox workarounds, neither touches the system:
#  1. the distro fp-compiler lacks the X11/GL units ("Can't find unit Glx"), so use the FPC 3.2.2 that ships in the
#     Castle bundle (tools/contrib/fpc/bin first in PATH). castle-convert does not need this: it never opens a window.
#  2. Castle's Linux window backend is GTK3; the box has libgtk-3.so.0 etc. but no libgtk-3.so dev symlinks, so make
#     the symlinks in castle-engine-output/linklibs (a build-output folder) and pass -Fl.
# The binary lands in this folder as ./castle-render. Do not commit it.
CASTLE_ENGINE_PATH="${CASTLE_ENGINE_PATH:?set CASTLE_ENGINE_PATH to the castle_game_engine folder}"
export CASTLE_ENGINE_PATH
export PATH="$CASTLE_ENGINE_PATH/tools/contrib/fpc/bin:$CASTLE_ENGINE_PATH/bin:$PATH"
cd "$(dirname "$0")" || exit 1
LL="$PWD/castle-engine-output/linklibs"
mkdir -p "$LL"
for l in gtk-3 gdk-3 gdk_pixbuf-2.0 pango-1.0 harfbuzz harfbuzz-gobject atk-1.0; do
  if [ ! -e "$LL/lib$l.so" ] && ! ls /usr/lib/x86_64-linux-gnu/lib$l.so >/dev/null 2>&1; then
    f=$(ls /usr/lib/x86_64-linux-gnu/lib$l.so.0* 2>/dev/null | head -1)
    [ -n "$f" ] && ln -sf "$f" "$LL/lib$l.so"
  fi
done
exec castle-engine compile --compiler-option=-Fl"$LL" "$@"
