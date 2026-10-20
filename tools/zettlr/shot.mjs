// Drives a Zettlr started with --remote-debugging-port over the DevTools protocol (Node's
// own WebSocket, no packages): opens the sample note, shows the sidebar and writes a PNG of
// the main window. Run by render.sh:  node shot.mjs PORT NOTE OUT.png
import fs from 'fs';

const [port, note, out] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));

let page;
for (let i = 0; i < 60 && !page; i++) {
  try {
    const pages = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
    page = pages.find(p => p.type === 'page' && p.url.includes('main_window'));
  } catch { /* not up yet */ }
  if (!page) await sleep(500);
}
if (!page) { console.error('shot: no Zettlr main window'); process.exit(1); }

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((ok, fail) => { ws.onopen = ok; ws.onerror = fail; });
let id = 0;
const waiting = new Map();
ws.onmessage = e => {
  const m = JSON.parse(e.data);
  if (waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
};
const call = (method, params = {}) => new Promise(r => {
  const i = ++id; waiting.set(i, r); ws.send(JSON.stringify({ id: i, method, params }));
});
const value = async expr => (await call('Runtime.evaluate', { expression: expr, returnByValue: true })).result?.result?.value;
// the centre of the first element the expression finds, or null
const where = async expr => value(`(() => { const e = ${expr}; if (!e) return null;
  const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()`);
const click = async ([x, y]) => {
  await call('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
  await call('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
  await call('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
  await sleep(600);
};
const byText = text => `[...document.querySelectorAll('#file-tree span.display-text')].find(e => e.textContent.trim() === ${JSON.stringify(text)})`;

for (let i = 0; i < 40 && !(await where(byText(note))); i++) await sleep(500);
const file = await where(byText(note));
if (!file) { console.error(`shot: ${note} isn't in the file tree`); process.exit(1); }
await click(file);
const folder = await where(byText('notes'));
if (folder) await click(folder);
if (!(await value(`!!document.querySelector('#sidebar')`))) {
  const toggle = await where(`document.querySelector('#toolbar-toggle-sidebar')`);
  if (toggle) await click(toggle);
}
await click([5, 5]); // away from the controls, so none shows its hover state
await sleep(1500);
const shot = await call('Page.captureScreenshot', { format: 'png' });
fs.writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
ws.close();
