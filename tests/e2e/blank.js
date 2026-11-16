// A blank "Untitled car" saved on the device by an earlier version: it must not come back, and one on screen can be removed.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
  await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 240)));
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  const chips = () => p.locator('.garage .chip:not(.add)').evaluateAll((els) => els.map((e) => (e.classList.contains('on') ? '*' : '') + e.textContent.trim()));
  const title = async () => (await p.locator('.head .title').innerText().catch(() => '')).replace(/\s+/g, ' ');
  const saved = () => p.evaluate(() => new Promise((done) => { const r = indexedDB.open('dealsheet', 1); r.onsuccess = () => { const s = r.result.transaction('garage', 'readonly').objectStore('garage'); const k = s.getAllKeys(); k.onsuccess = () => { const i = s.get('index'); i.onsuccess = () => done({ keys: k.result.filter((x) => String(x).startsWith('car:')), order: (i.result || {}).order }); }; }; }));
  await p.goto('http://localhost:8766/', { waitUntil: 'networkidle' }); await p.waitForTimeout(12000);
  // what his phone holds: a real car, then a blank one that was on screen, and the sample hidden
  await p.evaluate(() => new Promise((done) => {
    localStorage.setItem('dealsheet.prefs', JSON.stringify({ hide_sample: true, v: 2 }));
    const r = indexedDB.open('dealsheet', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('garage');
    r.onsuccess = () => { const tx = r.result.transaction('garage', 'readwrite'), s = tx.objectStore('garage');
      s.put({ deal: { car: { year: 2019, make: 'Porsche', model: '911', price: 98000 }, comps: [], offer: {}, summary: '', message: '' }, photo: '', photos: {} }, 'car:aaaa1111');
      s.put({ deal: { car: {}, comps: [], offer: {}, summary: '', message: '' }, photo: '', photos: {} }, 'car:bbbb2222');
      s.put({ order: ['aaaa1111', 'bbbb2222'], active: 'bbbb2222', saved: Date.now() }, 'index');
      tx.oncomplete = () => done(); };
  }));
  await p.reload({ waitUntil: 'networkidle' }); await p.waitForTimeout(12000);
  log('1 after loading with a saved blank car', { chips: await chips(), title: await title(), cross: await p.locator('.garage .chipx').count(), onDevice: await saved() });
  await p.screenshot({ path: '/tmp/e2e/blank-top.png', clip: { x: 0, y: 0, width: 390, height: 110 }, timeout: 120000 }).catch(() => {});
  // empty the garage: a blank car is the place to start from, and it has no cross because nothing else is there
  await p.locator('.garage .chipx').click(); await p.waitForTimeout(300); await p.locator('.garage .chipx').click(); await p.waitForTimeout(5000);
  log('2 the last car removed', { chips: await chips(), title: await title(), cross: await p.locator('.garage .chipx').count(), onDevice: await saved() });
  // add a car: the blank one goes by itself
  await p.locator('.dockbar input[type=password]').fill('sk-ant-test-abcd1234').catch(() => {}); await p.locator('.dockbar .go').click().catch(() => {}); await p.waitForTimeout(5000);
  await p.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/1'); await p.locator('.dockbar .go').click();
  for (let i = 0; i < 400; i++) { await p.waitForTimeout(500); if (!(await p.locator('.stage.busy').count()) && i > 6) break; }
  await p.waitForTimeout(4000);
  log('3 a car added to an empty garage', { chips: await chips(), title: await title(), onDevice: await saved() });
  await p.reload({ waitUntil: 'networkidle' }); await p.waitForTimeout(12000);
  log('4 after a reload', { chips: await chips(), title: await title() });
  log('errors', { exc: await p.locator('[data-testid="stException"]').count(), errs });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
