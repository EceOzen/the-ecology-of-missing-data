"""
GBIF: il polygon'ları üzerinden WKT sorgusu ile occurrence sayımı.

occurrence/search endpoint'i key gerektirmiyor. Her il için:
  - toplam kayıt sayısı (tüm taksonlar)
  - yıllara göre kırılım (START_YEAR - END_YEAR)
  - benzersiz recordedBy (gözlemci) sayısı yaklaşık tahmini (facet ile)

Büyük/çok adacıklı il sınırları GBIF'in WKT karakter limitine takılabilir,
bu yüzden SIMPLIFY_TOLERANCE ile basitleştiriyoruz.
"""
import time
import pandas as pd
from pygbif import occurrences as occ
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient
from tqdm import tqdm

from config import RAW_DIR, RATE_LIMIT_DELAY, START_YEAR, END_YEAR, SIMPLIFY_TOLERANCE, load_boundaries, BIRDS_ONLY, BIRD_TAXON_KEY


MAX_WKT_LENGTH = 1500  # GBIF search endpoint'i bu civarı aşan WKT'lerde 400 verebiliyor


def _drop_slivers(geom, min_area_ratio=0.001):
    """buffer(0) sonrası oluşan minik kırıntı polygon'ları at, sadece anlamlı
    parçaları tut (toplam alanın min_area_ratio'dan büyük olanlar)."""
    if not isinstance(geom, MultiPolygon):
        return geom
    total_area = geom.area
    if total_area == 0:
        return geom
    kept = [p for p in geom.geoms if p.area / total_area >= min_area_ratio]
    if not kept:
        kept = [max(geom.geoms, key=lambda p: p.area)]
    return kept[0] if len(kept) == 1 else MultiPolygon(kept)


def polygon_to_wkt(geom, tolerance=SIMPLIFY_TOLERANCE, il_adi=None):
    """
    GBIF, polygon köşelerinin saat yönünün TERSİNE (counter-clockwise) sıralı
    olmasını şart koşuyor — aksi halde 400 Bad Request veriyor.
    Ayrıca WKT ~1500 karakteri aştığında da 400 verebiliyor, bu yüzden:
      1) basitleştir + geçersizse buffer(0) ile onar
      2) buffer(0)'ın ürettiği minik kırıntı parçaları at
      3) hâlâ çok uzunsa toleransı kademeli artırarak tekrar dene
      4) son çare: bounding box'a düş (kaba ama en azından çalışır)
    """
    current_tolerance = tolerance
    for _ in range(6):
        simplified = geom.simplify(current_tolerance, preserve_topology=True)
        if not simplified.is_valid:
            simplified = simplified.buffer(0)
        simplified = _drop_slivers(simplified)

        if isinstance(simplified, Polygon):
            simplified = orient(simplified, sign=1.0)
        elif isinstance(simplified, MultiPolygon):
            simplified = MultiPolygon([orient(p, sign=1.0) for p in simplified.geoms])

        wkt = simplified.wkt
        if len(wkt) <= MAX_WKT_LENGTH:
            return wkt
        current_tolerance *= 2  # daha kaba basitleştirmeyi dene

    # Son çare: bounding box (il sınırının kaba dikdörtgeni)
    from shapely.geometry import box
    minx, miny, maxx, maxy = geom.bounds
    bbox = orient(box(minx, miny, maxx, maxy), sign=1.0)
    if il_adi:
        print(f"  UYARI: {il_adi} için sınır çok karmaşık, bounding box'a düşüldü "
              f"(komşu ilin bir kısmı yanlışlıkla dahil olabilir).")
    return bbox.wkt


