---
name: web-clip
description: >
  把网页链接（微信公众号、飞书 Wiki/文档、知乎、小红书、普通博客等）抓取成 Markdown 原文 + 图片，
  落地到用户指定的本地目录。当用户甩一个或多个网址说"存下来""剪藏""抓下来归档""保存这篇文章/笔记"
  时使用。全程本地提取，零 LLM token；图文位置精确对应。首次使用先问用户存到哪个目录，记住后不再问。
---

# Web Clip

把网页剪藏成 Markdown + 图片，存到用户指定目录的 `articles/` 和 `assets/` 子目录。

## 完成标准

只做到「落地文件」：抓取 → 写入 `<DEST>/articles/<slug>.md` + `<DEST>/assets/`。
不做摘要/改写。

## 输出目录（首次必问，之后记住）

脚本把输出目录持久化在 `~/.web-clip.json`，解析优先级：`--out` > 环境变量 `CLIP_OUT` > 配置文件。

**执行任何抓取前，先确认是否已有保存的目录：**

```bash
python <skill_dir>/scripts/clip.py --show-config
```

- 返回 `{"out": null}` → **先问用户要存到哪个目录**，拿到路径后用 `--out "<DIR>"` 跑第一篇
  （会自动写入配置），或先 `--set-out "<DIR>"` 保存再抓。
- 返回 `{"out": "..."}` → 已有目录，直接抓，不用再问；除非用户要求换目录。

> 注意：`--out` 指向的是输出根目录，脚本在其下建 `articles/` 和 `assets/`。
> 例：用户想存进 BOMI 知识库的 raw，就传 `--out "D:\BOMI\raw"`。

## 依赖（首次安装）

```bash
pip install lxml trafilatura playwright
python -m playwright install chromium
```

- `lxml`：微信公众号静态 HTML 解析
- `trafilatura`：通用网页提取
- `playwright` + chromium：飞书 / 知乎等需要渲染的站点

## 用法

```bash
# 首次：指定目录（自动记住）
python <skill_dir>/scripts/clip.py "<URL>" --out "<DEST_ROOT>"

# 之后：省略 --out，用记住的目录
python <skill_dir>/scripts/clip.py "<URL>"
```

- 多个链接：逐个调用（每次一个 URL）。
- 不传 `--slug` 时，文件名自动用文章标题；图片命名 `<slug>-NN.<ext>`。
- 脚本输出一行 JSON（含自检指标），见下。

成功示例输出：
```json
{"ok": true, "title": "...", "source": "微信公众号",
 "article": ".../articles/标题.md", "slug": "...",
 "chars": 1497, "images": 2, "img_refs": 2, "headings": 9,
 "warnings": [], "preview": "每次换 AI 供应商……"}
```

### 省 token：只看 JSON，不要回读正文

脚本已在本地把质检指标算好放进 JSON。**默认不要用 Read 打开抓下来的 `.md`**（一篇中文长文回读要几千 token）。直接按 JSON 判断：

- `warnings: []` 且 `images == img_refs` → 抓取干净，直接汇报成功。
- `preview` 字段瞄一眼正文开头是否是预期内容（防抓错页面）。
- **只有** `warnings` 非空时，才按需 Read 对应片段排查：
  - `empty_title` / `body_too_short` → 可能被反爬或选错容器
  - `ui_noise:复制` 等 → 残留编辑器按钮文字，需补清洗规则
  - `img_missing:N` → N 张图引用了但没下下来
  - `ok: false` → 已写 stub，正文未抓到

## 执行流程

1. `--show-config` 看有没有保存的目录；没有就**问用户存到哪里**，用 `--out` 指定（自动记住）。
2. 对每个 URL 跑 `clip.py`，**只读 JSON 结果**（见「省 token」一节，默认不回读正文）。
3. 按 JSON 的 `warnings` / `images==img_refs` / `preview` 判断成败；仅异常时才 Read 排查。
4. 若目标目录是有自身约定的知识库，按其约定收尾（如更新索引/日志）；否则跳过。
5. 向用户汇报：标题、落地路径、图片数；失败的列出来并说明（stub 已写）。

