# Verification evidence — 2026-10-12

This file separates inspected upstream behavior, executed local tests, and pending
live acceptance. No real mailbox or hosting account was used.

## Executed locally

- Downloaded the official `mail-mcp` v0.4.16 macOS ARM64 release archive and checked
  SHA-256 `5fad9ddaaced33872eeccb27a272b5d4060aab61281e184ba7c7a7bc9a61f51c`
  against the release asset's published digest before execution.
- Ran `tests/test_upstream.py`: **6 integration tests passed**. Used an isolated
  subprocess environment, a temporary working directory, artificial MIME mail,
  a loopback fake IMAP server and real upstream MCP Streamable HTTP. Checked
  initialization/version, tool discovery, folders, search, body reads via
  EXAMINE/BODY.PEEK[], exact attachment bytes on disk/in base64, explicit inline
  size omission, and IMAP delete/SMTP send refusal before any network operation.
- Ran `tests/test_supervisor.py`: **4 process tests passed** using Bash 5.3 and
  synthetic executable doubles. Checked forced TLS/read-only/loopback defaults,
  separating mail/tunnel credentials, stopping the other child after either
  child exits, and SIGTERM cleanup of both children.
- Ran `scripts/check_public.py`: passed. No credentials, personal domains,
  owner identifiers or instance details are included in these files. This is a
  limited guard plus human review, not proof that arbitrary future commits are safe.
- Ran the local Northflank renderer with reserved example values. It produced one
  combined-service definition with zero replicas and zero ports; no API calls.
- Installed official `@northflank/cli` 0.13.0 in a disposable working directory.
  Verified `nf login`, `nf list projects`, and `nf create service combined` options
  using help output only. No account login or provisioning took place.
- Retrieved anonymous public registry manifests for mail-mcp v0.4.16,
  cloudflared 2026.10.0 and Bash 5.3. Image index digests are pinned in
  `deploy/versions.json`; Linux AMD64 and ARM64 platforms are present.

## Inspected source and official documentation

- [Mail MCP v0.4.16 source](https://github.com/tecnologicachile/mail-mcp/tree/v0.4.16):
  HTTP opt-in, loopback default, stateless `/mcp`, no built-in authentication,
  EXAMINE/PEEK reads, write gates, embedded WebPKI TLS roots and hostname validation,
  attachment disk write/base64 ceiling. No `/health` route. Write tools remain
  discoverable. Yandex app-password permissions are not constrained by this code.
- [Upstream release](https://github.com/tecnologicachile/mail-mcp/releases/tag/v0.4.16):
  published 2026-10-05. Repository main was updated 2026-10-10 and is not archived.
  The image publishing workflow is manually triggered; pinned public manifests
  were resolved independently rather than inferred from the Git tag.
- [Open issues](https://github.com/tecnologicachile/mail-mcp/issues): no assertion
  that the absence of a reported issue proves security. Custom CA support is an
  open topic; this Yandex setup uses standard public TLS roots.
- [Northflank pricing](https://northflank.com/pricing),
  [billing terms](https://northflank.com/docs/v1/application/billing/pricing-on-northflank),
  [projects](https://northflank.com/docs/v1/application/getting-started/create-a-project),
  [ports](https://northflank.com/docs/v1/application/network/configure-ports),
  [CLI](https://northflank.com/docs/v1/api/use-the-cli),
  [combined-service fields](https://northflank.com/docs/v1/api/project/services/create-combined-service):
  two always-on free services, one Sandbox project, required payment method,
  private networking and CLI/API. A resource plan ID does not establish free
  entitlement. Combined-service creation has not been submitted to a live API.
- [Cloudflare Managed OAuth](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/):
  Beta, HTTP self-hosted app support, 401/discovery, RFC 8707, DCR configuration and
  opaque OAuth tokens transformed into a signed Access assertion for origins.
- [Tunnel origin Access enforcement](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/cloudflared-parameters/origin-parameters/):
  Protect with Access validates JWT at the connector with required team/AUD.
  This is a ready-made origin enforcement layer, not a custom verifier.
- [OpenAI MCP authentication](https://developers.openai.com/apps-sdk/build/auth/)
  and [connection guide](https://developers.openai.com/apps-sdk/deploy/connect-chatgpt/):
  Streamable HTTP, metadata discovery, PKCE S256, `resource`, DCR/CIMD options and
  connection-specific callback allowlisting. A general protocol match does not
  prove this Cloudflare combination works with a particular ChatGPT account.
- [Yandex IMAP](https://yandex.com/support/yandex-360/customers/mail/en/mail-clients/others):
  enable IMAP/app-password authentication; official server, TLS port 993,
  dedicated Mail app password.

## Executed container checks

- Built the actual Dockerfile using the pinned manifests in an isolated local
  Docker environment. No image was pushed or resource provisioned remotely.
  Linux ARM64 passed natively; Linux AMD64 passed under local emulation.
- Both upstream executables run in the final image; cloudflared reports
  `2026.10.0`. Verified non-root UID, available CA certificate bundle and tools
  needed by the CMD readiness probe.
- `tests/test_container.py`: **6 offline tests passed on each architecture**.
  The container has no network, no host ports, a read-only root filesystem and
  a 256 MiB memory limit.
  The actual Linux mail-mcp serves MCP HTTP and refuses IMAP delete/SMTP send
  despite intentionally unsafe parent environment flags. HTTP tests explicitly
  replace the connector with a sleeping process, not a real authenticated tunnel.
- Separately tested actual cloudflared failing with an invented token and no
  network: the supervisor stops the complete container. Disconnected readiness
  is rejected, and SIGTERM shuts down the container without SIGKILL.
- Northflank browser/API-token login succeeded. Read-only project access was
  verified; no services existed. Git integration inspection is denied by the
  selected role, so integration attachment cannot yet be confirmed through CLI.
  No secret values or account-specific identifiers are recorded in this document.
- Cloudflare read-only API access succeeded. The resource lists had no
  mail/IMAP-named Access apps or tunnels; this name-based check does not rule out
  resources with other names. No existing resources were modified.

## Not executed — needs an authorized deployment

The following are also pending: the account's actual free-plan/build quote and
quota accounting; container memory/storage under representative attachment load;
Cloudflare Managed OAuth availability/pricing on that account; Cloudflare route
JWT enforcement; unauthenticated/invalid/expired-token denial; no origin bypass;
owner-only ChatGPT OAuth including discovery/PKCE/refresh; real Yandex folders,
search, unread-state preservation; PDF extraction and PDF/image use in ChatGPT;
restart/redeploy recovery; secret rotation; confirmed billing and Workers usage.

In particular, base64 bytes inside JSON are not evidence that ChatGPT can open or
analyze a binary attachment. No public file-serving endpoint, OCR, native MCP image
content or automatic ChatGPT file conversion has been implemented.
