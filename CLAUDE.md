# Coach de câle, données — repères pour Claude

- Dépôt public : n'y écrire aucun secret ni renseignement interne.
- État du projet, décisions en vigueur, problèmes connus et tâches restantes : `docs/ETAT_DU_PROJET.md`. À consulter au démarrage de chaque session et à mettre à jour après un changement important vérifié.
- Un changement à `zones.txt`, `feuillets.txt` ou `scripts/` poussé sur `main` relance la préparation et publie sur Cloudflare R2.
- L'application est dans le dépôt `coach-de-cale`.
- Par défaut (méthode Factory) : travailler sur une branche et ouvrir une pull request vers `main` ; ne jamais déployer en production sans autorisation explicite de Marc-André.

## Optimal AI Factory — Speed First (méthode de développement)
Priorités : 1) délai jusqu'à une livraison **validée** 2) qualité 3) parallélisme utile 4) moins d'attente pour Marc-André 5) tokens.
- Toute tâche de plus de quelques minutes : suivre le skill `optimal-factory` (`.claude/skills/optimal-factory/SKILL.md`) — triage, graphe de dépendances, choix des modèles, worktrees, tests en parallèle, mesure.
- Agents du dépôt (`.claude/agents/`) : `architecte` (opus), `dev` / `dev-parallele` (sonnet), `testeur` (sonnet), `reviseur` (opus), `debogueur` (opus), `eclaireur` (haiku).
- Lancer les tâches indépendantes en même temps ; escalader vers un modèle plus fort après un échec ; ne jamais affaiblir un test pour le faire passer.
- Les règles de branche, de publication et d'approbation de CE fichier priment sur la méthode.
