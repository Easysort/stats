"""Easysort Stats Dashboard - raylib-based monitoring UI."""
from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from pyray import *
from health import (
    get_device_health,
    get_ip_device_health,
    get_runner_health,
    get_tracking_health,
    DeviceStatus,
    IPDeviceStatus,
    RunnerStatus,
)
from storage import get_all_storage, StorageHistory
from charts import draw_line_chart, draw_status_card, draw_device_card, draw_storage_summary
from easysort.registry import RegistryBase
from easysort.helpers import REGISTRY_LOCAL_IP

Registry = RegistryBase(base=REGISTRY_LOCAL_IP)
DEVICES_TXT = Path(__file__).parent / "devices.txt"
MKV_VOLUME = os.getenv("MKV_VOLUME", "/media/easysort/lenovo")
REFRESH_INTERVAL, HEAVY_INTERVAL, PAD = 180, 1800, 24  # 3min light, 30 min heavy

class Dashboard:
    def __init__(self):
        self.devices: list[DeviceStatus] = []
        self.ip_devices: list[IPDeviceStatus] = []
        self.runners: list[RunnerStatus] = []
        self.tracking: list[RunnerStatus] = []
        self.mkv_storage: StorageHistory | None = None
        self.supabase_storage: StorageHistory | None = None
        self.last_refresh = self.last_heavy = self.scroll_y = 0

    def refresh(self, heavy: bool = False):
        if heavy:
            try: Registry.SYNC()
            except Exception as e: print(f"Sync error: {e}")
            self.last_heavy = get_time()
        self.devices = get_device_health(Registry.backend)
        self.ip_devices = get_ip_device_health(DEVICES_TXT)
        self.runners = get_runner_health(Registry.backend)
        self.tracking = get_tracking_health(heavy)
        self.mkv_storage, self.supabase_storage = get_all_storage(MKV_VOLUME, save=heavy)
        
    def update(self):
        t = get_time()
        if t - self.last_heavy > HEAVY_INTERVAL:
            self.refresh(heavy=True)
            self.last_refresh = t
        elif t - self.last_refresh > REFRESH_INTERVAL:
            self.refresh()
            self.last_refresh = t
        self.scroll_y = max(0, self.scroll_y - int(get_mouse_wheel_move() * 40))
        
    def draw(self):
        w, h = get_screen_width(), get_screen_height()
        clear_background(Color(18, 18, 22, 255))
        y = PAD - self.scroll_y
        
        # Header
        draw_text("EASYSORT", PAD, y, 32, WHITE)
        next_soft = max(0, int(REFRESH_INTERVAL - (get_time() - self.last_refresh)))
        next_heavy = max(0, int(HEAVY_INTERVAL - (get_time() - self.last_heavy)))
        draw_text(f"refresh {next_soft}s | sync {next_heavy // 60}m{next_heavy % 60:02d}s", w - PAD - 220, y + 10, 14, Color(80, 80, 90, 255))
        y += 56
        
        # Storage
        if self.mkv_storage and self.supabase_storage:
            cw = (w - PAD * 3) // 2
            draw_storage_summary(PAD, y, cw, "Local", self.mkv_storage.current.used_gb, self.mkv_storage.current.total_gb)
            draw_storage_summary(PAD * 2 + cw, y, cw, "Cloud", self.supabase_storage.current.used_gb, self.supabase_storage.current.total_gb)
            y += 72
            
            ch = 140
            qw = (w - PAD * 5) // 4
            draw_line_chart(PAD, y, qw, ch, self.mkv_storage.week_data(), "Local 7d", Color(100, 180, 255, 255), 7)
            draw_line_chart(PAD * 2 + qw, y, qw, ch, self.supabase_storage.week_data(), "Cloud 7d", Color(180, 130, 255, 255), 7)
            draw_line_chart(PAD * 3 + qw * 2, y, qw, ch, self.mkv_storage.month_data(2), "Local 60d", Color(100, 180, 255, 255), 60)
            draw_line_chart(PAD * 4 + qw * 3, y, qw, ch, self.supabase_storage.month_data(2), "Cloud 60d", Color(180, 130, 255, 255), 60)
            y += ch + PAD
        
        # Devices
        draw_text("DEVICES", PAD, y, 16, Color(90, 90, 100, 255))
        y += 28
        cols = max(1, (w - PAD) // 280)
        card_w = (w - PAD * (cols + 1)) // cols
        device_card_h = 76
        for i, dev in enumerate(self.devices):
            detail = f"{dev.age_minutes}m ago" if dev.age_minutes is not None else (dev.error or "—")
            draw_device_card(PAD + (i % cols) * (card_w + PAD), y + (i // cols) * device_card_h, card_w, dev.name, dev.ok, detail, dev.last_path)
        if self.devices:
            y += ((len(self.devices) - 1) // cols + 1) * device_card_h + PAD

        # IP devices (from devices.txt, /health on each)
        if self.ip_devices:
            draw_text("IP DEVICES", PAD, y, 16, Color(90, 90, 100, 255))
            y += 28
            for i, dev in enumerate(self.ip_devices):
                draw_device_card(
                    PAD + (i % cols) * (card_w + PAD), y + (i // cols) * device_card_h, card_w,
                    dev.name, dev.ok, dev.detail, None, over_temp=dev.over_temp
                )
            y += ((len(self.ip_devices) - 1) // cols + 1) * device_card_h + PAD

        # Runners
        draw_text("RUNNERS", PAD, y, 16, Color(90, 90, 100, 255))
        y += 28
        runner_card_h = 76
        for i, r in enumerate(self.runners):
            draw_status_card(PAD + (i % cols) * (card_w + PAD), y + (i // cols) * runner_card_h, card_w, r.name, r.ok, r.detail, r.warn, r.path)
        if self.runners: y += ((len(self.runners) - 1) // cols + 1) * runner_card_h + PAD
        
        # Tracking Service
        draw_text("TRACKING SERVICE", PAD, y, 16, Color(90, 90, 100, 255))
        y += 28
        for i, t in enumerate(self.tracking):
            draw_status_card(PAD + (i % cols) * (card_w + PAD), y + (i // cols) * runner_card_h, card_w, t.name, t.ok, t.detail, t.warn, t.path)

def main():
    set_config_flags(2 | 64)  # FLAG_FULLSCREEN_MODE | FLAG_VSYNC_HINT
    init_window(0, 0, "Easysort Stats")
    
    dash = Dashboard()
    dash.refresh(heavy=True)
    
    while not window_should_close():
        dash.update()
        begin_drawing()
        dash.draw()
        end_drawing()
    
    close_window()

if __name__ == "__main__":
    main()
