# Pipeline v2 — ne değişti, ne çalıştırılacak

## Pod'da çalıştırma sırası
```bash
# 1) Eski tüm-takson tür kırılımını yedekle (kuş-only yeniden çekilecek)
mv data/raw/gbif_il_tur_kirilimi.csv data/raw/gbif_il_tur_kirilimi_ALL_TAXA.csv
# 2) .env'e ekle:  XENO_CANTO_KEY=...   (https://xeno-canto.org/account)
# 3) Hepsi:
./run_pipeline.sh            # Xeno-canto key yoksa: SKIP_XC=1 ./run_pipeline.sh
```
Sadece yeni/düzeltilmiş parçalar için:
```bash
python fetch_gbif_monthly.py        # aylık kuş kaydı (~5 dk)
python fetch_xenocanto.py           # ses kayıtları
rm data/raw/yol_agi_il.csv && python fetch_covariates.py --only roads   # yol verisini baştan
python fetch_covariates.py --only pop
python aggregate.py
```

## Düzeltmeler
| Dosya | Sorun | Çözüm |
|---|---|---|
| fetch_covariates.py | Yol uzunluğu EPSG:3857'de ölçülüyordu (~%29 şişik) | İlin UTM diliminde ölçülüyor |
| fetch_covariates.py | Alan = derece²·111² (~%29 şişik) | Eşit-alan EPSG:6933 (Türkiye toplamı 781.054 km², gerçek ~783.000) |
| fetch_covariates.py | Nüfus "yoğunluğu" = raster ortalaması (kişi/piksel) | toplam nüfus / km² |
| fetch_covariates.py | Yol sonuçları 0.1–0.5 km çıkıyordu (60 il) | <0.02 km/km² "yarım yanıt" sayılıp başka aynada yeniden denenir; sonda şüpheli iller listelenir |
| fetch_covariates.py | WDPA hiç hesaplanmıyordu | Protected Planet'ten indirilen dosyadan il kesişimi (üst üste binenler tek sayılır) |
| fetch_ebird.py / config.py | "K.Maraş" ≠ "Kahramanmaraş" → 82. satır | config.NAME_FIX, hem eBird hem aggregate'te uygulanır |
| fetch_gbif.py | Tür kırılımı tek sayfa (2000'de kesilebilir) + kuş olmayanlar (buğday, kaplumbağa…) | facetOffset ile sayfalama; BIRDS_ONLY=True ile taxonKey=212 (Aves); ayrıca gbif_kus_kayit sütunu |
| tüm fetch_* | requests'te timeout yoktu | REQUEST_TIMEOUT=30 |
| aggregate.py | il adı uyuşmazlığı sessizdi | uyarı basar, 81 satır kontrolü yapar |
| requirements.txt | ebird-api kullanılmıyordu | çıkarıldı |

## Yeni
* `fetch_gbif_monthly.py` → `data/raw/gbif_il_aylik.csv` (il × ay kuş kaydı; göç/mevsimsel sessizlik)
* `fetch_xenocanto.py` → `xenocanto_il_ozet.csv`, `xenocanto_il_tur.csv` (ses kaydı dağılımı; koordinatsız kayıtları da sayar)

## Doğrulanmadı (dikkat)
* Xeno-canto API v3: `key`, `page`, `per_page` ve `cnt:"Turkey"` sorgusu belgelerden/okuma notlarından
  hatırlanarak yazıldı; xeno-canto.org erişimime kapalıydı. Script ilk kaydın alan adlarını basar;
  `lat/lon/gen/sp` farklıysa dosya başındaki `FIELD_*` sabitlerini düzelt. `per_page` 500'ü reddederse düşür.
* Bu ortamdan GBIF/Overpass/Xeno-canto'ya erişemediğim için ağ çağıran kısımlar çalıştırılmadı;
  alan/uzunluk/WDPA/eşleme/birleştirme mantığı sentetik verilerle test edildi.
* GBIF `facetOffset` pygbif'te destekleniyor; gerçek yanıtı bir ilde kontrol et (Muğla'da 1000+ tür bekleniyor).

