#!/bin/bash
set -e

# Set versions and directories
FFMPEG_VERSION="4.4"
NASM_VERSION="2.15.05"
YASM_VERSION="1.3.0"
FFMPEG_DIR="$HOME/ffmpeg"
GLTRANSITION_DIR="$HOME/ffmpeg-gl-transition"
BUILD_DIR="$HOME/ffmpeg_build"
SRC_DIR="$HOME/ffmpeg_sources"
NUM_CORES=$(nproc)

mkdir -p "$SRC_DIR"

# Update and install system dependencies
sudo apt update
sudo apt install -y \
  autoconf automake build-essential cmake git libtool pkg-config curl \
  libx264-dev libx265-dev libnuma-dev libvpx-dev libfdk-aac-dev libmp3lame-dev \
  libopus-dev libvorbis-dev libtheora-dev libass-dev libfreetype6-dev libfribidi-dev \
  libfontconfig1-dev libwebp-dev libspeex-dev libsoxr-dev \
  libaom-dev libdav1d-dev libxvidcore-dev libgsm1-dev libsnappy-dev \
  libbluray-dev libzvbi-dev libmodplug-dev libopenal-dev libjack-jackd2-dev \
  libpulse-dev libsdl2-dev libxcb1-dev libxcb-shm0-dev libxcb-xfixes0-dev \
  libva-dev libvdpau-dev libdrm-dev libx11-dev libxext-dev libxfixes-dev \
  libxrandr-dev libxinerama-dev libxcursor-dev libxi-dev libxrender-dev \
  libxss-dev libxtst-dev zlib1g-dev libglew-dev libglfw3-dev \
  libegl-dev libxml2-dev liblzma-dev libbz2-dev libssl-dev \
  libsoil-dev xvfb

# ---- Install NASM ----
cd "$SRC_DIR"
if ! nasm -v | grep -q "$NASM_VERSION"; then
  echo "Installing NASM $NASM_VERSION..."
  curl -O -L https://www.nasm.us/pub/nasm/releasebuilds/$NASM_VERSION/nasm-$NASM_VERSION.tar.bz2
  tar xjf nasm-$NASM_VERSION.tar.bz2
  cd nasm-$NASM_VERSION
  ./autogen.sh
  ./configure --prefix="$BUILD_DIR"
  make -j"$NUM_CORES"
  make install
fi

# ---- Install YASM ----
cd "$SRC_DIR"
if ! yasm --version | grep -q "$YASM_VERSION"; then
  echo "Installing YASM $YASM_VERSION..."
  curl -O -L https://www.tortall.net/projects/yasm/releases/yasm-$YASM_VERSION.tar.gz
  tar xzf yasm-$YASM_VERSION.tar.gz
  cd yasm-$YASM_VERSION
  ./configure --prefix="$BUILD_DIR"
  make -j"$NUM_CORES"
  make install
fi

export PATH="$BUILD_DIR/bin:$PATH"
export PKG_CONFIG_PATH="$BUILD_DIR/lib/pkgconfig:/usr/local/lib/pkgconfig:$PKG_CONFIG_PATH"
export DISPLAY=:1

# Start Xvfb (headless GL)
echo "Starting Xvfb..."
nohup Xvfb :1 -screen 0 1280x1024x16 >/dev/null 2>&1 &

# ---- Clone gltransition and ffmpeg ----
if [ ! -d "$GLTRANSITION_DIR" ]; then
  git clone https://github.com/adnahmed/ffmpeg-gl-transition "$GLTRANSITION_DIR"
fi

if [ ! -d "$FFMPEG_DIR" ]; then
  git clone --branch release/$FFMPEG_VERSION --depth 1 https://git.ffmpeg.org/ffmpeg.git "$FFMPEG_DIR"
fi

# ---- Apply gltransition modifications ----
cp "$GLTRANSITION_DIR/vf_gltransition.c" "$FFMPEG_DIR/libavfilter/"

cd "$FFMPEG_DIR"
if [ -f "$GLTRANSITION_DIR/ffmpeg.diff" ]; then
  git apply "$GLTRANSITION_DIR/ffmpeg.diff" || {
    echo "Manual patching required: Add vf_gltransition.o to Makefile and REGISTER_FILTER to allfilters.c"
  }
fi

# ⚠️ Disable EGL in vf_gltransition.c to avoid WSL GPU access issues
sed -i '/^# define GL_TRANSITION_USING_EGL/d' "$FFMPEG_DIR/libavfilter/vf_gltransition.c"


# ---- Configure FFmpeg ----
./configure \
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
  --extra-libs='-lGLEW -lEGL -lSOIL -lGL -lglfw'

# ---- Build and install ----
make -j"$NUM_CORES"
make install

# ---- Confirm installation ----
"$BUILD_DIR/bin/ffmpeg" -filters | grep gltransition || {
  echo "ERROR: gltransition not detected. Check Makefile and allfilters.c changes."
}

# clone gl_transitions into the FFMPEG directory and move all the files into FFMPEG directory
if [ ! -d "$FFMPEG_DIR/gl-transitions" ]; then
  git clone https://github.com/gl-transitions/gl-transitions "$FFMPEG_DIR/gl-transitions"
  mv "$FFMPEG_DIR/gl-transitions/transitions/"* "$FFMPEG_DIR/"
  mv "$FFMPEG_DIR/dissolve.glsl" "$FFMPEG_DIR/dissolve.glsl.bak"
  mv "$FFMPEG_DIR/dissolve.glsl.bak/dissolve.glsl" "$FFMPEG_DIR/dissolve.glsl"
  rm -rf "$FFMPEG_DIR/gl-transitions"
  rm -rf "$FFMPEG_DIR/dissolve.glsl.bak"
fi

echo "✅ FFmpeg 4.4 with gltransition built successfully at $BUILD_DIR/bin/ffmpeg"
