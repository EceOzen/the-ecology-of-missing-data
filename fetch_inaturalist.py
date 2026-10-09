"""
iNaturalist: il bounding box'ı üzerinden gözlem sayımı.

Public API, key gerekmiyor. quality_grade ile "research" (uzman onaylı)
ve "casual" (onaysız) ayrımını ayrı ayrı çekiyoruz — bu, "hangi gözlem
resmi bilime sayılıyor" sorusuna doğrudan veri sağlıyor.

NOT: iNaturalist gözlemlerinin büyük kısmı zaten GBIF'e besleniyor.
Bu script'i asıl research/casual ayrımı için kullan, toplam hacim için
GBIF verisiyle çakışma olacağını unutma (aggregate.py bunu ayrı sütunlarda
tutuyor, otomatik toplamıyor).
"""
import time
import requests
import pandas as pd
from tqdm import tqdm

from config import RAW_DIR, RATE_LIMIT_DELAY, REQUEST_TIMEOUT, load_boundaries

BASE = "https://api.inaturalist.org/v1/observations"


def count_observations(bbox, quality_grade=None):
    params = {
        "swlat": bbox[1], "swlng": bbox[0],
        "nelat": bbox[3], "nelng": bbox[2],
        "per_page": 0,  # sadece total_results istiyoruz
    }
    if quality_grade:
        params["quality_grade"] = quality_grade
    r = requests.get(BASE, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()["total_results"]


def main():
    gdf = load_boundaries()
    rows = []

    for _, il in tqdm(gdf.iterrows(), total=len(gdf), desc="iNaturalist illeri"):
        name = il.get("il_adi", il.get("name", "bilinmiyor"))
        bbox = il.geometry.bounds  # (minx, miny, maxx, maxy)

        try:
            total = count_observations(bbox)
            time.sleep(RATE_LIMIT_DELAY)
            research = count_observations(bbox, quality_grade="research")
            time.sleep(RATE_LIMIT_DELAY)
            casual = count_observations(bbox, quality_grade="casual")
            time.sleep(RATE_LIMIT_DELAY)
        except requests.HTTPError as e:
            print(f"Uyarı: {name} için hata: {e}")
            continue

        rows.append({
            "il_adi": name,
            "inat_toplam": total,
            "inat_research_grade": research,
            "inat_casual": casual,
        })

    df = pd.DataFrame(rows)
    out_path = RAW_DIR / "inaturalist_il_ozet.csv"
    df.to_csv(out_path, index=False)
    print(f"Kaydedildi: {out_path} ({len(df)} il)")
    print(
        "NOT: Bounding box kullanıldığı için sınır illerinde (örn. komşu "
        "illerle iç içe geçen bbox'larda) hafif üst-sayım olabilir — "
        "polygon-exact sayım istersen 'geometry' yerine noktaları çekip "
        "GeoPandas ile spatial join yapman gerekir."
    )


if __name__ == "__main__":
    main()
