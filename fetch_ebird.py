"""
eBird: il bazında (subnational1, TR-XX kodları) yıllık gözlem/tür istatistikleri.

eBird'in doğrudan "bölge başına kayıt sayısı" endpoint'i olmadığı için,
region'a ait checklist istatistiklerini (`get_region_stats` benzeri) ve
tür listesini kullanarak yaklaşık bir yoğunluk metriği üretiyoruz:
  - toplam checklist (gözlem listesi) sayısı
  - toplam tür sayısı
  - benzersiz gözlemci sayısı (varsa)

Not: eBird API'sinde 'observation count' değil 'checklist count' esas
birim — bu da projenin "gözlemci emeği" temasına iyi oturuyor.
"""
import time
import pandas as pd
import requests
from tqdm import tqdm

from config import EBIRD_API_KEY, RAW_DIR, RATE_LIMIT_DELAY, START_YEAR, END_YEAR, REQUEST_TIMEOUT, fix_name

BASE = "https://api.ebird.org/v2"
HEADERS = {"x-ebirdapitoken": EBIRD_API_KEY}


def get_turkey_subregions():
    """TR-XX il kodlarını ve isimlerini çeker."""
    url = f"{BASE}/ref/region/list/subnational1/TR"
    r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()  # [{"code": "TR-34", "name": "Istanbul"}, ...]


def get_region_species_count(region_code):
    """Bölgedeki toplam tür sayısı (tüm zamanlar)."""
    url = f"{BASE}/product/spplist/{region_code}"
    r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return len(r.json())


def get_recent_checklists_sample(region_code, max_results=200):
    """
    Son checklist'lerden bir örneklem — tam tarihsel toplu indirme eBird'in
    ücretsiz API'sinde desteklenmiyor (buna 'EBD' / Basic Dataset gerekir,
    ayrı bir başvuru: https://ebird.org/data/download).
    Bu script yalnızca API üzerinden erişilebilen özet istatistikleri çeker.
    """
    url = f"{BASE}/product/lists/{region_code}"
    r = requests.get(url, headers=HEADERS, params={"maxResults": max_results}, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def main():
    if not EBIRD_API_KEY:
        raise SystemExit("EBIRD_API_KEY .env dosyasında tanımlı değil.")

    regions = get_turkey_subregions()
    rows = []

    for region in tqdm(regions, desc="eBird illeri"):
        code, name = region["code"], fix_name(region["name"])
        try:
            species_count = get_region_species_count(code)
            time.sleep(RATE_LIMIT_DELAY)
            checklists = get_recent_checklists_sample(code)
            time.sleep(RATE_LIMIT_DELAY)

            observer_ids = {c.get("userDisplayName") for c in checklists if c.get("userDisplayName")}
            rows.append({
                "il_kodu": code,
                "il_adi": name,
                "ebird_tur_sayisi": species_count,
                "ebird_checklist_ornek_sayisi": len(checklists),
                "ebird_gozlemci_ornek_sayisi": len(observer_ids),
            })
        except requests.HTTPError as e:
            print(f"Uyarı: {code} ({name}) için hata: {e}")
            continue

    df = pd.DataFrame(rows)
    out_path = RAW_DIR / "ebird_il_ozet.csv"
    df.to_csv(out_path, index=False)
    print(f"Kaydedildi: {out_path} ({len(df)} il)")
    print(
        "NOT: Tam tarihsel/yıl-bazlı kayıt hacmi için eBird Basic Dataset (EBD) "
        "başvurusu gerekiyor — bu script sadece API üzerinden erişilebilen "
        "özet istatistikleri çekiyor."
    )


if __name__ == "__main__":
    main()
