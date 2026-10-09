"""
Kuş kartı verisi: tür başına kısa tanım (Wikipedia TR/EN/FR/ES), fotoğraf (+kaynak/lisans),
koruma durumu ve iNaturalist'ten TR/FR/ES halk adları.

Girdi : data/processed/site_species.csv   (build_site.py yazar: speciesKey, latin, en)
Çıktı : data/processed/species_cards.json        (build_site.py bunu siteye gömer)
        data/processed/species_names_suggested.csv  (latin, tr, fr, es, de — Wikipedia başlıkları / iNaturalist; 
                                                     dil sözlüğünü doldururken YARDIMCI, kontrol et!)
Önbellek: data/cache/species_cards_cache.json  (kaldığı yerden devam eder)

Sıra:  ./run_pipeline.sh   ->  python fetch_species_cards.py  ->  python build_site.py
(build_site.py ilk koşuda site_species.csv'yi yazar; kartlar sonraki build'e girer.)

Kullanım:  python fetch_species_cards.py [--limit 20] [--langs tr,en,fr,es,de] [--names]
Not: Wikipedia ve iNaturalist yanıt alanları bu ortamda canlı doğrulanamadı; ilk koşuda
     --limit 5 ile deneyip data/processed/species_cards.json'a bak.
"""
import argparse
import json
import time
from urllib.parse import quote

import pandas as pd
import requests
from tqdm import tqdm

from config import DATA_DIR, PROCESSED_DIR, REQUEST_TIMEOUT

UA = {"User-Agent": "EcologyOfMissingData/1.0 (MozFest 2026 installation; eceozen23@gmail.com)"}
CACHE = DATA_DIR / "cache" / "species_cards_cache.json"
WIKI = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
INAT = "https://api.inaturalist.org/v1"
EXTRACT_MAX = 420          # siteye gömülen özet uzunluğu (karakter)
WIKI_DELAY, INAT_DELAY = 0.1, 1.0


def get_json(url, params=None):
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=REQUEST_TIMEOUT)
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1)); continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
    return None


def trim(text, n=EXTRACT_MAX):
    text = " ".join((text or "").split())
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def wiki_card(latin, lang):
    j = get_json(WIKI.format(lang=lang, title=quote(latin.replace(" ", "_"))))
    if not j or j.get("type") == "disambiguation" or not j.get("extract"):
        return None
    return {
        "title": j.get("title"),
        "extract": trim(j["extract"]),
        "url": (j.get("content_urls") or {}).get("desktop", {}).get("page"),
        "thumb": (j.get("thumbnail") or {}).get("source"),
    }


def inat_taxon(latin):
    j = get_json(f"{INAT}/taxa", {"q": latin, "rank": "species", "per_page": 5, "locale": "en"})
    time.sleep(INAT_DELAY)
    for t in (j or {}).get("results", []):
        if (t.get("name") or "").lower() == latin.lower():
            return t
    return None


def iucn_status(t):
    for cs in t.get("conservation_statuses") or []:
        if not cs.get("place") and "iucn" in str(cs.get("authority", "")).lower():
            return cs.get("status")
    cs = t.get("conservation_status") or {}
    if cs and not cs.get("place") and "iucn" in str(cs.get("authority", "")).lower():
        return cs.get("status")
    return None


def build_card(latin, langs, with_names):
    card = {"wiki": {}}
    for lang in langs:
        w = wiki_card(latin, lang)
        time.sleep(WIKI_DELAY)
        if w:
            card["wiki"][lang] = {k: w[k] for k in ("title", "extract", "url") if w.get(k)}
            if w.get("thumb") and "photo" not in card:
                card["photo"] = {"url": w["thumb"], "credit": f"Wikipedia ({lang}) / Wikimedia Commons",
                                 "page": w.get("url")}
    t = inat_taxon(latin)
    if t:
        card["inat_id"] = t.get("id")
        st = iucn_status(t)
        if st:
            card["iucn"] = st
        dp = t.get("default_photo") or {}
        if dp.get("medium_url") and "photo" not in card:
            card["photo"] = {"url": dp["medium_url"], "credit": dp.get("attribution") or "iNaturalist",
                             "license": dp.get("license_code"), "page": f"https://www.inaturalist.org/taxa/{t.get('id')}"}
        if with_names:
            names = {}
            for lang in ("tr", "fr", "es", "de"):
                j = get_json(f"{INAT}/taxa/{t['id']}", {"locale": lang})
                time.sleep(INAT_DELAY)
                res = (j or {}).get("results") or []
                n = res[0].get("preferred_common_name") if res else None
                if n:
                    names[lang] = n
            card["names"] = names
    return card


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="sadece ilk N tür (deneme)")
    ap.add_argument("--langs", default="tr,en,fr,es,de")
    ap.add_argument("--names", action="store_true", help="iNaturalist TR/FR/ES/DE halk adı önerilerini de çek (yavaş; Wikipedia başlıkları zaten ad olarak kullanılır)")
    args = ap.parse_args()
    langs = [l for l in args.langs.split(",") if l]

    src = PROCESSED_DIR / "site_species.csv"
    if not src.exists():
        raise SystemExit(f"{src} yok — önce `python build_site.py` bir kez çalışsın (tür listesini yazar).")
    sp = pd.read_csv(src)
    if args.limit:
        sp = sp.head(args.limit)

    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    for latin in tqdm(sp["latin"].tolist(), desc="Kuş kartları"):
        if latin in cache:
            continue
        cache[latin] = build_card(latin, langs, with_names=args.names)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    cards = {l: cache[l] for l in sp["latin"] if l in cache}
    (PROCESSED_DIR / "species_cards.json").write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
    def nm(l, c, lg):
        v = c.get("names", {}).get(lg, "")
        w = c.get("wiki", {}).get(lg, {}).get("title", "")
        return v or (w if w and w.lower() != l.lower() else "")
    rows = [{"latin": l, "tr": nm(l, c, "tr"), "fr": nm(l, c, "fr"), "es": nm(l, c, "es"), "de": nm(l, c, "de")}
            for l, c in cards.items()]
    pd.DataFrame(rows).to_csv(PROCESSED_DIR / "species_names_suggested.csv", index=False, encoding="utf-8-sig")

    n = len(cards)
    print(f"\n{n} tür: Wikipedia özeti olan -> " + ", ".join(
        f"{lg}:{sum(1 for c in cards.values() if lg in c['wiki'])}" for lg in langs)
        + f" | fotoğraf: {sum(1 for c in cards.values() if 'photo' in c)} | IUCN: {sum(1 for c in cards.values() if 'iucn' in c)}")
    print("Şimdi: python build_site.py   (kartlar siteye girer)")


if __name__ == "__main__":
    main()
