"""
Xeno-canto: Türkiye'deki ses kayıtlarının il başına dağılımı.

Neden: GBIF kayıtları ile ses kayıtlarını yan yana koymak. Kuşun "duyulup hiç
kaydedilmediği" / "kayıt var ama ses yok" yerleri görünür olur.

Gereksinim: ücretsiz hesap -> https://xeno-canto.org/account -> API key -> .env içine
    XENO_CANTO_KEY=xxxx
(API v3 key ister. DOĞRULA: alan adları ve `per_page` sınırı aşağıda v2/v3 belgelerinden
 hatırlanarak yazıldı; script ilk kaydın alanlarını ekrana basar, farklıysa FIELD_* sabitlerini düzelt.)

Yalnızca META VERİ (id, tür, koordinat) kullanılır; ses dosyaları indirilmez.
Kayıtlar CC lisanslıdır; siteye ses koyarsan her kaydın lisansına ve kaydedene atıf gerekir.

Çıktılar:
  data/cache/xenocanto_tr.json        ham kayıtlar (tekrar çalıştırmada API'ye gitmeden okunur)
  data/raw/xenocanto_il_ozet.csv      il_adi, xc_kayit, xc_tur_sayisi
  data/raw/xenocanto_il_tur.csv       il_adi, tur (Genus species), xc_kayit
"""
import json
import time
import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

from config import RAW_DIR, DATA_DIR, XENO_CANTO_KEY, REQUEST_TIMEOUT, load_boundaries

BASE = "https://xeno-canto.org/api/3/recordings"
QUERIES = ['cnt:"Turkey"', 'cnt:"Türkiye"']     # ülke adı iki yazımla denenir, id'ye göre tekilleştirilir
PER_PAGE = 500
FIELD_LAT, FIELD_LON, FIELD_GEN, FIELD_SP = "lat", "lon", "gen", "sp"
CACHE = DATA_DIR / "cache" / "xenocanto_tr.json"


def fetch_all():
    if not XENO_CANTO_KEY:
        raise SystemExit("XENO_CANTO_KEY tanımlı değil (.env). Key: https://xeno-canto.org/account")
    recs = {}
    for q in QUERIES:
        page = 1
        while True:
            r = requests.get(BASE, params={"query": q, "key": XENO_CANTO_KEY, "page": page, "per_page": PER_PAGE},
                             timeout=60)
            r.raise_for_status()
            j = r.json()
            if j.get("error"):
                raise SystemExit(f"Xeno-canto hata döndü: {j}")
            for rec in j.get("recordings", []):
                recs[rec["id"]] = rec
            n_pages = int(j.get("numPages", 1))
            print(f"  {q}  sayfa {page}/{n_pages}  (toplam benzersiz kayıt: {len(recs)})")
            if page >= n_pages:
                break
            page += 1
            time.sleep(1.1)              # nazik ol: ~1 istek/sn
    return list(recs.values())


def main():
    if CACHE.exists():
        recs = json.loads(CACHE.read_text())
        print(f"Cache'ten okundu: {len(recs)} kayıt ({CACHE}). Yenilemek için dosyayı sil.")
    else:
        recs = fetch_all()
        CACHE.write_text(json.dumps(recs))
    if not recs:
        raise SystemExit("Hiç kayıt gelmedi — key'i ve ülke sorgusunu kontrol et.")
    print("İlk kaydın alanları:", sorted(recs[0].keys()))

    rows, no_coord = [], 0
    for r in recs:
        try:
            lat, lon = float(r[FIELD_LAT]), float(r[FIELD_LON])
        except (KeyError, TypeError, ValueError):
            no_coord += 1
            continue
        rows.append({"id": r["id"], "tur": f"{r.get(FIELD_GEN, '')} {r.get(FIELD_SP, '')}".strip(),
                     "geometry": Point(lon, lat)})
    print(f"Koordinatı olmayan kayıt: {no_coord} / {len(recs)}  (bunlar ile atanamaz — bu da bir sessizlik türü)")

    pts = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    il = load_boundaries()[["il_adi", "geometry"]]
    joined = gpd.sjoin(pts, il, how="left", predicate="within")
    outside = joined["il_adi"].isna().sum()
    print(f"Hiçbir ile düşmeyen (kıyı dışı/sınır dışı) kayıt: {outside}")
    joined = joined.dropna(subset=["il_adi"])

    per_tur = joined.groupby(["il_adi", "tur"]).size().reset_index(name="xc_kayit")
    per_il = joined.groupby("il_adi").agg(xc_kayit=("id", "count"), xc_tur_sayisi=("tur", "nunique")).reset_index()
    # kaydı hiç olmayan iller de 0 ile görünsün
    per_il = il[["il_adi"]].merge(per_il, on="il_adi", how="left").fillna({"xc_kayit": 0, "xc_tur_sayisi": 0})
    per_il[["xc_kayit", "xc_tur_sayisi"]] = per_il[["xc_kayit", "xc_tur_sayisi"]].astype(int)

    per_il.to_csv(RAW_DIR / "xenocanto_il_ozet.csv", index=False)
    per_tur.to_csv(RAW_DIR / "xenocanto_il_tur.csv", index=False)
    print(f"Kaydedildi: xenocanto_il_ozet.csv ({len(per_il)} il), xenocanto_il_tur.csv")
    print("\nEn çok / en az ses kaydı olan iller:")
    print(per_il.sort_values("xc_kayit", ascending=False).head(5).to_string(index=False))
    print(per_il.sort_values("xc_kayit").head(5).to_string(index=False))


if __name__ == "__main__":
    main()
