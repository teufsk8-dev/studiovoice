---
name: studio-voice
description: Transformer un enregistrement de voix fait au micro d'un PC ou d'un téléphone en voix qualité studio - isoler la voix, supprimer le bruit de fond (débruitage IA DeepFilterNet avec repli ffmpeg), puis appliquer une chaîne de traitement studio (coupe-bas, dé-esseur, égalisation présence, compression, normalisation loudness 2 passes). Accepte un fichier audio (wav, mp3, m4a, flac...) ou une vidéo directement - dans ce cas la piste est extraite, traitée et recollée dans la vidéo sans réencoder l'image. Utiliser ce skill quand l'utilisateur dit "améliore cet enregistrement", "nettoie le son", "débruite", "isole la voix", "enlève le bruit de fond", "rends ça comme en studio", "voix studio", "améliore l'audio de cette vidéo", "le son de mon micro est mauvais", ou pour le traitement voix des montages vidéo (Dude Talk), "studio voice", "clean up audio", "denoise recording", "enhance speech". Windows/macOS/Linux (Python 3 + ffmpeg requis, DeepFilterNet optionnel).
---

# StudioVoice

Voix qualité studio à partir d'un enregistrement micro, via `scripts/studio_voice.py`.

## Utilisation

```
python scripts/studio_voice.py INPUT [-o OUTPUT] [options]
```

- `INPUT` : audio (`.wav .mp3 .m4a .flac .ogg .opus`) **ou vidéo** (la piste audio est
  extraite, traitée, puis remise dans la vidéo avec `-c:v copy` — l'image n'est pas réencodée).
- Sans `-o`, la sortie est `<nom>_studio.<ext>` à côté de l'entrée. **Jamais d'écrasement
  de l'original.**

Options :

| Option | Effet |
|---|---|
| `--no-ai` | force le débruitage ffmpeg (afftdn) même si DeepFilterNet est installé |
| `--lufs -16` | cible loudness (défaut -16 ; -14 pour YouTube pur, -19 voix douce) |
| `--strength light\|normal\|strong` | intensité débruitage + compression (défaut normal) |
| `--compare` | génère des spectrogrammes avant/après à côté de la sortie |
| `--keep-temp` | conserve le dossier temporaire (debug) |

## Pipeline

1. Extraction → WAV 48 kHz mono
2. Débruitage : **DeepFilterNet** (IA, local) si `deepFilter` est dans le PATH, sinon
   `afftdn` (ffmpeg, suivi de bruit)
3. Chaîne studio : coupe-bas 78 Hz → dé-esseur → EQ (-2 dB @300 Hz, +2 dB @4,2 kHz,
   air 9,5 kHz) → compression 3:1 → **loudnorm 2 passes** vers la cible LUFS
4. Encodage selon l'extension de sortie, ou remux vidéo

Le script imprime un rapport : plancher de bruit avant/après, loudness mesurée → cible.

## Comportement attendu de l'agent

- Lance d'abord tel quel (défauts sains). Si l'utilisateur trouve le résultat trop
  traité → `--strength light` ; bruit résiduel → `--strength strong`.
- Le premier lancement avec IA télécharge le modèle DeepFilterNet (~50 Mo) et peut
  prendre plusieurs minutes sur CPU — préviens l'utilisateur, lance en arrière-plan.
- Si DeepFilterNet n'est pas installé, le script fonctionne quand même (repli afftdn,
  moins bluffant sur les bruits complexes). Proposer :
  `pip install deepfilternet torch==2.1.2 torchaudio==2.1.2 soundfile`
  (les versions torch/torchaudio sont épinglées : les 2.2+ cassent DeepFilterNet 0.5.x).
- Pour juger le résultat sans l'écouter : `--compare` + lecture des spectrogrammes,
  et le rapport loudness/plancher de bruit.
- Montages Dude Talk : passer ce skill **avant** la coupe des blancs (le débruitage
  rend la détection de silences plus fiable) ; il remplace l'étape débruit + loudnorm
  du montage.

## Tests

```
python tests/smoke_test.py
```

Test hors-ligne (voix synthétique bruitée, `--no-ai`) : vérifie sortie créée,
loudness dans la tolérance, et remux vidéo intact.
