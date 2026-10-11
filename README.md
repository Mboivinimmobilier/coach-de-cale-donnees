# Coach de câle — données de la carte écoforestière

Ce dépôt prépare automatiquement la **Carte écoforestière à jour** du Québec pour l'app Coach de câle.

- Source : Ministère des Ressources naturelles et des Forêts (MRNF), *Carte écoforestière à jour*, licence **CC-BY 4.0** (Données Québec).
- Traitement : pour chaque feuillet 1/250 000 listé dans `feuillets.txt`, le script garde les champs utiles et ajoute une **classe « orignal »** par peuplement
  (i = idéal/mixte, n = nourriture, a = abri, h = humide, o = ouvert récent, r = résineux peu utile, w = eau).
- Résultat : un fichier `XXX.pmtiles` par feuillet, publié sur GitHub Pages, + `index.json`.
- Mise à jour : chaque année en juillet, ou quand on modifie `feuillets.txt`.

Les classes « orignal » sont des repères indicatifs tirés de la recherche (repousses de 15 à 30 ans, mixtes et lisières, milieux humides) ; elles ne remplacent pas la connaissance du terrain.
