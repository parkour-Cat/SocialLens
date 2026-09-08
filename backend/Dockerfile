# Backend only. The browser and extension must run on the host.
#   docker build -t sociallens-backend backend
#   docker run --rm -p 127.0.0.1:17800:17800 -v "$PWD/data:/data" sociallens-backend
# The container listens on 0.0.0.0 (containers have no other way); publishing on 127.0.0.1
# keeps it reachable from the host only. ffmpeg (B 站 DASH merge) and yt-dlp (YouTube) are
# included so downloads work inside the container too.
FROM python:3.12-slim

ENV SOCIALLENS_HOST=0.0.0.0 \
    SOCIALLENS_PORT=17800 \
    SOCIALLENS_DATA_DIR=/data \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY sociallens ./sociallens
RUN pip install ".[download]"

EXPOSE 17800
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD curl -fsS http://127.0.0.1:17800/health || exit 1
CMD ["sociallens"]
