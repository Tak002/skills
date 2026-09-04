/* 브라우저용 스캐너 (file:// 에서 📂 폴더 열기 모드가 사용).
 * 규칙은 filetypes.json → filetypes.js (build.py 가 생성) 에서 읽는다. Python 판(build.py)과 같은 결과를 내야 한다.
 * ESM/CORS 문제(file:// 에서는 type=module 이 막힘)를 피하려고 전역 객체 ReportScan 에 노출한다. */
(function (g) {
  'use strict';
  const R = g.REPORT_FILETYPES;
  if (!R) { console.error('filetypes.js 가 없습니다. python _viewer/build.py 를 한 번 실행하세요.'); g.ReportScan = null; return; }
  const EXT_TYPE = {};
  for (const [t, exts] of Object.entries(R.types)) for (const e of exts) if (!(e in EXT_TYPE)) EXT_TYPE[e] = t;
  const CODE_EXT = R.code;
  const BODY_MAX = R.bodyMaxBytes;
  const HEAD_BYTES = R.headBytes;
  const SKIP_DIR_NAMES = new Set(R.skipDirs);
  const SKIP_ROOT_FILES = new Set(R.skipRootFiles);

  const extOf = name => { const i = name.lastIndexOf('.'); return i < 0 ? '' : name.slice(i).toLowerCase(); };
  const isHidden = name => R.hiddenPrefixes.some(p => name.startsWith(p)) || SKIP_DIR_NAMES.has(name);

  function unquote(s) {
    s = s.trim();
    if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) return s.slice(1, -1);
    return s;
  }

  /** 아주 단순한 YAML front matter 파서 (key: value, 배열 [a, b], 리스트 - a) */
  function parseFrontMatter(text) {
    const m = /^---\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/.exec(text);
    if (!m) return { meta: {}, body: text };
    const meta = {};
    let lastKey = null;
    for (const raw of m[1].split(/\r?\n/)) {
      const line = raw.trimEnd();
      if (!line.trim() || line.trim().startsWith('#')) continue;
      const li = /^\s+-\s+(.*)$/.exec(line) || /^-\s+(.*)$/.exec(line);
      if (li && lastKey) {
        if (!Array.isArray(meta[lastKey])) meta[lastKey] = meta[lastKey] ? [meta[lastKey]] : [];
        meta[lastKey].push(unquote(li[1]));
        continue;
      }
      const kv = /^([A-Za-z0-9_-]+)\s*:\s*(.*)$/.exec(line);
      if (!kv) continue;
      lastKey = kv[1];
      let v = kv[2].trim();
      if (v.startsWith('[') && v.endsWith(']')) v = v.slice(1, -1).split(',').map(s => unquote(s)).filter(Boolean);
      else if (v === 'true') v = true;
      else if (v === 'false') v = false;
      else v = unquote(v);
      meta[lastKey] = v;
    }
    return { meta, body: text.slice(m[0].length) };
  }

  function firstHeading(body) {
    const m = /^#\s+(.+?)\s*#*\s*$/m.exec(body);
    return m ? m[1].trim() : null;
  }

  function toDate(v) {
    if (!v) return null;
    const m = /(\d{4})[-./](\d{1,2})[-./](\d{1,2})/.exec(String(v));
    return m ? `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}` : null;
  }

  const isoDate = d => new Date(d).toISOString().slice(0, 10);
  const stripBom = s => s.replace(/^﻿/, '');

  /** 파일 하나를 노드로. readText 는 필요할 때만 호출되는 () => Promise<string> */
  async function fileNode({ name, rel, size, mtimeMs, readText }) {
    const ext = extOf(name);
    const i = rel.lastIndexOf('/');
    const base = { name, path: rel, dir: i < 0 ? '' : rel.slice(0, i), ext, size, mtime: new Date(mtimeMs).toISOString() };
    const fallbackDate = toDate(name) || isoDate(mtimeMs);
    const t = EXT_TYPE[ext];
    if (t === 'md') {
      const text = stripBom(await readText()).replace(/\r\n/g, '\n');
      const { meta, body } = parseFrontMatter(text);
      const title = meta.title || firstHeading(body) || name.replace(/\.[^.]+$/, '');
      const date = toDate(meta.date) || fallbackDate;
      const tags = Array.isArray(meta.tags) ? meta.tags : meta.tags ? [String(meta.tags)] : [];
      return { type: 'md', ...base, title, date, tags, meta, body };
    }
    if (t === 'html') {
      const text = await readText();
      const m = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(text);
      const title = m ? m[1].trim().replace(/\s+/g, ' ') : name.replace(/\.[^.]+$/, '');
      return { type: 'html', ...base, title, date: fallbackDate, tags: [] };
    }
    if (t === 'json' && size <= BODY_MAX) {
      const text = stripBom(await readText());
      let title = name;
      try { const j = JSON.parse(text); if (j && typeof j === 'object' && !Array.isArray(j) && typeof j.title === 'string') title = j.title; } catch {}
      return { type: 'json', ...base, title, date: fallbackDate, tags: [], body: text };
    }
    if (t === 'text' && size <= BODY_MAX) {
      const text = stripBom(await readText()).replace(/\r\n/g, '\n');
      return { type: 'text', ...base, title: name, date: fallbackDate, tags: [], body: text };
    }
    if (CODE_EXT[ext] && size <= BODY_MAX) {
      const text = stripBom(await readText()).replace(/\r\n/g, '\n');
      return { type: 'code', ...base, title: name, date: fallbackDate, tags: [], lang: CODE_EXT[ext], body: text };
    }
    if (t !== undefined || CODE_EXT[ext]) return { type: 'file', ...base, title: name, date: fallbackDate, tags: [] };
    return null;
  }

  /** listDir(relDir) → [{name, kind:'dir'|'file', size, mtimeMs, readText}] 를 주면 트리를 만든다. */
  async function walk(listDir, relDir = '') {
    const children = [];
    for (const ent of await listDir(relDir)) {
      if (isHidden(ent.name)) continue;
      const rel = relDir ? `${relDir}/${ent.name}` : ent.name;
      if (ent.kind === 'dir') children.push(await walk(listDir, rel));
      else {
        if (!relDir && SKIP_ROOT_FILES.has(ent.name)) continue;
        const n = await fileNode({ ...ent, rel });
        if (n) children.push(n);
      }
    }
    children.sort((a, b) => {
      if ((a.type === 'dir') !== (b.type === 'dir')) return a.type === 'dir' ? -1 : 1;
      return a.name.localeCompare(b.name, 'ko');
    });
    const j = relDir.lastIndexOf('/');
    return { type: 'dir', name: relDir ? relDir.slice(j + 1) : '', path: relDir, children };
  }

  function stats(root) {
    const s = { md: 0, html: 0, json: 0, text: 0, code: 0, file: 0, dir: -1 };
    (function count(n) { s[n.type]++; if (n.type === 'dir') n.children.forEach(count); })(root);
    return s;
  }

  g.ReportScan = { parseFrontMatter, firstHeading, toDate, fileNode, walk, stats, HEAD_BYTES };
})(typeof globalThis !== 'undefined' ? globalThis : window);
