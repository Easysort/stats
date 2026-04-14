# WhatsApp Alerts

After every hosted dashboard refresh cycle, `alerts.py` checks the latest
snapshot data and pushes a notification to NanoClaw (the WhatsApp assistant)
when alert conditions are met. NanoClaw forwards the message to the main
WhatsApp group.

No separate polling — alerts fire on the same schedule as the hosted
dashboard's own refresh cycle.

## Alert rules

### IP device connection failures

Fires when an IP device (`dash.ip_devices`) has `ok = False` for **3
consecutive refresh cycles** (roughly 9 minutes of sustained failure at the
3-minute interval).

Resets when the device reports `ok = True`. A fresh alert fires if it fails
again later.

Example message:
```
*Stats Alert* — IP device *my-device* has failed 3 polls in a row (connection refused).
```

### Camera device offline (> 3 hours)

Fires when a camera device (`dash.devices`) has `age_minutes > 180` — no media
has arrived in over 3 hours.

Resets when `age_minutes` drops back to ≤ 180.

Example message:
```
*Stats Alert* — Camera *cam-north* has been offline for 3h 42m. Last seen: 2026-02-22T10:15:00.
```

## Deduplication

Each device has its own state entry. Once an alert fires, no further alerts are
sent for that device until it recovers. State is persisted to
`stats/office/alert_state.json` so a process restart does not re-fire
already-sent alerts.

## Setup

### 1. Environment variables

Add to `easysort/.env` (loaded via `--env-file .env` when running — see below):

```
NANOCLAW_NOTIFY_URL=http://<nanoclaw-tailscale-ip>:8151
NANOCLAW_NOTIFY_SECRET=<shared-secret>
```

The secret must match `NOTIFY_SECRET` in the NanoClaw `.env` file.

### 2. Run script

Pass `--env-file .env` to `uv run` if you want the environment variables loaded
explicitly:

```bash
cd /home/easysort/Easysort
uv run --env-file .env python stats/office/main.py
```

Without the NanoClaw env vars, alerts are not pushed and a warning is printed
instead.

## How it works

```text
OfficeMonitorService._refresh_once()
  -> alerts.check_and_notify(snapshot)
  -> checks snapshot.ip_devices and snapshot.devices against thresholds
  -> loads/saves alert_state.json for deduplication
  -> POST http://<nanoclaw>:8151/notify  {"secret": "...", "text": "..."}
```

If `NANOCLAW_NOTIFY_URL` or `NANOCLAW_NOTIFY_SECRET` are not set, the check
still runs but a message is printed instead of pushed.
