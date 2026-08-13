#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = ["kokoro-onnx>=0.5", "soundfile>=0.12", "numpy>=1.26"]
# ///
"""Generate narration audio and provenance sidecars from approved scripts.

Usage:
    uv run scripts/generate_audio.py <book-id> [level]      one book, one or all levels
    uv run scripts/generate_audio.py --all                  every book, every level
    uv run scripts/generate_audio.py --inspect-pronunciation "text"
    ./bookflow audio <book-id> [level]                      same, via the CLI

Behaviour:
- Voices only scripts whose front matter says `status: complete` (--allow-draft overrides).
- Skips audio whose sidecar sha256 still matches the script (--force overrides).
- Calibrates speaking speed so measured words-per-minute tracks
  `base_words_per_minute` in config/audio.json (--no-calibrate keeps the raw speed).
- Inserts short pauses between sentences groups and longer ones between paragraphs.
- Writes compressed audio (mp3) when the local soundfile build supports it,
  otherwise wav, plus a sidecar JSON required by config/audio.json.

Engine: kokoro-onnx, the ONNX build of the open-weight Kokoro-82M model — the
same voices as the PyTorch `kokoro` package without the multi-gigabyte torch
dependency, and it installs on any supported Python. Model files (~340 MB)
download once into models/ (git-ignored).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf

from pronunciation import phonemize_with_dictionary

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
MODEL_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
SAMPLE_RATE = 24000


def load_config() -> dict:
    config = json.loads((ROOT / "config/audio.json").read_text(encoding="utf-8"))
    tts = config["tts"]
    pronunciation_path = ROOT / tts["pronunciation_dictionary"]
    pronunciation_bytes = pronunciation_path.read_bytes()
    pronunciation_doc = json.loads(pronunciation_bytes)
    return {
        "levels": config["levels"],
        "target_wpm": config.get("base_words_per_minute", 150),
        "voice": tts.get("default_voice", "bf_emma"),
        "voices": tts.get("voices", {}),
        "output_format": tts.get("output_format", "mp3"),
        "pronunciations": pronunciation_doc["entries"],
        "pronunciation_sha256": hashlib.sha256(pronunciation_bytes).hexdigest(),
    }


def voice_lang(voice: str) -> str:
    """Kokoro voice ids start with the language: a* American, b* British."""
    return "en-us" if voice.startswith("a") else "en-gb"


def dictionary_affects(script_text: str, sidecar: dict, entries: list[dict]) -> bool:
    """A dictionary change only stales audio it could actually alter (mirrors check.py)."""
    if sidecar.get("pronunciation_terms"):
        return True
    lang = sidecar.get("lang", "")
    for entry in entries:
        if lang not in entry.get("phonemes", {}):
            continue
        for spelling in (entry["term"], *entry.get("aliases", [])):
            if re.search(rf"(?<!\w){re.escape(spelling)}(?!\w)", script_text, re.IGNORECASE):
                return True
    return False


def parse_script(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                key, separator, value = line.partition(":")
                if separator:
                    meta[key.strip()] = value.strip()
            text = text[end + 5:]
    return meta, text


def narration(text: str) -> str:
    text = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`>#]", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def chunked_paragraphs(text: str, max_chars: int = 350) -> list[list[str]]:
    """Sentence-packed chunks per paragraph, kept below the model's comfort limit."""
    paragraphs = [p.strip().replace("\n", " ") for p in re.split(r"\n\s*\n", text) if p.strip()]
    result = []
    for paragraph in paragraphs:
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            if current and len(current) + len(sentence) + 1 > max_chars:
                chunks.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            chunks.append(current)
        result.append(chunks)
    return result


def ensure_models(quantized: bool) -> tuple[Path, Path]:
    MODELS.mkdir(exist_ok=True)
    names = ("kokoro-v1.0.int8.onnx" if quantized else "kokoro-v1.0.onnx", "voices-v1.0.bin")
    paths = []
    for name in names:
        destination = MODELS / name
        if not destination.exists() or destination.stat().st_size == 0:
            print(f"Downloading {name} (one-off) ...")
            partial = destination.with_suffix(destination.suffix + ".part")
            urllib.request.urlretrieve(f"{MODEL_RELEASE}/{name}", partial)
            partial.rename(destination)
        paths.append(destination)
    return paths[0], paths[1]


