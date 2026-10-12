# Yandex Mail MCP server for deployment on Northflank

Self-host Yandex Mail search, reading and attachment access through MCP Streamable
HTTP, using **one Northflank service**. The second free service slot stays available.

This project packages prebuilt `tecnologicachile/mail-mcp` and official
`cloudflared` binaries into one small container. Cloudflare Access handles OAuth;
cloudflared validates Access JWTs. No custom OAuth/JWT proxy, Workers, KV or database.

**Status:** the one-container image builds, and its MCP HTTP, isolation and
shutdown behavior have been checked offline. IMAP/attachment behavior passed
synthetic-mail tests. No real mailbox, Northflank deployment or ChatGPT OAuth
connection has been tested. See [verification evidence and remaining checks](docs/verification.md).
Do not treat this as a proven end-to-end integration yet.

## Architecture

```text
ChatGPT / remote MCP client
  -> HTTPS on YOUR hostname
  -> Cloudflare Access Managed OAuth (only YOUR authorized identity)
  -> named Cloudflare Tunnel
  -> ONE Northflank container:
       cloudflared [validates Access JWT]
         -> http://127.0.0.1:8000/mcp
       mail-mcp [IMAP/SMTP writes disabled]
         -> Yandex IMAP, port 993, verified TLS
```

MCP and connector metrics bind to container loopback. **No Northflank ports are
published or configured.** A small Bash supervisor starts both binaries, forwards
shutdown signals, and exits if either child stops so the platform can restart the
whole container. Image manifests are pinned in [deploy/versions.json](deploy/versions.json).
This launcher is the only runtime custom code; it does not implement authentication.

## Costs and limits — checked 2026-10-12

