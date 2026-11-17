# État du projet — Coach de câle, données de la carte écoforestière

Synthèse dressée le 17 novembre 2026 à partir du code de `main` (commit `5a7feca`) et des conversations Claude accessibles. Ce document complète `README.md` sans le répéter. L'application elle-même est dans le dépôt `coach-de-cale` (voir son `docs/ETAT_DU_PROJET.md`).

## 1. Objectif

Préparer automatiquement la Carte écoforestière à jour du Québec (MRNF, licence CC-BY 4.0) pour l'app Coach de câle : un fichier de tuiles par secteur, avec une classe d'habitat pour l'orignal et pour le cerf de Virginie, et la couche des ravages.

## 2. Dépôt et publication

| Élément | Valeur | État |
|---|---|---|
| Dépôt | `Mboivinimmobilier/coach-de-cale-donnees` (public) | Vérifié |
| Branches | `main`, plus `inspect`, `rapport`, `testwms`, `zones` (sorties d'outils) | Vérifié |
| Pipeline | `.github/workflows/carte.yml` : à chaque changement de `zones.txt`, `feuillets.txt` ou `scripts/`, chaque nuit (reprise des feuillets non finis) et une refonte annuelle le 15 juillet | Vérifié |
| Publication | Cloudflare R2 (bucket `coach-de-cale`); GitHub Pages gardé en secours | Rapporté par les commits du 31 oct.; non vérifié en ligne |
| Scripts | `scripts/prep.py`, `tools/zones.py`, `tools/saisons_app.py`, `tools/inspect_tiles.py` | Vérifié |

## 3. État réalisé

- 31 oct. : pipeline incrémental publié sur R2 (il saute les feuillets complets et récents); plus de déploiement GitHub Pages.
- 1er nov. : 15 secteurs ajoutés (Laurentides, La Vérendrye, Gaspésie, Abitibi-Est, Mauricie, Saguenay, Charlevoix, Bas-Saint-Laurent, Côte-Nord), deux feuillets par passage; relance automatique du passage suivant.
- Rapporté le 4 nov. : les 15 secteurs sont terminés et vérifiés en ligne.

## 4. Décisions encore applicables

- Héberger les feuillets sur Cloudflare R2 (GitHub Pages plafonne à 1 Go). Les secrets R2 sont dans les secrets GitHub du dépôt, jamais dans le code.
- Préparer d'avance les grands secteurs de chasse du Québec plutôt qu'attendre les demandes.
- Les classes d'habitat sont des repères tirés de la recherche; elles ne remplacent pas la connaissance du terrain.

## 5. Problèmes connus et contradictions

- **`README.md` en retard** : il dit que le résultat est « publié sur GitHub Pages ». Depuis le 31 oct., la publication se fait sur R2.
- Le pipeline tourne chaque nuit : un changement dans `scripts/` ou `zones.txt` poussé sur `main` relance la préparation et publie.
- Couverture : l'objectif est tout le Québec; les secteurs hors de la liste passent par « Demander mon secteur » dans l'app.

## 6. Tâches restantes

1. Corriger la phrase du `README.md` sur GitHub Pages.
2. Ajouter les secteurs demandés par les utilisateurs (table `cdc_demandes_secteur` du projet Supabase `coach-de-cale`).
3. Mettre à jour les dates de saison chaque année (`data/saisons-2026.json`).

## 7. Sources

Conversations Claude : « Coach de call » (4 nov.), « Partage de position entre chasseurs » (18 oct.). Document Claude : « Codes de la carte écoforestière ». Fichiers : `README.md`, `data/verification.md`, `supabase/2026-10-17_especes.md`.
