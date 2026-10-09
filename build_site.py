"""
Pipeline çıktılarından siteyi üretir:  site/index.html

Girdi:
  data/raw/gbif_il_tur_kirilimi.csv     il x tür kayıt sayıları
  data/raw/species_name_lookup.csv      (resolve_species_names.py; --vernacular ile Türkçe adlar da gelir)
  data/processed/il_summary.csv         (aggregate.py)
  data/boundaries/turkey_iller.geojson
  reference/bird_names.csv              Latince -> İngilizce ad
  site/site_template.html               arayüz şablonu (veri yer tutucuları içerir)
Çıktı:
  site/index.html  (+ site/.nojekyll)    -> GitHub Pages'e olduğu gibi yüklenir

Kullanım:  python build_site.py [--top 250]
"""
import argparse
import json
import re
import warnings
import pandas as pd
import geopandas as gpd

from config import BASE_DIR, RAW_DIR, PROCESSED_DIR, load_boundaries, neighbors, EQUAL_AREA_EPSG

TEMPLATE = BASE_DIR / "site" / "site_template.html"
OUT = BASE_DIR / "site" / "index.html"


def canonical_of(row):
    c = row.get("canonical")
    if isinstance(c, str) and c.strip():
        return c.strip()
    return " ".join(str(row["tur_adi"]).split()[:2])      # "Parus major Linnaeus, 1758" -> "Parus major"


def _len_sec(v):
    try:
        parts = [int(x) for x in str(v).split(":")]
        return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))
    except Exception:
        return 0


def best_recordings(latin_set):
    """data/cache/xenocanto_tr.json (fetch_xenocanto.py) -> {latin: {id,f,r,l,q,t,len}} (tür başına en iyi 1 kayıt:
    kalite A>B>.., 'song' tercih, ~8-45 sn)."""
    path = RAW_DIR.parent / "cache" / "xenocanto_tr.json"
    if not path.exists():
        print("NOT: xenocanto_tr.json yok — kuş sesi yerine ton çalınacak (fetch_xenocanto.py).")
        return {}
    recs = json.loads(path.read_text(encoding="utf-8"))
    qrank = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
    best = {}
    for r in recs:
        latin = f"{r.get('gen', '')} {r.get('sp', '')}".strip()
        f = r.get("file") or ""
        if latin not in latin_set or not f:
            continue
        if f.startswith("//"):
            f = "https:" + f
        n = _len_sec(r.get("length"))
        key = (qrank.get(str(r.get("q", "")).strip().upper(), 5),
               0 if "song" in str(r.get("type", "")).lower() else 1,
               0 if 8 <= n <= 45 else 1, abs(n - 20))
        if latin not in best or key < best[latin][0]:
            lic = str(r.get("lic", ""))
            m = re.search(r"licenses/([a-z\-]+)/([\d.]+)", lic)
            best[latin] = (key, {"id": str(r.get("id")), "f": f, "r": str(r.get("rec", "")),
                                 "l": (m.group(1).upper() + " " + m.group(2)) if m else "",
                                 "q": str(r.get("q", "")), "t": str(r.get("type", "")), "len": n})
    out = {k: v[1] for k, v in best.items()}
    # yerel ses dosyaları (fetch_sounds.py): site/sounds/<id>.mp3 varsa onu kullan; klasör varsa olmayanı at
    sdir = OUT.parent / "sounds"
    if sdir.exists():
        for k in list(out):
            if (sdir / f"{out[k]['id']}.mp3").exists():
                out[k]["f"] = f"sounds/{out[k]['id']}.mp3"
            else:
                del out[k]
        print(f"Yerel ses: {len(out)} tür site/sounds/ içinden çalacak.")
    else:
        print("NOT: site/sounds/ yok — ses xeno-canto'dan hotlink (çalmayabilir). fetch_sounds.py çalıştır.")
    return out


def classify_site(desig):
    d = str(desig or "").lower()
    if "ramsar" in d: return "ramsar"
    if "world heritage" in d: return "whs"
    if "biosphere" in d: return "mab"
    return "other"


