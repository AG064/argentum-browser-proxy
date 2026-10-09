ARG WORKER_IMAGE=argentum-browser-proxy-worker
FROM ${WORKER_IMAGE}
COPY tests/container/private/ca.crt /usr/local/share/ca-certificates/fixture.crt
RUN update-ca-certificates
COPY tests/container/ /app/tests/container/
