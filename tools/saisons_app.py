"""Convertit research_notes/zones/saisons-2026.json en fichier compact pour l'app (zones-saisons.json), en bon français."""
import json, re, sys
src, dst = sys.argv[1], sys.argv[2]
d = json.load(open(src))
ANI = {
 "orignal avec bois (male adulte, bois >= 10 cm) ; OSB (femelle ou veau, bois < 10 cm) seulement avec permis OSB gagne au tirage pour cette zone":
   "Mâle (bois de 10 cm et plus). Femelle ou veau : seulement avec un permis gagné au tirage",
 "cerf avec bois (male adulte, bois >= 7 cm)": "Avec bois de 7 cm et plus",
 "avec ou sans bois": "Avec ou sans bois",
 "femelle ou male a bois de moins de 7 cm seulement (sans bois)": "Sans bois seulement (femelle, ou mâle avec bois de moins de 7 cm)",
 "avec bois RTLB (au moins 3 pointes de 2,5 cm ou plus d'un cote) ou sans bois": "Avec bois d'au moins 3 pointes de 2,5 cm d'un côté, ou sans bois",
 "avec bois RTLB (au moins 3 pointes de 2,5 cm ou plus d'un cote)": "Avec bois d'au moins 3 pointes de 2,5 cm d'un côté",
 "tout orignal (segment \"Orignal\") : avec bois et OSB permis a l'arc/arbalete en 2026 (exception a l'alternance)": "Tout orignal, avec ou sans bois (exception de 2026 à l'arc et à l'arbalète)",
 "orignal avec bois (male adulte, bois >= 10 cm) seulement (alternance : 2026 = annee restrictive, OSB ferme ; OSB rouvert en 2027)": "Mâle seulement (bois de 10 cm et plus) : 2026 est une année restrictive, le sans bois rouvre en 2027",
 "tout orignal : avec bois et OSB (femelle, veau), sans permis special": "Tout orignal, avec ou sans bois, sans permis spécial",
 "orignal avec bois (male adulte, bois >= 10 cm)": "Mâle (bois de 10 cm et plus)",
 "tout orignal (segment \"Orignal\")": "Tout orignal, avec ou sans bois",
}
W = [("Periode", "Période"), ("periode", "période"), ("Releve", "Relève"), ("releve", "relève"), ("certifies", "certifiés"), ("numero", "numéro"),
     ("Macpes", "Macpès"), ("Arbalete", "Arbalète"), ("arbalete", "arbalète"), ("Iles", "Îles"), ("iles", "îles"), ("ile d", "île d"), ("ilots", "îlots"), ("sejour", "séjour"),
     ("Appatage", "Appâtage"), ("annee", "année"), ("jusqu'a", "jusqu'à"), ("Quebec", "Québec"), ("Beaupre", "Beaupré"), ("regles", "règles"),
     ("verifier", "vérifier"), ("declin", "déclin"), ("publiee", "publiée"), ("fermee", "fermée"), ("Riviere", "Rivière"), ("cote", "côté"),
     ("specia", "spécia"), ("prive", "privé"), ("deja", "déjà"), ("Duquesne", "Duquesne")]
def fr(t):
  if not t: return ""
  t = re.sub(r"\s*Rel[eè]ve list[eé]e pour 3 est.*$", "", t)
  if "ZSR" in t: return "Partie à règles particulières : dates de la zone voisine, à vérifier dans le règlement."
  t = re.sub(r"\s*\(verifier dans quelle sous-zone ils se trouvent\)", "", t)
  t = re.sub(r"\s*:\s*a confirmer au 1 877 346-6763\.?", ". À confirmer au 1 877 346-6763.", t)
  t = re.sub(r"\s*[;:]?\s*a confirmer\.?$", ". À confirmer.", t)
  t = t.replace("(voir 8nmr)", "(voir Zone 8 nord · montagne de Rigaud)").replace(" : voir 'territoires'.", " (voir plus bas).")
  for a, b in W: t = re.sub(r"\b" + a, b, t)
  t = re.sub(r"(?<!['’])\ba\b", "à", t)
  return t.strip()
ENG = {"arc": "arc", "arbalete": "arbalète", "carabine": "carabine", "fusil": "fusil", "acb": "chargement par la bouche"}
def per(L): return [[p["du"], p["au"], [ENG.get(e, e) for e in p.get("engins", [])], ANI.get(p.get("animaux", ""), fr(p.get("animaux", ""))), fr(p.get("note", ""))] for p in L]
def nom(n):
  t = n.replace(" - ", " · ").replace("partie ZSR", "partie à règles particulières").replace("(reste, hors sud-ouest)", "(hors sud-ouest)")
  for a, b in W: t = re.sub(r"\b" + a, b, t)
  return t
Z = {}
for k, v in d["zones"].items():
  e = {"n": nom(v["nom"]), "o": per(v.get("orignal", [])), "c": per(v.get("cerf", []))}
  notes = v.get("notes") or {}
  if notes.get("orignal"): e["xo"] = fr(notes["orignal"])
  if notes.get("cerf"): e["xc"] = fr(notes["cerf"])
  Z[v["code_wfs"].upper()] = e
T = {}
for k, v in (d.get("territoires") or {}).items():
  T[k] = {"n": nom(v["nom"]), "o": per(v.get("orignal", [])), "c": per(v.get("cerf", []))}
out = {"v": d.get("version", "2026"), "maj": d.get("maj"), "valide": "2027-03-31",
       "src": {"orignal": "https://www.quebec.ca/tourisme-loisirs-sport/activites-sportives-et-de-plein-air/chasse-sportive/periodes-limites/orignal",
               "cerf": "https://www.quebec.ca/tourisme-loisirs-sport/activites-sportives-et-de-plein-air/chasse-sportive/periodes-limites/cerf-virginie"},
       "z": Z, "t": T}
s = json.dumps(out, ensure_ascii=False, separators=(",", ":")); open(dst, "w").write(s)
print(len(Z), "zones,", len(T), "territoires,", len(s.encode()) // 1024, "Ko")
