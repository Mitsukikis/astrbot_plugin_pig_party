import hashlib
from pathlib import PurePosixPath
from urllib.parse import quote, urljoin, urlsplit, urlunsplit


PIGHUB_SITE_BASE = "https://pighub.top"
PIGHUB_API_URL = f"{PIGHUB_SITE_BASE}/api/images?sort=2"
PIGHUB_GITHUB_TREE_API = (
    "https://api.github.com/repos/BadFish-HSrui/PigHub-DB/git/trees/master?recursive=1"
)
PIGHUB_GITHUB_RAW_BASE = (
    "https://raw.githubusercontent.com/BadFish-HSrui/PigHub-DB/master/"
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
GENERIC_ANALYSIS = "随机抽到的今日小猪，今天也要保持精神。"

KEYWORD_ANNOTATIONS = [
    (
        ("僵尸", "丧尸"),
        "喜欢的食物是猪脑",
        "你有着独特的个性和思维方式，常常让人捉摸不透。你的创造力和想象力丰富，总能带来意想不到的惊喜。",
    ),
    (
        ("骰", "骰子"),
        "智商随机摇",
        "你外表方正，有时却是个不懂变通的可爱猪头。做决定像掷骰子般随性，比起思考更信运气，这份憨直恰恰是你的过喜之处。",
    ),
    (
        ("彩虹", "大色", "七彩"),
        "斯图亚特·彩虹猪",
        "像行走的彩虹，存在感强烈又热情直接。你坦率追求美好事物，偶尔显得太热闹，但是真诚又有魅力。",
    ),
    (
        ("普通", "默认"),
        "普通小猪",
        "你性格温和，喜欢简单的生活，容易满足。在别人眼中可能有些慵懒，但你知道如何享受生活的美好。",
    ),
    (
        ("兔", "兔子"),
        "披着兔耳的伪装专家",
        "你今天的关键词是反差萌。看起来乖巧无害，心里却藏着一套自己的节奏，适合安静地完成一件漂亮的小事。",
    ),
    (
        ("奥", "奥数", "数学"),
        "脑内公式乱飞",
        "你今天适合处理难题，但不适合被别人催。灵感会突然拐弯，答案也许绕远路才出现。",
    ),
    (
        ("碗", "饭", "吃", "叉烧", "烤", "肉", "火锅", "包", "面", "汤"),
        "干饭雷达启动",
        "你今天的能量和食欲绑定很深。吃饱以后判断力会上线，没吃饱时容易把全世界都看成菜单。",
    ),
    (
        ("读博", "博士", "论文", "学习", "上学", "考试", "书"),
        "学术压力型小猪",
        "你今天看起来很有研究精神，其实内心正在和截止日期赛跑。别硬扛，拆成小任务会更容易赢。",
    ),
    (
        ("天使", "天堂", "神", "光环"),
        "自带柔光滤镜",
        "你今天比较容易心软，也容易成为大家默认求助的对象。善良很好，但记得给自己留一点边界。",
    ),
    (
        ("恶魔", "魔", "地狱"),
        "坏心眼含量上升",
        "你今天很适合整点小活，灵感带着一点危险的幽默感。只要不玩过头，大家反而会觉得你很有趣。",
    ),
    (
        ("坦克", "战", "枪", "炮", "武装"),
        "重装突进型小猪",
        "你今天行动力很强，适合把拖了很久的事情直接推进。缺点是容易冲太快，出发前先看一眼地图。",
    ),
    (
        ("机械", "赛博", "机甲", "机器人"),
        "赛博零件还在发光",
        "你的理性模块今天很在线，适合整理、规划和修东西。只是情绪系统也需要保养，别只给自己装冷却风扇。",
    ),
    (
        ("猫", "喵"),
        "猫化小猪",
        "你今天有点高冷又有点黏人，嘴上说随便，心里其实很在意。适合被顺毛，也适合偷偷发光。",
    ),
    (
        ("龟", "乌龟"),
        "慢热防御型小猪",
        "你的节奏不快，但很稳。别人催你的时候先别慌，慢慢推进也能抵达很远的地方。",
    ),
    (
        ("哭", "泪", "悲", "伤"),
        "情绪含水量偏高",
        "你今天比较敏感，容易被小事戳中。把话说出来会轻松很多，不必假装自己一点都不在意。",
    ),
    (
        ("笑", "乐", "哈哈", "开心"),
        "快乐扩散源",
        "你今天很适合把气氛带起来，随口一句都可能让大家笑出声。快乐不是幼稚，是你的续航方式。",
    ),
    (
        ("睡", "懒", "困"),
        "低电量省电模式",
        "你今天适合慢一点，能躺就先躺，能明天再说就别硬撑。恢复精神也是正经任务。",
    ),
]

FALLBACK_DESCRIPTIONS = [
    "今日状态：{name}",
    "{name}人格上线",
    "小猪气质：{name}",
    "{name}能量体",
    "今日抽象指数：{name}",
    "野生{name}出现",
]

FALLBACK_ANALYSES = [
    "你今天抽到了{name}，说明状态里带着一点随性和一点倔强。别急着解释自己，先按自己的节奏把事情做稳。",
    "{name}代表一种很有存在感的小猪气场：看似普通，其实有自己的坚持。今天适合少想一点，多做一点。",
    "今天的{name}提醒你，灵感可能藏在很不起眼的地方。遇到卡住的事，换个角度就会突然顺手。",
    "抽到{name}的人，今天容易被细节影响心情。把重要的事情排在前面，小麻烦就没那么吵了。",
    "{name}带来的运势很直接：该吃吃，该睡睡，该认真时认真。保持松弛，反而更容易拿到好结果。",
    "你今天和{name}的频率对上了，适合用一点幽默化解压力。不要把自己绷太紧，松一点也能很厉害。",
]


def normalize_image_url(url: str, base_url: str = PIGHUB_SITE_BASE) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    if value.startswith("//"):
        value = f"https:{value}"
    elif value.startswith("/"):
        value = urljoin(base_url, value)

    parts = urlsplit(value)
    path = quote(parts.path, safe="/%")
    query = quote(parts.query, safe="=&%")
    fragment = quote(parts.fragment, safe="")
    return urlunsplit((parts.scheme, parts.netloc, path, query, fragment))


def build_pighub_pig_list(payload) -> list[dict]:
    if not isinstance(payload, dict):
        return []

    items = payload.get("data")
    if not isinstance(items, list):
        return []

    pigs: list[dict] = []
    seen_ids: set[str] = set()
    for item in items:
        pig = _build_api_item(item)
        if not pig or pig["id"] in seen_ids:
            continue
        seen_ids.add(pig["id"])
        pigs.append(pig)
    return pigs


def build_github_pig_list(payload) -> list[dict]:
    if not isinstance(payload, dict):
        return []

    tree = payload.get("tree")
    if not isinstance(tree, list):
        return []

    pigs: list[dict] = []
    seen_ids: set[str] = set()
    for item in tree:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "blob":
            continue

        path = str(item.get("path") or "").strip()
        if not path.startswith("data/") or not _is_image_path(path):
            continue

        sha = str(item.get("sha") or "").strip()
        pig_id = f"pighubdb-{sha[:12]}" if sha else f"pighubdb-{_short_hash(path)}"
        if pig_id in seen_ids:
            continue
        seen_ids.add(pig_id)

        filename = PurePosixPath(path).name
        name = _filename_stem(filename) or pig_id
        annotation = make_pig_annotation(name, pig_id, filename)
        pigs.append(
            {
                "id": pig_id,
                "name": name,
                "description": annotation["description"],
                "analysis": annotation["analysis"],
                "filename": filename,
                "image_url": PIGHUB_GITHUB_RAW_BASE + quote(path, safe="/%"),
            }
        )
    return pigs


def _build_api_item(item) -> dict | None:
    if not isinstance(item, dict):
        return None

    filename = str(item.get("filename") or "").strip()
    image_url = str(item.get("image_url") or "").strip()
    if not image_url and filename:
        image_url = f"/images/{filename}"
    if not image_url or not _is_image_path(filename or image_url):
        return None

    raw_id = item.get("id")
    if raw_id is None or str(raw_id).strip() == "":
        raw_id = _short_hash(filename or image_url)

    pig_id = f"pighub-{raw_id}"
    title = str(item.get("title") or "").strip()
    name = title or _filename_stem(filename) or pig_id
    annotation = make_pig_annotation(name, pig_id, filename)
    return {
        "id": pig_id,
        "name": name,
        "description": annotation["description"],
        "analysis": annotation["analysis"],
        "filename": filename or PurePosixPath(urlsplit(image_url).path).name,
        "image_url": normalize_image_url(image_url),
    }


def make_pig_annotation(name: str, pig_id: str = "", filename: str = "") -> dict:
    clean_name = str(name or "").strip() or "未知小猪"
    haystack = f"{clean_name} {filename}".lower()
    for keywords, description, analysis in KEYWORD_ANNOTATIONS:
        if any(keyword.lower() in haystack for keyword in keywords):
            return {"description": description, "analysis": analysis}

    seed = f"{clean_name}|{pig_id}|{filename}"
    description = _stable_pick(FALLBACK_DESCRIPTIONS, seed + "|desc").format(
        name=clean_name
    )
    analysis = _stable_pick(FALLBACK_ANALYSES, seed + "|analysis").format(
        name=clean_name
    )
    if analysis == GENERIC_ANALYSIS:
        analysis = FALLBACK_ANALYSES[0].format(name=clean_name)
    return {"description": description, "analysis": analysis}


def _is_image_path(path: str) -> bool:
    suffix = PurePosixPath(str(path)).suffix.lower()
    return suffix in IMAGE_EXTENSIONS


def _filename_stem(filename: str) -> str:
    return PurePosixPath(str(filename)).stem.strip()


def _short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _stable_pick(options: list[str], seed: str) -> str:
    if not options:
        return ""
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return options[int(digest[:8], 16) % len(options)]
