// 通用网页 DOM 提取器：在 Playwright 渲染后的活 DOM 上跑，
// 复用 Readability + Turndown，叠加滚动加载 / 解懒加载 / _next/image 解码 / 首图兜底。
// 定义 window.__webclipExtractGeneric()，返回 {title, content}（content 为含真实图片 URL 的 markdown）。
// 图片不在此处下载（页面内 fetch 受 CORS 限制），交由 Python 端 urllib 下载。
window.__webclipExtractGeneric = async function () {
  const INVISIBLE = /[­​-‏‪-‮⁠-⁯﻿]/g;

  // _next/image?url=ENCODED 等代理 → 真实原图
  const resolveUrl = (u) => {
    if (!u) return '';
    const m = u.match(/\/_next\/image\?url=([^&]+)/);
    if (m) { try { return decodeURIComponent(m[1]); } catch (e) {} }
    return u;
  };

  // 1) 滚动到底触发懒加载，再回顶
  const sh = document.body.scrollHeight;
  for (let p = 0; p <= sh; p += 600) { window.scrollTo(0, p); await new Promise(r => setTimeout(r, 200)); }
  window.scrollTo(0, 0);
  await new Promise(r => setTimeout(r, 400));

  // 2) 把懒加载 / srcset / 代理的真实地址写回 img.src，让 Readability 能保留、markdown 链接正确
  for (const img of document.querySelectorAll('img')) {
    let u = img.currentSrc || img.getAttribute('src') || img.getAttribute('data-src') || '';
    if ((!u || u.startsWith('data:')) && img.getAttribute('srcset')) {
      const cands = img.getAttribute('srcset').split(',').map(s => s.trim().split(/\s+/)[0]).filter(Boolean);
      if (cands.length) u = cands[cands.length - 1];
    }
    u = resolveUrl(u);
    if (u && u.startsWith('http')) img.setAttribute('src', u);
  }

  // 3) 文章首图候选（DOM 第一张大图，排除导航/页脚）——Readability 常裁掉正文主体外的首图
  let leadUrl = '';
  for (const img of document.querySelectorAll('img')) {
    if (img.closest('nav, footer')) continue;
    const w = img.naturalWidth || parseInt(img.getAttribute('width')) || 0;
    const h = img.naturalHeight || parseInt(img.getAttribute('height')) || 0;
    if (w >= 400 || h >= 400) {
      const u = resolveUrl(img.currentSrc || img.getAttribute('src') || '');
      if (u && u.startsWith('http')) { leadUrl = u; break; }
    }
  }

  const article = new Readability(document.cloneNode(true)).parse();
  if (!article) return null;
  const td = new TurndownService({ headingStyle: 'atx', codeBlockStyle: 'fenced' });
  let content = td.turndown(article.content);
  const title = (article.title || document.title || '').replace(INVISIBLE, '').trim();

  // 去掉正文开头的 H1（文章首个 H1 即标题，外层会单独添加，避免重复；只删 # 不碰 ##）
  content = content.replace(/^\s*#\s+[^\n]+\n+/, '');

  // 首图若未被正文收录，补到开头
  if (leadUrl && !content.includes(leadUrl)) content = `![](${leadUrl})\n\n` + content;

  return { title: title || '无标题', content };
};
