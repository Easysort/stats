"""Easysort Stats Dashboard - raylib-based monitoring UI."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from pyray import *
from health import get_device_health, get_runner_health, DeviceStatus, RunnerStatus
from storage import get_all_storage, StorageHistory
from charts import draw_line_chart, draw_status_card, draw_storage_summary
from easysort.registry import Registry

# Config
WIDTH, HEIGHT = 1280, 800
MKV_VOLUME = os.getenv("MKV_VOLUME", "/media/easysort/lenovo")
REFRESH_INTERVAL = 30  # seconds

class Dashboard:
    def __init__(self):
        self.devices: list[DeviceStatus] = []
        self.runners: list[RunnerStatus] = []
        self.mkv_storage: StorageHistory | None = None
        self.supabase_storage: StorageHistory | None = None
        self.last_refresh = 0.0
        self.scroll_y = 0
        
    def refresh(self):
        """Refresh all data."""
        self.devices = get_device_health(Registry.backend)
        self.runners = get_runner_health()
        self.mkv_storage, self.supabase_storage = get_all_storage(MKV_VOLUME)
        
    def update(self):
        """Update dashboard state."""
        if get_time() - self.last_refresh > REFRESH_INTERVAL:
            self.refresh()
            self.last_refresh = get_time()
        # Scroll
        self.scroll_y -= int(get_mouse_wheel_move() * 30)
        self.scroll_y = max(0, self.scroll_y)
        
    def draw(self):
        """Draw dashboard."""
        clear_background(Color(20, 20, 25, 255))
        y = 20 - self.scroll_y
        
        # Header
        draw_text("EASYSORT STATS", 20, y, 28, WHITE)
        draw_text(f"Last refresh: {self.last_refresh:.0f}s ago", WIDTH - 200, y + 8, 14, GRAY)
        y += 50
        
        # Storage Section
        draw_text("STORAGE", 20, y, 20, Color(150, 150, 150, 255))
        y += 30
        
        if self.mkv_storage and self.supabase_storage:
            # Summary bars
            draw_storage_summary(20, y, 300, self.mkv_storage.name, 
                               self.mkv_storage.current.used_gb, self.mkv_storage.current.total_gb)
            draw_storage_summary(340, y, 300, self.supabase_storage.name,
                               self.supabase_storage.current.used_gb, self.supabase_storage.current.total_gb)
            y += 80
            
            # Charts - 1 week
            draw_line_chart(20, y, 300, 150, self.mkv_storage.week_data(), "MKV - 1 Week", SKYBLUE)
            draw_line_chart(340, y, 300, 150, self.supabase_storage.week_data(), "Supabase - 1 Week", VIOLET)
            
            # Charts - 2 months
            draw_line_chart(660, y, 300, 150, self.mkv_storage.month_data(2), "MKV - 2 Months", SKYBLUE)
            draw_line_chart(980, y, 300, 150, self.supabase_storage.month_data(2), "Supabase - 2 Months", VIOLET)
            y += 170
        
        # Devices Section
        draw_text("DEVICE HEALTH", 20, y, 20, Color(150, 150, 150, 255))
        y += 30
        
        col_w = 300
        for i, dev in enumerate(self.devices):
            col = i % 4
            row = i // 4
            detail = f"age: {dev.age_minutes}min" if dev.age_minutes else (dev.error or "unknown")
            draw_status_card(20 + col * (col_w + 10), y + row * 60, col_w, dev.name, dev.ok, detail)
        
        if self.devices:
            y += ((len(self.devices) - 1) // 4 + 1) * 60 + 20
        
        # Runners Section  
        draw_text("RUNNER HEALTH", 20, y, 20, Color(150, 150, 150, 255))
        y += 30
        
        for i, runner in enumerate(self.runners):
            col = i % 4
            row = i // 4
            detail = f"pending: {runner.jobs_pending} | done: {runner.jobs_completed}"
            draw_status_card(20 + col * (col_w + 10), y + row * 60, col_w, runner.name, runner.ok, detail)
        
        # Footer hint
        draw_text("Scroll to see more | Auto-refresh every 30s", 20, HEIGHT - 25, 12, GRAY)

def main():
    init_window(WIDTH, HEIGHT, "Easysort Stats")
    set_target_fps(60)
    
    dash = Dashboard()
    dash.refresh()
    
    while not window_should_close():
        dash.update()
        begin_drawing()
        dash.draw()
        end_drawing()
    
    close_window()

if __name__ == "__main__":
    main()
