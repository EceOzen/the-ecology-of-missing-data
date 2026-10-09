"""
speciesKey -> isim çözümü (ayrı adım: GBIF'e tür başına istek atar, ~1.2 sn/tür; resumable).

Çözülen anahtarlar: eksik_turler_detay_id.csv + top_species_id.csv birleşimi. (Eski sürüm sadece
"eksik" olanları çözüyordu: her ilde kaydı olan Parus major gibi türlerin adı hiç çözülmüyor,
site listesine giremiyordu.)

v2:
  * Önbellek CSV modülüyle yazılıyor. Eski sürümde "Parus major Linnaeus, 1758" gibi virgüllü adlar
    önbelleği bozuyordu (yarıda kesilip devam edince okuma hatası / kayık sütunlar).
  * Ek alanlar: canonical (yazar adı yok), class (Aves filtresi için), family.
  * --vernacular: İngilizce ve TÜRKÇE halk adlarını da çeker (tür başına +1 istek). Türkçe adlar
    GBIF'te eksik olabilir; olmayanlar boş kalır.  DOĞRULA: `language` değerleri 'eng' / 'tur'.

Çıktılar:
  data/raw/species_name_lookup.csv       speciesKey, tur_adi, canonical, class, family, vernacular_en, vernacular_tr
  data/processed/eksik_turler_detay.csv  (eksik_turler_detay_id.csv + tur_adi) — eski çıktıyla uyumlu
"""
import argparse
import csv
import time
import pandas as pd
from pygbif import species as gbif_species
from tqdm import tqdm

from config import RAW_DIR, PROCESSED_DIR, RATE_LIMIT_DELAY

LOOKUP = RAW_DIR / "species_name_lookup.csv"
COLS = ["speciesKey", "tur_adi", "canonical", "class", "family", "vernacular_en", "vernacular_tr"]


def load_cache():
    if not LOOKUP.exists():
        with open(LOOKUP, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(COLS)
        return {}
    try:
        df = pd.read_csv(LOOKUP)
    except Exception:
        # eski, virgülle bozulmuş önbellek: kurtarılabilen satırları al, yedekle
        bad = LOOKUP.with_suffix(".bak")
        LOOKUP.replace(bad)
        print(f"UYARI: önbellek okunamadı, {bad.name} olarak yedeklendi; baştan çözülecek.")
        with open(LOOKUP, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(COLS)
        return {}
    for c in COLS:
        if c not in df.columns:
            df[c] = ""
    df = df[COLS]
    df.to_csv(LOOKUP, index=False)                 # yeni sütun düzenine geçir
    return {int(r.speciesKey): r._asdict() for r in df.itertuples(index=False)}


def vernacular(key, lang):
    try:
        res = gbif_species.name_usage(key=int(key), data="vernacularNames").get("results", [])
    except Exception:
        return ""
    names = [r.get("vernacularName", "") for r in res if r.get("language") == lang]
    return names[0] if names else ""


def resolve(keys, with_vernacular):
    cache = load_cache()
    todo = [int(k) for k in keys if int(k) not in cache or (with_vernacular and not cache[int(k)]["vernacular_en"] and not cache[int(k)]["vernacular_tr"])]
    print(f"{len(cache)} tür önbellekte; {len(todo)} tür çözülecek.")
    for key in tqdm(todo, desc="Tür isimleri"):
        try:
            info = gbif_species.name_usage(key=key)
            row = {"speciesKey": key, "tur_adi": info.get("scientificName") or info.get("canonicalName") or f"key:{key}",
                   "canonical": info.get("canonicalName", ""), "class": info.get("class", ""), "family": info.get("family", "")}
        except Exception:
            row = {"speciesKey": key, "tur_adi": f"bilinmiyor (key:{key})", "canonical": "", "class": "", "family": ""}
        row["vernacular_en"] = vernacular(key, "eng") if with_vernacular else cache.get(key, {}).get("vernacular_en", "")
        row["vernacular_tr"] = vernacular(key, "tur") if with_vernacular else cache.get(key, {}).get("vernacular_tr", "")
        cache[key] = row
        with open(LOOKUP, "a", newline="", encoding="utf-8") as f:     # ya da cache'i baştan yazmak: burada append, çözülmüş satır eskisini geçersiz kılar
            csv.writer(f).writerow([row[c] for c in COLS])
        time.sleep(RATE_LIMIT_DELAY * (3 if with_vernacular else 1))
    # tekrarlanan anahtarlarda son satır geçerli
    df = pd.read_csv(LOOKUP).drop_duplicates("speciesKey", keep="last")
    df.to_csv(LOOKUP, index=False)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vernacular", action="store_true", help="İngilizce/Türkçe halk adlarını da çek")
    args = ap.parse_args()

    id_path = PROCESSED_DIR / "eksik_turler_detay_id.csv"
    top_path = PROCESSED_DIR / "top_species_id.csv"
    if not id_path.exists():
        raise SystemExit(f"{id_path} bulunamadı — önce rank_missing_species.py'yi çalıştır.")
    detay = pd.read_csv(id_path)
    keys = set(detay["speciesKey"].unique())
    if top_path.exists():
        keys |= set(pd.read_csv(top_path)["speciesKey"].unique())
    print(f"{len(keys)} benzersiz tür isimlendirilecek.")

    names = resolve(sorted(keys), args.vernacular)
    detay = detay.merge(names[["speciesKey", "tur_adi"]], on="speciesKey", how="left")
    out = PROCESSED_DIR / "eksik_turler_detay.csv"
    detay.to_csv(out, index=False)
    print(f"\nKaydedildi: {out}")
    non_bird = names[(names["class"].notna()) & (names["class"] != "") & (names["class"] != "Aves")]
    if len(non_bird):
        print(f"NOT: {len(non_bird)} tür kuş değil (class != Aves); site kuş-only süzer. Örnek: {non_bird['tur_adi'].head(3).tolist()}")


if __name__ == "__main__":
    main()
