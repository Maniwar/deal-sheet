// Price another listing of the same model from the sales already held, compare, keep across a reload, remove, and make one the car.
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
  await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 240)));
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  const calls = (re) => (fs.readFileSync('/tmp/e2e/calls.log', 'utf8').match(re) || []);
  const toasts = []; const grab = async () => { const t = (await p.locator('.toast').evaluate((e) => (e.hidden ? '' : e.textContent)).catch(() => '')).replace(/\s+/g, ' '); if (t && toasts[toasts.length - 1] !== t) toasts.push(t); };
  const rows = async () => { await p.locator('.sheet-tabs .tab[data-tab=case]').click(); await p.waitForTimeout(700); return p.locator('.sheet-body .ver').evaluateAll(els => els.map(e => e.innerText.replace(/\s+/g, ' ').slice(0, 260))); };
  const price = async (fill, label) => { toasts.length = 0; await p.locator('.sheet-tabs .tab[data-tab=case]').click(); await p.waitForTimeout(700); const s0 = calls(/budget:/g).length; await fill();
    await p.locator('.sheet-body .vform button[type=submit]').click();
    for (let i = 0; i < 80; i++) { await p.waitForTimeout(400); await grab(); if (toasts.some((t) => /fair deal is about|no price/.test(t))) break; }
    await p.waitForTimeout(1500);
    log(label, { toasts: toasts.map((t) => t.slice(0, 200)), rows: await rows(), searchesRun: calls(/budget:/g).length - s0, lastOffer: calls(/offer for:.*/g).slice(-1)[0] }); };
  await p.goto('http://localhost:8766/', { waitUntil: 'networkidle' }); await p.waitForTimeout(14000);
  await p.locator('.dockbar input[type=password]').fill('sk-ant-test-abcd1234'); await p.locator('.dockbar .go').click(); await p.waitForTimeout(5000);
  await p.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/1'); await p.locator('.dockbar .go').click();
  for (let i = 0; i < 400; i++) { await p.waitForTimeout(500); if (!(await p.locator('.stage.busy').count()) && i > 6) break; }
  await p.waitForTimeout(3000);
  await p.locator('.tabs .tab[data-tab=case]').click(); await p.waitForTimeout(1000);
  log('1 built', { head: (await p.locator('.head .sub').innerText()).slice(0, 70), form: await p.locator('.sheet-body .vform').count(), rows: await rows() });
  await price(async () => { const f = p.locator('.sheet-body .vform');
    await f.locator('input[name=miles]').fill('1,000'); await f.locator('input[name=price]').fill('99000'); await f.locator('select[name=gear]').selectOption('Automatic');
    await f.locator('input[name=exterior]').fill('Misano Blue'); await f.locator('textarea[name=options]').fill('Carbon ceramic brakes'); }, '2 a 1,000-mile automatic in blue with ceramic brakes');
  await p.locator('.sheet-body .vform').evaluate((e) => e.scrollIntoView({ block: 'start' })); await p.waitForTimeout(400);
  await p.screenshot({ path: '/tmp/e2e/versions-1.png' });
  await p.locator('.sheet-body .versions').evaluate((e) => e.scrollIntoView({ block: 'start' })); await p.waitForTimeout(400);
  await p.screenshot({ path: '/tmp/e2e/versions-2.png' });
  await price(async () => { const f = p.locator('.sheet-body .vform');
    await f.locator('input[name=miles]').fill('15000'); await f.locator('input[name=price]').fill(''); await f.locator('select[name=gear]').selectOption('');
    await f.locator('input[name=exterior]').fill(''); await f.locator('textarea[name=options]').fill(''); }, '3 the same car at 15,000 miles, nothing else changed');
  await p.reload({ waitUntil: 'networkidle' }); await p.waitForTimeout(16000);
  await p.locator('.tabs .tab[data-tab=case]').click(); await p.waitForTimeout(1200);
  log('4 after a reload', { rows: await rows() });
  await p.locator('.sheet-body .verdrop').last().click(); await p.waitForTimeout(3000);
  log('5 one removed', { rows: await rows() });
  toasts.length = 0;
  await p.locator('.sheet-body .veruse').first().click();
  for (let i = 0; i < 90; i++) { await p.waitForTimeout(400); await grab(); if (toasts.some((t) => /worked out again/.test(t) && !/Working out/.test(t))) break; }
  await p.waitForTimeout(1500);
  await p.locator('.sheet-tabs .tab[data-tab=message]').click(); await p.waitForTimeout(700);
  log('6 made it the car', { toasts: toasts.map((t) => t.slice(0, 260)), head: (await p.locator('.head .sub').innerText()).slice(0, 90), message: (await p.locator('.sheet-body .msgbox').inputValue().catch(() => 'none')).replace(/\s+/g, ' '),
    basis: await (async () => { await p.locator('.sheet-tabs .tab[data-tab=case]').click(); await p.waitForTimeout(700); return (await p.locator('.sheet-body .basis').innerText().catch(() => 'none')).replace(/\s+/g, ' '); })(), rows: await rows() });
  await price(async () => { const f = p.locator('.sheet-body .vform');
    await f.locator('input[name=miles]').fill('20000'); await f.locator('select[name=gear]').selectOption('Automatic'); }, '7 an automatic at 20,000 miles: searched for first');
  toasts.length = 0; const s1 = calls(/budget:/g).length;
  await p.locator('.sheet-body .veruse').first().click();
  for (let i = 0; i < 300; i++) { await p.waitForTimeout(400); await grab(); if (toasts.some((t) => /worked out again|no sales to work/.test(t) && !/Working out/.test(t))) break; }
  await p.waitForTimeout(2000);
  await p.locator('.sheet-tabs .tab[data-tab=message]').click(); await p.waitForTimeout(700);
  log('8 made the automatic the car: search, offer and message', { toasts: toasts.map((t) => t.slice(0, 330)), head: (await p.locator('.head .sub').innerText()).slice(0, 90), tabs: (await p.locator('.sheet-tabs .tab').allInnerTexts()).slice(1, 3),
    message: (await p.locator('.sheet-body .msgbox').inputValue().catch(() => 'none')).replace(/\s+/g, ' '), searchRequests: calls(/budget:/g).length - s1, rows: await rows() });
  log('errors', { exc: await p.locator('[data-testid="stException"]').count(), errs });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
