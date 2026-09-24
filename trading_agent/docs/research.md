# Recherche marché — cadre, pas de chiffres inventés

**Statut au 2026-09-24 : aucune donnée de marché en direct n'a pu être collectée.** Depuis
l'environnement de build, DefiLlama, CoinGecko, l'API Binance et typesafe.ai étaient bloqués par le
proxy réseau. Je ne fournis donc **aucune** liste de finalistes, aucun TVL, aucun revenu, aucun
calendrier de déblocage. En produire sans source primaire serait de l'invention présentée comme de
l'analyse.

Ce document est la grille à remplir, une ligne par source datée.

## 1. Régime (à recalculer à chaque session de recherche)

| Signal | Source primaire | Lecture |
|---|---|---|
| Tendance BTC / ETH (prix vs MM 50/200 j, pente) | données OHLC de l'exchange | tendance / range |
| Dominance BTC | CoinGecko `/global` | rotation vers alts ou refuge |
| Offre de stablecoins (variation 30 j) | DefiLlama stablecoins | liquidité entrante/sortante |
| Funding perp, open interest | endpoints publics des exchanges | levier, risque de squeeze |
| Macro (taux, DXY, calendrier FOMC/CPI) | Fed, BLS | risque d'événement |
| Rotation narrative | volumes par secteur | où va le flux |

## 2. Fiche par candidat (5 à 10)

Pour chaque jeton, chaque chiffre porte sa source et sa date. Tout ce qui est estimé est marqué
**[ESTIMATION]**, tout ce qui est spéculatif **[SPÉCULATION]**.

- Offre : circulante / totale / FDV ; **calendrier de déblocage 12 mois** (en % de la circulante).
- Revenus et frais du protocole (30 j, 90 j), et **part qui revient au détenteur du jeton**
  (buyback, burn, staking réel). Frais ≠ valeur pour le jeton.
- TVL, utilisateurs actifs, **dont part incitée** (émissions, points, airdrop farming).
- Concentration des détenteurs (top 10 hors contrats/exchanges).
- Catalyseurs : **confirmés** (date, lien officiel) vs **supposés**.
- **Thèse baissière construite sérieusement**, pas une ligne pour la forme.
- **Condition d'invalidation** chiffrée (ex. : revenu 30 j en baisse de X %, déblocage > Y % absorbé
  sans soutien, perte d'un niveau de prix).

## 3. Passage recherche → schéma Jev

Un finaliste n'a pas son propre schéma « magique » : il reçoit le schéma commun
`schemas/decision_v1.json`, plus éventuellement un champ spécifique **seulement si** une variable
de la thèse est observable dans le snapshot (ex. : un flag `unlock_window` calculé par le code à
partir du calendrier). Une thèse fondamentale à horizon de semaines ne se juge pas à la bougie :
elle fixe l'**univers** et le **biais de direction autorisé**, le réflexe ne fait que le timing.
