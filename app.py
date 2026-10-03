import os
import sys
import json
import re
import html
import asyncio
from contextlib import asynccontextmanager
import threading
import time
import webbrowser
from pathlib import Path
from typing import Dict, Any, Optional
import socket

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import httpx
import logging

# 优先解析 IPv4，避免在纯直连、国内宽带、修改 hosts、加速器或代理环境下因无效 IPv6 路由导致的连接超时挂起
orig_getaddrinfo = socket.getaddrinfo

def getaddrinfo_prefer_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    try:
        res = orig_getaddrinfo(host, port, family, type, proto, flags)
        v4 = [r for r in res if r[0] == socket.AF_INET]
        v6 = [r for r in res if r[0] == socket.AF_INET6]
        return (v4 + v6) if v4 else res
    except Exception:
        return orig_getaddrinfo(host, port, family, type, proto, flags)

socket.getaddrinfo = getaddrinfo_prefer_ipv4

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 判断是否处于 PyInstaller 打包环境
IS_FROZEN = getattr(sys, 'frozen', False)
if IS_FROZEN:
    # 打包运行环境下，前端静态资源解压在 sys._MEIPASS
    BUNDLE_DIR = Path(sys._MEIPASS)
    # 配置文件 config.json 必须保存在 exe 所在目录，这样配置才能持久化
    APP_DIR = Path(sys.executable).parent
else:
    BUNDLE_DIR = Path(__file__).parent
    APP_DIR = Path(__file__).parent

STATIC_DIR = BUNDLE_DIR / "static"
CONFIG_FILE = APP_DIR / "config.json"
LOG_FILE = APP_DIR / "steamtonotion.log"

# 日志：控制台输出格式保持原样不变；同时滚动写入 APP_DIR/steamtonotion.log（2MB × 3 份）。
# 目的：打包版关闭黑框后控制台内容即丢失，有文件日志才能在用户报错时复盘。
CONSOLE_LOG_FORMAT = "%(levelname)s:%(name)s:%(message)s"
FILE_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

def setup_logging():
    from logging.handlers import RotatingFileHandler
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(CONSOLE_LOG_FORMAT))
    root.addHandler(console)

    try:
        file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(FILE_LOG_FORMAT))
        root.addHandler(file_handler)
    except Exception as log_err:
        print(f"[WARN] 无法创建日志文件 {LOG_FILE}: {log_err}", file=sys.stderr)

    # httpx 的 INFO 级别会打印完整请求 URL，而 Steam Web API 的 key 位于查询参数中，
    # 为避免 API Key 被写进日志文件，这里只保留 httpx 的告警及以上级别。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return root

setup_logging()
logger = logging.getLogger(__name__)

http_client: Optional[httpx.AsyncClient] = None
http_client_proxy: str = ""  # 记录当前连接池实际使用的代理，用于判断是否需要重建
config_lock = threading.Lock()

def effective_proxy(proxy: Optional[str] = None) -> str:
    """返回应当生效的代理：显式传入优先，否则读取已保存的配置。"""
    if proxy is not None:
        return (proxy or "").strip()
    try:
        return (load_config().get("proxy") or "").strip()
    except Exception:
        return ""

def create_http_client(proxy: Optional[str] = None) -> httpx.AsyncClient:
    global http_client_proxy
    proxy_url = effective_proxy(proxy)
    http_client_proxy = proxy_url

    transport_kwargs: Dict[str, Any] = {
        "retries": 1,
        "verify": False,
        "limits": httpx.Limits(
            max_keepalive_connections=10,
            max_connections=25,
            keepalive_expiry=15.0
        )
    }
    use_trust_env = True
    if proxy_url:
        transport_kwargs["proxy"] = proxy_url
        use_trust_env = False

    transport = httpx.AsyncHTTPTransport(**transport_kwargs)
    
    timeout_config = httpx.Timeout(
        connect=6.0,
        read=10.0,
        write=5.0,
        pool=3.0
    )
    
    return httpx.AsyncClient(
        transport=transport,
        timeout=timeout_config,
        follow_redirects=True,
        trust_env=use_trust_env,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )

async def safe_close_client(client: httpx.AsyncClient):
    try:
        # 宽限期必须大于最长请求超时（Notion 12s），否则换池会把飞行中的请求直接打断
        await asyncio.sleep(20.0)
        if not client.is_closed:
            await client.aclose()
    except Exception:
        pass

async def reset_client(proxy: Optional[str] = None, force: bool = False) -> httpx.AsyncClient:
    """重建（或复用）全局 HTTP 连接池。

    代理未变化且未强制重建时直接复用现有连接池——这样"保存配置"不会无谓换池，
    也就不会把此刻飞行中的 Steam/Notion 请求打断（旧连接池由安全关闭任务在宽限期后回收）。
    """
    global http_client
    target_proxy = effective_proxy(proxy)
    if not force and http_client is not None and not http_client.is_closed and target_proxy == http_client_proxy:
        logger.info("reset_client: proxy unchanged, reusing existing connection pool")
        return http_client
    old_client = http_client
    http_client = create_http_client(proxy=proxy)
    if old_client is not None and not old_client.is_closed:
        asyncio.create_task(safe_close_client(old_client))
    return http_client

_last_auto_heal_ts = 0.0

async def auto_heal_client():
    """Safely recreate HTTP client pool when connection issues occur.

    带 5 秒节流：网络中断时多个请求会同时报连接错误，避免短时间内反复换池。
    """
    global _last_auto_heal_ts
    now = time.monotonic()
    if now - _last_auto_heal_ts < 5.0:
        logger.info("auto_heal_client skipped (throttled within 5s)")
        return
    _last_auto_heal_ts = now
    try:
        await reset_client(force=True)
        logger.info("HTTP client pool rebuilt after connection issue")
    except Exception as e:
        logger.warning(f"Error during auto_heal_client: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = create_http_client()
    yield
    if http_client and not http_client.is_closed:
        await http_client.aclose()

def get_client() -> httpx.AsyncClient:
    global http_client
    if http_client is None or http_client.is_closed:
        http_client = create_http_client()
    return http_client

app = FastAPI(title="Steam to Notion Backend", lifespan=lifespan)

# 安全加固：本工具为纯本地同源应用（前端所有请求都是相对路径），无需开放跨域。
# 原 allow_origins=["*"] + allow_credentials=True 会让任意网页都能读取/调用本地 API。
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not STATIC_DIR.exists():
    STATIC_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

DEFAULT_CONFIG = {
    "notion_token": "",
    "steamgriddb_key": "",
    "steam_api_key": "",
    "steam_id64": "",
    "database_id": "",
    "proxy": "",
    "field_mapping": {
        "title": {"name": "游戏名称", "type": "title", "enabled": True},
        "title_en": {"name": "全名", "type": "rich_text", "enabled": True},
        "cover_grid": {"name": "封面", "type": "files", "enabled": True},
        "genre": {"name": "类型", "type": "multi_select", "enabled": True},
        "tags": {"name": "标签", "type": "multi_select", "enabled": True},
        "release_date": {"name": "发行日期", "type": "date", "enabled": True},
        "playtime": {"name": "游玩时长", "type": "number", "enabled": True},
        "developer": {"name": "开发商", "type": "multi_select", "enabled": True},
        "publisher": {"name": "发行商", "type": "multi_select", "enabled": True},
        "description": {"name": "简介", "type": "rich_text", "enabled": True},
        "steam_url": {"name": "Steam链接", "type": "url", "enabled": True}
    },
    "use_hero_as_cover": True,
    "use_icon_as_page_icon": True
}

GENRE_TRANSLATIONS = {
    "Action": "动作",
    "Adventure": "冒险",
    "RPG": "角色扮演",
    "Strategy": "策略",
    "Simulation": "模拟",
    "Casual": "休闲",
    "Indie": "独立",
    "Sports": "体育",
    "Racing": "竞速",
    "Massively Multiplayer": "大型多人在线",
    "Free to Play": "免费开玩",
    "Early Access": "抢先体验",
    "Animation & Modeling": "动画制作与建模",
    "Audio Production": "音频制作",
    "Design & Illustration": "设计与插画",
    "Education": "教育",
    "Game Development": "游戏开发",
    "Photo Editing": "照片编辑",
    "Utilities": "实用工具",
    "Video Production": "视频制作",
    "Web Publishing": "网页发布",
    "Accounting": "财务会计",
    "Documentary": "纪录片",
    "Episodic": "剧集",
    "Movie": "电影",
    "Short": "短片",
    "Tutorial": "教程"
}

CJK_CHAR_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
LATIN_CHAR_RE = re.compile(r'[A-Za-z]')

def strip_embedded_english(name: str) -> str:
    """官方名称里"中文名 + 英文原名"混写时，剥掉英文部分，只留本地化名称。

    只处理两种"一眼可辨"的形态，其余一律原样返回（绝不猜测、绝不按空格硬拆）：

      1) 尾部括号内为纯英文：'空战奇兵8 希孚之翼 (ACE COMBAT 8: WINGS OF THEVE)' -> '空战奇兵8 希孚之翼'
      2) 冒号分隔且一侧纯中文、另一侧纯英文：'Valheim: 英灵神殿' -> '英灵神殿'

    刻意不处理"空格分隔"（如 '仁王 Complete Edition'）：这类名字里的英文往往是版本后缀
    （Complete Edition / Deluxe / Remastered 等）而不是英文原名，拆掉会丢信息。
    中文名自带冒号的情况（'全面战争：战锤3'、'极限竞速：地平线 5'）因两侧都是中文而不会被改动。
    """
    if not name or not isinstance(name, str):
        return name
    name = name.strip()

    # 形态 1：尾部括号内是纯英文
    m = re.match(r'^(.*?)\s*[（(]\s*([^)）]*?)\s*[)）]\s*$', name)
    if m:
        head, tail = m.group(1).strip(), m.group(2).strip()
        if head and tail and CJK_CHAR_RE.search(head) and LATIN_CHAR_RE.search(tail) and not CJK_CHAR_RE.search(tail):
            return head

    # 形态 2：冒号分隔，一侧纯中文、另一侧纯英文
    m = re.match(r'^(.*?)\s*[:：]\s*(.*)$', name)
    if m:
        a, b = m.group(1).strip(), m.group(2).strip()
        if a and b:
            a_cjk, a_lat = bool(CJK_CHAR_RE.search(a)), bool(LATIN_CHAR_RE.search(a))
            b_cjk, b_lat = bool(CJK_CHAR_RE.search(b)), bool(LATIN_CHAR_RE.search(b))
            if a_cjk and not a_lat and b_lat and not b_cjk:
                return a
            if b_cjk and not b_lat and a_lat and not a_cjk:
                return b

    return name

def decode_unicode_escapes(s: str) -> str:
    """Decode raw unicode escape sequences like \\u89d2\\u8272 into real characters."""
    if not s or not isinstance(s, str):
        return s or ""
    if "\\u" in s or "\\U" in s:
        try:
            return json.loads(f'"{s}"')
        except Exception:
            try:
                return s.encode("utf-8").decode("unicode_escape")
            except Exception:
                pass
    return s

def load_config() -> dict:
    with config_lock:
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    return {**DEFAULT_CONFIG, **config}
            except Exception as e:
                logger.error(f"Error loading config: {e}")
        return DEFAULT_CONFIG.copy()

def save_config(config: dict):
    with config_lock:
        tmp_file = CONFIG_FILE.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, CONFIG_FILE)

