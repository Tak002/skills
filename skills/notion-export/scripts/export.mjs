#!/usr/bin/env node
/**
 * export.mjs — Notion 페이지를 하위 페이지·데이터베이스 행까지 재귀적으로 Markdown 트리로 저장한다.
 *
 * 사용법:
 *   node export.mjs <notion-url-or-id> --out <dir> [옵션]
 *
 * 옵션:
 *   --out <dir>          출력 폴더 (필수)
 *   --prefix <str>       파일명 앞에 붙일 접두어 (예: 2026-09-04-)
 *   --tags a,b           front matter tags
 *   --no-frontmatter     front matter 를 넣지 않는다
 *   --no-props           DB 행의 속성 표를 본문 위에 넣지 않는다
 *   --no-images          이미지를 내려받지 않고 원본(만료되는) URL 을 그대로 둔다
 *   --no-files           파일·동영상·PDF 를 내려받지 않는다 (기본: 서명 URL 로 내려받아 assets/ 에 저장)
 *   --max-file-mb <n>    이 크기를 넘는 파일은 건너뛴다 (기본 100)
 *   --depth <n>          재귀 깊이 (기본 10)
 *   --exclude <regex>    제목이 맞는 하위 페이지·DB 를 건너뛴다 (예: "백업|Legacy")
 *   --max-pages <n>      이 수만큼 저장하면 멈춘다
 *   --concurrency <n>    동시에 받는 페이지 수 (기본 2)
 *   --delay <ms>         페이지 요청 사이 대기 (기본 300)
 *   --resume             <out>/.notion-export.json 에 기록된 페이지는 다시 받지 않는다 (중단 재개·증분)
 *   --list               저장하지 않고 트리만 출력
 *   --token <token_v2>   비공개 페이지용 인증 쿠키 (env NOTION_TOKEN_V2, 또는 scripts/.env)
 *   --user <user-id>     notion_user_id 쿠키 (env NOTION_USER_ID, 또는 scripts/.env)
 *   --auth-file <path>   NOTION_TOKEN_V2=..., NOTION_USER_ID=... 가 든 파일 (기본 scripts/.env)
 *
 * 동작: 페이지를 받는 즉시 파일로 쓰고(내부 링크는 Notion URL), 모두 끝난 뒤 한 번 더 훑어
 * 저장된 페이지끼리의 링크를 상대 경로로 바꾸고 "## 하위 페이지" 트리를 붙인다.
 * 의존성: notion-client, notion-x-to-md (이 폴더에서 `npm install`). Node 22 이상.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { NotionAPI } from 'notion-client'
import { notionPageToMarkdown, renderCollectionProperty } from 'notion-x-to-md'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const MANIFEST = '.notion-export.json'

// ---------- 인자 ----------
function parseArgs(argv) {
  const o = { _: [], frontmatter: true, props: true, images: true, files: true, maxFileMb: 100, depth: 10, delay: 300, concurrency: 2, list: false, resume: false, tags: [] }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    const next = () => argv[++i]
    switch (a) {
      case '--out': o.out = next(); break
      case '--prefix': o.prefix = next(); break
      case '--tags': o.tags = next().split(',').map((s) => s.trim()).filter(Boolean); break
      case '--no-frontmatter': o.frontmatter = false; break
      case '--no-props': o.props = false; break
      case '--no-images': o.images = false; break
      case '--no-files': o.files = false; break
      case '--max-file-mb': o.maxFileMb = Number(next()); break
      case '--depth': o.depth = Number(next()); break
      case '--exclude': o.exclude = new RegExp(next()); break
      case '--max-pages': o.maxPages = Number(next()); break
      case '--concurrency': o.concurrency = Math.max(1, Number(next())); break
      case '--delay': o.delay = Number(next()); break
      case '--resume': o.resume = true; break
      case '--list': o.list = true; break
      case '--token': o.token = next(); break
      case '--user': o.user = next(); break
      case '--auth-file': o.authFile = next(); break
      case '-h': case '--help': o.help = true; break
      default:
        if (a.startsWith('--')) die(`알 수 없는 옵션: ${a}`)
        o._.push(a)
    }
  }
  return o
}

function die(msg, code = 1) {
  console.error(`[notion-export] ${msg}`)
  process.exit(code)
}

function loadAuth(o) {
  const file = o.authFile || path.join(HERE, '.env')
  const env = {}
  if (fs.existsSync(file)) {
    for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/)
      if (m) env[m[1]] = m[2].replace(/^["']|["']$/g, '')
    }
  }
  return {
    token: o.token || process.env.NOTION_TOKEN_V2 || env.NOTION_TOKEN_V2 || undefined,
    user: o.user || process.env.NOTION_USER_ID || env.NOTION_USER_ID || undefined,
    fileToken: process.env.NOTION_FILE_TOKEN || env.NOTION_FILE_TOKEN || undefined,
    file,
  }
}

// ---------- ID / 제목 / 파일명 ----------
function toId(input) {
  const s = input.replace(/-/g, '')
  const m = s.match(/[0-9a-f]{32}(?![0-9a-f])/gi)
  if (!m) return null
  const h = m[m.length - 1].toLowerCase() // URL 에서는 마지막 32hex 가 페이지 id
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}
const compact = (id) => id.replace(/-/g, '')

// Notion 응답은 {value: Block} 또는 {value: {value: Block, role}} 두 형태가 있다.
function rec(map, id) {
  const r = map?.[id]
  if (!r) return undefined
  const v = r.value
  return v && v.value && !v.type && !v.name ? v.value : v
}
const richText = (arr) => (Array.isArray(arr) ? arr.map((t) => (Array.isArray(t) ? t[0] : '')).join('') : '')
const blockTitle = (b) => richText(b?.properties?.title).trim()
const emojiIcon = (b) => { const i = b?.format?.page_icon; return i && !/^(https?:|\/|attachment:|notion:)/.test(i) ? i : '' }

function safeName(title, fallback) {
  let s = (title || '').replace(/[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}️]/gu, '') // 이모지
  s = s.replace(/[<>:"/\\|?*\x00-\x1f]/g, ' ').replace(/\s+/g, ' ').trim().replace(/[ .]+$/g, '')
  s = s.replace(/ /g, '-')
  if (s.length > 80) s = s.slice(0, 80).replace(/-+$/g, '')
  return s || fallback
}

function relLink(fromFile, toFile) {
  let r = path.relative(path.dirname(fromFile), toFile).split(path.sep).join('/')
  if (!r.startsWith('.')) r = './' + r
  return r.split('/').map(encodeURIComponent).join('/').replace(/%2E/g, '.').replace(/\(/g, '%28').replace(/\)/g, '%29')
}

// ---------- 페이지 안에서 하위 페이지·DB 찾기 ----------
function findChildren(recordMap, pageId) {
  const blocks = recordMap.block || {}
  const children = [] // {kind:'page', id, title, lastEdited} | {kind:'collection', id, cid, name, rows:[{id,title,lastEdited}]}
  const seenBlocks = new Set()
  const walk = (id) => {
    if (seenBlocks.has(id)) return
    seenBlocks.add(id)
    const b = rec(blocks, id)
    if (!b) return
    for (const cid of b.content || []) {
      const c = rec(blocks, cid)
      if (!c) continue
      if (c.type === 'page') {
        // 이 페이지 안에 실제로 들어 있는 하위 페이지만 (링크 블록은 alias 타입이라 여기 안 옴)
        children.push({ kind: 'page', id: c.id, title: blockTitle(c), lastEdited: c.last_edited_time })
      } else if (c.type === 'collection_view' || c.type === 'collection_view_page') {
        const colId = c.collection_id || c.format?.collection_pointer?.id
        if (!colId) continue
        const col = rec(recordMap.collection || {}, colId)
        const name = richText(col?.name).trim() || contextName(recordMap, c)
        const rows = collectionRows(recordMap, colId, c.view_ids || []).map((rid) => { const rb = rec(blocks, rid); return { id: rid, title: blockTitle(rb), lastEdited: rb?.last_edited_time } })
        children.push({ kind: 'collection', id: c.id, cid: colId, name, rows })
      } else {
        walk(cid) // column_list, column, toggle, callout, quote, tab, synced_block ...
      }
    }
  }
  walk(pageId)
  return children
}

// 이름 없는 인라인 DB: 앵커 링크 글자 → 감싸는 callout/toggle 의 제목 → 바로 앞 형제 중 제목이 있는 블록의 첫 줄
function contextName(recordMap, block) {
  const blocks = recordMap.block || {}
  const firstLine = (b) => blockTitle(b).split('\n')[0].trim()
  const anchors = anchorLinkTexts(recordMap)
  let cur = block
  for (let hop = 0; hop < 4 && cur; hop++) {
    if (anchors.has(compact(cur.id))) return anchors.get(compact(cur.id))
    const parent = rec(blocks, cur.parent_id)
    if (!parent) break
    if (['callout', 'toggle', 'quote'].includes(parent.type) && firstLine(parent)) return firstLine(parent)
    const sibs = parent.content || []
    for (let i = sibs.indexOf(cur.id) - 1; i >= 0; i--) {
      const s = rec(blocks, sibs[i])
      if (s && /^(header|sub_header|sub_sub_header|text|callout|toggle)$/.test(s.type) && firstLine(s)) return firstLine(s)
      if (s && s.type === 'divider' && parent.type === 'page') break // 구분선 너머는 다른 섹션
    }
    if (parent.type === 'page') break
    cur = parent
  }
  return ''
}

// 리치 텍스트 안의 링크([text, [["a", href]]]) 중 #32hex 앵커 → 링크 글자 (페이지당 한 번 계산)
const _anchorCache = new WeakMap()
function anchorLinkTexts(recordMap) {
  if (_anchorCache.has(recordMap)) return _anchorCache.get(recordMap)
  const map = new Map()
  for (const id of Object.keys(recordMap.block || {})) {
    const b = rec(recordMap.block, id)
    for (const seg of b?.properties?.title || []) {
      const [text, decos] = Array.isArray(seg) ? seg : []
      for (const d of decos || []) {
        if (d?.[0] !== 'a' || typeof d[1] !== 'string') continue
        const m = d[1].match(/#([0-9a-f]{32})/i)
        if (m && text?.trim() && !map.has(m[1].toLowerCase())) map.set(m[1].toLowerCase(), text.trim())
      }
    }
  }
  _anchorCache.set(recordMap, map)
  return map
}

function collectionRows(recordMap, colId, viewIds) {
  const ids = new Set()
  const q = recordMap.collection_query?.[colId] || {}
  for (const vid of [...viewIds, ...Object.keys(q)]) {
    const res = q[vid]
    if (!res) continue
    for (const v of Object.values(res)) {
      if (v && Array.isArray(v.blockIds)) v.blockIds.forEach((x) => ids.add(x))
    }
  }
  // 예비: 쿼리 결과가 없으면(보드 뷰만 있는 DB 등) recordMap 의 블록 중 parent 가 이 collection 인 것
  if (ids.size === 0) {
    for (const id of Object.keys(recordMap.block || {})) {
      const b = rec(recordMap.block, id)
      if (b?.parent_table === 'collection' && b.parent_id === colId && b.type === 'page') ids.add(id)
    }
  }
  return [...ids]
}

// ---------- 변환 전처리 ----------
const HEADER_TYPES = new Set(['header', 'sub_header', 'sub_sub_header'])

// 탭 블록: tab → (라벨 text, 자식 = 탭 내용) 구조. 변환기가 tab 을 모르므로
// 탭을 부모 목록에 펼치고, 라벨은 ### 제목(sub_sub_header)으로 바꾼다. 자식은 아래 flattenToggleHeadings 가 끌어올린다.
function flattenTabs(recordMap) {
  const blocks = recordMap.block || {}
  let n = 0
  for (const id of Object.keys(blocks)) {
    const b = rec(blocks, id)
    if (!b?.content?.length) continue
    if (!b.content.some((cid) => rec(blocks, cid)?.type === 'tab')) continue
    const next = []
    for (const cid of b.content) {
      const c = rec(blocks, cid)
      if (c?.type !== 'tab') { next.push(cid); continue }
      for (const lid of c.content || []) {
        const label = rec(blocks, lid)
        if (!label) continue
        if (label.type === 'text') {
          label.type = 'sub_sub_header'
          const icon = emojiIcon(label)
          if (icon && label.properties?.title) label.properties.title = [[icon + ' '], ...label.properties.title]
        }
        label.parent_id = b.id
        next.push(lid)
      }
      c.content = []
      n++
    }
    b.content = next
  }
  return n
}

// 토글형 제목(header/sub_header/sub_sub_header 에 자식이 달린 것)은 notion-x-to-md 가 자식을 버린다.
// 제목은 그대로 두고 자식을 부모의 content 에서 제목 바로 뒤로 끌어올린다 (중첩도 반복해서 평탄화).
function flattenToggleHeadings(recordMap) {
  const blocks = recordMap.block || {}
  let moved = 0
  for (let pass = 0; pass < 10; pass++) {
    let changed = false
    for (const id of Object.keys(blocks)) {
      const b = rec(blocks, id)
      if (!b?.content?.length) continue
      const next = []
      for (const cid of b.content) {
        next.push(cid)
        const c = rec(blocks, cid)
        if (c && HEADER_TYPES.has(c.type) && c.content?.length) {
          next.push(...c.content)
          for (const gid of c.content) { const g = rec(blocks, gid); if (g) { g.parent_id = b.id; g.parent_table = 'block' } }
          moved += c.content.length
          c.content = []
          changed = true
        }
      }
      b.content = next
    }
    if (!changed) break
  }
  return moved
}

// 스키마 없는 컬렉션(GitHub 연동 등 외부 동기화 DB)에서 변환기가 죽는다. 빈 스키마를 채워 넣는다.
function patchSchemalessCollections(recordMap) {
  let n = 0
  for (const id of Object.keys(recordMap.collection || {})) {
    const c = rec(recordMap.collection, id)
    if (c && !c.schema) { c.schema = {}; n++ }
  }
  return n
}

function dropCollectionViews(recordMap) {
  const blocks = recordMap.block || {}
  for (const id of Object.keys(blocks)) {
    const b = rec(blocks, id)
    if (!b?.content?.length) continue
    b.content = b.content.filter((cid) => { const t = rec(blocks, cid)?.type; return t !== 'collection_view' && t !== 'collection_view_page' })
  }
}

function preprocess(recordMap) {
  flattenTabs(recordMap)
  flattenToggleHeadings(recordMap)
  patchSchemalessCollections(recordMap)
}

// ---------- 사용자 멘션 ----------
// 본문·속성의 사용자 멘션([‣, [["u", id]]])은 recordMap.notion_user 에 있어야 이름으로 바뀐다. 없는 사용자는 getRecordValues 로 받아 채운다.
const userCache = new Map() // id -> record
function userIdsIn(recordMap) {
  const ids = new Set()
  const scan = (segs) => { for (const s of segs || []) for (const d of (Array.isArray(s) && s[1]) || []) if (d?.[0] === 'u' && typeof d[1] === 'string') ids.add(d[1]) }
  for (const id of Object.keys(recordMap.block || {})) {
    const b = rec(recordMap.block, id)
    for (const v of Object.values(b?.properties || {})) scan(v)
  }
  return ids
}
async function hydrateUsers(api, recordMap) {
  recordMap.notion_user = recordMap.notion_user || {}
  const missing = [...userIdsIn(recordMap)].filter((id) => !recordMap.notion_user[id])
  for (const id of missing) if (userCache.has(id)) recordMap.notion_user[id] = userCache.get(id)
  const fetchIds = missing.filter((id) => !userCache.has(id))
  if (!fetchIds.length) return
  try {
    const res = await api.getUsers(fetchIds)
    const results = res?.results || []
    fetchIds.forEach((id, i) => { const r = results[i]; if (r?.value) { recordMap.notion_user[id] = r; userCache.set(id, r) } })
  } catch (e) { console.warn(`  ! 사용자 조회 실패: ${e.message}`) }
}
function userName(recordMap, id) {
  const u = rec(recordMap.notion_user, id)
  if (!u) return ''
  return u.name || [u.given_name, u.family_name].filter(Boolean).join(' ') || u.email || ''
}

// ---------- DB 행 속성 표 ----------
const SKIP_PROP_TYPES = new Set(['title'])
function renderProps(recordMap, block) {
  if (block.parent_table !== 'collection') return ''
  const col = rec(recordMap.collection, block.parent_id)
  const schema = col?.schema
  if (!schema) return ''
  const rows = []
  for (const [key, sch] of Object.entries(schema)) {
    if (!sch || SKIP_PROP_TYPES.has(sch.type)) continue
    const raw = block.properties?.[key]
    let val = ''
    if (sch.type === 'person') {
      val = (raw || []).flatMap((s) => (Array.isArray(s) && s[1]) || []).filter((d) => d?.[0] === 'u').map((d) => userName(recordMap, d[1]) || '‣').join(', ')
    } else {
      try { val = renderCollectionProperty(sch, raw ?? [], block, recordMap, col) } catch { val = richText(raw) }
    }
    if (typeof val !== 'string') val = String(val ?? '')
    val = val.replace(/\s*\n\s*/g, ' ').replace(/\|/g, '\\|').trim()
    if (!val) continue
    rows.push(`| ${String(sch.name || key).replace(/\|/g, '\\|')} | ${val} |`)
  }
  if (!rows.length) return ''
  return `| 속성 | 값 |\n| --- | --- |\n${rows.join('\n')}\n\n`
}

