// A listing link pasted by hand: its page fills in the price, and a car already found on a listing site is recognised as the same one.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
  await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 240)));
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  const toast = () => p.locator('.toast').evaluate((e) => (e.hidden ? '' : e.textContent.replace(/\s+/g, ' '))).catch(() => '');
  const sale = async () => { await p.locator('.sheet-tabs .tab[data-tab=sale]').click(); await p.waitForTimeout(900);
    return { tab: await p.locator('.sheet-tabs .tab[data-tab=sale]').innerText(), cards: await p.locator('.sheet-body .card').evaluateAll(els => els.map(e => e.innerText.replace(/\s+/g, ' ')).filter((t) => /\$53,400|\$58,500|\$61,000/.test(t)).map((t) => t.slice(0, 330))) }; };
  const add = async (fields) => { await p.locator('.sheet-tabs .tab[data-tab=sale]').click(); await p.waitForTimeout(700);
    const box = p.locator('.sheet-body .byhand').last(); await box.locator('summary').click(); await p.waitForTimeout(400);
    for (const [name, value] of Object.entries(fields)) await box.locator(`input[name=${name}]`).fill(value);
    await box.locator('button').click(); let t = '';
    for (let i = 0; i < 40; i++) { await p.waitForTimeout(400); t = await toast(); if (t) break; }
    await p.waitForTimeout(1500); return t; };
  await p.goto('http://localhost:8766/', { waitUntil: 'networkidle' }); await p.waitForTimeout(14000);
  await p.locator('.dockbar input[type=password]').fill('sk-ant-test-abcd1234'); await p.locator('.dockbar .go').click(); await p.waitForTimeout(5000);
  await p.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/1'); await p.locator('.dockbar .go').click();
  for (let i = 0; i < 400; i++) { await p.waitForTimeout(500); if (!(await p.locator('.stage.busy').count()) && i > 6) break; }
  await p.waitForTimeout(3000);
  await p.locator('.tabs .tab[data-tab=case]').click(); await p.waitForTimeout(1000);
  const before = await sale();
  log('1 before', before);
  const t1 = await add({ url: 'http://127.0.0.1:8898/titleonly/1' });
  log('2 pasted only the link of a page whose price is in its title', { toast: t1.slice(0, 260), ...(await sale()) });
  const t2 = await add({ url: 'http://127.0.0.1:8898/listing/77' });
  log('3 pasted the link of a car that is not here yet', { toast: t2.slice(0, 200), ...(await sale()) });
  const t3 = await add({ url: 'http://127.0.0.1:8898/blocked/9' });
  log('4 pasted a link the app may not read, with no price', { toast: t3.slice(0, 200) });
  const t4 = await add({ url: 'http://127.0.0.1:8898/blocked/9', price: '61000' });
  log('5 the same link with the price typed', { toast: t4.slice(0, 200), ...(await sale()) });
  await p.locator('.sheet-body .card', { hasText: 'page you gave' }).first().evaluate((e) => e.scrollIntoView({ block: 'start' })).catch(() => {});
  await p.screenshot({ path: '/tmp/e2e/pasted.png' });
  log('errors', { exc: await p.locator('[data-testid="stException"]').count(), errs });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
