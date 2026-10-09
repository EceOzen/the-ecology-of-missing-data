"""
Tüm raw/*.csv dosyalarını il_adi üzerinden birleştirip data/processed/il_summary.csv üretir
(sitenin il istatistikleri bu dosyadan beslenir).

v2: korunan alan, Xeno-canto ve kuş-kaydı sütunları eklendi; il adı eşleşmeyen satırlar
(örn. eBird'ün "K.Maraş"ı) artık sessizce 82. satıra dönüşmüyor, uyarı basılıyor.
"""
import pandas as pd
import numpy as np

from config import RAW_DIR, PROCESSED_DIR, fix_name, load_boundaries


def safe_read(path):
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if "il_adi" in df.columns:
        df["il_adi"] = df["il_adi"].map(fix_name)
    return df


def main():
    sources = {
        "ebird": safe_read(RAW_DIR / "ebird_il_ozet.csv"),
        "gbif": safe_read(RAW_DIR / "gbif_il_ozet.csv"),
        "inat": safe_read(RAW_DIR / "inaturalist_il_ozet.csv"),
        "nufus": safe_read(RAW_DIR / "nufus_yogunlugu_il.csv"),
        "yol": safe_read(RAW_DIR / "yol_agi_il.csv"),
        "korunan": safe_read(RAW_DIR / "korunan_alan_il.csv"),
        "xc": safe_read(RAW_DIR / "xenocanto_il_ozet.csv"),
    }
    frames = {k: v for k, v in sources.items() if v is not None}
    if not frames:
        raise SystemExit("Hiçbir raw veri bulunamadı — önce fetch_*.py script'lerini çalıştır.")

    # GeoJSON'daki il adları referans: kaynaklar bunlarla eşleşmeli
    try:
        ref = set(load_boundaries()["il_adi"])
    except Exception:
        ref = None
    if ref:
        for k, f in frames.items():
            stray = set(f["il_adi"]) - ref
            missing = ref - set(f["il_adi"])
            if stray:
                print(f"UYARI [{k}]: GeoJSON'da olmayan il adları: {sorted(stray)} -> config.NAME_FIX'e ekle")
            if missing:
                print(f"UYARI [{k}]: {len(missing)} il eksik: {sorted(missing)[:6]}{' ...' if len(missing) > 6 else ''}")

    items = list(frames.values())
    df = items[0]
    for f in items[1:]:
        df = df.merge(f, on="il_adi", how="outer")

    if "gbif_toplam_kayit" in df.columns:
        df["log_gbif_kayit"] = np.log1p(df["gbif_toplam_kayit"].fillna(0))
        if "alan_km2" in df.columns:
            df["gbif_kayit_per_100km2"] = (df["gbif_toplam_kayit"] / df["alan_km2"] * 100).round(1)
    if "xc_kayit" in df.columns and "gbif_kus_kayit" in df.columns:
        # ses kaydı / yazılı kuş kaydı: düşükse "duyulmuyor, sadece yazılıyor"
        df["xc_per_1000_kus_kayit"] = (df["xc_kayit"] / df["gbif_kus_kayit"] * 1000).round(2)

    if "gbif_toplam_kayit" in df.columns:
        df = df.sort_values("gbif_toplam_kayit", ascending=False)

    out_path = PROCESSED_DIR / "il_summary.csv"
    df.to_csv(out_path, index=False)
    print(f"Kaydedildi: {out_path} ({len(df)} satır, {len(df.columns)} sütun) — 81 olmalı")
    if len(df) != 81:
        print("UYARI: satır sayısı 81 değil, yukarıdaki il adı uyarılarına bak.")

    if "gbif_toplam_kayit" in df.columns:
        print("\nEn yoğun 5 il:")
        print(df.nlargest(5, "gbif_toplam_kayit")[["il_adi", "gbif_toplam_kayit"]].to_string(index=False))
        print("\nEn sessiz 5 il:")
        print(df.nsmallest(5, "gbif_toplam_kayit")[["il_adi", "gbif_toplam_kayit"]].to_string(index=False))

    # hızlı sağlık kontrolü: yol verisi
    if "yol_yogunlugu_km_per_km2" in df.columns:
        low = df[df["yol_yogunlugu_km_per_km2"] < 0.02]["il_adi"].tolist()
        if low:
            print(f"\nUYARI: {len(low)} ilde yol yoğunluğu şüpheli düşük: {low[:8]}")


if __name__ == "__main__":
    main()
