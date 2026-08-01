import asyncio
import datetime
import json
import random
import tempfile
import time
from pathlib import Path
from urllib.parse import quote
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core import AstrBotConfig
from astrbot.core.message.components import At

# 修复导入冲突：PIL的Image重命名为PILImage
from PIL import Image as PILImage
from PIL import ImageDraw, ImageFont

try:
    from .pighub_client import (
        PIGHUB_API_URL,
        PIGHUB_GITHUB_TREE_API,
        build_github_pig_list,
        build_pighub_pig_list,
        parse_ai_annotation,
    )
except ImportError:
    from pighub_client import (
        PIGHUB_API_URL,
        PIGHUB_GITHUB_TREE_API,
        build_github_pig_list,
        build_pighub_pig_list,
        parse_ai_annotation,
    )


REMOTE_RESOURCE_BASE = (
    "https://raw.githubusercontent.com/MegSopern/astrbot_plugin_rollpig/main/resource"
)
REMOTE_TIMEOUT_SECONDS = 12
MAX_REMOTE_RESOURCE_BYTES = 24 * 1024 * 1024
REMOTE_USER_AGENT = "astrbot-plugin-pig-party/remote-resource-loader"
PIGHUB_SOURCE_PREFIX = "pighub"
AI_ANNOTATION_CACHE_VERSION = 1
AI_ANNOTATION_MAX_IMAGE_BYTES = 12 * 1024 * 1024
ACTION_DAILY = "daily"
ACTION_RANDOM = "random"
DEFAULT_PIG_TRIGGER_KEYWORDS = ["猪", "🐷", "🐖", "🐽"]
DEFAULT_DAILY_TRIGGERS = {"今日小猪", "抽小猪", "我的小猪"}
DEFAULT_RANDOM_TRIGGERS = {"随机小猪", "随机猪猪", "猪猪"}


