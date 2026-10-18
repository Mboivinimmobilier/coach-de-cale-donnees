"""Coach de câle — prépare la carte écoforestière (MRNF, CC-BY 4.0) pour l'app.
Pour chaque feuillet 1/250 000 : télécharge le GPKG officiel, garde les champs utiles,
calcule une classe « orignal » par peuplement, et produit un fichier PMTiles (tuiles vectorielles).
Usage : python scripts/prep.py [--test chemin.gpkg]"""
import csv, io, json, os, re, subprocess, sys, zipfile, urllib.request, urllib.parse, datetime, glob, shutil
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
  "pt": [r"^CL_PENT$", r"PENT"],                                # classe de pente (A-F)
}
# Champs lus un peuplement à la fois au service de cartes (GetFeatureInfo) : absents du service WFS
GFI_KEYS = {"co_ter": "te", "veg_pot": "vp", "couv_gaule": "cg", "st_ha_tot": "st", "annotation": "an", "type_eco": "t"}
# Codes d'essences (norme de stratification écoforestière, tableaux 8 et 9). PU = pruche (résineux), pas un peuplier.
FEU_C = {"BP", "BJ", "BG", "BB", "PE", "PT", "PA", "PD", "FI", "FX", "FN", "FT", "ER", "ES", "EO", "CR", "CH", "HG",
         "FO", "FA", "FP", "FR", "OR", "CT", "TA", "TI", "CA", "OV", "OS", "AU"}
RES_C = {"EN", "EB", "SB", "SE", "RX", "RZ", "PG", "EE", "EP", "SS", "ML", "ME", "TO", "TH", "PB", "PR", "PU", "RS"}
def _ess(s): return re.findall(r"[A-Z]{2}", s or "")
class _EssRe:
  """Remplace l'ancienne regex : cherche des codes d'essence entiers (par paires de lettres), pas des bouts de texte."""
  def __init__(self, codes): self.c = codes
  def search(self, s): return any(t in self.c for t in _ess(s))
FEU = _EssRe(FEU_C)
RES = _EssRe(RES_C)
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

# ---- Classes « orignal » (automne), d'après le rapport « Orignal et carte écoforestière » (Courtois et al. 2002,
# Dussault et al. 2006 IQH, Potvin et al. 2004…). v = valeur de la classe sur 3.
# i idéal (mixte mature) · a abri avec sapin · e abri d'épinette noire · n nourriture · h humide riche · b humide pauvre
# p passage (résineux bas ou clairsemé) · o ouvert récent · r résineux peu utile · w eau · x non forestier / inconnu
DIST2 = re.compile(r"^(CT|CPR|CPRS|CPRS_U|CPPTM|CPPTM_U|CPH|CPT|CDV|CTSP|CTSP_U|CTSP_T|CBA|CB|CEF|CRS|CRB|CRR|ETR|REA|RIA|RPS|BR|BRU|CHT|ES|DT|VER|P|PL|PLN|ENS|PRR|CPC|CPI_CP|CBT|CMR)")
PLANT = re.compile(r"^(P|PL|PLN|PRR|ENS)$")
SAPIN = re.compile(r"SB|SE|EB")
PUR_EN = re.compile(r"^((EN|PG|RX|RZ|ML|PI|EP|ME|MH|MJ)+)$")
VIEUX = ("50", "70", "90", "110", "120", "130", "VIN", "VIR")
NONFOR = re.compile(r"^(A|AF|ANT|GR|RO|LTE|ILE|NF|NX|NE)$")
def classe(r):
  te = sv(r.get("te")).upper(); vp = sv(r.get("vp")).upper()
  e = sv(r.get("e")).upper(); tc = sv(r.get("tc")).upper()
  ori = sv(r.get("or")).upper(); ao = num(r.get("ao")); h = sv(r.get("h")); d = sv(r.get("d")).upper(); g = sv(r.get("g")).upper()
  cg = sv(r.get("cg")).upper(); st = r.get("st"); ds = sv(r.get("ds")).upper(); dr = sv(r.get("dr"))
  an = sv(r.get("an")).upper(); hm = dp = None; pf = None
  m_ = re.search(r"\*(\d+)%", an); dp = int(m_.group(1)) if m_ else None
  m_ = re.search(r"(\d+(?:\.\d+)?)M\*", an); hm = float(m_.group(1)) if m_ else None
  comp = re.findall(r"([A-Z]{2})(\d+)", an.split("*")[0]) if an else []
  if comp: pf = sum(int(q) for c_, q in comp if FEU.search(c_)) / max(1, sum(int(q) for _, q in comp)) * 100
  # Hauteur et densité exactes : on les ramène aux classes pour garder les mêmes règles, mais avec la vraie valeur
  if hm is not None: h = "1" if hm >= 22 else "2" if hm >= 17 else "3" if hm >= 12 else "4" if hm >= 7 else "5" if hm >= 4 else "6" if hm >= 2 else "7"
  if dp is not None: d = "A" if dp >= 80 else "B" if dp >= 60 else "C" if dp >= 40 else "D"
  # Terrains non forestiers (code de terrain lu au service de cartes)
  if EAU.match(te): return "w", 0.0, 0
  if te == "INO": return "h", 1.8, 3
  if te == "AL": return "h", 1.3, 2   # aulnaie : bon couvert, mais l'aulne est peu mangé
  if te == "DH": return ("b", 1.0, 1) if vp.startswith("TOB") else ("h", 1.8, 3) if vp[:3] in ("TOF", "MA1") else ("h", 1.5, 2)
  if te == "DS": return "r", 0.5, 0
  if NONFOR.match(te): return "x", 0.0, 0
  feu = tc in ("F", "M") or (not tc and bool(FEU.search(e))); res = tc in ("R", "M") or (not tc and bool(RES.search(e)))
  since = YEAR - ao if (ao and DIST2.match(ori)) else None
  if since is not None and since < 5: return "o", 0.9, 1
  if not tc and not e:   # pas de peuplement : milieu humide ou terrain ouvert
    if vp.startswith("TOB") or vp[:3] in ("RE3", "RS3"): return "b", 1.0, 1
    if ds.startswith("7") or dr[:1] in ("5", "6"): return ("h", 1.8, 3) if vp[:3] in ("TOF", "MA1") else ("h", 1.5, 2)
    return "x", 0.0, 0
  pur = bool(PUR_EN.match(e)) and not SAPIN.search(e)
  if since is not None and since < 10:   # 5-10 ans : transition, le brout monte (seuils atteints vers 10 ans en mixte)
    return ("n", 1.4, 1) if feu else ("o", 0.9, 1)
  if since is not None and since <= 25:  # fenêtre utile de la repousse
    if feu: return "n", 2.2 * (0.6 if pur else 1), 2
    return "p", 1.2, 0
  if since is not None and since <= 45 and feu: return "n", 2.0, 2
  # Peuplements matures ou sans perturbation récente
  if tc == "M" or (not tc and feu and res):
    if h in ("1", "2", "3") or g in VIEUX: return "i", 3.0 if (SAPIN.search(e) or (pf is not None and pf >= 50)) else 2.7, 3
    return "n", 2.0, 2
  if feu and not res:
    return "n", 2.2 if h in ("5", "6", "7") else 2.0, 2
  if res:
    try: stv = float(st) if st not in (None, "") else None
    except (TypeError, ValueError): stv = None
    couvert = h in ("1", "2", "3", "4") and (d in ("A", "B") or (stv is not None and stv >= 13))
    if couvert: return ("a", 2.4, 2) if SAPIN.search(e) else ("e", 1.5, 2)
    # Gaules feuillues sous un résineux ouvert (5e inventaire) : brout à portée de l'orignal
    if re.search(r"F", cg) and re.search(r"[12]", cg): return "n", 1.8, 2
    if re.search(r"M", cg) and re.search(r"[12]", cg): return "n", 1.6, 2
    if FEU.search(e) and h in ("4", "5", "6", "7"): return "n", 1.8, 2   # RXFX, ENFX… jeunes
    if h in ("4", "5", "6", "7"): return "p", 1.2, 0
    return "r", 0.5, 0
  return "x", 0.0, 0

