"""Lit quelques tuiles publiées (GitHub Pages) et affiche les propriétés des peuplements, pour diagnostiquer l'app."""
import json, sys, urllib.request, math, gzip, collections
from pmtiles.reader import Reader, MmapSource
import mapbox_vector_tile as mvt
BASE = "https://mboivinimmobilier.github.io/coach-de-cale-donnees/"
idx = json.loads(urllib.request.urlopen(BASE + "index.json?x=1").read())
print("modele", idx.get("modele"), "maj", idx.get("maj"), [f["id"] for f in idx["feuillets"]])
pts = [(48.83, -79.20), (48.87, -79.20), (48.90, -79.20), (48.80, -79.215)]
def tile(lat, lon, z):
  n = 2 ** z; x = int((lon + 180) / 360 * n); y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n); return z, x, y
for f in idx["feuillets"]:
  fn = "/tmp/" + f["url"]
  urllib.request.urlretrieve(BASE + f["url"], fn)
  with open(fn, "rb") as fh:
    r = Reader(MmapSource(fh)); print(f["id"], r.header()["max_zoom"], r.metadata().get("vector_layers", [{}])[0].get("fields") if isinstance(r.metadata(), dict) else "")
    for lat, lon in pts:
      if not (f["bbox"][1] <= lat <= f["bbox"][3]): continue
      z, x, y = tile(lat, lon, 14); d = r.get(z, x, y)
      if not d: print(" pas de tuile", lat, lon); continue
      try: d = gzip.decompress(d)
      except Exception: pass
      t = mvt.decode(d); L = t.get("pee", {}).get("features", [])
      miss = sum(1 for q in L if q["properties"].get("p") is None); c = collections.Counter(q["properties"].get("o") for q in L)
      print(f" {lat},{lon} z14 : {len(L)} peuplements, p manquant {miss}, classes {dict(c)}")
      for q in L[:6]: print("   ", {k: q["properties"].get(k) for k in ("o", "p", "q", "rd", "e", "h", "an")})
