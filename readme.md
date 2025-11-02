# Tek seferlik örnek alma (en başta bunu yap)
python3 netusage.py sample

# Belirli bir aralıkla sürekli örnek alma (60 saniye)
python3 netusage.py watch --interval 60

# Belirli bir günün toplamı
python3 netusage.py report --day 2025-11-02

# Aynı günün saatlik kırılımı
python3 netusage.py report --day 2025-11-02 --hourly

# Belirli tarih/saat aralığı
python3 netusage.py report --from "2025-11-01T12:00:00" --to "2025-11-03T23:00:00"