def mult(r, o, v):
  """Modificateurs : plantation, éclaircie précommerciale, épidémie légère, station, pente forte."""
  if v <= 0: return v
  ori = sv(r.get("or")).upper(); ao = num(r.get("ao")); pe = sv(r.get("pe")).upper(); ap = num(r.get("ap"))
  vp = sv(r.get("vp")).upper()[:3]; dr = sv(r.get("dr")); h = sv(r.get("h")); pt = sv(r.get("pt")).upper()
  since = YEAR - ao if ao else None
  if PLANT.match(ori) and since is not None and since <= 30 and o in ("n", "p"): v *= 0.7
  if pe.startswith("EPC") and ap and YEAR - ap <= 15 and o in ("n", "i"): v *= 0.8
  if pe == "EL": v *= 1.1
  jeune = (since is not None and since <= 30) or h in ("5", "6", "7")
  if jeune and o in ("n", "i", "p"):
    if vp in ("MS2", "ME1") or dr == "31": v *= 1.15
    elif vp == "RE2": v *= 0.8
    elif vp in ("RS3", "RE3"): v *= 0.5
    elif vp in ("RE1", "TOB"): v *= 0.3
  if pt in ("E", "F"): v *= 0.5
  # Quelques feuillus dans un résineux (ex. EN90PT10 noté « ENEN ») : un peu de brout en plus
  an = sv(r.get("an")).upper(); comp = re.findall(r"([A-Z]{2})(\d+)", an.split("*")[0]) if an else []
  if comp and o in ("a", "e", "p", "r"):
    pf = sum(int(q) for c_, q in comp if FEU.search(c_)) / max(1, sum(int(q) for _, q in comp)) * 100
    if pf >= 20: v *= 1.15
    elif pf >= 10: v *= 1.08
  return min(3.0, v)


def wfs_zone(nom, s_, w, n, e, step=0.05, typ="ori_pee_close_scale", suffix=""):
  """Télécharge une couche WFS d'une zone par petits carreaux, sans doublons."""
  feats = {}; lat = s_; k = 0; fails = 0
  while lat < n:
    lon = w
    while lon < e:
      start = 0
      while True:
        q = (f"{WFS}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=ms:{typ}&SRSNAME=EPSG:4326"
             f"&BBOX={lat:.4f},{lon:.4f},{min(lat+step,n):.4f},{min(lon+step,e):.4f},urn:ogc:def:crs:EPSG::4326"
             f"&COUNT=2000&STARTINDEX={start}&OUTPUTFORMAT=application/json;%20subtype=geojson;%20charset=iso-8859-1")
        try:
          raw = get(q, tries=5); j = json.loads(raw.decode("iso-8859-1"))
        except Exception as ex:
          fails += 1; log("carreau raté", typ, lat, lon, repr(ex)); break
        fs = j.get("features", [])
        for f in fs:
          fid = f.get("properties", {}).get("ogc_fid") or f.get("id")
          if fid is not None: feats[fid] = f
        k += 1
        if len(fs) < 2000: break
        start += 2000
      lon += step; time.sleep(0.2)
    if typ == "ori_pee_close_scale": log(nom, f"lat {lat:.2f} : {len(feats)} peuplements, {k} requêtes, {fails} ratés")
    lat += step
  if typ != "ori_pee_close_scale": log(nom, typ, len(feats), "entités", fails, "ratés")
  path = f"{TMP}/{nom}{suffix}.geojson"
  json.dump({"type": "FeatureCollection", "features": list(feats.values())}, open(path, "w"))
  return path

# ---- Cartes à jour : coupes, feux et autres perturbations plus récentes que la photo du peuplement
def maj_perturb(df, nom, bb):
  """bb = (s, w, n, e). Remplace origine/année (ou perturbation partielle) par la plus récente qui couvre le peuplement."""
  s_, w, n, e = bb; pts = df.geometry.representative_point(); nmaj = 0
  for typ in ("ca_interv_for_close_scale", "ca_feu_close_scale", "ca_perturb_autre_close_scale"):
    try:
      g = gpd.read_file(wfs_zone(nom, s_, w, n, e, step=0.1, typ=typ, suffix="_" + typ), engine="pyogrio")
    except Exception as ex:
      log("maj", typ, "impossible", repr(ex)); continue
    if g.empty: continue
    g = g.set_crs(4326, allow_override=True)
    j = gpd.sjoin(gpd.GeoDataFrame(geometry=pts, crs=4326), g, predicate="within", how="inner")
    for idx, row in j.iterrows():
      o2 = sv(row.get("origine")).upper(); a2 = num(row.get("an_origine")); p2 = sv(row.get("perturb")).upper(); b2 = num(row.get("an_perturb"))
      if o2 and a2 and a2 > (num(df.at[idx, "ao"]) or 0): df.at[idx, "or"] = o2; df.at[idx, "ao"] = str(int(a2)); nmaj += 1
      elif p2 and b2 and b2 > (num(df.at[idx, "ap"]) or 0): df.at[idx, "pe"] = p2; df.at[idx, "ap"] = str(int(b2)); nmaj += 1
  log(nom, "mises à jour de perturbations :", nmaj)

# ---- Données détaillées du 5e inventaire (code de terrain, végétation potentielle, gaules, surface terrière)
GFI_CACHE = "cache"
def gfi_enrich(df, nom, budget_s=150 * 60, threads=8):
  import concurrent.futures as cf
  os.makedirs(GFI_CACHE, exist_ok=True); cpath = f"{GFI_CACHE}/gfi-{nom}.json"
  try: cache = json.load(open(cpath))
  except Exception: cache = {}
  tc = df["tc"].map(sv).str.upper(); h = df["h"].map(sv)
  need = ~((tc.isin(["F", "M"])) & (h.isin(["1", "2", "3"])))   # les feuillus et mixtes matures n'en ont pas besoin
  p3857 = df.to_crs(3857).geometry.representative_point()
  todo = [(str(df.at[i, "fid"]), p3857[i].x, p3857[i].y) for i in df.index[need] if str(df.at[i, "fid"]) not in cache]
  log(nom, "détails à lire :", len(todo), "(", len(cache), "déjà en cache )")
  t0 = time.time()
  def one(t):
    fid, x, y = t
    if time.time() - t0 > budget_s: return fid, None
    q = (f"{WFS}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetFeatureInfo&LAYERS=ori_pee_close_scale&QUERY_LAYERS=ori_pee_close_scale&STYLES="
         f"&CRS=EPSG:3857&BBOX={x-15:.1f},{y-15:.1f},{x+15:.1f},{y+15:.1f}&WIDTH=31&HEIGHT=31&I=15&J=15&INFO_FORMAT=text/plain&FEATURE_COUNT=3")
    txt = None
    for k_ in range(3):
      try:
        with urllib.request.urlopen(urllib.request.Request(q, headers=UA), timeout=40) as rr: txt = rr.read().decode("utf-8", "replace"); break
      except Exception: time.sleep(2 * (k_ + 1))
    if txt is None: return fid, None
    best = {}; cur = None
    for line in txt.splitlines():
      mm = re.match(r"\s*Feature (\d+):", line)
      if mm: cur = {}; continue
      mm = re.match(r"\s*([a-z_0-9]+) = '(.*)'\s*$", line)
      if mm and cur is not None:
        cur[mm.group(1)] = mm.group(2)
        if mm.group(1) == "ogc_fid" and mm.group(2) == fid: best = cur
        elif not best and mm.group(1) == "ogc_fid": best = cur
    return fid, {k: best.get(k, "") for k in GFI_KEYS} if best else {}
  done = 0
  with cf.ThreadPoolExecutor(threads) as ex:
    for fid, val in ex.map(one, todo):
      if val is not None: cache[fid] = val; done += 1
      if done and done % 5000 == 0: json.dump(cache, open(cpath, "w")); log(nom, "détails lus :", done)
  json.dump(cache, open(cpath, "w"))
  log(nom, "détails lus cette fois :", done, "en", int(time.time() - t0), "s ; total en cache :", len(cache))
  for k, col in GFI_KEYS.items():
    vals = df["fid"].map(lambda f: (cache.get(str(f)) or {}).get(k, ""))
    if col == "te": df[col] = [v if v else old for v, old in zip(vals, df[col] if col in df else [None] * len(df))]
    else: df[col] = vals

