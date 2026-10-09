"""
GBIF: il başına AYLIK kuş kaydı sayısı (göç / mevsimsel sessizlik için).

Çıktı: data/raw/gbif_il_aylik.csv   (il_adi, ay, kayit)   ay = 1..12, START_YEAR-END_YEAR toplamı
Checkpoint'lidir: yarıda kesilirse tekrar çalıştırınca bitmiş illeri atlar.
81 il x 2 istek (~1.2 sn bekleme) -> yaklaşık 4-5 dakika.

Sonraki adım (site tarafı): "hangi il hangi ayda sessiz" = bir ilin ay payı / ülke geneli ay payı.
"""
import time
import pandas as pd
from tqdm import tqdm

from config import RAW_DIR, RATE_LIMIT_DELAY, START_YEAR, END_YEAR, load_boundaries, BIRD_TAXON_KEY
from fetch_gbif import polygon_to_wkt, _occ_search_with_retry

OUT = RAW_DIR / "gbif_il_aylik.csv"


def monthly_counts(wkt):
    resp = _occ_search_with_retry(
        geometry=wkt, taxonKey=BIRD_TAXON_KEY, year=f"{START_YEAR},{END_YEAR}",
        facet="month", facetLimit=12, limit=0)
    out = {m: 0 for m in range(1, 13)}
    for f in resp.get("facets", []):
        if f["field"] == "MONTH":
            for c in f["counts"]:
                out[int(c["name"])] = c["count"]
    return out


def main():
    gdf = load_boundaries()
    done = set()
    if OUT.exists():
        done = set(pd.read_csv(OUT)["il_adi"].unique())
        print(f"{len(done)} il zaten çekilmiş, atlanacak.")
    else:
        OUT.write_text("il_adi,ay,kayit\n")

    for _, il in tqdm(gdf.iterrows(), total=len(gdf), desc="GBIF aylık"):
        name = il["il_adi"]
        if name in done:
            continue
        try:
            counts = monthly_counts(polygon_to_wkt(il.geometry, il_adi=name))
        except Exception as e:
            print(f"Uyarı: {name} aylık çekim hatası: {e}")
            continue
        with open(OUT, "a") as f:
            for m, c in counts.items():
                f.write(f"{name},{m},{c}\n")
        time.sleep(RATE_LIMIT_DELAY)

    df = pd.read_csv(OUT)
    print(f"Kaydedildi: {OUT} ({df['il_adi'].nunique()} il)")
    nat = df.groupby("ay")["kayit"].sum()
    print("\nUlusal aylık kuş kaydı (kontrol: göç aylarında artış beklenir):")
    print(nat.to_string())


if __name__ == "__main__":
    main()