@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/api/config")
async def get_config():
    config = load_config()
    notion_token = config.get("notion_token", "")
    steamgriddb_key = config.get("steamgriddb_key", "")
    steam_api_key = config.get("steam_api_key", "")
    steam_id64 = config.get("steam_id64", "")
    
    masked_config = config.copy()
    if notion_token:
        masked_config["notion_token"] = f"***{notion_token[-4:]}" if len(notion_token) >= 4 else "***"
    if steamgriddb_key:
        masked_config["steamgriddb_key"] = f"***{steamgriddb_key[-4:]}" if len(steamgriddb_key) >= 4 else "***"
    if steam_api_key:
        masked_config["steam_api_key"] = f"***{steam_api_key[-4:]}" if len(steam_api_key) >= 4 else "***"
        
    masked_config["notion_token_set"] = bool(notion_token)
    masked_config["steamgriddb_key_set"] = bool(steamgriddb_key)
    masked_config["steam_api_key_set"] = bool(steam_api_key)
    masked_config["steam_id64_set"] = bool(steam_id64)
    masked_config["steam_id64"] = steam_id64
    masked_config["proxy"] = config.get("proxy", "")
    return masked_config

@app.post("/api/config")
async def update_config(request: Request):
    try:
        new_config = await request.json()
        config = load_config()
        # Merge dicts
        for k, v in new_config.items():
            if k in ["notion_token", "steamgriddb_key", "steam_api_key"] and isinstance(v, str) and v.startswith("***"):
                continue # don't overwrite with masked string
            # 空 database_id 视为"未选择数据库"，直接忽略，避免前端未加载数据库列表时清空已保存的库
            if k == "database_id" and not (isinstance(v, str) and v.strip()):
                continue
            if k == "field_mapping" and isinstance(v, dict):
                # 空映射视为无效输入（前端映射表未渲染时会提交 {}），忽略以避免清空已有映射
                if not v:
                    continue
                # Preserve existing type and enabled state
                old_mapping = config.get("field_mapping", {})
                merged_mapping = {}
                for mk, mv in v.items():
                    if isinstance(mv, dict):
                        old_item = old_mapping.get(mk, {})
                        ptype = mv.get("type") or old_item.get("type", "rich_text")
                        is_enabled = mv.get("enabled", old_item.get("enabled", True))
                        merged_mapping[mk] = {
                            "name": mv.get("name", old_item.get("name", "")),
                            "type": ptype,
                            "enabled": bool(is_enabled)
                        }
                    else:
                        merged_mapping[mk] = mv
                # 本次未提交的字段（如历史遗留键）保持原样，避免被静默丢弃
                for mk, mv in old_mapping.items():
                    if mk not in merged_mapping:
                        merged_mapping[mk] = mv
                config[k] = merged_mapping
            elif isinstance(v, dict) and k in config and isinstance(config[k], dict):
                config[k].update(v)
            else:
                config[k] = v
        save_config(config)
        await reset_client()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

def parse_steam_date(date_str: str) -> Optional[str]:
    if not date_str:
        return None
    date_str = date_str.strip()
    
    # Try parsing '2022年2月25日'
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日?', date_str)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
        
    # YYYY-MM-DD
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', date_str)
    if m:
        return m.group(0)
        
    months = {
        'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04', 'May': '05', 'Jun': '06',
        'Jul': '07', 'Aug': '08', 'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
    }
    
    # 'Feb 25, 2022' or '25 Feb, 2022'
    m = re.search(r'([A-Z][a-z]{2})\s+(\d{1,2}),?\s+(\d{4})', date_str)
    if m:
        return f"{m.group(3)}-{months[m.group(1)]}-{m.group(2).zfill(2)}"
    
    m = re.search(r'(\d{1,2})\s+([A-Z][a-z]{2}),?\s+(\d{4})', date_str)
    if m:
        return f"{m.group(3)}-{months[m.group(2)]}-{m.group(1).zfill(2)}"
        
    # 'Jan 2023'
    m = re.search(r'([A-Z][a-z]{2})\s+(\d{4})', date_str)
    if m:
        return f"{m.group(2)}-{months[m.group(1)]}-01"
        
    # '2023'
    m = re.search(r'^(\d{4})$', date_str)
    if m:
        return f"{m.group(1)}-01-01"
        
    return None

