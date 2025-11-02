
#!/usr/bin/env python3
"""
netusage.py — Terminal tabanlı macOS ağ (Wi‑Fi) veri kullanımı kaydedici ve raporlama aracı.

Yeni özellikler
- report --last 1h / 24h / 30m / 7d gibi sürelerle hızlı rapor
- report --since YYYY-MM-DD veya YYYY-MM-DDTHH:MM:SS formatında belirli tarihten bugüne rapor
- report --update: raporlamadan hemen önce otomatik sample al

Özellikler
- Arayüz tespiti: Varsayılan çıkış (default route) arayüzünü otomatik bulur (genelde Wi‑Fi: en0).
- Örnekleme (sampling): Şu anki toplam RX/TX bayt değerlerini SQLite veritabanına yazar.
- İzleme (watch): Belirlenen aralıkla (varsayılan 60s) sürekli örnek alır.
- Raporlar:
  * Günlük toplam (YYYY-MM-DD)
  * Saatlik dağılım (YYYY-MM-DD için)
  * Özel zaman aralığı (ISO8601 başlangıç/bitiş)
  * Belirli tarihten bugüne (--since YYYY-MM-DD veya ISO8601 tarih-saat)
  * Son X süre (örn. --last 1h, 24h)

Kullanım
  python3 netusage.py watch --interval 60
  python3 netusage.py sample
  python3 netusage.py report --day 2025-11-02
  python3 netusage.py report --day 2025-11-02 --hourly
  python3 netusage.py report --from "2025-11-01T00:00:00" --to "2025-11-02T00:00:00"
  python3 netusage.py report --since "2025-11-01" --update
  python3 netusage.py report --since "2025-11-02T18:30:00" --update
  python3 netusage.py report --last 24h --update

Notlar
- macOS'ta toplam RX/TX sayaçları yeniden başlatmada sıfırlanabilir. Bu araç zaman içinde örnek alıp ardışık örnekler arasındaki farklardan kullanım hesaplar.
- Sayaç taşması (wrap) ihtimaline karşı basit koruma vardır (negatif delta sıfırlanır).
"""

import argparse
import datetime as dt
import os
import signal
import sqlite3
import subprocess
import sys
import time
from typing import Optional, Tuple

DB_PATH_DEFAULT = os.path.expanduser("~/.netusage.db")

def run(cmd: list[str]) -> str:
    out = subprocess.check_output(cmd, text=True)
    return out.strip()

def detect_default_iface() -> Optional[str]:
    try:
        out = run(["route", "get", "default"])
        for line in out.splitlines():
            if "interface:" in line:
                return line.split()[-1].strip()
    except Exception:
        pass
    try:
        out = run(["networksetup", "-listallhardwareports"])
        lines = out.splitlines()
        for i, line in enumerate(lines):
            if "Hardware Port: Wi-Fi" in line or "Hardware Port: Wi‑Fi" in line:
                for j in range(i+1, min(i+5, len(lines))):
                    if lines[j].strip().startswith("Device:"):
                        return lines[j].split(":")[1].strip()
    except Exception:
        pass
    return "en0"

def read_iface_bytes(iface: str) -> Tuple[int, int]:
    out = run(["netstat", "-ib", "-I", iface])
    lines = [l for l in out.splitlines() if l.strip()]
    header = None
    for i, l in enumerate(lines):
        if l.lower().startswith("name"):
            header = lines[i]
            data_lines = lines[i+1:]
            break
    if header is None:
        rx_total = tx_total = 0
        for l in lines[1:]:
            parts = l.split()
            try:
                rx = int(parts[-4])
                tx = int(parts[-3])
                rx_total += rx
                tx_total += tx
            except Exception:
                continue
        return rx_total, tx_total
    cols = header.split()
    def find_idx(name: str) -> Optional[int]:
        for idx, c in enumerate(cols):
            if c.lower() == name:
                return idx
        return None
    try:
        i_idx = find_idx("ibytes") or cols.index("Ibytes")
        o_idx = find_idx("obytes") or cols.index("Obytes")
    except Exception:
        i_idx = -4
        o_idx = -3
    rx_total = 0
    tx_total = 0
    for l in data_lines:
        parts = l.split()
        if len(parts) <= max(i_idx, o_idx):
            continue
        if parts[0] != iface:
            continue
        try:
            rx_total += int(parts[i_idx])
            tx_total += int(parts[o_idx])
        except Exception:
            pass
    return rx_total, tx_total

