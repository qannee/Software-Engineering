import hashlib
from pathlib import Path

import httpx

from app.core.config import settings


class TTSAdapter:
    async def synthesize(self, text: str, locale: str) -> dict:
        if not settings.TTS_API_KEY:
            raise RuntimeError("Chưa cấu hình TTS_API_KEY để tạo tệp audio")
        voice = settings.TTS_VOICE_ID_VI if locale == "vi-VN" else settings.TTS_VOICE_ID_EN
        if not voice:
            raise RuntimeError(f"Chưa cấu hình voice ID cho {locale}")
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=5.0)) as client:
            response = await client.post(url, params={"output_format": "mp3_44100_128"}, json={"text": text, "model_id": settings.TTS_MODEL}, headers={"xi-api-key": settings.TTS_API_KEY, "Accept": "audio/mpeg"})
            response.raise_for_status()
        digest = hashlib.sha256(response.content).hexdigest()
        filename = f"{digest[:32]}-{locale}.mp3"
        folder = Path(settings.AUDIO_DIRECTORY)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / filename).write_bytes(response.content)
        return {"audio_url": f"/media/audio/{filename}", "checksum": digest, "voice": voice}
