# -*- coding: utf-8 -*-
"""股票搜索索引：SQLite持久化 + 拼音生成 + 模糊匹配。"""
from __future__ import annotations

import logging
import sqlite3
import threading
from difflib import SequenceMatcher
from pathlib import Path

from core.config import DATA_DIR

log = logging.getLogger("stockai.search")

_DB_PATH = DATA_DIR / "stock_index.db"
_lock = threading.Lock()


# ---------- 拼音首字母表（覆盖常见汉字） ----------
# 简化版：只做首字母映射，够用即可
_PINYIN_MAP: dict[str, str] = {}


def _build_pinyin_map() -> None:
    """构建汉字→首字母映射表（常用字）。"""
    global _PINYIN_MAP
    if _PINYIN_MAP:
        return
    # 常用A股股票名称中的汉字（覆盖高频字）
    rows = (
        "阿A", "艾A", "安A", "奥A", "澳A", "百B", "宝B", "北B", "贝B", "比B",
        "碧B", "冰B", "博B", "布B", "白B", "保B", "本B", "必B", "标B", "波B",
        "才C", "财C", "常C", "长C", "朝C", "晨C", "成C", "城C", "赤C", "传C",
        "创C", "春C", "次C", "川C", "磁C", "翠C", "达D", "大D", "代D", "丹D",
        "道D", "德D", "迪D", "电D", "东D", "动D", "都D", "独D", "端D", "多D",
        "当D", "岛D", "登D", "地D", "鼎D", "恩E", "二E", "尔E", "发F", "法F",
        "凡F", "飞F", "丰F", "风F", "佛F", "福F", "富F", "方F", "坊F", "房F",
        "菲F", "分F", "峰F", "凤F", "复F", "高G", "格G", "工G", "公G", "光G",
        "广G", "国G", "贵G", "谷G", "冠G", "硅G", "桂G", "海H", "汉H", "杭H",
        "豪H", "好H", "禾H", "合H", "恒H", "红H", "华H", "化H", "环H", "汇H",
        "火H", "湖H", "虎H", "花H", "黄H", "辉H", "会H", "机J", "吉J", "极J",
        "集J", "计J", "佳J", "家J", "嘉J", "建J", "江J", "交J", "金J", "京J",
        "精J", "九J", "酒J", "君J", "晶J", "捷J", "锦J", "巨J", "均J", "开K",
        "凯K", "康K", "科K", "可K", "克K", "快K", "宽K", "昆K", "蓝L", "老L",
        "乐L", "雷L", "力L", "立L", "利L", "联L", "良L", "两L", "龙L", "鲁L",
        "绿L", "罗L", "洛L", "兰L", "量L", "六L", "陆L", "马M", "玛M", "迈M",
        "茂M", "梅M", "美M", "蒙M", "米M", "密M", "民M", "明M", "摩M", "墨M",
        "茅M", "麦M", "曼M", "苗M", "南N", "能N", "宁N", "农N", "诺N", "欧O",
        "攀P", "朋P", "皮P", "平P", "普P", "鹏P", "浦P", "七Q", "齐Q", "奇Q",
        "企Q", "千Q", "前Q", "强Q", "桥Q", "青Q", "轻Q", "全Q", "群Q", "启Q",
        "钦Q", "庆Q", "秋Q", "人R", "日R", "融R", "如R", "瑞R", "润R", "荣R",
        "容R", "三S", "山S", "上S", "深S", "神S", "生S", "声S", "石S", "时S",
        "世S", "市S", "首S", "双S", "水S", "司S", "四S", "松S", "苏S", "商S",
        "绍S", "申S", "盛S", "视S", "数S", "顺S", "思S", "太T", "泰T", "唐T",
        "天T", "铁T", "通T", "同T", "台T", "特T", "腾T", "体T", "万W", "王W",
        "网W", "微W", "维W", "伟W", "卫W", "温W", "文W", "五W", "西W", "锡X",
        "下X", "先X", "新X", "信X", "星X", "兴X", "徐X", "许X", "厦X", "祥X",
        "晓X", "旭X", "宜Y", "亿Y", "易Y", "益Y", "银Y", "英Y", "永Y", "勇Y",
        "友Y", "有Y", "宇Y", "雨Y", "元Y", "远Y", "云Y", "运Y", "雅Y", "亚Y",
        "盐Y", "扬Y", "药Y", "一Y", "伊Y", "溢Y", "盈Y", "优Y", "渝Y", "玉Y",
        "杂Z", "泽Z", "章Z", "招Z", "浙Z", "真Z", "正Z", "中Z", "众Z", "珠Z",
        "主Z", "住Z", "专Z", "紫Z", "自Z", "总Z", "走Z", "组Z", "最Z", "左Z",
        "州Z", "智Z", "轴Z", "卓Z", "资Z", "综Z", "座Z",
        "股G", "票P", "团T", "份F", "公G", "司S", "业Y", "行X", "银Y",
        "证Z", "险X", "投T", "资Z", "管G", "理L", "名M", "创C", "控K",
    )
    for item in rows:
        if len(item) >= 2:
            char, letter = item[0], item[1]
            _PINYIN_MAP[char] = letter


