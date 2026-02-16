"""Minimal chart rendering for raylib."""
from __future__ import annotations
from datetime import datetime, timedelta
from pyray import *
from storage import StoragePoint

BG = Color(28, 28, 34, 255)
GRID = Color(40, 40, 48, 255)
MUTED = Color(100, 100, 110, 255)
TMUX_OK_COLOR = Color(80, 200, 120, 255)
TMUX_NO_COLOR = Color(220, 80, 80, 255)

def draw_line_chart(x: int, y: int, w: int, h: int, points: list[StoragePoint], title: str, color: Color, days: int = 7):
    from datetime import datetime, timedelta
    draw_rectangle_rounded(Rectangle(x, y, w, h), 0.08, 8, BG)
    draw_text(title, x + 14, y + 10, 13, MUTED)
    
    if len(points) < 2:
        draw_text("—", x + w // 2 - 5, y + h // 2, 14, GRID)
        return
    
    left_pad, top, right_pad, bot = 44, 32, 14, 22
    cx, cy, cw, ch = x + left_pad, y + top, w - left_pad - right_pad, h - top - bot
    max_v, min_v = max(p.used_gb for p in points), min(p.used_gb for p in points)
    margin = (max_v - min_v) * 0.1 if max_v != min_v else max_v * 0.01
    max_v, min_v = max_v + margin, min_v - margin
    rng = max_v - min_v or 1
    
    # Grid + Y-axis labels
    for i in range(4):
        gy = cy + int(ch * i / 3)
        draw_line(cx, gy, cx + cw, gy, GRID)
        val = max_v - (rng * i / 3)
        draw_text(f"{val:.2f}G", x + 2, gy - 5, 9, MUTED)
    
    # X-axis: days ago (0=today on right, increasing left)
    now = datetime.now()
    t_start, t_end = now - timedelta(days=days), now
    step = 1 if days <= 7 else 10
    for d in range(0, days + 1, step):
        lx = cx + cw - int(cw * d / days)
        draw_text(str(d), lx - 3, cy + ch + 4, 10, MUTED)
    
    # Plot points by their actual timestamp position
    for i in range(1, len(points)):
        p0, p1 = points[i - 1], points[i]
        x1 = cx + int(cw * (p0.timestamp - t_start).total_seconds() / (days * 86400))
        x2 = cx + int(cw * (p1.timestamp - t_start).total_seconds() / (days * 86400))
        y1 = cy + int(ch * (1 - (p0.used_gb - min_v) / rng))
        y2 = cy + int(ch * (1 - (p1.used_gb - min_v) / rng))
        draw_line_ex(Vector2(x1, y1), Vector2(x2, y2), 2.0, color)
    # Final dot at last point
    last = points[-1]
    lx = cx + int(cw * (last.timestamp - t_start).total_seconds() / (days * 86400))
    ly = cy + int(ch * (1 - (last.used_gb - min_v) / rng))
    draw_circle(lx, ly, 4, color)

def draw_status_card(x: int, y: int, w: int, name: str, ok: bool, detail: str, warn: bool = False, path: str | None = None):
    if warn:
        bg, dot = Color(55, 50, 35, 255), Color(220, 180, 60, 255)
    elif ok:
        bg, dot = Color(35, 55, 45, 255), Color(80, 200, 120, 255)
    else:
        bg, dot = Color(55, 35, 40, 255), Color(220, 80, 80, 255)
    
    h = 68 if path else 50
    draw_rectangle_rounded(Rectangle(x, y, w, h), 0.15, 8, bg)
    draw_circle(x + 18, y + 20, 5, dot)
    draw_text(name, x + 34, y + 8, 15, WHITE)
    draw_text(detail, x + 34, y + 26, 12, MUTED)
    if path:
        max_chars = (w - 48) // 6
        display_path = path if len(path) <= max_chars else "..." + path[-(max_chars - 3):]
        draw_text(display_path, x + 34, y + 46, 10, Color(120, 120, 130, 255))

def draw_device_card(
    x: int, y: int, w: int, name: str, ok: bool, detail: str, path: str | None, over_temp: bool = False,
    checked_ago_seconds: int | None = None,
    tmux_running: bool | None = None,
):
    if over_temp:
        bg, dot = Color(60, 25, 25, 255), Color(255, 50, 50, 255)
    elif tmux_running is not None:
        bg = Color(35, 55, 45, 255) if tmux_running else Color(55, 35, 40, 255)
        dot = Color(80, 200, 120, 255) if tmux_running else Color(220, 80, 80, 255)
    elif ok:
        bg, dot = Color(35, 55, 45, 255), Color(80, 200, 120, 255)
    else:
        bg, dot = Color(55, 35, 40, 255), Color(220, 80, 80, 255)
    draw_rectangle_rounded(Rectangle(x, y, w, 68), 0.15, 8, bg)
    draw_circle(x + 18, y + 20, 5, dot)
    draw_text(name, x + 34, y + 8, 15, WHITE)
    draw_text(detail, x + 34, y + 26, 12, MUTED)
    if path:
        # Truncate path from the left if too long
        max_chars = (w - 48) // 6
        display_path = path if len(path) <= max_chars else "..." + path[-(max_chars - 3):]
        draw_text(display_path, x + 34, y + 46, 10, Color(120, 120, 130, 255))
    elif checked_ago_seconds is not None:
        ago = f"{checked_ago_seconds // 60}m" if checked_ago_seconds >= 60 else f"{checked_ago_seconds}s"
        draw_text(f"Checked {ago} ago", x + 34, y + 46, 10, Color(120, 120, 130, 255))


def _ts_to_float(dt: datetime) -> float:
    """Convert datetime to seconds for positioning (timezone-naive treated as local)."""
    return dt.timestamp() if hasattr(dt, "timestamp") else (dt - datetime(1970, 1, 1)).total_seconds()


def draw_ip_device_temp_chart(
    x: int, y: int, w: int, h: int,
    temp_history: list[tuple[datetime, float | None, bool]],
) -> None:
    """Draw a small temp-over-time chart. X=time, Y=temp °C. Segments green when tmux running, red when not."""
    draw_rectangle_rounded(Rectangle(x, y, w, h), 0.08, 6, BG)
    left_pad, top_pad, right_pad, bot_pad = 28, 12, 8, 18
    cx, cy, cw, ch = x + left_pad, y + top_pad, w - left_pad - right_pad, h - top_pad - bot_pad
    if cw <= 0 or ch <= 0 or not temp_history:
        draw_text("no data", x + 14, y + 14, 10, MUTED)
        return
    # Only points with valid temp for range and drawing
    valid = [(dt, t, tmux) for dt, t, tmux in temp_history if t is not None]
    if len(valid) < 2:
        draw_text("no temp", x + 14, y + 14, 10, MUTED)
        return
    t_min = min(_ts_to_float(dt) for dt, _, _ in valid)
    t_max = max(_ts_to_float(dt) for dt, _, _ in valid)
    temp_min = min(t for _, t, _ in valid)
    temp_max = max(t for _, t, _ in valid)
    t_range = t_max - t_min or 1
    margin = (temp_max - temp_min) * 0.1 if temp_max != temp_min else 1.0
    temp_lo, temp_hi = temp_min - margin, temp_max + margin
    temp_rng = temp_hi - temp_lo or 1
    # Y-axis labels (temp °C)
    for i in range(3):
        gy = cy + int(ch * i / 2)
        val = temp_hi - (temp_rng * i / 2)
        draw_text(f"{val:.0f}", x + 2, gy - 4, 9, MUTED)
    draw_text("C", x + 4, cy + ch + 2, 8, MUTED)
    # X-axis: time labels (oldest left, newest right)
    for i in range(3):
        frac = i / 2
        tx = cx + int(cw * frac)
        ts = t_min + t_range * frac
        dt_label = datetime.fromtimestamp(ts)
        ago_sec = t_max - ts
        if ago_sec < 60:
            label = "now"
        elif ago_sec < 3600:
            label = f"-{int(ago_sec // 60)}m"
        else:
            label = f"-{int(ago_sec // 3600)}h"
        draw_text(label, tx - 8, cy + ch + 2, 9, MUTED)
    # Grid
    for i in range(1, 3):
        gx = cx + int(cw * i / 2)
        draw_line(gx, cy, gx, cy + ch, GRID)
    for i in range(1, 2):
        gy = cy + int(ch * i / 2)
        draw_line(cx, gy, cx + cw, gy, GRID)
    # Line segments: color by tmux
    for i in range(1, len(valid)):
        dt0, t0, tmux0 = valid[i - 1]
        dt1, t1, tmux1 = valid[i]
        x0 = cx + int(cw * (_ts_to_float(dt0) - t_min) / t_range)
        x1 = cx + int(cw * (_ts_to_float(dt1) - t_min) / t_range)
        y0 = cy + int(ch * (1 - (t0 - temp_lo) / temp_rng))
        y1 = cy + int(ch * (1 - (t1 - temp_lo) / temp_rng))
        color = TMUX_OK_COLOR if tmux1 else TMUX_NO_COLOR
        draw_line_ex(Vector2(x0, y0), Vector2(x1, y1), 2.0, color)
    # Last point dot
    lx = cx + int(cw * (_ts_to_float(valid[-1][0]) - t_min) / t_range)
    ly = cy + int(ch * (1 - (valid[-1][1] - temp_lo) / temp_rng))
    dot_color = TMUX_OK_COLOR if valid[-1][2] else TMUX_NO_COLOR
    draw_circle(lx, ly, 3, dot_color)


def draw_storage_summary(x: int, y: int, w: int, name: str, used: float, total: float):
    draw_rectangle_rounded(Rectangle(x, y, w, 60), 0.1, 8, BG)
    pct = (used / total * 100) if total > 0 else 0
    draw_text(name, x + 14, y + 10, 14, WHITE)
    draw_text(f"{used:.0f}/{total:.0f} GB", x + w - 90, y + 10, 13, MUTED)
    
    bar_w, bar_h, bar_y = w - 28, 10, y + 38
    draw_rectangle_rounded(Rectangle(x + 14, bar_y, bar_w, bar_h), 0.5, 4, GRID)
    fill_w = int(bar_w * min(pct / 100, 1))
    bar_color = Color(80, 200, 120, 255) if pct < 70 else Color(240, 180, 60, 255) if pct < 90 else Color(220, 80, 80, 255)
    if fill_w > 0: draw_rectangle_rounded(Rectangle(x + 14, bar_y, fill_w, bar_h), 0.5, 4, bar_color)