## Sonradan eklenenler (rank / resolve / site)
| Dosya | Bulgu | Çözüm |
|---|---|---|
| analyze_missing_species.py | `touches()` ile komşu bulma: 81 ilin **53'ünde komşu sayısı 0** çıkmıştı (`eksik_turler_il.csv`), komşu analizi fiilen çalışmıyordu | `config.neighbors()` (≈2 km toleranslı kesişim): ortalama 4,9 komşu, hiçbir ilde 0 yok. Çıktıyı yeniden üret. |
| analyze/rank | Hiç tür satırı olmayan il sonuçtan sessizce düşerdi (en sessiz iller!) | Tüm iller GeoJSON'dan alınır, boş olanlar için uyarı |
| tüm GBIF çekimi | **20 ilde tür sayısı tam 2000** = eski facet sınırı; listeler kesilmişti | Sayfalama (fetch_gbif.py) |
| rank_missing_species.py | Yüklediğin sürüm eskiydi (isimleri kendi çözüyordu), resolve_*.py ise ID dosyası bekliyordu | ID-only sürüm; komşu sütunları (`komsuda_kayitli`) ve `top_species_id.csv` eklendi |
| resolve_species_names.py | Önbellek `f"{key},{name}"` ile yazılıyordu: "Parus major Linnaeus, 1758" virgülü yarıda kesilip devam edince dosyayı bozar. Ayrıca sadece *eksik* türleri çözüyordu; her ilde kayıtlı yaygın türlerin (Parus major) adı hiç çözülmüyordu | csv modülü; eksik + top türler birlikte; `class`/`canonical`/`family`; `--vernacular` ile EN + TR halk adı |
| (yeni) build_site.py | HTML'e veri elle gömülüyordu | `site/site_template.html` + pipeline çıktıları -> `site/index.html`. Mevcut v8 verisiyle birebir aynı çıktıyı verdiği test edildi. |

Site artık şu zinciri çalıştırınca kendini yeniler: `./run_pipeline.sh` (ya da son iki adım: `python aggregate.py && python build_site.py`).
Türkçe halk adı bulunan türlerde dropdown Türkçe modda o adı gösterir, yoksa İngilizce.

## v9 — Göç sekmesi
- site_template.html: yeni "Göç" sekmesi (Trakya–Boğaziçi ve Doğu/Borçka koridorları, sonbahar/ilkbahar animasyonu, tür çipleri → haritada o türün kayıt dağılımı, rota altında veri sessizliği).
- Koridorlar ve tür listeleri ŞEMATİK/TASLAK (elle çizildi, ölçülmüş iz değil). Gerçek hareket için ay×il tür verisi gerekir (fetch_gbif_monthly.py / GBIF download).

## Kuş kartı verisi
- `fetch_species_cards.py`: Wikipedia özeti (TR/EN/FR/ES), fotoğraf+kaynak, IUCN durumu, iNaturalist TR/FR/ES ad önerileri -> data/processed/species_cards.json.
- Sıra: run_pipeline.sh -> python fetch_species_cards.py -> python build_site.py. build_site.py kartları siteye gömer (arayüz v10'da).

## v10
- Site: açılış ekranı (4 dil), "Hakkında" sekmesi, sergi modu (45 sn boşta kalınca otomatik tur; ?idle=SANIYE, ?nointro), okunurluk (daha büyük yazı/kontrast), kuş kartı ("Tanış"), Google Form bağlandı.
- Çok dilli isimler: reference/bird_names_multilang.csv (latin,tr,en,fr,es) -> build_site.py okur; check_names_dictionary.py eksikleri names_missing.csv'ye yazar.
- Hata düzeltmesi: haritadaki il sayımı göç haritası kopyalarını da sayıyordu (legend sayıları 2 katı çıkıyordu).

## v11–v12
- Yeni "Koruma alanları" sekmesi: resmi sayı (DKMP 695) / Protected Planet'te herkese açık (18) / kısıtlı (4.251) + herkese açık alanların haritası ve listesi. Konsept: verinin kendisi eksik.
- build_site.py: data/cache/wdpa_tur.* içindeki herkese açık alanları sekmeye gömer (dosya yoksa noktasız çıkar).
- Not: Protected Planet Türkiye verisinin çoğunu kısıtlıyor; fetch_covariates.py'nin "korunan alan oranı" bu veriyle anlamlı DEĞİL, site kullanmıyor.
- Almanca (DE) dil seçeneği eklendi. Kuş adları için sözlüğe isteğe bağlı `de` sütunu (reference/bird_names_multilang.csv).
