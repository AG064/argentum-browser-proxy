FROM nginx:stable-alpine@sha256:8f84ed99befc3891b8f329c5c202785278a2cfb7c25107d57fb2a134a3117433
RUN apk add --no-cache iptables util-linux python3
COPY deploy/nginx.conf /etc/nginx/nginx.conf
COPY deploy/gateway_bootstrap.py /bootstrap.py
ENTRYPOINT ["python3", "/bootstrap.py"]
