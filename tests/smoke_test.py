#!/usr/bin/env python3
"""Test de fumée StudioVoice — hors-ligne, sans IA (--no-ai).

Fabrique une 'voix' synthétique bruitée avec ffmpeg, la traite, et vérifie :
  1. la sortie audio existe et sa loudness est proche de la cible ;
  2. le chemin vidéo remuxe sans réencoder l'image (codec vidéo inchangé).
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "studio_voice.py"


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def measured_lufs(path):
    code, out = run(["ffmpeg", "-i", str(path),
                     "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", out, re.S)
    assert m, f"pas de mesure loudnorm pour {path}"
    return float(json.loads(m.group(0))["input_i"])


def main():
    failures = 0
    with tempfile.TemporaryDirectory(prefix="sv_test_") as td:
        td = Path(td)

        # 'Voix' synthétique : deux sinus modulés + bruit blanc de fond
        noisy = td / "noisy.wav"
        code, out = run([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "sine=frequency=210:duration=8",
            "-f", "lavfi",
            "-i", "anoisesrc=colour=white:amplitude=0.05:duration=8",
            "-filter_complex", "[0]volume=0.4[v];[v][1]amix=inputs=2:duration=first",
            "-ar", "48000", str(noisy)])
        assert code == 0, f"génération du signal test échouée :\n{out[-400:]}"

        # --- Test 1 : audio ---
        out_audio = td / "out.wav"
        code, out = run([sys.executable, str(SCRIPT), str(noisy),
                         "--no-ai", "-o", str(out_audio)])
        if code != 0 or not out_audio.exists():
            print(f"ECHEC audio : code {code}\n{out[-600:]}")
            failures += 1
        else:
            lufs = measured_lufs(out_audio)
            if abs(lufs - (-16.0)) <= 2.5:
                print(f"OK audio : sortie a {lufs:.1f} LUFS (cible -16)")
            else:
                print(f"ECHEC audio : {lufs:.1f} LUFS, trop loin de -16")
                failures += 1

        # --- Test 2 : vidéo (remux, image intacte) ---
        vid = td / "in.mp4"
        code, out = run(["ffmpeg", "-y",
                         "-f", "lavfi", "-i", "color=c=gray:s=320x180:d=8",
                         "-i", str(noisy), "-t", "8",
                         "-c:v", "libx264", "-preset", "ultrafast",
                         "-c:a", "aac", str(vid)])
        assert code == 0, f"génération vidéo test échouée :\n{out[-400:]}"
        out_video = td / "out.mp4"
        code, out = run([sys.executable, str(SCRIPT), str(vid),
                         "--no-ai", "-o", str(out_video)])
        if code != 0 or not out_video.exists():
            print(f"ECHEC vidéo : code {code}\n{out[-600:]}")
            failures += 1
        else:
            _, probe = run(["ffprobe", "-v", "quiet", "-print_format", "json",
                            "-show_streams", str(out_video)])
            streams = json.loads(probe)["streams"]
            codecs = {s["codec_type"]: s["codec_name"] for s in streams}
            if codecs.get("video") == "h264" and codecs.get("audio") == "aac":
                print(f"OK vidéo : flux {codecs}")
            else:
                print(f"ECHEC vidéo : flux inattendus {codecs}")
                failures += 1

    print("TOUT OK" if failures == 0 else f"{failures} échec(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
