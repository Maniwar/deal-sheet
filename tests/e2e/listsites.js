// The listing-sites search: cars read off Cars.com and CarGurus results with their VINs, then a Refresh that reprices one and loses another.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
  await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 240)));
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  const toast = () => p.locator('.toast').evaluate((e) => (e.hidden ? '' : e.textContent)).catch(() => '');
  const sale = async () => { await p.locator('.sheet-tabs .tab[data-tab=sale]').click(); await p.waitForTimeout(900);
    return p.locator('.sheet-body .card').evaluateAll(els => els.map(e => e.innerText.replace(/\s+/g, ' ')).filter((t) => /Cars\.com|CarGurus|Edmunds|read live/i.test(t)).map((t) => t.slice(0, 400))); };
  await p.goto('http://localhost:8766/', { waitUntil: 'networkidle' }); await p.waitForTimeout(14000);
  await p.locator('.dockbar input[type=password]').fill('sk-ant-test-lists1'); await p.locator('.dockbar .go').click(); await p.waitForTimeout(5000);
  await p.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/1'); await p.locator('.dockbar .go').click();
  for (let i = 0; i < 160; i++) { await p.waitForTimeout(500); if (!(await p.locator('.working').isVisible().catch(() => false)) && i > 8) break; }
  await p.waitForTimeout(2500);
  await p.locator('.tabs .tab[data-tab=case]').click(); await p.waitForTimeout(1200);
  const first = await sale();
  log('1 after the build', { tab: await p.locator('.sheet-tabs .tab[data-tab=sale]').innerText(), fromListingSites: first.length, cards: first });
  log('2 checks', { longoOnce: first.filter((t) => /Longo/.test(t)).length, carmaxAutomaticLeftOut: !first.some((t) => /CarMax/.test(t)), noVinSetAside: first.filter((t) => /Kian/.test(t)).map((t) => /Not counted/i.test(t)),
    resultsLinks: await p.locator('.sheet-body .c-link').evaluateAll(els => els.map(e => e.innerText.replace(/\s+/g, ' ')).filter((t) => /results/i.test(t)).length) });
  await p.screenshot({ path: '/tmp/e2e/lists-1.png' });
  await p.locator('.sheet .close, .sheet-close, .sheet-tabs + button, .sheet [aria-label="Close"]').first().click().catch(() => {}); await p.waitForTimeout(800);
  const btn = p.locator('.verdict .refresh');
  await btn.click(); let note = '';
  for (let i = 0; i < 160; i++) { await p.waitForTimeout(400); note = note || await toast(); if ((await btn.innerText().catch(() => '')) === 'Refresh results' && i > 5) break; }
  await p.waitForTimeout(2000);
  log('3 refresh notice', (note || await toast()).slice(0, 330));
  await p.locator('.tabs .tab[data-tab=case]').click().catch(() => {}); await p.waitForTimeout(1200);
  const second = await sale();
  log('4 after the refresh', second);
  await p.locator('.sheet-body .card', { hasText: 'eCarOne' }).first().scrollIntoViewIfNeeded().catch(() => {});
  await p.screenshot({ path: '/tmp/e2e/lists-2.png' });
  log('errors', { exc: await p.locator('[data-testid="stException"]').count(), errs });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
