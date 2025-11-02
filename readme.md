# netusage – macOS Network Usage Monitor

A lightweight command-line tool for tracking and reporting WiFi data usage on macOS. Records network traffic statistics over time and provides detailed reports with multiple time filtering options.

## Features

- 🔍 **Automatic Interface Detection**: Automatically detects the default network interface (usually `en0` for WiFi)
- 📊 **Real-time Sampling**: Continuously records RX/TX byte counts at configurable intervals
- 📈 **Flexible Reporting**:
  - Daily usage summaries (with optional hourly breakdown)
  - Custom time ranges (ISO8601 format)
  - Relative time periods (e.g., last 1 hour, 24 hours, 7 days)
  - Usage from a specific date/time until now (`--since`)
- 💾 **SQLite Backend**: Stores samples persistently in a database
- 🛡️ **Wraparound Protection**: Handles counter resets and wraparounds gracefully
- 🌍 **Timezone Support**: Specify custom timezones for day boundary calculations

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd net_usage
```

2. Ensure Python 3.8+ is installed:
```bash
python3 --version
```

3. No external dependencies required! The tool uses only Python standard library modules.

## Usage

### Basic Commands

#### Take a Single Sample
```bash
python3 netusage.py sample
```
Records a one-time snapshot of the current RX/TX bytes.

#### Watch Mode (Continuous Sampling)
```bash
python3 netusage.py watch --interval 60
```
Continuously records samples at 60-second intervals. Press `Ctrl+C` to stop.

### Reporting

#### Daily Report
```bash
python3 netusage.py report --day 2025-11-02 --update
```
Shows total upload/download for a specific day. The `--update` flag takes a fresh sample before reporting.

#### Daily Report with Hourly Breakdown
```bash
python3 netusage.py report --day 2025-11-02 --hourly --update
```
Displays hourly usage distribution for the entire day.

#### Custom Time Range
```bash
python3 netusage.py report --from "2025-11-01T12:00:00" --to "2025-11-03T23:00:00" --update
```
Reports usage for any ISO8601 date/time range.

#### Relative Time Periods
```bash
# Last 1 hour
python3 netusage.py report --last 1h --update

# Last 24 hours
python3 netusage.py report --last 24h --update

# Last 30 minutes
python3 netusage.py report --last 30m --update

# Last 7 days
python3 netusage.py report --last 7d --update

# Last 2 weeks
python3 netusage.py report --last 2w --update
```

#### Usage Since a Specific Date/Time
```bash
# From a specific date until now (starts at midnight)
python3 netusage.py report --since "2025-11-01" --update

# From a specific date and time until now
python3 netusage.py report --since "2025-11-02T18:30:00" --update
```

### Advanced Options

#### Specify Custom Interface
```bash
python3 netusage.py report --day 2025-11-02 --iface en0
```

#### Custom Database Location
```bash
python3 netusage.py report --day 2025-11-02 --db /custom/path/netusage.db
```

#### Timezone Support
```bash
python3 netusage.py report --day 2025-11-02 --tz Europe/Istanbul
```

### Important Notes

- The `--update` flag automatically takes a fresh sample before generating the report
- The tool cannot work with a single sample; it needs at least two samples to calculate usage (by computing deltas)
- You must run `sample` or `watch` first to populate the database with data
- macOS counters may reset after reboot, but this tool calculates usage from consecutive samples, so it's resilient to counter resets

## Database Location

By default, samples are stored in:
```
~/.netusage.db
```

This is a SQLite database. You can inspect it with:
```bash
sqlite3 ~/.netusage.db "SELECT * FROM samples LIMIT 10;"
```

## Getting Started

Here's a typical workflow:

1. **Start sampling** (leave running):
```bash
python3 netusage.py watch --interval 60
```

2. **In another terminal, check usage** (while watch is running):
```bash
python3 netusage.py report --last 1h --update
```

3. **Get daily summary**:
```bash
python3 netusage.py report --day 2025-11-03 --update
```

4. **Get usage from specific point in time**:
```bash
python3 netusage.py report --since "2025-11-01T14:30:00" --update
```

## Command Reference

```
usage: netusage.py [-h] [--db DB] [--iface IFACE] {sample,watch,report} ...

positional arguments:
  {sample,watch,report}
    sample              Take a single network sample
    watch               Continuously sample at intervals
    report              Generate usage reports

optional arguments:
  --db DB               SQLite database path (default: ~/.netusage.db)
  --iface IFACE         Network interface to monitor (default: auto-detect)

Report Options:
  --day DAY             Daily report (YYYY-MM-DD format)
  --hourly              Show hourly breakdown for daily report
  --from FROM           Start time (ISO8601, e.g., 2025-11-02T00:00:00)
  --to TO               End time (ISO8601)
  --last LAST           Last X duration (e.g., 30m, 1h, 24h, 7d, 2w)
  --since SINCE         From a date/time until now (YYYY-MM-DD or ISO8601)
  --tz TZ               Timezone for day boundaries (e.g., Europe/Istanbul)
  --update              Take a fresh sample before reporting
```

## Troubleshooting

### No data appears in reports
- Ensure you've run `sample` or `watch` to populate the database
- Wait a few minutes after starting `watch` to have enough samples for calculations

### Incorrect interface detected
- Manually specify the interface: `--iface en1`
- Check available interfaces: `networksetup -listallhardwareports`

### Reports show 0 bytes
- The tool needs at least 2 samples in the time range to calculate usage
- Try extending the time range or ensuring sufficient data exists

## Development

This tool is written in pure Python with no external dependencies. Feel free to modify and extend it!

## License

MIT License - Feel free to use, modify, and distribute.

## Author

Created for macOS network monitoring.