def potentiel(df):
  """Note orignal de 0 à 10 par peuplement (automne) :
     valeur de la classe (sur 3) × 6, puis + lisière nourriture-abri dans ~10 ha (max 2,8)
     + milieu humide ou rive proche (max 0,6) + passage qui relie nourriture et abri (0,5)."""
  import shapely
  m = df.to_crs(32198); G = m.geometry.values
  bad = ~shapely.is_valid(G)
  if bad.any(): G = G.copy(); G[bad] = shapely.make_valid(G[bad])
  o = df["o"].tolist(); v = df["v"].astype(float).tolist(); n = len(df)
  FOOD = ("n", "i"); COVER = ("a", "e", "i"); FOREST = ("i", "a", "e", "n", "p")
  tree = shapely.STRtree(G)
  L, Rr = tree.query(shapely.buffer(G, 2), predicate="intersects")
  _VOIS.clear(); _VOIS.update(G=G, tree=tree, L=L, R=Rr, n=n)   # voisinages réutilisés par la note cerf
  touchF = [False] * n; touchC = [False] * n; touchH = [False] * n; pa = []; pb = []
  for a_, b_ in zip(L, Rr):
    if a_ == b_: continue
    if o[b_] in FOOD: touchF[a_] = True
    if o[b_] in COVER: touchC[a_] = True
    if o[b_] in ("h", "b"): touchH[a_] = True
    if a_ < b_ and o[a_] != o[b_] and ((o[a_] in FOOD and o[b_] in COVER) or (o[a_] in COVER and o[b_] in FOOD)): pa.append(a_); pb.append(b_)
  # Lisières nourriture-abri (lignes partagées)
  if pa:
    E = shapely.intersection(shapely.boundary(G[pa]), shapely.buffer(G[pb], 2))
    E = E[~shapely.is_empty(E)]
  else: E = shapely.from_wkt([])
  rp = shapely.point_on_surface(G); circ = shapely.buffer(rp, 180, quad_segs=8); AREA_HA = 3.14159 * 180 * 180 / 10000
  _VOIS["rp"] = rp
  dens = [0.0] * n
  if len(E):
    et = shapely.STRtree(E); ci, ei = et.query(circ, predicate="intersects")
    ln = shapely.length(shapely.intersection(E[ei], circ[ci]))
    for c_, l_ in zip(ci, ln): dens[c_] += l_
    dens = [d_ / AREA_HA for d_ in dens]
  # Milieux humides et rives
  hum_idx = [k for k in range(n) if o[k] in ("h", "w")]
  dwet = [9e9] * n
  if hum_idx:
    ht = shapely.STRtree(G[hum_idx]); fi = [k for k in range(n) if o[k] in FOREST]
    if fi:
      qi, ti = ht.query_nearest(G[fi], max_distance=500, return_distance=False, all_matches=False)
      dd = shapely.distance(G[fi][qi], G[hum_idx][ti])
      for q_, d_ in zip(qi, dd): dwet[fi[q_]] = min(dwet[fi[q_]], d_)
  # Centre des coupes récentes : plus de 200 m de tout couvert ou repousse
  oi = [k for k in range(n) if o[k] == "o"]; ci_ = [k for k in range(n) if o[k] in ("i", "a", "e", "n", "p")]
  if oi and ci_:
    ct = shapely.STRtree(G[ci_]); qi, ti = ct.query_nearest(rp[oi], max_distance=200, return_distance=False, all_matches=False)
    near = set(oi[q_] for q_ in qi)
    for k in oi:
      if k not in near: v[k] = 0.5
  pts_ = df["pt"].map(lambda x: sv(x).upper()).tolist() if "pt" in df else [""] * n
  P = []; Lf = []; D = []
  for k in range(n):
    c = o[k]
    if c in ("x", "w"): P.append(0.0); Lf.append(0); D.append(0); continue
    sc = v[k] / 3 * 6.0
    if c in FOREST or c == "h": sc += 2.8 * min(1.0, dens[k] / 70.0)
    if c in FOREST: sc += 0.6 if dwet[k] <= 120 else 0.35 if dwet[k] <= 300 else 0.15 if dwet[k] <= 500 else 0
    if c == "p" and touchF[k] and touchC[k]: sc += 0.5
    if c in FOREST and touchH[k] and pts_[k] in ("C", "D"): sc += 0.2   # butte ou pente au bord d'un milieu humide (savoir de chasseurs)
    P.append(round(min(10.0, max(0.0, sc)), 1)); Lf.append(1 if dens[k] >= 30 else 0); D.append(int(round(dens[k])))
  df["p"] = P; df["l"] = Lf; df["ld"] = D; df["v"] = [round(x, 2) for x in v]
  try: secteur(df, G, rp, E, o, v)
  except Exception: log("secteur ERREUR", traceback.format_exc()); df["q"] = None
  try: routes(df, rp)
  except Exception: log("routes ERREUR", traceback.format_exc()); df["rd"] = None

def secteur(df, G, rp, E, o, v, pas=750.0, rayon=1262.0):
  """Indice officiel de qualité d'habitat (Dussault et al. 2006) sur ~500 ha autour de chaque peuplement :
     0,45 × nourriture (moyenne pondérée par la surface) + 0,55 × lisière (m/ha ÷ 30, max 1). Résultat sur 10."""
  import shapely, numpy as np
  FOODC = {"i": 0.4, "a": 0.15, "e": 0.05, "p": 0.3, "h": 0.1, "b": 0.1, "o": 0.1, "r": 0.05}
  fc = np.array([(1.0 if v[k] >= 2.1 else 0.5) if o[k] == "n" else FOODC.get(o[k], 0.0) for k in range(len(o))])
  use = np.array([c not in ("w", "x") for c in o]); A = shapely.area(G)
  X = shapely.get_x(rp); Y = shapely.get_y(rp)
  x0, y0, x1, y1 = X.min(), Y.min(), X.max(), Y.max()
  gx = np.arange(x0, x1 + pas, pas); gy = np.arange(y0, y1 + pas, pas)
  GX, GY = np.meshgrid(gx, gy); GP = shapely.points(GX.ravel(), GY.ravel())
  tp = shapely.STRtree(rp); num_ = np.zeros(len(GP)); den = np.zeros(len(GP)); ed = np.zeros(len(GP))
  EM = shapely.point_on_surface(E) if len(E) else None; EL = shapely.length(E) if len(E) else None
  te_ = shapely.STRtree(EM) if len(E) else None
  for c0 in range(0, len(GP), 2000):
    circ = shapely.buffer(GP[c0:c0 + 2000], rayon, quad_segs=6)
    gi, pi = tp.query(circ, predicate="contains")
    w_ = A[pi] * use[pi]
    num_ += np.bincount(gi + c0, weights=w_ * fc[pi], minlength=len(GP)); den += np.bincount(gi + c0, weights=w_, minlength=len(GP))
    if te_ is not None:
      gj, ej = te_.query(circ, predicate="contains")
      ed += np.bincount(gj + c0, weights=EL[ej], minlength=len(GP))
  sif = np.divide(num_, den, out=np.zeros_like(num_), where=den > 0)
  sie = np.minimum(1.0, ed / (np.pi * rayon * rayon / 10000) / 30.0)
  q = 10 * (0.45 * sif + 0.55 * sie)
  ix = np.clip(np.round((X - x0) / pas).astype(int), 0, len(gx) - 1); iy = np.clip(np.round((Y - y0) / pas).astype(int), 0, len(gy) - 1)
  df["q"] = np.round(q.reshape(len(gy), len(gx))[iy, ix], 1)

ROUTES_OUT = {}
LEVES_OUT = {}
SGM_WFS = "https://servicesvectoriels.atlas.gouv.qc.ca/IDS_SGM_WFS/service.svc/get"
AIR = re.compile(r"air|heli|hélic|aéro|aero|dighem|geotem|vtem|mobile ?mt|drone|uav|falcon|gradiometer|borehole|forage|en puits|infinitem|ztem|spectrom", re.I)
SOL = re.compile(r"induced polari|polarisation|\bIP\b|ground|au sol|line ?cut|coupe de ligne|lignes? coupée|grid|grille|magnetometer|magnétom|\bVLF\b|beep ?mat|horizontal loop|max-?min|gravim|\bEM\b|pulse|time domain|résistivit|resistivit", re.I)
def leves(bb):
  """Levés géophysiques déposés au gouvernement (SIGÉOM, rapports GM) : on garde ceux faits au sol, qui demandent
     souvent de couper des lignes droites (grilles aux 100 m), et ceux dont le type est inconnu."""
  s_, w, n, e = bb; out = []
  for typ in ("SGM:Dem_geophysique_adn", "SGM:Dem_geophysique"):
    q = (f"{SGM_WFS}?service=WFS&version=2.0.0&request=GetFeature&typeNames={typ}&count=5000&srsName=EPSG:4326"
         f"&bbox={s_},{w},{n},{e},urn:ogc:def:crs:EPSG::4326&outputFormat=application/json")
    try: j = json.loads(get(q, tries=3).decode("utf-8", "replace"))
    except Exception as ex: log("levés", typ, repr(ex)); continue
    for f in j.get("features", []):
      pr = f.get("properties") or {}; t = sv(pr.get("TITRE_DOCM"))
      fort = re.search(r"ground|au sol|line ?cut|coupe de ligne|lignes? coupée|grid|grille|induced polari|polarisation|\bIP\b", t, re.I)
      if AIR.search(t) and not fort: continue
      k = "sol" if (fort or SOL.search(t)) else "?"
      out.append({"type": "Feature", "geometry": f.get("geometry"), "properties": {"k": k, "t": t[:140], "a": sv(pr.get("AN_PUBL")) or None,
        "gm": sv(pr.get("NUMR_RAPR")) or None, "u": sv(pr.get("HYPERLIEN")) or None, "c": sv(pr.get("COMPAGNIES"))[:80] or None}})
  log("levés géophysiques au sol ou possibles :", len(out), "sur", "2 couches")
  return out
