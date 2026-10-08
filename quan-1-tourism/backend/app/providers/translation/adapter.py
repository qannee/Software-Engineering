import httpx

from app.core.config import settings


class TranslationAdapter:
    async def translate_to_english(self, text: str) -> str:
        if not settings.TRANSLATION_API_KEY:
            raise RuntimeError("Chưa cấu hình TRANSLATION_API_KEY; nhập bản dịch tiếng Anh trong trang quản trị")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post("https://api-free.deepl.com/v2/translate", data={"text": text, "source_lang": "VI", "target_lang": "EN-US"}, headers={"Authorization": f"DeepL-Auth-Key {settings.TRANSLATION_API_KEY}"})
            response.raise_for_status()
        return response.json()["translations"][0]["text"]
