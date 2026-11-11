#!/usr/bin/env node
/**
 * Capture dashboard stills for the project video.
 *
 * Drives the locally installed Chrome over the DevTools protocol (no npm
 * packages, Node's built-in WebSocket). Two kinds of shot:
 *
 *   full   - the whole 1920x1080 register, for the "here is the dashboard" beats
 *   clip   - one panel captured on its own, for cutting in as a tight insert
 *
 *   node video/capture_shots.mjs
 *
 * Needs the receiver running (./start.sh). Writes into video/shots/.
 */
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const PORT = 9333
const PROFILE = '/tmp/codebuff-shots-chrome'
const URL_APP = 'http://127.0.0.1:8080/'
// fileURLToPath, not .pathname: the project folder name contains a space, which
// a raw URL pathname would keep as %20 and write the PNGs into a stray folder
const OUT = join(dirname(fileURLToPath(import.meta.url)), 'shots') + '/'
const W = 1920
const H = 1080

const SHOTS = [
  // live register, straight off the receiver
  { name: '01-live-overview', acts: [] },
  { name: '02-live-students-panel', acts: [], clip: 'Students' },
  { name: '03-live-timeline-panel', acts: [], clip: 'Timeline' },
  { name: '04-live-scanlog-panel', acts: [], clip: 'Scan log' },

  // the labelled eight-session set
  { name: '05-sample-session1-watch30', acts: ['sample'] },
  { name: '06-sample-session3-review63', acts: ['sample', 'next', 'next', 'expand'] },
  { name: '07-sample-session3-arithmetic', acts: ['sample', 'next', 'next', 'expand'], clip: 'Flagged runs' },
  { name: '08-sample-session5-high71', acts: ['sample', 'next', 'next', 'next', 'next'] },
  { name: '09-sample-all-sessions', acts: ['sample', 'all'] },
  { name: '10-sample-all-incidents', acts: ['sample', 'all'], clip: 'Flagged runs' },
  { name: '11-student-drawer', acts: ['sample', 'all', 'drawer'] },

  // the same physical card, rejected then accepted (live scan log)
  { name: '12-same-card-scans', acts: [], clip: 'Scan log' },
  { name: '13-same-card-denied', acts: ['denied'], clip: 'Scan log' },
  { name: '14-same-card-granted', acts: ['granted'], clip: 'Scan log' },
]

/* One injected helper. Every action is plain DOM, so it does not depend on how
   the dashboard wires its buttons, and every action returns a short note that
   gets printed - so a silently-failing step shows up in the log instead of
   quietly producing a wrong frame. */
const helper = `
  window.__act = (name) => {
    const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
    const byText = (sel, re) => [...document.querySelectorAll(sel)].find(e => re.test(norm(e.textContent)));
    const click = (sel, re) => { const el = byText(sel, re); if (el) { el.click(); return true } return false };
    const key = k => { for (const t of [document, window])
      t.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true })) };
    switch (name) {
      case 'sample': return click('button', /^sample data$/i) ? 'sample data on' : 'NO sample button';
      case 'next':   return click('button', /^next$/i) ? 'next session' : (key('ArrowRight'), 'next via key');
      case 'all':    return click('button', /^all sessions$/i) ? 'all sessions' : 'NO all-sessions control';
      case 'expand': return (click('button, summary, a, [role=button]', /show the calculation/i)
                             || click('button, summary, [role=button]', /calculation|breakdown/i))
                             ? 'arithmetic open' : 'NO calculation control';
      case 'denied':  return click('button', /^denied$/i) ? 'denied filter' : 'NO denied filter';
      case 'granted': return click('button', /^granted$/i) ? 'granted filter' : 'NO granted filter';
      case 'drawer': { const r = document.querySelector('tr.clickable, tbody tr');
                       if (r) { r.click(); return 'drawer open' } return 'NO student row' }
      default: return 'unknown action ' + name;
    }
  };

  /* Page-coordinate box of a panel, found by the text of its heading. */
  window.__box = (label) => {
    const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
    const h = [...document.querySelectorAll('h1,h2,h3')]
      .find(x => new RegExp(label, 'i').test(norm(x.textContent)));
    if (!h) return null;
    const el = h.closest('section.panel') || h.closest('section') || h.parentElement;
    const r = el.getBoundingClientRect();
    return { x: Math.max(0, Math.round(r.left + window.scrollX)),
             y: Math.max(0, Math.round(r.top + window.scrollY)),
             w: Math.round(r.width), h: Math.round(r.height) };
  };

  window.__drawerBox = () => {
    const el = document.querySelector('#drawer');
    if (!el || el.getAttribute('aria-hidden') === 'true') return null;
    const r = el.getBoundingClientRect();
    return { x: Math.max(0, Math.round(r.left + window.scrollX)),
             y: Math.max(0, Math.round(r.top + window.scrollY)),
             w: Math.round(r.width), h: Math.round(r.height) };
  };
  'ok'
`

