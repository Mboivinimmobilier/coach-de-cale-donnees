"""Coach de câle — prépare la carte écoforestière (MRNF, CC-BY 4.0) pour l'app.
Pour chaque feuillet 1/250 000 : télécharge le GPKG officiel, garde les champs utiles,
calcule une classe « orignal » par peuplement, et produit un fichier PMTiles (tuiles vectorielles).
Usage : python scripts/prep.py [--test chemin.gpkg]"""
import csv, io, json, os, re, subprocess, sys, zipfile, urllib.request, datetime, glob, shutil
import pyogrio, geopandas as gpd, traceback, time
UA = {"User-Agent": "Mozilla/5.0 (CoachDeCale; +https://coach-de-cale.netlify.app)"}
LOG = []
def log(*a):
  t = " ".join(str(x) for x in a); print(t, flush=True); LOG.append(t)
def get(url, dest=None, tries=4):
  for i in range(tries):
    try:
      req = urllib.request.Request(url, headers=UA)
      with urllib.request.urlopen(req, timeout=300) as r:
        if not dest: return r.read()
        with open(dest, "wb") as f: shutil.copyfileobj(r, f, 1 << 20)
        return dest
    except Exception as e:
      log("essai", i + 1, "échec", url, repr(e)); time.sleep(10 * (i + 1))
  raise RuntimeError("téléchargement impossible : " + url)

CSV_URL = "https://diffusion.mffp.gouv.qc.ca/Diffusion/DonneeGratuite/Foret/DONNEES_FOR_ECO_SUD/Cartes_ecoforestieres_perturbations/03-Telechargement/URL_250K_MAJ.csv"
# Le serveur de téléchargement refuse les serveurs infonuagiques : on passe par le service WFS officiel (même carte, CC-BY 4.0)
WFS = "https://geoegl.msp.gouv.qc.ca/ws/mffpecofor.fcgi"
OUT = "dist"; TMP = "tmp"; YEAR = datetime.date.today().year
os.makedirs(OUT, exist_ok=True); os.makedirs(TMP, exist_ok=True)

# Champs recherchés (le premier nom trouvé gagne) — les noms exacts sont dans le dictionnaire officiel
FIELDS = {
  "tc": [r"^type_couv$", r"TYPE_COUV"],                        # type de couvert : F feuillu, M mixte, R résineux
  "e":  [r"^GR_ESS$", r"^GR_ESS", r"ESS"],                     # groupement d'essences
  "d":  [r"^CL_DENS$", r"DENS"],                                # classe de densité (A-D)
  "h":  [r"^CL_HAUT$", r"HAUT"],                                # classe de hauteur (1-7)
  "g":  [r"^CL_AGE$", r"AGE"],                                  # classe d'âge
  "or": [r"^ORIGINE$", r"^CO_ORIGINE$", r"ORIG(?!.*AN)"],       # perturbation d'origine (CT, CPR, BR…)
  "ao": [r"^AN_ORIGINE$", r"AN_?ORI"],                          # année de l'origine
  "pe": [r"^PERTURB$", r"^CO_PERTURB$", r"PERTU(?!.*AN)"],      # perturbation partielle
  "ap": [r"^AN_PERTURB$", r"AN_?PERT"],                         # année de la perturbation partielle
  "t":  [r"^TYPE_ECO$", r"TYP.*ECO"],                           # type écologique
  "te": [r"^CO_TER$", r"^TYPE_TER$", r"TER(?!R)"],              # terrain non forestier (eau, dénudé humide, aulnaie…)
  "dr": [r"^CL_DRAI$", r"DRAI"],                                # drainage (50-69 = mauvais à très mauvais)
  "ds": [r"^DEP_SUR$", r"DEP_?SUR"],                            # dépôt de surface (7 = organique : tourbière)
}
FEU = re.compile(r"BP|PE|PT|FI|FX|ER|BJ|PEU|FT|PU|BB")
RES = re.compile(r"EN|EB|SB|SE|RX|RZ|PG|EE|EP|SS|ML|ME|TO|TH|PB|PR")
DIST = re.compile(r"^(CT|CPR|CPRS|CRS|CRB|BR|BRU|CHT|ES|P|PL|PLN|CBA|CPH|CB|CPC|CPPTM|CPI_CP|REA|CBT|CMR)$")
HUMIDE = re.compile(r"^(DH|AL|INO|TOU|MAR)$")
EAU = re.compile(r"^(EAU|LAC|RIV|ILE)$")

def pick(cols, pats):
  for p in pats:
    for c in cols:
      if re.search(p, c, re.I): return c
  return None

def sv(v):
  if v is None: return ""
  t = str(v).strip(); return "" if t.lower() in ("nan", "none", "null") else t
def num(v):
  t = sv(v); m = re.match(r"^(\d{4})", t); return int(m.group(1)) if m else 0

