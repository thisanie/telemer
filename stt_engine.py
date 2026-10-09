"""Local Hugging Face speech-to-text engine for teleMER experiments."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Optional

import numpy as np
import soundfile as sf
import torch
from scipy.signal import resample_poly
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline


MODEL_ID = "openai/whisper-small"
DEFAULT_LANGUAGE = "hindi"
TARGET_SAMPLE_RATE = 16_000


class STTEngine:
    """Transcribe local audio with a multilingual Whisper model."""

    def __init__(
        self,
        model_id: str = MODEL_ID,
        language: str = DEFAULT_LANGUAGE,
        device: Optional[str] = None,
    ) -> None:
        self.model_id = model_id
        self.language = language
        self.device = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        self.torch_dtype = (
            torch.float16 if torch.cuda.is_available() else torch.float32
        )

        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            self.model_id,
            dtype=self.torch_dtype,
            low_cpu_mem_usage=True,
            use_safetensors=True,
        ).to(self.device)
        processor = AutoProcessor.from_pretrained(self.model_id)

        self.transcriber = pipeline(
            "automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            dtype=self.torch_dtype,
            device=self.device,
        )

    def _load_audio(self, audio_path: str | Path) -> tuple[np.ndarray, int]:
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")

        audio_array, source_sample_rate = sf.read(
            path,
            dtype="float32",
            always_2d=False,
        )
        if audio_array.ndim == 2:
            audio_array = audio_array.mean(axis=1)

        if source_sample_rate != TARGET_SAMPLE_RATE:
            audio_array = resample_poly(
                audio_array,
                TARGET_SAMPLE_RATE,
                source_sample_rate,
            ).astype("float32")

        return audio_array, TARGET_SAMPLE_RATE

    def _make_audio_input(
        self,
        audio_array: np.ndarray,
        sample_rate: int,
    ) -> dict[str, Any]:
        # The Transformers pipeline mutates this dictionary during preprocessing.
        return {"raw": audio_array, "sampling_rate": sample_rate}

    def transcribe(
        self,
        audio_path: str | Path,
        return_timestamps: bool = False,
    ) -> str | dict[str, Any]:
        """Transcribe an audio file, optionally returning timestamp chunks."""
        audio_array, sample_rate = self._load_audio(audio_path)
        result = self.transcriber(
            self._make_audio_input(audio_array, sample_rate),
            return_timestamps=return_timestamps,
            generate_kwargs={
                "language": self.language,
                "task": "transcribe",
            },
        )

        if return_timestamps:
            return result
        return result["text"].strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe a local audio file")
    parser.add_argument("audio_path", help="Path to a WAV, FLAC, or other soundfile-readable file")
    parser.add_argument("--language", default=DEFAULT_LANGUAGE)
    parser.add_argument("--timestamps", action="store_true")
    args = parser.parse_args()

    engine = STTEngine(language=args.language)
    result = engine.transcribe(args.audio_path, return_timestamps=args.timestamps)

    if args.timestamps:
        print(result.get("text", "").strip())
        for chunk in result.get("chunks", []):
            start, end = chunk["timestamp"]
            print(f"{start:.2f}s - {end:.2f}s: {chunk['text'].strip()}")
    else:
        print(result)


if __name__ == "__main__":
    main()
