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
GFI_KEYS = {"co_ter": "te", "veg_pot": "vp", "couv_gaule": "cg", "st_ha_tot": "st", "annotation": "an"}
FEU = re.compile(r"BP|PE|PT|FI|FX|FN|ER|BJ|PEU|FT|PU|BB|AU")
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
      if o2 and a2 and a2 > (num(df.at[idx, "ao"]) or 0): df.at[idx, "or"] = o2; df.at[idx, "ao"] = a2; nmaj += 1
      elif p2 and b2 and b2 > (num(df.at[idx, "ap"]) or 0): df.at[idx, "pe"] = p2; df.at[idx, "ap"] = b2; nmaj += 1
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

def routes(df, rp):
  """Distance à la route passante la plus proche (OpenStreetMap : autoroute, nationale, régionale, collectrice)."""
  import shapely, numpy as np
  if os.environ.get("SANS_RESEAU"): df["rd"] = None; return
  b = df.total_bounds; q = (f'[out:json][timeout:180];way["highway"~"^(motorway|trunk|primary|secondary|tertiary)(_link)?$"]'
       f'({b[1]:.4f},{b[0]:.4f},{b[3]:.4f},{b[2]:.4f});out geom;')
  raw = None
  for url in ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"):
    try:
      req = urllib.request.Request(url, data=("data=" + urllib.parse.quote(q)).encode(), headers=UA)
      with urllib.request.urlopen(req, timeout=240) as r: raw = r.read(); break
    except Exception as ex: log("routes", url, repr(ex))
  if raw is None: df["rd"] = None; return
  ways = [w_ for w_ in json.loads(raw).get("elements", []) if w_.get("geometry")]
  log("routes passantes (OSM) :", len(ways))
  if not ways: df["rd"] = None; return
  L = gpd.GeoSeries([shapely.LineString([(g["lon"], g["lat"]) for g in w_["geometry"]]) for w_ in ways if len(w_["geometry"]) > 1], crs=4326).to_crs(32198).values
  t = shapely.STRtree(L); qi, ti = t.query_nearest(rp, max_distance=1500, return_distance=False, all_matches=False)
  d = np.full(len(rp), np.nan); d[qi] = shapely.distance(rp[qi], L[ti])
  df["rd"] = [None if np.isnan(x) else int(round(x)) for x in d]

def layer_of(path):
  lays = pyogrio.list_layers(path)
  best = None
  for name, geom in lays:
    if geom and "POLYGON" in str(geom).upper():
      n = pyogrio.read_info(path, layer=name)["features"]
      score = n * (3 if re.search(r"PEE|PEUPL|ECO", name, re.I) else 1)
      if not best or score > best[0]: best = (score, name)
  return best[1] if best else lays[0][0]

def process(fid, gpkg, bb=None):
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
    try: gfi_enrich(df, fid, budget_s=int(os.environ.get("GFI_BUDGET", 70 * 60)))
    except Exception: log("gfi ERREUR", traceback.format_exc())
  keys = list(FIELDS) + ["vp", "cg", "st", "an"]
  cs = [classe(r) for r in df[keys].to_dict("records")]
  recs = df[keys].to_dict("records")
  df["o"] = [c[0] for c in cs]; df["s"] = [c[2] for c in cs]; df["v"] = [mult(r, c[0], c[1]) for r, c in zip(recs, cs)]
  potentiel(df)
  df["st"] = df["st"].map(lambda x: sv(x) or None)
  for k in list(FIELDS) + ["vp", "cg", "an"]:
    if k in ("ao", "ap"): df[k] = df[k].map(lambda v: num(v) or None).astype("Int64")
    else: df[k] = df[k].map(lambda v: re.sub(r"\.0$", "", sv(v)) or None).astype("object")
  with open(f"{OUT}/schema-{fid}.txt", "a") as f:
    f.write("classes: " + json.dumps(df["o"].value_counts().to_dict()) + "\n")
    f.write("exemples:\n" + df.drop(columns="geometry").head(8).to_string() + "\n")
  df = df.drop(columns=["fid"])
  nd = f"{TMP}/{fid}.geojsonl"; df.to_file(nd, driver="GeoJSONSeq", engine="pyogrio")
  out = f"{OUT}/{fid}.pmtiles"
  if os.environ.get("SANS_TIPPECANOE"): return {"id": fid, "entites": int(len(df)), "classes": df["o"].value_counts().to_dict()}
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
    nom, a, b, c, d = args[1].split(";"); g = wfs_zone(nom, float(a), float(b), float(c), float(d)); done.append(process(nom, g, (float(a), float(b), float(c), float(d))))
  elif args and args[0] == "--test":
    done.append(process("TEST", args[1]))
  elif os.path.exists("zones.txt"):
    for l in open("zones.txt"):
      l = l.strip()
      if not l or l.startswith("#"): continue
      nom, a, b, c, d = [x.strip() for x in l.split(";")]
      try:
        g = wfs_zone(nom, float(a), float(b), float(c), float(d))
        r = process(nom, g, (float(a), float(b), float(c), float(d))); r["bbox"] = [float(b), float(a), float(d), float(c)]; done.append(r)
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
         "modele": 2, "classes": {"i": "Idéal (mixte mature)", "a": "Abri avec sapin", "e": "Abri d'épinette noire", "n": "Nourriture", "h": "Humide riche", "b": "Humide pauvre", "p": "Passage", "o": "Ouvert récent", "r": "Résineux peu utile", "w": "Eau", "x": "Non forestier"}, "feuillets": done}
  json.dump(idx, open(f"{OUT}/index.json", "w"), ensure_ascii=False, indent=1)
  open(f"{OUT}/.nojekyll", "w").close()
  log(json.dumps(idx, ensure_ascii=False)[:800])
  open(f"{OUT}/journal.txt", "w").write("\n".join(LOG))

if __name__ == "__main__": main_safe()
