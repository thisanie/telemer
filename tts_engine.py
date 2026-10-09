"""Local Kokoro text-to-speech engine for teleMER experiments."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import torch
from kokoro import KPipeline


MODEL_ID = "hexgrad/Kokoro-82M"
LANGUAGE_CODE = "h"
VOICE_OPTIONS = ("hf_alpha", "hf_beta", "hm_omega", "hm_psi")
DEFAULT_VOICE = "hf_alpha"
DEFAULT_SPEED = 1.0
SAMPLING_RATE = 24_000


class TTSEngine:
    """Generate speech locally with Kokoro's Hindi voice pipeline.

    Kokoro does not currently provide a dedicated Indian-English voice. The
    Hindi voice family is used here as the closest available Indian-region
    approximation; callers should evaluate the voices before production use.
    """

    def __init__(
        self,
        voice: str = DEFAULT_VOICE,
        speed: float = DEFAULT_SPEED,
        device: Optional[str] = None,
    ) -> None:
        if voice not in VOICE_OPTIONS:
            raise ValueError(
                f"Unsupported voice {voice!r}. Choose one of: {', '.join(VOICE_OPTIONS)}"
            )
        if speed <= 0:
            raise ValueError("speed must be greater than zero")

        self.voice = voice
        self.speed = speed
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.pipeline = KPipeline(
            lang_code=LANGUAGE_CODE,
            repo_id=MODEL_ID,
            device=self.device,
        )

    def synthesize(
        self,
        text: str,
        output_path: Optional[str | Path] = None,
    ) -> tuple[np.ndarray, int]:
        """Generate speech and optionally save it as a WAV file."""
        if not text.strip():
            raise ValueError("text must not be empty")

        audio_chunks = []
        for _, _, audio in self.pipeline(
            text,
            voice=self.voice,
            speed=self.speed,
            split_pattern=r"\n+",
        ):
            if isinstance(audio, torch.Tensor):
                audio = audio.detach().cpu().numpy()
            audio_chunks.append(np.asarray(audio, dtype=np.float32))

        if not audio_chunks:
            raise RuntimeError("Kokoro generated no audio chunks")

        waveform = np.concatenate(audio_chunks)
        if output_path is not None:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            sf.write(output_file, waveform, SAMPLING_RATE)

        return waveform, SAMPLING_RATE


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a WAV file with Kokoro TTS")
    parser.add_argument("text", help="Text to synthesize")
    parser.add_argument(
        "--output",
        default="artifacts/tts_sample.wav",
        help="Output WAV path",
    )
    parser.add_argument("--voice", choices=VOICE_OPTIONS, default=DEFAULT_VOICE)
    parser.add_argument("--speed", type=float, default=DEFAULT_SPEED)
    args = parser.parse_args()

    engine = TTSEngine(voice=args.voice, speed=args.speed)
    waveform, sampling_rate = engine.synthesize(args.text, args.output)
    duration_seconds = len(waveform) / sampling_rate
    print(f"Saved {args.output}")
    print(f"Device: {engine.device}")
    print(f"Voice: {engine.voice}")
    print(f"Duration: {duration_seconds:.2f} seconds")


if __name__ == "__main__":
    main()
