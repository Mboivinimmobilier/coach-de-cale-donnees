# Vérification — saisons 2026 orignal et cerf

Fait le 2026-10-17. Les fichiers de ce dossier sont `saisons-2026.json` et `zones-geo.md`.

## Sources et URL de chaque date

| Code | Source | URL | Mise à jour | Statut |
|---|---|---|---|---|
| S1 | Québec.ca, Périodes de chasse à l'orignal (FR) | https://www.quebec.ca/tourisme-loisirs-sport/activites-sportives-et-de-plein-air/chasse-sportive/periodes-limites/orignal | 23 sept. 2026 | Lue (WebFetch). **Source de toutes les dates d'orignal** |
| S2 | Québec.ca, Moose seasons (EN) | https://www.quebec.ca/en/tourism-recreation-sport/sporting-and-outdoor-activities/sport-hunting/seasons-bag-limits/moose | 23 sept. 2026 | Lue, sert à la vérification croisée |
| S3 | Québec.ca, Périodes de chasse au cerf de Virginie | https://www.quebec.ca/tourisme-loisirs-sport/activites-sportives-et-de-plein-air/chasse-sportive/periodes-limites/cerf-virginie | 21 mai 2026 | Lue. **Source de toutes les dates du cerf** |
| S4 | Calendrier cerf 2026 (PDF) | https://cdn-contenu.quebec.ca/cdn-contenu/chasse/Documents/calendrier-zone-chasse-cerf-virginie-2026.pdf | 2026 | Lu (texte). Il donne les **engins par zone**. Les dates sont dans des barres de couleur qu'on ne peut pas extraire |
| S5 | Plan de gestion de l'orignal, nouveautés (PDF) | https://cdn-contenu.quebec.ca/cdn-contenu/faune/documents/gestion-especes/Plans-gestion/plan-gestion-orignal-nouveautes.pdf | 2026 | Lu. Il donne les zones sans arme à feu, les zones fermées, l'OSB et l'alternance |
| S6 | Nouveautés réglementaires 2026-2028 | https://www.quebec.ca/tourisme-loisirs-sport/activites-sportives-et-de-plein-air/chasse-sportive/nouveautes-reglementaires | 21 mai 2026 | Lue. OSB, retrait des périodes ACB, ouverture de la zone 18 au cerf |
| S7 | Québec.ca, gibier/orignal | https://www.quebec.ca/tourisme-loisirs-sport/activites-sportives-et-de-plein-air/chasse-sportive/gibier/orignal | 26 juin 2026 | Lue. Zone 17 fermée, limites 1/2 et 1/3 (24 zecs) |
| S8 | chasseurquebec.com (secondaire, recopie Québec.ca) | https://chasseurquebec.com/periodes-de-chasse | relevé du 30 août 2026 | Lue, sert à la vérification croisée |
| S9 | Horizon Chasse et Pêche (secondaire) | https://horizonchassepeche.ca/periodes-chasse-orignal-zones-quebec/ | 28 juil. 2026 | Lue, sert à la vérification croisée |
| S10 | Notes internes du 2026-10-17 (`/home/claude/research_notes/chevreuil/reglement-rut.md`, §2.4) | même source que S3 | — | Comparées |
| S11 | Cartes des zones | https://www.quebec.ca/tourisme-loisirs-sport/activites-sportives-et-de-plein-air/chasse-sportive/cartes-zones | — | Lue. 28 zones de chasse ; la zone 25 sert seulement à la pêche |

Chaque période du JSON a un champ `src`. Toutes les dates d'orignal viennent de S1 et toutes les dates du cerf de S3.

