# ─── Builder Stage ──────────────────────────────────────────────────────────
FROM python:3.11.4-slim-bullseye AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    SRC_DIR=/opt/ffmpeg_sources \
    BUILD_DIR=/opt/ffmpeg_build \
    FFMPEG_DIR=/opt/ffmpeg \
    GLTRANSITION_DIR=/opt/ffmpeg-gl-transition \
    FDKAAC_DIR=/opt/fdk-aac \
    NASM_VERSION=2.15.05 \
    YASM_VERSION=1.3.0 \
    FFMPEG_VERSION=4.4 \
    DISPLAY=:1

# Install essential build deps (without NASM/YASM)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    autoconf automake build-essential cmake git libtool pkg-config curl \
    libx264-dev libx265-dev libnuma-dev libvpx-dev \
    libmp3lame-dev libopus-dev libvorbis-dev libtheora-dev libass-dev \
    libfreetype6-dev libfribidi-dev libfontconfig1-dev libwebp-dev \
    libspeex-dev libsoxr-dev libaom-dev libdav1d-dev libxvidcore-dev \
    libgsm1-dev libsnappy-dev libbluray-dev libzvbi-dev libmodplug-dev \
    libopenal-dev libjack-jackd2-dev libpulse-dev libsdl2-dev libxcb1-dev \
    libxcb-shm0-dev libxcb-xfixes0-dev libva-dev libvdpau-dev libdrm-dev \
    libx11-dev libxext-dev libxfixes-dev libxrandr-dev libxinerama-dev \
    libxcursor-dev libxi-dev libxrender-dev libxss-dev libxtst-dev \
    zlib1g-dev libglew-dev libglfw3-dev libegl-dev libxml2-dev \
    liblzma-dev libbz2-dev libssl-dev libsoil-dev xvfb \
    && rm -rf /var/lib/apt/lists/*

# Prepare directories
RUN mkdir -p $SRC_DIR $BUILD_DIR $FFMPEG_DIR $GLTRANSITION_DIR $FDKAAC_DIR

WORKDIR $SRC_DIR

# Install NASM from source
RUN curl -L -O https://www.nasm.us/pub/nasm/releasebuilds/$NASM_VERSION/nasm-$NASM_VERSION.tar.bz2 && \
    tar xjf nasm-$NASM_VERSION.tar.bz2 && cd nasm-$NASM_VERSION && \
    ./autogen.sh && \
    ./configure --prefix="$BUILD_DIR" && \
    make -j$(nproc) && \
    make install

# Install YASM from source
RUN curl -L -O https://www.tortall.net/projects/yasm/releases/yasm-$YASM_VERSION.tar.gz && \
    tar xzf yasm-$YASM_VERSION.tar.gz && cd yasm-$YASM_VERSION && \
    ./configure --prefix="$BUILD_DIR" && \
    make -j$(nproc) && \
    make install

# Build fdk-aac from source
RUN git clone https://github.com/mstorsjo/fdk-aac.git $FDKAAC_DIR && \
    cd $FDKAAC_DIR && autoreconf -fiv && \
    ./configure --prefix="$BUILD_DIR" --disable-shared && \
    make -j$(nproc) && make install

# Clone and patch gltransition filter code
RUN git clone https://github.com/adnahmed/ffmpeg-gl-transition $GLTRANSITION_DIR
RUN git clone --branch release/$FFMPEG_VERSION --depth 1 https://git.ffmpeg.org/ffmpeg.git $FFMPEG_DIR
RUN cp $GLTRANSITION_DIR/vf_gltransition.c $FFMPEG_DIR/libavfilter/ && \
    sed -i '/^# define GL_TRANSITION_USING_EGL/d' $FFMPEG_DIR/libavfilter/vf_gltransition.c

WORKDIR $FFMPEG_DIR

# Start headless X for shader compilation
RUN nohup Xvfb :1 -screen 0 1280x1024x16 >/dev/null 2>&1 &

# Configure, build & install FFmpeg
RUN PKG_CONFIG_PATH="$BUILD_DIR/lib/pkgconfig" ./configure \
    --prefix="$BUILD_DIR" \
    --enable-gpl \
    --enable-libx264 \
    --enable-libx265 \
    --enable-nonfree \
    --enable-libass \
    --enable-libfreetype \
    --enable-libmp3lame \
    --enable-libtheora \
    --enable-libvorbis \
    --enable-libvpx \
    --enable-libopus \
    --enable-libxvid \
    --enable-libfdk-aac \
    --enable-opengl \
    --enable-filter=gltransition \
    --extra-cflags="-I/usr/include/SOIL -I$BUILD_DIR/include" \
    --extra-ldflags="-L/usr/lib/x86_64-linux-gnu -L$BUILD_DIR/lib -lSOIL -lGL" \
    --extra-libs='-lGLEW -lEGL -lSOIL -lGL -lglfw' && \
    make -j$(nproc) && make install && \
    $BUILD_DIR/bin/ffmpeg -filters | grep gltransition

# Copy all gl-transitions shaders
WORKDIR $SRC_DIR
RUN git clone https://github.com/gl-transitions/gl-transitions.git && \
    cp gl-transitions/transitions/*.glsl $BUILD_DIR/bin/ && \
    cp gl-transitions/transitions/dissolve/dissolve.glsl $BUILD_DIR/bin/

# ─── Final Stage ────────────────────────────────────────────────────────────
FROM python:3.11.4-slim-bullseye AS prod

ENV BUILD_DIR=/opt/ffmpeg_build \
    FFMPEG_BINARY=/opt/ffmpeg_build/bin/ffmpeg \
    FFPROBE_BINARY=/opt/ffmpeg_build/bin/ffprobe \
    POETRY_VERSION=1.8.2 \
    DEBIAN_FRONTEND=noninteractive

# Copy FFmpeg runtime
COPY --from=builder /opt/ffmpeg_build /opt/ffmpeg_build

# Install Poetry
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    curl -sSL https://install.python-poetry.org | python3 - --version $POETRY_VERSION && \
    ln -s /root/.local/bin/poetry /usr/local/bin/poetry && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false && \
    poetry install --only main --no-interaction --no-ansi

# Copy app source
COPY . .

CMD ["python", "-m", "vidx"]