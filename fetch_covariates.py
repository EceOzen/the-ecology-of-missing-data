"""
Bağlamsal katmanlar — "neden bu bölge sessiz" sorusuna açıklayıcı değişkenler:

  1) WDPA: il başına korunan alan oranı (%)            [yerel dosyadan]
  2) WorldPop: il başına nüfus ve nüfus yoğunluğu (kişi/km²)
  3) OSM (ana yollar): il başına ana yol uzunluğu ve yoğunluğu (km, km/km²)

v2 düzeltmeleri:
  * Alan: derece*111² yerine EPSG:6933 (eşit-alan). Eski yöntem alanı ~%29 şişiriyordu.
  * Yol uzunluğu: EPSG:3857 yerine ilin kendi UTM diliminde ölçülüyor (3857 uzunluğu ~%29 şişirir).
  * Nüfus yoğunluğu: raster ORTALAMASI değil, toplam nüfus / alan(km²). WorldPop 100 m "kişi/piksel"
    verir; ortalaması kişi/km² DEĞİLDİR (İstanbul 2663 gibi anlamsız bir sayı çıkıyordu).
  * WDPA: API geometri vermiyordu ve hiçbir yere bağlanmamıştı. Artık Protected Planet'ten
    indirilen Türkiye dosyasını okuyup il kesişimini hesaplıyor.
  * OSM: implausible düşük sonuç (< ~0.02 km/km²) hata sayılıp başka aynada yeniden denenir.

Kullanım:  python fetch_covariates.py [--only wdpa|pop|roads]

WDPA dosyası: https://www.protectedplanet.net/country/TUR -> Download (Shapefile veya GeoPackage),
zip'i aç, içindeki *polygons* dosyasını şu adlardan biriyle data/cache/ altına koy:
    wdpa_tur.gpkg | wdpa_tur.shp | wdpa_tur.geojson
(Türkiye dosyası birkaç parçaya bölünmüş olabilir; hepsini QGIS/ogr2ogr ile birleştir ya da bana sor.)
"""
import argparse
import time
import pandas as pd
import geopandas as gpd
from tqdm import tqdm

from config import RAW_DIR, DATA_DIR, EQUAL_AREA_EPSG, load_boundaries

CACHE_DIR = DATA_DIR / "cache"


def area_km2(gdf):
    """Her il için eşit-alan projeksiyonunda km² (gdf ile aynı index)."""
    return gdf.to_crs(epsg=EQUAL_AREA_EPSG).geometry.area / 1e6


# ---------------------------------------------------------------------------
# 1) WDPA — korunan alan oranı (yerel dosya)
# ---------------------------------------------------------------------------
def find_wdpa_file():
    for name in ("wdpa_tur.gpkg", "wdpa_tur.shp", "wdpa_tur.geojson"):
        p = CACHE_DIR / name
        if p.exists():
            return p
    return None


def compute_protected_area_ratio(boundaries, wdpa):
    wdpa = wdpa[wdpa.geometry.notna()].copy()
    # planlanan/önerilen alanları dışarıda bırak (sütun varsa)
    if "STATUS" in wdpa.columns:
        wdpa = wdpa[~wdpa["STATUS"].isin(["Proposed", "Not Reported"])]
    wdpa["geometry"] = wdpa.geometry.buffer(0)
    wdpa = wdpa.to_crs(epsg=EQUAL_AREA_EPSG)
    # üst üste binen alanlar iki kez sayılmasın
    union = wdpa.geometry.unary_union

    b = boundaries.to_crs(epsg=EQUAL_AREA_EPSG)
    rows = []
    for idx, il in b.iterrows():
        a = il.geometry.area
        inter = il.geometry.intersection(union).area
        rows.append({"il_adi": boundaries.loc[idx, "il_adi"],
                     "korunan_alan_orani": round(100 * inter / a, 2) if a else 0.0})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 2) WorldPop — toplam nüfus ve nüfus yoğunluğu
# ---------------------------------------------------------------------------
def compute_population_density(boundaries, raster_path):
    """
    raster_path: WorldPop Türkiye 100 m "kişi/piksel" (ppp) GeoTIFF'i, data/cache/worldpop_tur.tif.
    (Bu bir YOĞUNLUK rasterı değilse — dosya adında 'pd' varsa — toplam yerine ortalama gerekir.)
    """
    from rasterstats import zonal_stats

    stats = zonal_stats(boundaries, str(raster_path), stats=["sum"], nodata=-99999)
    areas = area_km2(boundaries)
    rows = []
    for (idx, il), s in zip(boundaries.iterrows(), stats):
        total = s["sum"]
        a = float(areas.loc[idx])
        rows.append({"il_adi": il["il_adi"], "tahmini_nufus": total, "alan_km2": round(a, 1),
                     "nufus_yogunlugu_km2": round(total / a, 1) if total is not None and a else None})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3) OSM — ana yol yoğunluğu
# ---------------------------------------------------------------------------
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
ROAD_CSV_HEADER = "il_adi,yol_uzunlugu_km,yol_yogunlugu_km_per_km2\n"
MIN_PLAUSIBLE_KM_PER_KM2 = 0.02   # bunun altı = büyük olasılıkla yarım/boş Overpass yanıtı


