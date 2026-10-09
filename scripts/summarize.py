# -*- coding: utf-8 -*-
"""用免费档 Hy3（OpenRouter, tencent/hy3:free）总结昨日 AI 资讯。

输出: digests/<昨日日期>.md + digests/latest.md
铁律:
- 无 key / 调用失败 → 降级为「标题清单版」，永远 exit 0，不炸链、不伪造总结。
- 只允许基于给定条目总结，禁止编造。
- 永远不出空文件（空清单也要写出说明），防止下游读到空产物。
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS = ["tencent/hy3:free", "tencent/hy3-preview:free"]
MAX_ITEMS = 45
MAX_CHAR_PER_ITEM = 240

SYSTEM_PROMPT = (
    "你是资深科技编辑，为中文读者写每日 AI 资讯日报。"
    "铁律：只基于用户提供的资讯条目总结，绝不编造、绝不添加条目里没有的信息；"
    "不确定的内容直接舍弃；输出为简体中文 Markdown。"
)

USER_PROMPT_TMPL = """以下是{date}（北京时间）抓取到的 {n} 条 AI 资讯条目（JSON）：

{body}

请输出一份日报，格式如下（不要加其他顶层标题）：

# {date} AI 资讯日报

## 要闻速览
（5~8 条，每条一句话概括，最重要的放前面）

## 分条详情
（每条格式：**标题**（来源）：2 句以内摘要。按重要性排序，最多 15 条）

## 一句话点评
（<=3 句，基于当天条目的整体趋势观察，禁止脑补）

全文控制在 1200 字以内。"""


def _call_openrouter(messages, api_key: str):
    body = json.dumps({
        "model": None,  # placeholder, set per attempt
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 4000,
    }).encode("utf-8")

    last_err = None
    for model in MODELS:
        payload = json.loads(body.decode("utf-8"))
        payload["model"] = model
        data = json.dumps(payload).encode("utf-8")
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    API_URL, data=data, method="POST",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=180) as r:
                    resp = json.loads(r.read())
                text = resp["choices"][0]["message"]["content"]
                if text and text.strip():
                    print(f"[ok] model={model}")
                    return text.strip(), model
                last_err = "empty content"
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {e}"
                print(f"[warn] {model} attempt{attempt + 1}: {last_err}")
                time.sleep(5 * (attempt + 1))
    return None, f"all attempts failed: {last_err}"


def _degraded_digest(date_str: str, items: list, reason: str) -> str:
    lines = [f"# {date_str} AI 资讯日报（降级·标题清单版）", "",
             f"> 模型总结不可用：{reason}。以下为原始条目，仅供参考。", ""]
    if not items:
        lines.append("今日未抓取到符合条件的资讯条目（数据源可能故障），请人工检查 raw_news/。")
    for x in items[:30]:
        line = f"- **{x['title']}**（{x['source']}）"
        if x.get("link"):
            line += f" [链接]({x['link']})"
        lines.append(line)
    return "\n".join(lines) + "\n"


def main():
    now = datetime.now(CST)
    day_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    date_str = (day_end - timedelta(days=1)).date().isoformat()
    base = Path(__file__).resolve().parent.parent
    raw_path = base / "raw_news" / f"{date_str}.json"
    if not raw_path.exists():
        # 容错：抓取步失败时找最近一份 raw_news
        candidates = sorted((base / "raw_news").glob("*.json")) if (base / "raw_news").exists() else []
        if not candidates:
            digest = _degraded_digest(date_str, [], "raw_news 缺失（抓取步失败）")
            _write(base, date_str, digest, {"model": "degraded", "total": 0})
            return 0
        raw_path = candidates[-1]
        date_str = raw_path.stem

    data = json.loads(raw_path.read_text(encoding="utf-8"))
    items = data.get("items", [])
    slim = [
        {"source": x.get("source"), "title": x.get("title"),
         "summary": (x.get("summary") or "")[:MAX_CHAR_PER_ITEM]}
        for x in items[:MAX_ITEMS]
    ]

    api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    digest, model_used = None, None
    if api_key and slim:
        body_lines = [json.dumps(x, ensure_ascii=False) for x in slim]
        user_prompt = USER_PROMPT_TMPL.format(date=date_str, n=len(slim), body="\n".join(body_lines))
        text, model_used = _call_openrouter(
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user", "content": user_prompt}], api_key)
        if text:
            digest = text
        else:
            print(f"[warn] LLM failed: {model_used}")
    elif not api_key:
        print("[warn] OPENROUTER_API_KEY 未配置，走降级标题清单版")

    if digest is None:
        reason = "LLM 调用失败" if api_key else "未配置 OPENROUTER_API_KEY"
        digest = _degraded_digest(date_str, slim, reason)
        model_used = model_used or "degraded"

    _write(base, date_str, digest, {"model": model_used, "total": len(slim)})
    return 0


def _write(base: Path, date_str: str, digest: str, meta: dict):
    d = base / "digests"
    d.mkdir(exist_ok=True)
    footer = f"\n\n---\n*生成：GitHub Actions + 免费模型 {meta.get('model')} · 条目数 {meta.get('total')} · 零积分*\n"
    out = digest.rstrip() + footer
    (d / f"{date_str}.md").write_text(out, encoding="utf-8", newline="\n")
    (d / "latest.md").write_text(out, encoding="utf-8", newline="\n")
    print(f"[done] digests/{date_str}.md model={meta.get('model')} total={meta.get('total')}")


if __name__ == "__main__":
    sys.exit(main())