@app.get("/api/steam/search")
async def search_steam_games(q: str = ""):
    """Search Steam games with smart sequential prioritization and instant ID fallback."""
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Search query cannot be empty")
    
    # 提取类似 "Game Name (1325200)" 或者 URL 中的纯数字 ID
    url_match = re.search(r'app/(\d+)', query)
    if url_match:
        query = url_match.group(1)
        
    cleaned_query = re.sub(r'\s*\(\d{2,10}\)\s*$', '', query).strip()
    if cleaned_query:
        query = cleaned_query
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
    }
    client = get_client()

    # 如果用户直接输入纯数字 App ID
    if query.isdigit():
        app_id_int = int(query)
        icon = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{query}/capsule_sm_120.jpg"
        # 尝试快速获取名称
        try:
            res = await client.get(
                f"https://store.steampowered.com/api/appdetails?appids={query}&l=schinese",
                headers=headers,
                timeout=5.0
            )
            if res.status_code == 200:
                app_data = res.json().get(query, {})
                if app_data.get("success"):
                    name = app_data.get("data", {}).get("name", f"App {query}")
                    return {"results": [{"app_id": app_id_int, "name": name, "icon": icon}]}
        except Exception:
            pass
        return {"results": [{"app_id": app_id_int, "name": f"Steam App {query}", "icon": icon}]}

    async def fetch_store_search(term: str, cc: str = "cn", lang: str = "schinese") -> list:
        try:
            res = await client.get(
                "https://store.steampowered.com/api/storesearch/",
                params={"term": term, "l": lang, "cc": cc},
                headers=headers,
                timeout=6.0
            )
            if res.status_code == 200:
                data = res.json()
                items = data.get("items", [])
                if items:
                    return [{
                        "app_id": item.get("id"),
                        "name": item.get("name", ""),
                        "icon": item.get("tiny_image", "")
                    } for item in items[:10]]
        except (httpx.ConnectTimeout, httpx.ConnectError) as ce:
            logger.warning(f"Storesearch ({cc}/{lang}) connection issue: {type(ce).__name__}")
            await auto_heal_client()
        except Exception as e:
            logger.warning(f"Storesearch ({cc}/{lang}) failed: {type(e).__name__} {e}")
        return []

    async def fetch_suggest_search(term: str) -> list:
        try:
            res = await client.get(
                "https://store.steampowered.com/search/suggest",
                params={"term": term, "f": "games", "cc": "CN", "l": "schinese"},
                headers=headers,
                timeout=5.0
            )
            if res.status_code == 200:
                pattern = re.compile(
                    r'data-ds-appid=[\x22\x27](\d+)[\x22\x27].*?<div class=[\x22\x27]match_name[\x22\x27]>([^<]+)</div>.*?<div class=[\x22\x27]match_img[\x22\x27]><img src=[\x22\x27]([^\x22\x27]+)[\x22\x27]',
                    re.DOTALL
                )
                matches = pattern.findall(res.text)
                if matches:
                    return [{
                        "app_id": int(appid),
                        "name": html.unescape(name.strip()),
                        "icon": img.strip()
                    } for appid, name, img in matches[:10]]
        except Exception as e:
            logger.warning(f"Store suggest failed: {type(e).__name__} {e}")
        return []

    async def fetch_community_search(term: str) -> list:
        # steamcommunity.com 在国内无代理或仅加速商店的环境下无法访问，设 3.5s 超时快速尝试
        try:
            res = await client.get(
                f"https://steamcommunity.com/actions/SearchApps/{term}",
                headers=headers,
                timeout=3.5
            )
            if res.status_code == 200:
                items = res.json()
                if isinstance(items, list) and items:
                    return [{
                        "app_id": int(item.get("appid", 0)),
                        "name": item.get("name", ""),
                        "icon": item.get("icon") or item.get("logo", "")
                    } for item in items[:10]]
        except Exception as e:
            logger.info(f"Community SearchApps skipped/failed: {type(e).__name__}")
        return []

    # 1. 优先请求官方国区商店（UU加速器、直连 hosts、规则代理首选，90%场景单次即中且极快）
    results = await fetch_store_search(query, cc="cn", lang="schinese")
    if results:
        return {"results": results}

    # 2. 如果国区无结果（锁区游戏、特殊英文名称），回退至美区商店
    results = await fetch_store_search(query, cc="us", lang="english")
    if results:
        return {"results": results}

    # 3. 如果仍无结果，尝试 Store Suggest（同属 store.steampowered.com）
    results = await fetch_suggest_search(query)
    if results:
        return {"results": results}

    # 4. 兜底回退：尝试 Community SearchApps（支持带代理或全局翻墙的用户）
    results = await fetch_community_search(query)
    if results:
        return {"results": results}

    return {"results": []}

async def get_steam_playtime(app_id: str, config: dict) -> Optional[float]:
    """Fetch playtime for a specific app from Steam Web API GetOwnedGames and GetRecentlyPlayedGames (family sharing fallback)."""
    api_key = (config.get("steam_api_key") or "").strip()
    steam_id = (config.get("steam_id64") or "").strip()
    if not api_key or not steam_id:
        return None
    client = get_client()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
    params = {
        "key": api_key,
        "steamid": steam_id,
        "appids_filter[0]": str(app_id),
        "include_played_free_games": 1,
        "format": "json"
    }
    for attempt in range(2):
        try:
            res = await client.get(url, params=params, headers=headers, timeout=6.0)
            if res.status_code == 200:
                data = res.json()
                games = data.get("response", {}).get("games", [])
                if games:
                    minutes = games[0].get("playtime_forever", 0)
                    playtime_hours = round(minutes / 60.0, 1)
                    logger.info(f"Successfully retrieved playtime for app {app_id}: {playtime_hours} hours")
                    return playtime_hours
                # Not in owned games, proceed to check recently played (handles family sharing)
                break
            else:
                logger.warning(f"Steam GetOwnedGames attempt {attempt + 1} returned {res.status_code} for app {app_id}: {res.text}")
        except (httpx.ConnectTimeout, httpx.ConnectError) as ce:
            logger.warning(f"Steam GetOwnedGames attempt {attempt + 1} connection issue for app {app_id}: {type(ce).__name__}")
            if attempt == 0:
                await asyncio.sleep(0.3)
        except Exception as e:
            logger.warning(f"Steam GetOwnedGames attempt {attempt + 1} failed for app {app_id}: {type(e).__name__} {e}")
            if attempt == 0:
                await asyncio.sleep(0.3)

    # 2. Fallback for Family Sharing games: GetRecentlyPlayedGames tracks user activity even for shared games
    try:
        recent_url = "https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v1/"
        recent_params = {"key": api_key, "steamid": steam_id, "format": "json"}
        r_res = await client.get(recent_url, params=recent_params, headers=headers, timeout=6.0)
        if r_res.status_code == 200:
            r_data = r_res.json()
            for g in r_data.get("response", {}).get("games", []):
                if str(g.get("appid")) == str(app_id):
                    minutes = g.get("playtime_forever", 0)
                    playtime_hours = round(minutes / 60.0, 1)
                    logger.info(f"Retrieved family-shared/recent playtime for app {app_id}: {playtime_hours} hours")
                    return playtime_hours
    except Exception as re:
        logger.warning(f"GetRecentlyPlayedGames check failed for app {app_id}: {type(re).__name__} {re}")

    return None

@app.get("/api/steam/{app_id}/playtime")
async def get_single_playtime(app_id: str):
    if not app_id.isdigit():
        raise HTTPException(status_code=400, detail="Invalid App ID")
    config = load_config()
    playtime = await get_steam_playtime(app_id, config)
    return {"playtime": playtime}