def classe(r):
  """Classe orignal : i=idéal (mixte), n=nourriture (feuillus / repousse), a=abri (résineux dense),
     h=humide, o=ouvert récent (trop jeune), r=résineux peu utile, w=eau, x=inconnu. s = note 0 à 3."""
  te = sv(r.get("te")).upper()
  if EAU.match(te): return "w", 0
  if HUMIDE.match(te): return "h", 2
  e = sv(r.get("e")).upper(); tc = sv(r.get("tc")).upper()
  feu = tc in ("F", "M") or (not tc and bool(FEU.search(e))); res = tc in ("R", "M") or (not tc and bool(RES.search(e)))
  ori = sv(r.get("or")).upper(); ao = num(r.get("ao"))
  since = YEAR - ao if (ao and DIST.match(ori)) else None
  if since is not None and since < 5: return "o", 1
  # Terrain sans couvert forestier : tourbière / dénudé humide (dépôt organique ou mauvais drainage), sinon eau, agricole, chemin…
  if not tc and not e and (since is None or since > 30):
    ds = sv(r.get("ds")).upper(); dr = sv(r.get("dr"))
    if ds.startswith("7") or (dr[:1] in ("5", "6")): return "h", 2
    return "x", 0
  if since is not None and since <= 30: return ("i", 3) if (feu and res) else ("n", 3 if since >= 10 else 2)
  if feu and res: return "i", 3
  if feu: return "n", 2
  if res:
    d = sv(r.get("d")).upper(); h = sv(r.get("h"))
    return ("a", 2) if (d in ("A", "B") and h in ("1", "2", "3", "4")) else ("r", 1)
  return "x", 0


def wfs_zone(nom, s_, w, n, e, step=0.05):
  """Télécharge les peuplements d'une zone par petits carreaux (service WFS), sans doublons."""
  feats = {}; lat = s_; k = 0; fails = 0
  while lat < n:
    lon = w
    while lon < e:
      start = 0
      while True:
        q = (f"{WFS}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=ms:ori_pee_close_scale&SRSNAME=EPSG:4326"
             f"&BBOX={lat:.4f},{lon:.4f},{min(lat+step,n):.4f},{min(lon+step,e):.4f},urn:ogc:def:crs:EPSG::4326"
             f"&COUNT=2000&STARTINDEX={start}&OUTPUTFORMAT=application/json;%20subtype=geojson;%20charset=iso-8859-1")
        try:
          raw = get(q, tries=5); j = json.loads(raw.decode("iso-8859-1"))
        except Exception as ex:
          fails += 1; log("carreau raté", lat, lon, repr(ex)); break
        fs = j.get("features", [])
        for f in fs:
          fid = f.get("properties", {}).get("ogc_fid") or f.get("id")
          if fid is not None: feats[fid] = f
        k += 1
        if len(fs) < 2000: break
        start += 2000
      lon += step; time.sleep(0.2)
    log(nom, f"lat {lat:.2f} : {len(feats)} peuplements, {k} requêtes, {fails} ratés"); lat += step
  path = f"{TMP}/{nom}.geojson"
  json.dump({"type": "FeatureCollection", "features": list(feats.values())}, open(path, "w"))
  return path

def layer_of(path):
  lays = pyogrio.list_layers(path)
  best = None
  for name, geom in lays:
    if geom and "POLYGON" in str(geom).upper():
      n = pyogrio.read_info(path, layer=name)["features"]
      score = n * (3 if re.search(r"PEE|PEUPL|ECO", name, re.I) else 1)
      if not best or score > best[0]: best = (score, name)
  return best[1] if best else lays[0][0]

def process(fid, gpkg):
  lay = layer_of(gpkg) if gpkg.endswith(".gpkg") else pyogrio.list_layers(gpkg)[0][0]
  info = pyogrio.read_info(gpkg, layer=lay); cols = list(info["fields"])
  m = {k: pick(cols, v) for k, v in FIELDS.items()}
  with open(f"{OUT}/schema-{fid}.txt", "w") as f:
    f.write(f"couche: {lay}\nentités: {info['features']}\ncrs: {info['crs']}\nchamps: {cols}\ncorrespondance: {json.dumps(m)}\n")
  log(fid, "couche", lay, info["features"], "entités", json.dumps(m))
  use = [c for c in m.values() if c]
  df = gpd.read_file(gpkg, layer=lay, columns=use, engine="pyogrio")
  df = df.rename(columns={v: k for k, v in m.items() if v})
  for k in FIELDS:
    if k not in df: df[k] = None
  df = df.to_crs(4326)
  cs = [classe(r) for r in df[list(FIELDS)].to_dict("records")]
  df["o"] = [c[0] for c in cs]; df["s"] = [c[1] for c in cs]
  for k in FIELDS:
    if k in ("ao", "ap"): df[k] = df[k].map(lambda v: num(v) or None).astype("Int64")
    else: df[k] = df[k].map(lambda v: re.sub(r"\.0$", "", sv(v)) or None).astype("object")
  with open(f"{OUT}/schema-{fid}.txt", "a") as f:
    f.write("classes: " + json.dumps(df["o"].value_counts().to_dict()) + "\n")
    f.write("exemples:\n" + df.drop(columns="geometry").head(8).to_string() + "\n")
  nd = f"{TMP}/{fid}.geojsonl"; df.to_file(nd, driver="GeoJSONSeq", engine="pyogrio")
  out = f"{OUT}/{fid}.pmtiles"
  subprocess.run(["tippecanoe", "-o", out, "--force", "-l", "pee", "-Z", "10", "-z", "15",
    "--coalesce-smallest-as-needed", "--detect-shared-borders", "--simplify-only-low-zooms",
    "--no-tile-stats", "-q", "-P", nd], check=True)
  b = df.total_bounds
  return {"id": fid, "url": f"{fid}.pmtiles", "bbox": [round(float(x), 4) for x in b], "taille": os.path.getsize(out), "entites": int(len(df)), "champs": m}

