"""
monitor.py — Furnace burn session monitor.

Polls MCP3008 CH0 via SPI, detects furnace ON/OFF state using
AC signal variance, and logs completed burn sessions to burns.csv.

Run with: venv/bin/python monitor.py
"""

import csv
import json
import os
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import spidev

CONFIG_PATH = Path(__file__).parent / "config.json"
CSV_PATH = Path(__file__).parent / "burns.csv"
CSV_HEADER = ["session_id", "start_time", "end_time", "duration_seconds"]


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def read_mcp3008(spi, channel):
    # MCP3008 SPI read — single-ended, 10-bit result
    r = spi.xfer2([1, (8 + channel) << 4, 0])
    return ((r[1] & 3) << 8) | r[2]


def ensure_csv():
    if not CSV_PATH.exists():
        with open(CSV_PATH, "w", newline="") as f:
            csv.writer(f).writerow(CSV_HEADER)


def next_session_id():
    ensure_csv()
    last_id = 0
    with open(CSV_PATH, newline="") as f:
        for row in csv.DictReader(f):
            try:
                last_id = int(row["session_id"])
            except (ValueError, KeyError):
                pass
    return last_id + 1


def append_session(session_id, start_time, end_time):
    duration = int((end_time - start_time).total_seconds())
    with open(CSV_PATH, "a", newline="") as f:
        csv.writer(f).writerow([
            session_id,
            start_time.strftime("%Y-%m-%d %H:%M:%S"),
            end_time.strftime("%Y-%m-%d %H:%M:%S"),
            duration,
        ])
    return duration


def fmt_duration(seconds):
    m, s = divmod(seconds, 60)
    return f"{m}m {s}s"


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main():
    cfg = load_config()
    sample_interval = 1.0 / cfg["sample_rate_hz"]
    window_size = cfg["sample_rate_hz"] * cfg["on_confirmation_seconds"]
    variance_threshold = cfg["variance_threshold"]
    on_secs = cfg["on_confirmation_seconds"]
    off_secs = cfg["off_confirmation_seconds"]

    spi = spidev.SpiDev()
    spi.open(0, cfg["spi_channel"])
    spi.max_speed_hz = cfg["spi_speed_hz"]

    ensure_csv()

    window = deque(maxlen=window_size)

    # State machine
    state = "IDLE"          # IDLE or RUNNING
    session_start = None
    session_id = None

    # Confirmation timers — track how long the candidate state has held
    candidate_on_since = None   # time variance first went above threshold
    candidate_off_since = None  # time variance first went below threshold

    print(f"[{now_str()}] Furnace monitor started (threshold={variance_threshold}, "
          f"on_confirm={on_secs}s, off_confirm={off_secs}s)")

    try:
        while True:
            raw = read_mcp3008(spi, 0)
            window.append(raw)

            variance = max(window) - min(window) if len(window) >= 2 else 0
            is_active = variance > variance_threshold

            now = datetime.now()

            if state == "IDLE":
                if is_active:
                    if candidate_on_since is None:
                        candidate_on_since = now
                    elif (now - candidate_on_since).total_seconds() >= on_secs:
                        # Confirmed ON
                        state = "RUNNING"
                        session_start = candidate_on_since
                        session_id = next_session_id()
                        candidate_on_since = None
                        print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Furnace ON")
                else:
                    candidate_on_since = None

            elif state == "RUNNING":
                if not is_active:
                    if candidate_off_since is None:
                        candidate_off_since = now
                    elif (now - candidate_off_since).total_seconds() >= off_secs:
                        # Confirmed OFF
                        end_time = candidate_off_since
                        duration = append_session(session_id, session_start, end_time)
                        state = "IDLE"
                        candidate_off_since = None
                        print(f"[{end_time.strftime('%Y-%m-%d %H:%M:%S')}] "
                              f"Furnace OFF — session {session_id}, "
                              f"duration {fmt_duration(duration)}")
                        session_start = None
                        session_id = None
                else:
                    candidate_off_since = None

            time.sleep(sample_interval)

    except KeyboardInterrupt:
        print(f"\n[{now_str()}] Monitor stopped.")
    finally:
        spi.close()


if __name__ == "__main__":
    main()
