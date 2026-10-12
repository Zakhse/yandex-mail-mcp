#!/usr/bin/env bash
# Bash >= 5.1. Container PID 1: forward shutdown, reap both children, fail fast.
set -Eeuo pipefail
: "${MAIL_IMAP_DEFAULT_USER:?Set the IMAP username in runtime secrets}"
: "${MAIL_IMAP_DEFAULT_PASS:?Set the IMAP app password in runtime secrets}"
: "${TUNNEL_TOKEN:?Set the named tunnel token in runtime secrets}"

# Enforce the safety boundary regardless of accidental deployment overrides.
export MAIL_MCP_TRANSPORT=http MAIL_MCP_HTTP_HOST=127.0.0.1
export MAIL_MCP_HTTP_PORT=8000 MAIL_MCP_HTTP_PATH=/mcp
export MAIL_IMAP_DEFAULT_PORT=993 MAIL_IMAP_DEFAULT_SECURE=true
export MAIL_IMAP_WRITE_ENABLED=false MAIL_SMTP_WRITE_ENABLED=false
mkdir -p "${MAIL_ATTACHMENT_DOWNLOAD_DIR:-/tmp/attachments}"

mail_pid='' tunnel_pid=''
cleanup() {
    trap - EXIT TERM INT
    for child in "$mail_pid" "$tunnel_pid"; do
        if [[ -n "$child" ]]; then kill -TERM "$child" 2>/dev/null || true; fi
    done
    # Bound shutdown even if a child ignores TERM.
    (sleep 5; for child in "$mail_pid" "$tunnel_pid"; do
        if [[ -n "$child" ]]; then kill -KILL "$child" 2>/dev/null || true; fi
    done) &
    local watchdog=$!
    for child in "$mail_pid" "$tunnel_pid"; do
        if [[ -n "$child" ]]; then wait "$child" 2>/dev/null || true; fi
    done
    kill -TERM "$watchdog" 2>/dev/null || true
    wait "$watchdog" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

# Credentials are scoped to the appropriate child process.
env -i PATH=/usr/local/bin:/usr/bin:/bin RUST_LOG=error \
    MAIL_MCP_TRANSPORT="$MAIL_MCP_TRANSPORT" MAIL_MCP_HTTP_HOST="$MAIL_MCP_HTTP_HOST" \
    MAIL_MCP_HTTP_PORT="$MAIL_MCP_HTTP_PORT" MAIL_MCP_HTTP_PATH="$MAIL_MCP_HTTP_PATH" \
    MAIL_IMAP_DEFAULT_HOST="${MAIL_IMAP_DEFAULT_HOST:-imap.yandex.com}" \
    MAIL_IMAP_DEFAULT_USER="$MAIL_IMAP_DEFAULT_USER" MAIL_IMAP_DEFAULT_PASS="$MAIL_IMAP_DEFAULT_PASS" \
    MAIL_IMAP_DEFAULT_PORT="$MAIL_IMAP_DEFAULT_PORT" MAIL_IMAP_DEFAULT_SECURE="$MAIL_IMAP_DEFAULT_SECURE" \
    MAIL_IMAP_WRITE_ENABLED=false MAIL_SMTP_WRITE_ENABLED=false \
    MAIL_ATTACHMENT_DOWNLOAD_DIR="${MAIL_ATTACHMENT_DOWNLOAD_DIR:-/tmp/attachments}" \
    MAIL_IMAP_CONNECT_TIMEOUT_MS=10000 MAIL_IMAP_GREETING_TIMEOUT_MS=10000 \
    MAIL_IMAP_SOCKET_TIMEOUT_MS=30000 MAIL_IMAP_CURSOR_MAX_ENTRIES=128 \
    "${1:-/mail-mcp}" &
mail_pid=$!
env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/nonexistent \
    TUNNEL_TOKEN="$TUNNEL_TOKEN" TUNNEL_TRANSPORT_PROTOCOL=http2 \
    "${2:-/usr/local/bin/cloudflared}" tunnel --no-autoupdate \
    --loglevel warn --metrics 127.0.0.1:2000 run &
tunnel_pid=$!

# If either program exits, restart the whole service rather than leave half alive.
set +e
wait -n "$mail_pid" "$tunnel_pid"
status=$?
set -e
if [[ "$status" -eq 0 ]]; then status=1; fi
exit "$status"
