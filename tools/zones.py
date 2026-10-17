"""Limites officielles des zones de chasse du Québec (MRNF, service SmartFaunePub de Forêt ouverte),
regroupées par partie de zone et allégées pour tenir dans l'app (recherche de la zone par GPS, hors réseau)."""
import json, sys, time, urllib.request, urllib.parse
import geopandas as gpd, shapely
from shapely.geometry import shape, mapping
URL = "https://servicesvecto3.mern.gouv.qc.ca/geoserver/SmartFaunePub/ows"
UA = {"User-Agent": "CoachDeCale/1.0 (+https://coach-de-cale.netlify.app)"}
def get(params, tries=5):
  q = URL + "?" + urllib.parse.urlencode(params)
  for i in range(tries):
    try:
      with urllib.request.urlopen(urllib.request.Request(q, headers=UA), timeout=180) as r: return r.read()
    except Exception as ex:
      print("essai", i + 1, repr(ex), flush=True); time.sleep(10 * (i + 1))
  raise RuntimeError("échec " + q)
feats, start, seen = [], 0, set()
while True:
  j = json.loads(get({"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": "SmartFaunePub:Zone_chasse_da3_sefaq",
                      "outputFormat": "application/json", "srsName": "EPSG:4326", "count": 1000, "startIndex": start,
                      "sortBy": "Zone,Shape_Area,Latitude,Longitude"}))
  fs = j.get("features", [])
  for f in fs:
    k = (f.get("id"), (f.get("properties") or {}).get("Shape_Area"))
    if k in seen: continue
    seen.add(k); feats.append(f)
  print("page", start, len(fs), "total", len(feats), flush=True)
  if len(fs) < 1000: break
  start += 1000
rows = []
for f in feats:
  p = f.get("properties") or {}
  if not f.get("geometry"): continue
  rows.append({"z": str(p.get("Zone") or "").strip().upper(), "p": str(p.get("Partie_zon") or "").strip(), "n": str(p.get("No_zone") or "").strip(),
               "geometry": shape(f["geometry"])})
g = gpd.GeoDataFrame(rows, crs=4326)
g["geometry"] = shapely.make_valid(g.geometry.values)
d = g.dissolve(by="z", aggfunc="first").reset_index()
out = []
for _, r in d.iterrows():
  geom = r.geometry
  m = gpd.GeoSeries([geom], crs=4326).to_crs(32198).iloc[0]
  parts = list(getattr(m, "geoms", [m]))
  big = [q for q in parts if q.area >= 2e6]          # îlots de moins de 2 km² retirés (sauf si c'est tout ce qu'il y a)
  keep = big if big else sorted(parts, key=lambda q: -q.area)[:20]
  m2 = shapely.MultiPolygon([q for q in keep if q.geom_type == "Polygon"] + [x for q in keep if q.geom_type == "MultiPolygon" for x in q.geoms])
  m2 = m2.simplify(250 if r["z"] not in ("08NMR",) else 20, preserve_topology=True)
  g2 = gpd.GeoSeries([m2], crs=32198).to_crs(4326).iloc[0]
  g2 = shapely.set_precision(g2, 0.0001)
  out.append({"type": "Feature", "properties": {"z": r["z"], "p": r["p"], "n": r["n"]}, "geometry": mapping(g2)})
fc = {"type": "FeatureCollection", "source": "MRNF, Zones et parties de zones de chasse (SmartFaunePub:Zone_chasse_da3_sefaq)",
      "maj": time.strftime("%Y-%m-%d"), "features": out}
s = json.dumps(fc, separators=(",", ":"))
open(sys.argv[1] if len(sys.argv) > 1 else "zones-chasse.json", "w").write(s)
print("zones :", len(out), "taille :", len(s) // 1024, "Ko", sorted(x["properties"]["z"] for x in out))