def routes(df, rp):
  """Routes et chemins d'OpenStreetMap. k : p = route passante (autoroute à collectrice), f = chemin (forestier, local),
     s = sentier ou chemin d'hiver. rd = distance du peuplement à la route passante la plus proche (m)."""
  import shapely, numpy as np
  if os.environ.get("SANS_RESEAU"): df["rd"] = None; return
  b = df.total_bounds; q = (f'[out:json][timeout:240];way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|service|track|path|bridleway)(_link)?$"]'
       f'({b[1]:.4f},{b[0]:.4f},{b[3]:.4f},{b[2]:.4f});out geom tags;')
  raw = None
  hdr = {"User-Agent": "CoachDeCale/1.0 (carte de chasse; +https://coach-de-cale.netlify.app)", "Accept": "application/json,*/*",
         "Content-Type": "application/x-www-form-urlencoded"}
  for url in ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
              "https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass.kumi.systems/api/interpreter") * 2:
    try:
      req = urllib.request.Request(url, data=("data=" + urllib.parse.quote(q)).encode(), headers=hdr)
      with urllib.request.urlopen(req, timeout=300) as r: raw = r.read(); break
    except Exception as ex: log("routes", url, repr(ex)); time.sleep(20)
  if raw is None: df["rd"] = None; return
  feats = []; passant = []
  for w_ in json.loads(raw).get("elements", []):
    g = w_.get("geometry") or []
    if len(g) < 2: continue
    hw = (w_.get("tags") or {}).get("highway", ""); tg = (w_.get("tags") or {}).get("tracktype", "")
    k = "p" if re.match(r"^(motorway|trunk|primary|secondary|tertiary)", hw) else "s" if hw in ("path", "bridleway") or tg in ("grade4", "grade5") else "f"
    ln = shapely.LineString([(x["lon"], x["lat"]) for x in g])
    feats.append({"type": "Feature", "properties": {"k": k, "n": (w_.get("tags") or {}).get("name") or None}, "geometry": shapely.geometry.mapping(ln)})
    if k == "p": passant.append(ln)
  log("routes et chemins (OSM) :", len(feats), "dont", len(passant), "passantes")
  ROUTES_OUT["feats"] = feats
  if not passant: df["rd"] = None; return
  L = gpd.GeoSeries(passant, crs=4326).to_crs(32198).values
  t = shapely.STRtree(L); qi, ti = t.query_nearest(rp, max_distance=1500, return_distance=False, all_matches=False)
  d = np.full(len(rp), np.nan); d[qi] = shapely.distance(rp[qi], L[ti])
  df["rd"] = [None if np.isnan(x) else int(round(x)) for x in d]

# =====================================================================================================
# ---- Cerf de Virginie (automne), d'après le rapport « Chevreuil et carte écoforestière » : clé du MFFP
# (Hébert et al. 2013, Guide d'aménagement des ravages, 4e éd. ; MDPF, fiche Cerf) transposée à l'automne.
# Les 19 classes du rapport (C1-C19) sont regroupées en 10 classes affichables (oc) ; vc = valeur sur 3
# (colonne « Automne » du rapport, après modificateurs M1-M10). Le sous-code C1-C19 reste interne (_sc).
# Regroupement : e = C1 · a = C2, C3 · m = C4, C5 · j = C6, C7, C8 · n = C9, C13 · f = C10 · c = C11, C12
#                u = C14, C15, C16 · p = C17, C18 (+ inconnu, vc 0) · w = C19
_VOIS = {}          # voisinages spatiaux calculés par potentiel() (orignal), réutilisés pour le cerf
RAVAGES_OUT = {}
CERF_CLASSES = {"e": "Abri d'élite (thuya, pruche, sapin)", "a": "Abri (épinettes, pins)", "m": "Nourriture-abri (couche d'automne)",
  "j": "Jeune coupe (brout)", "n": "Nourriture (couvert clair, régénération, mât)", "f": "Friche", "c": "Champ agricole",
  "u": "Peu utilisé (feuillu fermé, mélézaie, aulnaie, plantation)", "p": "Pauvre ou nul (pessière claire, dénudé, tourbière)", "w": "Eau"}
MELEZE = {"ML", "ME", "MJ", "MH"}
RES_CERF = RES_C - MELEZE          # M1 : la clé compte le mélèze comme un feuillu
ABRI_ELITE = {"TO", "PU", "SB"}   # thuya, pruche, sapin : abri + nourriture (MDPF)
ABRI_PAUVRE = {"EN", "PG"}        # épinette noire (et pin gris) : abri partiel, aucune nourriture
MAT = {"CH", "CR", "HG"}          # chênes et hêtre : glands et faînes en sept.-nov.
SC_COUVERT = {"C1", "C2", "C3", "C4", "C5", "C15"}
SC_NOURR = {"C4", "C5", "C6", "C7", "C8", "C9", "C9r", "C10", "C11", "C11-12", "C12", "C13"}   # côté « nourriture » des lisières
SC_M11 = {"C6", "C7", "C8", "C9", "C9r", "C10", "C11", "C11-12", "C12", "C13"}                 # M11 : nourriture loin du couvert
SC_J = {"C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C9r", "C10", "C11", "C11-12", "C13", "C15"}
SC_OUV = {"C6", "C7", "C8", "C9r", "C10", "C11", "C11-12", "C12"}                              # ouvertures du secteur (M16)
OC_FORET = ("e", "a", "m", "j", "n", "u")                                                      # reçoivent C (champ) et Ri (rive)
NOTE_CERF_MAX = 9.2   # maximum avant le 15 novembre (B 5 + J 2 + C 1,5 + Ri 0,7) ; Rv (0,8) s'ajoute dans l'app

def _mesures(r):
  """Hauteur et densité (classes), corrigées par la hauteur et la densité exactes de l'annotation (5e inventaire)."""
  h = sv(r.get("h")); d = sv(r.get("d")).upper(); an = sv(r.get("an")).upper()
  m_ = re.search(r"\*(\d+)%", an); dp = int(m_.group(1)) if m_ else None
  m_ = re.search(r"(\d+(?:\.\d+)?)M\*", an); hm = float(m_.group(1)) if m_ else None
  if hm is not None: h = "1" if hm >= 22 else "2" if hm >= 17 else "3" if hm >= 12 else "4" if hm >= 7 else "5" if hm >= 4 else "6" if hm >= 2 else "7"
  if dp is not None: d = "A" if dp >= 80 else "B" if dp >= 60 else "C" if dp >= 40 else "D"
  return h, d

def _age_cl(g):
  """Classe d'âge en années : 10, 30, 50… (premier étage si étagé) ; VIN/VIR = 90, JIN/JIR = 50 (rapport, C1)."""
  g = sv(g).upper()
  if g.startswith("VI"): return 90
  if g.startswith("JI"): return 50
  m_ = re.match(r"^(\d+)", g)
  if not m_: return None
  s = m_.group(1)
  for k in (3, 2):
    if len(s) >= k and int(s[:k]) in (10, 30, 50, 70, 90, 110, 120, 130): return int(s[:k])
  return int(s[:2])

def _couv(tc, codes):
  """R, MR (mixte à dominance résineuse), MF (mixte à dominance feuillue) ou F, mélèze compté comme feuillu (M1, M2)."""
  first = codes[0] if codes else ""
  if tc == "M": return "MR" if first in RES_CERF else "MF"
  if tc in ("R", "F"): return tc
  if not codes: return ""
  nr = sum(c in RES_CERF for c in codes)
  if nr == len(codes): return "R"
  if nr == 0: return "F"
  return "MR" if first in RES_CERF else "MF"

