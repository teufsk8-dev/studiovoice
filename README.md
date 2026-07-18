# StudioVoice

Transforme un enregistrement de voix fait au micro d'un PC ou d'un téléphone en voix
qualité studio : isolation de la voix, suppression du bruit de fond par IA
([DeepFilterNet](https://github.com/Rikorose/DeepFilterNet), 100 % local), puis chaîne
de traitement studio (coupe-bas, dé-esseur, égalisation, compression, normalisation
loudness en 2 passes).

Accepte un fichier audio **ou une vidéo** : dans ce cas la piste audio est extraite,
traitée, puis recollée dans la vidéo sans réencoder l'image.

C'est à la fois un outil en ligne de commande autonome et un
[skill Claude Code](https://docs.claude.com/en/docs/claude-code/skills) (`SKILL.md`).

## Prérequis

- Python 3.9 – 3.11
- [ffmpeg](https://ffmpeg.org/) dans le PATH
- Optionnel mais recommandé — débruitage IA :

```
pip install deepfilternet torch==2.1.2 torchaudio==2.1.2 soundfile
```

> torch/torchaudio sont épinglés en 2.1.2 : les versions 2.2+ ont retiré l'API
> `torchaudio.backend` dont dépend DeepFilterNet 0.5.x.

Sans DeepFilterNet, le script fonctionne quand même avec le débruiteur ffmpeg
(`afftdn`), moins efficace sur les bruits complexes (clim, rue, réverbération).

## Utilisation

```
python scripts/studio_voice.py enregistrement.m4a
python scripts/studio_voice.py interview.mp4                 # vidéo : audio traité, image intacte
python scripts/studio_voice.py voix.wav -o voix_studio.mp3
python scripts/studio_voice.py voix.wav --strength strong    # bruit tenace
python scripts/studio_voice.py voix.wav --lufs -14           # cible YouTube
python scripts/studio_voice.py voix.wav --compare            # spectrogrammes avant/après
```

Sortie par défaut : `<nom>_studio.<ext>` à côté de l'original (jamais d'écrasement).

Le script imprime un rapport chiffré :

```
Entrée   : lune fr.m4a  (audio)
Débruitage : DeepFilterNet (IA)
Chaîne studio : EQ + dé-esseur + compression, loudnorm -16.0 LUFS (2 passes)
Sortie   : lune fr_studio.m4a
Plancher de bruit : -83.8 dB -> silence total (< -120 dB)
Loudness : -31.14 LUFS mesuré -> cible -16.0 LUFS
```

## Pipeline

| Étape | Outil | Détail |
|---|---|---|
| Extraction | ffmpeg | WAV 48 kHz mono |
| Débruitage | DeepFilterNet ou afftdn | isolation de la voix, suppression du fond |
| Coupe-bas | highpass 78 Hz | grondement, bruits de manipulation |
| Dé-esseur | deesser | sifflantes |
| EQ voix | equalizer/treble | -2 dB @ 300 Hz, +2 dB @ 4,2 kHz, air 9,5 kHz |
| Compression | acompressor 3:1 | dynamique lissée, voix « devant » |
| Loudness | loudnorm 2 passes | cible -16 LUFS, vrai-pic -1,5 dB |

## Installation comme skill Claude Code

```powershell
# Windows (jonction)
cmd /c mklink /J "$env:USERPROFILE\.claude\skills\studio-voice" "chemin\vers\StudioVoice"
```

```bash
# macOS / Linux
ln -s /chemin/vers/StudioVoice ~/.claude/skills/studio-voice
```

## Tests

```
python tests/smoke_test.py
```

## Licence

MIT
