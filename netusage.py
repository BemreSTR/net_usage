
#!/usr/bin/env python3
"""
netusage.py — Terminal tabanlı macOS ağ (Wi‑Fi) veri kullanımı kaydedici ve raporlama aracı.

Özellikler
- Arayüz tespiti: Varsayılan çıkış (default route) arayüzünü otomatik bulur (genelde Wi‑Fi: en0).
- Örnekleme (sampling): Şu anki toplam RX/TX bayt değerlerini SQLite veritabanına yazar.
- İzleme (watch): Belirlenen aralıkla (varsayılan 60s) sürekli örnek alır.
- Raporlar:
  * Günlük toplam (YYYY-MM-DD)
  * Saatlik dağılım (YYYY-MM-DD için)
  * Özel zaman aralığı (ISO8601 başlangıç/bitiş)

Kullanım
  python3 netusage.py watch --interval 60
  python3 netusage.py sample
  python3 netusage.py report --day 2025-11-02
  python3 netusage.py report --day 2025-11-02 --hourly
  python3 netusage.py report --from "2025-11-01T00:00:00" --to "2025-11-02T00:00:00"

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
    """
    Varsayılan ağ geçidi için kullanılan arayüzü bulur.
    """
    try:
        out = run(["route", "get", "default"])
        for line in out.splitlines():
            if "interface:" in line:
                return line.split()[-1].strip()
    except Exception:
        pass
    # Yedek yöntem: Wi‑Fi arayüz adını bul
    try:
        out = run(["networksetup", "-listallhardwareports"])
        # Örnek blok:
        # Hardware Port: Wi-Fi
        # Device: en0
        # ...
        lines = out.splitlines()
        for i, line in enumerate(lines):
            if "Hardware Port: Wi-Fi" in line or "Hardware Port: Wi‑Fi" in line:
                for j in range(i+1, min(i+5, len(lines))):
                    if lines[j].strip().startswith("Device:"):
                        return lines[j].split(":")[1].strip()
    except Exception:
        pass
    # En son çare: en0 varsay
    return "en0"

def read_iface_bytes(iface: str) -> Tuple[int, int]:
    """
    netstat ile RX/TX baytlarını okur.
    macOS: 'netstat -ib -I <iface>' çıktısında Ibytes (RX) ve Obytes (TX) sütunları bulunur.
    """
    out = run(["netstat", "-ib", "-I", iface])
    # Başlık satırını bul, son satırdaki toplamları al (aynı arayüz birden çok satır olabilir)
    # Format değişken olabilir; bu yüzden sütun adlarını bulmaya çalış.
    lines = [l for l in out.splitlines() if l.strip()]
    header = None
    for i, l in enumerate(lines):
        if l.lower().startswith("name"):
            header = lines[i]
            data_lines = lines[i+1:]
            break
    if header is None:
        # Fallback: tüm satırlarda topla (sütun pozisyonlarına güvenmeden)
        rx_total = tx_total = 0
        for l in lines[1:]:
            parts = l.split()
            try:
                # Genellikle: ... Ibytes Obytes ...
                # Ibytes genelde sondan 4., Obytes sondan 3. olabilir.
                rx = int(parts[-4])
                tx = int(parts[-3])
                rx_total += rx
                tx_total += tx
            except Exception:
                continue
        return rx_total, tx_total
    # Sütun isimlerine göre index bul
    cols = header.split()
    def find_idx(name: str) -> Optional[int]:
        for idx, c in enumerate(cols):
            if c.lower() == name:
                return idx
        return None
    # Bazı sürümlerde 'Ibytes'/'Obytes' küçük/büyük olabilir
    try:
        i_idx = find_idx("ibytes") or cols.index("Ibytes")
        o_idx = find_idx("obytes") or cols.index("Obytes")
    except Exception:
        # Tahmini indexlerle dene
        i_idx = -4
        o_idx = -3
    rx_total = 0
    tx_total = 0
    for l in data_lines:
        parts = l.split()
        if len(parts) <= max(i_idx, o_idx):
            continue
        # Sadece seçilen iface satırlarını topla
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
        if dr < 0: dr = 0  # sayaç sıfırlandı/taştıysa
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

def day_bounds(date_str: str, tz: Optional[str] = None) -> Tuple[int,int]:
    tzinfo = None
    if tz:
        try:
            import zoneinfo
            tzinfo = zoneinfo.ZoneInfo(tz)
        except Exception:
            pass
    if tzinfo is None:
        # Sistem saat dilimi
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
    # ISO8601 gibi: 2025-11-02T00:00:00
    try:
        dtobj = dt.datetime.fromisoformat(s)
    except Exception:
        raise SystemExit("Tarih/saat ISO8601 formatında olmalı, ör: 2025-11-02T09:00:00")
    if dtobj.tzinfo is None:
        dtobj = dtobj.astimezone()  # yerel saat
    return int(dtobj.timestamp())

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

def cmd_report(args):
    iface = args.iface or detect_default_iface()
    if args.day:
        start_ts, end_ts = day_bounds(args.day, args.tz)
        rx, tx = compute_usage_between(start_ts, end_ts, iface, args.db)
        print(f"[rapor] {args.day} ({iface})")
        print(f"  İndirilen: {humanize_bytes(rx)}")
        print(f"  Yüklenen: {humanize_bytes(tx)}")
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
        print(f"[rapor] {args.range_from} .. {args.range_to} ({iface})")
        print(f"  İndirilen: {humanize_bytes(rx)}")
        print(f"  Yüklenen: {humanize_bytes(tx)}")
        return
    raise SystemExit("report için --day YYYY-MM-DD veya --from ISO --to ISO veriniz.")

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
    sr.add_argument("--tz", help="Gün sınırları için saat dilimi (örn: Europe/Istanbul). Boşsa yerel saat.")
    sr.set_defaults(func=cmd_report)
    return p

def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