@app.get("/api/steam/{app_id}")
async def get_steam_data(app_id: str):
    if not app_id.isdigit():
        raise HTTPException(status_code=400, detail="App ID must be a number. Use /api/steam/search?q=name to search by name.")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    client = get_client()
    
    config = load_config()
    playtime_task = None
    if (config.get("steam_api_key") or "").strip() and (config.get("steam_id64") or "").strip():
        playtime_task = get_steam_playtime(app_id, config)

    store_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Cookie": "birthtime=283993201; mature_content=1; wants_mature_content=1; lastagecheckage=1-January-1980"
    }
    cn_task = client.get(f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=schinese", headers=headers, timeout=8.0)
    en_task = client.get(f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english", headers=headers, timeout=8.0)
    cmd_task = client.get(f"https://api.steamcmd.net/v1/info/{app_id}", headers=headers, timeout=8.0)
    store_task = client.get(f"https://store.steampowered.com/app/{app_id}/?l=schinese", headers=store_headers, timeout=8.0)
    
    tasks = [cn_task, en_task, cmd_task, store_task]
    if playtime_task:
        tasks.append(playtime_task)

    results = await asyncio.gather(*tasks, return_exceptions=True)
    cn_res, en_res, cmd_res, store_res = results[:4]
    playtime = results[4] if (playtime_task and not isinstance(results[4], Exception)) else None
        
    # Parse SteamCMD early so its metadata and assets are ready as fallbacks
    cmd_common = {}
    cmd_lib_assets = {}
    clienticon_url = ""
    community_icon_url = ""
    if not isinstance(cmd_res, Exception) and getattr(cmd_res, "status_code", 0) == 200:
        try:
            cmd_data = cmd_res.json()
            cmd_common = cmd_data.get("data", {}).get(str(app_id), {}).get("common", {})
            cmd_lib_assets = cmd_common.get("library_assets_full", {})
            cicon_hash = cmd_common.get("clienticon")
            if cicon_hash:
                clienticon_url = f"https://shared.fastly.steamstatic.com/community_assets/images/apps/{app_id}/{cicon_hash}.ico"
            comm_hash = cmd_common.get("icon")
            if comm_hash:
                community_icon_url = f"https://shared.fastly.steamstatic.com/community_assets/images/apps/{app_id}/{comm_hash}.jpg"
        except Exception as e:
            logger.warning(f"Failed to parse steamcmd data: {e}")

    cn_data = {}
    if not isinstance(cn_res, Exception) and getattr(cn_res, "status_code", 0) == 200:
        try:
            cn_json = cn_res.json()
            cn_key = next(iter(cn_json), None)
            cn_data = cn_json.get(cn_key, {}) if cn_key else {}
        except Exception as e:
            logger.warning(f"Error parsing cn_res: {e}")

    en_data = {}
    if not isinstance(en_res, Exception) and getattr(en_res, "status_code", 0) == 200:
        try:
            en_json = en_res.json()
            en_key = next(iter(en_json), None)
            en_data = en_json.get(en_key, {}) if en_key else {}
        except Exception as e:
            logger.warning(f"Error parsing en_res: {e}")

    # 单语失败重试：中/英两个 appdetails 是并发请求，Steam 会限流，实际经常只成功其中一个。
    # 失败的一侧在这里单独串行重试一次，避免出现"中文名丢失"或"英文全名丢失"。
    for _lang, _slot in (("schinese", "cn"), ("english", "en")):
        if (cn_data if _slot == "cn" else en_data).get("success"):
            continue
        try:
            await asyncio.sleep(0.5)
            retry_res = await client.get(
                f"https://store.steampowered.com/api/appdetails?appids={app_id}&l={_lang}",
                headers=headers, timeout=10.0
            )
            if retry_res.status_code == 200:
                retry_json = retry_res.json()
                r_key = next(iter(retry_json), None)
                retry_data = retry_json.get(r_key, {}) if r_key else {}
                if retry_data.get("success"):
                    if _slot == "cn":
                        cn_data = retry_data
                    else:
                        en_data = retry_data
                    logger.info(f"Retried {_lang} appdetails for {app_id}: ok")
                else:
                    logger.warning(f"Retried {_lang} appdetails for {app_id}: still unsuccessful")
        except Exception as e:
            logger.warning(f"Retry {_lang} appdetails failed for {app_id}: {type(e).__name__} {e}")

    # HTML store page fallback parsing if store_res succeeded
    html_desc = ""
    html_devs = []
    html_pubs = []
    html_date = ""
    html_text = ""
    if not isinstance(store_res, Exception) and getattr(store_res, "status_code", 0) == 200:
        html_text = store_res.text
        m_desc = re.search(r'<meta\s+name=["\']Description["\']\s+content=["\']([^"\']+)["\']', html_text, re.IGNORECASE)
        if m_desc:
            html_desc = html.unescape(m_desc.group(1).strip())
        html_devs = [html.unescape(d.strip()) for d in re.findall(r'id=["\']developers_list["\']>.*?<a[^>]*>([^<]+)</a>', html_text, re.DOTALL)]
        html_pubs = [html.unescape(p.strip()) for p in re.findall(r'class=["\']dev_row["\']>.*?<b>(?:发行商|Publisher):</b>.*?<a[^>]*>([^<]+)</a>', html_text, re.DOTALL)]
        m_date = re.search(r'class=["\']date["\']>([^<]+)</div>', html_text)
        if m_date:
            html_date = html.unescape(m_date.group(1).strip())

    if not cn_data.get("success") and not en_data.get("success"):
        game_name = cmd_common.get("name")
        if not game_name and html_text:
            title_m = re.search(r'class=["\']apphub_AppName["\']>([^<]+)</div>', html_text)
            if title_m:
                game_name = html.unescape(title_m.group(1).strip())
        if game_name:
            logger.warning(f"Using SteamCMD & HTML fallback for {app_id} as store API failed")
            cn_app = en_app = {
                "name": game_name,
                "short_description": html_desc,
                "developers": html_devs,
                "publishers": html_pubs,
                "genres": []
            }
        else:
            raise HTTPException(status_code=502, detail="Steam 商店详情接口暂时无法访问，请检查网络或稍后重试")
    else:
        cn_app = cn_data.get("data", {}) if cn_data.get("success") else {}
        en_app = en_data.get("data", {}) if en_data.get("success") else {}

    # Bidirectional fallback
    if not cn_app and en_app:
        cn_app = en_app
    if not en_app and cn_app:
        en_app = cn_app

    title_cn = cn_app.get("name", "")
    title_en = en_app.get("name", "")
    if not title_en and not title_cn:
        title_cn = title_en = cmd_common.get("name", f"App {app_id}")
    elif not title_en:
        title_en = cmd_common.get("name") or title_cn
    elif not title_cn:
        title_cn = title_en
    
    cjk_pattern = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
    # "本地化名称"判定：只要官方名称不是英文名就算（简体/繁体中文、日文汉字与假名、韩文等一律算）。
    # 做法与字符集/语言无关：比较"简中接口名称"与"英文接口名称"是否不同（忽略大小写与首尾空格）。
    # 两者相同 ⇒ 说明该游戏没有本地化名称（官方名称本身就是英文名），
    # 此时不应把同一个名字同时写进「游戏名称」和「全名」两列。
    has_localized_name = title_cn.strip().lower() != title_en.strip().lower()
    # 官方简中名自身可能混着英文原名（如 "空战奇兵8 希孚之翼 (ACE COMBAT 8: WINGS OF THEVE)"、"Valheim: 英灵神殿"）：
    # 只在"一眼可辨"的两种形态下剥离英文部分作为「游戏名称」；「全名」始终取英文接口名称，不从解析结果推断。
    display_title = strip_embedded_english(title_cn) if has_localized_name else title_en
    
    description = cn_app.get("short_description", "")
    if not description or (len(description) < 10 and not cjk_pattern.search(description)):
        description = en_app.get("short_description", "")
    if not description:
        description = html_desc
        
    if description:
        description = html.unescape(description)
        description = re.sub(r'<br\s*/?>', '\n', description, flags=re.IGNORECASE)
        description = re.sub(r'<[^>]+>', '', description).strip()
        
    # Translate genres to Chinese
    raw_genres_en = [g.get("description", "") for g in en_app.get("genres", []) if isinstance(g, dict)]
    raw_genres_cn = [g.get("description", "") for g in cn_app.get("genres", []) if isinstance(g, dict)]
    genres = []
    for g in raw_genres_en:
        genres.append(GENRE_TRANSLATIONS.get(g, g))
    if not genres and raw_genres_cn:
        genres = raw_genres_cn
    
    # Extract tags (Steam商店页简介下方的用户标签，双通道提取)
    tags = []
    if html_text:
        # 1. 尝试从 script 中的 InitAppTagModal 提取完整标签列表
        # InitAppTagModal( 1086940, [{"tagid":122,"name":"\u89d2\u8272\u626e\u6f14", ...
        m_modal = re.search(r'InitAppTagModal\s*\(\s*\d+\s*,\s*(\[.*?\])\s*,', html_text, re.DOTALL)
        if m_modal:
            try:
                modal_json = json.loads(m_modal.group(1))
                for item in modal_json:
                    raw_name = item.get("name", "")
                    cleaned = html.unescape(decode_unicode_escapes(raw_name).strip())
                    if cleaned and cleaned != "+" and cleaned not in tags:
                        tags.append(cleaned)
            except Exception as je:
                logger.warning(f"Error parsing InitAppTagModal JSON: {je}")

        # 正则扫描兜底
        modal_tags = re.findall(r'\{\s*["\']tagid["\']\s*:\s*\d+\s*,\s*["\']name["\']\s*:\s*["\']([^"\']+)["\']', html_text)
        for t in modal_tags:
            cleaned = html.unescape(decode_unicode_escapes(t).strip())
            if cleaned and cleaned != "+" and cleaned not in tags:
                tags.append(cleaned)
                
        # 2. 尝试从 class="app_tag" 提取
        raw_tags = re.findall(r'class=["\']app_tag["\'][^>]*>([^<]+)', html_text)
        for t in raw_tags:
            cleaned = html.unescape(decode_unicode_escapes(t).strip())
            if cleaned and cleaned != "+" and cleaned not in tags:
                tags.append(cleaned)
                
    # 3. 兜底：如果 HTML 标签为空，使用已解析的类型 genres 兜底
    if not tags and genres:
        tags = [decode_unicode_escapes(g) for g in genres if g and g not in tags]
    
    release_date_str = en_app.get("release_date", {}).get("date", "")
    release_date_iso = parse_steam_date(release_date_str)
    
    if not release_date_iso and cn_app.get("release_date", {}).get("date"):
        release_date_iso = parse_steam_date(cn_app.get("release_date", {}).get("date", ""))
        if not release_date_str:
            release_date_str = cn_app.get("release_date", {}).get("date", "")

    if not release_date_iso and html_date:
        release_date_iso = parse_steam_date(html_date)
        if not release_date_str:
            release_date_str = html_date

    # 1. 从 SteamCMD 解析高清资产（cmd_common 与 cmd_lib_assets 已在前面解析）

    def extract_cmd_asset(asset_name: str, prefer_2x: bool = True) -> str:
        """从 steamcmd library_assets_full 提取官方直链资产"""
        item = cmd_lib_assets.get(asset_name, {})
        img_dict = item.get("image2x", {}) if prefer_2x and "image2x" in item else item.get("image", {})
        if not img_dict and "image" in item:
            img_dict = item.get("image", {})
        if isinstance(img_dict, dict):
            rel_path = img_dict.get("english") or next(iter(img_dict.values()), "")
            if rel_path:
                return f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{app_id}/{rel_path}"
        return ""

    cmd_logo = extract_cmd_asset("library_logo", prefer_2x=True)
    cmd_hero = extract_cmd_asset("library_hero", prefer_2x=True)
    cmd_grid = extract_cmd_asset("library_capsule", prefer_2x=True)
    
    cmd_header_raw = cmd_common.get("header_image", {})
    cmd_header = ""
    if isinstance(cmd_header_raw, dict):
        h_rel = cmd_header_raw.get("english") or next(iter(cmd_header_raw.values()), "")
        if h_rel:
            cmd_header = f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{app_id}/{h_rel}"
    elif isinstance(cmd_header_raw, str) and cmd_header_raw:
        cmd_header = f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{app_id}/{cmd_header_raw}"

    # Fallback for community icon
    if not community_icon_url:
        community_icon_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/capsule_sm_120.jpg"

    # If clienticon couldn't be retrieved via SteamCMD API, fallback to community icon
    if not clienticon_url:
        clienticon_url = community_icon_url

    # Verify official logo (高清透明Logo)
    official_logo_url = cmd_logo
    if not official_logo_url:
        for logo_name in ["logo_2x.png", "logo.png"]:
            logo_candidate = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/{logo_name}"
            try:
                l_res = await client.head(logo_candidate, timeout=3.5)
                if l_res.status_code == 200:
                    official_logo_url = logo_candidate
                    break
            except Exception:
                pass

    header_image = en_app.get("header_image") or cn_app.get("header_image") or cmd_header or f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"
    
    # Verify library_hero availability, fallback to official background_raw (1920x1080)
    hero_candidate = cmd_hero or f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/library_hero.jpg"
    bg_candidate = en_app.get("background_raw") or cn_app.get("background_raw") or en_app.get("background") or ""
    screenshots = en_app.get("screenshots", [])
    screenshot_candidate = screenshots[0].get("path_full", "") if screenshots else ""

    library_hero = ""
    try:
        head_res = await client.head(hero_candidate, timeout=3.5)
        if head_res.status_code == 200:
            library_hero = hero_candidate
    except Exception:
        pass
        
    if not library_hero:
        # Fallback to official 1920x1080 store background or HD screenshot
        library_hero = bg_candidate or screenshot_candidate or header_image

    library_grid = cmd_grid or f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/library_600x900.jpg"

    steam_images = {
        "header": header_image,
        "library_hero": library_hero,
        "library_grid": library_grid,
        "official_logo": official_logo_url,
        "clienticon": clienticon_url,
        "icon": community_icon_url
    }

    return {
        "app_id": int(app_id) if app_id.isdigit() else app_id,
        "title": display_title,
        # 仅当"游戏名称"确实取到非英文的本地化名称时，才回填英文全名(别名)：
        # 官方只有英文名时，不再把同一个英文名重复写进两列
        "title_en": title_en if has_localized_name else "",
        # 兼容字段名：语义为"是否取到非英文的本地化名称"
        "has_chinese_name": has_localized_name,
        "description": description,
        "developers": en_app.get("developers", []) or html_devs,
        "publishers": en_app.get("publishers", []) or html_pubs,
        "genres": genres,
        "genres_cn": raw_genres_cn,
        "tags": tags,
        "release_date": release_date_str,
        "release_date_iso": release_date_iso,
        "playtime": playtime,
        "header_image": header_image,
        "steam_images": steam_images,
        "steam_url": f"https://store.steampowered.com/app/{app_id}"
    }

@app.get("/api/steamgriddb/search/{app_id}")
async def search_steamgriddb(app_id: str):
    config = load_config()
    key = config.get("steamgriddb_key")
    if not key:
        raise HTTPException(status_code=400, detail="SteamGridDB key not configured")
        
    headers = {"Authorization": f"Bearer {key}"}
    client = get_client()
    try:
        res = await client.get(f"https://www.steamgriddb.com/api/v2/games/steam/{app_id}", headers=headers)
        try:
            data = res.json()
        except Exception:
            data = {"success": False, "msg": res.text}
        return JSONResponse(content=data, status_code=res.status_code)
    except Exception as e:
        logger.error(f"SteamGridDB search error: {e}")
        return JSONResponse(content={"success": False, "msg": str(e)}, status_code=502)

@app.get("/api/steamgriddb/{image_type}/{game_id}")
async def get_steamgriddb_images(image_type: str, game_id: str):
    if image_type not in ["grids", "heroes", "icons", "logos"]:
        raise HTTPException(status_code=400, detail="Invalid image type")
        
    config = load_config()
    key = config.get("steamgriddb_key")
    if not key:
        raise HTTPException(status_code=400, detail="SteamGridDB key not configured")
        
    url = f"https://www.steamgriddb.com/api/v2/{image_type}/game/{game_id}"
    params = {}
    if image_type == "heroes":
        params["dimensions"] = "1920x620,3840x1240"
        
    headers = {"Authorization": f"Bearer {key}"}
    client = get_client()
    try:
        if image_type == "grids":
            # SteamGridDB 默认返回按热度排序的前50张图，其中绝大多数是竖版(600x900)，导致横版(92:43/460x215/920x430)极易被淹没。
            # 为了满足 Notion 画廊横版封面的高频需求，并发分别获取高清横版(460x215,920x430)与竖版(600x900)，并将横版排在最前面！
            h_task = client.get(url, headers=headers, params={"dimensions": "460x215,920x430"}, timeout=8.0)
            v_task = client.get(url, headers=headers, params={"dimensions": "600x900"}, timeout=8.0)
            h_res, v_res = await asyncio.gather(h_task, v_task, return_exceptions=True)
            
            h_items = []
            if not isinstance(h_res, Exception) and getattr(h_res, "status_code", 0) == 200:
                try:
                    h_items = h_res.json().get("data", [])
                except Exception:
                    pass
                    
            v_items = []
            if not isinstance(v_res, Exception) and getattr(v_res, "status_code", 0) == 200:
                try:
                    v_items = v_res.json().get("data", [])
                except Exception:
                    pass
            
            # 去重合并：横版在前，竖版在后
            seen_ids = set()
            combined = []
            for item in h_items + v_items:
                iid = item.get("id") or item.get("url")
                if iid and iid not in seen_ids:
                    seen_ids.add(iid)
                    combined.append(item)
            
            # 兜底：如果特定尺寸都没有返回（极冷门游戏），尝试不带参数全量查询一次
            if not combined:
                fallback_res = await client.get(url, headers=headers, timeout=8.0)
                if fallback_res.status_code == 200:
                    try:
                        combined = fallback_res.json().get("data", [])
                    except Exception:
                        pass
                        
            return JSONResponse(content={"success": True, "data": combined}, status_code=200)

        res = await client.get(url, headers=headers, params=params)
        try:
            data = res.json()
        except Exception:
            data = {"success": False, "msg": res.text}
        return JSONResponse(content=data, status_code=res.status_code)
    except Exception as e:
        logger.error(f"SteamGridDB fetch error: {e}")
        return JSONResponse(content={"success": False, "msg": str(e)}, status_code=502)

@app.get("/api/notion/databases")
async def list_notion_databases():
    config = load_config()
    token = config.get("notion_token")
    if not token:
        raise HTTPException(status_code=400, detail="Notion token not configured")
        
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    client = get_client()
    try:
        res = await client.post(
            "https://api.notion.com/v1/search", 
            headers=headers,
            json={"filter": {"property": "object", "value": "database"}},
            timeout=10.0
        )
        if res.status_code != 200:
            raise HTTPException(status_code=res.status_code, detail=res.text)
            
        data = res.json()
        dbs = []
        for db in data.get("results", []):
            properties = {}
            for k, v in db.get("properties", {}).items():
                ptype = v.get("type")
                if ptype not in ["formula", "rollup", "created_time", "last_edited_time", "created_by", "last_edited_by"]:
                    properties[k] = {"type": ptype, "id": v.get("id")}
                    
            title_prop = db.get("title", [])
            title = title_prop[0].get("plain_text", "Untitled") if title_prop else "Untitled"
            
            dbs.append({
                "id": db.get("id"),
                "title": title,
                "properties": properties
            })
        return dbs
    except (httpx.ConnectTimeout, httpx.ConnectError) as ce:
        logger.warning(f"Notion databases connection issue: {type(ce).__name__}")
        await auto_heal_client()
        raise HTTPException(
            status_code=502,
            detail="无法连接到 Notion 服务器。国内直连 Notion 可能会受网络限制，请在设置中配置代理（例如 http://127.0.0.1:7890）或开启加速工具。"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching Notion databases: {e}")
        raise HTTPException(status_code=500, detail=str(e))

NOTION_FIELD_ALIASES = {
    "tags": ["tags", "tag", "标签", "游戏标签", "steam标签", "steam tags", "user tags"],
    "genre": ["genre", "genres", "类型", "分类", "游戏类型", "类别"],
    "title": ["title", "name", "游戏名称", "名称", "游戏名", "名字", "game"],
    "title_en": ["title_en", "english name", "english title", "全名", "英文全名", "英文名", "原名"],
    "cover_grid": ["cover", "grid", "封面", "海报", "封面图", "grid封面", "boxart"],
    "release_date": ["release_date", "release date", "date", "发行日期", "发售日期", "日期", "上线时间"],
    "playtime": ["playtime", "play time", "hours", "游玩时长", "时长", "游戏时长", "游玩时间"],
    "developer": ["developer", "developers", "dev", "开发商", "开发团队", "制作组", "开发"],
    "publisher": ["publisher", "publishers", "pub", "发行商", "发行"],
    "description": ["description", "desc", "简介", "描述", "游戏简介", "详情"],
    "steam_url": ["steam_url", "steam url", "url", "link", "steam链接", "链接", "steam"]
}

# 说明：上面的 NOTION_FIELD_ALIASES 后端已不再使用——字段映射严格按用户选择的属性名，
# 该表保留仅为将来需要恢复"未映射时自动推荐"功能时可用。

async def ensure_field_mapping_healthy(mapping: dict, db_id: str, token: str) -> dict:
    """仅做"映射体检"：把用户已选定、但当前数据库里不存在的属性名告警出来。

    设计原则：字段映射严格以用户选择的 Notion 属性名为准，与该属性叫什么名字无关
    —— Steam 抓到的 tags 写进用户指定的某一列，Steam 抓到的类型写进用户指定的另一列。
    **本函数不补齐、不改写、不启用任何字段**：
      * 未映射（属性名为空）的字段一律不写；
      * 已选定的名字即使当前库里不存在，也只告警保留（历史版本会按别名重新猜列，已移除）。
    """
    if not db_id or not token or not mapping:
        return mapping

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28"
    }
    client = get_client()
    try:
        r = await client.get(f"https://api.notion.com/v1/databases/{db_id}", headers=headers, timeout=6.0)
        if r.status_code != 200:
            logger.warning(f"Field-mapping check skipped: Notion returned {r.status_code}")
            return mapping

        db_props = r.json().get("properties", {})
        for k, conf in mapping.items():
            name = (conf or {}).get("name") or ""
            if not name:
                continue
            if name not in db_props:
                logger.warning(f"字段映射 '{k}' -> '{name}' 在当前 Notion 数据库中不存在（不会写入，也不会被自动替换），请在设置中确认")
    except Exception as e:
        logger.warning(f"Failed to check field mapping against Notion: {e}")

    return mapping

@app.post("/api/notion/create")
async def create_notion_page(request: Request):
    config = load_config()
    token = config.get("notion_token")
    db_id = config.get("database_id")
    if not token or not db_id:
        raise HTTPException(status_code=400, detail="Notion token or database ID not configured")
        
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
        
    game = data.get("game", {})
    images = data.get("images", {})
    steam_images = game.get("steam_images", {})
    
    # 桌面图标 = clienticon (优先) / official_logo / icon, 库横幅 = pagecover (hero), Steam封面 = 封面 (grid)
    # sanitize_image_url：去掉链接末尾的 ?t=xxxxxx 缓存参数（带该参数在 Notion 中偶发不显示）
    grid_img = sanitize_image_url(images.get("grid") or steam_images.get("header") or game.get("header_image") or steam_images.get("library_grid") or "")
    hero_img = sanitize_image_url(images.get("hero") or steam_images.get("library_hero") or "")
    icon_img = sanitize_image_url(images.get("icon") or steam_images.get("clienticon") or steam_images.get("official_logo") or steam_images.get("icon") or "")
    
    mapping = config.get("field_mapping", {})
    mapping = await ensure_field_mapping_healthy(mapping, db_id, token)
    
    properties = {}
    
    for src_key, field_conf in mapping.items():
        if not field_conf.get("enabled", True):
            continue
        name = field_conf.get("name")
        ptype = field_conf.get("type")
        if not name or not ptype:
            continue
            
        value = None
        if src_key == "title": value = game.get("title")
        elif src_key == "title_en": value = game.get("title_en")
        elif src_key == "cover_grid": value = grid_img
        elif src_key == "cover_hero": value = hero_img
        elif src_key == "genre": value = game.get("genres", [])
        elif src_key == "tags": value = game.get("tags", [])
        elif src_key == "release_date": value = game.get("release_date_iso") or game.get("release_date")
        elif src_key == "playtime": value = game.get("playtime")
        elif src_key == "developer": value = game.get("developers", [])
        elif src_key == "publisher": value = game.get("publishers", [])
        elif src_key == "description": value = game.get("description")
        elif src_key == "steam_url": value = game.get("steam_url")
        
        if value is None or value == "" or value == []:
            continue
        
        # For rich_text/title/select: join arrays into comma-separated string
        if isinstance(value, list) and ptype in ("rich_text", "title", "select"):
            value = ", ".join(value)
            
        prop_val = None
        if ptype == "title":
            prop_val = {"title": [{"text": {"content": str(value)[:2000]}}]}
        elif ptype == "rich_text":
            text_str = f"{value} 小时" if src_key == "playtime" and isinstance(value, (int, float)) else str(value)
            prop_val = {"rich_text": [{"text": {"content": text_str[:2000]}}]}
        elif ptype == "multi_select":
            items = value if isinstance(value, list) else [value]
            # Notion 的 multi_select 不允许选项名含逗号（用空格替换），也不允许出现重复选项名（会直接 400）
            cleaned = []
            for v in items:
                if not v:
                    continue
                n = str(v).replace(",", "").strip()[:100]
                if n and n not in cleaned:
                    cleaned.append(n)
            prop_val = {"multi_select": [{"name": n} for n in cleaned]}
        elif ptype == "select":
            v = value[0] if isinstance(value, list) and value else value
            if v:
                prop_val = {"select": {"name": str(v).replace(",", "").strip()[:100]}}
        elif ptype == "date":
            try:
                if re.match(r'^\d{4}-\d{2}-\d{2}$', str(value)):
                    prop_val = {"date": {"start": str(value)}}
            except Exception:
                pass
        elif ptype == "url":
            prop_val = {"url": str(value)[:2000]}
        elif ptype == "files":
            prop_val = {"files": [{"type": "external", "name": "cover", "external": {"url": str(value)[:2000]}}]}
        elif ptype == "number":
            try:
                prop_val = {"number": float(value)}
            except Exception:
                pass
        elif ptype == "checkbox":
            prop_val = {"checkbox": bool(value)}
            
        if prop_val:
            properties[name] = prop_val

    logger.info(f"Notion Page Create - Properties mapped and sent: {list(properties.keys())}")
    if "tags" in game and game["tags"]:
        tag_prop_name = mapping.get("tags", {}).get("name")
        if tag_prop_name and tag_prop_name in properties:
            logger.info(f"Pushed tags to Notion property '{tag_prop_name}': {game.get('tags', [])[:5]}")
        else:
            logger.warning(f"Tags were not sent: mapping.tags.name='{tag_prop_name}', enabled={mapping.get('tags', {}).get('enabled')}")

    page_data = {
        "parent": {"database_id": db_id},
        "properties": properties
    }
    
    if config.get("use_hero_as_cover") and hero_img:
        page_data["cover"] = {"type": "external", "external": {"url": str(hero_img)[:2000]}}
        
    if config.get("use_icon_as_page_icon") and icon_img:
        page_data["icon"] = {"type": "external", "external": {"url": str(icon_img)[:2000]}}
        
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    client = get_client()
    try:
        res = await client.post("https://api.notion.com/v1/pages", headers=headers, json=page_data, timeout=12.0)
        if res.status_code not in (200, 201):
            return JSONResponse(status_code=400, content={"status": "error", "message": res.text})
        page_res = res.json()
        return {"status": "success", "url": page_res.get("url")}
    except (httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout) as ce:
        logger.warning(f"Notion create page connection issue: {type(ce).__name__}")
        await auto_heal_client()
        # 超时后无法确定页面是否已建立：主动核对一次，避免用户重试时产生重复页面
        reconciled = None
        try:
            reconciled = await find_existing_notion_page(
                token, db_id, mapping,
                game.get("title", ""), game.get("title_en", ""), game.get("steam_url", "")
            )
        except Exception as re_err:
            logger.warning(f"Create-page timeout reconciliation failed: {re_err}")
        if reconciled:
            logger.info(f"Page exists despite timeout, treated as created: {reconciled.get('url')}")
            return {"status": "success", "url": reconciled.get("url"), "reconciled": True}
        return JSONResponse(
            status_code=502,
            content={"status": "error", "message": "连接 Notion 服务器超时或失败。国内直连 Notion 可能会受网络限制，请在设置中配置代理（例如 http://127.0.0.1:7890）或开启加速工具。"}
        )
    except Exception as e:
        logger.error(f"Error creating notion page: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

def parse_notion_property_value(prop: dict) -> Any:
    """Extract clean Python value from raw Notion property object."""
    if not isinstance(prop, dict):
        return None
    ptype = prop.get("type")
    if ptype == "title":
        return "".join([t.get("plain_text", "") for t in prop.get("title", [])])
    elif ptype == "rich_text":
        return "".join([t.get("plain_text", "") for t in prop.get("rich_text", [])])
    elif ptype == "number":
        return prop.get("number")
    elif ptype == "select":
        s = prop.get("select")
        return s.get("name") if isinstance(s, dict) else None
    elif ptype == "multi_select":
        return [item.get("name") for item in prop.get("multi_select", []) if isinstance(item, dict) and item.get("name")]
    elif ptype == "date":
        d = prop.get("date")
        return d.get("start") if isinstance(d, dict) else None
    elif ptype == "url":
        return prop.get("url")
    elif ptype == "files":
        files = prop.get("files", [])
        if files:
            f = files[0]
            if f.get("type") == "external":
                return f.get("external", {}).get("url")
            elif f.get("type") == "file":
                return f.get("file", {}).get("url")
        return None
    elif ptype == "checkbox":
        return prop.get("checkbox")
    return None

def extract_notion_page_image(img_obj: dict) -> str:
    if not isinstance(img_obj, dict):
        return ""
    itype = img_obj.get("type")
    if itype == "external":
        return img_obj.get("external", {}).get("url", "")
    elif itype == "file":
        return img_obj.get("file", {}).get("url", "")
    return ""

IMAGE_URL_EXT_RE = re.compile(r'\.(?:jpg|jpeg|png|webp|gif|ico|bmp|svg|avif)$', re.IGNORECASE)

def sanitize_image_url(url: str) -> str:
    """把图片链接清理成"干净的、以图片扩展名结尾"的链接后再写入 Notion。

    Steam 的商店接口会在图片链接后附加缓存参数（如 `header.jpg?t=1777363040`），
    实测带该参数时 Notion 偶发不显示图片；链接末尾也可能出现 `#` 锚点。

    规则：
      * 去掉 `?` 之后的一切（查询串）与 `#` 之后的一切（锚点）；
      * **仅当清理后的结果仍以常见图片扩展名结尾时才采用该结果**，否则原样返回（不误伤其它 URL）；
      * 清理生效时记 INFO 日志、遇到"不认识的结尾"记 WARNING，便于排查。
    """
    if not url or not isinstance(url, str):
        return url or ""
    url = url.strip()
    base = url.split("?", 1)[0].split("#", 1)[0].strip()
    if base != url and IMAGE_URL_EXT_RE.search(base):
        logger.info(f"图片链接已清理后缀: {url[:160]} -> {base[:160]}")
        return base
    if url and not IMAGE_URL_EXT_RE.search(url):
        logger.warning(f"图片链接不以常见图片扩展名结尾，原样保留（未改写）: {url[:160]}")
    return url

def _notion_match_condition(prop_name: str, prop_type: Optional[str], value: str, url_variants: bool = False) -> Optional[dict]:
    """按 Notion 属性的真实类型构造等值匹配条件。
    原先写死 title/url 类型：一旦该属性是 rich_text/select，Notion 会返回 400 并被静默吞掉，导致查重失效。"""
    if not prop_name or not value:
        return None
    ptype = (prop_type or "").strip() or ("url" if url_variants else "title")
    values = [value.rstrip("/"), value.rstrip("/") + "/"] if url_variants else [value]
    conds = []
    for v in values:
        if ptype == "rich_text":
            conds.append({"property": prop_name, "rich_text": {"equals": v}})
        elif ptype == "select":
            conds.append({"property": prop_name, "select": {"equals": v}})
        elif ptype == "url":
            conds.append({"property": prop_name, "url": {"equals": v}})
        else:
            conds.append({"property": prop_name, "title": {"equals": v}})
    return {"or": conds} if len(conds) > 1 else conds[0]

async def find_existing_notion_page(token: str, db_id: str, mapping: dict,
                                    title: str = "", title_en: str = "", steam_url: str = "") -> Optional[dict]:
    """在 Notion 数据库中查找已存在的游戏页面：先按 Steam 链接精确匹配，再按名称匹配，返回原始页面对象或 None。

    供 /api/notion/search（前端查重）与创建页面超时后的核对逻辑复用。
    只要映射里配置了属性名即参与匹配（不因该字段"不写入 Notion"而跳过查重）。
    """
    if not token or not db_id:
        return None

    title = (title or "").strip()
    title_en = (title_en or "").strip()
    steam_url = (steam_url or "").strip()

    url_conf = mapping.get("steam_url") or {}
    title_conf = mapping.get("title") or {}
    title_en_conf = mapping.get("title_en") or {}

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    client = get_client()

    async def _query(filter_query: dict) -> Optional[dict]:
        try:
            res = await client.post(
                f"https://api.notion.com/v1/databases/{db_id}/query",
                headers=headers,
                json={"filter": filter_query, "page_size": 1},
                timeout=8.0
            )
            if res.status_code == 200:
                results = res.json().get("results", [])
                if results:
                    return results[0]
            else:
                logger.warning(f"Notion dedupe query returned {res.status_code}: {res.text[:300]}")
        except Exception as e:
            logger.warning(f"Notion dedupe query failed: {type(e).__name__} {e}")
        return None

    # Priority 1: Exact match by steam_url
    url_cond = _notion_match_condition(url_conf.get("name") or "", url_conf.get("type"), steam_url, url_variants=True)
    if url_cond:
        matched = await _query(url_cond)
        if matched:
            logger.info(f"Notion dedupe matched by steam_url ('{url_conf.get('name')}'): {matched.get('url')}")
            return matched

    # 中/英文名两个取值都参与名称匹配（去重后），按目标属性的真实类型构造条件
    name_values = []
    for v in (title, title_en):
        if v and v not in name_values:
            name_values.append(v)

    async def _match_by_property(prop_conf: dict, label: str) -> Optional[dict]:
        prop_name = (prop_conf.get("name") or "").strip()
        conds = [c for c in (
            _notion_match_condition(prop_name, prop_conf.get("type"), v) for v in name_values
        ) if c]
        if not conds:
            return None
        hit = await _query({"or": conds} if len(conds) > 1 else conds[0])
        if hit:
            logger.info(f"Notion dedupe matched by {label} ('{prop_name}'): {hit.get('url')}")
        return hit

    # Priority 2: 按「游戏名称」列匹配
    matched = await _match_by_property(title_conf, "游戏名称")
    if matched:
        return matched

    # Priority 3: 按「英文全名」列匹配（两列配置不同时才查）
    # 英文名唯一性高，且不受中文名被改写/拆分的影响，可以命中"旧条目仍写着旧中文名"的情况
    title_en_prop = (title_en_conf.get("name") or "").strip()
    if title_en_prop and title_en_prop != (title_conf.get("name") or "").strip():
        matched = await _match_by_property(title_en_conf, "英文全名")
        if matched:
            return matched

    return None

@app.post("/api/notion/search")
async def search_existing_notion_game(request: Request):
    """Search if game already exists in Notion DB by steam_url (exact) or title."""
    config = load_config()
    token = config.get("notion_token")
    db_id = config.get("database_id")
    if not token or not db_id:
        return {"found": False}

    try:
        body = await request.json()
    except Exception:
        body = {}

    mapping = config.get("field_mapping", {})
    matched_page = await find_existing_notion_page(
        token, db_id, mapping,
        (body.get("title") or "").strip(),
        (body.get("title_en") or "").strip(),
        (body.get("steam_url") or "").strip()
    )

    if not matched_page:
        return {"found": False}

    raw_props = matched_page.get("properties", {})
    simplified_props = {}
    
    prop_to_key = {}
    for k, v in mapping.items():
        if isinstance(v, dict) and v.get("name"):
            prop_to_key[v["name"]] = k

    for prop_name, prop_data in raw_props.items():
        val = parse_notion_property_value(prop_data)
        if prop_name in prop_to_key:
            src_k = prop_to_key[prop_name]
            simplified_props[src_k] = val
        simplified_props[prop_name] = val

    cover_url = extract_notion_page_image(matched_page.get("cover"))
    icon_url = extract_notion_page_image(matched_page.get("icon"))

    return {
        "found": True,
        "page_id": matched_page.get("id"),
        "page_url": matched_page.get("url"),
        "properties": simplified_props,
        "cover_url": cover_url,
        "icon_url": icon_url
    }

@app.patch("/api/notion/update")
async def update_notion_page(request: Request):
    """Update an existing Notion page (all fields or images only)."""
    config = load_config()
    token = config.get("notion_token")
    if not token:
        raise HTTPException(status_code=400, detail="Notion token not configured")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    page_id = data.get("page_id")
    if not page_id:
        raise HTTPException(status_code=400, detail="page_id is required for update")

    only_images = bool(data.get("only_images", False))
    game = data.get("game", {})
    images = data.get("images", {})
    steam_images = game.get("steam_images", {})

    def resolve_selected_image(key: str, *fallbacks: str) -> str:
        """前端始终会提交 grid/hero/icon 三个键：键存在且为空串 = 用户主动取消选中，此时不得用官方图回填。
        仅当键未提交（旧版前端/第三方调用）时才回退到 Steam 官方图片。"""
        if key in images:
            return (images.get(key) or "").strip()
        for f in fallbacks:
            if f:
                return f
        return ""

    grid_img = sanitize_image_url(resolve_selected_image("grid", steam_images.get("header") or "", game.get("header_image") or "", steam_images.get("library_grid") or ""))
    hero_img = sanitize_image_url(resolve_selected_image("hero", steam_images.get("library_hero") or ""))
    icon_img = sanitize_image_url(resolve_selected_image("icon", steam_images.get("clienticon") or "", steam_images.get("official_logo") or "", steam_images.get("icon") or ""))

    db_id = config.get("database_id")
    mapping = config.get("field_mapping", {})
    if db_id and not only_images:
        mapping = await ensure_field_mapping_healthy(mapping, db_id, token)
    properties = {}

    if not only_images:
        for src_key, field_conf in mapping.items():
            if not field_conf.get("enabled", True):
                continue
            name = field_conf.get("name")
            ptype = field_conf.get("type")
            if not name or not ptype:
                continue

            value = None
            if src_key == "title": value = game.get("title")
            elif src_key == "title_en": value = game.get("title_en")
            elif src_key == "cover_grid": value = grid_img
            elif src_key == "cover_hero": value = hero_img
            elif src_key == "genre": value = game.get("genres", [])
            elif src_key == "tags": value = game.get("tags", [])
            elif src_key == "release_date": value = game.get("release_date_iso") or game.get("release_date")
            elif src_key == "playtime": value = game.get("playtime")
            elif src_key == "developer": value = game.get("developers", [])
            elif src_key == "publisher": value = game.get("publishers", [])
            elif src_key == "description": value = game.get("description")
            elif src_key == "steam_url": value = game.get("steam_url")

            if value is None or value == "" or value == []:
                continue

            if isinstance(value, list) and ptype in ("rich_text", "title", "select"):
                value = ", ".join(value)

            prop_val = None
            if ptype == "title":
                prop_val = {"title": [{"text": {"content": str(value)[:2000]}}]}
            elif ptype == "rich_text":
                text_str = f"{value} 小时" if src_key == "playtime" and isinstance(value, (int, float)) else str(value)
                prop_val = {"rich_text": [{"text": {"content": text_str[:2000]}}]}
            elif ptype == "multi_select":
                items = value if isinstance(value, list) else [value]
                # Notion 的 multi_select 不允许选项名含逗号（用空格替换），也不允许出现重复选项名（会直接 400）
                cleaned = []
                for v in items:
                    if not v:
                        continue
                    n = str(v).replace(",", "").strip()[:100]
                    if n and n not in cleaned:
                        cleaned.append(n)
                prop_val = {"multi_select": [{"name": n} for n in cleaned]}
            elif ptype == "select":
                v = value[0] if isinstance(value, list) and value else value
                if v:
                    prop_val = {"select": {"name": str(v).replace(",", "").strip()[:100]}}
            elif ptype == "date":
                try:
                    if re.match(r'^\d{4}-\d{2}-\d{2}$', str(value)):
                        prop_val = {"date": {"start": str(value)}}
                except Exception:
                    pass
            elif ptype == "url":
                prop_val = {"url": str(value)[:2000]}
            elif ptype == "files":
                prop_val = {"files": [{"type": "external", "name": "cover", "external": {"url": str(value)[:2000]}}]}
            elif ptype == "number":
                try:
                    prop_val = {"number": float(value)}
                except Exception:
                    pass
            elif ptype == "checkbox":
                prop_val = {"checkbox": bool(value)}

            if prop_val:
                properties[name] = prop_val

        logger.info(f"Notion Page Update - Properties mapped and sent: {list(properties.keys())}")
        if "tags" in game and game["tags"]:
            tag_prop_name = mapping.get("tags", {}).get("name")
            if tag_prop_name and tag_prop_name in properties:
                logger.info(f"Updated tags in Notion property '{tag_prop_name}': {game.get('tags', [])[:5]}")
            else:
                logger.warning(f"Tags were not updated: mapping.tags.name='{tag_prop_name}', enabled={mapping.get('tags', {}).get('enabled')}")
    else:
        for src_key, field_conf in mapping.items():
            if not field_conf.get("enabled", True):
                continue
            name = field_conf.get("name")
            ptype = field_conf.get("type")
            if src_key == "cover_grid" and grid_img and name and ptype == "files":
                properties[name] = {"files": [{"type": "external", "name": "cover", "external": {"url": str(grid_img)[:2000]}}]}

    page_patch = {}
    if properties:
        page_patch["properties"] = properties

    if config.get("use_hero_as_cover") and hero_img:
        page_patch["cover"] = {"type": "external", "external": {"url": str(hero_img)[:2000]}}

    if config.get("use_icon_as_page_icon") and icon_img:
        page_patch["icon"] = {"type": "external", "external": {"url": str(icon_img)[:2000]}}

    if not page_patch:
        return JSONResponse(status_code=400, content={"status": "error", "message": "没有需要更新的字段或图片"})

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }

    client = get_client()
    try:
        res = await client.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=headers, json=page_patch, timeout=12.0)
        if res.status_code not in (200, 201):
            return JSONResponse(status_code=400, content={"status": "error", "message": res.text})
        page_res = res.json()
        return {"status": "success", "url": page_res.get("url")}
    except (httpx.ConnectTimeout, httpx.ConnectError) as ce:
        logger.warning(f"Notion update page connection issue: {type(ce).__name__}")
        await auto_heal_client()
        return JSONResponse(
            status_code=502,
            content={"status": "error", "message": "连接 Notion 服务器超时或失败，请检查网络代理设置。"}
        )
    except Exception as e:
        logger.error(f"Error updating notion page: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
        
def open_browser():
    import time
    time.sleep(1.2)
    webbrowser.open("http://localhost:8000")

if __name__ == "__main__":
    import uvicorn
    # 自动调起系统默认浏览器，小白双击即用
    threading.Thread(target=open_browser, daemon=True).start()
    
    print("\n" + "=" * 60)
    print("  [*] Steam to Notion 已成功启动！")
    print("  [*] 访问地址: http://localhost:8000")
    print("  [*] 浏览器将自动为您打开，如未弹出请手动复制上方地址访问。")
    print("  [*] 关闭此黑框窗口即可退出程序。")
    print(f"  [*] 运行日志: {LOG_FILE}")
    print("=" * 60 + "\n")
    
    # 打包模式下不能传字符串 "app:app"，必须直接传入 app 对象
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