### URL non lisibles
- `https://cdn-contenu.quebec.ca/cdn-contenu/chasse/Documents/regles-chasse-2026-2028.pdf` : **HTTP 404** (pg_net). Le shell est bloqué par le proxy et WebFetch refuse l'URL (provenance).
- `calendrier-zone-chasse-orignal-2026.pdf` et 6 variantes du nom (`calendrier-zones-…`, `calendrier-chasse-orignal-2026.pdf`, `…-2026-2027.pdf`, `regles-chasse-2026-2027.pdf`, `periodes-chasse-reserves-fauniques-2026-2028.pdf`) : **toutes en 404**. La page S1 ne renvoie à aucun PDF de calendrier pour l'orignal.
- Le PDF du cerf (S4) répond 200 par pg_net, mais le contenu binaire est tronqué à 1 683 octets. Je l'ai lu par WebFetch.
- Le communiqué « Chasse à l'orignal : ajustement des modalités 2026-2027 » (https://www.quebec.ca/nouvelles/actualites/details/chasse-a-lorignal-ajustement-des-modalites-pour-la-saison-2026-2027-68506) n'a rendu qu'une page vide.

## Vérification croisée (au moins 2 sources par zone)

| Zone | Espèce | Période | S1/S3 (officiel) | 2e source | Verdict |
|---|---|---|---|---|---|
| **13** | orignal | arc/arb. | 26 sept.-4 oct., segment « Orignal » (sans bois permis) | S2 : Sep 26-Oct 4, « any moose » ; S8 et S9 : idem | ✅ concorde |
| **13** | orignal | armes à feu | 10-25 oct., avec bois | S2 : Oct 10-25 antlered ; S8 et S9 : idem ; S5 : 2026 restrictive | ✅ |
| **13 SO** | cerf | arc/arb. | 3-16 oct., avec ou sans bois | S8 : idem ; S10 : idem ; S4 : engins ARC-ARB et AAF (pas d'ACB-FUS) | ✅ |
| **13 SO** | cerf | AF | 7-22 nov., avec bois ; relève 31 oct.-1er nov. | S8 et S10 : idem | ✅ |
| **16** | orignal | arc/arb. | 12-20 sept., avec bois | S2 : Sep 12-20 ; S8 et S9 : idem | ✅ |
| **16** | orignal | armes à feu | 26 sept.-16 oct. | S2 ; S8 ; S9 | ✅ |
| **16** | cerf | — | pas de période | S8 : « aucune période pour 14, 16, 17, 19… » ; S4 : 16 absente | ✅ non chassable |
| **10 est** | orignal | arc/arb. | 26 sept.-12 oct. ; **pas d'arme à feu** | S2 ; S8 ; S9 (« arc et arbalète seulement ») ; S5 (« ARC-ARB seulement ») | ✅ |
| **10 ouest** | orignal | arc/arb. puis AF | 26 sept.-4 oct. ; 10-18 oct. | S2 ; S8 ; S9 | ✅ |
| **10 est** | cerf | AA / ACB-FUS / AF | 3-16 oct. avec bois ; 17-21 oct. avec bois ; 7-22 nov. avec bois | S8 et S10 : idem ; S4 : ARC-ARB, ACB-FUS, AAF | ✅ |
| **10 ouest** | cerf | AA / ACB-FUS / AF | 3-16 oct. avec ou sans bois ; 17-21 oct. avec bois ; 7-22 nov. avec bois | S8 et S10 : idem | ✅ |
| **6 (N et S)** | orignal | arc/arb. | 3-9 oct., avec bois ; **pas d'arme à feu** | S2 ; S8 ; S9 ; S5 (5 à 9 sans arme à feu) | ✅ |
| **6 N / 6 S** | cerf | AA / ACB-FUS / AF / relève | 3-16 oct. RTLB ou sans bois ; 17-21 oct. RTLB ou sans bois ; 7-22 nov. RTLB ; relève RTLB | S8 et S10 : idem ; S4 : ARC-ARB, ACB-FUS, AAF | ✅ |
| **1** | orignal | AA / AF | 26 sept.-4 oct. ; 17-25 oct. | S2 ; S8 ; S9 | ✅ |
| **1 N / 1 S** | cerf | AF | **7-15 nov.** (pas 22) | S8 et S10 : idem | ✅ |
| **19 sud** | orignal | 3 parties | NO : 29 août-6 sept. et 12 sept.-12 oct. ; E : 5-13 sept. et 19 sept.-1er nov. ; O : 5-13 sept. et 19 sept.-18 oct. | S2 ; S8 ; S9 | ✅ dates. ⚠️ S9 dit « avec bois », mais S1, S2 et S5 disent « tout orignal / tous les segments ». J'ai retenu les sources officielles |
| **22** | orignal | arc / AF | arc 5-13 sept. ; AF 19 sept.-12 oct. | S2 ; S8 ; S9 | ✅ |
| **18** | cerf | AA / ACB-FUS | 7-12 nov. ; 13-15 nov., avec bois | S8 ; S4 (ARC-ARB, ACB-FUS) ; S6 (ouverture de la zone 18) | ✅ |
| **20** | cerf | AF | 1er-31 août avec bois ; 1er sept.-24 déc. avec ou sans bois | S8 ; S4 (note Anticosti) ; S10 | ✅ |

Je n'ai trouvé **aucune divergence de date** entre les sources officielles et secondaires.

## Points incertains (à confirmer au 1 877 346-6763 ou dans le PDF des règles quand il sera en ligne)

1. **Zones 19 nord et 21, orignal** : elles sont absentes de S1, S2 et S5. Je les ai codées comme fermées (`orignal_ferme: true`), mais ce n'est **pas une fermeture explicite**. Les fermetures explicites sont 17 (S1 et S7) et 20, 23 et 24 (S5).
2. **Zone 3 est, relève cerf** : S8 et S10 l'indiquent, mais une lecture de S3 n'a pas fait ressortir de ligne relève pour 3 est. J'ai gardé la relève, avec une note.
3. **Cantons de Macpès et Duquesne (zone 2)** : S1 les exclut de l'arme à feu pour l'orignal, et S3 les exclut de l'AF et de la relève pour le cerf. Macpès a la période arc/arb. du cerf (3-16 oct.). Pour Duquesne, on ne sait pas si l'arc et l'arbalète restent permis. Les deux cantons n'ont pas de polygone dans la couche WFS.
4. **Zone 20, partie ouest (cerf)** : S3 dit « sauf la partie ouest », sans dates pour cette partie. C'est probablement le parc national ou des secteurs à règles propres ; la couche `secteur_chasse_anticosti` du WFS pourrait le préciser.
5. **Parties « ZSR » (08NZ, 09OZ, 10EZ)** et **Seigneurie de Beaupré (27ESB, 27OSB)** : ce sont des codes de la couche officielle que les pages de dates ne mentionnent pas. J'y ai mis les dates de la sous-zone parente, avec une note. Le sens de « ZSR » reste à confirmer.
6. **Zone 15 nord (15N)** : la couche WFS la sépare, mais S3 ne liste que 15 est et 15 ouest pour le cerf. Je l'ai codée non chassable au cerf. Pour l'orignal, j'y ai mis les dates de la zone 15.
7. **OSB par période** : S1 et S5 disent que l'OSB exige un permis gagné au tirage dans les zones 1-12, 14-16, 22, 26 et 27. Elles ne précisent pas si ce permis vaut pour toutes les périodes, alors je l'ai supposé. Zone 13 : l'OSB est permis à l'arc et à l'arbalète en 2026, **sans tirage** selon S1 (« sauf la zone 13 pour la chasse à l'arc et à l'arbalète en 2026 »).
8. **Aucune période de relève pour l'orignal** : le mot n'apparaît ni dans S1, ni dans S2, ni dans S5. La relève du 31 oct.-1er nov. vaut pour le cerf seulement.
9. **Zecs** : les dates propres de 8 zecs viennent de S1 (dans `territoires`). Les zones de Batiscan-Neilson, des Martres, Jeannotte et Rivière-Blanche ne sont pas rattachées dans le JSON. Les réserves fauniques et pourvoiries ne sont **pas couvertes** (voir la page `periodes-limites/reserves-fauniques`).
10. **Engins orignal, période AF** : j'ai noté `carabine, fusil, acb, arc, arbalete`, parce que les périodes ACB à part ont été retirées en 2026 (S5, S6) et que l'ACB est permise pendant la période AF. Les calibres minimaux ne sont pas codés, puisque le PDF des règles est inaccessible.
11. **Couche géographique de 2022** : voir `zones-geo.md`.
