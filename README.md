# Stats

Raylib-based monitoring dashboard for production infrastructure, with a JSON
API and WhatsApp alert integration.

## Running

```bash
cd /home/easysort/Easysort
DISPLAY=:0 uv run --env-file .env stats/office/main.py
```

`--env-file .env` is required to load the alert notification credentials.
Without it, the dashboard and API still work but WhatsApp alerts will not be
pushed.

## Docs

| File | Description |
|---|---|
| `office/API.md` | JSON API endpoints served on port 8150 |
| `office/ALERTS.md` | WhatsApp alert rules, setup, and env vars |