def download(fid, url):
  z = f"{TMP}/{fid}.zip"
  if not os.path.exists(z):
    log("téléchargement", fid, url); get(url, z); log("reçu", fid, os.path.getsize(z), "octets")
  d = f"{TMP}/{fid}"; shutil.rmtree(d, ignore_errors=True); zipfile.ZipFile(z).extractall(d)
  g = glob.glob(f"{d}/**/*.gpkg", recursive=True); return g[0]

def main_safe():
  try: main()
  except Exception:
    log("ERREUR GÉNÉRALE", traceback.format_exc())
    os.makedirs(OUT, exist_ok=True); open(f"{OUT}/journal.txt", "w").write("\n".join(LOG))
    if not os.path.exists(f"{OUT}/index.json"): json.dump({"maj": None, "feuillets": [], "erreur": True}, open(f"{OUT}/index.json", "w"))
    open(f"{OUT}/.nojekyll", "w").close()

def main():
  args = sys.argv[1:]; done = []
  if args and args[0] == "--zone":   # essai rapide : --zone nom;s;w;n;e
    nom, a, b, c, d = args[1].split(";"); g = wfs_zone(nom, float(a), float(b), float(c), float(d)); done.append(process(nom, g))
  elif args and args[0] == "--test":
    done.append(process("TEST", args[1]))
  elif os.path.exists("zones.txt"):
    for l in open("zones.txt"):
      l = l.strip()
      if not l or l.startswith("#"): continue
      nom, a, b, c, d = [x.strip() for x in l.split(";")]
      try:
        g = wfs_zone(nom, float(a), float(b), float(c), float(d))
        r = process(nom, g); r["bbox"] = [float(b), float(a), float(d), float(c)]; done.append(r)
      except Exception:
        log("ERREUR", nom, traceback.format_exc())
      shutil.rmtree(TMP, ignore_errors=True); os.makedirs(TMP, exist_ok=True)
  else:
    want = [l.strip().upper() for l in open("feuillets.txt") if l.strip() and not l.startswith("#")]
    raw = get(CSV_URL)
    try: txt = raw.decode("utf-8-sig")
    except UnicodeDecodeError: txt = raw.decode("cp1252")
    log("CSV", len(txt), "caractères ; début :", txt[:300].replace("\n", " ⏎ "))
    delim = ";" if txt.split("\n", 1)[0].count(";") > txt.split("\n", 1)[0].count(",") else ","
    rows = list(csv.DictReader(io.StringIO(txt), delimiter=delim))
    key = next(k for k in rows[0] if "FEUILLET" in k.upper() and "NOM" not in k.upper())
    gk = next(k for k in rows[0] if "GPKG" in k.upper())
    log("colonnes", list(rows[0].keys()), "lignes", len(rows))
    for fid in want:
      try:
        r = next((x for x in rows if x[key].strip().upper() in (fid, fid.replace("0", ""), "0" + fid)), None)
        if not r: log("introuvable", fid, "exemples :", [x[key] for x in rows[:8]]); continue
        done.append(process(fid, download(fid, r[gk].strip())))
      except Exception:
        log("ERREUR", fid, traceback.format_exc())
      shutil.rmtree(TMP, ignore_errors=True); os.makedirs(TMP, exist_ok=True)  # libérer le disque
  idx = {"maj": datetime.date.today().isoformat(), "annee_ref": YEAR, "source": "MRNF, Carte écoforestière à jour (CC-BY 4.0)",
         "classes": {"i": "Idéal (mixte)", "n": "Nourriture", "a": "Abri", "h": "Humide", "o": "Ouvert récent", "r": "Résineux peu utile", "w": "Eau", "x": "Inconnu"}, "feuillets": done}
  json.dump(idx, open(f"{OUT}/index.json", "w"), ensure_ascii=False, indent=1)
  open(f"{OUT}/.nojekyll", "w").close()
  log(json.dumps(idx, ensure_ascii=False)[:800])
  open(f"{OUT}/journal.txt", "w").write("\n".join(LOG))

if __name__ == "__main__": main_safe()
