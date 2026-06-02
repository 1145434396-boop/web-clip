---
name: web-clip
description: >
  把网页链接（微信公众号、飞书 Wiki/文档、知乎、小红书、普通博客等）抓取成 Markdown + 图片，
  落地到用户指定的本地目录。当用户说"存下来""剪藏""抓下来""保存这篇文章/笔记"时使用。
---

```bash
bash <skill_dir>/scripts/run.sh "<URL>" [--out "<DIR>"]
```

- 输出 `NEED_DIR` → 问用户存到哪个目录，补 `--out "<DIR>"` 重跑
- 多个链接逐个调用
- 直接把输出转给用户