function cdp(ws) {
  let id = 0
  const pending = new Map()
  ws.addEventListener('message', ev => {
    const msg = JSON.parse(ev.data)
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id)
      pending.delete(msg.id)
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result)
    }
  })
  return (method, params = {}) => new Promise((resolve, reject) => {
    const mid = ++id
    pending.set(mid, { resolve, reject })
    ws.send(JSON.stringify({ id: mid, method, params }))
  })
}

async function waitForChrome() {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/version`)
      if (r.ok) return await r.json()
    } catch {}
    await sleep(250)
  }
  throw new Error('Chrome did not open its debugging port')
}

async function main() {
  mkdirSync(OUT, { recursive: true })
  rmSync(PROFILE, { recursive: true, force: true })

  const chrome = spawn(CHROME, [
    '--headless=new', '--disable-gpu', '--hide-scrollbars',
    '--no-first-run', '--no-default-browser-check', '--disable-extensions',
    '--force-device-scale-factor=1',
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    `--window-size=${W},${H}`, 'about:blank',
  ], { stdio: 'ignore' })

  try {
    await waitForChrome()
    const t = await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' }).then(r => r.json())
    const ws = new WebSocket(t.webSocketDebuggerUrl)
    await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej) })
    const send = cdp(ws)

    await send('Page.enable')
    await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false })

    for (const shot of SHOTS) {
      await send('Page.navigate', { url: URL_APP })
      await sleep(2200)                                   // first render + first poll
      await send('Runtime.evaluate', { expression: helper, returnByValue: true })

      const notes = []
      for (const act of shot.acts) {
        const r = await send('Runtime.evaluate', {
          expression: `String(window.__act(${JSON.stringify(act)}))`, returnByValue: true,
        })
        notes.push(`${act} -> ${r.result?.value ?? 'THREW'}`)
        await sleep(900)                                  // let the UI settle
      }

      let params = { format: 'png', captureBeyondViewport: false }
      if (shot.clip) {
        const expr = shot.clip === 'drawer'
          ? 'window.__drawerBox()'
          : `window.__box(${JSON.stringify(shot.clip)})`
        const box = await send('Runtime.evaluate', { expression: expr, returnByValue: true })
        const b = box.result?.value
        if (!b || !b.w || !b.h) { console.log(`  ${shot.name.padEnd(32)} NO CLIP BOX for "${shot.clip}"`); continue }
        params = { format: 'png', captureBeyondViewport: true, clip: { x: b.x, y: b.y, width: b.w, height: b.h, scale: 1 } }
        notes.push(`clip ${b.w}x${b.h}`)
      }

      const png = await send('Page.captureScreenshot', params)
      writeFileSync(OUT + shot.name + '.png', Buffer.from(png.data, 'base64'))
      console.log(`  ${shot.name.padEnd(32)} ${notes.join(' · ') || 'top of page'}`)
    }

    ws.close()
  } finally {
    chrome.kill('SIGTERM')
    await sleep(400)
  }
  console.log(`\n  ${SHOTS.length} shots in video/shots/`)
}

main().catch(e => { console.error('  ! ' + e.message); process.exit(1) })
