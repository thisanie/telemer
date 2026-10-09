"""Gemini Live speech-to-text adapter for the realtime call flow."""

from __future__ import annotations

import asyncio
import os

from google import genai
from google.genai import types


DEFAULT_MODEL = "gemini-3.5-transcribe-live"


class GeminiLiveSTTEngine:
    """Transcribe one browser audio clip with a Gemini Live session."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        resolved_api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not resolved_api_key:
            raise RuntimeError("GOOGLE_API_KEY is not set")
        self.model = model or os.getenv("TELEMER_TRANSCRIPTION_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        self.client = genai.Client(api_key=resolved_api_key)

    def _config(self) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities=["TEXT"],
            input_audio_transcription=types.AudioTranscriptionConfig(
                language_codes=[],
            ),
        )

    async def transcribe_realtime(
        self,
        audio_queue: asyncio.Queue[bytes | None],
        transcript_queue: asyncio.Queue[dict[str, str] | None],
    ) -> None:
        """Bridge streamed PCM audio to Gemini and return partial/final text."""
        fragments: list[str] = []
        audio_ended = asyncio.Event()
        try:
            async with self.client.aio.live.connect(
                model=self.model,
                config=self._config(),
            ) as session:
                async def send_audio() -> None:
                    while True:
                        audio_bytes = await audio_queue.get()
                        if audio_bytes is None:
                            await session.send_realtime_input(audio_stream_end=True)
                            audio_ended.set()
                            return
                        await session.send_realtime_input(
                            audio=types.Blob(
                                data=audio_bytes,
                                mime_type="audio/pcm;rate=16000",
                            ),
                        )

                sender = asyncio.create_task(send_audio())
                try:
                    async with asyncio.timeout(self.timeout):
                        async for response in session.receive():
                            server_content = response.server_content
                            if server_content and server_content.input_transcription:
                                text = server_content.input_transcription.text or ""
                                if text:
                                    fragments.append(text)
                                    await transcript_queue.put(
                                        {"type": "partial", "text": text}
                                    )
                            if (
                                server_content
                                and server_content.turn_complete
                                and audio_ended.is_set()
                            ):
                                await transcript_queue.put(
                                    {
                                        "type": "final",
                                        "text": " ".join(fragments).strip(),
                                    }
                                )
                                break
                finally:
                    sender.cancel()
                    await asyncio.gather(sender, return_exceptions=True)
        finally:
            await transcript_queue.put(None)

    async def transcribe(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/wav",
    ) -> str:
        if not audio_bytes:
            return ""

        fragments: list[str] = []
        async with self.client.aio.live.connect(
            model=self.model,
            config=self._config(),
        ) as session:
            await session.send_realtime_input(
                audio=types.Blob(data=audio_bytes, mime_type=mime_type),
            )
            await session.send_realtime_input(audio_stream_end=True)

            async with asyncio.timeout(self.timeout):
                async for response in session.receive():
                    server_content = response.server_content
                    if server_content and server_content.input_transcription:
                        text = server_content.input_transcription.text or ""
                        if text:
                            fragments.append(text)
                    if server_content and server_content.turn_complete:
                        break

        return " ".join(fragments).strip()