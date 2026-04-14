# Stats

LAN-hosted monitoring dashboard for production infrastructure, with a browser
UI, JSON API, persisted last-known state, and optional WhatsApp alert
integration.

## Running

```bash
cd /home/easysort/Easysort
uv run --env-file .env python stats/office/main.py
```

The dashboard binds to `0.0.0.0:8150` by default.

- On the device: `http://localhost:8150`
- From another machine on the same network: `http://<device-ip>:8150`

`--env-file .env` is optional, but useful when you want registry, Supabase, or
alert settings loaded explicitly.

## Docs

| File | Description |
|---|---|
| `office/API.md` | JSON API endpoints served on port 8150 |
| `office/ALERTS.md` | WhatsApp alert rules, setup, and env vars |
