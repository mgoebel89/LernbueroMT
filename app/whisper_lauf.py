"""Ein Diktat erkennen (laeuft mit dem Python aus /opt/lernbuero-whisper, nicht im Webdienst).

  python whisper_lauf.py <audiodatei> <modellordner> <modell> [fachwoerter]

Gibt eine Zeile JSON aus: {"text": ..., "unsicher": [...], "audio_s": ..., "dauer_s": ...}. Nur lokal, ohne Internet.
Eigener Prozess je Diktat: das Modell belegt nur waehrend des Erkennens Arbeitsspeicher.
"""
import json
import os
import sys
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")


def main():
    datei, ordner, modell = sys.argv[1:4]
    fachwoerter = sys.argv[4] if len(sys.argv) > 4 else ""
    os.environ.setdefault("HF_HOME", os.path.join(ordner, "hf"))
    from faster_whisper import WhisperModel   # erst hier: dauert etwas
    start = time.monotonic()
    m = WhisperModel(modell, device="cpu", compute_type="int8", download_root=ordner, local_files_only=True,
                     cpu_threads=os.cpu_count() or 2)
    segmente, info = m.transcribe(datei, language="de", beam_size=5, vad_filter=True, word_timestamps=True,
                                  initial_prompt=fachwoerter or None, condition_on_previous_text=False)
    teile, unsicher = [], []
    for s in segmente:
        teile.append(s.text.strip())
        for w in s.words or []:
            wort = w.word.strip(" ,.!?;:")
            if wort and w.probability < 0.5 and wort not in unsicher:
                unsicher.append(wort)
    print(json.dumps({"text": " ".join(t for t in teile if t), "unsicher": unsicher[:20],
                      "audio_s": round(info.duration, 1), "dauer_s": round(time.monotonic() - start, 1)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
