#!/usr/bin/env python3
"""
Mac Power Monitor - A real-time terminal visualizer for power in/out on macOS.
Features threaded data collection for an ultra-smooth htop-like experience.
"""

import subprocess
import re
import time
import sys
import os
import signal
import curses
import threading
from datetime import datetime
from collections import deque


class PowerData:
    """Stores power-related data from various sources"""
    def __init__(self):
        self.power_source = 'Unknown'
        self.battery_percent = 0
        self.charging_status = 'Unknown'
        self.time_remaining = 'Unknown'
        self.cycle_count = 0
        self.condition = 'Checking...'
        self.max_capacity_percent = 100
        self.charger_wattage = 0
        self.charger_connected = False
        self.fully_charged = False
        self.low_power_mode = False
        self.temperature = 0
        self.voltage = 0
        self.amperage = 0
        self.power_watts = 0
        # Charger details
        self.adapter_voltage = 0
        self.adapter_current = 0
        self.adapter_watts = 0
        self.serial = 'Unknown'
        # Battery capacities
        self.design_capacity = 0
        self.current_capacity = 0
        
        # Power Mode: PERFORMANCE (0.5s), BALANCED (2s), ECO (5s)
        self.mode = "BALANCED"
        self.poll_interval = 2.0
        
        # History for graphs
        self.power_history = deque(maxlen=100)
        self.temp_history = deque(maxlen=100)
        
        # Metadata
        self.last_update_time = 0
        self.poll_latency = 0


