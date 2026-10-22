"""Sessizlik endeksi (il bazlı)  ->  data/processed/il_silence.csv

"Yok" verisi doğrudan ölçülemez; iki şeyi ölçeriz:
  1) GÖZLEM AÇIĞI (effort gap): kayıtlar insan üretimi. log(kayıt) ~ log(nüfus) + log(yüzölçümü) [+ log(yol yoğunluğu)]
     modelinin artığı (z). Negatif = nüfus/erişim/alana göre BEKLENENDEN AZ kayıt.
  2) ENVANTER TAMLIĞI: il × tür matrisinden Chao-Jost örnekleme tamlığı (sample coverage) ve Chao1 tür tamlığı.
     Düşük = çok sayıda tür tek-iki kayıtla görülmüş, envanter eksik.
sessizlik_endeksi (0-100) = iki bileşenin yüzdelik sıra ortalaması (yüksek = daha sessiz).
Girdi:  data/processed/il_summary.csv, data/raw/gbif_il_tur_kirilimi.csv, (opsiyonel) data/raw/species_name_lookup.csv
Not: Bu bir GÖZLEM ÇABASI endeksidir; habitat/ekolojik beklenti (beslenme alanları vb.) ayrı bir sonraki katmandır."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).parent
RAW, PROC = BASE / "data" / "raw", BASE / "data" / "processed"


def read(p):
    return pd.read_csv(p, sep=None, engine="python", encoding="utf-8-sig")


def pct_rank(x):
    return pd.Series(x).rank(pct=True).to_numpy() * 100


def chao_coverage(counts):
    c = np.asarray([v for v in counts if v > 0], dtype=float)
    n, f1, f2 = c.sum(), (c == 1).sum(), (c == 2).sum()
    if n < 2:
        return np.nan, len(c), np.nan
    if f2 > 0:
        cov = 1 - f1 / n * ((n - 1) * f1 / ((n - 1) * f1 + 2 * f2))
        s_est = len(c) + f1 * f1 / (2 * f2)
    else:
        cov = 1 - f1 / n * ((n - 1) * max(f1 - 1, 0) / ((n - 1) * max(f1 - 1, 0) + 2))
        s_est = len(c) + f1 * max(f1 - 1, 0) / 2
    return cov, len(c), len(c) / s_est


def main():
    s = read(PROC / "il_summary.csv")
    need = ["il_adi", "gbif_toplam_kayit", "alan_km2", "tahmini_nufus"]
    miss = [c for c in need if c not in s.columns]
    if miss:
        sys.exit(f"il_summary.csv'de eksik sütun: {miss}  (mevcut: {list(s.columns)})")
    s = s.copy()
    for c in need[1:]:
        s[c] = pd.to_numeric(s[c], errors="coerce")
    y = np.log1p(s["gbif_toplam_kayit"].to_numpy())
    cols, names = [np.ones(len(s))], ["sabit"]
    for c, nm in (("tahmini_nufus", "log_nufus"), ("alan_km2", "log_alan")):
        cols.append(np.log(s[c].clip(lower=1)).to_numpy()); names.append(nm)
    yol = "yol_yogunlugu_km_per_km2"
    if yol in s.columns and pd.to_numeric(s[yol], errors="coerce").gt(0.02).mean() > 0.9:
        cols.append(np.log(pd.to_numeric(s[yol], errors="coerce").clip(lower=0.02)).to_numpy()); names.append("log_yol")
    else:
        print("NOT: yol yoğunluğu yok/şüpheli — modelde kullanılmadı.")
    X = np.column_stack(cols)
    ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
    beta, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None)
    pred = X @ beta
    res = y - pred
    r2 = 1 - np.nanvar(res[ok]) / np.nanvar(y[ok])
    print("Model:", dict(zip(names, beta.round(2))), f"R²={r2:.2f}")
    s["beklenen_kayit"] = np.nan_to_num(np.expm1(pred)).round().astype(int)
    s["efor_z"] = (res - np.nanmean(res[ok])) / np.nanstd(res[ok])

    m = read(RAW / "gbif_il_tur_kirilimi.csv")
    lk = RAW / "species_name_lookup.csv"
    if lk.exists():
        nm = read(lk)
        if "class" in nm.columns:
            birds = set(nm.loc[nm["class"] == "Aves", "speciesKey"].astype(str))
            if birds:
                m = m[m["speciesKey"].astype(str).isin(birds)]
    rows = []
    for il, g in m.groupby("il_adi"):
        cov, so, comp = chao_coverage(g["kayit_sayisi"].to_numpy())
        rows.append({"il_adi": il, "envanter_tamligi": cov, "tur_sayisi": so, "tur_tamligi": comp})
    s = s.merge(pd.DataFrame(rows), on="il_adi", how="left")
    a = pct_rank(-s["efor_z"].fillna(0))            # beklenenden az kayıt -> yüksek
    b = pct_rank(1 - s["envanter_tamligi"].fillna(s["envanter_tamligi"].median()))
    s["sessizlik_endeksi"] = ((a + b) / 2).round(0).astype(int)
    out = s[["il_adi", "gbif_toplam_kayit", "beklenen_kayit", "efor_z", "envanter_tamligi", "tur_tamligi",
             "sessizlik_endeksi"]].sort_values("sessizlik_endeksi", ascending=False)
    out[["efor_z", "envanter_tamligi", "tur_tamligi"]] = out[["efor_z", "envanter_tamligi", "tur_tamligi"]].round(3)
    out.to_csv(PROC / "il_silence.csv", index=False, encoding="utf-8-sig")
    print("\nEn sessiz 10 il:\n", out.head(10).to_string(index=False))
    print("\nEn az sessiz 5 il:\n", out.tail(5).to_string(index=False))
    print(f"\nYazıldı: {PROC / 'il_silence.csv'}  ->  sonra: python build_site.py")


if __name__ == "__main__":
    main()
