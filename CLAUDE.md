# Furnace Monitor

Raspberry Pi Zero 2W that detects furnace burn sessions via a current clamp and logs them to a CSV. Exposes a local web dashboard and a JSON API consumed by a separate oil tank Pi.

## Hardware

- Current clamp: SCT-013-000 connected via 3.5mm jack to a breadboard circuit
- ADC: MCP3008, reading CH0 via SPI
- Raw signal: ~519–524 when furnace OFF, oscillates ~511–530 when ON
- Detection uses **trimmed range variance** of a rolling sample window (top/bottom 5% of samples dropped before computing range), not a simple threshold

## Project Structure

```
monitor.py     # Sensor polling + burn session logger (systemd service)
web.py         # Flask dashboard + JSON API (systemd service)
burns.csv      # Auto-created; one row per completed burn session
config.json    # All tunable parameters — edit here, no code changes needed
venv/          # Python virtualenv (flask, spidev)
```

## Services

Both run as systemd services under the `skipsuva` user:

```bash
sudo systemctl status furnace-monitor
sudo systemctl status furnace-web

sudo systemctl restart furnace-monitor   # after config.json changes
journalctl -u furnace-monitor -f         # live logs
```

## config.json Fields

| Field | Current value | Purpose |
|---|---|---|
| `spi_channel` | 0 | MCP3008 chip select |
| `spi_speed_hz` | 1350000 | SPI clock speed |
| `sample_rate_hz` | 20 | Samples per second |
| `variance_threshold` | 12 | Min trimmed range to count as ON |
| `on_confirmation_seconds` | 15 | Signal must look ON this long before state flips |
| `off_confirmation_seconds` | 20 | Signal must look OFF this long before state flips |
| `min_burn_seconds` | 60 | Sessions shorter than this are discarded (not written to CSV) |
| `port` | 8080 | Flask port |

To tune false triggers: increase `variance_threshold` or `min_burn_seconds`. To reduce split sessions (one real burn logged as multiple): increase `off_confirmation_seconds`. Restart the service after any change — no code edits needed.

## monitor.py

State machine: IDLE → RUNNING → IDLE

- Reads MCP3008 via `spidev`
- Rolling window = `sample_rate_hz × on_confirmation_seconds` samples
- Variance = trimmed range: `sorted_window[-5%] - sorted_window[5%]` (robust to single-sample noise spikes)
- ON confirmed after variance exceeds threshold for `on_confirmation_seconds`
- OFF confirmed after variance drops below threshold for `off_confirmation_seconds`
- Sessions shorter than `min_burn_seconds` are discarded (logged to console, not CSV)
- Completed sessions appended to `burns.csv`
- session_id auto-increments from last row in CSV

## web.py

Flask app on port 8080. Read-only — it never writes to burns.csv.

Routes:
- `GET /` — dashboard (dark theme, Chart.js, orange accent `#fb923c`)
- `GET /api/burns?days=N` — JSON session list, default 30 days, max 365, CORS enabled
- `GET /api/status` — health check with last burn timestamp

## burns.csv Format

```
session_id,start_time,end_time,duration_seconds
1,2026-05-06 21:54:44,2026-05-06 21:55:59,74
```

## Tailscale

This Pi is on Tailscale at `100.106.202.5`. The oil tank Pi fetches from `http://100.106.202.5:8080/api/burns` to power its Furnace tab.

## Quick Reference

```bash
# Live logs
journalctl -u furnace-monitor -f

# Recent burns
tail -20 ~/furnace-burns/burns.csv

# Test API
curl http://localhost:8080/api/burns?days=7
curl http://localhost:8080/api/status

# Restart after config change
sudo systemctl restart furnace-monitor
```
