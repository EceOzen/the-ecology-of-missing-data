"""
Ortak konfigürasyon. Key'leri .env dosyasından okuyor.

.env örneği:
    EBIRD_API_KEY=xxxx
    WDPA_TOKEN=xxxx
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- API keys ---
EBIRD_API_KEY = os.environ.get("EBIRD_API_KEY", "")
WDPA_TOKEN = os.environ.get("WDPA_TOKEN", "")

# --- Yollar ---
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
BOUNDARY_PATH = DATA_DIR / "boundaries" / "turkey_iller.geojson"

for d in (RAW_DIR, PROCESSED_DIR, (DATA_DIR / "boundaries"), (DATA_DIR / "cache")):
    d.mkdir(parents=True, exist_ok=True)

# --- v2 eklemeleri ---
REQUEST_TIMEOUT = 30          # saniye; hiçbir istek sonsuza kadar beklemesin
BIRDS_ONLY = True             # GBIF tür kırılımı ve aylık kayıtlar sadece kuşlar (Aves, taxonKey=212)
BIRD_TAXON_KEY = 212
XENO_CANTO_KEY = os.environ.get("XENO_CANTO_KEY", "")   # https://xeno-canto.org/account
EQUAL_AREA_EPSG = 6933        # alan hesabı için eşit-alan projeksiyonu (EPSG:3857 alanı ~%30 şişirir)
# Kaynakların farklı yazdığı il adlarını GeoJSON'daki adlara eşler (aggregate'te çift satırı önler)
NAME_FIX = {"K.Maraş": "Kahramanmaraş"}

# --- Zaman aralığı ---
START_YEAR = 2010
END_YEAR = 2026

# --- Rate limiting ---
RATE_LIMIT_DELAY = 1.2  # saniye, art arda istekler arası

# --- Boundary sadeleştirme (GBIF WKT sorguları için) ---
SIMPLIFY_TOLERANCE = 0.01  # derece cinsinden, kıyı illerinde kontrol et

# --- İl sınırlarını okuyan yardımcı fonksiyon ---
def load_boundaries():
    import geopandas as gpd

    if not BOUNDARY_PATH.exists():
        raise FileNotFoundError(
            f"İl sınırları bulunamadı: {BOUNDARY_PATH}\n"
            "README.md'deki 'İl sınırları' bölümüne bak."
        )
    gdf = gpd.read_file(BOUNDARY_PATH)
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    # tüm script'ler il adını `il_adi` sütunundan okusun (cihadturhan GeoJSON'unda alan adı `name`)
    if "il_adi" not in gdf.columns and "name" in gdf.columns:
        gdf["il_adi"] = gdf["name"]
    return gdf


def neighbors(gdf, tol_deg=0.02):
    """
    İl komşuluğu: sınırı `tol_deg` (≈2 km) tolerans içinde kesen iller.
    ESKİ yöntem `geometry.touches()` basitleştirilmiş/çakışmayan sınırlarda neredeyse hiç komşu bulmuyordu
    (81 ilin 53'ünde 0 komşu çıkmıştı).
    """
    out = {}
    for _, il in gdf.iterrows():
        near = gdf[gdf.geometry.intersects(il.geometry.buffer(tol_deg)) & (gdf["il_adi"] != il["il_adi"])]
        out[il["il_adi"]] = sorted(near["il_adi"].tolist())
    return out


def fix_name(name):
    return NAME_FIX.get(name, name)
