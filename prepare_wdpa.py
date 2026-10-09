"""
Protected Planet'ten inen bölünmüş WDPA zip'lerini (..._TUR_shp_0/1/2.zip) birleştirir
ve data/cache/wdpa_tur.gpkg olarak yazar (fetch_covariates.py bunu otomatik bulur).

Kullanım:
  python prepare_wdpa.py  yol/WDPA_WDOECM_Oct2026_Public_TUR_shp_0.zip  ..._shp_1.zip  ..._shp_2.zip
  # ya da zip'lerin olduğu klasör:
  python prepare_wdpa.py  yol/klasor
Sadece POLİGON dosyaları alınır (nokta olanlar atlanır).
"""
import sys, zipfile, tempfile
from pathlib import Path
import pandas as pd
import geopandas as gpd
from config import DATA_DIR

def main(args):
    if not args:
        raise SystemExit(__doc__)
    zips = []
    for a in args:
        p = Path(a)
        zips += sorted(p.glob("*.zip")) if p.is_dir() else [p]
    zips = [z for z in zips if "shp" in z.name.lower() or "wdpa" in z.name.lower()]
    if not zips:
        raise SystemExit("zip bulunamadı")
    parts = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, z in enumerate(zips):
            d = Path(tmp) / f"z{i}"
            with zipfile.ZipFile(z) as zf:
                zf.extractall(d)
            for shp in sorted(d.rglob("*.shp")):
                if "point" in shp.name.lower():
                    print("  atlandı (nokta):", shp.name); continue
                g = gpd.read_file(shp)
                if g.empty or not g.geom_type.astype(str).str.contains("Polygon").any():
                    print("  atlandı (poligon yok):", shp.name); continue
                print(f"  {z.name} / {shp.name}: {len(g)} alan")
                parts.append(g)
    if not parts:
        raise SystemExit("Poligon shapefile bulunamadı")
    wdpa = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=parts[0].crs)
    if "WDPAID" in wdpa.columns:
        wdpa = wdpa.drop_duplicates("WDPAID")
    out = DATA_DIR / "cache" / "wdpa_tur.gpkg"
    out.parent.mkdir(parents=True, exist_ok=True)
    wdpa.to_file(out, driver="GPKG")
    print(f"Kaydedildi: {out}  ({len(wdpa)} alan). Şimdi: python fetch_covariates.py --only wdpa")

if __name__ == "__main__":
    main(sys.argv[1:])