// ---------- 본문 후처리 ----------
// 링크 대상에 괄호가 한 겹 들어간 URL( 예: `..._(5).png` )도 잡도록 균형 괄호를 허용
const LINK_RE = /(!?)\[([^\]]*)\]\(((?:[^()\s]|\([^()\s]*\))+)\)/g
const NOTION_URL = (id, anchor) => `https://www.notion.so/${compact(id)}${anchor ? '#' + compact(anchor) : ''}`

// 1차: Notion 내부 링크(/32hex, notion.so/..., app.notion.com/...)를 전부 정규화된 Notion URL 로
function normalizeLinks(md) {
  return md.replace(LINK_RE, (whole, bang, text, target) => {
    if (bang) return whole
    if (!/^(https?:\/\/[^/]*notion\.(so|site|com)\/|\/)/i.test(target)) return whole
    const pathPart = target.split(/[?#]/)[0]
    const idm = pathPart.replace(/-/g, '').match(/[0-9a-f]{32}(?![0-9a-f])/gi)
    let id = idm ? toId(idm[idm.length - 1]) : null
    const peek = target.match(/[?&]p=([0-9a-f]{32})/i)
    if (peek) id = toId(peek[1])
    const anchor = target.match(/#([0-9a-f]{32})/i)
    if (!id) return whole
    return `[${text}](${NOTION_URL(id, anchor ? toId(anchor[1]) : null)})`
  })
}

// 2차(마지막 패스): 저장된 페이지로의 Notion URL 을 상대 경로로
function relativizeLinks(md, fromFile, pages) {
  return md.replace(LINK_RE, (whole, bang, text, target) => {
    if (bang) return whole
    const m = target.match(/^https:\/\/www\.notion\.so\/([0-9a-f]{32})(?:#([0-9a-f]{32}))?$/i)
    if (!m) return whole
    let id = toId(m[1])
    if (m[2] && pages.has(toId(m[2]))) id = toId(m[2]) // 앵커가 저장된 페이지면 그쪽으로
    const p = pages.get(id)
    return p ? `[${text}](${relLink(fromFile, p.file)})` : whole
  })
}

// 공백으로 시작·끝나는 굵게/기울임 구간이 깨진 Markdown 을 만든다. 코드 펜스 밖에서만 정리.
function fixEmphasis(md) {
  const parts = md.split(/(```[\s\S]*?```)/)
  for (let i = 0; i < parts.length; i += 2) {
    let s = parts[i]
    for (let k = 0; k < 3; k++) {
      s = s.replace(/\*\*(\s+)([^*\n]+?)\*\*/g, '$1**$2**')
        .replace(/\*\*([^*\n]+?)(\s+)\*\*/g, '**$1**$2')
        .replace(/\*\*(\s*)\*\*/g, '$1')
        .replace(/(^|[^*])\*\*\*\*(?!\*)/g, '$1')
    }
    s = s.replace(/^[ \t>]*_{2}[ \t]*$\n?/gm, '') // 빈 버튼 등이 남긴 `__` 줄
    parts[i] = fixTableRows(s)
  }
  return parts.join('')
}

// DB 표 셀 안의 줄바꿈(여러 줄 제목 등)이 행을 쪼갠다. `|` 로 시작했는데 `|` 로 끝나지 않는 줄은 다음 줄과 합친다.
function fixTableRows(s) {
  const lines = s.split('\n')
  const out = []
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i]
    const t = line.trimEnd()
    if (/^\s*(?:>\s*)*\|/.test(t) && !t.endsWith('|')) {
      // 변환기는 행을 항상 `|` 로 끝내므로, 끝나지 않으면 셀 안 줄바꿈이다: `|` 로 끝나는 줄이 나올 때까지 합친다
      let j = i + 1
      while (j < lines.length && j - i < 30) {
        line += ' ' + lines[j].replace(/^\s*(?:>\s*)*/, '').trim()
        if (lines[j].trimEnd().endsWith('|')) break
        j++
      }
      i = Math.min(j, lines.length - 1)
    }
    out.push(line)
  }
  return out.join('\n')
}

// 비공개 페이지의 첨부(file.notion.so, app.notion.com/image)는 서명 URL 이어도 로그인 쿠키가 있어야 열린다
let AUTH_COOKIE = ''
function downloadHeaders(url) {
  const h = { 'user-agent': 'Mozilla/5.0' }
  if (AUTH_COOKIE && /^https:\/\/([^/]+\.)?notion\.(so|com)\//i.test(url)) h.cookie = AUTH_COOKIE
  return h
}
async function fetchWithRetry(url, tries = 3) {
  let last
  for (let attempt = 0; attempt < tries; attempt++) {
    if (attempt) await new Promise((res) => setTimeout(res, 800 * attempt))
    const r = await fetch(url, { headers: downloadHeaders(url) })
    if (r.ok) return r
    last = r.status
    try { await r.arrayBuffer() } catch {}
  }
  throw new Error(`HTTP ${last}`)
}

async function downloadImages(md, fromFile, assetsDir, pageId, cache) {
  const jobs = []
  md.replace(LINK_RE, (whole, bang, alt, url) => {
    if (bang && /^https?:\/\//i.test(url)) jobs.push({ whole, alt, url })
    return whole
  })
  if (!jobs.length) return md
  fs.mkdirSync(assetsDir, { recursive: true })
  let n = 0
  for (const j of jobs) {
    let local = cache.get(j.url)
    if (!local) {
      try {
        const r = await fetchWithRetry(j.url)
        const buf = Buffer.from(await r.arrayBuffer())
        const ext = guessExt(j.url, r.headers.get('content-type'))
        const name = `${compact(pageId).slice(0, 8)}-${String(++n).padStart(2, '0')}-${shortHash(j.url)}${ext}`
        local = path.join(assetsDir, name)
        fs.writeFileSync(local, buf)
        cache.set(j.url, local)
      } catch (e) {
        console.warn(`  ! 이미지 실패 (${e.message}): ${j.url.slice(0, 80)}...`)
        continue
      }
    }
    md = md.split(j.whole).join(`![${j.alt}](${relLink(fromFile, local)})`)
  }
  return md
}

// 파일·동영상·PDF·오디오 블록: recordMap.signed_urls[blockId] 로 내려받아 md 의 원본 소스를 로컬 경로로 바꾼다
const FILE_TYPES = new Set(['file', 'video', 'pdf', 'audio'])
async function downloadFiles(md, fromFile, assetsDir, recordMap, pageId, maxMb, stats) {
  const blocks = recordMap.block || {}
  for (const id of Object.keys(blocks)) {
    const b = rec(blocks, id)
    if (!b || !FILE_TYPES.has(b.type)) continue
    const source = b.properties?.source?.[0]?.[0]
    const signed = recordMap.signed_urls?.[id]
    if (!source || !signed || !md.includes(`](${source})`)) continue
    const fname = decodeURIComponent((source.startsWith('attachment:') ? source.split(':').slice(2).join(':') : source.split('?')[0].split('/').pop()) || '')
    const ext = (fname.match(/\.[A-Za-z0-9]{1,6}$/) || [''])[0].toLowerCase()
    try {
      // 비공개 첨부의 서명 URL(file.notion.so/com)은 token_v2 만으로는 403 이고 file_token 쿠키가 더 필요하다 (get-token.mjs --open).
      const r = await fetchWithRetry(signed)
      const len = Number(r.headers.get('content-length') || 0)
      if (len > maxMb * 1024 * 1024) { console.warn(`  - 파일 건너뜀 (${(len / 1048576).toFixed(0)}MB > ${maxMb}MB): ${fname}`); try { await r.arrayBuffer() } catch {} ; continue }
      const buf = Buffer.from(await r.arrayBuffer())
      if (buf.length > maxMb * 1024 * 1024) { console.warn(`  - 파일 건너뜀 (${(buf.length / 1048576).toFixed(0)}MB > ${maxMb}MB): ${fname}`); continue }
      fs.mkdirSync(assetsDir, { recursive: true })
      const local = path.join(assetsDir, `${compact(pageId).slice(0, 8)}-f-${shortHash(source)}${ext}`)
      fs.writeFileSync(local, buf)
      md = md.split(`](${source})`).join(`](${relLink(fromFile, local)})`)
      stats.files++
    } catch (e) {
      console.warn(`  ! 파일 실패 (${e.message}, ${(() => { try { return new URL(signed).host } catch { return '?' } })()}): ${fname}${/403/.test(e.message) && !AUTH_COOKIE.includes('file_token') ? ' — file_token 쿠키 없음. node get-token.mjs --open <페이지URL> --write 후 재실행' : ''}`)
      // 원본이 attachment: 면 링크가 쓸모없으므로 서명 URL 로라도 바꿔 둔다 (곧 만료)
      if (source.startsWith('attachment:')) md = md.split(`](${source})`).join(`](${signed})`)
    }
  }
  return md
}

function guessExt(url, ctype) {
  try {
    const u = new URL(url)
    let inner = u.pathname
    if (u.pathname.startsWith('/image/')) inner = decodeURIComponent(u.pathname.slice(7))
    const m = inner.match(/\.(png|jpe?g|gif|webp|svg|bmp|tiff?)(?:$|\?)/i)
    if (m) return '.' + m[1].toLowerCase().replace('jpeg', 'jpg')
  } catch {}
  const map = { 'image/png': '.png', 'image/jpeg': '.jpg', 'image/gif': '.gif', 'image/webp': '.webp', 'image/svg+xml': '.svg' }
  return map[(ctype || '').split(';')[0]] || '.png'
}

function shortHash(s) {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) }
  return (h >>> 0).toString(16).padStart(8, '0')
}

function frontMatter({ title, tags, source, id, date, icon, lastEdited }) {
  const esc = (s) => `"${String(s).replace(/"/g, '\\"')}"`
  const lines = ['---', `title: ${esc(title)}`, `date: ${date}`]
  if (tags.length) lines.push(`tags: [${tags.join(', ')}]`)
  lines.push(`source: ${source}`, `notion_id: ${id}`)
  if (icon) lines.push(`icon: ${esc(icon)}`)
  if (lastEdited) lines.push(`last_edited: ${new Date(lastEdited).toISOString()}`)
  lines.push('---', '')
  return lines.join('\n')
}

const TREE_HEADING = '\n\n## 하위 페이지\n\n'
function stripTree(md) {
  const i = md.indexOf('\n## 하위 페이지\n')
  return i >= 0 ? md.slice(0, i).replace(/\s+$/, '') : md.replace(/\s+$/, '')
}

// ---------- 메인 ----------
async function main() {
  const o = parseArgs(process.argv.slice(2))
  if (o.help || !o._[0] || (!o.out && !o.list)) {
    console.log(fs.readFileSync(fileURLToPath(import.meta.url), 'utf8').split('*/')[0].replace(/^\/\*\*\n/, '').replace(/^ \* ?/gm, ''))
    process.exit(o.help ? 0 : 1)
  }
  const rootId = toId(o._[0])
  if (!rootId) die(`페이지 id 를 찾지 못했다: ${o._[0]}`)
  const auth = loadAuth(o)
  const api = new NotionAPI({ authToken: auth.token, activeUser: auth.user, userTimeZone: 'Asia/Seoul' })
  if (auth.token) AUTH_COOKIE = `token_v2=${auth.token}${auth.user ? `; notion_user_id=${auth.user}` : ''}${auth.fileToken ? `; file_token=${auth.fileToken}` : ''}`
  const out = o.out ? path.resolve(o.out) : null
  const prefix = o.prefix || ''
  const today = new Date().toISOString().slice(0, 10)
  console.log(`[notion-export] root=${rootId} auth=${auth.token ? 'token_v2' : '없음(공개 페이지)'}${o.list ? ' (목록만)' : ` out=${out}`}${o.resume ? ' (resume)' : ''}${o.exclude ? ` exclude=${o.exclude}` : ''}`)

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  const pages = new Map() // id -> {id, title, file, dir, depth, children, parentId, kind, lastEdited}
  const usedNames = new Map() // dir -> Set(name)
  const uniq = (dir, name) => {
    const set = usedNames.get(dir) || new Set()
    usedNames.set(dir, set)
    let n = name, i = 1
    while (set.has(n.toLowerCase())) n = `${name}-${++i}`
    set.add(n.toLowerCase())
    return n
  }
  const stats = { fetched: 0, cached: 0, excluded: 0, files: 0, failed: [] }
  const imgCache = new Map()
  const assetsDir = out ? path.join(out, 'assets') : ''

  // manifest (resume)
  const manifestPath = out ? path.join(out, MANIFEST) : null
  let manifest = { version: 1, root: rootId, pages: {} }
  if (o.resume && manifestPath && fs.existsSync(manifestPath)) {
    try { manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8')) } catch { console.warn('  ! manifest 를 읽지 못해 처음부터 받는다') }
    if (manifest.root !== rootId) { console.warn('  ! manifest 의 root 가 다르다. 처음부터 받는다'); manifest = { version: 1, root: rootId, pages: {} } }
  }
  const rel = (p) => path.relative(out, p).split(path.sep).join('/')
  const abs = (p) => path.join(out, ...p.split('/'))
  let dirty = 0
  const saveManifest = (force) => {
    if (!manifestPath || o.list) return
    if (!force && ++dirty % 5 !== 0) return
    const m = { version: 1, root: rootId, savedAt: new Date().toISOString(), pages: {} }
    for (const p of pages.values()) m.pages[p.id] = { title: p.title, file: rel(p.file), dir: rel(p.dir), kind: p.kind, depth: p.depth, parentId: p.parentId, lastEdited: p.lastEdited, children: p.children }
    fs.mkdirSync(out, { recursive: true })
    fs.writeFileSync(manifestPath, JSON.stringify(m), 'utf8')
  }

  async function fetchPage(id) {
    try {
      return await api.getPage(id, { fetchRelationPages: false })
    } catch (e) {
      const msg = String(e?.message || e)
      if (/401|403|unauthorized|forbidden|Could not find|not found|restricted/i.test(msg)) {
        console.error(`[notion-export] 페이지 ${id} 를 읽지 못했다: ${msg}`)
        if (!auth.token) console.error('  → 비공개 페이지면 인증이 필요하다. node get-token.mjs --write 로 token_v2 를 얻은 뒤 다시 실행.')
        else console.error('  → token_v2 가 만료됐거나 이 페이지에 권한이 없다. node get-token.mjs --write 로 갱신.')
      }
      throw e
    }
  }

  async function convert(recordMap, title) {
    preprocess(recordMap)
    try { return await notionPageToMarkdown(recordMap) } catch (e1) {
      // 컬렉션 뷰 때문에 죽는 경우가 대부분: 뷰를 빼고 한 번 더
      dropCollectionViews(recordMap)
      try { const md = await notionPageToMarkdown(recordMap); console.warn(`  ! DB 표 없이 변환 (${e1.message})`); return md } catch (e2) {
        console.warn(`  ! markdown 변환 실패: ${e2.message}`)
        return `# ${title}\n\n> 변환 실패: ${e2.message}\n`
      }
    }
  }

  // 큐 항목: {id, dir, depth, parentId, kind, title?, lastEdited?, isRoot?}
  const queue = [{ id: rootId, dir: out || '', depth: 0, isRoot: true, parentId: null, kind: 'page' }]
  const inFlight = new Set()
  let stopped = false
  const enqueueChildren = (page, children) => {
    for (const c of children) {
      if (c.kind === 'page') {
        if (o.exclude && o.exclude.test(c.title || '')) { stats.excluded++; console.log(`${'  '.repeat(page.depth + 1)}- (제외) ${c.title}`); continue }
        page.children.push({ kind: 'page', id: c.id })
        queue.push({ id: c.id, dir: page.dir, depth: page.depth + 1, parentId: page.id, kind: 'page', title: c.title, lastEdited: c.lastEdited })
      } else {
        if (o.exclude && o.exclude.test(c.name || '')) { stats.excluded += c.rows.length; console.log(`${'  '.repeat(page.depth + 1)}[DB] (제외) ${c.name} (${c.rows.length}행)`); continue }
        const cname = uniq(page.dir, safeName(c.name, `db-${compact(c.cid).slice(-8)}`) + '/').replace(/\/$/, '')
        const cdir = path.join(page.dir, cname)
        const group = { kind: 'collection', name: c.name || cname, dir: cdir, rows: [] }
        page.children.push(group)
        console.log(`${'  '.repeat(page.depth + 1)}[DB] ${group.name} (${c.rows.length}행)`)
        for (const r of c.rows) {
          if (o.exclude && o.exclude.test(r.title || '')) { stats.excluded++; continue }
          group.rows.push(r.id)
          queue.push({ id: r.id, dir: cdir, depth: page.depth + 1, parentId: page.id, kind: 'row', title: r.title, lastEdited: r.lastEdited })
        }
      }
    }
  }

  async function processItem(item) {
    if (pages.has(item.id) || inFlight.has(item.id)) return
    if (item.depth > o.depth) return
    inFlight.add(item.id)
    try {
      // resume: manifest 에 있고 파일이 남아 있고 수정 시각이 같으면 다시 받지 않는다
      const m = manifest.pages[item.id]
      if (o.resume && !o.list && m && fs.existsSync(abs(m.file)) && (!item.lastEdited || !m.lastEdited || item.lastEdited === m.lastEdited)) {
        const page = { id: item.id, title: m.title, file: abs(m.file), dir: abs(m.dir), depth: item.depth, children: [], parentId: item.parentId, kind: m.kind, lastEdited: m.lastEdited }
        uniq(path.dirname(page.file), path.basename(page.file, '.md'))
        pages.set(item.id, page)
        stats.cached++
        console.log(`${'  '.repeat(item.depth)}- ${page.title} (cached)`)
        // 자식은 manifest 의 기록으로 이어간다
        const kids = []
        for (const c of m.children || []) {
          if (c.kind === 'page') { const cm = manifest.pages[c.id]; kids.push({ kind: 'page', id: c.id, title: cm?.title || '', lastEdited: cm?.lastEdited }) }
          else kids.push({ kind: 'collection', id: c.dir, cid: c.dir, name: c.name, rows: c.rows.map((rid) => ({ id: rid, title: manifest.pages[rid]?.title || '', lastEdited: manifest.pages[rid]?.lastEdited })), _dir: c.dir })
        }
        // 컬렉션 폴더 이름은 manifest 의 것을 그대로 쓴다
        for (const c of kids) {
          if (c.kind === 'page') { page.children.push({ kind: 'page', id: c.id }); queue.push({ id: c.id, dir: page.dir, depth: page.depth + 1, parentId: page.id, kind: 'page', title: c.title, lastEdited: c.lastEdited }) }
          else {
            const cdir = abs(c._dir); uniq(path.dirname(cdir), path.basename(cdir) + '/')
            const group = { kind: 'collection', name: c.name, dir: cdir, rows: [] }
            page.children.push(group)
            for (const r of c.rows) { group.rows.push(r.id); queue.push({ id: r.id, dir: cdir, depth: page.depth + 1, parentId: page.id, kind: 'row', title: r.title, lastEdited: r.lastEdited }) }
          }
        }
        return
      }

      const recordMap = await fetchPage(item.id)
      const blk = rec(recordMap.block, item.id)
      if (!blk) throw new Error(`응답에 페이지 블록이 없다 (권한 문제일 수 있음)`)
      const title = blockTitle(blk) || item.title || `untitled-${compact(item.id).slice(0, 8)}`
      const base = safeName(title, `untitled-${compact(item.id).slice(0, 8)}`)
      const name = uniq(item.dir, prefix + base)
      const file = path.join(item.dir, name + '.md')
      const childDir = item.isRoot ? item.dir : path.join(item.dir, uniq(item.dir, base + '/').replace(/\/$/, ''))
      const page = { id: item.id, title, file, dir: childDir, depth: item.depth, children: [], parentId: item.parentId, kind: item.kind, lastEdited: blk.last_edited_time }
      pages.set(item.id, page)
      stats.fetched++
      console.log(`${'  '.repeat(item.depth)}- ${title}`)

      // 하위 페이지 탐색은 원본 구조로 먼저
      enqueueChildren(page, findChildren(recordMap, item.id))

      if (!o.list) {
        await hydrateUsers(api, recordMap)
        let md = await convert(recordMap, title)
        if (!/^#\s/.test(md)) md = `# ${title}\n\n${md}`
        if (o.props) {
          const props = renderProps(recordMap, blk)
          if (props) md = md.replace(/^(#[^\n]*\n)\n?/, `$1\n${props}`)
        }
        md = normalizeLinks(md)
        md = fixEmphasis(md)
        if (o.images) md = await downloadImages(md, file, assetsDir, item.id, imgCache)
        if (o.files) md = await downloadFiles(md, file, assetsDir, recordMap, item.id, o.maxFileMb, stats)
        const source = NOTION_URL(item.id)
        const head = o.frontmatter ? frontMatter({ title, tags: o.tags, source, id: item.id, date: today, icon: emojiIcon(blk), lastEdited: blk.last_edited_time }) : ''
        fs.mkdirSync(path.dirname(file), { recursive: true })
        fs.writeFileSync(file, head + md.replace(/\s+$/, '') + '\n', 'utf8')
        saveManifest(false)
      }
    } catch (e) {
      stats.failed.push({ id: item.id, title: item.title, error: String(e?.message || e) })
      console.error(`${'  '.repeat(item.depth)}! 실패 ${item.title || item.id}: ${e?.message || e}`)
    } finally {
      inFlight.delete(item.id)
    }
  }

  // 워커 풀
  await new Promise((resolve) => {
    let active = 0
    const pump = () => {
      if (stopped) { if (active === 0) resolve(); return }
      while (active < o.concurrency && queue.length) {
        if (o.maxPages && pages.size + active >= o.maxPages) { stopped = true; break }
        const item = queue.shift()
        active++
        processItem(item).finally(async () => { active--; if (o.delay) await sleep(o.delay); pump() })
      }
      if (active === 0 && (!queue.length || stopped)) resolve()
    }
    pump()
  })
  if (stopped) console.log(`\n[notion-export] --max-pages ${o.maxPages} 에 도달해 멈췄다. 큐에 ${queue.length} 페이지 남음`)

  if (o.list) { console.log(`\n총 ${pages.size} 페이지${stats.excluded ? `, 제외 ${stats.excluded}` : ''}`); return }

  // 트리 색인 문자열 (페이지마다 자기 하위만)
  function treeLines(page, fromFile, indent = '') {
    const lines = []
    for (const c of page.children) {
      if (c.kind === 'page') {
        const p = pages.get(c.id); if (!p) continue
        lines.push(`${indent}- [${p.title}](${relLink(fromFile, p.file)})`)
        lines.push(...treeLines(p, fromFile, indent + '  '))
      } else {
        const rows = c.rows.map((rid) => pages.get(rid)).filter(Boolean)
        if (!rows.length) continue
        lines.push(`${indent}- 📁 ${c.name}`)
        for (const p of rows) {
          lines.push(`${indent}  - [${p.title}](${relLink(fromFile, p.file)})`)
          lines.push(...treeLines(p, fromFile, indent + '    '))
        }
      }
    }
    return lines
  }

  // 마지막 패스: 상대 링크 + 트리
  let relinked = 0
  for (const p of pages.values()) {
    if (!fs.existsSync(p.file)) continue
    const before = fs.readFileSync(p.file, 'utf8')
    let md = relativizeLinks(stripTree(before), p.file, pages)
    const tree = treeLines(p, p.file)
    if (tree.length) md += TREE_HEADING + tree.join('\n')
    md += '\n'
    if (md !== before) { fs.writeFileSync(p.file, md, 'utf8'); relinked++ }
  }
  saveManifest(true)
  const failedNote = stats.failed.length ? `, 실패 ${stats.failed.length}` : ''
  console.log(`\n[notion-export] ${pages.size} 페이지 (받음 ${stats.fetched}, 캐시 ${stats.cached}${stats.excluded ? `, 제외 ${stats.excluded}` : ''}${failedNote}) → ${out}${imgCache.size ? ` | 이미지 ${imgCache.size}` : ''}${stats.files ? ` | 파일 ${stats.files}` : ''} | 링크 갱신 ${relinked}`)
  if (stats.failed.length) for (const f of stats.failed) console.log(`  ! ${f.title || f.id}: ${f.error}`)
}

main().catch((e) => { console.error(e?.stack || e); process.exit(1) })
