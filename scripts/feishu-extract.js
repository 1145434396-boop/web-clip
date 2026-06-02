// feishu-extract.js — 基于 window.PageMain 内部模型树提取飞书文档
// 定义 window.__webclipExtractFeishu()，返回 {title, content, images}
// images: { placeholderKey: { dataUrl, mime } }，content 中以 placeholderKey 作为图片占位
(function () {
  const ZWSP = /[\u200b\u200c\u200d\u2060\ufeff]/g;
  const clean = s => (s || '').replace(ZWSP, '');

  function blockText(b) {
    try {
      const zs = b.zoneState;
      if (!zs) return '';
      // 优先用 content.ops（Quill delta），可还原 mention / 超链接
      const content = zs.content || (zs.getContent && zs.getContent());
      if (content && Array.isArray(content.ops)) {
        let out = '';
        for (const op of content.ops) {
          let ins = typeof op.insert === 'string' ? op.insert : '';
          const attr = op.attributes || {};
          if (attr['fixEnter'] === 'true') continue;           // 行尾换行占位
          const ic = attr['inline-component'];
          if (ic) {
            try {
              const comp = JSON.parse(ic);
              const d = comp.data || {};
              const t = comp.type || '';
              if (t.indexOf('mention') === 0) {
                const label = d.title || d.name || ins.trim() || '链接';
                const url = d.raw_url || d.url || '';
                out += url ? ('[' + label + '](' + url + ')') : label;
                continue;
              }
            } catch (e) {}
          }
          const link = attr['link'] || attr['href'];
          if (link && ins.trim()) { out += '[' + ins + '](' + decodeURIComponent(link) + ')'; continue; }
          out += ins;
        }
        return clean(out).replace(/\n+$/, '').trim();
      }
      const t = zs.allText || '';
      return clean(t).replace(/\n+$/, '').trim();
    } catch (e) { return ''; }
  }

  function blobToDataUrl(blob) {
    return new Promise(r => { const fr = new FileReader(); fr.onloadend = () => r(fr.result); fr.readAsDataURL(blob); });
  }

  async function fetchByToken(imgMgr, token) {
    if (!imgMgr || !token) return null;
    try {
      const info = await new Promise((res, rej) => {
        let done = false;
        imgMgr.fetch({ token, isHD: true, fuzzy: false }, {}, d => { done = true; res(d); });
        setTimeout(() => { if (!done) rej(new Error('timeout')); }, 20000);
      });
      const src = info && (info.src || info.originSrc);
      if (!src) return null;
      const resp = await fetch(src);
      const blob = await resp.blob();
      return { dataUrl: await blobToDataUrl(blob), mime: (info && info.mimeType) || blob.type || 'image/png' };
    } catch (e) { return null; }
  }

  async function renderWhiteboard(b) {
    try {
      const ak = b.whiteboardBlock && b.whiteboardBlock.abilityKit;
      if (!ak) return null;
      const ratioApp = ak.getRatioApp();
      if (!ratioApp || !ratioApp.app) return null;
      const bounds = ratioApp.app.application.nodeManager.getNodesBounds();
      bounds.maxX += 24; bounds.minX -= 24; bounds.maxY += 24; bounds.minY -= 24;
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const canvas = ratioApp.app.renderManager.getImageOffscreenCanvas(bounds, ratio, '#ffffff');
      if (!canvas) return null;
      let blob = null;
      if (canvas.convertToBlob) blob = await canvas.convertToBlob({ type: 'image/png' });
      else if (canvas.toBlob) blob = await new Promise(res => canvas.toBlob(res, 'image/png'));
      if (blob) return { dataUrl: await blobToDataUrl(blob), mime: 'image/png' };
      if (canvas.toDataURL) return { dataUrl: canvas.toDataURL('image/png'), mime: 'image/png' };
      return null;
    } catch (e) { return null; }
  }

  window.__webclipExtractFeishu = async function () {
    const pm = window.PageMain;
    if (!pm || !pm.blockManager || !pm.blockManager.rootBlockModel) return null;
    const bm = pm.blockManager;
    const root = bm.rootBlockModel;

    const images = {};
    let imgCounter = 0;
    function pushImage(rec) { const k = '__WBCLIP_IMG_' + (imgCounter++) + '__'; images[k] = rec; return k; }

    // heading 层级归一
    const hls = [];
    (function collect(b) { const m = /^heading(\d)$/.exec(b.type); if (m) hls.push(+m[1]); (b.children || []).forEach(collect); })(root);
    const minH = hls.length ? Math.min.apply(null, hls) : 1;

    // 单元格内联渲染：children 渲染成一行，<br> 分隔
    async function renderCellInline(cellBlock) {
      const parts = [];
      let ordIdx = 0;
      for (const c of (cellBlock.children || [])) {
        const t = c.type;
        let s = '';
        if (t === 'bullet') s = '\u2022 ' + blockText(c);
        else if (t === 'ordered') { ordIdx++; s = ordIdx + '. ' + blockText(c); }
        else if (t === 'image') {
          const tok = c.snapshot && c.snapshot.image && c.snapshot.image.token;
          const rec = await fetchByToken(c.imageManager, tok);
          if (rec) s = '![](' + pushImage(rec) + ')';
        } else s = blockText(c);
        if (s) parts.push(s);
      }
      return parts.join('<br>');
    }

    async function renderTable(b, lines) {
      const snap = b.snapshot || {};
      const rowsId = snap.rows_id || [];
      const colsId = snap.columns_id || [];
      const cellSet = snap.cell_set || {};
      if (!rowsId.length || !colsId.length) return;
      // cell_set 的 block_id 是 record id；建 record id -> cell block 映射
      const cellByRecord = {};
      for (const cell of (b.children || [])) {
        try { const recId = bm.getRecordByBlockId(cell.id).id; cellByRecord[recId] = cell; } catch (e) {}
      }
      const grid = [];
      for (const rid of rowsId) {
        const row = [];
        for (const cid of colsId) {
          const entry = cellSet[rid + cid];
          let text = '';
          if (entry && entry.block_id) {
            const cell = cellByRecord[entry.block_id];
            if (cell) text = await renderCellInline(cell);
          }
          row.push(text.replace(/\|/g, '\\|'));
        }
        grid.push(row);
      }
      if (!grid.length) return;
      const header = grid[0];
      lines.push('| ' + header.join(' | ') + ' |');
      lines.push('| ' + header.map(() => '---').join(' | ') + ' |');
      for (let i = 1; i < grid.length; i++) lines.push('| ' + grid[i].join(' | ') + ' |');
      lines.push('');
    }

    const lines = [];
    async function render(b, depth) {
      const t = b.type;
      if (t === 'page') { for (const c of b.children || []) await render(c, 0); return; }
      const hm = /^heading(\d)$/.exec(t);
      if (hm) {
        const x = blockText(b);
        if (x) lines.push('#'.repeat(Math.min(2 + (+hm[1]) - minH, 6)) + ' ' + x, '');
        for (const c of b.children || []) await render(c, depth);
        return;
      }
      switch (t) {
        case 'text': { const x = blockText(b); if (x) lines.push(x, ''); for (const c of b.children || []) await render(c, depth); break; }
        case 'bullet': { lines.push('  '.repeat(depth) + '- ' + blockText(b)); for (const c of b.children || []) await render(c, depth + 1); if (depth === 0) lines.push(''); break; }
        case 'ordered': { lines.push('  '.repeat(depth) + '1. ' + blockText(b)); for (const c of b.children || []) await render(c, depth + 1); if (depth === 0) lines.push(''); break; }
        case 'todo': { const done = b.snapshot && b.snapshot.done; lines.push('  '.repeat(depth) + '- [' + (done ? 'x' : ' ') + '] ' + blockText(b)); for (const c of b.children || []) await render(c, depth + 1); break; }
        case 'quote': case 'quote_container': {
          const collect = [];
          const x = blockText(b); if (x) collect.push(x);
          for (const c of b.children || []) { const cx = blockText(c); if (cx) collect.push(cx); }
          collect.forEach(l => l.split('\n').forEach(ln => lines.push('> ' + ln)));
          lines.push(''); break;
        }
        case 'code': { const lang = (b.snapshot && b.snapshot.language) || ''; lines.push('```' + lang, blockText(b), '```', ''); break; }
        case 'divider': lines.push('---', ''); break;
        case 'callout': { for (const c of b.children || []) await render(c, depth); break; }
        case 'image': {
          const tok = b.snapshot && b.snapshot.image && b.snapshot.image.token;
          const rec = await fetchByToken(b.imageManager, tok);
          if (rec) lines.push('![](' + pushImage(rec) + ')', '');
          break;
        }
        case 'whiteboard': {
          const rec = await renderWhiteboard(b);
          if (rec) lines.push('![](' + pushImage(rec) + ')', '');
          else lines.push('[\u98de\u4e66\u753b\u677f]', '');
          break;
        }
        case 'sheet': { const tk = b.snapshot && b.snapshot.token; lines.push(tk ? ('[[WBCLIP_EMBED:sheet:' + tk + ']]') : '[\u98de\u4e66\u7535\u5b50\u8868\u683c]', ''); break; }
        case 'bitable': { const tk = b.snapshot && b.snapshot.token; lines.push(tk ? ('[[WBCLIP_EMBED:bitable:' + tk + ']]') : '[\u98de\u4e66\u591a\u7ef4\u8868\u683c]', ''); break; }
        case 'table': await renderTable(b, lines); break;
        case 'grid': case 'grid_column': { for (const c of b.children || []) await render(c, depth); break; }
        default: { const x = blockText(b); if (x) lines.push(x, ''); for (const c of b.children || []) await render(c, depth); }
      }
    }

    await render(root, 0);

    let title = clean(document.title || '').replace(/ - \u98de\u4e66\u4e91\u6587\u6863| - Feishu Docs/g, '').trim();
    const content = lines.join('\n').replace(/\n{3,}/g, '\n\n').trim();
    return { title: title || '\u65e0\u6807\u9898', content, images };
  };
})();
