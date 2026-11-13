# x3d.castle build + test image: Castle Game Engine 7.0-alpha.3 snapshot, headless, no GPU.
#
#   docker build -f docker/Dockerfile -t x3d-castle .
#   docker run --rm x3d-castle                    # runs docker/smoke.sh
#   docker run --rm -it -v "$PWD":/work x3d-castle bash
#
# Status: written from the commands that were run by hand on Ubuntu 24.04 (fp-compiler is NOT needed, the Castle bundle
# ships FPC 3.2.2). The image itself has not been built in the sandbox it was written in (no Docker daemon there);
# the first CI run (.github/workflows/docker.yml) is its first test.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl xz-utils make binutils python3 \
      xvfb xauth \
      libgl1 libgl1-mesa-dri libglx-mesa0 mesa-utils \
      libgtk-3-0t64 libgtk-3-dev libharfbuzz-gobject0 \
      libopenal1 libpng16-16t64 libpng-dev libfreetype6 libfreetype-dev \
      libvorbisfile3 libcurl4t64 libx11-6 libx11-dev libxcursor1 \
    && rm -rf /var/lib/apt/lists/*

# The Castle bundle: bin/ (castle-engine, castle-model-viewer, castle-model-converter, castle-editor, ...), src/ and its own
# FPC 3.2.2 under tools/contrib/fpc. The URL is a moving "snapshot", so the build is pinned by checksum and fails loudly
# if the snapshot is replaced; to move to a new snapshot, change both ARGs.
ARG CASTLE_URL=https://castle-engine.gateway.scarf.sh/snapshot/castle-engine-7.0-alpha.3.snapshot-linux-x86_64-bundle.tar.xz
ARG CASTLE_SHA256=4b8935a4d1117db52a52781472cd2ae851696a235265ba09bd0e0834bf2a48cd
RUN curl -fL --retry 4 -o /tmp/castle.tar.xz "$CASTLE_URL" \
 && echo "$CASTLE_SHA256  /tmp/castle.tar.xz" | sha256sum -c - \
 && mkdir -p /opt/castle && tar xf /tmp/castle.tar.xz -C /opt/castle \
 && rm /tmp/castle.tar.xz

ENV CASTLE_ENGINE_PATH=/opt/castle/castle_game_engine
# The bundle's FPC first: the distro fp-compiler lacks the X11/GL units castle-render needs.
ENV PATH=/opt/castle/castle_game_engine/tools/contrib/fpc/bin:/opt/castle/castle_game_engine/bin:$PATH

WORKDIR /work
COPY castle-convert /work/castle-convert
COPY castle-render /work/castle-render
COPY tools /work/tools
COPY docker/smoke.sh /work/docker/smoke.sh

# exporter: opens no window, so any FPC would do
RUN cd castle-convert && castle-engine compile && test -x x3d-castle-convert
# render harness: needs the GTK3 link libraries (build.sh makes the .so symlinks)
RUN cd castle-render && ./build.sh && test -x castle-render

ENV PATH=/work/castle-convert:/work/castle-render:$PATH
CMD ["sh", "/work/docker/smoke.sh"]
