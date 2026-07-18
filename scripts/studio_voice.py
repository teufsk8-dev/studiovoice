#!/usr/bin/env python3
"""StudioVoice — transforme un enregistrement micro (PC/téléphone) en voix qualité studio.

Pipeline :
  1. Extraction audio -> WAV 48 kHz mono
  2. Débruitage : DeepFilterNet (IA, si installé) sinon ffmpeg afftdn
  3. Chaîne studio : coupe-bas, dé-esseur, EQ voix, compression, loudnorm 2 passes
  4. Sortie audio, ou remux dans la vidéo d'origine (-c:v copy)

Usage :
  python studio_voice.py INPUT [-o OUTPUT] [--no-ai] [--lufs -16] [--strength normal]
                                [--compare] [--keep-temp]
"""

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}

# Réglages par intensité : (afftdn nr, seuil compresseur, ratio, gain présence)
STRENGTHS = {
    "light":  {"nr": 8,  "comp_thr": -20, "comp_ratio": 2.5, "presence": 1.5},
    "normal": {"nr": 12, "comp_thr": -24, "comp_ratio": 3.0, "presence": 2.0},
    "strong": {"nr": 20, "comp_thr": -28, "comp_ratio": 4.0, "presence": 2.5},
}


def run(cmd, **kw):
    """Lance une commande, retourne (code, stdout+stderr)."""
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", **kw)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def die(msg):
    print(f"ERREUR : {msg}", file=sys.stderr)
    sys.exit(1)


def probe(path):
    """Retourne les infos ffprobe (streams) du fichier."""
    code, out = run(["ffprobe", "-v", "quiet", "-print_format", "json",
                     "-show_streams", "-show_format", str(path)])
    if code != 0:
        die(f"ffprobe n'a pas pu lire {path}")
    return json.loads(out)


def has_deepfilter():
    return shutil.which("deepFilter") is not None


def extract_wav(src, dst):
    """Extrait/convertit la piste audio en WAV 48 kHz mono (format attendu par DeepFilterNet)."""
    code, out = run(["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "1",
                     "-ar", "48000", "-c:a", "pcm_s16le", str(dst)])
    if code != 0:
        die(f"extraction audio échouée :\n{out[-800:]}")


def denoise_ai(src_wav, workdir):
    """Débruitage DeepFilterNet. Retourne le chemin du WAV débruité."""
    outdir = workdir / "dfn"
    outdir.mkdir(exist_ok=True)
    code, out = run(["deepFilter", str(src_wav), "--output-dir", str(outdir)])
    if code != 0:
        print(f"  DeepFilterNet a échoué, repli sur afftdn.\n{out[-400:]}")
        return None
    produced = list(outdir.glob("*.wav"))
    return produced[0] if produced else None


def denoise_ffmpeg(src_wav, dst_wav, nr):
    """Débruitage ffmpeg (réduction spectrale avec suivi du bruit)."""
    code, out = run(["ffmpeg", "-y", "-i", str(src_wav),
                     "-af", f"afftdn=nr={nr}:nf=-42:tn=1", str(dst_wav)])
    if code != 0:
        die(f"afftdn échoué :\n{out[-800:]}")


def studio_chain(s, lufs, measured=None):
    """Construit la chaîne de filtres 'studio'. measured=None -> passe d'analyse."""
    loudnorm = f"loudnorm=I={lufs}:TP=-1.5:LRA=11"
    if measured:
        loudnorm += (f":measured_I={measured['input_i']}"
                     f":measured_TP={measured['input_tp']}"
                     f":measured_LRA={measured['input_lra']}"
                     f":measured_thresh={measured['input_thresh']}"
                     f":offset={measured['target_offset']}:linear=true")
    else:
        loudnorm += ":print_format=json"
    return ",".join([
        "highpass=f=78",                                   # coupe le grondement / bruit de manipulation
        "deesser=i=0.35",                                  # adoucit les sifflantes
        "equalizer=f=300:t=q:w=1.2:g=-2",                  # dégage le bas-médium boueux
        f"equalizer=f=4200:t=q:w=1.4:g={s['presence']}",   # présence / intelligibilité
        "treble=g=1.5:f=9500",                             # air
        (f"acompressor=threshold={s['comp_thr']}dB:ratio={s['comp_ratio']}"
         ":attack=8:release=180:makeup=2"),                # lisse la dynamique
        loudnorm,
    ])


def loudnorm_analyze(src_wav, s, lufs):
    """Passe 1 : mesure loudness à travers la chaîne complète."""
    code, out = run(["ffmpeg", "-y", "-i", str(src_wav),
                     "-af", studio_chain(s, lufs), "-f", "null", "-"])
    if code != 0:
        die(f"analyse loudnorm échouée :\n{out[-800:]}")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", out, re.S)
    if not m:
        die("impossible de lire la mesure loudnorm")
    return json.loads(m.group(0))


def apply_chain(src_wav, dst_wav, s, lufs, measured):
    """Passe 2 : applique la chaîne avec les valeurs mesurées."""
    code, out = run(["ffmpeg", "-y", "-i", str(src_wav),
                     "-af", studio_chain(s, lufs, measured),
                     "-ar", "48000", str(dst_wav)])
    if code != 0:
        die(f"application de la chaîne échouée :\n{out[-800:]}")


