# WhatsApp Alerts

After every `Dashboard.refresh()` cycle, `alerts.py` checks the in-memory
dashboard data and pushes a notification to NanoClaw (the WhatsApp assistant)
when alert conditions are met. NanoClaw forwards the message to the main
WhatsApp group.

No separate polling — alerts fire on the same schedule as the dashboard's own
data refresh (every 3 minutes for a light update, every 30 minutes for a heavy
sync).

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

Pass `--env-file .env` to `uv run` so the environment variables are loaded:

```bash
cd /home/easysort/Easysort
DISPLAY=:0 uv run --env-file .env stats/office/main.py
```

Without `--env-file`, `uv run` does not automatically pick up `.env` and the
alerts will not be pushed (a warning is printed on each refresh instead).

## How it works

```
Dashboard.refresh()
  └─ alerts.check_and_notify(self)
       └─ checks dash.ip_devices and dash.devices against thresholds
       └─ loads/saves alert_state.json for deduplication
       └─ POST http://<nanoclaw>:8151/notify  {"secret": "...", "text": "..."}
            └─ NanoClaw validates secret, sends to main WhatsApp group
```

If `NANOCLAW_NOTIFY_URL` or `NANOCLAW_NOTIFY_SECRET` are not set, the check
still runs but a message is printed instead of pushed.