def _cerf_classe(r):
  """(oc, vc, sous-code) d'un peuplement, avant modificateurs. Table « Classes de peuplement » du rapport."""
  te = sv(r.get("te")).upper(); vp = sv(r.get("vp")).upper(); t = sv(r.get("t")).upper()
  e = sv(r.get("e")).upper(); tc = sv(r.get("tc")).upper(); ori = sv(r.get("or")).upper(); ao = num(r.get("ao"))
  ds = sv(r.get("ds")).upper(); dr = sv(r.get("dr")); h, d = _mesures(r); age = _age_cl(r.get("g"))
  if te in ("EAU", "LAC", "RIV"): return "w", 0.0, "C19"
  if te == "A": return "c", 2.2, "C11"          # la bande de 100 m ; le centre est découpé plus loin (C12)
  if ori == "FR": return "f", 2.4, "C10"
  if te == "AL": return "u", 0.6, "C16"
  if te in ("DH", "INO"): return "p", 0.5, "C17"
  if te in ("DS", "ANT", "ILE") or NONFOR.match(te): return "p", 0.3, "C18"
  codes = _ess(e); first = codes[0] if codes else ""; couv = _couv(tc, codes)
  since = YEAR - ao if (ao and DIST2.match(ori)) else None
  if since is not None:
    since = max(0, since)
    if PLANT.match(ori):
      if since < 50: return "u", 1.4, "C15"
    elif ori.startswith("CHT"):
      if since <= 25: return "u", 0.6, "C16"     # chablis total : « peu utilisé » selon la clé
    else:                                         # coupes, feux, épidémies graves (ES = M8), verglas…
      res = couv == "R"; regen = h in ("5", "6", "7", "")
      if since <= 1: return "j", 1.4, "C7"
      if not res and since <= 7: return "j", 2.4, "C6"
      if res and since <= 4: return "j", 1.8, "C7"   # résineux 2-4 ans : entre débris et pic (conception)
      if res and since <= 15: return "j", 2.4, "C6"
      if regen and since <= 25: return "j", 1.6, "C8"
  if not tc and not codes:
    if vp.startswith("TOB") or vp[:3] in ("RE3", "RS3") or ds.startswith("7") or dr[:1] in ("5", "6"): return "p", 0.5, "C17"
    return "p", 0.0, "X"                            # non forestier sans code de terrain (GFI manquant)
  vpt = vp or t
  if couv in ("R", "MR") and (first in ABRI_PAUVRE or first in MELEZE) and d in ("C", "D") and \
     (ds.startswith("7") or vpt[:2] in ("RE", "RP") or vpt[:3] == "RS2"): return "p", 0.5, "C17"
  if first in MELEZE: return "u", 0.6, "C16"
  if h in ("5", "6", "7"): return "n", 2.0, "C9r"   # régénération (M3 : densité non évaluée sous 4 m)
  if couv in ("F", "MF") and MAT & set(codes[:2]) and (age is None or age >= 50) and h in ("1", "2", "3"): return "n", 2.2, "C13"
  if h in ("1", "2", "3", "4"):
    if couv in ("R", "MR"):
      if d in ("A", "B") and h != "4" and (age is None or age >= 50):
        if ABRI_ELITE & set(codes[:2]): return "e", 2.2, "C1"
        if first in ABRI_PAUVRE: return "a", 1.0, "C3"
        return "a", 1.8, "C2"
      if d == "D": return "n", 2.0, "C9"
      return "m", 2.6, "C4"
    if couv == "MF": return ("n", 2.0, "C9") if d == "D" else ("m", 2.4, "C5")
    if d in ("C", "D") or (age is not None and age < 30): return "n", 2.0, "C9"
    return "u", 1.0, "C14"
  return "n", 1.6, "C9"                             # hauteur inconnue : valeur prudente

def mult_cerf(r, oc, vc, sc):
  """Modificateurs M4-M10 du rapport (perturbations partielles, station). Retourne (oc, vc, sc)."""
  if vc <= 0 or oc in ("w", "c", "f", "p"): return oc, vc, sc
  pe = sv(r.get("pe")).upper(); ap = num(r.get("ap")); ori = sv(r.get("or")).upper(); ao = num(r.get("ao"))
  codes = _ess(sv(r.get("e")).upper()); couv = _couv(sv(r.get("tc")).upper(), codes); h, d = _mesures(r); age = _age_cl(r.get("g"))
  st_ = (sv(r.get("t")) or sv(r.get("vp"))).upper(); ds = sv(r.get("ds")).upper(); dr = sv(r.get("dr"))
  sp = YEAR - ap if ap else None
  if sp is not None and sp < 10 and re.match(r"^(CP|EC)", pe):     # CJ (jardinage, M6) : aucun changement
    if sc in ("C1", "C2", "C3"): oc, vc, sc = "m", 2.6, "C4"        # M5 : l'abri coupé descend en nourriture-abri
    elif couv in ("F", "MF", "MR"): vc *= 1.15                       # M4 : ouverture qui relance le brout
  if pe.startswith("EPC") and sp is not None and sp < 15 and oc in ("j", "n"): vc *= 0.9   # M7
  if pe == "EL" and sc in ("C1", "C2", "C3", "C4"): vc *= 0.8                               # M8
  since = YEAR - ao if (ao and DIST2.match(ori)) else None
  jeune = (since is not None and since < 20) or (since is None and (h in ("5", "6", "7") or age == 10))
  if jeune:
    if st_[:2] in ("FE", "MJ", "MF", "FO") or (ds in ("1A", "1AY") and dr[:1] in ("2", "3")) or ds in ("3AN", "3AE"): vc *= 1.15   # M9
    elif st_[:2] in ("RE", "RS", "RP") or (ds.startswith("2") and dr[:1] in ("0", "1") and "PG" in codes) or \
         (ds[:2] in ("7E", "7T") and ({"EN"} | MELEZE) & set(codes)): vc *= 0.7                                                   # M10
  return oc, round(min(3.0, vc), 3), sc

def classe_cerf(r):
  """Classe cerf d'automne (oc) et valeur sur 3 (vc), modificateurs de peuplement compris."""
  oc, vc, _ = mult_cerf(r, *_cerf_classe(r)); return oc, vc

def _polys(g):
  import shapely
  ps = [p for p in shapely.get_parts(g) if p.geom_type == "Polygon" and p.area > 0]
  return None if not ps else ps[0] if len(ps) == 1 else shapely.MultiPolygon(ps)

def _voisinages(df):
  """Géométries (32198), arbre et paires de voisins : ceux de potentiel() s'ils existent, sinon calculés ici."""
  import shapely
  if _VOIS.get("n") == len(df) and "rp" in _VOIS: return
  G = df.to_crs(32198).geometry.values; bad = ~shapely.is_valid(G)
  if bad.any(): G = G.copy(); G[bad] = shapely.make_valid(G[bad])
  tree = shapely.STRtree(G); L, R = tree.query(shapely.buffer(G, 2), predicate="intersects")
  _VOIS.clear(); _VOIS.update(G=G, tree=tree, L=L, R=R, n=len(df), rp=shapely.point_on_surface(G))

