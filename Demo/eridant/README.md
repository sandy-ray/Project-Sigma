# Eridant prototype

The application now runs behind server-side authentication. Do not open
`eridant-demo.html` directly; the authenticated server is the security boundary.

## First-time setup

Provision a user. The password is read from a hidden terminal prompt and only a
salted hash is stored in SQLite.

```bash
python3 auth_server.py create-user \
  --email analyst@example.com \
  --name "Credit Analyst" \
  --role analyst
```

To change an existing user's password (local or on Render Shell):

```bash
python3 auth_server.py reset-password --email analyst@example.com
```

You will be prompted twice for the new password. On Render, open your service →
**Shell**, then run the same command against the deployed app directory (`/app`).
Use the exact email address already registered in production.

Start the local server:

```bash
cp .env.example .env
# Add your Anthropic API key to .env, then:
python3 auth_server.py serve
```

Set `ANTHROPIC_API_KEY` in `.env` (or export it) so draft credit analysis runs
automatically when a complete credit file is opened. Optional `ANTHROPIC_MODEL`
defaults to `claude-sonnet-4-6`. For faster local demos, combine
`ANTHROPIC_MODEL=claude-haiku-4-5`, a lower `ANTHROPIC_MAX_TOKENS` (for example
`8192`), and `ANTHROPIC_FAST_ANALYSIS=1` (sends extracted fields only instead of
full document text).

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000). There are no default
or hardcoded credentials.

## Realtime document parsing

The authenticated demo accepts safe Word documents into a local staging flow.
Each file is parsed immediately in the browser across its complete textual Word
parts, then classified primarily from document content with the filename used
only as a secondary hint. Ambiguous or duplicate classifications remain staged
for manual document-type assignment; an analyst can also correct an assigned
type at any time.

Initial intake only rejects files that are not supported documents or violate structural safety
limits (for example encryption, macros, unsafe ZIP paths, excessive expansion,
or missing core Word parts). Missing business fields do not reject the upload.
They are shown on the assigned document and prevent the credit file from becoming
ready until required document types contain their required fields.
There is no bundled specimen-value fallback. Extraction remains in
the browser. For a layout-faithful source preview, the authenticated page sends
the validated document bytes to the authenticated document-render endpoint. The
server converts them to PDF inside an isolated temporary directory and removes
the source document and PDF immediately after returning the PDF response. The PDF remains
in browser memory and is displayed with the vendored PDF.js runtime.

PDF conversion requires LibreOffice (`soffice`) on the server PATH. Local macOS
installs are detected automatically. The Render deploy uses a Docker image with
LibreOffice Writer so document PDF preview works on the public URL. When it is
installed elsewhere, set `SIGMA_SOFFICE` to the absolute executable path before
starting the server. A conversion failure does not change extracted values or
issue an approval or decline; the viewer shows the extracted document fallback.

Local parsing and reconciliation never produce an approval or decline. The
**Credit review assistant** remains pending until a configured Anthropic or
OpenAI-compatible provider successfully returns a draft analysis. A missing key,
invalid response, timeout, or failed API request leaves the credit file without a
draft summary — the human analyst retains full decision authority.

When the analyst explicitly generates a draft analysis, the assistant receives
the complete normalized paragraph and table content of all five documents,
including textual Word headers, footers, notes, comments, footnotes, and
endnotes. Every paragraph and non-empty table cell has a stable evidence ID. The
existing no-null extracted field catalog, derived metrics, and five deterministic
reconciliations accompany the full document content as supporting data; they no
longer define the limit of the review. Expected values that were not located use
the explicit `not_found_in_parsed_packet` state rather than an ambiguous `null`.

The system prompt instructs the assistant to summarize cross-document
discrepancies, standalone credit risks, missing or unverifiable information,
positive factors, borrower questions, and next steps, then return a draft
recommendation for analyst review: `APPROVED`, `NEEDS_FURTHER_INVESTIGATION`, or
`DECLINED`. The browser strictly validates the response shape and every cited
evidence ID before showing the draft. Citation links open the generated PDF and
highlight the cited source text. Requests use deterministic document ordering and
temperature zero. A successful draft is cached in memory by the complete credit file,
prompt version, provider, and model hash so repeated clicks on an unchanged
file return the same validated result without another provider call.

Full normalized document content leaves the browser only when the analyst opens
the analysis workspace with a complete credit file. The server then
calls Anthropic automatically via **POST /api/credit-analysis** using
`ANTHROPIC_API_KEY` from the environment (or a local `.env` file). Identical
credit files are cached in server memory so the provider is not called again.