- [Northflank pricing](https://northflank.com/pricing) advertises two free,
  always-on services without sleeping. Its
  [Sandbox documentation](https://northflank.com/docs/v1/application/getting-started/create-a-project)
  allows one project; this deployment uses one combined build-and-deploy service.
- Northflank [requires a payment method for all plans](https://northflank.com/docs/v1/application/billing/pricing-on-northflank).
  Free does **not** mean no card. The provider says Sandbox is not for production.
- Start with the smallest **account-confirmed free CPU plan**, one replica, no GPU,
  volume, addon, extra build service or persistent build cache. Europe–West
  (`europe-west`, London) is a reasonable region; no latency benchmark was made.
- The example plan `nf-compute-10` is 0.1 CPU / 256 MiB in the public API, but the
  [public plan list](https://api.northflank.com/v1/plans) also lists a paid price.
  The plan ID itself does not prove a free entitlement. Confirm a **$0 quote for
  your account** before creating it, including build charges. Do not select a
  paid upgrade merely to make an example work.
- Larger RAM, more replicas, extra storage/build capacity, paid networking,
  another region/cloud, BYOC resources and plan upgrades can incur charges. A
  billing alert is a notification, not a hard spending cap.
- Cloudflare offers a [Zero Trust free plan](https://www.cloudflare.com/plans/zero-trust-services/).
  Managed OAuth is documented as **Beta**. These pages do not establish an
  unconditional free entitlement to Managed OAuth for every account: check its
  availability and pricing in your own dashboard before proceeding.
- You need your own domain served by Cloudflare. Domain registration/renewal and
  your ChatGPT subscription may cost money. No Workers are used by this design.
- This project adds no per-call quota. Provider, IMAP, OAuth, traffic, memory and
  ChatGPT limits still apply. Large attachments are fetched in full and can exceed
  a small container's memory. This is a small personal instance, not unlimited hosting.

## 1. Prepare Cloudflare — before supplying a mailbox password

1. Create a Zero Trust organization and a **self-hosted HTTP Access application**
   for your entire MCP hostname, including `/mcp` and all other paths. Use a
   hostname you own; no real hostname belongs in this repository.
2. Create an Allow policy for **only your intended identity**, using your IdP or
   one-time PIN. Do not use Everyone, Bypass, or a wildcard email domain. Avoid
   extra policies that admit other users. The one configured mailbox is shared
   by every identity admitted through Access.
3. Enable [Managed OAuth](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/)
   in the application's Advanced settings. Enable DCR where available. Allow only
   the exact HTTPS redirect URI shown by ChatGPT for this connection. Keep
   localhost/loopback clients disabled unless you explicitly need a local client.
   A 5–15 minute access-token lifetime is a reasonable starting point.
4. Create a **remotely managed named Cloudflare Tunnel**. Add a published
   application route for your hostname to `http://127.0.0.1:8000`. Leave the route
   path unrestricted so discovery/authorization endpoints remain reachable.
5. Enable **Protect with Access** on that route and select your Zero Trust team
   and this Access application's audience (AUD). This makes cloudflared validate
   `Cf-Access-Jwt-Assertion` before forwarding. See the
   [official origin parameters](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/cloudflared-parameters/origin-parameters/)
   and [reference fragment](deploy/cloudflare/tunnel-route.example.yaml).
   The fragment is documentation; token-based remote tunnels get their actual
   route configuration from Cloudflare, not from this file.
6. Save the tunnel token directly to hosting secrets. Do not paste it into chat,
   Git, shell arguments, screenshots or a Dockerfile. Do not use a Quick Tunnel.

Use the self-hosted application's Managed OAuth flow. Cloudflare's third-party
MCP application/portal recipe assumes the third-party server handles OAuth or
validates JWT itself. Upstream mail-mcp does neither; in this design the official
cloudflared connector enforces JWT validation at the origin boundary.

## 2. Deploy ONE service on Northflank

### Dashboard

1. Confirm Sandbox availability and cost; create/select one project. Choose your
   region deliberately: Northflank does not allow changing it after creation.
2. Connect your own copy of this GitHub repository. Create **one combined service**
   that builds and deploys it using `/Dockerfile`, build context `/`, BuildKit.
   Do not create separate Mail MCP and tunnel services.
3. Use one replica and the account-confirmed free CPU/RAM plan. Review the build
   plan and cost too. Do not enable persistent build cache or volumes.
4. Under Networking ensure the service has **zero configured ports**. The
   Dockerfile deliberately has no `EXPOSE`. Keep Docker command/entrypoint defaults.
5. Create a runtime-only Secret group restricted to this service. Start with
   synthetic values for `MAIL_IMAP_DEFAULT_USER` and `MAIL_IMAP_DEFAULT_PASS`,
   and your tunnel's real `TUNNEL_TOKEN` entered **only in the panel**. Synthetic
   mailbox credentials allow OAuth/security validation without real mailbox access.
   Never use build arguments for these three values.
6. Run security checks below. Then replace synthetic mailbox values with your
   dedicated Yandex credentials only when you are ready to authorize live access.
7. Optionally configure a CMD readiness probe that checks both loopback endpoints:

   ```sh
   /usr/local/bin/bash -c 'exec 3<>/dev/tcp/127.0.0.1/8000 && wget -q -O /dev/null http://127.0.0.1:2000/ready'
   ```

   `/ready` belongs to cloudflared; mail-mcp has **no `/health` endpoint**. A healthy
   process/tunnel does not prove that the mailbox password or ChatGPT works.

### CLI instead of dashboard operation

Northflank provides an [official CLI](https://northflank.com/docs/v1/api/use-the-cli)
for projects, services, builds, secrets and operational checks. Current package
`0.13.0` requires Node **>=22.13.0** (the general docs still mention an older minimum).

```sh
npm install -g @northflank/cli@0.13.0
nf login --name mail-mcp
nf list projects
```

`nf login` opens a browser once to select/create an API token. Keep it outside the
repository; never share the token in a prompt. Restrict permissions to the intended
project and operations. After login, routine operation can use CLI/API.

Prepare the one-service request **locally, without API calls**:

```sh
python3 scripts/render_northflank.py \
  --repo-url https://github.com/EXAMPLE/yandex-mail-mcp \
  --deployment-plan YOUR_CONFIRMED_FREE_PLAN
```

Use your own repository URL. The generated file goes to ignored `.private/`;
real deployment identifiers stay outside tracked files. It requests **zero running
replicas and zero ports**, allowing secrets and Access to be configured first.

After reviewing the cost, repository URL and definition, provision it with:

```sh
nf create service combined --project YOUR_PROJECT_ID --file .private/combined-service.json
```

This command changes real infrastructure and can trigger a build; do not run it
until you authorize provisioning. Configure the restricted runtime secrets and
scale the single service to one replica after security review. The existing
`Harness project automation` role covers service operations and logs, but its
default permissions do not cover Secret groups, Git integration inspection or
billing reads. Configure secrets and the initial integration/cost checks in the
panel, or add only the required permissions to a scoped custom role. An Owner
token is unnecessary for routine service operation.

The template uses the documented create-service fields; acceptance by the
CLI and your live account is still untested. Build availability/free entitlement are account-dependent.

## 3. Configure Yandex IMAP

Follow [Yandex's mail-client instructions](https://yandex.com/support/yandex-360/customers/mail/en/mail-clients/others):

- Enable IMAP and the **App passwords and OAuth tokens** option in Mail settings.
- In Yandex ID, create a dedicated **Mail app password**. Use it instead of your
  primary account password. A mail app password is **not a read-only credential**.
- Set `MAIL_IMAP_DEFAULT_USER` to your account's required login and
  `MAIL_IMAP_DEFAULT_PASS` to that app password in the Northflank runtime Secret group.
- Default host is `imap.yandex.com`, port 993 with certificate-verified TLS.
  `MAIL_IMAP_DEFAULT_HOST` can be changed to another official Yandex hostname if
  required by Yandex's current guidance. The launcher forces TLS and port 993.
- Do not configure SMTP, Graph, EWS or additional accounts.

The launcher forces `MAIL_IMAP_WRITE_ENABLED=false` and
`MAIL_SMTP_WRITE_ENABLED=false`, even if someone accidentally overrides them in
runtime settings. Upstream still **advertises write tools**; do not select them in
ChatGPT. Invocation is blocked by upstream's write gates, not just tool descriptions.
These gates do not turn the underlying credential into a restricted mail credential.

## 4. Connect and test ChatGPT

Follow [OpenAI's current connection guide](https://developers.openai.com/apps-sdk/deploy/connect-chatgpt/).
The exact app/plugin/custom-MCP UI and access depend on your account/workspace.
This project is a private MCP endpoint, not a published App Directory submission.

1. Use `https://YOUR_MCP_HOSTNAME/mcp` with OAuth authentication.
2. Copy the exact redirect URI shown by ChatGPT into Access's Managed OAuth
   allowlist; do not assume one fixed callback works for every connection.
3. Check the discovered protected-resource and authorization metadata, a 401
   `WWW-Authenticate` challenge, PKCE **S256**, DCR and the `resource` parameter.
   [OpenAI auth requirements](https://developers.openai.com/apps-sdk/build/auth/)
   and [Cloudflare Managed OAuth](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/)
   describe the relevant contracts; they do not prove interoperability for this instance.
4. Authorize using only the allowed identity. Confirm a second identity is rejected.
5. Initially call `list_all_accounts` and read-only tools. Search with dates,
   folder, sender/subject and a bounded limit. Use the returned message ID and cursor.

Do not disable Access, publish a Northflank origin, add a Workers OAuth sample or
introduce a custom auth proxy to get past an error. Preserve the privacy boundary,
record the actual discovery/PKCE/callback failure and resolve it before live mail.

## Attachments: what is available and what is not proved

`imap_get_message` returns MIME metadata. For PDFs, use
`extract_attachment_text=true` to request server-side text extraction. Scanned
PDFs may have no extractable text; this server does not provide OCR.

`imap_get_attachment` always writes decoded bytes to a server-local file. That
path **cannot be opened by remote ChatGPT**. For a small attachment, request:

```json
{
  "message_id": "MESSAGE_ID_FROM_SEARCH",
  "filename": "ATTACHMENT_NAME_FROM_MESSAGE",
  "include_base64": true,
  "max_inline_bytes": 262144
}
```

Bytes are in `data.content_base64` with filename/type/size metadata. If they exceed
that ceiling, the field is null and `data.base64_omitted_reason` explains why.
Upstream allows raising the ceiling to 10,000,000 bytes, but context and response
limits often make that impractical. It fetches the entire MIME message and writes
the attachment even when inline data is omitted. Avoid repeated large downloads;
Northflank ephemeral files last until replacement and can fill the filesystem.
Restart/redeploy to clear disposable attachment data.

Local tests prove byte transport, **not** that ChatGPT automatically converts JSON
base64 into an analyzable PDF/image or downloadable file. Test a synthetic PDF and
image in your actual ChatGPT client before depending on that workflow. Native MCP
image/file content and attachment download URLs are not provided by this wrapper.
No public attachment file server is added.

## Security acceptance before real mail

- Anonymous/invalid/expired credentials cannot initialize MCP or invoke tools.
  Managed OAuth should yield an OAuth challenge, not only a browser 302 login.
- Only the intended identity can authorize. No Everyone/Bypass policy exists.
- Access discovery remains reachable without authenticated tool execution.
- Tunnel `Protect with Access` verifies the correct team/AUD.
- Northflank has no public, private or VPC service ports; no direct origin route.
- No secrets are in build args, image layers, Git, logs or this repository.
- With authorized live tests: unread messages stay unread after body/attachment
  reads; writes/sending are denied; attachment handling works in ChatGPT.
- Restart/redeploy and credential rotation recover; billing/Workers usage remains
  consistent with the chosen plan and the architecture.

Mail, HTML and attachments are untrusted input. Do not follow instructions inside
messages or execute files from mail. Access protects entry; it does not prevent
prompt injection or restrict what the allowed owner can ask the MCP to read.

## Local self-hosting and checks

Compose uses the same **one-container** design. Configure a named tunnel and
Access first, copy `.env.example` to an ignored `.env`, fill it privately, then:

```sh
docker compose up --build -d
```

No host ports are published. Compose additionally uses a read-only root filesystem
and a bounded temporary filesystem. These Compose hardening options are **not**
a claim that Northflank applies the same filesystem restrictions.

Run repository checks without any mailbox credentials:

```sh
python3 scripts/check_public.py
python3 tests/test_supervisor.py
docker build -t yandex-mail-mcp:local-check .
python3 tests/test_container.py
python3 tests/test_upstream.py --binary /path/to/checksum-verified/mail-mcp
```

The container test disables external networking and uses invented credentials.
Its HTTP checks use a sleeping connector double, with a separate test of the
actual cloudflared failure/shutdown path. The upstream test launches its own
synthetic loopback IMAP server and discards the
operator environment. It never logs into Yandex. No tokens are needed. Do not
supply live credentials to a smoke test. See [verification](docs/verification.md).

## Recovery and rotation

Replace the Yandex app password in the runtime Secret group, restart the one
service, verify access, then revoke the old app password. Rotate the tunnel token
in Cloudflare and the same Secret group, restart, and confirm the connector is
healthy. Revoke Access grants/sessions or change policy as needed; refresh and
session behavior must be verified with the actual client. Keep the old image
pins as a rollback reference; update all pins together after synthetic tests.
Pagination cursors and attachment files are ephemeral and are lost on replacement.
Do not print raw logs or secret-bearing API responses when diagnosing a failure.
