// For sale now: the page check needs proof, and a car whose own page says automatic goes when the buyer's car is a manual.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
  await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 240)));
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  const cards = () => p.locator('.sheet-body .card').evaluateAll((els) => els.map((e) => ({ pill: (e.querySelector('.pill') || {}).textContent, price: (e.querySelector('.c-price') || {}).textContent, meta: ((e.querySelector('.c-meta') || {}).textContent || '').slice(0, 60), seen: ((e.querySelector('.c-seen') || {}).textContent || '').slice(0, 58), flag: [...e.querySelectorAll('.c-flag')].map((f) => f.textContent.slice(0, 40)).join(' | ') })));
  await p.goto('http://localhost:8766/', { waitUntil: 'networkidle' }); await p.waitForTimeout(14000);
  await p.locator('.dockbar input[type=password]').fill('sk-ant-test-abcd1234'); await p.locator('.dockbar .go').click(); await p.waitForTimeout(5000);
  await p.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/1'); await p.locator('.dockbar .go').click();
  for (let i = 0; i < 200; i++) { await p.waitForTimeout(500); if (!(await p.locator('.stage.busy').count()) && i > 6) break; }
  await p.waitForTimeout(2500);
  log('0 the car', (await p.locator('.head .sub').innerText()).slice(0, 60));
  await p.locator('.tabs .tab[data-tab=case]').click(); await p.waitForTimeout(1200);
  await p.locator('.sheet-tabs .tab[data-tab=sale]').click(); await p.waitForTimeout(1200);
  const all = await cards();
  log('1 for sale tab', await p.locator('.sheet-tabs .tab[data-tab=sale]').innerText());
  all.forEach((c) => console.log('   ' + JSON.stringify(c)));
  log('2 automatics left in the list', all.filter((c) => /Automatic/.test(c.meta) || /89,000|52,000/.test(c.price)).length);
  const ended = await p.locator('.sheet-body .card').evaluateAll((els) => els.filter((e) => /ended/i.test((e.querySelector('.pill') || {}).textContent || '')).map((e) => (e.querySelector('.c-price') || {}).textContent));
  log('2b listing ended', ended);
  await p.screenshot({ path: '/tmp/e2e/gear-sale.png', fullPage: false, timeout: 120000 }).catch((e) => console.log('shot failed', String(e).slice(0, 80)));
  await p.locator('.sheet-tabs .tab[data-tab=case]').click(); await p.waitForTimeout(800);
  await p.locator('.sheet-body .steplog summary').click().catch(() => {}); await p.waitForTimeout(400);
  log('2c step log lines about what was left out', (await p.locator('.sheet-body .steplog .livelog div').allInnerTexts()).filter((t) => /Left out|still there|could not be confirmed|sold or gone/i.test(t)));
  const body = await p.locator('.sheet-body').innerText(); const at = body.indexOf('automatic transmission');
  log('3 the case says', body.slice(Math.max(0, at - 8), at + 190).replace(/\s+/g, ' '));
  log('errors', { exc: await p.locator('[data-testid="stException"]').count(), errs });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
