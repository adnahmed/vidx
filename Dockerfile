# ─── FFmpeg Builder Stage ───────────────────────────────────────────────────
# This stage builds FFmpeg with GL Transitions support
FROM python:3.11-slim-bookworm AS ffmpeg-builder

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

# Ensure built tools are discoverable
ENV PATH=/opt/ffmpeg_build/bin:$PATH

# Install minimal build dependencies required
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    autoconf automake build-essential cmake git libtool pkg-config curl ca-certificates \
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
    liblzma-dev libbz2-dev libssl-dev libsoil-dev xvfb wget \
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
    cd $FFMPEG_DIR && \
    if [ -f "$GLTRANSITION_DIR/ffmpeg.diff" ]; then \
    git apply "$GLTRANSITION_DIR/ffmpeg.diff" || echo "Manual patching"; \
    fi && \
    sed -i '/^# define GL_TRANSITION_USING_EGL/d' $FFMPEG_DIR/libavfilter/vf_gltransition.c

WORKDIR $FFMPEG_DIR

# Start headless X for shader compilation
RUN nohup Xvfb :1 -screen 0 1280x1024x16 >/dev/null 2>&1 &
ENV DISPLAY=:1

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
    --extra-cflags="-I/usr/include/SOIL -I /opt/ffmpeg_build/include" \
    --extra-ldflags="-L/usr/lib/x86_64-linux-gnu -L/opt/ffmpeg_build/lib -lSOIL -lGL" \
    --extra-libs='-lGLEW -lEGL -lSOIL -lGL -lglfw' && \
    make -j$(nproc) && make install 

RUN /opt/ffmpeg_build/bin/ffmpeg -filters | grep gltransition && echo "GL Transitions filter verified"

# Copy all gl-transitions shaders
WORKDIR $SRC_DIR
RUN git clone --depth 1 https://github.com/gl-transitions/gl-transitions.git && \
    cp -r gl-transitions/transitions/*.glsl $BUILD_DIR/bin/ && \
    mv $BUILD_DIR/bin/dissolve.glsl $BUILD_DIR/bin/dissolve.glsl.bak && \
    mv $BUILD_DIR/bin/dissolve.glsl.bak/dissolve.glsl $BUILD_DIR/bin/dissolve.glsl && \
    rm -rf $BUILD_DIR/bin/dissolve.glsl.bak && \
    echo "Shaders copied successfully"

# Cleanup build directories to reduce layer size
RUN rm -rf $SRC_DIR && \
    rm -rf $BUILD_DIR/lib/pkgconfig && \
    find $BUILD_DIR -name "*.a" -delete && \
    find $BUILD_DIR -name "*.la" -delete && \
    find $BUILD_DIR -name "*.h" -delete && \
    strip $BUILD_DIR/bin/* 2>/dev/null || true && \
    echo "FFmpeg build stage complete"

# ─── Dependencies Layer ─────────────────────────────────────────────────────
# This layer contains only runtime dependencies
FROM python:3.11-slim-bookworm AS runtime-deps

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl libmagic1 xvfb \
    libxcb1 \
    libxcb-shm0 \
    libxcb-shape0 \
    libxcb-xfixes0 \
    libasound2 \
    libgl1 \
    libsdl2-2.0-0 \
    libxv1 \
    libx11-6 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libass9 \
    libva2 \
    libfreetype6 \
    libvpx7 \
    libmp3lame0 \
    libopus0 \
    libtheora0 \
    libvorbis0a \
    libvorbisenc2 \
    libx264-164 \
    libx265-199 \
    libxvidcore4 \
    libva-drm2 \
    libva-x11-2 \
    libvdpau1 \
    libglew2.2 \
    libegl1 \
    libglfw3 \
    libsoil1 \
    redis-server \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# MongoDB server for self-contained Render deployments (VIDX_EMBEDDED_MONGO).
# Official mongodb-org repo for Debian bookworm; only the server package is installed.
RUN curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
    gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg && \
    echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/debian bookworm/mongodb-org/7.0 main" \
      > /etc/apt/sources.list.d/mongodb-org-7.0.list && \
    apt-get update && apt-get install -y --no-install-recommends mongodb-org-server && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# ─── Python Dependencies Layer ──────────────────────────────────────────────
FROM runtime-deps AS python-builder

# uv is the project's package manager (uv.lock is the source of truth).
COPY --from=ghcr.io/astral-sh/uv:0.8.23 /uv /uvx /usr/local/bin/

WORKDIR /tmp

# Copy project files required to resolve dependencies
COPY pyproject.toml uv.lock README.md ./

# Export locked runtime dependencies and build wheels for them. This only
# depends on the lockfile, so Docker can cache it when app source changes.
RUN uv export --frozen --no-dev --no-emit-project --format requirements-txt -o requirements.txt && \
    python -m pip wheel -r requirements.txt -w /wheels && \
    rm -rf /root/.cache/pip && \
    find /usr/local -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Now copy the application source and build the app wheel. This step will change when
# the application code changes, but the dependency wheels in /wheels will remain cached.
COPY . .
RUN python -m pip wheel . -w /wheels && rm -rf /root/.cache/pip || true

# ─── Final Production Image ─────────────────────────────────────────────────
FROM runtime-deps AS prod

ENV BUILD_DIR=/opt/ffmpeg_build \
    FFMPEG_BINARY=/opt/ffmpeg_build/bin/ffmpeg \
    FFPROBE_BINARY=/opt/ffmpeg_build/bin/ffprobe \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DISPLAY=:1

# Create non-root user for security
RUN useradd -m -u 1000 vidx && \
    mkdir -p /app /tmp && \
    chown -R vidx:vidx /app /tmp

# Copy FFmpeg from builder stage
COPY --from=ffmpeg-builder --chown=vidx:vidx /opt/ffmpeg_build /opt/ffmpeg_build

# Copy Python dependencies from python-builder stage
COPY --from=python-builder --chown=vidx:vidx /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

WORKDIR /app

# Make entrypoint executable
COPY --chown=vidx:vidx docker-entrypoint.sh render-entrypoint.sh /usr/local/bin/
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh /usr/local/bin/render-entrypoint.sh && \
    chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/render-entrypoint.sh

# Copy pre-built wheels from the python-builder stage and install them. Installing wheels
# is cache-friendly: if dependencies haven't changed, this layer will be cached and
# pip won't re-run a costly install on every rebuild.
COPY --from=python-builder --chown=vidx:vidx /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels && \
    find /usr/local -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true && \
    find /usr/local -type f -name "*.pyc" -delete

# Copy application source (after installing wheels) so that code changes won't bust the
# dependency-install layer. This keeps rebuilds fast when only app code changed.
COPY --chown=vidx:vidx . .

# Switch to non-root user
USER vidx:vidx

# Health check
HEALTHCHECK --interval=10s --timeout=5s --retries=20 --start-period=60s \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health').getcode()==200 else 1)" || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "vidx"]