class PigPartyPlugin(Star):
    CANVAS_WIDTH = 800  # 画布宽度
    CANVAS_HEIGHT = 800  # 画布高度
    AVATAR_SIZE = 280  # 头像大小
    SPACING_AVATAR_NAME = 20  # 头像与名称间距
    SPACING_NAME_DESC = 25  # 名称与描述间距
    SPACING_DESC_ANALYSIS = 30  # 描述与解析间距
    DESC_FONT_SIZE = 32  # 描述字体大小
    ANALYSIS_FONT_SIZE = 28  # 解析字体大小
    ANALYSIS_LINE_HEIGHT_FACTOR = 1.6  # 解析行高因子
    ANALYSIS_WIDTH_RATIO = 0.85  # 解析宽度比例
    NAME_FONT_SIZE = 66  # 名称字体大小

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config

        # 配置项
        self.admins_id: list[str] = context.get_config().get("admins_id", [])
        self.at_view_pig: bool = self.config.get("at_view_pig", False)
        self.enable_remote_resource: bool = self.config.get("enable_remote_resource", True)
        self.remote_resource_base: str = str(
            self.config.get("remote_resource_base", REMOTE_RESOURCE_BASE)
        ).rstrip("/")
        self.auto_reply_pig_messages: bool = self.config.get(
            "auto_reply_pig_messages", True
        )
        self.pig_trigger_keywords: list[str] = self._load_keyword_config(
            "pig_trigger_keywords", DEFAULT_PIG_TRIGGER_KEYWORDS
        )
        self.remote_refresh_hours: int = max(
            int(self.config.get("remote_refresh_hours", 12)), 0
        )
        self.random_recent_limit: int = max(
            int(self.config.get("random_recent_limit", 8)), 0
        )
        self.enable_ai_pig_annotation: bool = self.config.get(
            "enable_ai_pig_annotation", True
        )
        self.ai_annotation_provider_id: str = str(
            self.config.get("ai_annotation_provider_id", "") or ""
        ).strip()
        self.ai_annotation_timeout_seconds: int = max(
            min(int(self.config.get("ai_annotation_timeout_seconds", 45)), 120), 10
        )

        # 初始化路径
        self.plugin_dir = Path(__file__).parent
        self.plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_pig_party")
        self.res_dir = self.plugin_dir / "resource"
        self.font_dir = self.res_dir / "font"  # 插件内字体目录（跨平台优先）
        self.piginfo_path = self.res_dir / "pig.json"
        self.image_dir = self.res_dir / "image"
        self.today_path = self.plugin_data_dir / "rollpig_today.json"
        self.random_history_path = self.plugin_data_dir / "random_pig_history.json"
        self.remote_state_path = self.plugin_data_dir / "remote_resource_state.json"
        self.ai_annotation_cache_path = (
            self.plugin_data_dir / "pig_ai_annotation_cache.json"
        )
        self._last_remote_source = ""
        self._ai_annotation_locks: dict[str, asyncio.Lock] = {}

        # 创建必要目录（自动创建font文件夹）
        self.plugin_data_dir.mkdir(parents=True, exist_ok=True)
        self.font_dir.mkdir(parents=True, exist_ok=True)

        # 初始化数据
        self.pig_list = self._load_pig_list()
        self._refresh_pig_list_if_due()
        if not self.pig_list:
            logger.error("小猪信息为空或不存在，请检查资源文件！")
        self.random_history = self.load_json(self.random_history_path, {})
        self.ai_annotation_cache = self._load_ai_annotation_cache()

        # 初始化字体（优先插件内自定义字体，跨平台兼容）
        self.font_regular = self._init_regular_font()  # 常规字体（描述/解析）
        self.font_bold = self._init_bold_font()  # 加粗字体（名称）

    def _load_keyword_config(self, key: str, default: list[str]) -> list[str]:
        value = self.config.get(key, default)
        if isinstance(value, str):
            items = [item.strip() for item in value.replace("，", ",").split(",")]
            return [item for item in items if item]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return default

    def _load_font(
        self, font_candidates: list[str | Path], size: int, purpose: str
    ) -> ImageFont.FreeTypeFont | None:
        """
        通用字体加载器，按候选顺序加载可用字体\n
        :param font_candidates: 字体路径候选列表
        :param size: 字体大小
        :param purpose: 字体用途描述
        :return: 加载的字体对象，失败则返回默认字体
        """
        for font_path in font_candidates:
            if Path(font_path).exists():
                try:
                    return ImageFont.truetype(str(font_path), size)
                except Exception as e:
                    logger.warning(f"加载{purpose}字体{font_path}失败：{e}")
                    continue
        logger.warning(f"未找到{purpose}字体，使用默认字体")
        return ImageFont.load_default()

    def _init_regular_font(self) -> ImageFont.FreeTypeFont | None:
        """初始化常规字体（可爱字体，用于描述/解析）"""
        font_paths = [
            self.font_dir / "可爱字体.ttf",
            self.font_dir / "SourceHanSansCN-Regular.otf",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/PingFang.ttc",
        ]
        return self._load_font(font_paths, self.DESC_FONT_SIZE, "常规")

    def _init_bold_font(self) -> ImageFont.FreeTypeFont | None:
        """初始化加粗字体（荆南麦圆体，用于名称）"""
        font_paths = [
            self.font_dir / "荆南麦圆体.otf",
            self.font_dir / "SourceHanSansCN-Bold.otf",
            "C:/Windows/Fonts/msyhbd.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/PingFang.ttc",
        ]
        return self._load_font(font_paths, self.NAME_FONT_SIZE, "加粗")

    def _get_text_size(
        self, text: str, font: ImageFont.FreeTypeFont
    ) -> tuple[int, int]:
        """
        兼容PIL不同版本的文字尺寸计算\n
        :param text: 文字内容
        :param font: 字体对象
        :return: 文字宽高元组
        """
        draw = ImageDraw.Draw(PILImage.new("RGB", (1, 1)))
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return (bbox[2] - bbox[0], bbox[3] - bbox[1])
        except Exception:
            return draw.textsize(text, font=font)

    def _draw_bold_text(
        self,
        draw: ImageDraw.ImageDraw,
        pos: tuple,
        text: str,
        font: ImageFont.FreeTypeFont,
        fill: tuple,
    ):
        """
        模拟文字加粗（兜底方案）\n
        :param draw: ImageDraw对象
        :param pos: 文字位置
        :param text: 文字内容
        :param font: 字体对象
        :param fill: 文字颜色
        """
        x, y = pos
        offsets = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        for ox, oy in offsets:
            draw.text((x + ox, y + oy), text, fill=fill, font=font)
        draw.text((x, y), text, fill=fill, font=font)

    def load_json(self, path: Path, default):
        """
        加载JSON文件\n
        :param path: 文件路径
        :param default: 默认值（文件不存在或解析失败时使用）
        :return: 解析后的数据对象
        """
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return default
        try:
            return json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError:
            logger.error(f"JSON文件解析失败，重置为默认值：{path}")
            path.write_text(
                json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return default

    def save_json(self, path: Path, data):
        """
        保存JSON数据\n
        :param path: 文件路径
        :param data: 数据对象
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _load_ai_annotation_cache(self) -> dict:
        default = {"version": AI_ANNOTATION_CACHE_VERSION, "records": {}}
        payload = self.load_json(self.ai_annotation_cache_path, default)
        if not isinstance(payload, dict) or not isinstance(payload.get("records"), dict):
            return default
        if payload.get("version") != AI_ANNOTATION_CACHE_VERSION:
            return default
        return payload

    @staticmethod
    def _is_pighub_pig(pig_data: dict) -> bool:
        return str(pig_data.get("id", "")).startswith(PIGHUB_SOURCE_PREFIX)

    def _cached_ai_annotation(self, pig_data: dict) -> dict:
        if not self.enable_ai_pig_annotation or not self._is_pighub_pig(pig_data):
            return {}
        records = self.ai_annotation_cache.get("records", {})
        cached = records.get(str(pig_data.get("id", "")), {})
        if not isinstance(cached, dict) or cached.get("status") != "ok":
            return {}
        return parse_ai_annotation(json.dumps(cached, ensure_ascii=False))

    def _apply_cached_ai_annotation(self, pig_data: dict) -> dict:
        annotation = self._cached_ai_annotation(pig_data)
        if not annotation:
            return pig_data
        result = dict(pig_data)
        result.update(annotation)
        return result

    def _resolve_ai_annotation_provider(self, event: AstrMessageEvent):
        if self.ai_annotation_provider_id:
            getter = getattr(self.context, "get_provider_by_id", None)
            if callable(getter):
                try:
                    return getter(self.ai_annotation_provider_id)
                except Exception:
                    return None
            return None

        get_using = getattr(self.context, "get_using_provider", None)
        if not callable(get_using):
            return None
        umo = getattr(event, "unified_msg_origin", "")
        try:
            return get_using(umo=umo)
        except TypeError:
            try:
                return get_using(umo)
            except Exception:
                return None
        except Exception:
            return None

    def _ai_provider_label(self, provider) -> str:
        if self.ai_annotation_provider_id:
            return self.ai_annotation_provider_id
        provider_config = getattr(provider, "provider_config", None)
        if isinstance(provider_config, dict):
            provider_id = str(provider_config.get("id", "")).strip()
            if provider_id:
                return provider_id
        return type(provider).__name__ if provider is not None else "current:none"

    @staticmethod
    def _validated_image_reference(image_path: Path) -> str:
        try:
            image_size = image_path.stat().st_size
        except OSError:
            return ""
        if image_size <= 0 or image_size > AI_ANNOTATION_MAX_IMAGE_BYTES:
            return ""
        if image_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            return ""
        # AstrBot providers accept local paths and perform provider-specific encoding.
        # Native Gemini expects a path here; passing a data URL is treated as a filename.
        return str(image_path.absolute())

    @staticmethod
    def _ai_annotation_prompt(pig_data: dict) -> str:
        name = " ".join(str(pig_data.get("name", "未知小猪")).split())[:80]
        filename = " ".join(str(pig_data.get("filename", "")).split())[:120]
        return (
            "请认真观察这张猪猪梗图，为‘今日小猪’生成和画面真正相关的趣味文案。"
            "必须利用图中能看见的主体、动作、表情、服饰、道具、文字或场景，至少点出两个具体视觉细节；"
            "不要只根据文件名猜测，不要写成可替换到任意图片上的性格模板。"
            "description 写 8 到 22 个中文字符，像有梗的称号或一句话；"
            "analysis 写 55 到 110 个中文字符，把画面细节自然联想到用户今天的状态，轻松、具体、有趣，避免冒犯。"
            "只输出 JSON，不要 Markdown，不要解释。"
            "格式：{\"description\":\"……\",\"analysis\":\"……\"}。"
            f"\n素材名：{name}\n文件名：{filename or '未知'}"
        )

    def _ai_annotation_retry_blocked(self, pig_id: str, provider_label: str) -> bool:
        record = self.ai_annotation_cache.get("records", {}).get(pig_id, {})
        if not isinstance(record, dict) or record.get("status") != "failed":
            return False
        if str(record.get("provider_id", "")) != provider_label:
            return False
        try:
            return float(record.get("retry_after", 0)) > time.time()
        except (TypeError, ValueError):
            return False

    def _save_ai_annotation_record(self, pig_id: str, record: dict):
        records = self.ai_annotation_cache.setdefault("records", {})
        records[pig_id] = record
        self.save_json(self.ai_annotation_cache_path, self.ai_annotation_cache)

    def _save_ai_annotation_failure(self, pig_id: str, provider_label: str):
        self._save_ai_annotation_record(
            pig_id,
            {
                "status": "failed",
                "provider_id": provider_label,
                "retry_after": int(time.time()) + 30 * 60,
            },
        )

    async def _ensure_ai_pig_annotation(
        self, pig_data: dict, event: AstrMessageEvent
    ) -> dict:
        if not self.enable_ai_pig_annotation or not self._is_pighub_pig(pig_data):
            return pig_data

        cached_result = self._apply_cached_ai_annotation(pig_data)
        if cached_result is not pig_data:
            return cached_result

        pig_id = str(pig_data.get("id", ""))
        lock = self._ai_annotation_locks.setdefault(pig_id, asyncio.Lock())
        async with lock:
            cached_result = self._apply_cached_ai_annotation(pig_data)
            if cached_result is not pig_data:
                return cached_result

            provider = self._resolve_ai_annotation_provider(event)
            provider_label = self._ai_provider_label(provider)
            if self._ai_annotation_retry_blocked(pig_id, provider_label):
                return pig_data
            if provider is None:
                logger.warning("今日小猪识图文案未找到可用模型，暂用静态注解")
                self._save_ai_annotation_failure(pig_id, provider_label)
                return pig_data

            try:
                image_path = await asyncio.to_thread(self.find_image_file, pig_data)
                if not image_path or not image_path.exists():
                    raise FileNotFoundError("pig image unavailable")
                image_reference = await asyncio.to_thread(
                    self._validated_image_reference, image_path
                )
                if not image_reference:
                    raise ValueError("pig image is empty, unsupported, or too large")

                response = await asyncio.wait_for(
                    provider.text_chat(
                        prompt=self._ai_annotation_prompt(pig_data),
                        image_urls=[image_reference],
                        max_tokens=300,
                    ),
                    timeout=self.ai_annotation_timeout_seconds,
                )
                response_text = str(
                    getattr(response, "completion_text", response) or ""
                ).strip()
                annotation = parse_ai_annotation(response_text)
                if not annotation:
                    raise ValueError("vision provider returned invalid annotation JSON")

                self._save_ai_annotation_record(
                    pig_id,
                    {
                        "status": "ok",
                        "provider_id": provider_label,
                        "generated_at": datetime.datetime.now(
                            datetime.timezone.utc
                        ).isoformat(),
                        **annotation,
                    },
                )
                result = dict(pig_data)
                result.update(annotation)
                logger.info("已生成并缓存看图文案：%s provider=%s", pig_id, provider_label)
                return result
            except Exception as exc:
                logger.warning(
                    "今日小猪识图文案生成失败，暂用静态注解：%s error=%s",
                    pig_id,
                    type(exc).__name__,
                )
                self._save_ai_annotation_failure(pig_id, provider_label)
                return pig_data

    def _load_pig_list(self) -> list[dict]:
        local_data = self.load_json(self.piginfo_path, [])
        if self._is_valid_pig_list(local_data):
            return local_data

        remote_data = self._fetch_remote_pig_list()
        if self._is_valid_pig_list(remote_data):
            self.save_json(self.piginfo_path, remote_data)
            logger.info("已从网络资源恢复小猪信息：%s 条", len(remote_data))
            return remote_data

        return []

    def _refresh_pig_list_if_due(self, now: int | None = None) -> list[dict]:
        current_list = getattr(self, "pig_list", [])
        if not self.enable_remote_resource or self.remote_refresh_hours <= 0:
            return current_list

        now = int(time.time()) if now is None else int(now)
        state = self.load_json(self.remote_state_path, {})
        try:
            last_refresh = int(state.get("last_pig_list_refresh", 0) or 0)
        except (TypeError, ValueError):
            last_refresh = 0

        refresh_interval = self.remote_refresh_hours * 60 * 60
        last_source = str(state.get("last_pig_list_source", ""))
        if (
            self._is_valid_pig_list(current_list)
            and last_refresh
            and last_source.startswith(PIGHUB_SOURCE_PREFIX)
            and now - last_refresh < refresh_interval
        ):
            return current_list

        remote_data = self._fetch_remote_pig_list()
        if self._is_valid_pig_list(remote_data):
            self.save_json(self.piginfo_path, remote_data)
            state["last_pig_list_refresh"] = now
            state["last_pig_list_source"] = self._last_remote_source or "unknown"
            self.save_json(self.remote_state_path, state)
            self.pig_list = remote_data
            logger.info(
                "已刷新网络小猪信息：%s 条，来源：%s",
                len(remote_data),
                state["last_pig_list_source"],
            )
            return remote_data

        return current_list

    def _pick_random_pig(self, scope_key: str) -> dict | None:
        pigs = [pig for pig in self.pig_list if isinstance(pig, dict) and pig.get("id")]
        if not pigs:
            return None

        history = self.random_history.setdefault(scope_key, [])
        recent_ids = set(history[-self.random_recent_limit :]) if self.random_recent_limit else set()
        candidates = [pig for pig in pigs if pig["id"] not in recent_ids]
        if not candidates:
            candidates = pigs

        pig = random.choice(candidates)
        if self.random_recent_limit > 0:
            history.append(pig["id"])
            self.random_history[scope_key] = history[-self.random_recent_limit :]
            self._save_random_history()
        return pig

    def _save_random_history(self):
        if hasattr(self, "random_history_path"):
            self.save_json(self.random_history_path, self.random_history)

    @staticmethod
    def _has_command_prefix(message_text: str) -> bool:
        return message_text.startswith(("/", "／"))

    def _message_text(self, event: AstrMessageEvent) -> str:
        message_text = getattr(event, "message_str", "") or getattr(
            getattr(event, "message_obj", None),
            "message_str",
            "",
        )
        return str(message_text or "").strip()

    def _message_body(self, message_text: str) -> str:
        body = message_text.strip()
        if self._has_command_prefix(body):
            body = body[1:].lstrip()
        return body

    def _classify_plain_message(self, message_text: str) -> str | None:
        text = message_text.strip()
        if not text:
            return None

        body = self._message_body(text)
        compact_body = "".join(body.split())
        # Exact commands are handled by @filter.command. Do not handle them again here.
        if compact_body in DEFAULT_DAILY_TRIGGERS or compact_body in DEFAULT_RANDOM_TRIGGERS:
            return None

        if self._has_command_prefix(text):
            return None

        if any(keyword and keyword in body for keyword in self.pig_trigger_keywords):
            return ACTION_RANDOM
        return None

    def _random_scope_key(self, event: AstrMessageEvent) -> str:
        group_id = self._call_event_getter(event, "get_group_id")
        if group_id:
            return f"group:{group_id}"

        sender_id = self._call_event_getter(event, "get_sender_id")
        if sender_id:
            return f"user:{sender_id}"
        return "global"

    @staticmethod
    def _call_event_getter(event: AstrMessageEvent, name: str):
        getter = getattr(event, name, None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:
            return None

    def _is_valid_pig_list(self, data) -> bool:
        if not isinstance(data, list) or not data:
            return False
        return all(isinstance(item, dict) and item.get("id") for item in data)

    def _current_pig_record(self, pig_data: dict) -> dict | None:
        pig_id = str(pig_data.get("id", ""))
        if not pig_id:
            return None
        for item in self.pig_list:
            if isinstance(item, dict) and str(item.get("id", "")) == pig_id:
                return self._apply_cached_ai_annotation(item)
        return None

    def _fetch_remote_pig_list(self) -> list[dict]:
        self._last_remote_source = ""

        payload = self._fetch_remote_json_url(PIGHUB_API_URL)
        pighub_data = build_pighub_pig_list(payload)
        if self._is_valid_pig_list(pighub_data):
            self._last_remote_source = "pighub-api"
            return pighub_data

        payload = self._fetch_remote_json_url(PIGHUB_GITHUB_TREE_API)
        github_data = build_github_pig_list(payload)
        if self._is_valid_pig_list(github_data):
            self._last_remote_source = "pighub-github"
            return github_data

        data = self._fetch_remote_bytes("pig.json")
        if not data:
            return []
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("网络小猪信息解析失败：%s", exc)
            return []
        if not self._is_valid_pig_list(payload):
            logger.warning("网络小猪信息格式无效")
            return []
        self._last_remote_source = "legacy-rollpig"
        return payload

    def _fetch_remote_json_url(self, url: str):
        data = self._fetch_url_bytes(url)
        if not data:
            return None
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("网络小猪JSON解析失败：%s %s", url, exc)
            return None

    def _fetch_remote_bytes(self, relative_path: str) -> bytes | None:
        url = self._remote_resource_url(relative_path)
        return self._fetch_url_bytes(url)

    def _fetch_url_bytes(self, url: str) -> bytes | None:
        if not self.enable_remote_resource:
            return None

        request = Request(url, headers={"User-Agent": REMOTE_USER_AGENT})
        try:
            with urlopen(request, timeout=REMOTE_TIMEOUT_SECONDS) as response:
                status = getattr(response, "status", 200)
                if status >= 400:
                    logger.warning("网络资源返回异常状态：%s %s", status, url)
                    return None

                content_length = response.headers.get("Content-Length")
                if (
                    content_length
                    and content_length.isdigit()
                    and int(content_length) > MAX_REMOTE_RESOURCE_BYTES
                ):
                    logger.warning("网络资源过大，已跳过：%s", url)
                    return None

                data = response.read(MAX_REMOTE_RESOURCE_BYTES + 1)
                if len(data) > MAX_REMOTE_RESOURCE_BYTES:
                    logger.warning("网络资源超过大小限制，已跳过：%s", url)
                    return None
                return data
        except Exception as exc:
            logger.warning("获取网络小猪资源失败：%s %s", url, exc)
            return None

    def _remote_resource_url(self, relative_path: str) -> str:
        safe_path = "/".join(
            quote(part.strip("/"), safe="") for part in relative_path.split("/") if part
        )
        return f"{self.remote_resource_base}/{safe_path}"

    def find_image_file(self, pig_data_or_id) -> Path | None:
        """
        查找对应ID的图片文件\n
        :param pig_data_or_id: 小猪数据或小猪ID
        :return: 图片文件路径，未找到返回None
        """
        pig_data = pig_data_or_id if isinstance(pig_data_or_id, dict) else {}
        pig_id = (
            str(pig_data.get("id", ""))
            if pig_data
            else str(pig_data_or_id or "")
        )
        exts = ["png", "jpg", "jpeg", "webp", "gif"]
        for ext in exts:
            file = self.image_dir / f"{pig_id}.{ext}"
            if file.exists():
                logger.debug(f"找到的小猪图片文件：{file.absolute()}")
                return file
        remote_file = self._download_remote_image(pig_data or pig_id, exts)
        if remote_file:
            return remote_file
        logger.warning(f"未找到小猪ID {pig_id} 对应的图片文件")
        return None

    def _download_remote_image(self, pig_data_or_id, exts: list[str]) -> Path | None:
        pig_data = pig_data_or_id if isinstance(pig_data_or_id, dict) else {}
        pig_id = (
            str(pig_data.get("id", ""))
            if pig_data
            else str(pig_data_or_id or "")
        )
        if not pig_id or any(part in pig_id for part in ("/", "\\")):
            logger.warning("小猪ID不合法，跳过网络图片下载：%s", pig_id)
            return None

        self.image_dir.mkdir(parents=True, exist_ok=True)

        image_url = str(pig_data.get("image_url", "")).strip() if pig_data else ""
        if image_url:
            ext = self._guess_image_ext(
                str(pig_data.get("filename", "")).strip() or image_url, exts
            )
            if ext:
                data = self._fetch_url_bytes(image_url)
                if data:
                    file = self.image_dir / f"{pig_id}.{ext}"
                    file.write_bytes(data)
                    logger.info("已从PigHub缓存小猪图片：%s", file.absolute())
                    return file

        for ext in exts:
            relative_path = f"image/{pig_id}.{ext}"
            data = self._fetch_remote_bytes(relative_path)
            if not data:
                continue

            file = self.image_dir / f"{pig_id}.{ext}"
            file.write_bytes(data)
            logger.info("已从网络资源缓存小猪图片：%s", file.absolute())
            return file
        return None

    @staticmethod
    def _guess_image_ext(name_or_url: str, exts: list[str]) -> str | None:
        path = urlsplit(str(name_or_url)).path
        suffix = Path(path).suffix.lower().lstrip(".")
        return suffix if suffix in exts else None


    def render_pig_image(self, pig_data: dict) -> Path | None:
        """
        整体居中渲染（垂直+水平双居中）\n
        :param pig_data: 小猪数据字典
        :return: 生成的图片临时文件路径，失败返回None
        """
        pig_id = pig_data.get("id", "")
        pig_name = pig_data.get("name", "未知小猪")
        pig_desc = pig_data.get("description", "无描述")
        pig_analysis = pig_data.get("analysis", "无解析")

        # 1. 画布基础配置
        canvas_width = self.CANVAS_WIDTH
        canvas_height = self.CANVAS_HEIGHT
        canvas = PILImage.new("RGB", (canvas_width, canvas_height), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)

        # 2. 预加载所有元素并计算尺寸（用于总高度计算）
        # 2.1 头像尺寸【核心修改：放大到280x280】
        avatar_w, avatar_h = self.AVATAR_SIZE, self.AVATAR_SIZE
        avatar = None
        avatar_path = self.find_image_file(pig_data)
        if avatar_path:
            try:
                avatar = PILImage.open(avatar_path)
                avatar.thumbnail((avatar_w, avatar_h))
                # 居中裁剪（保证正方形，适配新尺寸：280/2=140）
                if avatar.size != (avatar_w, avatar_h):
                    center_x = avatar.width // 2
                    center_y = avatar.height // 2
                    half = self.AVATAR_SIZE // 2
                    crop_box = (
                        center_x - half,
                        center_y - half,
                        center_x + half,
                        center_y + half,
                    )
                    avatar = avatar.crop(crop_box)
            except Exception as e:
                logger.error(f"加载小猪图片失败：{str(e)}")
                avatar = None

        # 2.2 名称尺寸
        name_font = self.font_bold
        name_w, name_h = self._get_text_size(pig_name, name_font)

        # 2.3 描述尺寸
        desc_font = self.font_regular.font_variant(
            size=self.DESC_FONT_SIZE
        )  # 匹配示例的描述字号
        desc_w, desc_h = self._get_text_size(pig_desc, desc_font)

        # 2.4 解析尺寸（自动换行后）
        analysis_font = self.font_regular.font_variant(size=self.ANALYSIS_FONT_SIZE)
        line_height = int(
            self.ANALYSIS_FONT_SIZE * self.ANALYSIS_LINE_HEIGHT_FACTOR
        )  # 匹配示例的行间距
        max_analysis_width = int(
            canvas_width * self.ANALYSIS_WIDTH_RATIO
        )  # 更宽的解析区域
        # 解析文字换行
        analysis_lines = []
        current_line = ""
        for char in pig_analysis:
            current_line += char
            line_w, _ = self._get_text_size(current_line, analysis_font)
            if line_w > max_analysis_width:
                analysis_lines.append(current_line[:-1])
                current_line = char
        if current_line:
            analysis_lines.append(current_line)
        # 计算解析总高度
        analysis_total_h = len(analysis_lines) * line_height

        # 3. 计算整体内容总高度（所有元素+间距）
        spacing_avatar_name = (
            self.SPACING_AVATAR_NAME
        )  # 头像放大后，间距从30调小到20，避免布局拥挤
        spacing_name_desc = self.SPACING_NAME_DESC  # 名称到描述的间距保持
        spacing_desc_analysis = self.SPACING_DESC_ANALYSIS  # 描述到解析的间距保持
        total_content_h = (
            avatar_h
            + spacing_avatar_name
            + name_h
            + spacing_name_desc
            + desc_h
            + spacing_desc_analysis
            + analysis_total_h
        )

        # 4. 计算垂直居中的起始Y坐标（核心：让整个内容块在画布中垂直居中）
        start_y = (canvas_height - total_content_h) // 2

        # 5. 绘制所有元素（基于起始Y坐标，保证整体居中）
        # 5.1 绘制头像（水平+垂直居中）
        avatar_x = (canvas_width - avatar_w) // 2
        avatar_y = start_y
        if avatar:
            canvas.paste(
                avatar,
                (avatar_x, avatar_y),
                mask=avatar if avatar.mode == "RGBA" else None,
            )
        else:
            # 头像加载失败时的提示（适配新尺寸）
            error_font = self.font_regular.font_variant(size=24)
            error_text = "图片加载失败"
            error_w, error_h = self._get_text_size(error_text, error_font)
            error_x = (canvas_width - error_w) // 2
            draw.text(
                (error_x, avatar_y + 120),  # 从90调到120，适配280高度的头像居中
                error_text,
                fill=(255, 0, 0),
                font=error_font,
            )

        # 5.2 绘制名称（水平居中）
        name_y = avatar_y + avatar_h + spacing_avatar_name
        name_x = (canvas_width - name_w) // 2
        self._draw_bold_text(draw, (name_x, name_y), pig_name, name_font, (0, 0, 0))

        # 5.3 绘制描述（水平居中）
        desc_y = name_y + name_h + spacing_name_desc
        desc_x = (canvas_width - desc_w) // 2
        draw.text((desc_x, desc_y), pig_desc, fill=(85, 85, 85), font=desc_font)

        # 5.4 绘制解析（逐行水平居中）
        analysis_y = desc_y + desc_h + spacing_desc_analysis
        for line in analysis_lines:
            line_w, line_h = self._get_text_size(line, analysis_font)
            line_x = (canvas_width - line_w) // 2
            draw.text((line_x, analysis_y), line, fill=(51, 51, 51), font=analysis_font)
            analysis_y += line_height

        # 6. 保存临时文件
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                canvas.save(tmp_path, format="PNG", quality=95)
            logger.debug(f"合成图片成功，临时文件路径：{tmp_path.absolute()}")
            if not tmp_path.exists():
                logger.error(f"临时文件创建失败：{tmp_path}")
                return None
            return tmp_path
        except Exception as e:
            logger.error(f"合成图片失败：{str(e)}")
            return None

    def get_at_ids(self, event: AstrMessageEvent) -> list[str]:
        """
        获取QQ被at用户的id列表
        :param event: Aiocqhttp消息事件对象
        :return: 被at用户的id列表（排除自己）
        """
        return [
            str(seg.qq)
            for seg in event.get_messages()
            if (isinstance(seg, At) and str(seg.qq) != event.get_self_id())  # 排除自己
        ]

    @filter.command("今日小猪", alias={"抽小猪", "我的小猪", "rollpig"})
    async def roll_pig(self, event: AstrMessageEvent):
        """抽取今日小猪"""
        await self._send_daily_pig(event)
        event.stop_event()

    @filter.command("随机小猪", alias={"随机猪猪", "猪猪", "rollpig_random"})
    async def random_pig(self, event: AstrMessageEvent):
        """随机发送一张猪猪表情"""
        await self.send_random_pig(event)
        event.stop_event()

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        if not self.auto_reply_pig_messages:
            return

        message_text = self._message_text(event)
        if not message_text or self._has_command_prefix(message_text):
            return

        action = self._classify_plain_message(message_text)
        if action == ACTION_DAILY:
            await self._send_daily_pig(event)
        elif action == ACTION_RANDOM:
            await self.send_random_pig(event)

    async def _send_daily_pig(self, event: AstrMessageEvent):
        today_str = datetime.date.today().isoformat()
        user_id = event.get_sender_id()
        if self.at_view_pig:
            parts = event.message_str.strip().split()
            at_ids = self.get_at_ids(event)
            if len(at_ids) > 1:
                await event.send(event.plain_result("一次只能抽取一个小猪哦！"))
                return
            if len(parts) >= 2:
                if at_ids[0] not in self.admins_id:
                    user_id = at_ids[0]
                else:
                    await event.send(event.plain_result("你这只小猪，不许对主人不敬！"))
                    return
        today_cache = self.load_json(self.today_path, {"date": "", "records": {}})
        if today_cache.get("date") != today_str:
            today_cache = {"date": today_str, "records": {}}
        user_records = today_cache["records"]

        if user_id in user_records:
            pig = self._current_pig_record(user_records[user_id])
            if pig:
                pig = await self._ensure_ai_pig_annotation(pig, event)
                if pig != user_records[user_id]:
                    user_records[user_id] = pig
                    self.save_json(self.today_path, today_cache)
                    logger.info("已更新今日小猪缓存注解：%s", pig.get("id", ""))
                await self.send_rendered_pig(event, pig, user_id)
                return

        if not self.pig_list:
            await event.send(event.plain_result("小猪信息加载失败，请检查后台报错！"))
            return

        pig = random.choice(self.pig_list)
        pig = await self._ensure_ai_pig_annotation(pig, event)
        user_records[user_id] = pig
        self.save_json(self.today_path, today_cache)

        await self.send_rendered_pig(event, pig, user_id)

    async def send_random_pig(self, event: AstrMessageEvent):
        """发送随机猪猪原图，优先避开最近发送过的素材。"""
        if not self.pig_list:
            await event.send(event.plain_result("暂无可用猪图数据，稍后再试一下吧。"))
            return

        pig = self._pick_random_pig(self._random_scope_key(event))
        if not pig:
            await event.send(event.plain_result("暂无可用猪图数据，稍后再试一下吧。"))
            return

        pig_id = pig.get("id", "")
        image_path = self.find_image_file(pig)
        if image_path and image_path.exists():
            try:
                await event.send(event.image_result(str(image_path.absolute())))
                logger.info("随机猪猪图片发送成功：%s", pig_id)
                return
            except Exception as exc:
                logger.error("发送随机猪猪图片失败：%s", exc)

        pig_name = pig.get("name", "未知小猪")
        await event.send(event.plain_result(f"这只小猪暂时没有可用图片：{pig_name}"))

    async def send_rendered_pig(
        self, event: AstrMessageEvent, pig_data: dict, user_id: str
    ):
        """合成并发送小猪图片"""
        # 使用线程池异步执行CPU密集型任务
        img_path = await asyncio.to_thread(self.render_pig_image, pig_data)
        if img_path and img_path.exists():
            try:
                chain = [Comp.Plain(". 这是你的今日小猪：")]
                group_id = event.get_group_id()
                if group_id:
                    chain.insert(0, Comp.At(qq=user_id))
                await event.send(event.chain_result(chain))
                await event.send(event.image_result(str(img_path.absolute())))
                logger.info("合成图片发送成功")
                return
            except Exception as e:
                logger.error(f"发送合成图片失败：{str(e)}")
            finally:
                try:
                    img_path.unlink(missing_ok=True)
                except Exception as cleanup_err:
                    logger.warning(f"清理临时图片失败：{cleanup_err}")

        await self.send_fallback_msg(event, pig_data)

    async def send_fallback_msg(self, event: AstrMessageEvent, pig_data: dict):
        """降级发送：原始图片 + 纯文本"""
        pig_name = pig_data.get("name", "未知小猪")
        pig_desc = pig_data.get("description", "无描述")
        pig_analysis = pig_data.get("analysis", "无解析")
        pig_id = pig_data.get("id", "")

        text_msg = (
            f"【今日小猪】\n名称：{pig_name}\n描述：{pig_desc}\n解析：{pig_analysis}"
        )
        msg_chain = []

        avatar_path = self.find_image_file(pig_data)
        if avatar_path and avatar_path.exists():
            try:
                msg_chain.append(Comp.Image.fromFileSystem(str(avatar_path.absolute())))
            except Exception as e:
                logger.error(f"发送原始图片失败：{str(e)}")
                text_msg += "\n\n（图片发送失败，仅展示文字信息）"

        msg_chain.append(Comp.Plain(text_msg))
        await event.send(event.chain_result(msg_chain))

    async def terminate(self):
        """插件卸载清理"""
        logger.info("今日小猪插件已卸载")
