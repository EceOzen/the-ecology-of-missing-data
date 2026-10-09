"""Kuş seslerini yerel indirir -> site/sounds/<xcid>.mp3  (tarayıcı xeno-canto'dan çalamıyorsa çözüm).
Önce:  python fetch_sounds.py --limit 3     sonra:  python fetch_sounds.py     sonra:  python build_site.py
ffmpeg varsa kayıt 30 sn'ye kısaltılır (mono, 64k mp3); yoksa sadece mp3 kayıtlar olduğu gibi indirilir.
Site sekmesinde ses dosyaları site/sounds/ ile birlikte yayınlanmalı (klasörü index.html'in yanında tut)."""
import argparse, json, re, shutil, subprocess, sys, time
from pathlib import Path
import requests
from tqdm import tqdm

ROOT = Path(__file__).parent
CACHE = ROOT / "data" / "cache" / "xenocanto_tr.json"
SITE_SP = ROOT / "data" / "processed" / "site_species.csv"
OUT = ROOT / "site" / "sounds"
FFMPEG = shutil.which("ffmpeg")


def secs(s):
    m = re.match(r"(\d+):(\d+)", str(s or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else 0


def candidates(recs, latins):
    q = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
    by = {}
    for r in recs:
        lat = f"{r.get('gen','')} {r.get('sp','')}".strip()
        if lat not in latins or not r.get("file"):
            continue
        ext = str(r.get("file-name", "")).rsplit(".", 1)[-1].lower()
        if not FFMPEG and ext not in ("mp3", "mpeg"):
            continue
        n = secs(r.get("length"))
        if not FFMPEG and n > 90:
            continue
        key = (q.get(str(r.get("q", "")).strip().upper(), 5),
               0 if "song" in str(r.get("type", "")).lower() else 1,
               0 if 8 <= n <= 45 else 1, abs(n - 20))
        by.setdefault(lat, []).append((key, r))
    return {k: [r for _, r in sorted(v, key=lambda x: x[0])[:4]] for k, v in by.items()}


def download(r, dest):
    url = r["file"] if r["file"].startswith("http") else "https:" + r["file"]
    resp = requests.get(url, headers={"User-Agent": "ecology-of-missing-data/1.0 (research; eceozen23@gmail.com)"},
                        timeout=60, allow_redirects=True)
    resp.raise_for_status()
    raw = dest.with_suffix(".raw")
    raw.write_bytes(resp.content)
    if FFMPEG:
        p = subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(raw), "-t", "30", "-ac", "1",
                            "-b:a", "64k", str(dest)], capture_output=True)
        raw.unlink(missing_ok=True)
        return p.returncode == 0 and dest.exists() and dest.stat().st_size > 2000
    raw.rename(dest)
    return dest.stat().st_size > 2000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    import pandas as pd
    df = pd.read_csv(SITE_SP, sep=None, engine="python")
    latins = set(df["latin"].astype(str))
    recs = json.loads(CACHE.read_text(encoding="utf-8"))
    cand = candidates(recs, latins)
    items = sorted(cand.items())
    if a.limit:
        items = items[:a.limit]
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"ffmpeg: {'var' if FFMPEG else 'YOK (sadece mp3 kayıtlar, kısaltma yok)'} | kayıtlı tür: {len(cand)}/{len(latins)}")
    ok = fail = 0
    for lat, rs in tqdm(items, desc="Sesler"):
        got = False
        for r in rs:
            dest = OUT / f"{r['id']}.mp3"
            if dest.exists() and dest.stat().st_size > 2000:
                got = True; break
            try:
                if download(r, dest):
                    got = True; time.sleep(0.5); break
            except Exception as e:
                print(f"\n  {lat} XC{r['id']}: {e}")
            time.sleep(0.5)
        ok += got; fail += (not got)
    print(f"\nİndirilen/hazır: {ok} | alınamayan: {fail} | klasör: {OUT}")
    print("Şimdi: python build_site.py")


if __name__ == "__main__":
    main()
