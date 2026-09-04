#!/usr/bin/env node
/**
 * get-token.mjs — 브라우저에서 Notion 로그인 쿠키(token_v2, notion_user_id)를 꺼낸다.
 *
 * 원리: Chrome/Edge 를 전용 프로필 + 원격 디버깅 포트로 띄우고, DevTools Protocol 의
 * Storage.getCookies 로 httpOnly 쿠키를 읽는다. (Chrome 127+ 의 App-Bound Encryption 때문에
 * 쿠키 DB 파일을 직접 복호화하는 방식은 Windows 에서 더 이상 동작하지 않는다.)
 * 전용 프로필은 로그인 상태를 유지하므로 처음 한 번만 로그인하면 된다.
 *
 * 사용법:
 *   node get-token.mjs [--browser edge|chrome] [--port 9333] [--timeout 300] [--write] [--attach]
 *
 * 옵션:
 *   --browser   chrome(기본) | edge | <실행 파일 경로>
 *   --profile   프로필 폴더 (기본 ~/.cache/notion-export/profile-<browser>)
 *   --port      원격 디버깅 포트 (기본 9333)
 *   --timeout   로그인 기다리는 초 (기본 300)
 *   --write     결과를 이 폴더의 .env 에 저장 (NOTION_TOKEN_V2, NOTION_USER_ID). export.mjs 가 자동으로 읽는다.
 *   --attach    브라우저를 띄우지 않고 이미 --remote-debugging-port 로 떠 있는 브라우저에 붙는다.
 *   --keep      끝나도 브라우저를 닫지 않는다.
 *   --show      찾은 Notion 쿠키의 이름·도메인만 출력 (값은 출력하지 않음). 진단용.
 *   --open <url> 로그인 페이지 대신 이 URL 을 연다. 비공개 첨부를 받으려면 첨부가 있는 페이지를 열어 파일을 한 번 클릭해야
 *               file_token 쿠키가 생긴다 (NOTION_FILE_TOKEN 으로 저장). 이때는 --timeout 을 넉넉히.
 *
 * 의존성 없음. Node 22 이상 (내장 WebSocket, fetch).
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const o = { browser: 'chrome', port: 9333, timeout: 300, write: false, attach: false, keep: false, show: false, open: '' }
const argv = process.argv.slice(2)
for (let i = 0; i < argv.length; i++) {
  const a = argv[i], next = () => argv[++i]
  if (a === '--browser') o.browser = next()
  else if (a === '--profile') o.profile = next()
  else if (a === '--port') o.port = Number(next())
  else if (a === '--timeout') o.timeout = Number(next())
  else if (a === '--write') o.write = true
  else if (a === '--attach') o.attach = true
  else if (a === '--keep') o.keep = true
  else if (a === '--show') o.show = true
  else if (a === '--open') o.open = next()
  else if (a === '-h' || a === '--help') { console.log(fs.readFileSync(fileURLToPath(import.meta.url), 'utf8').split('*/')[0].replace(/^ \* ?/gm, '')); process.exit(0) }
  else { console.error(`알 수 없는 옵션: ${a}`); process.exit(1) }
}

function findBrowser(name) {
  if (/[\\/]/.test(name)) return name
  const pf = process.env['ProgramFiles'] || 'C:\\Program Files'
  const pf86 = process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)'
  const local = process.env.LOCALAPPDATA || ''
  const cands = name === 'chrome'
    ? [path.join(pf, 'Google/Chrome/Application/chrome.exe'), path.join(pf86, 'Google/Chrome/Application/chrome.exe'), path.join(local, 'Google/Chrome/Application/chrome.exe'),
       '/usr/bin/google-chrome', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']
    : [path.join(pf86, 'Microsoft/Edge/Application/msedge.exe'), path.join(pf, 'Microsoft/Edge/Application/msedge.exe'), path.join(local, 'Microsoft/Edge/Application/msedge.exe'),
       '/usr/bin/microsoft-edge', '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge']
  const hit = cands.find((p) => fs.existsSync(p))
  if (!hit) { console.error(`${name} 실행 파일을 찾지 못했다. --browser <경로> 로 지정.`); process.exit(1) }
  return hit
}

