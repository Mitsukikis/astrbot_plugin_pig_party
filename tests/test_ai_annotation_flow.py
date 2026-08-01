import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

try:
    from main import AI_ANNOTATION_CACHE_VERSION, PigPartyPlugin
except ModuleNotFoundError:
    PigPartyPlugin = None
    AI_ANNOTATION_CACHE_VERSION = 1


class StubVisionProvider:
    provider_config = {"id": "gemini-test"}

    def __init__(self, response_text):
        self.response_text = response_text
        self.calls = 0

    async def text_chat(self, **kwargs):
        self.calls += 1
        assert Path(kwargs["image_urls"][0]).is_file()
        assert "具体视觉细节" in kwargs["prompt"]
        return SimpleNamespace(completion_text=self.response_text)


@unittest.skipIf(PigPartyPlugin is None, "AstrBot runtime is not installed")
class AiAnnotationFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.image_path = root / "pighub-42.png"
        Image.new("RGB", (24, 24), (255, 120, 150)).save(self.image_path)

        self.plugin = object.__new__(PigPartyPlugin)
        self.plugin.enable_ai_pig_annotation = True
        self.plugin.ai_annotation_provider_id = ""
        self.plugin.ai_annotation_timeout_seconds = 5
        self.plugin.ai_annotation_cache_path = root / "annotation-cache.json"
        self.plugin.ai_annotation_cache = {
            "version": AI_ANNOTATION_CACHE_VERSION,
            "records": {},
        }
        self.plugin._ai_annotation_locks = {}
        self.plugin.find_image_file = lambda pig: self.image_path

        self.pig = {
            "id": "pighub-42",
            "name": "墨镜猪",
            "filename": "cool-pig.png",
            "description": "静态模板描述",
            "analysis": "静态模板解析，用来验证模型失败时能够继续正常返回。",
        }

    async def test_generates_once_then_reuses_id_cache(self):
        payload = json.dumps(
            {
                "description": "墨镜一戴谁也不爱",
                "analysis": "黑色墨镜配上微微扬起的猪嘴，今天的你气场已经先到场了；适合自信开工，但记得酷归酷，消息还是要回。",
            },
            ensure_ascii=False,
        )
        provider = StubVisionProvider(payload)
        self.plugin._resolve_ai_annotation_provider = lambda event: provider

        first = await self.plugin._ensure_ai_pig_annotation(self.pig, object())
        second = await self.plugin._ensure_ai_pig_annotation(self.pig, object())

        self.assertEqual(provider.calls, 1)
        self.assertEqual(first["description"], "墨镜一戴谁也不爱")
        self.assertEqual(second["description"], first["description"])
        self.assertEqual(
            self.plugin.ai_annotation_cache["records"]["pighub-42"]["status"],
            "ok",
        )

    async def test_invalid_model_output_falls_back_and_sets_cooldown(self):
        provider = StubVisionProvider("这不是可用的 JSON")
        self.plugin._resolve_ai_annotation_provider = lambda event: provider

        result = await self.plugin._ensure_ai_pig_annotation(self.pig, object())

        self.assertEqual(result["description"], "静态模板描述")
        self.assertEqual(
            self.plugin.ai_annotation_cache["records"]["pighub-42"]["status"],
            "failed",
        )

    async def test_exact_commands_are_available_to_plain_group_messages(self):
        self.plugin.pig_trigger_keywords = ["猪", "🐷"]
        self.assertEqual(self.plugin._classify_plain_message("今日小猪"), "daily")
        self.assertEqual(self.plugin._classify_plain_message("随机小猪"), "random")
        self.assertEqual(self.plugin._classify_plain_message("你是猪吗"), "random")

    async def test_one_event_can_only_be_claimed_once(self):
        class StubEvent:
            def __init__(self):
                self.extra = {}

            def get_extra(self, key):
                return self.extra.get(key)

            def set_extra(self, key, value):
                self.extra[key] = value

        event = StubEvent()
        self.assertTrue(self.plugin._claim_event(event, "daily"))
        self.assertFalse(self.plugin._claim_event(event, "daily"))
        self.assertFalse(self.plugin._claim_event(event, "random"))


if __name__ == "__main__":
    unittest.main()