Six complete fictional test sets are available in [`test_packets`](test_packets/README.md):

- `01_decline_as_presented`
- `02_approve_with_conditions`
- `03_clean_approve`
- `04_needs_further_investigation`
- `05_compliance_hold`
- `06_incomplete_resubmission`

Choose all five files from one folder at the same time, resolve any staged type
assignments or incomplete fields, then open the analysis. The folder name states
the scenario represented by its figures or its expected validation state; only
the configured assistant can produce a draft recommendation for analyst review.
The documents are realistic fictional facsimiles for testing; they are not
official bank, IRS, or California Secretary of State forms.

## CRE (income property) credit type

The upload card has a **C&I / CRE** switch. CRE is a renewal or refinance of a loan
secured by an income property, with the same journey as C&I: upload → reading →
bank-file retrieval → workspace → explain drawer → post-closing monitoring plan.

- **Borrower package (9 PDFs, all required):** loan request (01), rent roll (02),
  property operating statements (03), SPE financial statements (04), debt schedule
  (05), compliance certificate (11), anchor lease (06), anchor lease amendment (07)
  and shop lease abstracts (08).
- **Bank file (2 PDFs):** existing loan agreement (10) and appraisal (09). If they
  were dropped with the package, the retrieval step confirms them. **Load sample CRE
  file** pulls them from the sample packet. Otherwise the retrieval step asks for
  them, and **Continue** stays blocked until both are present.
- Document 12, the bank's own credit memo, is the analyst's finished work. It is
  rejected if uploaded and is never served.

PDFs are read in the browser through the PDF.js text layer. Text is rebuilt into
lines and table cells, and each document is classified by its content (the filename
is only a hint). Fields are found by label, not position, so names, tenant counts,
dates and amounts can change between deals. Missing required fields are listed on
the document and block **Analyze**. Every figure keeps its page, and evidence opens
the real PDF page with the source text highlighted.

The workspace recomputes 12 cross-document checks (D01–D12). They cover:
- covenant DSCR on the loan agreement's own definitions vs the certificate, and the
  add-backs that need lender acceptance;
- the anchor's early-termination right, and undisclosed affiliate debt;
- NOI and occupancy trend, and lease-date conflicts;
- recovery leakage, occupancy vs presented and appraised, and the appraisal's
  market-rent assumption;
- mortgage-balance dating, newer lease evidence, and anchor identity.

Severity thresholds are listed in `RULES` in the CRE script. The proposed rate comes
from the loan request when it is stated. Otherwise it is implied from the debt
service in the compliance certificate. The **Credit review assistant** uses the same
`/api/credit-analysis` endpoint as C&I, with a CRE prompt
(`eridant_cre_full_document_credit_judge_v1`). The rent-roll, covenant-test and
monitoring views are built from the same parsed data.

### Overrides and audit trail (CRE)

The analyst has the final say on every flagged item. **Override** sits on each of the
12 check cards and on each External verification card; the assistant's own extra points
(those not covered by a check) have **Dismiss**. An override records a decision (clear,
resolved with new evidence, accept with a condition, or change severity), a reason code
and a required explanation, with optional document-and-page evidence. Overridden items
are never hidden: they move to an "overridden" group and the counts update. **Undo** is
a new entry, never a deletion. The covenant test's "Bank accepts it" switches are logged
too.

A deal is identified by a SHA-256 fingerprint of its documents, so re-uploading the same
files brings back its decisions. Overrides and the append-only audit log live in the
server database (`cre_overrides`, `cre_audit_log`). Each entry stores the user and role
from the login session, server time, before and after, reason, note, evidence, deal,
rule and prompt versions, model, session reference, IP and a hash chained to the previous
entry. The **Audit trail** tab lists them and exports CSV.

**Roles.** There are two roles: **Credit Analyst** (`analyst`) and **Credit Supervisor**
(`supervisor`). Both can analyse, override, dismiss and view or export the audit log. Only a
Credit Supervisor can **Undo** an override, and the server enforces this. Each item keeps its
running history, including undone decisions. The audit log shows User ID, role, time and action
for every entry, can be filtered by role or user, and each row links back to its item. Open pages
pick up other users' decisions every 20 seconds. Create users with
`create-user --role supervisor` (or `analyst`). On Render, set
`SIGMA_BOOTSTRAP_SUPERVISOR_EMAIL`, `SIGMA_BOOTSTRAP_SUPERVISOR_PASSWORD` and
`SIGMA_BOOTSTRAP_SUPERVISOR_NAME` to add a supervisor next to the bootstrap analyst. Older
databases are upgraded to allow the supervisor role on start.

