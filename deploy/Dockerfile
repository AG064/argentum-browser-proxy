FROM node:22-bookworm-slim@sha256:efd0ab5780c2d9ab1f0f869571a00d5edb17793bff4cce4a2792e3eb0ffc7562 AS node
FROM python:3.12-slim-bookworm@sha256:2ed6491b93cd49272ee6de2b5a38440c3448360322c089fc23e370722d74179d AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends iproute2 util-linux ca-certificates && rm -rf /var/lib/apt/lists/*
RUN groupadd -g10001 argentum && useradd -u10001 -g10001 -d/runtime/home argentum && groupadd -g10002 egress && useradd -u10002 -g10002 egress
WORKDIR /app
COPY egress_broker.py /app/
COPY deploy/broker_bootstrap.py /app/deploy/
FROM base AS broker
ENTRYPOINT ["python", "/app/deploy/broker_bootstrap.py"]
FROM base AS worker
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/argentum/browsers ARGENTUM_PROXY_JOB_STATE_DIR=/runtime/jobs XDG_CACHE_HOME=/runtime/cache XDG_CONFIG_HOME=/runtime/config TMPDIR=/tmp
COPY package.json package-lock.json requirements.txt requirements-extract.txt /app/
RUN npm ci --ignore-scripts && pip install --no-cache-dir -r requirements.txt -r requirements-extract.txt
RUN npx playwright install --with-deps chromium --no-shell && apt-get install -y --no-install-recommends ffmpeg iptables libnss3-tools && rm -rf /var/lib/apt/lists/*
COPY . /app/
ENTRYPOINT ["python", "/app/deploy/worker_bootstrap.py"]
