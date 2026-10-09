# ai-news-daily

每日 09:00（北京时间）自动总结昨日 AI 重点资讯。

- 全链路跑在 GitHub Actions 上，LLM 用免费档 **Hy3**（腾讯混元开源，OpenRouter `tencent/hy3:free`），**零积分、零费用**。
- 数据源：机器之心 / 量子位 / 36氪 / Solidot / Hacker News（RSS，免费）。
- 产物：`digests/<日期>.md`（当日归档）+ `digests/latest.md`（最新一篇）。
- 未配置 `OPENROUTER_API_KEY` 或模型调用失败时，自动降级为「标题清单版」，不中断、不伪造。

## 需要配置的 Secret

| Secret | 说明 |
|---|---|
| `OPENROUTER_API_KEY` | openrouter.ai 注册（邮箱即可）→ Keys 创建 |

## 手动触发

Actions → AI news daily digest → Run workflow。
