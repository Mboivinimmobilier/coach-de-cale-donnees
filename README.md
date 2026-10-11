# Coach de câle — données de la carte écoforestière

Ce dépôt prépare automatiquement la **Carte écoforestière à jour** du Québec pour l'app Coach de câle.

- Source : Ministère des Ressources naturelles et des Forêts (MRNF), *Carte écoforestière à jour*, licence **CC-BY 4.0** (Données Québec).
- Traitement : pour chaque zone listée dans `zones.txt` (téléchargée par le service WFS officiel), le script garde les champs utiles et ajoute une **classe « orignal »** par peuplement
  (i = idéal/mixte, n = nourriture, a = abri, h = humide (tourbière, dénudé humide : dépôt organique ou mauvais drainage), o = ouvert récent, r = résineux peu utile, w = eau).
- Résultat : un fichier `zone.pmtiles` par zone, publié sur GitHub Pages, + `index.json`.
- Mise à jour : chaque année en juillet, ou quand on modifie `zones.txt`.

Les classes « orignal » sont des repères indicatifs tirés de la recherche (repousses de 15 à 30 ans, mixtes et lisières, milieux humides) ; elles ne remplacent pas la connaissance du terrain.
