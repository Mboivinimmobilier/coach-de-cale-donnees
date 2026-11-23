---
name: optimal-factory
description: "Méthode Optimal AI Factory — Speed First. À utiliser pour toute tâche de développement de plus de quelques minutes (fonctionnalité, refonte, audit, série de bogues) afin de décider combien d'agents lancer, lesquels, sur quels modèles, et comment paralléliser, tester et intégrer."
---

# Optimal AI Factory — Speed First

But : livrer un travail **validé** le plus vite possible. Les tokens sont secondaires ; la qualité ne l'est jamais.
Plus d'agents ≠ plus vite : chaque agent coûte du démarrage (≈ 30-90 s), du contexte à transmettre et de l'intégration.

## 1. Triage (≤ 2 min, fait par la session principale = le directeur)
| Taille | Exemple | Organisation |
|---|---|---|
| Petite | 1 bogue, 1 fichier | **Seul**, aucun agent. Au plus 1 `eclaireur` si la recherche est large. |
| Moyenne | 1 fonctionnalité, 2-4 zones | 2-4 agents : `dev` par zone indépendante + `testeur` en parallèle. |
| Grosse | plusieurs systèmes | `architecte` d'abord (plan + graphe), puis 4-8 `dev`/`dev-parallele` + `testeur` + `reviseur`. |
| Audit | revue large | jusqu'à 10-20 `eclaireur`/`reviseur` en lecture seule, un par zone. |

Règle : n'ajoute un agent que s'il retire du temps au **chemin critique**.

## 2. Graphe de dépendances (avant de lancer quoi que ce soit)
Écris en 5-15 lignes : tâches, ce qui bloque quoi, chemin critique, fichiers touchés par chaque tâche.
Deux tâches qui touchent le **même fichier** ne vont pas en parallèle (sauf worktrees séparés + intégration prévue).
Lance tout ce qui est indépendant **dans le même message** (plusieurs appels Agent d'un coup), en arrière-plan.

## 3. Choix des modèles (le plus probable de réussir vite, pas le moins cher)
- `opus` : architecture, décision structurante, bogue difficile ou déjà raté une fois, revue finale.
- `sonnet` : programmation courante, tests, la majorité des chantiers parallèles.
- `haiku` : recherche dans le code, inventaires, tâches mécaniques bien délimitées.
- **Escalade** : un agent qui échoue ou tourne en rond → relancer la même tâche **une** fois sur le modèle au-dessus
  avec le diagnostic de l'échec. Jamais deux fois la même tentative.

## 4. Isolation Git pour le travail parallèle
Plusieurs agents qui écrivent dans le même dépôt = **un worktree chacun**, créé par le directeur depuis la branche courante :
```bash
git worktree add ../wt-<tache> -b factory/<tache> HEAD
```
Donne le chemin absolu du worktree à l'agent `dev-parallele`. N'utilise pas `isolation: worktree` des agents :
il part de la branche **par défaut** du dépôt, pas de la branche de travail (risque de travailler sur du code périmé).
Intégration : `git cherry-pick` ou `git merge --no-ff` de chaque branche validée, dans l'ordre du graphe, puis
`git worktree remove`. Respecte la branche de livraison et les règles de publication du CLAUDE.md du dépôt.

## 5. Contrat de chaque agent (à mettre dans son prompt)
1. Objectif en une phrase. 2. Périmètre : fichiers/zones permis, interdits. 3. Critère d'acceptation **vérifiable**
(commande de test exacte). 4. Contexte déjà connu (pour ne pas refaire l'analyse). 5. Format du retour : ce qui a
changé, commande lancée et son résultat réel, risques.

## 6. Tests en même temps que le code
Pendant que les `dev` codent : un `testeur` écrit/prépare les tests et scénarios Playwright à partir du critère
d'acceptation ; un `reviseur` peut lire le code déjà poussé. Intégration progressive ; **contrôle d'intégration final**
(la suite complète du dépôt) après la dernière fusion, avant de déclarer fini. Aucun test déclaré réussi sans exécution.

## 7. Blocages
Un agent bloqué n'arrête rien : les autres continuent. Diagnostic court → correction simple, ou escalade de modèle,
ou réassignation. Ne remonte à Marc-André que ce qui exige sa décision (publication, dépense, vision, accès).
Ne relance pas une analyse complète si le résultat précédent est encore valide : transmets-le.

## 8. Mesure (tâches moyennes et plus)
Ajoute une ligne à `docs/factory/METRIQUES.md` : date, tâche, méthode (A seul / C hybride), nb d'agents, modèles,
minutes (plan / code / validation / total), tests OK, reprises, problèmes après intégration.
Ajuste la table du §1 quand les mesures contredisent ces repères.

## Limites connues (vérifiées le 2026-11-22, Claude Code 2.1.330)
- Sessions lancées depuis l'app Claude (cloud) : `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1` → **un sous-agent ne peut pas
  lancer d'autres sous-agents**. Pas de vrais « contremaîtres » : le directeur distribue directement.
  Ailleurs (Claude Code local), la profondeur par défaut est 3.
- 20 sous-agents simultanés maximum par défaut. Le conteneur cloud n'a que **2 CPU / 7 Go** : au-delà de 3 agents qui lancent
  Playwright en même temps, ils se ralentissent entre eux. Pour les tâches lourdes en tests, 3 agents d'exécution est le plafond utile.
- Push : `git -c push.negotiate=true push -u origin <branche>` fonctionne (identifiants injectés par le proxy de la session).
  `gh auth status` affiche « token invalid » : c'est trompeur, ça ne bloque rien.
- Pull requests : `gh pr create` est refusé (GraphQL bloqué, HTTP 403). Utiliser l'API REST :
  `gh api repos/<owner>/<repo>/pulls -f title=... -f head=<branche> -f base=<base> -f body=...`
- La configuration `~/.claude/` d'un ordinateur n'existe pas dans les sessions cloud : seul ce qui est dans le dépôt suit.
