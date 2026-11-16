// Changing the car's miles works the offer out again by itself; the button in The case does it by hand.
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
  await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 240)));
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  const offers = () => (fs.readFileSync('/tmp/e2e/calls.log', 'utf8').match(/offer call:/g) || []).length;
  const searches = () => (fs.readFileSync('/tmp/e2e/calls.log', 'utf8').match(/budget:/g) || []).length;
  const caseText = async () => { await p.locator('.sheet-tabs .tab[data-tab=case]').click(); await p.waitForTimeout(700); return (await p.locator('.sheet-body .lead-line').first().innerText()) + ' | ' + (await p.locator('.sheet-body .lead-sub').first().innerText()); };
  const toasts = []; const grab = async () => { const t = (await p.locator('.toast').evaluate((e) => (e.hidden ? '' : e.textContent)).catch(() => '')).replace(/\s+/g, ' '); if (t && toasts[toasts.length - 1] !== t) toasts.push(t); };
  await p.goto('http://localhost:8766/', { waitUntil: 'networkidle' }); await p.waitForTimeout(14000);
  await p.locator('.dockbar input[type=password]').fill('sk-ant-test-abcd1234'); await p.locator('.dockbar .go').click(); await p.waitForTimeout(5000);
  await p.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/1'); await p.locator('.dockbar .go').click();
  for (let i = 0; i < 400; i++) { await p.waitForTimeout(500); if (!(await p.locator('.stage.busy').count()) && i > 6) break; }
  await p.waitForTimeout(3000);
  await p.locator('.tabs .tab[data-tab=case]').click(); await p.waitForTimeout(1000);
  const s0 = searches();
  log('1 built', { head: (await p.locator('.head .sub').innerText()).slice(0, 60), theCase: await caseText(), offerCalls: offers(), button: await p.locator('.sheet-body .reoffer').innerText().catch(() => 'missing') });
  await p.locator('.sheet-tabs .tab[data-tab=car]').click(); await p.waitForTimeout(800);
  await p.locator('.sheet-body .carfacts input[name=miles]').fill('15,000');
  await p.locator('.sheet-body .carfacts button[type=submit]').click();
  for (let i = 0; i < 60; i++) { await p.waitForTimeout(400); await grab(); if (toasts.some((t) => /worked out again/.test(t))) break; }
  await p.waitForTimeout(1500);
  log('2 miles changed to 15,000', { toasts, head: (await p.locator('.head .sub').innerText()).slice(0, 60), theCase: await caseText(), offerCalls: offers(), searchesRun: searches() - s0 });
  toasts.length = 0;
  await p.locator('.sheet-body .reoffer').click();
  for (let i = 0; i < 60; i++) { await p.waitForTimeout(400); await grab(); if (toasts.some((t) => /worked out again/.test(t))) break; }
  log('3 the button, by hand', { toasts, offerCalls: offers(), button: await p.locator('.sheet-body .reoffer').innerText().catch(() => 'missing') });
  await p.screenshot({ path: '/tmp/e2e/miles-case.png', timeout: 120000 }).catch(() => {});
  toasts.length = 0;
  await p.locator('.sheet-tabs .tab[data-tab=car]').click(); await p.waitForTimeout(800);
  await p.locator('.sheet-body .carfacts input[name=exterior]').fill('Silver');
  await p.locator('.sheet-body .carfacts button[type=submit]').click();
  for (let i = 0; i < 12; i++) { await p.waitForTimeout(400); await grab(); }
  log('4 a change that does not move the price', { toasts, offerCalls: offers() });
  log('errors', { exc: await p.locator('[data-testid="stException"]').count(), errs });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
