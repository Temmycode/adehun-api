# WebSockets

Neither socket appears in `openapi.json` — FastAPI does not emit WebSocket routes
into an OpenAPI document. This file is the contract instead. If you change a
frame shape, change it here in the same commit.

## Connecting

Both sockets authenticate with the **access token as a query parameter**, not an
`Authorization` header (browsers cannot set headers on a WebSocket handshake):

```
wss://<host>/wallet/ws?token=<access_token>
wss://<host>/agreements/ws?token=<access_token>
```

A missing or invalid token closes the socket immediately with
`1008 POLICY_VIOLATION`. There is no auth error frame — handle the close code.

### Delivery guarantees — read this before designing around it

`app/realtime/manager.py` holds connections in a **plain in-process dict** keyed
by user id. That means:

* **No fan-out across workers or pods.** With more than one process, a push
  reaches a client only if it happens to be connected to the process handling
  that request. Anything that must be reliable needs the HTTP fallback.
* **Nothing is buffered or replayed.** A frame emitted while a client is
  disconnected is lost — there is no queue and no cursor.
* Every push is best-effort and wrapped in try/except; a socket failure never
  fails the HTTP request that triggered it.

Treat sockets as a latency optimisation over polling, never as the source of
truth.

---

## `/wallet/ws`

### On connect

Exactly one frame, pushed immediately:

```jsonc
{
  "type": "WALLET_STATE",
  "available_balance": 12500.0,   // float, not string
  "escrow_balance": 400000.0,
  "total_balance": 412500.0,      // available + escrow, precomputed
  "currency": "NGN"
}
```

### Pushed later

The same `WALLET_STATE` frame is re-pushed when a Paystack webhook credits the
wallet. Balances are floats here, unlike the REST API, which returns them as
decimal strings.

### Inbound

None. The server reads and discards; the read loop exists only to detect
disconnects.

### HTTP fallback — **this exists, use it**

`GET /wallet` returns `APIResponse[WalletBalanceResponse]` with the same
balances. Given the single-process caveat above, the socket should be treated as
an optimisation on top of this endpoint, not a replacement for it: poll or
refetch on resume, and reconcile.

---

## `/agreements/ws`

### On connect

```jsonc
{ "type": "connected", "message": "Agreement websocket connected" }
```

### Inbound: fetch one agreement

```jsonc
{ "type": "get_agreement", "agreement_id": "<uuid>" }
```

Replies with an `agreement` frame (no `event` key), or:

```jsonc
{ "type": "error", "message": "agreement_id is required" }
{ "type": "error", "message": "Unable to fetch agreement", "agreement_id": "<uuid>" }
{ "type": "error", "message": "Unsupported websocket event type" }
```

### Pushed: agreement state changed

**Yes — this socket does push agreement updates.** A client listener for it is
not dead code.

```jsonc
{
  "type": "agreement",
  "event": "updated",
  "agreement_id": "<uuid>",
  "agreement": { /* the full AgreementResponse, as in the REST API */ }
}
```

`agreement` is `AgreementResponse.model_dump(mode="json")` — the exact schema
`GET /agreements/{id}` returns, so one deserialiser covers both.

`event` values, and what triggers each:

| `event` | Trigger |
|---|---|
| `created` | `POST /agreements` — sent to the creator and the invitee |
| `updated` | `POST /agreements/{id}/accept`, `.../reject`, `.../fund` |
| `released` | Escrow released — both the manual `/release` and the automatic release on final condition approval |
| `cancelled` | `POST /agreements/{id}/cancel` |
| `refunded` | `POST /agreements/{id}/refund` (admin) |
| `raised` | A dispute was opened on the agreement |
| `resolved` | A dispute on the agreement was resolved |

Treat any unrecognised `event` as a plain refresh — the list will grow. The
`agreement` payload is always complete, so `event` is a hint, not something you
need to switch on exhaustively.

### Pushed: dispute state changed

Delivered on this same socket — `ws_manager` is keyed by user, so there is no
separate dispute socket to open.

```jsonc
{
  "type": "dispute",
  "event": "raised",
  "dispute_id": "<uuid>",
  "agreement_id": "<uuid>",
  "dispute": { /* the full DisputeResponse */ }
}
```

`event` is `raised` or `resolved`. A dispute change always sends **two** frames
to each party, in this order:

1. `{"type": "dispute", ...}`
2. `{"type": "agreement", "event": "raised" | "resolved", ...}`

The second carries the agreement's new `status` (`disputed`, or the restored
prior status). The ordering is deliberate: the agreement payload is read after
the transaction commits and the cache is invalidated, so it never carries a
stale status.

### HTTP fallback

`GET /agreements/{id}` and `GET /agreements`.