def decouper_champs(df, bande=100.0, mi=200.0):
  """Découpe les terrains agricoles (A) en bande de 0-100 m le long de la forêt (C11, 2,2), bande de 100-200 m
     (interpolée, 1,5) et centre à plus de 200 m (C12, 0,8). La première pièce garde la ligne du champ, les autres
     sont ajoutées à la fin avec les mêmes attributs (l'orignal ne change pas). Met à jour les voisinages partagés."""
  import shapely, numpy as np, pandas as pd
  _voisinages(df)
  G = _VOIS["G"]; tree = _VOIS["tree"]; n = len(df)
  oc = df["oc"].tolist(); sc = df["_sc"].tolist(); vc = df["vc"].tolist()
  foret = np.array([(o in ("e", "a", "m", "n", "u")) or (o == "j" and s != "C7") for o, s in zip(oc, sc)])
  champs = [k for k in range(n) if oc[k] == "c"]
  if not champs: return df
  qi, qj = tree.query(shapely.buffer(G[champs], mi), predicate="intersects")
  vois = {}
  for a_, b_ in zip(qi, qj):
    if foret[b_]: vois.setdefault(champs[a_], []).append(b_)
  remp = {}; extra = []   # remp[k] = géométrie de la 1re pièce ; extra = (parent, géom, vc, sc)
  for k in champs:
    g = G[k]; nb = vois.get(k)
    if not nb: vc[k] = 0.8; sc[k] = "C12"; continue      # aucun bois à 200 m : tout le champ est « centre »
    F = shapely.union_all(G[nb])
    z1 = shapely.intersection(g, shapely.buffer(F, bande, quad_segs=4)); z2 = shapely.intersection(g, shapely.buffer(F, mi, quad_segs=4))
    pcs = [(_polys(z1), 2.2, "C11"), (_polys(shapely.difference(z2, z1)), 1.5, "C11-12"), (_polys(shapely.difference(g, z2)), 0.8, "C12")]
    pcs = [p for p in pcs if p[0] is not None and p[0].area >= 200]
    if not pcs: continue
    if len(pcs) == 1 or sum(p[0].area for p in pcs[1:]) < max(5000, 0.05 * g.area):
      vc[k], sc[k] = pcs[0][1], pcs[0][2]; continue      # champ presque tout en bande : on ne découpe pas
    remp[k] = pcs[0][0]; vc[k], sc[k] = pcs[0][1], pcs[0][2]
    for p in pcs[1:]: extra.append((k, p[0], p[1], p[2]))
  df["vc"] = vc; df["_sc"] = sc
  if not remp: return df
  S = np.array(sorted(remp)); par = [x[0] for x in extra]
  G2 = np.concatenate([G, np.array([x[1] for x in extra], dtype=object)])
  for k, g in remp.items(): G2[k] = g
  g4326 = gpd.GeoSeries(list(G2[S]) + [x[1] for x in extra], crs=32198).to_crs(4326).values
  df = df.copy(); geo = df.geometry.values.copy(); geo[S] = g4326[:len(S)]; df["geometry"] = geo
  add = df.iloc[par].copy(); add["geometry"] = list(g4326[len(S):]); add["vc"] = [x[2] for x in extra]; add["_sc"] = [x[3] for x in extra]
  df = gpd.GeoDataFrame(pd.concat([df, add], ignore_index=True), geometry="geometry", crs=df.crs)
  # Voisinages : on garde les paires qui ne touchent pas un champ découpé, et on ajoute celles des pièces
  L, R = _VOIS["L"], _VOIS["R"]; keep = ~(np.isin(L, S) | np.isin(R, S))
  P = np.concatenate([S, np.arange(n, len(G2))]); B = shapely.buffer(G2[P], 2)
  a_, b_ = tree.query(B, predicate="intersects"); m_ = ~np.isin(b_, S)
  t2 = shapely.STRtree(G2[P]); a2, b2 = t2.query(B, predicate="intersects")
  L2 = np.concatenate([L[keep], P[a_[m_]], b_[m_], P[a2]]); R2 = np.concatenate([R[keep], b_[m_], P[a_[m_]], P[b2]])
  rp = np.concatenate([_VOIS["rp"], shapely.point_on_surface(G2[n:])]); rp[S] = shapely.point_on_surface(G2[S])
  _VOIS.update(G=G2, tree=None, L=L2, R=R2, n=len(G2), rp=rp)
  log("champs découpés en bandes :", len(S), "champs,", len(extra), "pièces ajoutées")
  return df

def potentiel_cerf(df, rav=None):
  """Note cerf d'automne sur 10 (rapport, « Formule de note recommandée ») :
     brute = B × M11 + J + C + Ri ; B = vc / 3 × 5 ; J = 2 × min(1, lisière couvert-nourriture / 70 m/ha) sur 10 ha ;
     C (forêt-champ) = 1,5 à ≤ 100 m d'un champ ou d'une friche, 0,9 à ≤ 400 m, 0,45 à ≤ 800 m ; Ri (rive) = 0,7 à ≤ 150 m
     de l'eau, 0,3 à ≤ 300 m ; M11 = × 0,5 si la nourriture est à plus de 220 m de tout couvert.
     pc = 10 × brute / 9,2 (maximum avant le 15 nov.). Rv (ravage) n'est pas inclus : l'app l'ajoute après le 15 nov.
     avec rv (pc_fin = pc × 0,92 + Rv). Poids : peuplement 50 %, juxtaposition 20 %, champ 15 %, rive 7 %, ravage 8 %."""
  import shapely, numpy as np
  _voisinages(df)
  G, L, R, rp = _VOIS["G"], _VOIS["L"], _VOIS["R"], _VOIS["rp"]; n = len(df)
  oc = np.array(df["oc"].tolist(), dtype=object); sc = df["_sc"].tolist(); vc = df["vc"].astype(float).to_numpy()
  isC = np.array(df["_cv"].tolist(), dtype=bool); isF = np.array([s in SC_NOURR for s in sc])
  # J : lisières couvert-nourriture (lignes partagées), densité en m/ha dans un cercle de 180 m (10 ha)
  m_ = (L < R) & (oc[L] != oc[R]) & ((isC[L] & isF[R]) | (isF[L] & isC[R]))
  pa, pb = L[m_], R[m_]; dens = np.zeros(n); propre = np.zeros(n)
  if len(pa):
    E = shapely.intersection(shapely.boundary(G[pa]), shapely.buffer(G[pb], 2)); ok = ~shapely.is_empty(E)
    E, pa, pb = E[ok], pa[ok], pb[ok]
    if len(E):
      circ = shapely.buffer(rp, 180, quad_segs=8); ci, ei = shapely.STRtree(E).query(circ, predicate="intersects")
      np.add.at(dens, ci, shapely.length(shapely.intersection(E[ei], circ[ci])))
      dens = dens / (np.pi * 180 * 180 / 10000)
      le = shapely.length(E); np.add.at(propre, pa, le); np.add.at(propre, pb, le)
  # Bande de champ (longue et étroite) : son point représentatif peut tomber loin de la lisière ; on prend aussi
  # sa propre lisière avec le couvert divisée par sa surface (100 m de bois en bordure = 1 ha de bande ≈ 100 m/ha)
  bande = np.array([s in ("C11", "C11-12") for s in sc])
  if bande.any():
    dens[bande] = np.maximum(dens[bande], propre[bande] / np.maximum(shapely.area(G[bande]) / 10000, 1.0))
  def proche(src, cible, maxd):
    d = np.full(len(src), np.nan); ci = np.flatnonzero(cible)
    if len(ci) and len(src):
      (qi, ti), dd = shapely.STRtree(G[ci]).query_nearest(src, max_distance=maxd, return_distance=True, all_matches=False)
      d[qi] = dd
    return d
  champ = np.isin(oc, ["c", "f"])
  ag = proche(G, champ, 3000.0); ag[champ] = 0.0; ag[oc == "w"] = np.nan
  dw = proche(G, oc == "w", 300.0)
  dcov = proche(rp, isC, 220.0)
  if bande.any(): dcov[bande] = proche(G[bande], isC, 220.0)   # la bande longe le bois par construction
  rvd = None
  if rav:
    try:
      RG = gpd.GeoSeries([shapely.geometry.shape(f["geometry"]) for f in rav], crs=4326).to_crs(32198).values
      RG = shapely.make_valid(RG); rvd = np.full(n, np.nan)
      (qi, ti), dd = shapely.STRtree(RG).query_nearest(G, max_distance=30000.0, return_distance=True, all_matches=False)
      rvd[qi] = dd
    except Exception: log("ravages distance ERREUR", traceback.format_exc()); rvd = None
  P = np.zeros(n); Jv = np.where(np.isin(sc, list(SC_J)), 2.0 * np.minimum(1.0, dens / 70.0), 0.0)
  foret = np.isin(oc, OC_FORET)
  Cv = np.where(foret & (ag <= 100), 1.5, np.where(foret & (ag <= 400), 0.9, np.where(foret & (ag <= 800), 0.45, 0.0)))
  Ri = np.where(foret & (dw <= 150), 0.7, np.where(foret & (dw <= 300), 0.3, 0.0))
  m11 = np.where(np.isin(sc, list(SC_M11)) & ~(dcov <= 220), 0.5, 1.0)
  B = vc / 3 * 5.0 * m11
  brute = B + Jv + Cv + Ri
  P = np.where((oc == "w") | (vc <= 0), 0.0, np.minimum(10.0, 10 * brute / NOTE_CERF_MAX))
  df["vc"] = np.round(vc, 2); df["pc"] = np.round(P, 1)
  df["ag"] = pd_int(ag); df["rv"] = pd_int(rvd) if rvd is not None else pd_int(np.full(n, np.nan))
  try: secteur_cerf(df, G, rp, oc, sc)
  except Exception: log("secteur cerf ERREUR", traceback.format_exc()); df["qc"] = None

def pd_int(a):
  import pandas as pd, numpy as np
  return pd.array([None if np.isnan(x) else int(round(x)) for x in a], dtype="Int64")

