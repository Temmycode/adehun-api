# Adehun API

FastAPI backend for Adehun, an escrow app: wallets funded through Paystack,
agreements with conditions, escrow lock/release/refund, disputes, in-app
notifications and websockets for live updates.

## Stack

Python 3.11, FastAPI, SQLModel/SQLAlchemy on Postgres, Alembic migrations,
Redis (optional cache and rate-limit store), Paystack, Cloudinary, Firebase
Auth (Google sign-in), Resend (email).

## Layout

```
app/
  routers/      HTTP + websocket routes. Cross-feature orchestration lives here.
  service/      Business logic. Services never call other feature services.
  repository/   Database access; every wallet mutation takes a row lock.
  schemas/      Pydantic request/response models.
  models/       SQLModel tables.
  core/         authz helpers, validators, idempotency, response envelope.
  templates/    HTML for the public invite page.
alembic/        migrations (always `alembic upgrade head`, never create_all)
tests/          pytest suite against a real Postgres database
docs/websockets.md  the websocket contract
```

## Setup

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env.local        # fill in values
createdb adehun_db
alembic upgrade head
uvicorn app.main:app --reload
```

`ENVIRONMENT` selects the dotenv file: `development` (default) reads
`.env.local`, `test` reads `.env.test`, `production` reads `.env.production`.
In production, set real environment variables and ship no file.

Set `DEBUG=true` locally to enable `/docs` and the dev-only login routes.
They can never load when `ENVIRONMENT=production`.

## Tests

```bash
pytest -q
```

The suite creates and migrates a throwaway `adehun_test` database on your
local Postgres (defaults to the `/tmp` socket, override with
`TEST_DATABASE_HOSTNAME`, `TEST_DATABASE_USERNAME`, `TEST_DATABASE_PASSWORD`).
Paystack, Firebase and email are replaced by in-process fakes; Redis is not
needed.

## Money model

- Amounts are naira with two decimals as `Decimal` internally and decimal
  strings on the wire. Kobo exists only at the Paystack boundary.
- The ledger (`transaction` table) is the source of truth; wallet balances are
  derived and checked by row-locked updates.
- Wallet funding credits only after `charge.success` is verified with
  Paystack. Escrow lock, release and refund are idempotent on fixed references,
  so replays never double-move money.
- Withdrawals debit first, then transfer; a provider rejection reverses, a
  timeout leaves the entry pending for the webhook or reconciliation.

## Authorization model

- Bearer JWT (HS256, pinned). Access tokens are short-lived; refresh tokens are
  persisted, rotated on use and revoked on logout or reuse.
- Every agreement, condition and asset route checks the caller is a
  participant (writes) or a participant/pending invitee (reads).
- Only the depositor approves or rejects conditions and uploaded assets.
- `/admin/*` requires `user.is_admin`, granted only by SQL.

## Webhooks

`POST /wallet/webhook/paystack` with the `x-paystack-signature` HMAC-SHA512
header, verified against the active secret only. Events are deduplicated on
`data.id`, failed events are re-driven at most 5 times.

## Invitations

Emails link to `{WEB_URL}/invite?token=...`, an HTML page served by this API
that opens the mobile app via `adehun://open/invite?token=...`. The app calls
`GET /invitations/{token}` to route. `/.well-known/assetlinks.json` is served
for Android App Links once `ANDROID_CERT_SHA256` is set.

## Deployment checklist

- `ENVIRONMENT=production`, `DEBUG=false`, `DATABASE_SSLMODE=require`,
  `TRUST_PROXY_HEADERS=true`, `WEB_URL=https://<host>`
- run uvicorn with `--proxy-headers --forwarded-allow-ips='*' --no-access-log`
- `alembic upgrade head` on every deploy
- Paystack live keys and `PAYSTACK_LIVE_MODE=true` only when ready;
  `PAYSTACK_TRANSFERS_ENABLED=true` only with a funded Paystack balance
- see `../SECURITY_NOTES.md` for the secret-rotation list
