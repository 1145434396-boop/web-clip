---
name: web-clip
description: >
  把网页链接（微信公众号、飞书 Wiki/文档、知乎、小红书、普通博客等）抓取成 Markdown + 图片，
  落地到用户指定的本地目录。当用户说"存下来""剪藏""抓下来""保存这篇文章/笔记"时使用。
  首次使用先问用户存到哪个目录，记住后不再问。
---

# Web Clip

## 1. 确认目录

```bash
python <skill_dir>/scripts/clip.py --show-config
```

- `{"out": null}` → 问用户存到哪里，用 `--out "<DIR>"` 指定（自动记住）
- `{"out": "..."}` → 已有目录，直接抓

## 2. 抓取

```bash
python <skill_dir>/scripts/clip.py "<URL>" [--out "<DIR>"]
```

多个链接逐个调用。

## 3. 读 JSON，不要 Read .md

- `warnings: []` 且 `images == img_refs` → 成功，直接汇报
- `preview` → 确认抓到的是正确页面
- `warnings` 非空 → 排查：`body_too_short`（反爬）/ `img_missing:N`（图缺失）/ `ok:false`（stub 已写）

## 4. 汇报

标题、落地路径、图片数；失败列出原因。