class DataCollector(threading.Thread):
    """Background thread for non-blocking data collection"""
    def __init__(self, data_obj, lock):
        super().__init__()
        self.data = data_obj
        self.lock = lock
        self.daemon = True
        self.running = True
        self.last_slow_check = 0

    def run_command(self, cmd_args):
        try:
            # Security: Use shell=False and pass arguments as a list
            result = subprocess.run(cmd_args, capture_output=True, text=True, timeout=5, shell=False)
            return result.stdout
        except Exception:
            return ""

    def run(self):
        while self.running:
            start_time = time.time()
            
            # 1. Collect Data - Consolidate to ONE fast shell call if possible
            # ioreg -w0 -rn AppleSmartBattery contains 95% of what we need
            ioreg_out = self.run_command(["ioreg", "-w0", "-rn", "AppleSmartBattery"])
            
            # 2. Parse under lock
            with self.lock:
                # Basic Source & Connection
                ext_conn = '"ExternalConnected" = Yes' in ioreg_out or '"AppleRawExternalConnected" = Yes' in ioreg_out
                self.data.power_source = 'AC Power' if ext_conn else 'Battery'
                self.data.charger_connected = ext_conn
                
                # Percentage
                cur_cap = re.search(r'"CurrentCapacity"\s*=\s*(\d+)', ioreg_out)
                max_cap = re.search(r'"MaxCapacity"\s*=\s*(\d+)', ioreg_out)
                if cur_cap and max_cap:
                    self.data.battery_percent = int(cur_cap.group(1))
                
                # Charging Status
                is_charging = '"IsCharging" = Yes' in ioreg_out
                fully_charged = '"FullyCharged" = Yes' in ioreg_out
                if fully_charged: self.data.charging_status = 'Fully Charged'
                elif is_charging: self.data.charging_status = 'Charging'
                else: self.data.charging_status = 'Discharging' if not ext_conn else 'Connected'

                # Time Remaining
                t_match = re.search(r'"TimeRemaining"\s*=\s*(\d+)', ioreg_out)
                if t_match:
                    mins = int(t_match.group(1))
                    if mins == 65535: self.data.time_remaining = "Calculating..."
                    else: self.data.time_remaining = f"{mins // 60}h {mins % 60}m"
                
                # Temperature (deciKelvin)
                match = re.search(r'"Temperature"\s*=\s*(\d+)', ioreg_out)
                if match: self.data.temperature = round((int(match.group(1)) / 10) - 273.15, 1)
                
                # Voltage & Amperage
                v_match = re.search(r'"Voltage"\s*=\s*(\d+)', ioreg_out)
                if v_match: self.data.voltage = int(v_match.group(1)) / 1000
                
                a_match = re.search(r'"InstantAmperage"\s*=\s*(-?\d+)', ioreg_out)
                if not a_match: a_match = re.search(r'"Amperage"\s*=\s*(-?\d+)', ioreg_out)
                
                if a_match:
                    amp = int(a_match.group(1))
                    if amp > 2**63: amp -= 2**64
                    self.data.amperage = amp
                
                self.data.power_watts = round(self.data.voltage * abs(self.data.amperage) / 1000, 2)
                self.data.power_history.append(self.data.power_watts)
                
                # Health & Cycles
                match = re.search(r'"CycleCount"\s*=\s*(\d+)', ioreg_out)
                if match: self.data.cycle_count = int(match.group(1))
                match = re.search(r'"DesignCapacity"\s*=\s*(\d+)', ioreg_out)
                if match: self.data.design_capacity = int(match.group(1))
                match = re.search(r'"AppleRawMaxCapacity"\s*=\s*(\d+)', ioreg_out)
                if match: 
                    self.data.current_capacity = int(match.group(1))
                    if self.data.design_capacity > 0:
                        self.data.max_capacity_percent = round((self.data.current_capacity / self.data.design_capacity) * 100, 1)

                # Charger Details
                ad_match = re.search(r'"(?:AppleRaw)?AdapterDetails"\s*=\s*\{([^}]+)\}', ioreg_out)
                if ad_match:
                    ad_str = ad_match.group(1)
                    v_match = re.search(r'[ ,]\"?AdapterVoltage\"?[:=](\d+)', " " + ad_str)
                    if v_match: self.data.adapter_voltage = int(v_match.group(1)) / 1000
                    c_match = re.search(r'[ ,]\"?Current\"?[:=](\d+)', " " + ad_str)
                    if c_match: self.data.adapter_current = int(c_match.group(1))
                    w_match = re.search(r'[ ,]\"?Watts\"?[:=](\d+)', " " + ad_str)
                    if w_match: self.data.charger_wattage = int(w_match.group(1))

                # Update metadata
                self.data.poll_latency = round((time.time() - start_time) * 1000, 0)

            # 3. Slow check for Condition & Low Power Mode (every 30s)
            if time.time() - self.last_slow_check > 30:
                prof_out = self.run_command(["system_profiler", "SPPowerDataType"])
                match = re.search(r'Condition:\s*(\w+)', prof_out)
                
                # Check low power mode via pmset
                lpm_out = self.run_command(["pmset", "-g"])
                
                with self.lock:
                    if match: self.data.condition = match.group(1)
                    # Look for lowpowermode line
                    lpm_match = re.search(r'lowpowermode\s+(\d)', lpm_out)
                    self.data.low_power_mode = (lpm_match.group(1) == '1') if lpm_match else False
                self.last_slow_check = time.time()

            time.sleep(self.data.poll_interval)


def draw_battery_bar(win, y, x, percent, width=30):
    filled = int((percent / 100) * width)
    empty = width - filled
    color = curses.color_pair(2) if percent >= 60 else (curses.color_pair(3) if percent >= 30 else curses.color_pair(1))
    win.addstr(y, x, "[")
    win.addstr("█" * filled, color | curses.A_BOLD)
    win.addstr("░" * empty, curses.color_pair(8))
    win.addstr(f"] {percent}%")


def draw_power_flow(win, y, x, is_charging, frame):
    if is_charging:
        p = ['⚡ ━━▶━━ ', '━⚡━━▶━━', '━━⚡━▶━━', '━━━⚡▶━━', '━━━━⚡━━']
        color = curses.color_pair(2)
    else:
        p = ['━━◀━━ ⚡', '━━◀━━⚡━', '━━◀━⚡━━', '━━◀⚡━━━', '━━⚡━━━━']
        color = curses.color_pair(3)
    win.addstr(y, x, p[frame % 5], color | curses.A_BOLD)


