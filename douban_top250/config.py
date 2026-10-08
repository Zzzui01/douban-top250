# -*- coding: utf-8 -*-
"""全局配置：URL、UA 池、反爬特征、默认抓取节奏与文件路径。"""

from __future__ import annotations

import os
from pathlib import Path

# --- 目标站点 -------------------------------------------------------------- #
BASE_URL = "https://movie.douban.com/top250"
HOME_URL = "https://movie.douban.com/"
SOURCE = BASE_URL

PAGE_SIZE = 25   # 豆瓣 Top250 每页 25 条
MAX_PAGES = 10   # 共 10 页 / 250 条

# --- 反爬对抗 -------------------------------------------------------------- #
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

# 命中这些特征说明被反爬拦截（豆瓣会返回“检测到有异常请求”或跳转 sec.douban.com）
ANTI_BOT_MARKS = ("检测到有异常请求", "sec.douban.com", "captcha", "robot")

# 触发风控的 HTTP 状态码
BLOCK_STATUS_CODES = (403, 418, 429)

# --- 抓取节奏默认值 -------------------------------------------------------- #
# 连续翻页是最明显的爬虫特征：即使每次 sleep 1-2 秒，连打 10 页列表页照样会被拦。
# 因此默认请求间隔 3-6 秒，且每 4 页长休息一次，全量约 2 分钟。
DEFAULT_TIMEOUT = 20
DEFAULT_RETRIES = 4                 # 单页最大尝试次数（普通失败）
DEFAULT_MAX_BLOCK_RETRIES = 2       # 被风控拦截后的最大尝试次数（再多只会延长封禁）
DEFAULT_DELAY = (3.0, 6.0)          # 每次请求前的随机延时范围（秒）
DEFAULT_COOLDOWN_EVERY = 4          # 每抓 N 页长休息一次，0 = 不休息
DEFAULT_COOLDOWN = (25.0, 45.0)     # 长休息随机秒数范围
DEFAULT_PREVIEW = 10                # 控制台预览条数

# --- 路径与文件名 ---------------------------------------------------------- #
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(os.environ.get("DOUBAN_OUTPUT_DIR") or (PROJECT_ROOT / "output"))
LOG_DIR = PROJECT_ROOT / "logs"
CACHE_DIR = PROJECT_ROOT / ".cache"
COOKIE_FILE = CACHE_DIR / "douban_cookies.json"

LOG_FILE = "douban_top250.log"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3

CSV_NAME = "douban_top250.csv"
JSON_NAME = "douban_top250.json"
XLSX_NAME = "douban_top250.xlsx"
CLEAN_CSV_NAME = "douban_top250_clean.csv"
CLEAN_JSON_NAME = "douban_top250_clean.json"