def ensure_db(db_path: str = DB_PATH_DEFAULT):
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS samples (
            ts INTEGER NOT NULL,
            iface TEXT NOT NULL,
            rx_bytes INTEGER NOT NULL,
            tx_bytes INTEGER NOT NULL
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_samples_ts_iface ON samples(ts, iface);")
    con.commit()
    con.close()

def insert_sample(iface: str, db_path: str = DB_PATH_DEFAULT):
    ensure_db(db_path)
    rx, tx = read_iface_bytes(iface)
    ts = int(time.time())
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("INSERT INTO samples (ts, iface, rx_bytes, tx_bytes) VALUES (?, ?, ?, ?)", (ts, iface, rx, tx))
    con.commit()
    con.close()
    return ts, rx, tx

def compute_usage_between(start_ts: int, end_ts: int, iface: str, db_path: str = DB_PATH_DEFAULT):
    ensure_db(db_path)
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("""
        SELECT ts, rx_bytes, tx_bytes FROM samples
        WHERE iface = ? AND ts BETWEEN ? AND ?
        ORDER BY ts ASC
    """, (iface, start_ts, end_ts))
    rows = cur.fetchall()
    con.close()
    if not rows or len(rows) < 2:
        return 0, 0
    total_rx = 0
    total_tx = 0
    prev_rx = rows[0][1]
    prev_tx = rows[0][2]
    for _, rx, tx in rows[1:]:
        dr = rx - prev_rx
        dt = tx - prev_tx
        if dr < 0: dr = 0
        if dt < 0: dt = 0
        total_rx += dr
        total_tx += dt
        prev_rx = rx
        prev_tx = tx
    return total_rx, total_tx

def humanize_bytes(n: int) -> str:
    for unit in ["B","KB","MB","GB","TB"]:
        if n < 1024.0:
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PB"

def day_bounds(date_str: str, tz: Optional[str] = None):
    tzinfo = None
    if tz:
        try:
            import zoneinfo
            tzinfo = zoneinfo.ZoneInfo(tz)
        except Exception:
            pass
    if tzinfo is None:
        tzinfo = dt.datetime.now().astimezone().tzinfo
    d = dt.datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tzinfo)
    start = int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    end = int((d + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    return start, end

def hourly_buckets_for_day(date_str: str, iface: str, db_path: str = DB_PATH_DEFAULT, tz: Optional[str] = None):
    start, end = day_bounds(date_str, tz)
    buckets = []
    for h in range(24):
        s = start + h*3600
        e = min(s + 3600, end)
        rx, tx = compute_usage_between(s, e, iface, db_path)
        buckets.append((h, rx, tx))
    return buckets

def parse_iso(s: str) -> int:
    try:
        dtobj = dt.datetime.fromisoformat(s)
    except Exception:
        raise SystemExit("Tarih/saat ISO8601 formatında olmalı, ör: 2025-11-02T09:00:00")
    if dtobj.tzinfo is None:
        dtobj = dtobj.astimezone()
    return int(dtobj.timestamp())

def parse_duration(s: str) -> int:
    s = s.strip().lower()
    if not s:
        raise SystemExit("--last için süre gerekli (örn. 1h, 24h, 30m, 7d)")
    try:
        num = int(''.join(ch for ch in s if ch.isdigit()))
    except ValueError:
        raise SystemExit("Süre numarası bulunamadı (örn. 30m, 1h)")
    unit = ''.join(ch for ch in s if ch.isalpha())
    if unit not in ("s","m","h","d","w"):
        raise SystemExit("Desteklenen birimler: s, m, h, d, w (örn. 45m, 2h, 1d)")
    mult = {"s":1, "m":60, "h":3600, "d":86400, "w":604800}[unit]
    return num * mult

def cmd_sample(args):
    iface = args.iface or detect_default_iface()
    ts, rx, tx = insert_sample(iface, args.db)
    print(f"[sample] {iface} @ {dt.datetime.fromtimestamp(ts).isoformat()} rx={rx} tx={tx}")

def cmd_watch(args):
    iface = args.iface or detect_default_iface()
    interval = args.interval
    print(f"[watch] iface={iface} interval={interval}s veritabanı={args.db}")
    def handler(signum, frame):
        print("\n[watch] Çıkılıyor...")
        sys.exit(0)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    ensure_db(args.db)
    while True:
        try:
            ts, rx, tx = insert_sample(iface, args.db)
            print(f"[sample] {iface} @ {dt.datetime.fromtimestamp(ts).isoformat()} rx={rx} tx={tx}")
        except Exception as e:
            print(f"[hata] {e}", file=sys.stderr)
        time.sleep(interval)

def print_usage_result(title: str, rx: int, tx: int):
    print(f"[rapor] {title}")
    print(f"  İndirilen: {humanize_bytes(rx)}")
    print(f"  Yüklenen: {humanize_bytes(tx)}")

def cmd_report(args):
    iface = args.iface or detect_default_iface()
    if args.update:
        insert_sample(iface, args.db)
    picks = sum(bool(x) for x in [args.day, args.range_from and args.range_to, args.last, args.since])
    if picks != 1:
        raise SystemExit("Lütfen şunlardan yalnızca birini kullanın: --day YA DA (--from & --to) YA DA --last YA DA --since")
    if args.since:
        end_ts = int(time.time())
        # --since parametresi gün (YYYY-MM-DD) veya tarih-saat (ISO8601) formatında olabilir
        since_str = args.since.strip()
        if 'T' not in since_str and len(since_str) == 10:
            # YYYY-MM-DD formatında, günün başlangıcından başla
            start_ts, _ = day_bounds(since_str, args.tz)
        else:
            # ISO8601 formatında (tarih-saat ile), direkt parse et
            start_ts = parse_iso(since_str)
        rx, tx = compute_usage_between(start_ts, end_ts, iface, args.db)
        start_dt = dt.datetime.fromtimestamp(start_ts).isoformat()
        end_dt = dt.datetime.fromtimestamp(end_ts).isoformat()
        print_usage_result(f"{start_dt} .. {end_dt} ({iface})", rx, tx)
        return
    if args.day:
        start_ts, end_ts = day_bounds(args.day, args.tz)
        rx, tx = compute_usage_between(start_ts, end_ts, iface, args.db)
        print_usage_result(f"{args.day} ({iface})", rx, tx)
        if args.hourly:
            print("\nSaatlik dağılım:")
            buckets = hourly_buckets_for_day(args.day, iface, args.db, args.tz)
            for h, brx, btx in buckets:
                print(f"  {h:02d}:00 - {h+1:02d}:00  ↓ {humanize_bytes(brx)}  ↑ {humanize_bytes(btx)}")
        return
    if args.range_from and args.range_to:
        start_ts = parse_iso(args.range_from)
        end_ts = parse_iso(args.range_to)
        if end_ts <= start_ts:
            raise SystemExit("--from, --to'dan önce olmalı")
        rx, tx = compute_usage_between(start_ts, end_ts, iface, args.db)
        print_usage_result(f"{args.range_from} .. {args.range_to} ({iface})", rx, tx)
        return
    if args.last:
        seconds = parse_duration(args.last)
        end_ts = int(time.time())
        start_ts = end_ts - seconds
        rx, tx = compute_usage_between(start_ts, end_ts, iface, args.db)
        print_usage_result(f"son {args.last} ({iface})", rx, tx)
        return

def build_parser():
    p = argparse.ArgumentParser(description="macOS ağ veri kullanımı kaydedici ve raporlama (CLI)")
    p.add_argument("--db", default=DB_PATH_DEFAULT, help=f"SQLite veritabanı yolu (vars: {DB_PATH_DEFAULT})")
    p.add_argument("--iface", help="İzlenecek arayüz (ör: en0). Boşsa otomatik tespit edilir.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("sample", help="Tek seferlik örnek al")
    sp.set_defaults(func=cmd_sample)
    sw = sub.add_parser("watch", help="Belirli aralıklarla sürekli örnek al")
    sw.add_argument("--interval", type=int, default=60, help="Örnekleme aralığı sn (vars: 60)")
    sw.set_defaults(func=cmd_watch)
    sr = sub.add_parser("report", help="Rapor üret")
    sr.add_argument("--day", help="Günlük rapor tarihi (YYYY-MM-DD)")
    sr.add_argument("--hourly", action="store_true", help="Günlük raporu saatlik kırılımda da göster")
    sr.add_argument("--from", dest="range_from", help="Başlangıç zamanı (ISO8601, ör: 2025-11-02T00:00:00)")
    sr.add_argument("--to", dest="range_to", help="Bitiş zamanı (ISO8601)")
    sr.add_argument("--last", help="Son X süre (örn. 30m, 1h, 24h, 7d, 2w)")
    sr.add_argument("--since", help="Belirli bir tarihten bugüne kadar (YYYY-MM-DD veya ISO8601 tarih-saat, ör: 2025-11-01 veya 2025-11-02T18:30:00)")
    sr.add_argument("--tz", help="Gün sınırları için saat dilimi (örn: Europe/Istanbul). Boşsa yerel saat.")
    sr.add_argument("--update", action="store_true", help="Raporlamadan hemen önce bir sample al")
    sr.set_defaults(func=cmd_report)
    return p

def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
