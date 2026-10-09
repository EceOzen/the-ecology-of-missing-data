"""
"Hangi tür, nerede eksik" — ID bazlı, hızlı adım (saniyeler sürer, GBIF'e istek atmaz).

Ulusal olarak en çok kaydedilen TOP_N türü seçer; her il için bunlardan hiç kaydı olmayanları
listeler. İsim çözme AYRI adımdır (resolve_species_names.py), çünkü o tür başına istek atar.

v2:
  * Hiç tür satırı olmayan iller (tamamen sessiz ya da çekimi başarısız) artık atlanmıyor —
    önceki sürüm tam da en sessiz illeri sonuçtan düşürebiliyordu.
  * Her satıra komşu bilgisi eklendi: `komsu_sayisi`, `komsuda_kayitli` (bu türü kaç komşu il kaydetmiş).
    komsuda_kayitli > 0 olanlar "büyük olasılıkla kaydedilmemiş" (sitedeki kehribar katman) sinyalidir.
  * Ulusal TOP_N listesi ayrıca top_species_id.csv olarak yazılır (site için isim çözümü bunu da kullanır).

Girdi : data/raw/gbif_il_tur_kirilimi.csv  (+ data/boundaries/turkey_iller.geojson)
Çıktı : data/processed/eksik_turler_detay_id.csv   il_adi, speciesKey, ulusal_toplam_kayit, komsu_sayisi, komsuda_kayitli
        data/processed/top_species_id.csv          speciesKey, ulusal_toplam_kayit
"""
import pandas as pd

from config import RAW_DIR, PROCESSED_DIR, load_boundaries, neighbors as compute_neighbors

TOP_N = 300              # kuş-only çekimde bu sayı tüm yaygın kuşları kapsar
MAX_MISSING_PER_IL = 20  # her il için listelenecek en çarpıcı eksik sayısı


def main():
    path = RAW_DIR / "gbif_il_tur_kirilimi.csv"
    if not path.exists():
        raise SystemExit(f"{path} bulunamadı — önce fetch_gbif.py'yi çalıştır.")
    df = pd.read_csv(path)
    if df.empty:
        raise SystemExit(f"{path} boş.")

    totals = df.groupby("speciesKey")["kayit_sayisi"].sum().sort_values(ascending=False)
    top = totals.head(TOP_N)
    print(f"Ulusal olarak en çok kaydedilen {len(top)} tür seçildi "
          f"(en popüler: {top.iloc[0]:.0f} kayıt, en az: {top.iloc[-1]:.0f} kayıt).")
    top.rename("ulusal_toplam_kayit").reset_index().to_csv(PROCESSED_DIR / "top_species_id.csv", index=False)

    gdf = load_boundaries()
    all_il = sorted(set(gdf["il_adi"]) | set(df["il_adi"]))
    nb = compute_neighbors(gdf)
    il_species = {il: set(g["speciesKey"]) for il, g in df.groupby("il_adi")}
    empty = [il for il in all_il if il not in il_species]
    if empty:
        print(f"UYARI: {len(empty)} ilde hiç tür satırı yok (çekim başarısız ya da tamamen sessiz): {empty}")
    top_set = set(top.index)

    rows = []
    for il in all_il:
        mine = il_species.get(il, set())
        neigh = nb.get(il, [])
        for key in top_set - mine:
            rows.append({
                "il_adi": il, "speciesKey": key, "ulusal_toplam_kayit": int(top[key]),
                "komsu_sayisi": len(neigh),
                "komsuda_kayitli": sum(1 for n in neigh if key in il_species.get(n, set())),
            })
    out = pd.DataFrame(rows).sort_values(["il_adi", "ulusal_toplam_kayit"], ascending=[True, False])
    out = out.groupby("il_adi").head(MAX_MISSING_PER_IL)
    out_path = PROCESSED_DIR / "eksik_turler_detay_id.csv"
    out.to_csv(out_path, index=False)
    print(f"Kaydedildi: {out_path} ({len(out)} satır, {out['il_adi'].nunique()} il)")
    capped = (df.groupby("il_adi").size() >= 2000).sum()
    if capped:
        print(f"UYARI: {capped} ilde tür sayısı tam 2000 — eski facet sınırı. Güncel fetch_gbif.py ile yeniden çek.")


if __name__ == "__main__":
    main()
