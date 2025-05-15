# --- Base Stage ---
FROM python:3.11.4-slim-bullseye AS base

ENV SRC_DIR=/opt/ffmpeg_sources
ENV BUILD_DIR=/opt/ffmpeg_build
ENV FFMPEG_DIR=/opt/ffmpeg
ENV GLTRANSITION_DIR=/opt/ffmpeg-gl-transition
RUN mkdir -p $SRC_DIR $BUILD_DIR $FFMPEG_DIR
COPY build_ffmpeg_gl_transitions.sh /tmp/build_ffmpeg_gl_transitions.sh
RUN chmod +x /tmp/build_ffmpeg_gl_transitions.sh
RUN /tmp/build_ffmpeg_gl_transitions.sh

# --- Production Stage ---
FROM python:3.11.4-slim-bullseye AS prod
ENV BUILD_DIR=/opt/ffmpeg_build
COPY --from=base $BUILD_DIR $BUILD_DIR
RUN chmod +x $BUILD_DIR/bin/ffmpeg
RUN chmod +x $BUILD_DIR/bin/ffprobe
ENV FFMPEG_BINARY=$BUILD_DIR/bin/ffmpeg
ENV FFPROBE_BINARY=$BUILD_DIR/bin/ffprobe

RUN pip install poetry==1.8.2
RUN poetry config virtualenvs.create false
RUN poetry config cache-dir /tmp/poetry_cache
COPY pyproject.toml poetry.lock /app/src/
WORKDIR /app/src
RUN --mount=type=cache,target=/tmp/poetry_cache poetry install --only main
COPY . /app/src/
RUN --mount=type=cache,target=/tmp/poetry_cache poetry install --only main
CMD ["/usr/local/bin/python", "-m", "vidx"]
FROM prod AS dev
RUN --mount=type=cache,target=/tmp/poetry_cache poetry install
