#!/usr/bin/env bash
# Ecology of Missing Data - pipeline'ı baştan sona çalıştırır.
# Kullanım:  ./run_pipeline.sh            (hepsi)
#            SKIP_XC=1 ./run_pipeline.sh  (Xeno-canto key yoksa)
set -e
cd "$(dirname "$0")"

# Tüm çıktı (hata dahil) hem ekrana hem logs/ altına yazılır
mkdir -p logs
LOG="logs/pipeline_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
echo "Log: $LOG"

echo "== 1/12: Ön kontroller =="
[ -f ".env" ] || { echo "HATA: .env yok. EBIRD_API_KEY (ve ops. XENO_CANTO_KEY) içermeli."; exit 1; }
[ -f "data/boundaries/turkey_iller.geojson" ] || { echo "HATA: data/boundaries/turkey_iller.geojson yok."; exit 1; }
[ -f "data/cache/worldpop_tur.tif" ] || echo "UYARI: worldpop_tur.tif yok — nüfus adımı atlanacak."
ls data/cache/wdpa_tur.* >/dev/null 2>&1 || echo "UYARI: data/cache/wdpa_tur.* yok — korunan alan adımı atlanacak."
if [ -f data/raw/gbif_il_tur_kirilimi.csv ] && ! grep -q "BIRDS_ONLY=done" data/raw/.birds_marker 2>/dev/null; then
  echo "NOT: eski (tüm taksonlar) gbif_il_tur_kirilimi.csv varsa, kuş-only için silip yeniden çekmelisin:"
  echo "     mv data/raw/gbif_il_tur_kirilimi.csv data/raw/gbif_il_tur_kirilimi_ALL_TAXA.csv"
fi

echo "== 2/12: Bağımlılıklar =="
pip install -q -r requirements.txt

echo "== 3/12: eBird ==";            python fetch_ebird.py
echo "== 4/12: GBIF (özet + tür) =="; python fetch_gbif.py; mkdir -p data/raw && echo "BIRDS_ONLY=done" > data/raw/.birds_marker
echo "== 5/12: GBIF aylık ==";        python fetch_gbif_monthly.py
echo "== 6/12: iNaturalist ==";       python fetch_inaturalist.py
if [ -z "$SKIP_XC" ]; then
  echo "== 7/12: Xeno-canto ==";      python fetch_xenocanto.py
else
  echo "== 7/12: Xeno-canto atlandı (SKIP_XC) =="
fi
echo "== 8/12: Bağlamsal katmanlar (WDPA / WorldPop / OSM) =="; python fetch_covariates.py
echo "== 9/12: Eksik tür analizi ==";  python analyze_missing_species.py
echo "== 10/12: Eksik türler (ID) ==";  python rank_missing_species.py
echo "== 11/12: Tür isimleri ==";       python resolve_species_names.py --vernacular   # Türkçe/İngilizce halk adları; ~15-20 dk
echo "== 12/12: Birleştirme + site ==";  python aggregate.py && python build_site.py
echo "Çıktılar: site/index.html (yayına hazır), data/processed/il_summary.csv, eksik_turler_il.csv; data/raw/gbif_il_aylik.csv, xenocanto_*.csv"
