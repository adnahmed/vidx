# ─── Builder Stage ──────────────────────────────────────────────────────────
FROM python:3.11.4-slim-bullseye AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    SRC_DIR=/opt/ffmpeg_sources \
    BUILD_DIR=/opt/ffmpeg_build \
    FFMPEG_DIR=/opt/ffmpeg \
    GLTRANSITION_DIR=/opt/ffmpeg-gl-transition \
    FFMPEG_VERSION=4.4 \
    NASM_VERSION=2.15.05 \
    YASM_VERSION=1.3.0 \
    NUM_CORES=$(nproc) \
    DISPLAY=:1

# Install build dependencies in one shot
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    autoconf automake build-essential cmake git libtool pkg-config curl \
    nasm yasm \
    libx264-dev libx265-dev libnuma-dev libvpx-dev libfdk-aac-dev libmp3lame-dev \
    libopus-dev libvorbis-dev libtheora-dev libass-dev libfreetype6-dev libfribidi-dev \
    libfontconfig1-dev libwebp-dev libspeex-dev libsoxr-dev libaom-dev libdav1d-dev \
    libxvidcore-dev libgsm1-dev libsnappy-dev libbluray-dev libzvbi-dev libmodplug-dev \
    libopenal-dev libjack-jackd2-dev libpulse-dev libsdl2-dev libxcb1-dev \
    libxcb-shm0-dev libxcb-xfixes0-dev libva-dev libvdpau-dev libdrm-dev \
    libx11-dev libxext-dev libxfixes-dev libxrandr-dev libxinerama-dev libxcursor-dev \
    libxi-dev libxrender-dev libxss-dev libxtst-dev zlib1g-dev libglew-dev libglfw3-dev \
    libegl-dev libxml2-dev liblzma-dev libbz2-dev libssl-dev libsoil-dev xvfb \
    && rm -rf /var/lib/apt/lists/*

# Prepare directories
RUN mkdir -p $SRC_DIR $BUILD_DIR $FFMPEG_DIR $GLTRANSITION_DIR

# Build FFmpeg with gltransition
WORKDIR $SRC_DIR

# Clone gl-transition repo
RUN git clone https://github.com/adnahmed/ffmpeg-gl-transition $GLTRANSITION_DIR

# Clone FFmpeg
RUN git clone --branch release/$FFMPEG_VERSION --depth 1 https://git.ffmpeg.org/ffmpeg.git $FFMPEG_DIR

# Patch in gltransition
RUN cp $GLTRANSITION_DIR/vf_gltransition.c $FFMPEG_DIR/libavfilter/ && \
    sed -i '/^# define GL_TRANSITION_USING_EGL/d' $FFMPEG_DIR/libavfilter/vf_gltransition.c

WORKDIR $FFMPEG_DIR

# Start headless X to compile shaders
RUN nohup Xvfb :1 -screen 0 1280x1024x16 >/dev/null 2>&1 &

# Configure, build & install
RUN ./configure \
    --prefix="$BUILD_DIR" \
    --enable-gpl \
    --enable-libx264 \
    --enable-libx265 \
    --enable-nonfree \
    --enable-libass \
    --enable-libfdk-aac \
    --enable-libfreetype \
    --enable-libmp3lame \
    --enable-libtheora \
    --enable-libvorbis \
    --enable-libvpx \
    --enable-opengl \
    --enable-libopus \
    --enable-libxvid \
    --enable-filter=gltransition \
    --extra-cflags="-I/usr/include/SOIL -I$BUILD_DIR/include" \
    --extra-ldflags="-L/usr/lib/x86_64-linux-gnu -L$BUILD_DIR/lib -lSOIL -lGL" \
    --extra-libs='-lGLEW -lEGL -lSOIL -lGL -lglfw' && \
    make -j"$NUM_CORES" && \
    make install && \
    $BUILD_DIR/bin/ffmpeg -filters | grep gltransition

# ─── Final Stage ────────────────────────────────────────────────────────────
FROM python:3.11.4-slim-bullseye AS prod

ENV BUILD_DIR=/opt/ffmpeg_build \
    FFMPEG_BINARY=/opt/ffmpeg_build/bin/ffmpeg \
    FFPROBE_BINARY=/opt/ffmpeg_build/bin/ffprobe \
    POETRY_VERSION=1.8.2 \
    DEBIAN_FRONTEND=noninteractive

# Copy only the FFmpeg binaries & libraries
COPY --from=builder /opt/ffmpeg_build /opt/ffmpeg_build

# Install Poetry and your app dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    curl -sSL https://install.python-poetry.org | python3 - --version $POETRY_VERSION && \
    ln -s /root/.local/bin/poetry /usr/local/bin/poetry && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi

# Copy your source
COPY . .

CMD ["python", "-m", "vidx"]
