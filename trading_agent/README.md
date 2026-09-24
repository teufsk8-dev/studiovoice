# tradeagent — agent de trading crypto 24/7 (papier par défaut)

Statut : **paper trading uniquement**. Aucun connecteur d'exchange live n'est livré.
Le passage en réel est une porte opérateur (phase 6), pas une option de config.

## Architecture : deux couches, jamais mélangées

| Couche | Rôle | Qui | Fréquence |
|---|---|---|---|
| **Cerveau** | recherche, dérivation de stratégie, code, revue nocturne, escalade | Claude (API Anthropic) | lent, rare |
| **Réflexe** | jugement typé par bougie : `regime`, `direction`, `toxic_flow`, `setup_quality`, `risk_state` | Jev (TypeSafe AI) | chaque bougie |
| **Code** | snapshot, seuils, taille, risque, kill switch, exécution, journal | Python déterministe | chaque bougie |

Règle : **le modèle juge, le code décide**. Aucun seuil, aucune taille, aucun effet de bord
ne dépend d'un texte généré.

```
carnet d'ordres ─► state_engine (causal, <400 tokens) ─► Jev (jugements + probas)
                                                          │
             code_risk_state (déterministe) ─────────────►│
                                                          ▼
                    policy.decide : portes + Kelly fractionnaire (≤ ¼)
                                                          ▼
                    risk.check : kill switch, DD 15 %, perte jour, position, spread, fraîcheur
                                                          ▼
                    exchange (PaperExchange) ─► decisions.jsonl ─► review nocturne ─► proposals/
```

## Fichiers

| Fichier | Contenu |
|---|---|
| `src/tradeagent/state_engine.py` | mid, spread, imbalance top-5, flux agresseur 60 s, vol réalisée, inventaire, drawdown, P&L jour. `LookaheadError` si une donnée est postérieure à `as_of`. |
| `schemas/decision_v1.json` | schéma de décision typé (versionné). |
| `src/tradeagent/schema.py` | validation stricte ; réponse invalide ⇒ HOLD, jamais « réparée ». |
| `src/tradeagent/engines.py` | `JevEngine` (HTTP, **format non vérifié**, voir plus bas) et `StubEngine` (heuristique de test, pas une stratégie). |
| `src/tradeagent/policy.py` | portes (quality ≥ 2, conf direction > 0,80, risk_state safe, pas de flux toxique), Kelly net de coûts, plafond ¼ Kelly en dur. |
| `src/tradeagent/risk.py` | limites dures, kill switch à verrouillage (reset opérateur avec motif). |
| `src/tradeagent/escalation.py` | escalade vers Claude si conf < 0,60 ou régime `crisis`. Verdicts autorisés : `hold`/`reduce`/`flatten` — **ne peut jamais ouvrir ni augmenter**. |
| `src/tradeagent/loop.py` | boucle par bougie, comptabilité mark-to-market, journal JSONL. |
| `src/tradeagent/review.py` | Brier multi-classes vs base rate, courbe de fiabilité, recommandations, **proposition** de schéma v+1. |

## Choix où je m'écarte du cahier des charges (et pourquoi)

1. **`risk_state` n'est pas laissé au modèle.** Le code calcule son propre `risk_state` à partir du
   drawdown, du P&L jour et de l'inventaire ; la valeur la plus stricte des deux gagne. Le modèle peut
   resserrer, jamais desserrer.
2. **La revue nocturne ne déploie rien seule.** Elle écrit `proposals/decision_vN.json` + un rapport.
   La promotion est une porte opérateur. Une boucle qui se réécrit chaque nuit sans humain, sur un
   échantillon de quelques centaines de décisions, sur-apprend le bruit.
3. **Kelly sur une probabilité de modèle** : la « calibration » annoncée par un fournisseur n'est pas
   la calibration mesurée sur *votre* marché. Tant que `review.py` n'a pas montré un Brier inférieur
   au base rate sur un échantillon suffisant (≥ quelques centaines de trades hors échantillon), la
   taille réelle doit rester au plancher, quel que soit le Kelly calculé.
4. **Pas de connecteur live.** Volontaire.

## Jev : ce qui est vérifié et ce qui ne l'est pas

- Vérifié (recherche web du 2026-09-24) : Jev existe, c'est un modèle « System One » de TypeSafe AI
  qui renvoie des jugements typés (Choice / Noul / Score) avec probabilités ; plusieurs projets
  open source de trading l'utilisent selon le motif « Jev juge, le code exécute ».
- **Non vérifié** : l'URL d'API, l'en-tête d'auth, le format exact requête/réponse, la latence
  (~81 ms dans le cahier des charges) et la calibration. Les domaines typesafe.ai et
  console.typesafe.ai étaient bloqués depuis l'environnement de build. `JevEngine` refuse de
  tourner sans `JEV_URL` et `JEV_API_KEY` explicites. **Vérifie le format avant d'activer.**

## Lancer

```bash
cd trading_agent/tests && python3 -m unittest -v      # 29 tests, stdlib uniquement
cd trading_agent && PYTHONPATH=src python3 -m tradeagent.review \
    --log logs/decisions.jsonl --schema schemas/decision_v1.json --out proposals
```

## Plan de build AgenKit (6 phases, porte d'approbation à chaque fin de phase)

AgenKit (agenkit.xyz) est un harnais d'agents spécialisés pour Claude Code piloté par la commande
`/agenkit`. Je n'ai pas pu lire sa doc (domaine bloqué) : les noms de phases ci-dessous sont les
miens, à aligner sur ceux de l'outil. Le découpage, lui, ne dépend pas de l'outil.

| Phase | Livrable | Fichiers | Porte de sortie (opérateur) |
|---|---|---|---|
| 1. Spec | objectifs, univers, limites de risque chiffrées, critères d'arrêt | `docs/spec.md`, `docs/research.md` | limites signées ; perte max acceptée écrite noir sur blanc |
| 2. Architecture | couches, contrats, schéma v1 | ce README, `schemas/decision_v1.json` | aucune limite dure déléguée au modèle |
| 3. Plan | ordre de build, stratégie de test, jeux de données | `docs/plan.md` | données historiques niveau carnet disponibles, horodatage vérifié |
| 4. Build test-first | code + tests | `src/tradeagent/*`, `tests/*` | tests verts, anti-lookahead testé, kill switch testé |
| 5. Revue | backtest walk-forward coûts inclus, puis ≥ 4 semaines de papier | `logs/`, `proposals/review_v*.md` | Brier < base rate, P&L net > 0 après frais+slippage mesurés, DD papier < 7,5 % |
| 6. Ship | capital minimal, montée par paliers | connecteur exchange (à écrire), runbook | revue humaine de chaque palier ; kill switch testé en réel |

## Ce qui reste à faire avant tout argent réel

- Connecteur de données réel (WebSocket carnet + trades) avec horloge synchronisée et détection de trous.
- Backtest walk-forward sur données carnet historiques, avec latence et slippage simulés.
- Connecteur d'exchange live avec ordres idempotents, réconciliation de position au démarrage,
  annulation de tous les ordres au déclenchement du kill switch.
- Remise à zéro quotidienne de `day_start_equity` (UTC) et persistance de l'état du kill switch sur disque.
- Alerting (kill switch, escalade, latence Jev, taux d'erreur de schéma).
