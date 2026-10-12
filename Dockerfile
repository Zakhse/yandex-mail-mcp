# Only copy prebuilt upstream binaries: no Rust/Go compilation or auth proxy.
FROM ghcr.io/tecnologicachile/mail-mcp@sha256:019a84ab766b67354fdc0d52cf403438270e46d78ba4e5901d4dc930973e31c3 AS mail
FROM cloudflare/cloudflared@sha256:9b49eed8f62806d5d45ddf59ecefb5710429598ea6d3fcccd2af938f621b2b07 AS tunnel
FROM bash@sha256:61962062d969cb46dfc2bad061d36342406fa485f64f246aa7e95693ca07df1f
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
