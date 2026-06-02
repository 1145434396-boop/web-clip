# web-clip

把网页（微信公众号 / 飞书 Wiki / 知乎 / 小红书 / 普通博客）一键抓成 **Markdown 原文 + 本地图片**，落地到你指定的目录。专为 AI agent skill 场景设计：**全程本地提取，零 LLM token**，图文位置精确对应。

甩一个或多个链接进来 → 干净的 `.md` + 下载好的图片，直接进你的知识库 / 笔记库。

## 特性

- **多平台**：针对每个平台用最省的抓取方式，自动按域名路由
- **零 token 提取**：HTML→Markdown、图片下载全在本地 Python 跑，不喂正文给大模型
- **精确图文位置**：图片插回正文原位（不是统一堆在文末）
- **自检指标**：每次输出一行 JSON（字数 / 图片数 / 警告 / 正文预览），agent 只看 JSON 即可判断质量，无需回读正文
- **路径记忆**：首次指定输出目录后记住，之后省略
- **失败兜底**：抓不到也写一条 stub，保住链接不丢

## 支持的来源

| 来源 | 抓取方式 | 状态 |
|------|---------|------|
| 微信公众号 `mp.weixin.qq.com` | urllib + 浏览器 UA → lxml 遍历 `js_content` | ✅ 完整 + 精确图文位置 |
| 飞书 Wiki/文档 `*.feishu.cn` | Playwright 分段滚动 + `data-block-id` 重排 | ✅ 完整 + 精确图文位置 |
| 知乎专栏 `zhihu.com` | 非 headless 真实 Chrome 渲染 + trafilatura | ✅ 完整 + 图片 |
| 小红书 `xiaohongshu.com` | urllib 拿文案（initial-state，免登录）+ `urlDefault` 提图 | ✅ 图文笔记（图库式） |
| 普通博客 / 其它 | urllib + trafilatura；失败转浏览器渲染 | ✅ 服务端渲染站点 |
| 任一失败 | 写 stub | 保住链接，`status: failed` |

## 安装

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

依赖：`lxml`（微信解析）、`trafilatura`（通用提取）、`playwright` + chromium（飞书/知乎渲染）。

## 用法

```bash
# 首次：指定输出目录（自动记住）
python scripts/clip.py "<URL>" --out "/path/to/notes"

# 之后：省略 --out，用记住的目录
python scripts/clip.py "<URL>"

# 查看 / 设置默认目录
python scripts/clip.py --show-config
python scripts/clip.py --set-out "/path/to/notes"
```

输出目录解析优先级：`--out` > 环境变量 `CLIP_OUT` > 配置文件 `~/.web-clip.json`。

### 落地结构

```
<DEST_ROOT>/
├── articles/
│   └── <标题>.md
└── assets/
    └── <标题>-00.png, <标题>-01.jpg, ...
```

存进 Obsidian/BOMI 这类知识库时，把 `--out` 指到对应目录即可，例如 `--out "D:/BOMI/raw"`。

### 输出 JSON（自检指标）

```json
{"ok": true, "title": "...", "source": "微信公众号",
 "article": ".../articles/标题.md", "slug": "...",
 "chars": 1497, "images": 2, "img_refs": 2, "headings": 9,
 "warnings": [], "preview": "正文开头……"}
```

- `images == img_refs` 且 `warnings: []` → 抓取干净
- `warnings` 可能含 `empty_title` / `body_too_short` / `ui_noise:复制` / `img_missing:N`
- 失败时 `ok: false`，并在 `stub` 字段给出占位文件路径

## 环境变量

| 变量 | 作用 |
|------|------|
| `CLIP_OUT` | 默认输出根目录（`--out` 优先） |
| `CLIP_HEADLESS=1` | 渲染分支改用 headless（无显示器服务器配合 `xvfb-run`） |


## 作为 Claude Code / agent skill 使用

仓库本身就是一个 skill：`SKILL.md` 描述触发条件与执行流程，`scripts/clip.py` 是实现。

```bash
npx skills add github:1145434396-boop/web-clip -g
```

安装后在 Claude Code 中直接对话即可，例如：

- "帮我把这篇文章存下来：https://..."
- "剪藏这几个链接到我的知识库"

## License

MIT
