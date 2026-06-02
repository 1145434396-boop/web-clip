#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
web-clip: 把网页（微信公众号 / 飞书 Wiki / 知乎 / 小红书 / 通用网页）抓成
Markdown + 图片，落地到用户指定的目录。全程零 LLM token。

用法:
    python clip.py <url> [--out <DEST_ROOT>] [--slug <slug>]
    python clip.py --show-config        # 打印已保存的输出目录
    python clip.py --set-out <DEST_ROOT> # 仅保存默认输出目录，不抓取

输出目录解析优先级：--out > 环境变量 CLIP_OUT > 配置文件 ~/.web-clip.json
首次用 --out 指定后会写入配置文件，之后可省略。

路由:
    mp.weixin.qq.com  -> 静态 HTML + lxml 遍历 js_content（精确图文位置）
    *.feishu.cn       -> Playwright 分段滚动 + data-block-id 重排（精确图文位置）
    zhihu.com         -> 非 headless 真实 Chrome 渲染 + trafilatura
    xiaohongshu.com   -> urllib 拿文案 + urlDefault 提图
    其它              -> urllib + trafilatura；失败转浏览器渲染
    全部失败          -> 写一条 stub，保住链接不丢

落地结构:
    {DEST_ROOT}/articles/{slug}.md
    {DEST_ROOT}/assets/{slug}-NN.<ext>

环境变量:
    CLIP_OUT       默认输出根目录（命令行 --out 优先）
    CLIP_HEADLESS  设 1 则渲染分支用 headless（云端无显示器时配合 xvfb）
