import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image, ImageChops

from daily_catalog import load_daily_catalog
from pighub_client import parse_ai_annotation


ROOT = Path(__file__).resolve().parents[1]


def load_plugin():
    names = (
        "astrbot",
        "astrbot.api",
        "astrbot.api.message_components",
        "astrbot.api.event",
        "astrbot.api.star",
        "astrbot.core",
        "astrbot.core.message",
        "astrbot.core.message.components",
    )
    modules = {name: types.ModuleType(name) for name in names}
    for name, module in modules.items():
        parent, _, child = name.rpartition(".")
        if parent:
            setattr(modules[parent], child, module)
    filters = types.SimpleNamespace(
        command=lambda *a, **k: lambda f: f,
        event_message_type=lambda *a, **k: lambda f: f,
        EventMessageType=types.SimpleNamespace(ALL="all"),
    )
    modules["astrbot.api"].logger = Mock()
    modules["astrbot.api.event"].AstrMessageEvent = object
    modules["astrbot.api.event"].filter = filters
    modules["astrbot.api.star"].Context = object
    modules["astrbot.api.star"].Star = object
    modules["astrbot.api.star"].StarTools = object
    modules["astrbot.core"].AstrBotConfig = dict
    modules["astrbot.core.message.components"].At = type("At", (), {})
    spec = importlib.util.spec_from_file_location(
        "pig_party_test_main", ROOT / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module.PigPartyPlugin


Plugin = load_plugin()


class DailyCatalogueTests(unittest.TestCase):
    def test_every_pig_has_a_distinct_description_and_matching_bundled_image(self):
        pigs = load_daily_catalog(ROOT / "resource" / "daily_pigs.json")
        self.assertEqual(len(pigs), 96)
        self.assertEqual(len({p["description"] for p in pigs}), 96)
        self.assertEqual(len({p["analysis"] for p in pigs}), 96)
        for pig in pigs:
            with self.subTest(pig=pig["id"]):
                self.assertEqual(pig["source"], "curated-rollpig")
                with Image.open(
                    ROOT / "resource" / "daily_image" / pig["filename"]
                ) as image:
                    image.verify()

    def test_invalid_catalogue_does_not_replace_a_valid_pool(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalogue.json"
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(load_daily_catalog(path), [])
            sample = load_daily_catalog(ROOT / "resource" / "daily_pigs.json")[0]
            path.write_text(
                json.dumps([sample, sample, {**sample, "id": "../outside"}]),
                encoding="utf-8",
            )
            self.assertEqual(len(load_daily_catalog(path)), 1)

    def test_preserved_vision_parser_accepts_complete_text_and_rejects_garbage(self):
        annotation = parse_ai_annotation(
            json.dumps(
                {
                    "description": "戴着兔耳认真营业",
                    "analysis": "头上竖着一对兔耳，圆圆的鼻子却藏不住猪猪身份。今天的可爱伪装就靠这份认真了。",
                }
            )
        )
        self.assertEqual(annotation["description"], "戴着兔耳认真营业")
        self.assertTrue(annotation["analysis"].endswith("。"))
        self.assertEqual(parse_ai_annotation("not json"), {})


class DailyFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.plugin = Plugin.__new__(Plugin)
        p = self.plugin
        p.daily_pigs = load_daily_catalog(ROOT / "resource" / "daily_pigs.json")
        p.daily_pig_source = "curated"
        p.pig_list = [
            {
                "id": "pighub-test",
                "name": "网络小猪",
                "analysis": "原始文案",
                "description": "测试",
            }
        ]
        p.daily_image_dir = ROOT / "resource" / "daily_image"
        p.image_dir = Path(self.directory.name) / "image"
        p.res_dir = ROOT / "resource"
        p.font_dir = p.res_dir / "font"
        p.today_path = Path(self.directory.name) / "today.json"
        p.remote_state_path = Path(self.directory.name) / "remote.json"
        p.piginfo_path = Path(self.directory.name) / "pighub.json"
        p.enable_remote_resource = False
        p.enable_ai_pig_annotation = True
        p.ai_annotation_cache = {"version": 1, "records": {}}
        p.at_view_pig = True
        p.admins_id = []
        p.send_rendered_pig = AsyncMock()
        p._resolve_ai_annotation_provider = Mock(
            side_effect=AssertionError("Curated pigs must not call a model")
        )
        self.event = Mock(message_str="今日小猪 多余文字")
        self.event.get_sender_id.return_value = "test-user"
        self.event.get_messages.return_value = []
        self.event.send = AsyncMock()

    async def test_curated_draw_is_stable_and_works_without_network_or_model(self):
        await self.plugin._send_daily_pig(self.event)
        first = self.plugin.send_rendered_pig.call_args.args[1]
        with patch("random.choice", side_effect=AssertionError("Cannot reroll today")):
            await self.plugin._send_daily_pig(self.event)
        second = self.plugin.send_rendered_pig.call_args.args[1]
        self.assertEqual(first, second)
        self.assertEqual(first["source"], "curated-rollpig")
        self.plugin._resolve_ai_annotation_provider.assert_not_called()

    async def test_existing_pighub_assignment_survives_pool_switch_and_index_removal(
        self,
    ):
        import datetime

        old = {
            "id": "pighub-removed",
            "name": "旧小猪",
            "description": "旧描述",
            "analysis": "旧解析",
        }
        self.plugin.save_json(
            self.plugin.today_path,
            {
                "date": datetime.date.today().isoformat(),
                "records": {"test-user": old},
            },
        )
        self.plugin.enable_ai_pig_annotation = False
        with patch(
            "random.choice",
            side_effect=AssertionError("Cannot change an existing assignment"),
        ):
            await self.plugin._send_daily_pig(self.event)
        self.assertEqual(self.plugin.send_rendered_pig.call_args.args[1], old)

    async def test_pighub_mode_and_empty_curated_catalogue_keep_existing_pool(self):
        self.plugin.daily_pig_source = "pighub"
        self.assertIs(self.plugin._daily_pig_pool(), self.plugin.pig_list)
        self.plugin.daily_pig_source = "curated"
        self.plugin.daily_pigs = []
        self.assertIs(self.plugin._daily_pig_pool(), self.plugin.pig_list)

    async def test_remote_refresh_cannot_overwrite_daily_text(self):
        original = [dict(p) for p in self.plugin.daily_pigs]
        self.plugin.enable_remote_resource = True
        self.plugin.remote_refresh_hours = 12
        self.plugin._last_remote_source = "pighub-api"
        self.plugin._fetch_remote_pig_list = Mock(return_value=self.plugin.pig_list)
        self.plugin._refresh_pig_list_if_due(now=10000)
        self.assertEqual(self.plugin.daily_pigs, original)

    async def test_bundled_image_works_offline_and_missing_image_uses_its_own_url(self):
        pig = self.plugin.daily_pigs[0]
        self.plugin._download_remote_image = Mock(
            side_effect=AssertionError("Must use bundled image")
        )
        self.assertTrue(self.plugin.find_image_file(pig).is_file())
        self.assertIsNone(self.plugin.find_image_file("../outside"))
        self.plugin.daily_image_dir = Path(self.directory.name)
        self.plugin._download_remote_image = Mock(return_value=None)
        self.assertIsNone(self.plugin.find_image_file(pig))
        self.assertEqual(
            self.plugin._download_remote_image.call_args.args[0]["image_url"],
            pig["image_url"],
        )

    async def test_longest_descriptions_render_with_clear_top_and_bottom_margins(self):
        self.plugin.font_regular = self.plugin._init_regular_font()
        self.plugin.font_bold = self.plugin._init_bold_font()
        pigs = sorted(
            self.plugin.daily_pigs, key=lambda p: len(p["analysis"]), reverse=True
        )[:4]
        for pig in pigs:
            with self.subTest(pig=pig["id"]):
                path = self.plugin.render_pig_image(pig)
                self.assertIsNotNone(path)
                try:
                    with Image.open(path) as image:
                        bounds = ImageChops.difference(
                            image.convert("RGB"), Image.new("RGB", image.size, "white")
                        ).getbbox()
                        self.assertEqual(image.width, 800)
                        self.assertGreater(bounds[1], 20)
                        self.assertLess(bounds[3], image.height - 20)
                finally:
                    path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
