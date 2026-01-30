"""Minimal chart rendering for raylib."""
from __future__ import annotations
from pyray import *
from storage import StoragePoint

def draw_line_chart(x: int, y: int, w: int, h: int, points: list[StoragePoint], title: str, color: Color):
    """Draw a simple line chart with storage data."""
    # Background
    draw_rectangle(x, y, w, h, Color(30, 30, 30, 255))
    draw_rectangle_lines(x, y, w, h, Color(60, 60, 60, 255))
    
    # Title
    draw_text(title, x + 10, y + 5, 14, WHITE)
    
    if len(points) < 2:
        draw_text("No data", x + w // 2 - 25, y + h // 2, 12, GRAY)
        return
    
    # Chart area
    pad, top_pad = 10, 25
    cx, cy, cw, ch = x + pad, y + top_pad, w - pad * 2, h - top_pad - pad
    
    # Scale
    max_val = max(p.used_gb for p in points) * 1.1 or 1
    min_val = min(p.used_gb for p in points) * 0.9
    val_range = max_val - min_val or 1
    
    # Draw grid lines
    for i in range(5):
        gy = cy + int(ch * i / 4)
        draw_line(cx, gy, cx + cw, gy, Color(50, 50, 50, 255))
        val = max_val - (val_range * i / 4)
        draw_text(f"{val:.0f}G", cx - 5, gy - 6, 10, GRAY)
    
    # Draw line
    for i in range(1, len(points)):
        x1 = cx + int(cw * (i - 1) / (len(points) - 1))
        x2 = cx + int(cw * i / (len(points) - 1))
        y1 = cy + int(ch * (1 - (points[i - 1].used_gb - min_val) / val_range))
        y2 = cy + int(ch * (1 - (points[i].used_gb - min_val) / val_range))
        draw_line(x1, y1, x2, y2, color)
        draw_circle(x2, y2, 3, color)

def draw_status_card(x: int, y: int, w: int, name: str, ok: bool, detail: str):
    """Draw a status card for health checks."""
    color = Color(40, 80, 40, 255) if ok else Color(100, 40, 40, 255)
    draw_rectangle(x, y, w, 50, color)
    draw_rectangle_lines(x, y, w, 50, Color(80, 80, 80, 255))
    
    # Status indicator
    indicator = GREEN if ok else RED
    draw_circle(x + 20, y + 25, 8, indicator)
    
    # Text
    draw_text(name, x + 40, y + 10, 16, WHITE)
    draw_text(detail, x + 40, y + 30, 12, LIGHTGRAY)

def draw_storage_summary(x: int, y: int, w: int, name: str, used: float, total: float):
    """Draw a storage summary bar."""
    h = 60
    draw_rectangle(x, y, w, h, Color(30, 30, 30, 255))
    draw_rectangle_lines(x, y, w, h, Color(60, 60, 60, 255))
    
    # Title and values
    pct = (used / total * 100) if total > 0 else 0
    draw_text(name, x + 10, y + 5, 14, WHITE)
    draw_text(f"{used:.1f} / {total:.1f} GB ({pct:.0f}%)", x + 10, y + 22, 12, LIGHTGRAY)
    
    # Progress bar
    bar_w, bar_h = w - 20, 12
    draw_rectangle(x + 10, y + 42, bar_w, bar_h, Color(50, 50, 50, 255))
    fill_w = int(bar_w * min(pct / 100, 1))
    bar_color = GREEN if pct < 70 else ORANGE if pct < 90 else RED
    draw_rectangle(x + 10, y + 42, fill_w, bar_h, bar_color)