def get_pinyin_abbr(name: str) -> str:
    """获取中文名称的拼音首字母缩写，如'贵州茅台'→'gzmt'。"""
    _build_pinyin_map()
    result = []
    for ch in name:
        if '\u4e00' <= ch <= '\u9fff':
            result.append(_PINYIN_MAP.get(ch, ''))
        elif ch.isalpha():
            result.append(ch.lower())
    return ''.join(result)


# ---------- SQLite索引 ----------
def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""CREATE TABLE IF NOT EXISTS stock_index (
        code TEXT, name TEXT, pinyin TEXT, market TEXT, ticker TEXT,
        PRIMARY KEY(code)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS search_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT, code TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    return conn


def build_index(stocks: list[dict]) -> int:
    """从内存股票列表构建索引。返回数量。"""
    with _lock:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM stock_index")
        rows = []
        for s in stocks:
            abbr = get_pinyin_abbr(s["name"])
            rows.append((s["code"], s["name"], abbr, s["market"], s["ticker"]))
        cur.executemany(
            "INSERT OR REPLACE INTO stock_index VALUES (?,?,?,?,?)", rows)
        conn.commit()
        count = cur.execute("SELECT COUNT(*) FROM stock_index").fetchone()[0]
        conn.close()
        log.info("股票索引构建完成: %d 条", count)
        return count


def load_index() -> list[dict]:
    """加载索引到内存。"""
    with _lock:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT code,name,pinyin,market,ticker FROM stock_index"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def index_exists() -> bool:
    return _DB_PATH.exists() and _DB_PATH.stat().st_size > 100


def log_search(query: str, code: str) -> None:
    """记录搜索历史。"""
    try:
        with _lock:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO search_history (query, code) VALUES (?,?)",
                (query, code))
            conn.commit()
            conn.close()
    except Exception:
        pass


def get_search_history(limit: int = 5) -> list[dict]:
    """获取最近搜索记录。"""
    try:
        with _lock:
            conn = _get_conn()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT DISTINCT query, code FROM search_history "
                "ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
            conn.close()
            return [dict(r) for r in rows]
    except Exception:
        return []


# ---------- 模糊匹配 ----------
def fuzzy_match(a: str, b: str) -> float:
    """返回相似度0-1。"""
    return SequenceMatcher(None, a, b).ratio()


# 热门股票加权（搜索歧义时优先返回这些）
_HOT = {
    "00700": 30, "600519": 30, "300750": 25, "002594": 25,
    "BABA": 25, "AAPL": 20, "TSLA": 20, "NVDA": 25,
    "000858": 20, "601318": 15,
}


def search_stocks(query: str, stocks: list[dict], limit: int = 15) -> list[dict]:
    """多维度搜索：代码/名称/拼音缩写，带模糊匹配。"""
    query = query.strip().lower()
    if not query:
        return []

    results = []
    for s in stocks:
        code = s["code"].lower()
        name = s["name"].lower()
        pinyin = s.get("pinyin", "").lower()
        ticker = s["ticker"].lower()

        score = 0.0
        match_type = ""

        # 1. 代码精确匹配
        if query == code or query == ticker:
            score = 100
            match_type = "代码精确"
        # 2. 代码前缀匹配
        elif code.startswith(query) or ticker.startswith(query):
            score = 90 - len(query)
            match_type = "代码前缀"
        # 3. 拼音缩写精确匹配
        elif query == pinyin:
            score = 85
            match_type = "拼音"
        # 4. 名称包含
        elif query in name:
            score = 70 - len(query)
            match_type = "名称"
        # 5. 拼音缩写前缀
        elif pinyin.startswith(query) and len(query) >= 2:
            score = 60 - len(query)
            match_type = "拼音前缀"
        # 6. 代码包含
        elif query in code:
            score = 50
            match_type = "代码包含"
        # 7. 模糊匹配（编辑距离）
        else:
            ratio = fuzzy_match(query, name)
            if ratio > 0.6:
                score = ratio * 40
                match_type = "模糊"
            else:
                ratio2 = fuzzy_match(query, pinyin)
                if ratio2 > 0.6:
                    score = ratio2 * 35
                    match_type = "拼音模糊"

        if score > 0:
            # 市场加权：A股+20，港股+10
            market = s.get("market", "")
            if "A股" in market:
                score += 20
            elif "港股" in market:
                score += 10
            # 热门股票加权
            score += _HOT.get(s["code"], 0)
            s = dict(s)
            s["score"] = score
            s["match_type"] = match_type
            results.append(s)

    # 按分数排序
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]
