"""
Eksik tür (detection gap) analizi.

"Hiç kayıt yok" (o ilde toplam gözlem az) ile "orada olması beklenirken
kaydedilmemiş tür" farklı şeyler — ikincisi asıl "altyapısal sessizlik"
argümanı için kanıt. Bu script iki tamamlayıcı yöntem kullanıyor:

  1) ULUSAL REFERANS: Türkiye genelinde GBIF'te kayıtlı tüm türlerin
     birleşim kümesi çıkarılıyor. Her il için bu kümede olup o ilde hiç
     kaydı olmayan türler = "potansiyel eksik".
     Sınırlama: bazı türler o ile gerçekten hiç uğramıyor olabilir
     (yayılış alanı dışında) — bu durumda "eksik" değil "gerçekten yok".

  2) KOMŞU İL KARŞILAŞTIRMASI: Aynı coğrafi bölgedeki illerde kaydedilmiş
     ama bu ilde kaydedilmemiş türler — çevresinde varlığı kanıtlanmış bir
     türün burada yokluğu, yayılış alanı dışında kalma ihtimalini azaltır,
     daha güçlü bir "tespit boşluğu" sinyali.

Girdi: data/raw/gbif_il_tur_kirilimi.csv (fetch_gbif.py'nin ürettiği)
       + data/boundaries/turkey_iller.geojson (komşuluk için, opsiyonel)
Çıktı: data/processed/eksik_turler_il.csv
"""
import pandas as pd

from config import RAW_DIR, PROCESSED_DIR, load_boundaries, neighbors as compute_neighbors


def load_species_matrix():
    path = RAW_DIR / "gbif_il_tur_kirilimi.csv"
    if not path.exists():
        raise SystemExit(
            f"{path} bulunamadı — önce güncellenmiş fetch_gbif.py'yi çalıştır "
            "(tür kırılımı çekimi ekli sürüm)."
        )
    df = pd.read_csv(path)
    if df.empty:
        raise SystemExit(
            f"{path} boş. GBIF sorgularının gerçekten sonuç döndürüp döndürmediğini "
            "kontrol et (WKT geometrisi, il_adi eşleşmesi vb.)."
        )
    return df


def national_reference_gap(species_df):
    """Yöntem 1: ulusal tür havuzu - il'in kendi türleri = eksik."""
    all_species = set(species_df["speciesKey"].unique())
    rows = []
    # hiç tür satırı olmayan (tamamen sessiz / çekimi başarısız) iller de listelensin
    try:
        all_il = sorted(set(load_boundaries()["il_adi"]) | set(species_df["il_adi"]))
    except Exception:
        all_il = sorted(species_df["il_adi"].unique())
    by_il = {il: set(g["speciesKey"]) for il, g in species_df.groupby("il_adi")}
    for il in all_il:
        il_species = by_il.get(il, set())
        eksik = all_species - il_species
        rows.append({
            "il_adi": il,
            "ilde_gorulen_tur_sayisi": len(il_species),
            "ulusal_tur_havuzu": len(all_species),
            "ulusal_referansa_gore_eksik_tur_sayisi": len(eksik),
            "eksik_tur_orani": round(100 * len(eksik) / len(all_species), 1),
        })
    return pd.DataFrame(rows), all_species


def find_neighbors(boundaries_gdf, name_field="il_adi"):
    """Her il için komşu illerin listesi (toleranslı kesişim; bkz. config.neighbors)."""
    return compute_neighbors(boundaries_gdf)


def neighbor_comparison_gap(species_df, neighbors):
    """Yöntem 2: komşu illerde görülüp bu ilde görülmeyen türler."""
    il_species = {il: set(grp["speciesKey"]) for il, grp in species_df.groupby("il_adi")}
    rows = []
    for il in neighbors:
        my_species = il_species.get(il, set())
        neighbor_names = neighbors.get(il, [])
        neighbor_species = set()
        for n in neighbor_names:
            neighbor_species |= il_species.get(n, set())
        eksik_komsuya_gore = neighbor_species - my_species
        rows.append({
            "il_adi": il,
            "komsu_il_sayisi": len(neighbor_names),
            "komsularda_gorulup_burada_gorulmeyen_tur_sayisi": len(eksik_komsuya_gore),
        })
    return pd.DataFrame(rows)


def main():
    species_df = load_species_matrix()

    national_df, all_species = national_reference_gap(species_df)
    print(f"Ulusal tür havuzu (GBIF, tüm iller birleşimi): {len(all_species)} tür")
    print("\nUlusal referansa göre en yüksek 'eksik tür oranı' olan 5 il:")
    print(national_df.nlargest(5, "eksik_tur_orani")[
        ["il_adi", "ilde_gorulen_tur_sayisi", "eksik_tur_orani"]
    ].to_string(index=False))

    try:
        boundaries = load_boundaries()
        neighbors = find_neighbors(boundaries)
        neighbor_df = neighbor_comparison_gap(species_df, neighbors)
        result = national_df.merge(neighbor_df, on="il_adi", how="left")
        print("\nKomşu karşılaştırmasına göre en yüksek boşluk olan 5 il:")
        print(neighbor_df.nlargest(5, "komsularda_gorulup_burada_gorulmeyen_tur_sayisi")
              .to_string(index=False))
    except Exception as e:
        print(f"Uyarı: komşu il analizi atlandı ({e}) — sadece ulusal referans kullanılıyor.")
        result = national_df

    out_path = PROCESSED_DIR / "eksik_turler_il.csv"
    result.to_csv(out_path, index=False)
    print(f"\nKaydedildi: {out_path}")
    print(
        "\nNOT: Bu iki yöntem de 'gerçek yokluk' ile 'tespit edilmemiş varlık'ı "
        "kesin ayıramıyor. Daha güçlü bir kanıt istersen IUCN/BirdLife yayılış "
        "alanı poligonlarını (range maps) devreye sokup 'türün yayılış alanı "
        "bu ili kapsıyor mu' filtresini ekleyebiliriz — bu, IUCN Red List "
        "spatial data için ayrı bir kayıt ve büyük shapefile indirmesi gerektirir."
    )


if __name__ == "__main__":
    main()