async function cdp(port, method, params = {}) {
  const info = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json()
  const ws = new WebSocket(info.webSocketDebuggerUrl)
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = (e) => rej(new Error('websocket 연결 실패')) })
  const result = await new Promise((res, rej) => {
    ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id === 1) (m.error ? rej(new Error(m.error.message)) : res(m.result)) }
    ws.send(JSON.stringify({ id: 1, method, params }))
  })
  ws.close()
  return result
}

async function readNotionCookies(port) {
  const { cookies } = await cdp(port, 'Storage.getCookies')
  const notion = cookies.filter((c) => /notion\.(so|com|site)$/.test(c.domain.replace(/^\./, '')))
  const pick = (n) => notion.find((c) => c.name === n)?.value
  // file_token: 비공개 첨부(file.notion.so/com) 다운로드용. 로그인만으로는 안 생기고 첨부를 한 번 열어야 생긴다.
  return { token: pick('token_v2'), user: pick('notion_user_id'), fileToken: pick('file_token'), names: notion.map((c) => `${c.name}@${c.domain}`) }
}

async function main() {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  let child = null
  if (!o.attach) {
    const exe = findBrowser(o.browser)
    const profile = o.profile || path.join(os.homedir(), '.cache', 'notion-export', `profile-${path.basename(exe).replace(/\.exe$/i, '')}`)
    fs.mkdirSync(profile, { recursive: true })
    const args = [`--user-data-dir=${profile}`, `--remote-debugging-port=${o.port}`, '--no-first-run', '--no-default-browser-check',
      '--disable-sync', '--disable-features=Translate', o.open || 'https://www.notion.so/login']
    child = spawn(exe, args, { stdio: 'ignore', detached: false })
    console.log(`[get-token] ${path.basename(exe)} 실행 (프로필 ${profile}, 포트 ${o.port})`)
    console.log('[get-token] 열린 창에서 Notion 에 로그인하세요. 로그인 상태는 이 프로필에 남으므로 다음부터는 자동입니다.')
  } else {
    console.log(`[get-token] 포트 ${o.port} 의 브라우저에 붙는다`)
  }

  const deadline = Date.now() + o.timeout * 1000
  let found = null, lastErr = null, connected = false
  const needFile = !!o.open // --open 이면 file_token 까지 기다린다
  while (Date.now() < deadline) {
    try {
      const c = await readNotionCookies(o.port)
      if (!connected) { connected = true; console.log(`[get-token] DevTools 연결됨. ${needFile ? '첨부를 한 번 클릭해 file_token 이 생기기를' : '로그인 완료를'} 기다리는 중...`) }
      if (c.token && (!needFile || c.fileToken)) { found = c; break }
    } catch (e) { lastErr = e }
    await sleep(2000)
  }
  if (o.show && found) console.log('[get-token] 쿠키:', found.names.join(', '))
  // 강제 종료하면 Chrome 이 쿠키를 디스크에 안 남겨 다음 실행에서 다시 로그인해야 한다. DevTools 로 정상 종료.
  if (child && !o.keep) {
    try { await Promise.race([cdp(o.port, 'Browser.close'), sleep(5000)]) } catch {}
    await sleep(1500)
    try { child.kill() } catch {}
  }
  if (!found) {
    if (connected) console.error(`[get-token] ${o.timeout}초 안에 로그인이 끝나지 않았다 (token_v2 없음). --timeout 을 늘려 다시 실행.`)
    else console.error(`[get-token] 포트 ${o.port} 의 DevTools 에 연결하지 못했다. 브라우저가 뜨지 않았거나 포트가 막혔다. 마지막 오류: ${lastErr?.message}`)
    process.exit(2)
  }
  const lines = [`NOTION_TOKEN_V2=${found.token}`, `NOTION_USER_ID=${found.user || ''}`, `NOTION_FILE_TOKEN=${found.fileToken || ''}`]
  if (!found.fileToken) console.log('[get-token] file_token 쿠키는 없음. 비공개 첨부(파일·동영상)를 받으려면 --open <첨부가 있는 페이지 URL> 로 다시 실행해 파일을 한 번 클릭.')
  if (o.write) {
    const file = path.join(HERE, '.env')
    fs.writeFileSync(file, lines.join('\n') + '\n', { encoding: 'utf8', mode: 0o600 })
    console.log(`[get-token] 저장: ${file} (git 에 올리지 말 것. 비밀번호와 같은 취급)`)
  } else {
    console.log(lines.join('\n'))
  }
}

main().catch((e) => { console.error(e?.stack || e); process.exit(1) })
