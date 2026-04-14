# Stats JSON API

A lightweight HTTP API that runs alongside the hosted browser dashboard and serves the monitoring data as JSON.

## Quick start

The API starts automatically when you run `main.py`. No extra setup needed.

```bash
python main.py
```

To change the port, set `STATS_API_PORT`:

```
STATS_API_PORT=9000 python main.py
```

## Endpoints

All responses are `application/json` with CORS enabled (`Access-Control-Allow-Origin: *`).

### `GET /api/status`

Returns the full dashboard state in a single response.

```json
{
  "timestamp": "2026-02-22T14:30:00.000000",
  "devices": [ ... ],
  "ip_devices": [ ... ],
  "runners": [ ... ],
  "tracking": [ ... ],
  "storage": { "local": { ... }, "cloud": { ... } }
}
```

### `GET /api/devices`

Device health from the registry. Each entry:

| Field | Type | Description |
|---|---|---|
| `name` | string | Device name |
| `ok` | bool | Healthy if last upload was within the 4 hour threshold |
| `age_minutes` | int or null | Minutes since last media file |
| `last_seen` | string or null | ISO timestamp of last file |
| `last_path` | string or null | Registry path of last file |
| `error` | string or null | Error message if unhealthy |

### `GET /api/ip_devices`

IP device health (from `devices.txt`, polled via `/health`). Each entry:

| Field | Type | Description |
|---|---|---|
| `name` | string | Device name |
| `ok` | bool | Healthy (temp ok, tmux running) |
| `detail` | string | Human-readable status line |
| `over_temp` | bool | True if temperature exceeds 85 C |
| `tmux_running` | bool | Whether tmux session is active |
| `temp_history` | array | Recent readings: `{ timestamp, temp_c, tmux_running }` |

### `GET /api/runners`

Runner health (verdis uploader, inference). Each entry:

| Field | Type | Description |
|---|---|---|
| `name` | string | Runner name |
| `ok` | bool | Healthy |
| `warn` | bool | Warning state (e.g. outside active hours) |
| `detail` | string | Human-readable status |
| `path` | string or null | Relevant registry path |
| `pending` | int | Number of pending items |

### `GET /api/tracking`

Tracking service health (argo weeks/months). Same schema as runners.

### `GET /api/storage`

Storage metrics for local and cloud volumes:

```json
{
  "local": {
    "name": "MiniKeyValue",
    "current": {
      "used_gb": 450.12,
      "total_gb": 1000.0,
      "free_gb": 549.88,
      "percent_used": 45.0
    },
    "history": [
      { "timestamp": "2026-02-22T12:00:00", "used_gb": 449.5, "total_gb": 1000.0 }
    ]
  },
  "cloud": { ... }
}
```

## Notes

- The API always returns the latest cached state from the hosted dashboard service.
- The service performs a single scheduled refresh cycle using the heavy sync path.
- API responses are sent with `Cache-Control: no-store` so browser clients can poll for live updates.
- No authentication — intended for local / private network use.