def _fetch_one_il_roads(geometry, il_area_km2, max_retries=4):
    """
    Ana yollar (motorway/trunk/primary/secondary). Bbox ile sorgulanır, gerçek il sınırına
    kırpılır. Uzunluk ilin UTM diliminde ölçülür. Sonuç implausible düşükse başka aynada yeniden denenir.
    """
    import osmnx as ox

    tags = {"highway": ["motorway", "trunk", "primary", "secondary"]}
    bbox_poly = geometry.envelope

    last_err = None
    for attempt in range(max_retries):
        mirror = OVERPASS_MIRRORS[attempt % len(OVERPASS_MIRRORS)]
        ox.settings.overpass_url = mirror
        ox.settings.overpass_rate_limit = True
        ox.settings.timeout = 180
        ox.settings.requests_timeout = 180
        ox.settings.max_query_area_size = 50_000 * 1_000_000
        try:
            gdf = ox.features_from_polygon(bbox_poly, tags=tags)
            gdf = gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])].copy()
            if gdf.empty:
                raise RuntimeError("Overpass boş döndü")
            gdf = gdf[gdf.geometry.intersects(geometry)].copy()
            gdf["geometry"] = gdf.geometry.intersection(geometry)
            gdf = gdf[~gdf.geometry.is_empty]
            km = gdf.to_crs(gdf.estimate_utm_crs()).length.sum() / 1000
            if il_area_km2 and km / il_area_km2 < MIN_PLAUSIBLE_KM_PER_KM2:
                raise RuntimeError(f"implausibly düşük sonuç ({km:.1f} km / {il_area_km2:.0f} km²) — yarım yanıt olabilir")
            return km
        except Exception as e:
            last_err = e
            time.sleep(5 * (attempt + 1))
    raise last_err


def compute_road_density(boundaries, out_path):
    """Her il bitince out_path'e yazar (checkpoint); yarıda kalırsa başarılı iller atlanır."""
    already_done = set()
    if out_path.exists():
        existing = pd.read_csv(out_path)
        already_done = set(existing.loc[existing["yol_uzunlugu_km"].notna(), "il_adi"])
        existing[existing["il_adi"].isin(already_done)].to_csv(out_path, index=False)
        print(f"Kaldığı yerden devam: {len(already_done)} il zaten çekilmiş, atlanacak.")
    else:
        out_path.write_text(ROAD_CSV_HEADER)

    areas = area_km2(boundaries)
    for idx, il in tqdm(boundaries.iterrows(), total=len(boundaries), desc="OSM yol ağı"):
        name = il["il_adi"]
        if name in already_done:
            continue
        a = float(areas.loc[idx])
        try:
            km = _fetch_one_il_roads(il.geometry, a)
            with open(out_path, "a") as f:
                f.write(f"{name},{round(km, 1)},{round(km / a, 3)}\n")
        except Exception as e:
            print(f"Uyarı: {name} için OSM hatası (tüm aynalar denendi): {e}")
            with open(out_path, "a") as f:
                f.write(f"{name},,\n")
    df = pd.read_csv(out_path)
    # son kontrol: hâlâ şüpheli düşük olanları bildir
    sus = df[(df["yol_yogunlugu_km_per_km2"] < MIN_PLAUSIBLE_KM_PER_KM2) | df["yol_uzunlugu_km"].isna()]
    if len(sus):
        print(f"UYARI: {len(sus)} il boş ya da şüpheli düşük: {', '.join(sus['il_adi'])}. "
              f"Script'i tekrar çalıştırırsan sadece boşlar yeniden denenir.")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["wdpa", "pop", "roads"], help="sadece birini çalıştır")
    args = ap.parse_args()
    boundaries = load_boundaries()

    if args.only in (None, "wdpa"):
        wdpa_file = find_wdpa_file()
        if wdpa_file:
            wdpa = gpd.read_file(wdpa_file)
            df = compute_protected_area_ratio(boundaries, wdpa)
            df.to_csv(RAW_DIR / "korunan_alan_il.csv", index=False)
            print(f"Kaydedildi: korunan_alan_il.csv  (en yüksek: {df.loc[df.korunan_alan_orani.idxmax(), 'il_adi']} "
                  f"%{df.korunan_alan_orani.max()})")
        else:
            print("Atlandı: data/cache/wdpa_tur.(gpkg|shp|geojson) yok — dosyanın nereden indirileceği için dosya başındaki nota bak.")

    if args.only in (None, "pop"):
        raster = CACHE_DIR / "worldpop_tur.tif"
        if raster.exists():
            df = compute_population_density(boundaries, raster)
            df.to_csv(RAW_DIR / "nufus_yogunlugu_il.csv", index=False)
            print(f"Kaydedildi: nufus_yogunlugu_il.csv  (toplam nüfus: {df.tahmini_nufus.sum():,.0f} — ~85 milyona yakın olmalı)")
        else:
            print(f"Atlandı: {raster} bulunamadı — WorldPop'tan indir.")

    if args.only in (None, "roads"):
        compute_road_density(boundaries, RAW_DIR / "yol_agi_il.csv")
        print("Kaydedildi: yol_agi_il.csv")


if __name__ == "__main__":
    main()
