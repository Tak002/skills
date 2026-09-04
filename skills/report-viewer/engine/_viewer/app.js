/* report viewer
 * 세 가지 데이터 소스를 지원한다.
 *   server : _viewer/serve.py 가 떠 있을 때 (http://127.0.0.1:포트). 등록된 어떤 폴더든 색인 없이 실시간으로 읽는다.
 *   data   : file:// 로 열었을 때 _viewer/build.py 가 만든 _viewer/data.js
 *   live   : file:// 에서 📂 폴더 열기 (File System Access API)
 * 설정(title, categories)은 서버 모드에선 /api/ping, 파일 모드에선 data.js 의 config 에서 온다.
 */
(() => {
  'use strict';

  const $ = (s, el = document) => el.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const main = $('#main');
  const tocEl = $('#toc');
  const layout = $('#layout');

  // ---------- 상태 ----------
  let MODE = 'data';            // 'server' | 'data' | 'live'
  let DATA = null;
  let byPath = new Map();
  let allFiles = [];
  let CONFIG = { title: 'Reports' };
  const SERVER = { roots: [], rootId: 'report', rootName: 'Reports' };

  let treeJson = '';               // 마지막으로 읽은 트리의 원본 (본문을 받아 노드가 바뀌어도 비교가 흔들리지 않게 따로 보관)
  function setData(d) {
    DATA = d; byPath = new Map(); allFiles = [];
    treeJson = d ? JSON.stringify(d.root) : '';
    if (!d) { updateFoot(); return; }
    if (d.config) CONFIG = { ...CONFIG, ...d.config };
    (function index(n) {
      byPath.set(n.path, n);
      if (n.type === 'dir') n.children.forEach(index); else allFiles.push(n);
    })(d.root);
    updateFoot();
  }

  const isReadme = n => n.type === 'md' && /^readme\.md$/i.test(n.name);
  const isAttach = n => n.type === 'file';
  const byDateDesc = (a, b) => (b.date || '').localeCompare(a.date || '') || (b.mtime || '').localeCompare(a.mtime || '');
  const reportsIn = d => d.children.reduce((s, c) => s + (c.type === 'dir' ? reportsIn(c) : (isAttach(c) || isReadme(c) ? 0 : 1)), 0);
  const latestIn = d => d.children.reduce((m, c) => { const v = c.type === 'dir' ? latestIn(c) : (isAttach(c) ? '' : c.date); return v > m ? v : m; }, '');
  const fmtSize = b => b < 1024 ? b + ' B' : b < 1048576 ? (b / 1024).toFixed(1) + ' KB' : (b / 1048576).toFixed(1) + ' MB';
  const fmtTime = iso => {
    if (!iso) return '';
    const d = new Date(iso); if (isNaN(d)) return iso;
    const p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  };

  function resolvePath(baseDir, rel) {
    const parts = baseDir ? baseDir.split('/') : [];
    for (const seg of rel.split('/')) {
      if (!seg || seg === '.') continue;
      if (seg === '..') parts.pop(); else parts.push(seg);
    }
    return parts.join('/');
  }
  const isExternal = h => /^[a-z][a-z0-9+.-]*:/i.test(h) || h.startsWith('//');
  const encPath = p => p.split('/').map(encodeURIComponent).join('/');
  const route = p => MODE === 'server' ? `#/~${encodeURIComponent(SERVER.rootId)}/${encPath(p)}` : `#/${encPath(p)}`;
  const rawUrl = p => MODE === 'server' ? `/raw/${encodeURIComponent(SERVER.rootId)}/${encPath(p)}` : encPath(p);
  const rootLabel = () => MODE === 'server' ? SERVER.rootName : (CONFIG.title || 'Reports');

  async function api(path, opts) {
    const r = await fetch(path, { cache: 'no-store', ...opts });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `${r.status} ${r.statusText}`);
    return j;
  }
  /** 서버 모드에서는 트리에 본문이 없다. 필요할 때 받아서 노드에 채운다. */
  async function ensureBody(node) {
    if (!node || node.body !== undefined || !DATA || !DATA.lazy) return node;
    const full = await api(`/api/file?root=${encodeURIComponent(SERVER.rootId)}&path=${encodeURIComponent(node.path)}`);
    if (full && full.body !== undefined) Object.assign(node, full);
    else node.body = '';
    return node;
  }

  // ---------- 테마 ----------
  const THEME_KEY = 'report-viewer-theme';
  function getTheme() {
    try { return localStorage.getItem(THEME_KEY) || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'); }
    catch { return 'light'; }
  }
  function applyTheme(t) {
    document.documentElement.dataset.theme = t;
    $('#css-md-light').disabled = t !== 'light';
    $('#css-md-dark').disabled = t !== 'dark';
    $('#css-hl-light').disabled = t !== 'light';
    $('#css-hl-dark').disabled = t !== 'dark';
    $('#theme-btn').textContent = t === 'dark' ? '☀️' : '🌙';
  }
  applyTheme(getTheme());
  $('#theme-btn').addEventListener('click', () => {
    const t = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(THEME_KEY, t); } catch {}
    applyTheme(t);
    navigate(); // mermaid 테마 등 재렌더
  });
  $('#nav-btn').addEventListener('click', () => document.body.classList.toggle('nav-open'));

  // ---------- 지연 로딩 ----------
  const loaded = {};
  const loadScript = src => loaded[src] ||= new Promise((res, rej) => {
    const s = document.createElement('script'); s.src = src; s.onload = res; s.onerror = () => rej(new Error('load fail: ' + src));
    document.head.appendChild(s);
  });
  function loadCss(href) {
    if (document.querySelector(`link[href="${href}"]`)) return;
    const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = href; document.head.appendChild(l);
  }

  // ---------- marked 설정 ----------
  marked.use(markedGfmHeadingId.gfmHeadingId());
  marked.use({
    gfm: true,
    renderer: {
      code(tok, langArg) {
        const text = typeof tok === 'object' ? tok.text : tok;
        const lang = ((typeof tok === 'object' ? tok.lang : langArg) || '').trim().split(/\s+/)[0];
        if (lang === 'mermaid') return `<pre class="mermaid">${esc(text)}</pre>`;
        const html = lang && hljs.getLanguage(lang) ? hljs.highlight(text, { language: lang }).value : esc(text);
        return `<div class="code-block"><button class="copy-btn" type="button">복사</button><pre><code class="hljs${lang ? ' language-' + esc(lang) : ''}">${html}</code></pre></div>`;
      },
    },
  });

  // 코드 블록을 보호한 채 수식을 추출 → 자리표시자로 치환
  function extractMath(src, inlineDollar) {
    const code = [];
    let s = src.replace(/```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`/g, m => { code.push(m); return `QQCP${code.length - 1}QQ`; });
    const found = [];
    const pats = [[/\$\$([\s\S]+?)\$\$/g, true], [/\\\[([\s\S]+?)\\\]/g, true], [/\\\(([\s\S]+?)\\\)/g, false]];
    if (inlineDollar) pats.push([/(?<![\\$\w])\$(?!\s)([^$\n]+?)(?<!\s)\$(?![\w$])/g, false]);
    for (const [re, display] of pats) s = s.replace(re, (_m, tex) => { found.push({ tex, display }); return `MATHPH${found.length - 1}X`; });
    s = s.replace(/QQCP(\d+)QQ/g, (_m, i) => code[+i]);
    return { src: s, found };
  }

  async function renderMarkdownInto(el, node, { stripTitle } = {}) {
    await ensureBody(node);
    let body = node.body || '';
    if (stripTitle) body = body.replace(/^\s*#\s+[^\n]*\n?/, '');
    const { src, found } = extractMath(body, node.meta && node.meta.math === true);
    let html = DOMPurify.sanitize(marked.parse(src), { ADD_ATTR: ['align'] });
    if (found.length) {
      loadCss('_viewer/vendor/katex.min.css');
      await loadScript('_viewer/vendor/katex.min.js');
      html = html.replace(/MATHPH(\d+)X/g, (_m, i) => katex.renderToString(found[+i].tex, { displayMode: found[+i].display, throwOnError: false }));
    }
    el.innerHTML = html;

    // 링크/이미지 경로 해석
    el.querySelectorAll('a[href]').forEach(a => {
      const href = a.getAttribute('href');
      if (href.startsWith('#')) {
        a.addEventListener('click', e => {
          e.preventDefault();
          let id = href.slice(1); try { id = decodeURIComponent(id); } catch {}
          const t = el.querySelector(`[id="${CSS.escape(id)}"]`);
          if (t) t.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        return;
      }
      if (isExternal(href)) { a.target = '_blank'; a.rel = 'noopener'; return; }
      let [p, hash] = href.split('#');
      try { p = decodeURIComponent(p); } catch {}
      const target = resolvePath(node.dir, p);
      if (byPath.has(target)) a.setAttribute('href', route(target));
      else { a.setAttribute('href', rawUrl(target) + (hash ? '#' + hash : '')); a.target = '_blank'; }
    });
    el.querySelectorAll('img[src]').forEach(img => {
      let s = img.getAttribute('src');
      if (isExternal(s) || s.startsWith('data:')) return;
      try { s = decodeURIComponent(s); } catch {}
      img.src = rawUrl(resolvePath(node.dir, s));
    });

    // mermaid
    const diagrams = el.querySelectorAll('pre.mermaid');
    if (diagrams.length) {
      try {
        await loadScript('_viewer/vendor/mermaid.min.js');
        if (!el.isConnected) return; // 스크립트를 받는 사이에 다른 화면으로 이동함
        mermaid.initialize({ startOnLoad: false, theme: document.documentElement.dataset.theme === 'dark' ? 'dark' : 'default', securityLevel: 'loose' });
        await mermaid.run({ nodes: diagrams });
      } catch (e) { if (el.isConnected) console.error(e); }
    }
  }

  // ---------- 공통 조각 ----------
  function breadcrumb(node) {
    const segs = node.path ? node.path.split('/') : [];
    let acc = '';
    const parts = [`<a href="${route('')}">${esc(rootLabel())}</a>`];
    segs.forEach((s, i) => {
      acc = acc ? acc + '/' + s : s;
      parts.push('<span class="sep">/</span>');
      parts.push(i === segs.length - 1 ? `<span class="cur">${esc(s)}</span>` : `<a href="${route(acc)}">${esc(s)}</a>`);
    });
    return `<div class="crumb">${parts.join('')}</div>`;
  }

  const badgeOf = f => (f.type === 'code' || f.type === 'file') && f.ext ? f.ext.slice(1) : f.type;

  function fileTable(files, showDir) {
    if (!files.length) return '';
    const rows = files.map(f => `<tr>
      <td class="t"><a href="${route(f.path)}">${esc(f.title || f.name)}</a></td>
      <td class="n"><span class="badge ${esc(f.type)}">${esc(badgeOf(f))}</span></td>
      ${showDir ? `<td class="n"><a href="${route(f.dir)}">${esc(f.dir || '/')}</a></td>` : ''}
      <td class="n">${esc(f.date || '')}</td>
      <td>${(f.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('')}</td>
      <td class="n">${fmtSize(f.size)}</td></tr>`).join('');
    return `<table class="files"><thead><tr><th>제목</th><th>형식</th>${showDir ? '<th>폴더</th>' : ''}<th>날짜</th><th>태그</th><th>크기</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  function docHead(node, extraMeta = [], extraHtml = '') {
    const m = node.meta || {};
    const bits = [
      `📅 ${esc(node.date)}`,
      `<a href="${route(node.dir)}">📁 ${esc(node.dir || '/')}</a>`,
      m.author ? `✍️ ${esc(m.author)}` : '',
      (node.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join(''),
      ...extraMeta,
      `수정 ${fmtTime(node.mtime)}`,
      `<a href="${rawUrl(node.path)}" target="_blank">원본 ${esc(node.ext)}</a>`,
    ].filter(Boolean).map(b => `<span>${b}</span>`).join('');
    return `<header class="doc-head"><h1>${esc(node.title || node.name)}</h1><div class="doc-meta">${bits}</div>${extraHtml}</header>`;
  }

  function setToc(visible) {
    tocEl.hidden = !visible;
    layout.classList.toggle('no-toc', !visible);
    if (!visible) tocEl.innerHTML = '';
  }

  let spy = null;
  function buildToc(article, node) {
    if (!article || !article.isConnected) return; // 본문을 받는 사이에 다른 화면으로 이동한 경우
    const hs = [...article.querySelectorAll('h1, h2, h3')].filter(h => h.id);
    if (hs.length < 2) { setToc(false); return; }
    setToc(true);
    tocEl.innerHTML = '<div class="toc-title">목차</div>' + hs.map(h =>
      `<a class="toc-${h.tagName.toLowerCase()}" href="${route(node.path)}" data-id="${esc(h.id)}" title="${esc(h.textContent)}">${esc(h.textContent)}</a>`).join('');
    tocEl.querySelectorAll('a').forEach(a => a.addEventListener('click', e => {
      e.preventDefault();
      const t = document.getElementById(a.dataset.id);
      if (t) t.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }));
    if (spy) spy.disconnect();
    spy = new IntersectionObserver(entries => {
      for (const en of entries) if (en.isIntersecting) {
        tocEl.querySelectorAll('a').forEach(a => a.classList.toggle('active', a.dataset.id === en.target.id));
        break;
      }
    }, { root: main, rootMargin: '0px 0px -75% 0px', threshold: 0 });
    hs.forEach(h => spy.observe(h));
  }

  // ---------- 화면 ----------
  async function renderDir(node) {
    main.className = '';
    const readme = node.children.find(isReadme);
    const dirs = node.children.filter(c => c.type === 'dir');
    const files = node.children.filter(c => c.type !== 'dir' && c !== readme).sort(byDateDesc);
    let html = breadcrumb(node) + `<h1 class="dir-title">${node.path ? '📁 ' + esc(node.name) : '📄 ' + esc(rootLabel())}</h1>`;
    if (!node.path && DATA.truncated) html += `<div class="notice">⚠ 파일이 너무 많아 앞부분만 읽었습니다. 더 작은 폴더를 등록하는 것이 좋습니다.</div>`;
    if (dirs.length) html += `<section class="cards">${dirs.map(d => {
      const label = !node.path && CONFIG.categories && CONFIG.categories[d.name] ? `<div class="card-desc">${esc(CONFIG.categories[d.name])}</div>` : '';
      return `<a class="card" href="${route(d.path)}"><div class="card-name">📁 ${esc(d.name)}</div>${label}<div class="card-meta">파일 ${reportsIn(d)}개 · 최근 ${latestIn(d) || '-'}</div></a>`;
    }).join('')}</section>`;
    if (files.length) html += `<h2 class="sec">파일</h2>` + fileTable(files);
    if (!node.path && dirs.length) {
      const recent = allFiles.filter(f => !isAttach(f) && !isReadme(f)).sort(byDateDesc).slice(0, 10);
      html += `<h2 class="sec">최근 파일</h2>` + (recent.length ? fileTable(recent, true) : '<div class="empty">아직 파일이 없습니다.</div>');
    } else if (!dirs.length && !files.length) html += '<div class="empty">비어 있는 폴더입니다.</div>';
    if (readme) html += `<article class="markdown-body readme" id="readme"></article>`;
    main.innerHTML = html;
    setToc(false);
    const el = $('#readme');
    if (readme && el) await renderMarkdownInto(el, readme);
  }

  async function renderMd(node) {
    main.className = '';
    await ensureBody(node);
    main.innerHTML = breadcrumb(node) + docHead(node) + `<article class="markdown-body" id="doc"></article>`;
    const firstH1 = /^\s*#\s+(.+?)\s*#*\s*$/m.exec(node.body || '');
    const stripTitle = !!firstH1 && firstH1[1].trim() === node.title && (node.body || '').trimStart().startsWith('#');
    const doc = $('#doc');
    await renderMarkdownInto(doc, node, { stripTitle });
    buildToc(doc, node);
  }

  function renderHtml(node) {
    main.className = 'frame-mode';
    setToc(false);
    // sandbox: 등록된 폴더의 html 이 뷰어와 같은 출처로 실행되어 서버 API 를 부르지 못하게 출처를 끊는다 (스크립트·폼·팝업은 허용)
    main.innerHTML = `<div class="frame-bar">${breadcrumb(node).replace('class="crumb"', 'class="crumb" style="margin:0"')}<span style="margin-left:auto"></span><a href="${rawUrl(node.path)}" target="_blank">새 탭에서 열기 ↗</a></div>
      <iframe class="html-frame" src="${rawUrl(node.path)}" title="${esc(node.title)}" sandbox="allow-scripts allow-forms allow-popups allow-modals"></iframe>`;
  }

  // JSON: 접을 수 있는 트리 + 하이라이트된 텍스트
  const JSON_TREE_MAX_CHILDREN = 500;
  function jsonTree(v, key, depth) {
    const k = key === undefined ? '' : `<span class="jk">${esc(typeof key === 'number' ? key : JSON.stringify(key))}</span><span class="jc">: </span>`;
    if (v === null || typeof v !== 'object') {
      const cls = v === null ? 'jnull' : typeof v === 'string' ? 'jstr' : typeof v === 'number' ? 'jnum' : 'jbool';
      return `<div class="jrow">${k}<span class="${cls}">${esc(JSON.stringify(v))}</span></div>`;
    }
    const isArr = Array.isArray(v);
    const entries = isArr ? v.map((x, i) => [i, x]) : Object.entries(v);
    const summary = `${k}<span class="jc">${isArr ? '[' : '{'}</span><span class="jcnt">${entries.length}${isArr ? '개' : '키'}</span><span class="jc">${isArr ? ']' : '}'}</span>`;
    if (!entries.length) return `<div class="jrow">${summary}</div>`;
    const shown = entries.slice(0, JSON_TREE_MAX_CHILDREN);
    const more = entries.length > shown.length ? `<div class="jrow jmore">… ${entries.length - shown.length}개 더 있음 (텍스트 보기에서 확인)</div>` : '';
    return `<details class="jnode"${depth < 2 ? ' open' : ''}><summary>${summary}</summary><div class="jkids">${shown.map(([kk, vv]) => jsonTree(vv, kk, depth + 1)).join('')}${more}</div></details>`;
  }
  async function renderJson(node) {
    main.className = '';
    setToc(false);
    await ensureBody(node);
    let parsed, err = null;
    try { parsed = JSON.parse(node.body); } catch (e) { err = e.message; }
    const pretty = err ? node.body : JSON.stringify(parsed, null, 2);
    const hl = pretty.length > 300000 ? esc(pretty) : hljs.highlight(pretty, { language: 'json' }).value;
    const tabs = err ? '' : `<div class="jtabs"><button type="button" class="jtab active" data-v="tree">트리</button><button type="button" class="jtab" data-v="text">텍스트</button><button type="button" class="jtab jexp" data-v="expand">모두 펼치기</button></div>`;
    main.innerHTML = breadcrumb(node) + docHead(node, [fmtSize(node.size), err ? `<span class="jerr">⚠ JSON 파싱 실패: ${esc(err)}</span>` : ''], tabs) + `
      <div id="jview-tree" class="jtree"${err ? ' hidden' : ''}>${err ? '' : jsonTree(parsed, undefined, 0)}</div>
      <div id="jview-text" class="markdown-body"${err ? '' : ' hidden'}><div class="code-block"><button class="copy-btn" type="button">복사</button><pre><code class="hljs language-json">${hl}</code></pre></div></div>`;
    main.querySelectorAll('.jtab:not(.jexp)').forEach(b => b.addEventListener('click', () => {
      main.querySelectorAll('.jtab:not(.jexp)').forEach(x => x.classList.toggle('active', x === b));
      $('#jview-tree').hidden = b.dataset.v !== 'tree';
      $('#jview-text').hidden = b.dataset.v !== 'text';
    }));
    const exp = main.querySelector('.jexp');
    if (exp) exp.addEventListener('click', () => {
      const all = main.querySelectorAll('#jview-tree details');
      const anyClosed = [...all].some(d => !d.open);
      all.forEach(d => d.open = anyClosed);
      exp.textContent = anyClosed ? '모두 접기' : '모두 펼치기';
    });
  }

  // 텍스트(.txt/.log) 와 코드: 줄 번호 + 줄바꿈 토글 (+ 코드는 하이라이트)
  const TEXT_MAX_LINES = 20000;
  /** hljs 결과를 줄 단위로 나누되, 줄을 넘어가는 span 을 닫고 다시 연다 */
  function splitHighlighted(html) {
    const out = []; let open = [];
    for (const line of html.split('\n')) {
      const stack = [...open];
      const re = /<span[^>]*>|<\/span>/g; let m;
      while ((m = re.exec(line))) { if (m[0] === '</span>') stack.pop(); else stack.push(m[0]); }
      out.push(open.join('') + line + '</span>'.repeat(stack.length));
      open = stack;
    }
    return out;
  }
  async function renderText(node) {
    main.className = '';
    setToc(false);
    await ensureBody(node);
    const body = node.body || '';
    const isCode = node.type === 'code';
    const lines = body.split('\n');
    let htmlLines;
    if (isCode && body.length <= 500000 && node.lang && hljs.getLanguage(node.lang)) htmlLines = splitHighlighted(hljs.highlight(body, { language: node.lang }).value);
    else htmlLines = lines.map(esc);
    const shown = htmlLines.slice(0, TEXT_MAX_LINES);
    const wrapKey = isCode ? 'report-viewer-wrap-code' : 'report-viewer-wrap';
    let wrap = !isCode;
    try { const v = localStorage.getItem(wrapKey); if (v) wrap = v === 'on'; } catch {}
    const tabs = `<div class="jtabs"><button type="button" class="jtab twrap${wrap ? ' active' : ''}">줄바꿈</button><button type="button" class="jtab tcopy">복사</button>${isCode ? `<span class="muted" style="align-self:center">${esc(node.lang)}</span>` : ''}</div>`;
    main.innerHTML = breadcrumb(node) + docHead(node, [`${lines.length.toLocaleString()}줄 · ${fmtSize(node.size)}`], tabs) + `
      <div class="ttext${wrap ? ' wrap' : ''}${isCode ? ' hljs' : ''}" id="ttext">${shown.map((l, i) => `<div class="tl"><span class="tn">${i + 1}</span><span class="tc">${l || ' '}</span></div>`).join('')}${lines.length > shown.length ? `<div class="tl jmore"><span class="tn"></span><span class="tc">… ${(lines.length - shown.length).toLocaleString()}줄 더 있음 (원본 파일에서 확인)</span></div>` : ''}</div>`;
    main.querySelector('.twrap').addEventListener('click', e => {
      const on = $('#ttext').classList.toggle('wrap');
      e.currentTarget.classList.toggle('active', on);
      try { localStorage.setItem(wrapKey, on ? 'on' : 'off'); } catch {}
    });
    main.querySelector('.tcopy').addEventListener('click', e => {
      const b = e.currentTarget;
      const done = () => { b.textContent = '복사됨'; setTimeout(() => b.textContent = '복사', 1200); };
      if (navigator.clipboard) navigator.clipboard.writeText(body).then(done, () => {});
    });
  }

  function renderFile(node) {
    main.className = '';
    setToc(false);
    main.innerHTML = breadcrumb(node) + `<div class="empty"><h2>📎 ${esc(node.name)}</h2><p>${fmtSize(node.size)} · 수정 ${fmtTime(node.mtime)}</p><p><a href="${rawUrl(node.path)}" target="_blank">파일 열기 ↗</a></p></div>`;
  }

  function renderNotFound(path) {
    main.className = '';
    setToc(false);
    const hint = MODE === 'server' ? '파일이 새로 생겼다면 🔄 버튼으로 폴더를 다시 읽으세요.' : '새 파일이라면 <code>python _viewer/build.py</code> 를 실행하고 새로고침하세요.';
    main.innerHTML = `<div class="empty"><h2>찾을 수 없음</h2><p><code>${esc(path)}</code> 가 없습니다. ${hint}</p><p><a href="${route('')}">홈으로</a></p></div>`;
  }

  // ---------- 사이드바 ----------
  function treeHtml(dir, active, depth) {
    const dirs = dir.children.filter(c => c.type === 'dir');
    const files = dir.children.filter(c => c.type !== 'dir').sort(byDateDesc);
    let html = dirs.map(d => {
      const open = depth === 0 || active === d.path || active.startsWith(d.path + '/');
      return `<div class="tnode${open ? ' open' : ''}"><div class="trow"><button class="tgl" type="button" aria-label="펼치기">▶</button><a href="${route(d.path)}" class="${active === d.path ? 'active' : ''}">📁 ${esc(d.name)}</a><span class="cnt">${reportsIn(d)}</span></div><div class="tkids">${treeHtml(d, active, depth + 1)}</div></div>`;
    }).join('');
    if (files.length) html += `<ul class="tfiles">${files.map(f =>
      `<li class="tfile"><a class="f-${f.type}${active === f.path ? ' active' : ''}" href="${route(f.path)}" title="${esc(f.name)}">${esc(f.title || f.name)}</a></li>`).join('')}</ul>`;
    return html;
  }
  function renderSidebar(active) {
    $('#tree').innerHTML = DATA ? treeHtml(DATA.root, active, 0) : '';
  }
  $('#tree').addEventListener('click', e => {
    const b = e.target.closest('.tgl');
    if (b) b.closest('.tnode').classList.toggle('open');
  });
  function updateFoot() {
    const f = $('#side-foot');
    if (!DATA) { f.innerHTML = '색인 없음'; return; }
    if (MODE === 'server') f.innerHTML = `🖥 서버 모드 · <b title="${esc(DATA.rootPath || '')}">${esc(DATA.rootName || '')}</b><br><span title="${esc(DATA.rootPath || '')}">${esc(DATA.rootPath || '')}</span><br>읽은 시각 ${fmtTime(DATA.generatedAt)}`;
    else if (DATA.live) f.innerHTML = `📂 실시간 모드: <b>${esc(DATA.folder)}</b><br>읽은 시각 ${fmtTime(DATA.generatedAt)} · 창을 다시 활성화하면 자동 갱신`;
    else f.innerHTML = `색인 생성: ${fmtTime(DATA.generatedAt)}<br>갱신: start.cmd(서버) · <code>python _viewer/build.py</code> · 📂 폴더 열기`;
  }

  // ---------- 실시간 폴더 모드 (File System Access API, file:// 전용) ----------
  const liveBtn = $('#live-btn');
  const liveExit = $('#live-exit');
  const hasFsApi = typeof window.showDirectoryPicker === 'function' && !!window.ReportScan;
  let liveHandle = null;
  let pendingHandle = null;

  function idb() {
    return new Promise((res, rej) => {
      const r = indexedDB.open('report-viewer', 1);
      r.onupgradeneeded = () => r.result.createObjectStore('handles');
      r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
    });
  }
  const idbOp = (mode, fn) => idb().then(db => new Promise((res, rej) => {
    const req = fn(db.transaction('handles', mode).objectStore('handles'));
    req.onsuccess = () => res(req.result); req.onerror = () => rej(req.error);
  }));
  const idbGet = k => idbOp('readonly', s => s.get(k));
  const idbSet = (k, v) => idbOp('readwrite', s => s.put(v, k));
  const idbDel = k => idbOp('readwrite', s => s.delete(k));

  async function scanHandle(handle) {
    const listDir = async rel => {
      let dir = handle;
      for (const seg of rel ? rel.split('/') : []) dir = await dir.getDirectoryHandle(seg);
      const out = [];
      for await (const [name, h] of dir.entries()) {
        if (h.kind === 'directory') out.push({ name, kind: 'dir' });
        else { const f = await h.getFile(); out.push({ name, kind: 'file', size: f.size, mtimeMs: f.lastModified, readText: () => f.text() }); }
      }
      return out;
    };
    const root = await ReportScan.walk(listDir, '');
    return { generatedAt: new Date().toISOString(), root, live: true, folder: handle.name, config: CONFIG };
  }
  function updateLiveUi() {
    if (MODE === 'server' || !hasFsApi) { liveBtn.hidden = true; liveExit.hidden = true; return; }
    liveBtn.hidden = false;
    if (liveHandle) { liveBtn.textContent = '🔄 다시 읽기'; liveBtn.title = '폴더를 다시 스캔'; liveExit.hidden = false; }
    else if (pendingHandle) { liveBtn.textContent = `📂 ${pendingHandle.name} 다시 연결`; liveBtn.title = '저장된 폴더에 다시 연결'; liveExit.hidden = false; }
    else { liveBtn.textContent = '📂 폴더 열기'; liveBtn.title = '폴더를 직접 읽기 (빌드 불필요)'; liveExit.hidden = true; }
  }
  async function enterLive(handle, { silent } = {}) {
    try {
      const data = await scanHandle(handle);
      liveHandle = handle; pendingHandle = null; MODE = 'live';
      setData(data);
      idbSet('dir', handle).catch(() => {});
      updateLiveUi();
      await navigate();
    } catch (e) {
      console.error(e);
      if (!silent) alert('폴더를 읽지 못했습니다: ' + e.message);
    }
  }
  async function rescanLive() {
    if (!liveHandle) return;
    try {
      const data = await scanHandle(liveHandle);
      const same = DATA && treeJson === JSON.stringify(data.root);
      if (same) return;
      setData(data);
      await navigate({ keepScroll: true });
    } catch (e) { console.error(e); }
  }
  async function exitLive() {
    liveHandle = null; pendingHandle = null; MODE = 'data';
    idbDel('dir').catch(() => {});
    setData(window.REPORT_DATA || null);
    updateLiveUi();
    await navigate();
  }
  async function tryRestoreLive() {
    if (!hasFsApi) return;
    let h = null;
    try { h = await idbGet('dir'); } catch {}
    if (!h) return;
    try {
      if ((await h.queryPermission({ mode: 'read' })) === 'granted') { await enterLive(h, { silent: true }); return; }
    } catch {}
    pendingHandle = h; updateLiveUi();
  }
  liveBtn.addEventListener('click', async () => {
    try {
      if (liveHandle) return rescanLive();
      if (pendingHandle) {
        if ((await pendingHandle.requestPermission({ mode: 'read' })) === 'granted') return enterLive(pendingHandle);
        pendingHandle = null; updateLiveUi();
      }
      const h = await window.showDirectoryPicker({ id: 'report-root', mode: 'read' });
      await enterLive(h);
    } catch (e) { if (e.name !== 'AbortError') alert(e.message); }
  });
  liveExit.addEventListener('click', exitLive);

  // ---------- 서버 모드 ----------
  const rootUi = $('#root-ui'), rootSel = $('#root-sel'), rootDel = $('#root-del');
  const LAST_ROOT_KEY = 'report-viewer-root';

  async function loadRoots() {
    const j = await api('/api/roots');
    SERVER.roots = j.roots;
    rootSel.innerHTML = SERVER.roots.map(r => `<option value="${esc(r.id)}" title="${esc(r.path)}"${r.exists ? '' : ' disabled'}>${esc(r.name)}${r.exists ? '' : ' (없음)'}</option>`).join('');
    rootSel.value = SERVER.rootId;
    const cur = SERVER.roots.find(r => r.id === SERVER.rootId);
    rootDel.hidden = !cur || !!cur.default;
  }
  async function loadRoot(id, { quiet } = {}) {
    const r = SERVER.roots.find(x => x.id === id);
    if (!r) throw new Error('등록되지 않은 폴더: ' + id);
    const d = await api(`/api/tree?root=${encodeURIComponent(id)}`);
    SERVER.rootId = id; SERVER.rootName = d.rootName || r.name;
    try { localStorage.setItem(LAST_ROOT_KEY, id); } catch {}
    rootSel.value = id;
    rootDel.hidden = !!r.default;
    $('#brand').textContent = '📄 ' + SERVER.rootName;
    $('#brand').href = route('');
    document.title = SERVER.rootName;
    const changed = !DATA || DATA.rootId !== id || treeJson !== JSON.stringify(d.root);
    if (changed || !quiet) setData(d);   // 변한 게 없으면 현재 노드(받아 둔 본문 포함)를 그대로 둔다
    return changed || !quiet;
  }
  async function refreshTree() {
    if (MODE !== 'server') return rescanLive();
    // 창을 다시 활성화했을 때 호출된다. 폴더가 실제로 바뀐 경우에만 다시 그리고, 그때도 스크롤 위치는 유지한다.
    try { if (await loadRoot(SERVER.rootId, { quiet: true })) await navigate({ keepScroll: true }); } catch (e) { console.error(e); }
  }
  rootSel.addEventListener('change', () => { location.hash = `#/~${encodeURIComponent(rootSel.value)}/`; });
  rootDel.addEventListener('click', async () => {
    const r = SERVER.roots.find(x => x.id === SERVER.rootId);
    if (!r || r.default || !confirm(`"${r.name}" 폴더를 목록에서 뺄까요? (파일은 지워지지 않습니다)`)) return;
    await api(`/api/roots/${encodeURIComponent(r.id)}`, { method: 'DELETE' });
    await loadRoots();
    location.hash = '#/~report/';
  });
  $('#root-refresh').addEventListener('click', refreshTree);

  // 폴더 추가 대화상자
  const modal = $('#modal'); let fbPath = '';
  async function fbOpen(path) {
    let j;
    try { j = await api(`/api/browse?path=${encodeURIComponent(path || '')}`); }
    catch (e) { $('#fb-list').innerHTML = `<div class="fb-empty">${esc(e.message)}</div>`; return; }
    fbPath = j.path;
    $('#fb-input').value = j.path;
    $('#fb-drives').innerHTML = j.drives.map(d => `<button type="button" data-p="${esc(d)}" class="${j.path.toUpperCase().startsWith(d.toUpperCase()) ? 'active' : ''}">${esc(d)}</button>`).join('');
    const sep = j.path.includes('\\') ? '\\' : '/';
    const segs = j.path ? j.path.replace(/[\\/]+$/, '').split(/[\\/]/) : [];
    let acc = '';
    $('#fb-crumb').innerHTML = j.path
      ? `<a data-p="${esc(j.parent || '')}" title="상위 폴더">⬆</a><span class="sep">&nbsp;</span>` + segs.map((s, i) => { acc = i === 0 ? (s || sep) + (s.endsWith(':') ? sep : '') : acc.replace(/[\\/]$/, '') + sep + s; return i === segs.length - 1 ? `<span class="cur">${esc(s || sep)}</span>` : `<a data-p="${esc(acc)}">${esc(s || sep)}</a>`; }).join(`<span class="sep">${esc(sep)}</span>`)
      : '<span class="cur">드라이브 또는 바로가기를 고르세요</span>';
    $('#fb-list').innerHTML = j.dirs.length ? j.dirs.map(d => `<div class="fb-item${d.hidden ? ' hidden' : ''}" data-p="${esc(d.path)}">📁 ${esc(d.name)}</div>`).join('') : '<div class="fb-empty">하위 폴더가 없습니다. 아래 버튼으로 이 폴더를 추가할 수 있습니다.</div>';
    $('#fb-add').disabled = !j.path;
  }
  $('#root-add').addEventListener('click', () => { modal.hidden = false; $('#fb-name').value = ''; fbOpen(''); });
  $('#modal-close').addEventListener('click', () => modal.hidden = true);
  modal.addEventListener('click', e => { if (e.target === modal) modal.hidden = true; });
  $('#fb-go').addEventListener('click', () => fbOpen($('#fb-input').value.trim()));
  $('#fb-input').addEventListener('keydown', e => { if (e.key === 'Enter') fbOpen(e.target.value.trim()); });
  $('#fb-drives').addEventListener('click', e => { const b = e.target.closest('button'); if (b) fbOpen(b.dataset.p); });
  $('#fb-crumb').addEventListener('click', e => { const a = e.target.closest('a'); if (a) fbOpen(a.dataset.p); });
  $('#fb-list').addEventListener('click', e => { const d = e.target.closest('.fb-item'); if (d) fbOpen(d.dataset.p); });
  $('#fb-add').addEventListener('click', async () => {
    if (!fbPath) return;
    try {
      const j = await api('/api/roots', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: fbPath, name: $('#fb-name').value.trim() || null }) });
      modal.hidden = true;
      await loadRoots();
      location.hash = `#/~${encodeURIComponent(j.added.id)}/`;
      if (currentRoute().rootId === j.added.id) navigate();
    } catch (e) { alert(e.message); }
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !modal.hidden) modal.hidden = true; });

  async function initServer() {
    if (!/^https?:$/.test(location.protocol)) return false;
    let p;
    try { p = await api('/api/ping'); } catch { return false; }
    if (!p || p.app !== 'report-viewer') return false;
    MODE = 'server';
    if (p.config) CONFIG = { ...CONFIG, ...p.config };
    rootUi.hidden = false;
    await loadRoots();
    let want = currentRoute().rootId;
    try { want = want || localStorage.getItem(LAST_ROOT_KEY); } catch {}
    if (!SERVER.roots.some(r => r.id === want && r.exists)) want = 'report';
    await loadRoot(want);
    return true;
  }

  // ---------- 검색 ----------
  function hitHtml(f, snippet) {
    return `<div class="hit"><div class="ht"><a href="${route(f.path)}">${esc(f.title || f.name)}</a> <span class="badge ${esc(f.type)}">${esc(badgeOf(f))}</span></div><div class="hp">${esc(f.dir || '/')} · ${esc(f.date || '')} ${(f.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('')}</div><div class="hs">${snippet}</div></div>`;
  }
  const markQ = (text, q) => esc(text).replace(new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), m => `<mark>${m}</mark>`);
  let searchSeq = 0;
  async function doSearch(q) {
    q = q.trim();
    if (!q) { navigate(); return; }
    const seq = ++searchSeq;
    let hits;
    if (MODE === 'server') {
      main.className = ''; setToc(false);
      main.innerHTML = `<h1 class="dir-title">🔍 “${esc(q)}” 검색 중…</h1>`;
      try { hits = (await api(`/api/search?root=${encodeURIComponent(SERVER.rootId)}&q=${encodeURIComponent(q)}`)).hits.map(h => ({ f: h, snippet: h.snippet ? markQ(h.snippet, q) : '' })); }
      catch (e) { hits = []; console.error(e); }
      if (seq !== searchSeq) return;
    } else {
      const lq = q.toLowerCase();
      hits = allFiles.filter(f => !isAttach(f)).map(f => {
        const t = (f.title || f.name).toLowerCase(), b = (f.body || '').toLowerCase(), tags = (f.tags || []).join(' ').toLowerCase();
        let score = 0;
        if (t.includes(lq)) score += 10;
        if (tags.includes(lq)) score += 5;
        const i = b.indexOf(lq);
        if (i >= 0) score += 1;
        if (!score) return null;
        let snippet = '';
        if (i >= 0) {
          const s = Math.max(0, i - 70), e = Math.min(b.length, i + lq.length + 90);
          snippet = (s > 0 ? '…' : '') + markQ(f.body.slice(s, e), q) + (e < b.length ? '…' : '');
        }
        return { f, score, snippet };
      }).filter(Boolean).sort((a, b) => b.score - a.score || byDateDesc(a.f, b.f));
    }
    main.className = '';
    setToc(false);
    main.innerHTML = `<h1 class="dir-title">🔍 “${esc(q)}” 검색 결과 ${hits.length}건</h1>` + (hits.map(h => hitHtml(h.f, h.snippet)).join('') || '<div class="empty">일치하는 파일이 없습니다.</div>');
  }
  let searchTimer = null;
  $('#search').addEventListener('input', e => { clearTimeout(searchTimer); searchTimer = setTimeout(() => doSearch(e.target.value), 250); });
  document.addEventListener('keydown', e => {
    if (e.key === '/' && !/input|textarea|select/i.test(e.target.tagName)) { e.preventDefault(); $('#search').focus(); }
    if (e.key === 'Escape' && e.target === $('#search')) { e.target.value = ''; navigate(); e.target.blur(); }
  });

  // ---------- 코드 복사 ----------
  main.addEventListener('click', e => {
    const b = e.target.closest('.copy-btn');
    if (!b) return;
    const code = b.parentElement.querySelector('code');
    const text = code ? code.textContent : '';
    const done = () => { b.textContent = '복사됨'; setTimeout(() => b.textContent = '복사', 1200); };
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, () => {});
    else { const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); done(); }
  });

  // ---------- 라우터 ----------
  /** '#/path' 또는 '#/~rootId/path' */
  function currentRoute() {
    let h = location.hash;
    if (!h.startsWith('#/')) return { rootId: null, path: '' };
    h = h.slice(2);
    let rootId = null;
    if (h.startsWith('~')) {
      const i = h.indexOf('/');
      rootId = i < 0 ? h.slice(1) : h.slice(1, i);
      h = i < 0 ? '' : h.slice(i + 1);
      try { rootId = decodeURIComponent(rootId); } catch {}
    }
    try { h = decodeURIComponent(h); } catch {}
    return { rootId, path: h.replace(/^\/+|\/+$/g, '') };
  }
  let navSeq = 0;
  async function navigate({ keepScroll = false } = {}) {
    const seq = ++navSeq;
    const savedTop = keepScroll ? main.scrollTop : 0;
    const { rootId, path } = currentRoute();
    document.body.classList.remove('nav-open');
    $('#search').value = '';
    if (MODE === 'server' && rootId && rootId !== SERVER.rootId) {
      try { await loadRoot(rootId); }
      catch (e) { renderSidebar(''); main.innerHTML = `<div class="empty"><h2>폴더를 열 수 없음</h2><p>${esc(e.message)}</p><p><a href="#/~report/">기본 폴더로</a></p></div>`; return; }
      if (seq !== navSeq) return;
    }
    renderSidebar(path);
    if (!DATA) {
      main.className = ''; setToc(false);
      main.innerHTML = `<div class="empty"><h2>색인이 없습니다</h2><p>가장 편한 방법은 <code>start.cmd</code>(Windows) 또는 <code>start.sh</code> 를 실행해 서버 모드로 여는 것입니다 (색인 불필요, 아무 폴더나 열람).</p><p>또는 터미널에서 <code>python _viewer/build.py</code> 를 실행한 뒤 새로고침${hasFsApi ? '하거나, 상단의 <b>📂 폴더 열기</b> 로 폴더를 직접 읽으세요.' : '하세요.'}</p></div>`;
      return;
    }
    const node = byPath.get(path);
    if (!node) { renderNotFound(path); return; }
    document.title = (node.path ? (node.title || node.name) + ' · ' : '') + rootLabel();
    try {
      if (node.type === 'dir') await renderDir(node);
      else if (node.type === 'md') await renderMd(node);
      else if (node.type === 'html') renderHtml(node);
      else if (node.type === 'json') await renderJson(node);
      else if (node.type === 'text' || node.type === 'code') await renderText(node);
      else renderFile(node);
    } catch (e) {
      console.error(e);
      main.innerHTML = breadcrumb(node) + `<div class="empty"><h2>열 수 없음</h2><p>${esc(e.message)}</p></div>`;
    }
    if (seq === navSeq) main.scrollTop = savedTop;
  }
  window.addEventListener('hashchange', () => navigate());

  // 창을 다시 활성화하면 폴더를 다시 읽는다 (서버/실시간 모드)
  let lastRefresh = 0;
  const maybeRefresh = () => { if (Date.now() - lastRefresh < 1500) return; lastRefresh = Date.now(); if (MODE === 'server') refreshTree(); else if (MODE === 'live') rescanLive(); };
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') maybeRefresh(); });
  window.addEventListener('focus', maybeRefresh);

  // ---------- 시작 ----------
  (async () => {
    if (await initServer()) { updateLiveUi(); await navigate(); return; }
    setData(window.REPORT_DATA || null);
    $('#brand').textContent = '📄 ' + (CONFIG.title || 'Reports');
    document.title = CONFIG.title || 'Reports';
    updateLiveUi();
    await navigate();
    tryRestoreLive();
  })();
})();
