/**
 * audit.mjs — 표본 감사. 루트 + 직접 자식 페이지 + DB 마다 앞 N행(최대 60 페이지)을 받아
 * 블록 종류·DB 속성 스키마·뷰 종류를 모으고, notionPageToMarkdown 결과에 각 블록의 글자가
 * 남아 있는지(서식 없는 가장 긴 세그먼트 20자) 대조한다. 결과는 JSON 파일 + 콘솔 요약.
 *
 *   node audit.mjs <notion-url-or-id> <out.json> [DB당 행수=2] [제외 정규식=백업]
 *
 * 인증은 export.mjs 와 같이 이 폴더의 .env (NOTION_TOKEN_V2, NOTION_USER_ID) 를 읽는다. 없으면 공개 페이지만.
 */
import fs from 'node:fs'
import { NotionAPI } from 'notion-client'
import { notionPageToMarkdown } from 'notion-x-to-md'

const [rootIn, outJson, rowsPerDb = '2', skipRe = '백업'] = process.argv.slice(2)
if (!rootIn || !outJson) { console.error('usage: node audit.mjs <url> <out.json> [rowsPerDb] [skipRegex]'); process.exit(1) }
let env = {}
try { env = Object.fromEntries(fs.readFileSync(new URL('./.env', import.meta.url), 'utf8').split(/\r?\n/).filter((l) => l.includes('=')).map((l) => l.split(/=(.*)/s).slice(0, 2))) } catch {}
const api = new NotionAPI({ authToken: env.NOTION_TOKEN_V2, activeUser: env.NOTION_USER_ID, userTimeZone: 'Asia/Seoul' })
const toId = (s) => { const h = s.replace(/-/g, '').match(/[0-9a-f]{32}/gi).pop().toLowerCase(); return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}` }
const rec = (map, id) => { const v = map?.[id]?.value; return v && v.value && !v.type && !v.name ? v.value : v }
const rt = (a) => (Array.isArray(a) ? a.map((t) => (Array.isArray(t) ? t[0] : '')).join('') : '')
const HEADERS = new Set(['header', 'sub_header', 'sub_sub_header'])

function flatten(rm) {
  const blocks = rm.block || {}
  for (let pass = 0; pass < 10; pass++) {
    let changed = false
    for (const id of Object.keys(blocks)) {
      const b = rec(blocks, id); if (!b?.content?.length) continue
      const next = []
      for (const cid of b.content) { next.push(cid); const c = rec(blocks, cid); if (c && HEADERS.has(c.type) && c.content?.length) { next.push(...c.content); c.content = []; changed = true } }
      b.content = next
    }
    if (!changed) break
  }
}

// 페이지에 속한 블록 전부 (하위 페이지/DB 안으로는 안 들어감)
function pageBlocks(rm, pid) {
  const out = []; const seen = new Set()
  const walk = (id, depth) => {
    if (seen.has(id)) return; seen.add(id)
    const b = rec(rm.block, id); if (!b) { out.push({ id, type: 'MISSING', depth }); return }
    if (id !== pid) out.push({ id, type: b.type, depth, b })
    if (id !== pid && (b.type === 'page' || b.type === 'collection_view_page')) return
    for (const c of b.content || []) walk(c, depth + 1)
  }
  walk(pid, 0)
  return out
}

const result = { pages: [], queryErrors: [], schemas: {}, views: {} }
const origError = console.error
console.error = (...a) => { const s = a.map(String).join(' '); if (/collectionQuery error/.test(s)) result.queryErrors.push(s.slice(0, 200)); else origError(...a) }

const queue = [{ id: toId(rootIn), depth: 0, via: 'root' }]
const seenPages = new Set()
while (queue.length && result.pages.length < 60) {
  const it = queue.shift(); if (seenPages.has(it.id)) continue; seenPages.add(it.id)
  let rm; try { rm = await api.getPage(it.id) } catch (e) { result.pages.push({ id: it.id, error: String(e.message) }); continue }
  const root = rec(rm.block, it.id); if (!root) { result.pages.push({ id: it.id, error: 'no root block' }); continue }
  const title = rt(root.properties?.title) || '(untitled)'
  const blocks = pageBlocks(rm, it.id)
  const types = {}; for (const x of blocks) types[x.type] = (types[x.type] || 0) + 1
  // 하위 페이지 / DB
  const children = [], dbs = []
  for (const x of blocks) {
    if (x.type === 'page') children.push(x.id)
    if (x.type === 'collection_view' || x.type === 'collection_view_page') {
      const cid = x.b.collection_id || x.b.format?.collection_pointer?.id
      const col = rec(rm.collection, cid)
      const name = rt(col?.name) || '(unnamed)'
      const schema = Object.fromEntries(Object.values(col?.schema || {}).map((p) => [p.name, p.type]))
      result.schemas[name] = schema
      const viewTypes = (x.b.view_ids || []).map((v) => { const cv = rec(rm.collection_view, v); return cv ? `${cv.type}${cv.query2?.group_by ? '(grouped)' : ''}${cv.query2?.filter?.filters?.length ? '(filtered)' : ''}` : 'missing' })
      result.views[name] = viewTypes
      const q = rm.collection_query?.[cid] || {}; const rows = new Set()
      for (const v of Object.values(q)) for (const r of Object.values(v)) if (r?.blockIds) r.blockIds.forEach((i) => rows.add(i))
      dbs.push({ name, cid, rows: rows.size, linked: !!x.b.format?.collection_pointer && !x.b.collection_id, viewTypes })
      if (!new RegExp(skipRe).test(name) && !new RegExp(skipRe).test(title)) [...rows].slice(0, Number(rowsPerDb)).forEach((r) => queue.push({ id: r, depth: it.depth + 1, via: `db:${name}` }))
    }
  }
  if (!new RegExp(skipRe).test(title)) children.forEach((c) => queue.push({ id: c, depth: it.depth + 1, via: 'page' }))
  // 변환 + 손실 대조
  flatten(rm)
  let md = ''; try { md = await notionPageToMarkdown(rm) } catch (e) { md = ''; result.pages.push({ id: it.id, title, mdError: String(e.message) }) }
  const norm = (s) => s.replace(/\s+/g, '')
  const mdN = norm(md)
  const lost = []
  for (const x of blocks) {
    const t = rt(x.b?.properties?.title).trim()
    if (!t || t.length < 3) continue
    const probe = norm(t).slice(0, 24)
    if (!mdN.includes(probe)) lost.push({ type: x.type, text: t.slice(0, 40) })
  }
  // DB 행이면 title 외 속성 값이 md 에 있는지
  let propCheck = null
  if (it.via.startsWith('db:')) {
    const col = rec(rm.collection, root.parent_id); const schema = col?.schema || {}
    const props = Object.entries(root.properties || {}).filter(([k]) => k !== 'title').map(([k, v]) => ({ name: schema[k]?.name, type: schema[k]?.type, value: rt(v).slice(0, 30) })).filter((p) => p.value)
    propCheck = { total: props.length, inMd: props.filter((p) => p.value && mdN.includes(norm(p.value).slice(0, 12))).length, sample: props.slice(0, 6) }
  }
  const page = { id: it.id, title, via: it.via, depth: it.depth, blocks: blocks.length, types, dbs, childPages: children.length, mdChars: md.length, lost, propCheck,
    icon: root.format?.page_icon ? 1 : 0, cover: root.format?.page_cover ? 1 : 0 }
  result.pages.push(page)
  console.log(`[${result.pages.length}] ${title} (${it.via}) blocks=${blocks.length} md=${md.length} lost=${lost.length}${propCheck ? ` props=${propCheck.inMd}/${propCheck.total}` : ''}`)
  await new Promise((r) => setTimeout(r, 150))
}
fs.writeFileSync(outJson, JSON.stringify(result, null, 2))

// 요약
const agg = {}; const lostAgg = {}
for (const p of result.pages) { for (const [t, n] of Object.entries(p.types || {})) agg[t] = (agg[t] || 0) + n; for (const l of p.lost || []) lostAgg[l.type] = (lostAgg[l.type] || 0) + 1 }
console.log('\n== block types (count) ==\n' + Object.entries(agg).sort((a, b) => b[1] - a[1]).map(([t, n]) => `${t}=${n}`).join(', '))
console.log('\n== text lost by type ==\n' + Object.entries(lostAgg).sort((a, b) => b[1] - a[1]).map(([t, n]) => `${t}=${n}`).join(', '))
console.log('\n== property types in schemas ==\n' + [...new Set(Object.values(result.schemas).flatMap((s) => Object.values(s)))].join(', '))
console.log('\n== view types ==\n' + Object.entries(result.views).map(([n, v]) => `${n}: ${v.join('|')}`).join('\n'))
console.log(`\n== query errors: ${result.queryErrors.length}`)
const pc = result.pages.filter((p) => p.propCheck); console.log(`== DB rows sampled: ${pc.length}, property values found in md: ${pc.reduce((a, p) => a + p.propCheck.inMd, 0)}/${pc.reduce((a, p) => a + p.propCheck.total, 0)}`)