"""
import sys, os, io, re, json, base64, hashlib, argparse, urllib.request, datetime, urllib.parse

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36')


# ---------- 公共工具 ----------

def slugify(text, fallback):
    text = (text or '').strip()
    # 长标题（如小红书整段文案）截到第一个句末标点或换行
    cut = re.split(r'[。！？\n.!?]', text, maxsplit=1)[0]
    if cut:
        text = cut
    text = re.sub(r'[\\/:*?"<>|#]+', '', text)
    text = re.sub(r'\s+', '-', text)
    text = text.strip('-')
    return text[:40] if text else fallback


def compute_checks(title, author, body, n_img, assets_dir, slug):
    """本地算质检指标，塞进 JSON，让 agent 不必回读正文。"""
    warnings = []
    if not title.strip():
        warnings.append('empty_title')
    if len(body.strip()) < 200:
        warnings.append('body_too_short')
    # 残留的飞书/编辑器 UI 噪声
    for noise in ('复制', 'Plain Text', '代码块', '请输入'):
        if noise in body:
            warnings.append(f'ui_noise:{noise}')
    # markdown 里引用的图片 vs 实际落盘的文件
    refs = re.findall(r'!\[\]\(assets/([^)]+)\)', body)
    on_disk = [f for f in os.listdir(assets_dir) if f.startswith(slug + '-')] if os.path.isdir(assets_dir) else []
    missing = [r for r in refs if r not in on_disk]
    if missing:
        warnings.append(f'img_missing:{len(missing)}')
    # 正文开头预览（截断，几十 token，够判断是不是抓到了正确内容）
    preview = re.sub(r'\s+', ' ', body.strip())[:120]
    return {
        'chars': len(body),
        'images': n_img,
        'img_refs': len(refs),
        'headings': len(re.findall(r'(?m)^#{2,6} ', body)),
        'warnings': warnings,
        'preview': preview,
    }


def ext_from(header_or_url, default='png'):
    s = header_or_url.lower()
    if 'jpeg' in s or 'jpg' in s or 'wx_fmt=jpeg' in s:
        return 'jpg'
    if 'gif' in s:
        return 'gif'
    if 'webp' in s:
        return 'webp'
    if 'svg' in s:
        return 'svg'
    return default


# ---------- 微信公众号：静态 HTML ----------

def fetch_wechat(url, slug, assets_dir):
    from lxml import html as lxml_html
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9'})
    raw = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'replace')
    tree = lxml_html.fromstring(raw)

    h1 = tree.xpath('//h1[contains(@class,"rich_media_title")]')
    title = h1[0].text_content().strip() if h1 else ''
    name = tree.xpath('//*[@id="js_name"]/text()')
    author = name[0].strip() if name else ''

    nodes = tree.xpath('//div[@id="js_content"]')
    if not nodes:
        raise RuntimeError('js_content not found (可能被反爬拦截)')
    content = nodes[0]

    counter = [0]
    lines = []

    def dl(src):
        src = (src or '').replace('&amp;', '&')
        if not src or src.startswith('data:'):
            return None
        try:
            r = urllib.request.Request(src, headers={'User-Agent': UA, 'Referer': url})
            data = urllib.request.urlopen(r, timeout=30).read()
        except Exception:
            return None
        fname = f'{slug}-{counter[0]:02d}.{ext_from(src)}'
        with open(os.path.join(assets_dir, fname), 'wb') as f:
            f.write(data)
        counter[0] += 1
        return fname

    BLOCK = ('p', 'section', 'h1', 'h2', 'h3', 'h4', 'blockquote', 'li')

    def walk(node):
        if node.tag == 'img':
            fn = dl(node.get('data-src') or node.get('src'))
            if fn:
                lines.append(f'![](assets/{fn})')
                lines.append('')
            return
        if node.tag in BLOCK:
            has_child_block = any(
                c.tag in BLOCK + ('img', 'ul', 'ol') for c in node)
            if not has_child_block:
                txt = node.text_content().strip()
                if txt:
                    if node.tag in ('h1', 'h2', 'h3', 'h4'):
                        lines.append('#' * max(int(node.tag[1]), 2) + ' ' + txt)
                    elif node.tag == 'blockquote':
                        lines.append('> ' + txt)
                    elif node.tag == 'li':
                        lines.append('- ' + txt)
                    else:
                        lines.append(txt)
                    lines.append('')
                return
        for c in node:
            walk(c)

    for child in content:
        walk(child)

    body = '\n'.join(lines)
    return title, author, '微信公众号', body, counter[0]


# ---------- 飞书 Wiki / 文档：Playwright ----------

def fetch_feishu(url, slug, assets_dir):
    """基于飞书页面内部模型 window.PageMain 提取，保留表格格式、画板图片。"""
    from playwright.sync_api import sync_playwright

    extractor = open(os.path.join(os.path.dirname(__file__), 'feishu-extract.js'),
                     encoding='utf-8').read()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 2000}, user_agent=UA)
        page.goto(url, wait_until='networkidle', timeout=45000)
        page.wait_for_timeout(4000)

        # 滚动加载，触发画板/图片等懒加载块初始化
        container = '.bear-web-x-container'
        if not page.query_selector(container):
            container = 'body'
        max_scroll = page.evaluate(f'(document.querySelector("{container}")||document.body).scrollHeight')
        pos = 0
        while pos <= max_scroll + 800:
            page.evaluate(f'(document.querySelector("{container}")||document.body).scrollTop = {pos}')
            page.wait_for_timeout(250)
            max_scroll = page.evaluate(f'(document.querySelector("{container}")||document.body).scrollHeight')
            pos += 600
        page.wait_for_timeout(2000)

        page.evaluate(extractor)
        result = page.evaluate('async () => await window.__webclipExtractFeishu()')
        browser.close()

    if not result:
        raise RuntimeError('window.PageMain 不可用（可能未登录或文档未加载）')

    title = result.get('title', '')
    body = result.get('content', '')
    images = result.get('images', {})

    # 落盘图片，替换占位符
    counter = 0
    for key, rec in images.items():
        try:
            data_url = rec['dataUrl']
            header, b64 = data_url.split(',', 1)
            data = base64.b64decode(b64)
        except Exception:
            continue
        fname = f'{slug}-{counter:02d}.{ext_from(header)}'
        with open(os.path.join(assets_dir, fname), 'wb') as f:
            f.write(data)
        body = body.replace(key, f'assets/{fname}')
        counter += 1

    return title, '', '飞书', body, counter


# ---------- 小红书：urllib 拿文案 + urlDefault 提图 ----------

def fetch_xhs(url, slug, assets_dir):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9'})
    html = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'replace')

    # 正文文案：优先 trafilatura，回退 og:description
    md, title, author = _trafilatura_md(html)
    if not md or len(md.strip()) < 20:
        desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html)
        md = desc.group(1) if desc else ''
    if not title:
        t = re.search(r'<meta[^>]+og:title["\'][^>]+content=["\']([^"\']+)["\']', html)
        title = (t.group(1) if t else '').replace(' - 小红书', '').strip()

    # 笔记图片：urlDefault（按 fileId 去重、保序）
    defs = re.findall(r'"urlDefault":"([^"]+)"', html)
    seen, imgs = set(), []
    for d in defs:
        d = d.replace('\\u002F', '/')
        fid = re.search(r'/([0-9a-z]+)!', d)
        key = fid.group(1) if fid else d
        if key not in seen:
            seen.add(key)
            imgs.append(d)

    n = 0
    gallery = []
    for d in imgs:
        try:
            r = urllib.request.Request(d.replace('http://', 'https://'),
                                       headers={'User-Agent': UA, 'Referer': 'https://www.xiaohongshu.com/'})
            data = urllib.request.urlopen(r, timeout=30).read()
        except Exception:
            continue
        fname = f'{slug}-{n:02d}.jpg'
        with open(os.path.join(assets_dir, fname), 'wb') as f:
            f.write(data)
        gallery.append(f'![](assets/{fname})')
        n += 1

    body = (md or '').strip()
    # 清理小红书噪声：话题标签的搜索链接 -> 纯文本；移除"加载中"占位
    body = re.sub(r'\[(#[^\]]+)\]\([^)]*\)', r'\1', body)
    body = re.sub(r'(?m)^\s*加载中\s*$', '', body)
    body = re.sub(r'\n{3,}', '\n\n', body).strip()
    if gallery:
        body += '\n\n' + '\n\n'.join(gallery)
    return title, author, '小红书', body, n


# ---------- 通用网页：trafilatura，失败转渲染 ----------

def _download_md_images(md, url, slug, assets_dir):
    """把 markdown 里的远程图片直链下载到本地并改写引用，保留原位置。"""
    counter = [0]
    seen = {}

    def repl(m):
        src = m.group(1).replace('&amp;', '&')
        if src.startswith('data:') or not src.startswith('http'):
            return m.group(0)
        if src in seen:
            return f'![](assets/{seen[src]})'
        try:
            r = urllib.request.Request(src, headers={'User-Agent': UA, 'Referer': url})
            data = urllib.request.urlopen(r, timeout=30).read()
        except Exception:
            return m.group(0)  # 下载失败保留原链接
        fname = f'{slug}-{counter[0]:02d}.{ext_from(src)}'
        with open(os.path.join(assets_dir, fname), 'wb') as f:
            f.write(data)
        seen[src] = fname
        counter[0] += 1
        return f'![](assets/{fname})'

    md = re.sub(r'!\[[^\]]*\]\(([^)]+)\)', repl, md)
    return md, counter[0]


def _trafilatura_md(html):
    import trafilatura
    md = trafilatura.extract(html, favor_recall=True, include_images=True,
                             include_links=True, output_format='markdown')
    title = author = ''
    meta = trafilatura.extract_metadata(html)
    if meta:
        title = meta.title or ''
        author = meta.author or ''
    return md, title, author


def fetch_generic(url, slug, assets_dir):
    # 先试零浏览器的 urllib + trafilatura（最省）
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9'})
        html = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'replace')
        md, title, author = _trafilatura_md(html)
        if md and len(md.strip()) > 200:
            md, n = _download_md_images(md, url, slug, assets_dir)
            return title, author, urllib.parse.urlparse(url).netloc, md, n
    except Exception:
        pass
    # 失败 -> 真实浏览器渲染（知乎等反爬/SPA）
    return fetch_rendered(url, slug, assets_dir)


def fetch_rendered(url, slug, assets_dir):
    """非 headless 真实 Chrome 渲染 + 反自动化检测，再交给 trafilatura。
    云端无显示器需用 xvfb-run 包裹，或设 BOMI_HEADLESS=1。"""
    from playwright.sync_api import sync_playwright
    headless = os.environ.get('CLIP_HEADLESS', '') == '1'
    with sync_playwright() as p:
        launch_args = ['--disable-blink-features=AutomationControlled']
        try:
            browser = p.chromium.launch(headless=headless, channel='chrome', args=launch_args)
        except Exception:
            browser = p.chromium.launch(headless=headless, args=launch_args)
        ctx = browser.new_context(viewport={'width': 1280, 'height': 2000},
                                  user_agent=UA, locale='zh-CN')
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()
        page.goto(url, wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(5000)
        page_title = page.title()
        html = page.content()
        body_text = page.inner_text('body')
        browser.close()

    # 登录墙/风控检测
    if len(body_text.strip()) < 200 or '请输入手机号' in body_text or '当前请求存在异常' in body_text \
            or ('登录' in body_text[:80] and len(body_text.strip()) < 400):
        raise RuntimeError('疑似登录墙或风控拦截（需登录态，浏览器渲染也拿不到正文）')

    md, title, author = _trafilatura_md(html)
    if not md or len(md.strip()) < 200:
        raise RuntimeError('渲染后 trafilatura 仍提取过少')
    title = title or page_title
    md, n = _download_md_images(md, url, slug, assets_dir)
    return title, author, urllib.parse.urlparse(url).netloc, md, n


# ---------- stub 兜底 ----------

def write_stub(url, slug, articles_dir, err):
    captured = datetime.date.today().isoformat()
    path = os.path.join(articles_dir, f'{slug}.md')
    md = (f'---\n'
          f'title: 未成功抓取\n'
          f'source_url: {url}\n'
          f'captured_at: {captured}\n'
          f'status: failed\n'
          f'error: "{err}"\n'
          f'---\n\n'
          f'# 未成功抓取的文章\n\n'
          f'- source_url: {url}\n'
          f'- captured_at: {captured}\n'
          f'- error: {err}\n\n'
          f'待人工补充。\n')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(md)
    return path


# ---------- 配置持久化 ----------

CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.web-clip.json')


def load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def resolve_out(cli_out):
    """优先级：--out > CLIP_OUT 环境变量 > 配置文件。命中 --out 时持久化。"""
    if cli_out:
        cfg = load_config()
        cfg['out'] = cli_out
        save_config(cfg)
        return cli_out
    env = os.environ.get('CLIP_OUT', '')
    if env:
        return env
    return load_config().get('out', '')


# ---------- 主流程 ----------

def route(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    if 'mp.weixin.qq.com' in host:
        return fetch_wechat
    if 'feishu.cn' in host or 'larksuite.com' in host or 'doubao.com' in host:
        return fetch_feishu
    if 'zhihu.com' in host:
        return fetch_rendered
    if 'xiaohongshu.com' in host or 'xhslink.com' in host:
        return fetch_xhs
    return fetch_generic


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('url', nargs='?', default='')
    ap.add_argument('--out', default='', help='输出根目录（首次指定后会记住）')
    ap.add_argument('--slug', default='')
    ap.add_argument('--show-config', action='store_true', help='打印已保存的输出目录后退出')
    ap.add_argument('--set-out', default='', help='仅保存默认输出目录，不抓取')
    args = ap.parse_args()

    # 仅查看 / 设置配置
    if args.show_config:
        print(json.dumps({'out': load_config().get('out') or None,
                          'config_path': CONFIG_PATH}, ensure_ascii=False))
        return
    if args.set_out:
        resolve_out(args.set_out)
        print(json.dumps({'ok': True, 'out': args.set_out, 'config_path': CONFIG_PATH}, ensure_ascii=False))
        return

    if not args.url:
        print(json.dumps({'ok': False, 'error': '缺少 url'}, ensure_ascii=False))
        sys.exit(2)

    out_root = resolve_out(args.out)
    if not out_root:
        print(json.dumps({'ok': False, 'error': 'no_output_dir',
                          'hint': '未设置输出目录，请先问用户存到哪里，再用 --out <DIR> 指定（会自动记住）'},
                         ensure_ascii=False))
        sys.exit(2)

    articles_dir = os.path.join(out_root, 'articles')
    assets_dir = os.path.join(out_root, 'assets')
    os.makedirs(articles_dir, exist_ok=True)
    os.makedirs(assets_dir, exist_ok=True)

    slug = args.slug or hashlib.md5(args.url.encode()).hexdigest()[:10]
    fetcher = route(args.url)

    try:
        title, author, source, body, n_img = fetcher(args.url, slug, assets_dir)
        if args.slug == '' and title:
            new_slug = slugify(title, slug)
            if new_slug != slug:
                # rename already-downloaded images to the title slug
                for fn in os.listdir(assets_dir):
                    if fn.startswith(slug + '-'):
                        os.rename(os.path.join(assets_dir, fn),
                                  os.path.join(assets_dir, fn.replace(slug, new_slug, 1)))
                body = body.replace(f'assets/{slug}-', f'assets/{new_slug}-')
                slug = new_slug

        captured = datetime.date.today().isoformat()
        fm = ['---',
              f'title: {title}',
              f'author: {author}',
              f'source_url: {args.url}',
              f'source: {source}',
              f'captured_at: {captured}',
              'status: ok',
              '---', '']
        head = f'# {title}\n' if title else ''
        md = '\n'.join(fm) + head + '\n' + body.strip() + '\n'
        md = re.sub(r'\n{3,}', '\n\n', md)
        path = os.path.join(articles_dir, f'{slug}.md')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(md)
        checks = compute_checks(title, author, body, n_img, assets_dir, slug)
        out = {'ok': True, 'title': title, 'author': author,
               'source': source, 'article': path, 'slug': slug}
        out.update(checks)
        print(json.dumps(out, ensure_ascii=False))
    except Exception as e:
        path = write_stub(args.url, slug, articles_dir, str(e).replace('"', "'")[:200])
        print(json.dumps({'ok': False, 'error': str(e), 'stub': path}, ensure_ascii=False))
        sys.exit(1)


if __name__ == '__main__':
    main()
