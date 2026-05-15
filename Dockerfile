FROM node:20-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHON_VENV_DIR=/app/.venv
ENV PATH=/app/.venv/bin:$PATH
ENV REDIS_URL=redis://127.0.0.1:6379/0
ENV REDIS_BIND=127.0.0.1
ENV REDIS_PORT=6379
ENV API_HOST=0.0.0.0
ENV API_PORT=8000
ENV WEB_HOST=0.0.0.0
ENV WEB_PORT=5173

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    ffmpeg \
    redis-server \
    lsof \
    procps \
    tini \
    fonts-dejavu-core \
  && rm -rf /var/lib/apt/lists/*

RUN corepack enable && corepack prepare pnpm@10.32.1 --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml requirements.txt ./
COPY apps/web/package.json /app/apps/web/package.json

RUN pnpm install --frozen-lockfile

RUN python3 -m venv /app/.venv \
  && /app/.venv/bin/pip install --no-cache-dir --upgrade pip \
  && /app/.venv/bin/pip install --no-cache-dir -r /app/requirements.txt \
  && touch /app/.venv/.requirements-installed

COPY . .

RUN touch /app/.venv/.requirements-installed

RUN chmod +x /app/scripts/*.sh

EXPOSE 5173 8000
EXPOSE 6379

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/bin/bash", "-lc", "mkdir -p /app/data/redis /app/.pids && if ! redis-cli -u \"$REDIS_URL\" ping >/dev/null 2>&1; then redis-server --bind \"$REDIS_BIND\" --port \"$REDIS_PORT\" --dir /app/data/redis --pidfile /app/data/redis/redis.pid --logfile /app/data/redis/redis.log --save '' --appendonly no --daemonize yes; fi && for i in $(seq 1 20); do redis-cli -u \"$REDIS_URL\" ping >/dev/null 2>&1 && break; sleep 0.25; done && redis-cli -u \"$REDIS_URL\" ping >/dev/null 2>&1 && exec pnpm dev"]