def draw_box(win, y, x, height, width, title=""):
    win.addstr(y, x, "╭" + "─" * (width - 2) + "╮", curses.color_pair(6))
    for i in range(1, height - 1):
        win.addstr(y + i, x, "│", curses.color_pair(6))
        win.addstr(y + i, x + width - 1, "│", curses.color_pair(6))
    win.addstr(y + height - 1, x, "╰" + "─" * (width - 2) + "╯", curses.color_pair(6))
    if title:
        t = f" {title} "
        win.addstr(y, x + (width - len(t)) // 2, t, curses.color_pair(5) | curses.A_BOLD)


def main_loop(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    
    # Colors
    curses.init_pair(1, curses.COLOR_RED, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)
    curses.init_pair(4, curses.COLOR_CYAN, -1)
    curses.init_pair(5, curses.COLOR_WHITE, -1)
    curses.init_pair(6, curses.COLOR_BLUE, -1)
    curses.init_pair(8, 240, -1) # Dark gray
    
    stdscr.nodelay(True)
    stdscr.timeout(200) # Fast UI refresh (5Hz)
    
    data = PowerData()
    lock = threading.Lock()
    collector = DataCollector(data, lock)
    collector.start()
    
    frame = 0
    
    while True:
        key = stdscr.getch()
        if key == ord('q') or key == ord('Q'):
            collector.running = False
            break
        elif key == ord('e') or key == ord('E'):
            with lock:
                data.mode = "ECO"
                data.poll_interval = 5.0
        elif key == ord('b') or key == ord('B'):
            with lock:
                data.mode = "BALANCED"
                data.poll_interval = 2.0
        elif key == ord('p') or key == ord('P'):
            with lock:
                data.mode = "PERFORMANCE"
                data.poll_interval = 0.5
            
        max_y, max_x = stdscr.getmaxyx()
        if max_x < 70 or max_y < 25:
            stdscr.clear()
            stdscr.addstr(0, 0, "Terminal too small (min 70x25)", curses.color_pair(1))
            stdscr.refresh()
            continue

        with lock:
            stdscr.clear()
            
            # Header
            stdscr.addstr(0, (max_x - 35) // 2, "⚡ MAC VOLT MONITOR ⚡", curses.color_pair(4) | curses.A_BOLD)
            mode_color = curses.color_pair(2) if data.mode == "ECO" else (curses.color_pair(3) if data.mode == "BALANCED" else curses.color_pair(1))
            stdscr.addstr(1, (max_x - 20) // 2, f"Mode: {data.mode}", mode_color | curses.A_BOLD)
            
            # --- POWER SOURCE ---
            draw_box(stdscr, 2, 2, 6, 66, "⚡ POWER SOURCE")
            source_icon = "🔌" if data.power_source == 'AC Power' else "🔋"
            source_color = curses.color_pair(2) if data.power_source == 'AC Power' else curses.color_pair(3)
            stdscr.addstr(3, 4, "Source:", curses.color_pair(5))
            stdscr.addstr(3, 20, f"{source_icon} {data.power_source}", source_color | curses.A_BOLD)
            stdscr.addstr(4, 4, "Status:", curses.color_pair(5))
            stdscr.addstr(4, 20, data.charging_status, curses.color_pair(5))
            stdscr.addstr(5, 4, "Flow:", curses.color_pair(5))
            is_active_charge = data.charging_status == 'Charging' or data.amperage > 50
            draw_power_flow(stdscr, 5, 20, is_active_charge, frame)
            
            # --- BATTERY ---
            draw_box(stdscr, 9, 2, 7, 66, "🔋 BATTERY STATUS")
            draw_battery_bar(stdscr, 10, 4, data.battery_percent, 35)
            health_color = curses.color_pair(2) if data.max_capacity_percent >= 80 else curses.color_pair(3)
            stdscr.addstr(11, 4, "Health:", curses.color_pair(5))
            stdscr.addstr(11, 20, f"{data.max_capacity_percent}% of design", health_color)
            stdscr.addstr(12, 4, "Condition:", curses.color_pair(5))
            stdscr.addstr(12, 20, data.condition, curses.color_pair(2) if 'Normal' in data.condition else curses.color_pair(3))
            stdscr.addstr(13, 4, "Cycles:", curses.color_pair(5))
            stdscr.addstr(13, 20, f"{data.cycle_count} cycles", curses.color_pair(5))
            stdscr.addstr(14, 4, "Time Left:", curses.color_pair(5))
            stdscr.addstr(14, 20, data.time_remaining, curses.color_pair(4) | curses.A_BOLD)

            # --- METRICS & CHARGER ---
            draw_box(stdscr, 17, 2, 6, 32, "📊 METRICS")
            p_color = curses.color_pair(2) if data.amperage >= 0 else curses.color_pair(3)
            stdscr.addstr(18, 4, "Power:", curses.color_pair(5))
            stdscr.addstr(18, 14, f"{'↓' if data.amperage >=0 else '↑'} {data.power_watts}W", p_color | curses.A_BOLD)
            stdscr.addstr(19, 4, "Current:", curses.color_pair(5))
            stdscr.addstr(19, 14, f"{abs(data.amperage)}mA", curses.color_pair(5))
            stdscr.addstr(20, 4, "Voltage:", curses.color_pair(5))
            stdscr.addstr(20, 14, f"{data.voltage:.2f}V", curses.color_pair(5))
            t_color = curses.color_pair(2) if data.temperature < 40 else curses.color_pair(1)
            stdscr.addstr(21, 4, "Temp:", curses.color_pair(5))
            stdscr.addstr(21, 14, f"{data.temperature}°C", t_color)

            if data.charger_connected:
                draw_box(stdscr, 17, 36, 6, 32, "🔌 CHARGER")
                stdscr.addstr(18, 38, "Wattage:", curses.color_pair(5))
                stdscr.addstr(18, 50, f"{data.charger_wattage}W", curses.color_pair(2) | curses.A_BOLD)
                stdscr.addstr(19, 38, "Adapter V:", curses.color_pair(5))
                stdscr.addstr(19, 50, f"{data.adapter_voltage:.1f}V", curses.color_pair(5))
                stdscr.addstr(20, 38, "Adapter I:", curses.color_pair(5))
                stdscr.addstr(20, 50, f"{data.adapter_current}mA", curses.color_pair(5))
                stdscr.addstr(21, 38, "Low Power:", curses.color_pair(5))
                stdscr.addstr(21, 50, "ON" if data.low_power_mode else "OFF", curses.color_pair(3) if data.low_power_mode else curses.color_pair(8))

            # --- GRAPH ---
            if max_y > 28:
                draw_box(stdscr, 24, 2, 4, 66, "📈 POWER HISTORY")
                history = list(data.power_history)
                if history:
                    m_v = max(history) if max(history) > 0 else 1
                    chars = [' ', '▂', '▃', '▄', '▅', '▆', '▇', '█']
                    g_w = min(60, len(history))
                    for i in range(g_w):
                        v = history[-(g_w-i)]
                        c_idx = int((v/m_v) * 7)
                        stdscr.addstr(26, 4 + i, chars[c_idx], curses.color_pair(4))

            # Footer
            footer = f" [P]erf | [B]alanced | [E]co | 'q' to quit  "
            stdscr.addstr(max_y-2, (max_x - len(footer)) // 2, footer, curses.color_pair(5))
            
            meta = f" Poll: {data.poll_latency}ms | Interval: {data.poll_interval}s "
            stdscr.addstr(max_y-1, (max_x - len(meta)) // 2, meta, curses.color_pair(8))

        stdscr.refresh()
        frame += 1
        time.sleep(0.05) # Cap UI refresh to ~20FPS


def main():
    if '--once' in sys.argv:
        # Mini non-curses version for simple check
        import subprocess
        print("Rapid Power Check:")
        out = subprocess.run("pmset -g batt; ioreg -rn AppleSmartBattery | grep -E 'Amperage|Voltage|Wattage|Temperature'", shell=True, capture_output=True, text=True).stdout
        print(out)
        return

    try:
        curses.wrapper(main_loop)
    except KeyboardInterrupt:
        pass
    print("\n\033[96m👋 Power monitoring stopped.\033[0m\n")


if __name__ == "__main__":
    main()
