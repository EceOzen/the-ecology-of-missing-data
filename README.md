# Ecology of Missing Data — Veri Toplama Pipeline'ı

Türkiye il bazında (81 il) biyoçeşitlilik gözlem yoğunluğu + bağlamsal (açıklayıcı)
katmanları çeken modüler script seti.

## Kurulum

```bash
pip install -r requirements.txt
```

### API key / hesap gereksinimleri

| Kaynak | Hesap | Key alma |
|---|---|---|
| eBird | Gerekli | https://ebird.org/api/keygen (anında) |
| GBIF | Sadece toplu indirme için gerekli, arama için gerekmiyor | https://www.gbif.org/user/profile |
| iNaturalist | Gerekmiyor (public API) | — |
| Copernicus Data Space | Gerekli (WDPA/CLC/raster işlemleri için değil ama ileride Sentinel katmanı eklenirse) | https://dataspace.copernicus.eu |
| Protected Planet (WDPA) | Token gerekli | https://api.protectedplanet.net/request |
| WorldPop | Gerekmiyor (doğrudan raster indirme) | https://www.worldpop.org |
| OSM (OSMnx üzerinden Overpass) | Gerekmiyor | — |

`.env` dosyası oluşturup key'leri oraya koy (bkz. `config.py`).

## İl sınırları (boundary) dosyası

Script'ler bir il-bazlı GeoJSON bekliyor (81 feature, her birinde `il_adi` ve
mümkünse `il_kodu` (plaka no) alanı olmalı). Böyle bir dosyan yoksa:

- https://github.com/cihadturhan/tr-geojson (il bazlı, iyi test edilmiş)
- veya kendi prototipindeki (`ecology-of-missing-data.html`) SVG'nin
  kaynağı olan Natural Earth/geo-countries setinden türetilebilir.

Dosyayı `data/boundaries/turkey_iller.geojson` olarak koy, `config.py`
içindeki `BOUNDARY_PATH` bunu gösteriyor.

## Çalıştırma sırası

```bash
python fetch_ebird.py
python fetch_gbif.py
python fetch_inaturalist.py
python fetch_covariates.py     # WDPA + nüfus yoğunluğu + yol ağı
python aggregate.py            # hepsini tek CSV'de birleştirir
```

Her fetch script'i `data/raw/<kaynak>.csv` üretir; `aggregate.py` bunları
il bazında tek bir `data/processed/il_summary.csv` dosyasında birleştirir —
bu dosya doğrudan harita/görselleştirme katmanının girdisi olacak.

## Notlar

- eBird ve GBIF rate limit'e takılmamak için istekler arasında bekleme
  (`RATE_LIMIT_DELAY`) var, 81 il için tam çekim ~10-20 dk sürebilir.
- GBIF sorguları WKT polygon ile yapılıyor; çok karmaşık il sınırları
  (çok adacıklı) `simplify_tolerance` ile basitleştiriliyor — kıyı
  illerinde (Muğla, Balıkesir vb.) bunu gözle kontrol et, aşırı
  basitleştirme kıyı gözlemlerini dışarıda bırakabilir.
- WDPA ve WorldPop büyük dosyalar indiriyor (ilk çalıştırmada), sonraki
  çalıştırmalarda cache'den okunuyor.
- OSM yol ağı çekimi (OSMnx) il başına birkaç dakika sürebilir, 81 il
  toplamda saatler alabilir — istersen `covariates` script'inde sadece
  bir alt küme ille test et.
