"""Coach de câle — prépare la carte écoforestière (MRNF, CC-BY 4.0) pour l'app.
Pour chaque feuillet 1/250 000 : télécharge le GPKG officiel, garde les champs utiles,
calcule une classe « orignal » par peuplement, et produit un fichier PMTiles (tuiles vectorielles).
Usage : python scripts/prep.py [--test chemin.gpkg]"""
import csv, io, json, os, re, subprocess, sys, zipfile, urllib.request, datetime, glob, shutil
import pyogrio, geopandas as gpd

CSV_URL = "https://diffusion.mffp.gouv.qc.ca/Diffusion/DonneeGratuite/Foret/DONNEES_FOR_ECO_SUD/Cartes_ecoforestieres_perturbations/03-Telechargement/URL_250K_MAJ.csv"
OUT = "dist"; TMP = "tmp"; YEAR = datetime.date.today().year
os.makedirs(OUT, exist_ok=True); os.makedirs(TMP, exist_ok=True)

# Champs recherchés (le premier nom trouvé gagne) — les noms exacts sont dans le dictionnaire officiel
FIELDS = {
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
  "dr": [r"^CL_DRAI$", r"DRAI"],                                # drainage
}
FEU = re.compile(r"BP|PE|FI|FX|ER|BJ|PEU|FT|PU")
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
  e = sv(r.get("e")).upper(); feu = bool(FEU.search(e)); res = bool(RES.search(e))
  ori = sv(r.get("or")).upper(); ao = num(r.get("ao"))
  since = YEAR - ao if (ao and DIST.match(ori)) else None
  if since is not None and since < 5: return "o", 1
  if since is not None and since <= 30: return ("i", 3) if (feu and res) else ("n", 3 if since >= 10 else 2)
  if feu and res: return "i", 3
  if feu: return "n", 2
  if res:
    d = sv(r.get("d")).upper(); h = sv(r.get("h"))
    return ("a", 2) if (d in ("A", "B") and h in ("1", "2", "3", "4")) else ("r", 1)
  return "x", 0

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
  lay = layer_of(gpkg); info = pyogrio.read_info(gpkg, layer=lay); cols = list(info["fields"])
  m = {k: pick(cols, v) for k, v in FIELDS.items()}
  with open(f"{OUT}/schema-{fid}.txt", "w") as f:
    f.write(f"couche: {lay}\nentités: {info['features']}\ncrs: {info['crs']}\nchamps: {cols}\ncorrespondance: {json.dumps(m)}\n")
  print(fid, "couche", lay, info["features"], "entités", json.dumps(m), flush=True)
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
    print("téléchargement", fid, url, flush=True)
    urllib.request.urlretrieve(url, z)
  d = f"{TMP}/{fid}"; shutil.rmtree(d, ignore_errors=True); zipfile.ZipFile(z).extractall(d)
  g = glob.glob(f"{d}/**/*.gpkg", recursive=True); return g[0]

def main():
  args = sys.argv[1:]; done = []
  if args and args[0] == "--test":
    done.append(process("TEST", args[1]))
  else:
    want = [l.strip().upper() for l in open("feuillets.txt") if l.strip() and not l.startswith("#")]
    rows = list(csv.DictReader(io.StringIO(urllib.request.urlopen(CSV_URL).read().decode("utf-8-sig"))))
    key = next(k for k in rows[0] if "FEUILLET" in k.upper() and "NOM" not in k.upper())
    gk = next(k for k in rows[0] if "GPKG" in k.upper())
    for fid in want:
      r = next((x for x in rows if x[key].strip().upper() == fid), None)
      if not r: print("introuvable", fid); continue
      done.append(process(fid, download(fid, r[gk].strip())))
      shutil.rmtree(TMP, ignore_errors=True); os.makedirs(TMP, exist_ok=True)  # libérer le disque
  idx = {"maj": datetime.date.today().isoformat(), "annee_ref": YEAR, "source": "MRNF, Carte écoforestière à jour (CC-BY 4.0)",
         "classes": {"i": "Idéal (mixte)", "n": "Nourriture", "a": "Abri", "h": "Humide", "o": "Ouvert récent", "r": "Résineux peu utile", "w": "Eau", "x": "Inconnu"}, "feuillets": done}
  json.dump(idx, open(f"{OUT}/index.json", "w"), ensure_ascii=False, indent=1)
  open(f"{OUT}/.nojekyll", "w").close()
  print(json.dumps(idx, ensure_ascii=False)[:800])

if __name__ == "__main__": main()