def _rampe(x, x0, y0, x1, y1): return y0 + (y1 - y0) * min(1.0, max(0.0, (x - x0) / (x1 - x0)))
def secteur_cerf(df, G, rp, oc, sc, pas=500.0, rayon=800.0):
  """Couche secteur cerf (M16) sur ~200 ha autour de chaque peuplement : indice 1 si les ouvertures (champ, friche,
     coupes et régénération : C6-C8, C9r, C10-C12) font 15-50 % et l'abri + nourriture-abri (C1-C5) ≥ 25 % ;
     0,5 si ouvertures < 10 % ; 0,6 si > 70 %. Entre ces seuils : interpolation linéaire, et abri sous 25 % :
     0,5 + 0,5 × part/25 % (choix de conception). Résultat sur 10."""
  import shapely, numpy as np
  A = shapely.area(G); use = np.array([o != "w" and s != "X" for o, s in zip(oc, sc)])
  ouv = np.array([s in SC_OUV for s in sc]); abri = np.array([s in ("C1", "C2", "C3", "C4", "C5") for s in sc])
  X = shapely.get_x(rp); Y = shapely.get_y(rp); x0, y0, x1, y1 = X.min(), Y.min(), X.max(), Y.max()
  gx = np.arange(x0, x1 + pas, pas); gy = np.arange(y0, y1 + pas, pas)
  GX, GY = np.meshgrid(gx, gy); GP = shapely.points(GX.ravel(), GY.ravel())
  tp = shapely.STRtree(rp); den = np.zeros(len(GP)); no = np.zeros(len(GP)); na = np.zeros(len(GP))
  for c0 in range(0, len(GP), 2000):
    circ = shapely.buffer(GP[c0:c0 + 2000], rayon, quad_segs=6)
    gi, pi = tp.query(circ, predicate="contains"); w_ = A[pi] * use[pi]
    den += np.bincount(gi + c0, weights=w_, minlength=len(GP))
    no += np.bincount(gi + c0, weights=w_ * ouv[pi], minlength=len(GP)); na += np.bincount(gi + c0, weights=w_ * abri[pi], minlength=len(GP))
  fo = np.divide(no, den, out=np.zeros_like(no), where=den > 0) * 100; fa = np.divide(na, den, out=np.zeros_like(na), where=den > 0) * 100
  io = np.array([0.5 if x < 10 else _rampe(x, 10, 0.5, 15, 1.0) if x < 15 else 1.0 if x <= 50 else _rampe(x, 50, 1.0, 70, 0.6) for x in fo])
  ia = np.array([1.0 if x >= 25 else 0.5 + 0.5 * x / 25 for x in fa])
  q = np.where(den > 0, 10 * io * ia, 0.0)
  ix = np.clip(np.round((X - x0) / pas).astype(int), 0, len(gx) - 1); iy = np.clip(np.round((Y - y0) / pas).astype(int), 0, len(gy) - 1)
  df["qc"] = np.round(q.reshape(len(gy), len(gx))[iy, ix], 1)

def cerf(df, rav=None):
  """Classe, valeur, note et secteur cerf. Retourne le df (champs agricoles découpés en bandes)."""
  keys = list(FIELDS) + ["vp", "cg", "st", "an"]
  recs = df[keys].to_dict("records"); out = []; cv = []
  for r in recs:
    oc, vc, sc = mult_cerf(r, *_cerf_classe(r)); h, d = _mesures(r)
    out.append((oc, vc, sc)); cv.append(sc in SC_COUVERT or (h in ("5", "6") and d in ("A", "B") and oc not in ("w", "c", "f", "p")))
  df["oc"] = [x[0] for x in out]; df["vc"] = [x[1] for x in out]; df["_sc"] = [x[2] for x in out]; df["_cv"] = cv
  df = decouper_champs(df)
  potentiel_cerf(df, rav)
  return df

RAV_WFS = "https://servicesvecto3.mern.gouv.qc.ca/geoserver/Habitats_Fauniques_Pub/wfs"
_RAV_TOUT = {}
def ravages(bb, marge_km=30.0):
  """Aires de confinement du cerf (ravages légaux) du GeoServer Habitats fauniques (MRNF), couche Habitat_legal,
     champ CATEGORIE = « Aire de confinement du cerf de Virginie ». Le service refuse (403) toute requête avec un
     en-tête Origin : urllib n'en envoie pas. On garde les aires à moins de 30 km du feuillet (bassin d'un ravage).
     Retourne une liste d'entités GeoJSON, ou None si le service est injoignable."""
  import shapely, math
  s_, w, n, e = bb; dl = marge_km / 111.0; dg = marge_km / (111.0 * math.cos(math.radians((s_ + n) / 2)))
  box = shapely.box(w - dg, s_ - dl, e + dg, n + dl)
  base = (f"{RAV_WFS}?service=WFS&version=2.0.0&request=GetFeature&typeNames=Habitats_Fauniques_Pub:Habitat_legal"
          f"&srsName=EPSG:4326&outputFormat=application/json&CQL_FILTER=")
  filt = "CATEGORIE LIKE 'Aire de confinement du cerf%'"
  feats = None
  try:
    q = base + urllib.parse.quote(filt + f" AND BBOX(SHAPE,{w - dg:.4f},{s_ - dl:.4f},{e + dg:.4f},{n + dl:.4f},'EPSG:4326')")
    feats = json.loads(get(q, tries=2).decode("utf-8", "replace")).get("features")
  except Exception as ex: log("ravages (bbox)", repr(ex))
  if not feats:   # filtre bbox refusé ou vide : toutes les aires de cerf du Québec (~11 Mo), une fois par run
    if "f" not in _RAV_TOUT:
      try: _RAV_TOUT["f"] = json.loads(get(base + urllib.parse.quote(filt), tries=3).decode("utf-8", "replace")).get("features", [])
      except Exception as ex: log("ravages (toutes)", repr(ex)); _RAV_TOUT["f"] = None
    feats = _RAV_TOUT["f"]
  if feats is None: return None
  out = []
  for f in feats:
    pr = f.get("properties") or {}
    if not re.search(r"confinement.*cerf", sv(pr.get("CATEGORIE")), re.I) or not f.get("geometry"): continue
    try:
      if not shapely.geometry.shape(f["geometry"]).intersects(box): continue
    except Exception: continue
    try: ha = round(float(sv(pr.get("SUP_HA")) or "nan"), 1)
    except ValueError: ha = None
    out.append({"type": "Feature", "geometry": f["geometry"], "properties": {"n": sv(pr.get("TOPONYME")) or None,
      "ha": None if ha != ha else ha, "dt": sv(pr.get("DA_ENT_VIG"))[:10] or None}})
  log("ravages (aires de confinement du cerf) à moins de", marge_km, "km :", len(out), [x["properties"]["n"] for x in out])
  return out

def layer_of(path):
  lays = pyogrio.list_layers(path)
  best = None
  for name, geom in lays:
    if geom and "POLYGON" in str(geom).upper():
      n = pyogrio.read_info(path, layer=name)["features"]
      score = n * (3 if re.search(r"PEE|PEUPL|ECO", name, re.I) else 1)
      if not best or score > best[0]: best = (score, name)
  return best[1] if best else lays[0][0]

