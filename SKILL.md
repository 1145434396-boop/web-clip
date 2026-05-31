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
不做摘要/改写。若目标目录是某个有自身约定的知识库（如 Obsidian/BOMI），抓完后按那个库的
约定收尾（如更新索引、日志），否则止于落地文件。

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

## 路由策略（脚本内部自动判断，无需干预）

| 来源 | 方法 | 说明 |
|------|------|------|
| `mp.weixin.qq.com` | urllib + 浏览器 UA → lxml 遍历 `js_content` | 服务端渲染，零浏览器；带 UA 绕反爬 |
| `*.feishu.cn` / `larksuite.com` / `doubao.com` | Playwright 分段滚动 + `data-block-id` 重排 | SPA + 虚拟滚动，必须真浏览器 |
| `zhihu.com` | 非 headless 真实 Chrome 渲染 + 反自动化 → trafilatura | headless 会被风控拦，必须真浏览器 |
| `xiaohongshu.com` / `xhslink.com` | urllib 拿文案（initial-state，免登录）+ `urlDefault` 提图 | 笔记图片作图库附正文后 |
| 其它（博客等） | urllib + trafilatura；失败转渲染分支 | 图片直链下载改本地路径 |
| 任一失败 | 写 stub | 保住链接，`status: failed`，待人工补 |

**渲染分支**（知乎及通用兜底）默认非 headless（`headless=False` + chrome channel + 屏蔽 `navigator.webdriver`）。
无显示器的服务器：需用 `xvfb-run` 包裹，或设环境变量 `CLIP_HEADLESS=1`（但 headless 可能重新被风控拦）。

**精确图文位置**：微信按 `js_content` 子节点 DOM 顺序；飞书按 `data-block-id` 整数排序重建。
飞书图片是 `blob:` URL，会被虚拟滚动卸载，脚本在可见时即时 `fetch`→base64 落盘，按字节指纹去重。

## 执行流程

1. `--show-config` 看有没有保存的目录；没有就**问用户存到哪里**，用 `--out` 指定（自动记住）。
2. 对每个 URL 跑 `clip.py`，**只读 JSON 结果**（见「省 token」一节，默认不回读正文）。
3. 按 JSON 的 `warnings` / `images==img_refs` / `preview` 判断成败；仅异常时才 Read 排查。
4. 若目标目录是有自身约定的知识库，按其约定收尾（如更新索引/日志）；否则跳过。
5. 向用户汇报：标题、落地路径、图片数；失败的列出来并说明（stub 已写）。

## 已验证

- ✅ 微信公众号（含图、列表、标题、代码块，精确图文位置）
- ✅ 飞书 Wiki（虚拟滚动全文 + 7 张图精确定位）
- ✅ 知乎专栏（非 headless 渲染，正文 + 图片直链下载定位）
- ✅ 小红书图文笔记（免登录拿文案 + `urlDefault` 提笔记图，图库附正文后）
- ✅ 普通博客（urllib + trafilatura，零浏览器）

## 未验证 / 注意

- 小红书**视频**笔记只会拿到文案，封面/视频未处理。
- 小红书图片是图库形式附在正文末尾（XHS 笔记本无图文交错结构），非逐段插入。
- 小红书 `title`/frontmatter 用整段文案（XHS 笔记无独立标题）；文件名 slug 已截到第一个句末标点。
- 微信文章标题级别：公众号作者常用扁平 `<h2>`，脚本忠实保留为 `##`，不强行推断子级。
- 脚本不做正文语义改写（零 token）；如需更干净的排版，再让 Claude 过一遍（有 token 成本）。
