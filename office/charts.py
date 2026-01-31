"""Minimal chart rendering for raylib."""
from __future__ import annotations
from pyray import *
from storage import StoragePoint

BG = Color(28, 28, 34, 255)
GRID = Color(40, 40, 48, 255)
MUTED = Color(100, 100, 110, 255)

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

def draw_status_card(x: int, y: int, w: int, name: str, ok: bool, detail: str):
    bg = Color(35, 55, 45, 255) if ok else Color(55, 35, 40, 255)
    draw_rectangle_rounded(Rectangle(x, y, w, 50), 0.15, 8, bg)
    dot = Color(80, 200, 120, 255) if ok else Color(220, 80, 80, 255)
    draw_circle(x + 18, y + 25, 5, dot)
    draw_text(name, x + 34, y + 12, 15, WHITE)
    draw_text(detail, x + 34, y + 30, 12, MUTED)

def draw_device_card(x: int, y: int, w: int, name: str, ok: bool, detail: str, path: str | None):
    bg = Color(35, 55, 45, 255) if ok else Color(55, 35, 40, 255)
    draw_rectangle_rounded(Rectangle(x, y, w, 68), 0.15, 8, bg)
    dot = Color(80, 200, 120, 255) if ok else Color(220, 80, 80, 255)
    draw_circle(x + 18, y + 20, 5, dot)
    draw_text(name, x + 34, y + 8, 15, WHITE)
    draw_text(detail, x + 34, y + 26, 12, MUTED)
    if path:
        # Truncate path from the left if too long
        max_chars = (w - 48) // 6
        display_path = path if len(path) <= max_chars else "..." + path[-(max_chars - 3):]
        draw_text(display_path, x + 34, y + 46, 10, Color(70, 70, 80, 255))

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