def process(fid, gpkg, bb=None, budget=None):
  RAVAGES_OUT.clear(); rav = None
  lay = layer_of(gpkg) if gpkg.endswith(".gpkg") else pyogrio.list_layers(gpkg)[0][0]
  info = pyogrio.read_info(gpkg, layer=lay); cols = list(info["fields"])
  m = {k: pick(cols, v) for k, v in FIELDS.items()}; idc = pick(cols, [r"^ogc_fid$", r"^OBJECTID$", r"^GEOCODE$"])
  with open(f"{OUT}/schema-{fid}.txt", "w") as f:
    f.write(f"couche: {lay}\nentités: {info['features']}\ncrs: {info['crs']}\nchamps: {cols}\ncorrespondance: {json.dumps(m)}\n")
  log(fid, "couche", lay, info["features"], "entités", json.dumps(m))
  use = [c for c in m.values() if c] + ([idc] if idc else [])
  df = gpd.read_file(gpkg, layer=lay, columns=use, engine="pyogrio")
  df = df.rename(columns={v: k for k, v in m.items() if v})
  if idc: df = df.rename(columns={idc: "fid"})
  else: df["fid"] = range(len(df))
  for k in FIELDS:
    if k not in df: df[k] = None
  df = df.to_crs(4326).reset_index(drop=True)
  for k in ("vp", "cg", "st", "an"): df[k] = None
  if bb and not os.environ.get("SANS_RESEAU"):
    try: maj_perturb(df, fid, bb)
    except Exception: log("maj_perturb ERREUR", traceback.format_exc())
    try: LEVES_OUT["feats"] = leves(bb)
    except Exception: log("levés ERREUR", traceback.format_exc())
    try: rav = ravages(bb)
    except Exception: log("ravages ERREUR", traceback.format_exc())
    if rav: RAVAGES_OUT["feats"] = rav
    try: gfi_enrich(df, fid, budget_s=budget or int(os.environ.get("GFI_BUDGET", 70 * 60)))
    except Exception: log("gfi ERREUR", traceback.format_exc())
  keys = list(FIELDS) + ["vp", "cg", "st", "an"]
  cs = [classe(r) for r in df[keys].to_dict("records")]
  recs = df[keys].to_dict("records")
  df["o"] = [c[0] for c in cs]; df["s"] = [c[2] for c in cs]; df["v"] = [mult(r, c[0], c[1]) for r, c in zip(recs, cs)]
  potentiel(df)
  # Cerf de Virginie : propriétés oc, vc, pc, qc, ag, rv dans les mêmes tuiles (l'orignal ne change pas)
  try: df = cerf(df, rav)
  except Exception:
    log("cerf ERREUR", traceback.format_exc())
    for k in ("oc", "vc", "pc", "qc", "ag", "rv"): df[k] = None
  df["st"] = df["st"].map(lambda x: sv(x) or None)
  def humide(r):
    t = sv(r.get("t")).upper(); dr = sv(r.get("dr")); tc = sv(r.get("tc"))
    if not tc: return 0
    if len(t) >= 4 and t[3] in "456": return 1
    if len(t) >= 4 and t[3] in "789": return 2
    return 1 if dr[:1] in ("4", "5") else 2 if dr[:1] == "6" else 0
  df["fh"] = [humide(r) for r in df[["t", "dr", "tc"]].to_dict("records")]
  for k in list(FIELDS) + ["vp", "cg", "an"]:
    if k in ("ao", "ap"): df[k] = df[k].map(lambda v: num(v) or None).astype("Int64")
    else: df[k] = df[k].map(lambda v: re.sub(r"\.0$", "", sv(v)) or None).astype("object")
  with open(f"{OUT}/schema-{fid}.txt", "a") as f:
    f.write("classes: " + json.dumps(df["o"].value_counts().to_dict()) + "\n")
    f.write("classes cerf: " + json.dumps(df["oc"].value_counts().to_dict()) + "\n")
    if "_sc" in df: f.write("sous-classes cerf: " + json.dumps(df["_sc"].value_counts().to_dict()) + "\n")
    f.write("exemples:\n" + df.drop(columns="geometry").head(8).to_string() + "\n")
  df = df.drop(columns=["fid"] + [c for c in ("_sc", "_cv") if c in df])
  nd = f"{TMP}/{fid}.geojsonl"; df.to_file(nd, driver="GeoJSONSeq", engine="pyogrio")
  out = f"{OUT}/{fid}.pmtiles"
  if os.environ.get("SANS_TIPPECANOE"): return {"id": fid, "entites": int(len(df)), "classes": df["o"].value_counts().to_dict(),
                                                "classes_cerf": df["oc"].value_counts().to_dict()}
  rdf = None
  if ROUTES_OUT.get("feats"):
    rdf = f"{TMP}/{fid}-routes.geojsonl"
    with open(rdf, "w") as f:
      for ft in ROUTES_OUT["feats"]: f.write(json.dumps(ft) + "\n")
  ROUTES_OUT.clear()
  cmd = ["tippecanoe", "-o", out, "--force", "-Z", "10", "-z", "15", "--coalesce-smallest-as-needed", "--detect-shared-borders",
         "--simplify-only-low-zooms", "--no-tile-stats", "-q", "-P", "-L", "pee:" + nd]
  if rdf: cmd += ["-L", "routes:" + rdf]
  if LEVES_OUT.get("feats"):
    lv = f"{TMP}/{fid}-leves.geojsonl"
    with open(lv, "w") as f:
      for ft in LEVES_OUT["feats"]:
        if ft.get("geometry"): f.write(json.dumps(ft) + "\n")
    cmd += ["-L", "leves:" + lv]
  LEVES_OUT.clear()
  nrav = 0
  if RAVAGES_OUT.get("feats"):
    rv_ = f"{TMP}/{fid}-ravages.geojsonl"
    with open(rv_, "w") as f:
      for ft in RAVAGES_OUT["feats"]: f.write(json.dumps(ft) + "\n"); nrav += 1
    cmd += ["-L", "ravages:" + rv_]
  RAVAGES_OUT.clear()
  subprocess.run(cmd, check=True)
  b = df.total_bounds
  return {"id": fid, "url": f"{fid}.pmtiles", "bbox": [round(float(x), 4) for x in b], "taille": os.path.getsize(out), "entites": int(len(df)), "champs": m, "ravages": nrav}

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

T0 = time.time()
def gfi_budget(restantes):
  """Budget GFI d'une zone : GFI_BUDGET (70 min) au plus, mais on garde ~35 min de traitement par zone restante
     après celle-ci (WFS, perturbations, notes, tippecanoe) pour finir sous DUREE_MAX (270 min ; timeout du workflow : 300 min)."""
  base = int(os.environ.get("GFI_BUDGET", 70 * 60)); total = int(os.environ.get("DUREE_MAX", 270 * 60))
  reste = total - (time.time() - T0) - 35 * 60 * restantes - 15 * 60   # + ~15 min pour finir la zone en cours
  return int(max(5 * 60, min(base, reste)))

def main():
  args = sys.argv[1:]; done = []
  if args and args[0] == "--zone":   # essai rapide : --zone nom;s;w;n;e
    nom, a, b, c, d = args[1].split(";"); g = wfs_zone(nom, float(a), float(b), float(c), float(d)); done.append(process(nom, g, (float(a), float(b), float(c), float(d))))
  elif args and args[0] == "--test":
    done.append(process("TEST", args[1]))
  elif os.path.exists("zones.txt"):
    zs = [l.strip() for l in open("zones.txt") if l.strip() and not l.strip().startswith("#")]
    for iz, l in enumerate(zs):
      nom, a, b, c, d = [x.strip() for x in l.split(";")]
      try:
        g = wfs_zone(nom, float(a), float(b), float(c), float(d))
        bud = gfi_budget(len(zs) - iz - 1); log(nom, "budget GFI :", bud // 60, "min ; écoulé :", int((time.time() - T0) / 60), "min")
        r = process(nom, g, (float(a), float(b), float(c), float(d)), budget=bud); r["bbox"] = [float(b), float(a), float(d), float(c)]; done.append(r)
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
  cl_o = {"i": "Idéal (mixte mature)", "a": "Abri avec sapin", "e": "Abri d'épinette noire", "n": "Nourriture", "h": "Humide riche", "b": "Humide pauvre", "p": "Passage", "o": "Ouvert récent", "r": "Résineux peu utile", "w": "Eau", "x": "Non forestier"}
  idx = {"maj": datetime.date.today().isoformat(), "annee_ref": YEAR, "source": "MRNF, Carte écoforestière à jour (CC-BY 4.0)",
         "modele": 2, "classes": cl_o,
         "especes": {"orignal": {"classes": cl_o},
                     "cerf": {"modele": 1, "classes": CERF_CLASSES,
                              "proprietes": {"oc": "classe", "vc": "valeur de la classe sur 3", "pc": "note d'automne sur 10 (avant le 15 nov.)",
                                             "qc": "secteur sur 10 (~200 ha)", "ag": "distance au champ ou à la friche (m, max 3000)",
                                             "rv": "distance au ravage (m, 0 = dedans, max 30000)"},
                              "fin_saison": "après le 15 nov. ou 20 cm de neige : pc × 0,92 + Rv, Rv = 0,8 si rv = 0, 0,5 si rv ≤ 3000, 0,25 si rv ≤ 10000",
                              "couche_ravages": "ravages", "source_ravages": "MRNF, Habitats fauniques (Habitat_legal), aires de confinement du cerf de Virginie"}},
         "feuillets": done}
  json.dump(idx, open(f"{OUT}/index.json", "w"), ensure_ascii=False, indent=1)
  open(f"{OUT}/.nojekyll", "w").close()
  log(json.dumps(idx, ensure_ascii=False)[:800])
  open(f"{OUT}/journal.txt", "w").write("\n".join(LOG))

if __name__ == "__main__": main_safe()