def _occ_search_with_retry(max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            return occ.search(**kwargs)
        except Exception as e:
            if "429" in str(e) and attempt < max_retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise


def _taxon_kwargs(birds=None):
    """BIRDS_ONLY=True iken tür kırılımı sadece kuşları (Aves) getirir. Tüm taksonlar için birds=False."""
    birds = BIRDS_ONLY if birds is None else birds
    return {"taxonKey": BIRD_TAXON_KEY} if birds else {}


def count_for_il(wkt, year_from, year_to, birds=False):
    resp = _occ_search_with_retry(geometry=wkt, year=f"{year_from},{year_to}", limit=0, **_taxon_kwargs(birds))
    return resp["count"]


def yearly_breakdown(wkt):
    """Yıl bazlı kayıt sayısı (facet)."""
    resp = _occ_search_with_retry(
        geometry=wkt, facet="year", facetLimit=(END_YEAR - START_YEAR + 5), limit=0
    )
    counts = {}
    for f in resp.get("facets", []):
        if f["field"] == "YEAR":
            for c in f["counts"]:
                counts[c["name"]] = c["count"]
    return counts


def species_breakdown(wkt, page_size=1000, max_pages=10):
    """
    Tür bazlı kayıt sayısı (facet). facetOffset ile sayfalar: kalabalık illerde
    (Muğla, Antalya, İstanbul) türler artık kesilmiyor.
    """
    species = {}
    for i in range(max_pages):
        resp = _occ_search_with_retry(
            geometry=wkt, facet="speciesKey", facetLimit=page_size, facetOffset=i * page_size,
            limit=0, **_taxon_kwargs())
        got = 0
        for f in resp.get("facets", []):
            if f["field"] == "SPECIES_KEY":
                for c in f["counts"]:
                    species[c["name"]] = c["count"]  # speciesKey -> kayıt sayısı
                    got += 1
        if got < page_size:
            break
        time.sleep(RATE_LIMIT_DELAY)
    return species


SPECIES_CSV_HEADER = "il_adi,speciesKey,kayit_sayisi\n"


def main():
    gdf = load_boundaries()
    rows = []
    yearly_rows = []

    species_path = RAW_DIR / "gbif_il_tur_kirilimi.csv"
    already_done = set()
    if species_path.exists():
        existing = pd.read_csv(species_path)
        already_done = set(existing["il_adi"].unique())
        print(f"Tür kırılımı: {len(already_done)} il zaten çekilmiş, atlanacak.")
    else:
        species_path.write_text(SPECIES_CSV_HEADER)

    for _, il in tqdm(gdf.iterrows(), total=len(gdf), desc="GBIF illeri"):
        name = il.get("il_adi", il.get("name", "bilinmiyor"))
        wkt = polygon_to_wkt(il.geometry, il_adi=name)

        try:
            total = count_for_il(wkt, START_YEAR, END_YEAR)
            time.sleep(RATE_LIMIT_DELAY)
            yearly = yearly_breakdown(wkt)
            time.sleep(RATE_LIMIT_DELAY)
        except Exception as e:
            print(f"Uyarı: {name} için GBIF hatası (özet): {e}")
            continue

        try:
            birds_total = count_for_il(wkt, START_YEAR, END_YEAR, birds=True)
            time.sleep(RATE_LIMIT_DELAY)
        except Exception as e:
            print(f"Uyarı: {name} için kuş sayımı alınamadı: {e}")
            birds_total = None

        rows.append({"il_adi": name, "gbif_toplam_kayit": total, "gbif_kus_kayit": birds_total})
        for year, count in yearly.items():
            yearly_rows.append({"il_adi": name, "yil": year, "gbif_kayit": count})

        if name not in already_done:
            try:
                species = species_breakdown(wkt)
                with open(species_path, "a") as f:
                    for species_key, count in species.items():
                        f.write(f"{name},{species_key},{count}\n")
                time.sleep(RATE_LIMIT_DELAY)
            except Exception as e:
                print(f"Uyarı: {name} için GBIF hatası (tür kırılımı): {e}")

    pd.DataFrame(rows).to_csv(RAW_DIR / "gbif_il_ozet.csv", index=False)
    pd.DataFrame(yearly_rows).to_csv(RAW_DIR / "gbif_il_yillik.csv", index=False)
    print(f"Kaydedildi: {RAW_DIR / 'gbif_il_ozet.csv'}, gbif_il_yillik.csv, gbif_il_tur_kirilimi.csv")
    print(
        "NOT: 100k+ kayıtlı büyük illerde (İstanbul, Muğla vb.) search API "
        "sayfalama limitine takılabilir — bu durumda GBIF 'download' "
        "endpoint'ine (hesap gerektirir) geçmen gerekebilir."
    )


if __name__ == "__main__":
    main()
