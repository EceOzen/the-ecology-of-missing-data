"""
Çok dilli isim sözlüğünü (reference/bird_names_multilang.csv) sitedeki türlerle karşılaştırır.
Sözlükte OLMAYAN ya da dili boş kalan türleri data/processed/names_missing.csv'ye yazar.

Kullanım:  python check_names_dictionary.py   (build_site.py bir kez çalışmış olmalı: site_species.csv)
"""
import pandas as pd
from config import BASE_DIR, PROCESSED_DIR

sp = pd.read_csv(PROCESSED_DIR / "site_species.csv", dtype=str)
path = BASE_DIR / "reference" / "bird_names_multilang.csv"
d = pd.read_csv(path, dtype=str, encoding="utf-8-sig", sep=None, engine="python").fillna("")
d = d.drop_duplicates("latin").set_index("latin")
rows = []
for r in sp.itertuples():
    row = d.loc[r.latin] if r.latin in d.index else None
    miss = [l for l in ("tr", "fr", "es") if row is None or not str(row.get(l, "")).strip()]
    if miss:
        rows.append({"speciesKey": r.speciesKey, "latin": r.latin, "en": r.en, "eksik_diller": ",".join(miss),
                     "listede_yok": row is None})
out = pd.DataFrame(rows)
out.to_csv(PROCESSED_DIR / "names_missing.csv", index=False, encoding="utf-8-sig")
print(f"{len(sp)} tür | sözlükte eksik/boş: {len(out)} | tamamen yok: {int(out['listede_yok'].sum()) if len(out) else 0}")
print("-> data/processed/names_missing.csv")