class Synthesiser:
    def __init__(self, model_path: Path, voices_path: Path, voice: str, lang: str,
                 pronunciations: list[dict]):
        from kokoro_onnx import Kokoro

        self.kokoro = Kokoro(str(model_path), str(voices_path))
        self.model_name = model_path.name
        self.voice = voice
        self.lang = lang
        self.pronunciations = pronunciations
        self.used_pronunciations: set[str] = set()

    def phonemes(self, text: str) -> tuple[str, list[str]]:
        """Return final Kokoro phonemes and the dictionary terms applied."""
        return phonemize_with_dictionary(
            text,
            self.lang,
            self.pronunciations,
            lambda value, lang: self.kokoro.tokenizer.phonemize(value, lang),
            set(self.kokoro.tokenizer.vocab),
        )

    def create(self, text: str, speed: float) -> np.ndarray:
        phonemes, used = self.phonemes(text)
        self.used_pronunciations.update(used)
        samples, sample_rate = self.kokoro.create(
            phonemes,
            voice=self.voice,
            speed=speed,
            lang=self.lang,
            is_phonemes=True,
        )
        if sample_rate != SAMPLE_RATE:
            raise SystemExit(f"unexpected sample rate {sample_rate}")
        return samples.astype(np.float32)

    def calibrate(self, paragraphs: list[list[str]], base_speed: float, target_wpm: int) -> float:
        """Measure the voice's natural pace on the opening chunks, return adjusted speed."""
        sample = [chunk for paragraph in paragraphs for chunk in paragraph][:3]
        if not sample:
            return base_speed
        words = sum(len(chunk.split()) for chunk in sample)
        seconds = sum(len(self.create(chunk, base_speed)) for chunk in sample) / SAMPLE_RATE
        measured = words / seconds * 60
        if abs(measured - target_wpm) / target_wpm <= 0.05:
            return base_speed
        adjusted = round(min(1.4, max(0.7, base_speed * target_wpm / measured)), 2)
        print(f"  calibrated speed {base_speed} -> {adjusted} ({measured:.0f} wpm vs target {target_wpm})")
        return adjusted

    def render(self, paragraphs: list[list[str]], speed: float) -> np.ndarray:
        chunk_gap = np.zeros(int(0.30 * SAMPLE_RATE), dtype=np.float32)
        paragraph_gap = np.zeros(int(0.55 * SAMPLE_RATE), dtype=np.float32)
        total = sum(len(p) for p in paragraphs)
        pieces: list[np.ndarray] = []
        done = 0
        for pi, paragraph in enumerate(paragraphs):
            for ci, chunk in enumerate(paragraph):
                pieces.append(self.create(chunk, speed))
                done += 1
                print(f"\r  synthesised {done}/{total} chunks", end="", flush=True)
                if ci < len(paragraph) - 1:
                    pieces.append(chunk_gap)
            if pi < len(paragraphs) - 1:
                pieces.append(paragraph_gap)
        print()
        if not pieces:
            raise SystemExit("script produced no narration text")
        return np.concatenate(pieces)


