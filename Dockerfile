# Only copy prebuilt upstream binaries: no Rust/Go compilation or auth proxy.
ARG MAIL_MCP_IMAGE=ghcr.io/tecnologicachile/mail-mcp:latest
ARG CLOUDFLARED_IMAGE=cloudflare/cloudflared:latest
ARG BASH_IMAGE=bash:latest
FROM ${MAIL_MCP_IMAGE} AS mail
FROM ${CLOUDFLARED_IMAGE} AS tunnel
FROM ${BASH_IMAGE}
COPY --from=mail /mail-mcp /mail-mcp
COPY --from=mail /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=tunnel /usr/local/bin/cloudflared /usr/local/bin/cloudflared
COPY --chmod=0555 scripts/start-services.sh /usr/local/bin/start-services
ENV MAIL_IMAP_DEFAULT_HOST=imap.yandex.com \
    MAIL_ATTACHMENT_DOWNLOAD_DIR=/tmp/attachments \
    MAIL_IMAP_CONNECT_TIMEOUT_MS=10000 \
    MAIL_IMAP_GREETING_TIMEOUT_MS=10000 \
    MAIL_IMAP_SOCKET_TIMEOUT_MS=30000 \
    MAIL_IMAP_CURSOR_MAX_ENTRIES=128 \
    RUST_LOG=error
# Deliberately no EXPOSE: Northflank must not auto-create a public port.
USER 65532:65532
ENTRYPOINT ["/usr/local/bin/bash", "/usr/local/bin/start-services"]