def noise_floor(path):
    """Estime le plancher de bruit (dB) via astats."""
    code, out = run(["ffmpeg", "-i", str(path), "-af", "astats", "-f", "null", "-"])
    floors = re.findall(r"Noise floor dB:\s*(-?[\d.]+|-inf)", out)
    if not floors:
        return None
    # -inf = silence numerique total (frequent apres debruitage IA) -> plancher a -120 dB
    vals = [-120.0 if f == "-inf" else float(f) for f in floors]
    return max(-120.0, min(vals))


def spectrogram(path, png):
    run(["ffmpeg", "-y", "-i", str(path),
         "-lavfi", "showspectrumpic=s=1024x400:legend=1", str(png)])


def mux_output(video_src, processed_wav, dst):
    """Recolle l'audio traité dans la vidéo d'origine sans réencoder l'image."""
    code, out = run(["ffmpeg", "-y", "-i", str(video_src), "-i", str(processed_wav),
                     "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                     "-c:a", "aac", "-b:a", "192k", "-shortest", str(dst)])
    if code != 0:
        die(f"remux vidéo échoué :\n{out[-800:]}")


def encode_audio(processed_wav, dst):
    """Encode le WAV traité vers le format demandé par l'extension de sortie."""
    if dst.suffix.lower() == ".wav":
        shutil.copyfile(processed_wav, dst)
        return
    codec = {".m4a": ["-c:a", "aac", "-b:a", "192k"],
             ".aac": ["-c:a", "aac", "-b:a", "192k"],
             ".mp3": ["-c:a", "libmp3lame", "-b:a", "192k"],
             ".flac": ["-c:a", "flac"],
             ".opus": ["-c:a", "libopus", "-b:a", "96k"],
             ".ogg": ["-c:a", "libvorbis", "-q:a", "6"]}
    args = codec.get(dst.suffix.lower())
    if args is None:
        die(f"format de sortie non géré : {dst.suffix}")
    code, out = run(["ffmpeg", "-y", "-i", str(processed_wav), *args, str(dst)])
    if code != 0:
        die(f"encodage sortie échoué :\n{out[-800:]}")


def main():
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Voix qualité studio à partir d'un enregistrement micro.")
    ap.add_argument("input", help="fichier audio ou vidéo")
    ap.add_argument("-o", "--output", help="fichier de sortie (défaut : <nom>_studio.<ext>)")
    ap.add_argument("--no-ai", action="store_true", help="ne pas utiliser DeepFilterNet")
    ap.add_argument("--lufs", type=float, default=-16.0, help="cible loudness (défaut -16)")
    ap.add_argument("--strength", choices=STRENGTHS, default="normal",
                    help="intensité du traitement (défaut normal)")
    ap.add_argument("--compare", action="store_true",
                    help="génère spectrogrammes avant/après à côté de la sortie")
    ap.add_argument("--keep-temp", action="store_true", help="conserve le dossier temporaire")
    args = ap.parse_args()

    src = Path(args.input).expanduser()
    if not src.exists():
        die(f"fichier introuvable : {src}")
    if not shutil.which("ffmpeg"):
        die("ffmpeg introuvable dans le PATH")

    info = probe(src)
    is_video = any(st["codec_type"] == "video" and st.get("disposition", {}).get("attached_pic", 0) == 0
                   for st in info["streams"])
    if not any(st["codec_type"] == "audio" for st in info["streams"]):
        die("aucune piste audio dans ce fichier")

    if args.output:
        dst = Path(args.output).expanduser()
    else:
        ext = src.suffix if is_video or src.suffix.lower() in AUDIO_EXTS else ".wav"
        dst = src.with_name(f"{src.stem}_studio{ext}")

    s = STRENGTHS[args.strength]
    workdir = Path(tempfile.mkdtemp(prefix="studiovoice_"))
    try:
        print(f"Entrée   : {src.name}  ({'vidéo' if is_video else 'audio'})")
        raw = workdir / "raw.wav"
        extract_wav(src, raw)
        floor_before = noise_floor(src)

        # --- Débruitage ---
        denoised = None
        if not args.no_ai and has_deepfilter():
            print("Débruitage : DeepFilterNet (IA)")
            denoised = denoise_ai(raw, workdir)
        if denoised is None:
            print(f"Débruitage : ffmpeg afftdn (nr={s['nr']})")
            denoised = workdir / "denoised.wav"
            denoise_ffmpeg(raw, denoised, s["nr"])

        # --- Chaîne studio, loudnorm 2 passes ---
        print(f"Chaîne studio : EQ + dé-esseur + compression, loudnorm {args.lufs} LUFS (2 passes)")
        measured = loudnorm_analyze(denoised, s, args.lufs)
        processed = workdir / "processed.wav"
        apply_chain(denoised, processed, s, args.lufs, measured)
        floor_after = noise_floor(processed)

        # --- Sortie ---
        if is_video:
            mux_output(src, processed, dst)
        else:
            encode_audio(processed, dst)
        print(f"Sortie   : {dst}")

        # --- Rapport ---
        if floor_before is not None and floor_after is not None:
            after_txt = "silence total (< -120 dB)" if floor_after <= -120.0 else f"{floor_after:.1f} dB"
            print(f"Plancher de bruit : {floor_before:.1f} dB -> {after_txt}")
        print(f"Loudness : {measured['input_i']} LUFS mesuré -> cible {args.lufs} LUFS")

        if args.compare:
            spectrogram(raw, dst.with_name(dst.stem + "_avant.png"))
            spectrogram(processed, dst.with_name(dst.stem + "_apres.png"))
            print(f"Spectrogrammes : {dst.stem}_avant.png / {dst.stem}_apres.png")
    finally:
        if args.keep_temp:
            print(f"Temp conservé : {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