def generate(book_dir: Path, level: str, synth: Synthesiser, config: dict,
             args: argparse.Namespace) -> str:
    script_path = book_dir / "scripts" / f"{level}.md"
    if not script_path.exists():
        return "no script"
    meta, body = parse_script(script_path)
    if meta.get("status") != "complete" and not args.allow_draft:
        return f"skipped (status: {meta.get('status', 'unknown')})"
    text = narration(body)
    if not text or "TODO" in text:
        return "skipped (script empty or contains TODO)"

    # Audio identity is (level, voice): each voice gets its own file + sidecar.
    audio_dir = book_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    voice = synth.voice
    sidecar_path = audio_dir / f"{level}.{voice}.json"
    script_sha = hashlib.sha256(script_path.read_bytes()).hexdigest()
    if sidecar_path.exists() and not args.force:
        previous = json.loads(sidecar_path.read_text(encoding="utf-8"))
        existing = audio_dir / f"{level}.{voice}.{previous.get('output_format', 'wav')}"
        dictionary_ok = (
            previous.get("pronunciation_dictionary_sha256") == config["pronunciation_sha256"]
            or not dictionary_affects(body, previous, config["pronunciations"])
        )
        if previous.get("source_script_sha256") == script_sha and dictionary_ok \
                and existing.exists():
            return "up to date"

    synth.used_pronunciations.clear()
    paragraphs = chunked_paragraphs(text)
    speed = args.speed
    if not args.no_calibrate:
        speed = synth.calibrate(paragraphs, args.speed, config["target_wpm"])
    samples = synth.render(paragraphs, speed)
    seconds = len(samples) / SAMPLE_RATE

    output_format = config["output_format"]
    output = audio_dir / f"{level}.{voice}.{output_format}"
    try:
        sf.write(output, samples, SAMPLE_RATE)
    except Exception as error:  # local libsndfile without mp3 support
        print(f"  {output_format} unavailable ({error}); writing wav")
        output_format = "wav"
        output = audio_dir / f"{level}.{voice}.wav"
        sf.write(output, samples, SAMPLE_RATE)
    for stale in audio_dir.glob(f"{level}.{voice}.*"):
        if stale.suffix not in {f".{output_format}", ".json"}:
            stale.unlink()

    words = len(text.split())
    sidecar = {
        "$schema": "../../../../schemas/audio-sidecar.schema.json",
        "schema_version": 2,
        "book_id": book_dir.name,
        "duration": level,
        "engine": "kokoro-onnx",
        "engine_version": importlib.metadata.version("kokoro-onnx"),
        "model": synth.model_name,
        "voice": synth.voice,
        "lang": synth.lang,
        "speed": speed,
        "sample_rate": SAMPLE_RATE,
        "output_format": output_format,
        "source_script": str(script_path.relative_to(ROOT)),
        "source_script_sha256": script_sha,
        "pronunciation_dictionary_sha256": config["pronunciation_sha256"],
        "pronunciation_terms": sorted(synth.used_pronunciations, key=str.casefold),
        "script_words": words,
        "audio_seconds": round(seconds, 3),
        "measured_wpm": round(words / seconds * 60, 2),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    return f"wrote audio/{output.name} ({seconds / 60:.1f} min at {sidecar['measured_wpm']:.0f} wpm)"


def listening_priority(book_dir: Path, levels: list[str]) -> list[str]:
    """Recommended level first, then the 30-second scan layer, then the rest."""
    if len(levels) == 1:
        return levels
    first: list[str] = []
    try:
        content = json.loads((book_dir / "content.json").read_text(encoding="utf-8"))
        recommended = content.get("editorial", {}).get("recommended_level")
        if recommended in levels:
            first.append(recommended)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    if "30-seconds" in levels and "30-seconds" not in first:
        first.append("30-seconds")
    return first + [level for level in levels if level not in first]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("book_id", nargs="?", help="book directory name under library/books")
    parser.add_argument("level", nargs="?", help="one level; omit for all configured levels")
    parser.add_argument("--all", action="store_true", help="every book in the library")
    parser.add_argument("--voice", help="override the configured voice")
    parser.add_argument("--speed", type=float, default=1.0, help="base speed before calibration")
    parser.add_argument("--force", action="store_true", help="regenerate even when up to date")
    parser.add_argument("--allow-draft", action="store_true", help="voice scripts not marked complete")
    parser.add_argument("--no-calibrate", action="store_true", help="skip words-per-minute calibration")
    parser.add_argument("--quantized", action="store_true", help="use the smaller int8 model")
    parser.add_argument(
        "--inspect-pronunciation",
        metavar="TEXT",
        help="print the final phonemes and matched dictionary terms, then exit",
    )
    args = parser.parse_args()

    config = load_config()
    if args.level and args.level not in config["levels"]:
        parser.error(f"unknown level '{args.level}'; configured: {', '.join(config['levels'])}")
    voice = args.voice or config["voice"]
    if config["voices"] and voice not in config["voices"]:
        print(f"note: voice '{voice}' is not listed in config/audio.json voices; using it anyway")
    model_path, voices_path = ensure_models(args.quantized)
    synth = Synthesiser(
        model_path,
        voices_path,
        voice,
        voice_lang(voice),
        config["pronunciations"],
    )
    if args.inspect_pronunciation:
        phonemes, used = synth.phonemes(args.inspect_pronunciation)
        print(f"language: {synth.lang}")
        print(f"dictionary terms: {', '.join(used) if used else '(none)'}")
        print(f"phonemes: {phonemes}")
        return 0

    books_root = ROOT / "library/books"
    if args.all:
        books = sorted(path for path in books_root.iterdir() if path.is_dir())
    elif args.book_id:
        books = [books_root / args.book_id]
        if not books[0].is_dir():
            parser.error(f"no such book: {args.book_id}")
    else:
        parser.error("give a book id or --all")
    levels = [args.level] if args.level else list(config["levels"])

    failures = 0
    for book_dir in books:
        print(f"{book_dir.name}:")
        for level in listening_priority(book_dir, levels):
            try:
                outcome = generate(book_dir, level, synth, config, args)
            except Exception as error:
                outcome = f"FAILED: {error}"
                failures += 1
            print(f"  {level}: {outcome}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
