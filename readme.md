### Artık --update komutu ile sampleyi yazmaya gerek kalmadı

# Tek seferlik örnek alma (en başta bunu yap)
python3 netusage.py sample

# Belirli bir aralıkla sürekli örnek alma (60 saniye)
python3 netusage.py watch --interval 60


# Belirli bir günün toplamı
python3 netusage.py report --day 2025-11-02 --update

# Aynı günün saatlik kırılımı
python3 netusage.py report --day 2025-11-02 --hourly --update

# Belirli tarih/saat aralığı
python3 netusage.py report --from "2025-11-01T12:00:00" --to "2025-11-03T23:00:00" --update

# Son 1 saat
python3 netusage.py report --last 1h --update

# Son 24 saat
python3 netusage.py report --last 24h --update

# Diğer örnekler
python3 netusage.py report --last 30m --update
python3 netusage.py report --last 7d --update
python3 netusage.py report --last 2w --update

# Raporlamadan hemen önce otomatik sample alır
python3 netusage.py report --last 1h --update

# Günlük raporda da geçerli
python3 netusage.py report --day 2025-11-03 --update