The free Render plan wipes the database on every redeploy, which would erase the audit
log. Before relying on it, attach a persistent disk and point `SIGMA_AUTH_DB` at it.

## Invite-based sign-up

Create a one-time invitation for the new user's exact email address:

```bash
python3 auth_server.py create-invite \
  --email new.analyst@example.com \
  --role analyst \
  --origin http://127.0.0.1:8000
```

Send the generated link to that user. The invitation expires after 24 hours by
default, can be used once, and cannot be used with a different email address.
The raw invitation token is printed once and only its SHA-256 hash is stored in
the database. Use `--hours` to select a lifetime between 1 and 168 hours.

Self-service public registration is intentionally not available: every account
requires an administrator-generated invitation, and the invitation controls the
new account's role.

By default, user and session records are stored in `sigma-auth.db`. Set
`SIGMA_AUTH_DB` or pass `--db` to place the database elsewhere. An optional
`SIGMA_PASSWORD_PEPPER` may be supplied from a secret manager; it must remain
stable for existing password hashes to keep working.

## Deploy to Render

The repo includes a `render.yaml` blueprint. After you connect GitHub to Render, the
public URL will look like:

`https://eridant.onrender.com`

(Use your service name if you change it in `render.yaml`.)

### One-time setup

1. **Push this repo to GitHub** (commit all Eridant changes first).
2. Open [Render Dashboard](https://dashboard.render.com/) → **New** → **Blueprint**.
3. Connect the `sigma` repository and apply the blueprint.
4. When prompted, set these **secret** environment variables:

| Variable | Purpose |
| --- | --- |
| `SIGMA_BOOTSTRAP_EMAIL` | Login email for the first analyst account |
| `SIGMA_BOOTSTRAP_PASSWORD` | Initial password (min 12 characters) |
| `ANTHROPIC_API_KEY` | Enables the credit review assistant |
| `SIGMA_PUBLIC_ORIGIN` | Your public URL, e.g. `https://eridant.onrender.com` |

   `SIGMA_PUBLIC_ORIGIN` can match the URL Render shows after the first deploy.
   Render also sets `RENDER_EXTERNAL_URL`, which the server uses as a fallback.

5. Optional: set `SIGMA_PASSWORD_PEPPER` to a long random secret and **keep it stable**
   across redeploys so existing passwords keep working.

6. Wait for the deploy to finish, then open your Render URL and sign in with the
   bootstrap email and password.

### After deploy

- **Change password:** Render → your service → **Shell** →  
  `python3 auth_server.py reset-password --email you@example.com`
- **Add users:** Shell → `python3 auth_server.py create-invite --email new@example.com --origin https://eridant.onrender.com`

On the free plan, the SQLite database is **ephemeral** — redeploys can reset users.
For a persistent demo, attach a Render disk and set `SIGMA_AUTH_DB` to a path on that
volume (for example `/var/data/sigma-auth.db`).

## Production boundary

Terminate TLS at a trusted reverse proxy and start the server with both options:

```bash
python3 auth_server.py serve \
  --host 0.0.0.0 \
  --secure-cookie \
  --public-origin https://eridant.example.com
```

`--secure-cookie` changes the session cookie to a `__Host-` cookie and enables
the `Secure` attribute and HSTS. Keep the SQLite database outside the public web
root with filesystem permissions limited to the service account.

This first authentication layer provides:

- PBKDF2-HMAC-SHA256 password hashing with unique salts and 600,000 iterations
- opaque server-side sessions with absolute and idle expiration
- `HttpOnly`, `SameSite=Strict` session cookies (`Secure` in HTTPS mode)
- session invalidation on logout
- origin validation, Fetch Metadata checks, and CSRF tokens for state-changing endpoints
- authenticated, CSRF-protected document-to-PDF rendering with repeat document safety validation
- per-account and per-IP login throttling
- server-side protection of the application HTML
- one-time, expiring, email-bound sign-up invitations

It does not yet provide password reset in the browser, MFA, SSO/SAML, account administration,
audit-log export, or a sandboxed document-conversion service. LibreOffice should
run in a separately constrained worker/container before a real bank deployment.

## Tests

```bash
PYTHONPYCACHEPREFIX=/tmp/eridant-pycache python3 -m unittest -v
```