def wdpa_sites(gdf):
    """data/cache/wdpa_tur.(gpkg|shp|geojson) -> koruma alanları sekmesi için [{n,t,k,il,a,lon,lat}].
    Not: Protected Planet Türkiye'nin verisinin çoğunu kısıtlıyor; burada sadece HERKESE AÇIK olanlar var."""
    for name in ("wdpa_tur.gpkg", "wdpa_tur.shp", "wdpa_tur.geojson"):
        f = RAW_DIR.parent / "cache" / name
        if f.exists():
            break
    else:
        print("NOT: wdpa_tur.* yok — Koruma alanları sekmesi nokta olmadan çıkacak.")
        return []
    w = gpd.read_file(f)
    w = w[w.geometry.notna()].copy()
    if "STATUS" in w.columns:
        w = w[~w["STATUS"].isin(["Proposed", "Not Reported"])]
    cen = w.to_crs(epsg=EQUAL_AREA_EPSG).geometry.centroid.to_crs(epsg=4326)
    pts = gpd.GeoDataFrame(w.drop(columns="geometry"), geometry=cen, crs=4326)
    j = gpd.sjoin(pts, gdf[["il_adi", "geometry"]].to_crs(4326), how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")]
    out = []
    for _, r in j.iterrows():
        nm = r.get("NAME_ENG") if isinstance(r.get("NAME_ENG"), str) and r.get("NAME_ENG").strip() else r.get("NAME")
        desig = r.get("DESIG_ENG") or r.get("DESIG") or ""
        a = r.get("GIS_AREA")
        out.append({"n": str(nm).strip(), "t": str(desig), "k": classify_site(desig),
                    "il": r["il_adi"] if isinstance(r.get("il_adi"), str) else "",
                    "a": int(round(float(a))) if a == a and a is not None else 0,
                    "lon": round(r.geometry.x, 3), "lat": round(r.geometry.y, 3)})
    out.sort(key=lambda x: -x["a"])
    print(f"{len(out)} herkese açık koruma alanı siteye eklendi ({len({x['il'] for x in out if x['il']})} ilde).")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=250, help="sitede kaç kuş türü olsun (ulusal kayıt sırasına göre)")
    args = ap.parse_args()

    matrix = pd.read_csv(RAW_DIR / "gbif_il_tur_kirilimi.csv")
    names = pd.read_csv(RAW_DIR / "species_name_lookup.csv")
    for c in ["canonical", "class", "vernacular_en", "vernacular_tr"]:
        if c not in names.columns:
            names[c] = ""
    ref = pd.read_csv(BASE_DIR / "reference" / "bird_names.csv").set_index("latin")["english"].to_dict()

    ref_full = pd.read_csv(BASE_DIR / "reference" / "bird_names.csv").set_index("latin")
    # Çok dilli sözlük (opsiyonel): reference/bird_names_multilang.csv  -> sütunlar: latin,tr,en,fr,es (speciesKey varsa o da kullanılır)
    ml = {}
    ml_path = BASE_DIR / "reference" / "bird_names_multilang.csv"
    if ml_path.exists():
        mdf = pd.read_csv(ml_path, dtype=str, encoding="utf-8-sig", sep=None, engine="python").fillna("")
        for r_ in mdf.to_dict("records"):
            ml[r_.get("latin", "").strip()] = {k: r_[k].strip() for k in ("tr", "en", "fr", "es", "de") if r_.get(k, "").strip()}
        print(f"Çok dilli sözlük: {len(ml)} satır okundu ({ml_path.name}).")
    nat = matrix.groupby("speciesKey")["kayit_sayisi"].sum().sort_values(ascending=False)
    names = names.drop_duplicates("speciesKey").set_index("speciesKey")

    species, missing = [], []
    for key, total in nat.items():
        if key not in names.index:
            continue
        r = names.loc[key]
        latin = canonical_of(r)
        has_class = isinstance(r.get("class"), str) and r["class"].strip() != ""
        is_bird = (r["class"] == "Aves") if has_class else (latin in ref)
        if not is_bird:
            continue
        en = r["vernacular_en"] if isinstance(r["vernacular_en"], str) and r["vernacular_en"].strip() else ref.get(latin)
        if not en:
            missing.append(latin)
            en = latin
        tr = r["vernacular_tr"] if isinstance(r["vernacular_tr"], str) and r["vernacular_tr"].strip() else ""
        sp = {"key": str(key), "name": str(r["tur_adi"]), "national": int(total), "latin": latin, "en": en}
        if tr:
            sp["tr"] = tr
        if latin in ml and ml[latin]:
            sp["n"] = ml[latin]                      # dile göre ad: n.tr / n.en / n.fr / n.es
        if latin in ref_full.index:
            fam, od = ref_full.loc[latin, "family"], ref_full.loc[latin, "order"]
            if isinstance(fam, str) and fam: sp["fam"] = fam
            if isinstance(od, str) and od: sp["ord"] = od
        species.append(sp)
        if len(species) >= args.top:
            break
    if missing:
        print(f"UYARI: {len(missing)} tür için İngilizce ad bulunamadı (Latince gösterilecek): {missing[:8]}"
              " -> reference/bird_names.csv'ye ekle")
    keep = {s["key"] for s in species}
    present = {}
    for r in matrix[matrix["speciesKey"].astype(str).isin(keep)].itertuples():
        present.setdefault(str(r.speciesKey), {})[r.il_adi] = int(r.kayit_sayisi)
    xc = best_recordings({sp["latin"] for sp in species})
    for sp in species:
        if sp["latin"] in xc:
            sp["xc"] = xc[sp["latin"]]
    print(f"{len(xc)} türe Xeno-canto kuş sesi eklendi.")
    # fetch_species_cards.py için tür listesi + (varsa) kart verisini ekle
    pd.DataFrame([{"speciesKey": s["key"], "latin": s["latin"], "en": s["en"]} for s in species]) \
        .to_csv(PROCESSED_DIR / "site_species.csv", index=False, encoding="utf-8-sig")
    cards_path = PROCESSED_DIR / "species_cards.json"
    if cards_path.exists():
        cards = json.loads(cards_path.read_text(encoding="utf-8"))
        n = 0
        for sp in species:
            c = cards.get(sp["latin"])
            if c:
                sp["card"] = c
                n += 1
        print(f"{n} türe kart verisi eklendi (species_cards.json).")
    else:
        print("NOT: species_cards.json yok — kuş kartları boş kalacak (python fetch_species_cards.py).")
    print(f"{len(species)} kuş türü siteye alındı ({sum(1 for s in species if 'tr' in s)} tanesinin Türkçe adı var).")

    gdf = load_boundaries()
    nb = neighbors(gdf)
    area = (gdf.to_crs(epsg=EQUAL_AREA_EPSG).geometry.area / 1e6).round().astype(int)
    area = dict(zip(gdf["il_adi"], area))
    summ = pd.read_csv(PROCESSED_DIR / "il_summary.csv").set_index("il_adi")
    stats = {}
    for il in gdf["il_adi"]:
        row = summ.loc[il] if il in summ.index else None
        def g(c):
            return None if row is None or c not in row or pd.isna(row[c]) else row[c]
        stats[il] = {
            "records": int(g("gbif_toplam_kayit") or matrix[matrix.il_adi == il].kayit_sayisi.sum()),
            "area": int(g("alan_km2") or area[il]),
            "ebird": int(g("ebird_tur_sayisi")) if g("ebird_tur_sayisi") is not None else None,
            "pop": int(g("tahmini_nufus")) if g("tahmini_nufus") is not None else None,
            "nb": nb[il],
        }
    for rank, il in enumerate(sorted(stats, key=lambda k: -stats[k]["records"]), 1):
        stats[il]["rank"] = rank

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")      # derece CRS'te centroid uyarısı: sıralama için yeterli
        cent = gdf.assign(lon=gdf.geometry.centroid.x).sort_values("lon")
    order = cent["il_adi"].tolist()

    html = TEMPLATE.read_text(encoding="utf-8")
    for token, obj in (("/*__SPECIES_DATA__*/null", {"speciesList": species, "presentCounts": present}),
                       ("/*__IL_STATS__*/null", stats), ("/*__IL_ORDER__*/null", order),
                       ("/*__WDPA_SITES__*/null", wdpa_sites(gdf))):
        assert token in html, token
        html = html.replace(token, json.dumps(obj, ensure_ascii=False), 1)
    OUT.write_text(html, encoding="utf-8")
    (OUT.parent / ".nojekyll").touch()
    print(f"Yazıldı: {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
