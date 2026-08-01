import json
import unittest

from pighub_client import (
    build_github_pig_list,
    build_pighub_pig_list,
    make_pig_annotation,
    normalize_image_url,
    parse_ai_annotation,
)


class PigHubClientTests(unittest.TestCase):
    def test_builds_pighub_items_from_api_payload(self):
        payload = {
            "code": 200,
            "message": "ok",
            "data": [
                {
                    "id": 1300,
                    "title": "被捕捉的小猪",
                    "filename": "被捕捉的小🐖.gif",
                    "image_url": "/images/被捕捉的小🐖.gif",
                }
            ],
        }

        pigs = build_pighub_pig_list(payload)

        self.assertEqual(len(pigs), 1)
        self.assertEqual(pigs[0]["id"], "pighub-1300")
        self.assertEqual(pigs[0]["name"], "被捕捉的小猪")
        self.assertEqual(pigs[0]["filename"], "被捕捉的小🐖.gif")
        self.assertNotEqual(pigs[0]["analysis"], "随机抽到的今日小猪，今天也要保持精神。")
        self.assertIn("%F0%9F%90%96", pigs[0]["image_url"])

    def test_rejects_invalid_pighub_payload(self):
        self.assertEqual(build_pighub_pig_list({"code": 40000, "message": "bad"}), [])
        self.assertEqual(build_pighub_pig_list({"data": "not-list"}), [])

    def test_builds_github_items_from_tree_payload(self):
        payload = {
            "tree": [
                {"type": "blob", "path": "data/猪读博.jpg", "sha": "a" * 40},
                {"type": "blob", "path": "data/.DS_Store", "sha": "b" * 40},
                {"type": "tree", "path": "data/nested", "sha": "c" * 40},
            ]
        }

        pigs = build_github_pig_list(payload)

        self.assertEqual(len(pigs), 1)
        self.assertEqual(pigs[0]["id"], "pighubdb-aaaaaaaaaaaa")
        self.assertEqual(pigs[0]["name"], "猪读博")
        self.assertIn("%E7%8C%AA%E8%AF%BB%E5%8D%9A.jpg", pigs[0]["image_url"])

    def test_normalize_image_url_handles_relative_and_absolute_urls(self):
        self.assertEqual(
            normalize_image_url("/images/猪读博.jpg"),
            "https://pighub.top/images/%E7%8C%AA%E8%AF%BB%E5%8D%9A.jpg",
        )
        self.assertEqual(
            normalize_image_url("https://example.com/a b.jpg"),
            "https://example.com/a%20b.jpg",
        )

    def test_annotations_are_specific_to_pig_names(self):
        zombie = make_pig_annotation("僵尸猪", "pighub-1", "僵尸猪.png")
        dice = make_pig_annotation("猪骰", "pighub-2", "猪骰.png")
        generic = make_pig_annotation("小猪快到碗里来", "pighub-3", "小猪快到碗里来.jpg")

        self.assertIn("猪脑", zombie["description"])
        self.assertIn("个性", zombie["analysis"])
        self.assertIn("随机", dice["description"])
        self.assertNotEqual(zombie["analysis"], dice["analysis"])
        self.assertIn("干饭", generic["description"])
        self.assertNotEqual(generic["analysis"], dice["analysis"])

    def test_parses_ai_annotation_from_markdown_wrapper(self):
        result = parse_ai_annotation(
            "```json\n"
            + json.dumps(
                {
                    "description": "墨镜小猪在线装酷",
                    "analysis": "墨镜和翘起的嘴角把气场拉满，今天的你适合带着这份自信出门；遇到麻烦先摆个酷脸，再慢慢把事情处理漂亮。",
                },
                ensure_ascii=False,
            )
            + "\n```"
        )

        self.assertEqual(result["description"], "墨镜小猪在线装酷")
        self.assertIn("墨镜", result["analysis"])

    def test_rejects_incomplete_ai_annotation(self):
        self.assertEqual(parse_ai_annotation("不是 JSON"), {})
        self.assertEqual(
            parse_ai_annotation('{"description":"小猪","analysis":"太短"}'), {}
        )

    def test_constrains_ai_annotation_for_card_layout(self):
        result = parse_ai_annotation(
            json.dumps(
                {
                    "description": "戴着红帽子举着饭碗等待开饭的小猪正在出现",
                    "analysis": "饭碗和红帽子把期待写在了脸上。" * 20,
                },
                ensure_ascii=False,
            )
        )

        self.assertLessEqual(len(result["description"]), 18)
        self.assertLessEqual(len(result["analysis"]), 72)
        self.assertTrue(result["analysis"].endswith(("。", "！", "？", "!", "?")))

    def test_overlong_analysis_stops_at_a_complete_sentence(self):
        result = parse_ai_annotation(
            json.dumps(
                {
                    "description": "风中凌乱，猪立叶！",
                    "analysis": "今日小猪站在绿叶上，头顶还飘着问号，看起来对今天的安排有点懵。别慌，保持这份可爱的迷茫，说不定就能找到方向然后继续一大段话",
                },
                ensure_ascii=False,
            )
        )

        self.assertEqual(
            result["analysis"],
            "今日小猪站在绿叶上，头顶还飘着问号，看起来对今天的安排有点懵。",
        )

    def test_removes_uncomfortable_identity_question(self):
        result = parse_ai_annotation(
            json.dumps(
                {
                    "description": "吃葱装象，梦想 PHP",
                    "analysis": "小猪叼着两根葱努力扮演大象，脑海里还浮现出 PHP 大象。这不就是你吗？",
                },
                ensure_ascii=False,
            )
        )

        self.assertEqual(
            result["analysis"],
            "小猪叼着两根葱努力扮演大象，脑海里还浮现出 PHP 大象。",
        )
        self.assertNotIn("你吗", result["analysis"])


if __name__ == "__main__":
    unittest.main()
