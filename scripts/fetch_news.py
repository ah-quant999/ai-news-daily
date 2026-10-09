# -*- coding: utf-8 -*-
"""抓取昨日 AI 重点资讯（纯标准库 RSS/JSON，免费无凭证）。

输出: raw_news/<昨日日期>.json
铁律: 永远 exit 0（抓不到就写空清单，不炸链）；时间一律北京时间 CST+8。
"""
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))

RSS_SOURCES = [
    # (名称, URL, 是否全量收录[AI垂直源=True / 综合源需关键词过滤=False])
    ("机器之心", "https://www.jiqizhixin.com/rss", True),
    ("量子位", "https://www.qbitai.com/feed", True),
    ("36氪", "https://36kr.com/feed", False),
    ("Solidot", "https://www.solidot.org/index?rss", False),
]

AI_KEYWORDS = [
    "AI", "人工智能", "大模型", "LLM", "GPT", "OpenAI", "Anthropic", "Claude",
    "Gemini", "DeepSeek", "混元", "通义", "文心", "豆包", "Kimi", "智谱",
    "智能体", "Agent", "多模态", "芯片", "GPU", "算力", "英伟达", "NVIDIA",
    "机器学习", "深度学习", "神经网络", "生成式", "AIGC", "推理模型",
]

HN_LOOKBACK_HOURS = 36


def _http_get(url: str, timeout: int = 30, retries: int = 3) -> bytes:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (ai-news-daily bot)"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    print(f"[warn] GET failed: {url} -> {last}")
    return b""


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_dt(s: str):
    s = (s or "").strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(CST)
        except ValueError:
            continue
    return None


def fetch_rss(name: str, url: str, ai_only: bool, day_start, day_end):
    raw = _http_get(url)
    if not raw:
        return []
    items = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        # 有些源前面带杂声明，退化重试
        txt = raw.decode("utf-8", "ignore")
        txt = txt[txt.find("<"):]
        try:
            root = ET.fromstring(txt)
        except ET.ParseError:
            print(f"[warn] XML parse failed: {name}")
            return []
    nodes = root.findall(".//item") or root.findall(".//entry")
    for n in nodes:
        title = _strip_html(n.findtext("title") or "")
        link = (n.findtext("link") or "").strip()
        if not link and n.find("link") is not None:
            link = (n.find("link").get("href") or "").strip()
        desc = _strip_html(n.findtext("description") or n.findtext("summary") or "")[:300]
        pub = _parse_dt(n.findtext("pubDate") or n.findtext("published") or n.findtext("updated") or "")
        blob = title + " " + desc
        if ai_only or any(k.lower() in blob.lower() for k in AI_KEYWORDS):
            items.append({"source": name, "title": title, "link": link,
                          "summary": desc, "published": pub.isoformat() if pub else None})
    # 时窗过滤：优先昨日；若昨日命中过少，放宽到近36h
    in_window = [x for x in items if x["published"] and day_start <= datetime.fromisoformat(x["published"]) < day_end]
    picked = in_window if len(in_window) >= 3 else items[:20]
    return picked


def fetch_hn(day_start, day_end):
    since = int((datetime.now(CST) - timedelta(hours=HN_LOOKBACK_HOURS)).timestamp())
    url = ("https://hn.algolia.com/api/v1/search_by_date?tags=story"
           f"&numericFilters=created_at_i>{since}&hitsPerPage=150")
    raw = _http_get(url)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    items = []
    for h in data.get("hits", []):
        title = h.get("title") or ""
        if not any(k.lower() in title.lower() for k in AI_KEYWORDS):
            continue
        items.append({
            "source": "Hacker News",
            "title": title,
            "link": h.get("url") or (f"https://news.ycombinator.com/item?id={h.get('objectID')}" if h.get("objectID") else ""),
            "summary": "",
            "published": h.get("created_at"),
        })
    return items[:20]


def main():
    now = datetime.now(CST)
    day_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start = day_end - timedelta(days=1)
    out: dict = {"generated_at": now.isoformat(), "window": [day_start.isoformat(), day_end.isoformat()], "items": []}

    for name, url, ai_only in RSS_SOURCES:
        got = fetch_rss(name, url, ai_only, day_start, day_end)
        print(f"[ok] {name}: {len(got)} items")
        out["items"].extend(got)
        time.sleep(1)

    got = fetch_hn(day_start, day_end)
    print(f"[ok] Hacker News: {len(got)} items")
    out["items"].extend(got)

    # 去重（按标题）
    seen, uniq = set(), []
    for x in out["items"]:
        key = re.sub(r"\W+", "", x["title"].lower())
        if key and key not in seen:
            seen.add(key)
            uniq.append(x)
    out["items"] = uniq
    out["total"] = len(uniq)

    out_dir = Path(__file__).resolve().parent.parent / "raw_news"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"{day_start.date().isoformat()}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"[done] {path.name} total={out['total']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
