// Changing the car's miles, colour or options works the offer out again and rewrites the message to match.
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
  const theCase = async () => { await p.locator('.sheet-tabs .tab[data-tab=case]').click(); await p.waitForTimeout(700);
    return { head: await p.locator('.sheet-body .lead-line').first().innerText(), basis: (await p.locator('.sheet-body .basis').innerText().catch(() => 'none')).replace(/\s+/g, ' '),
      stale: await p.locator('.sheet-body .basis + .c-flag').innerText().catch(() => ''), moves: await p.locator('.sheet-body .move').evaluateAll(els => els.map(e => e.innerText.replace(/\s+/g, ' ').slice(0, 90))) }; };
  const message = async () => { await p.locator('.sheet-tabs .tab[data-tab=message]').click(); await p.waitForTimeout(700); return (await p.locator('.sheet-body .msgbox').inputValue().catch(() => 'none')).replace(/\s+/g, ' '); };
  const change = async (fill, label) => { toasts.length = 0; await p.locator('.sheet-tabs .tab[data-tab=car]').click(); await p.waitForTimeout(800); await fill();
    await p.locator('.sheet-body .carfacts button[type=submit]').click();
    for (let i = 0; i < 80; i++) { await p.waitForTimeout(400); await grab(); if (toasts.some((t) => /worked out again/.test(t) && !/Working out/.test(t))) break; }
    await p.waitForTimeout(1500);
    log(label, { toasts: toasts.map((t) => t.slice(0, 210)), theCase: await theCase(), message: await message(), lastMessageCall: calls(/message call:.*/g).slice(-1)[0] }); };
  await p.goto('http://localhost:8766/', { waitUntil: 'networkidle' }); await p.waitForTimeout(14000);
  await p.locator('.dockbar input[type=password]').fill('sk-ant-test-abcd1234'); await p.locator('.dockbar .go').click(); await p.waitForTimeout(5000);
  await p.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/1'); await p.locator('.dockbar .go').click();
  for (let i = 0; i < 400; i++) { await p.waitForTimeout(500); if (!(await p.locator('.stage.busy').count()) && i > 6) break; }
  await p.waitForTimeout(3000);
  await p.locator('.tabs .tab[data-tab=case]').click(); await p.waitForTimeout(1000);
  log('1 built', { head: (await p.locator('.head .sub').innerText()).slice(0, 70), theCase: await theCase(), message: await message() });
  await change(() => p.locator('.sheet-body .carfacts input[name=miles]').fill('15,000'), '2 miles to 15,000');
  await change(() => p.locator('.sheet-body .carfacts input[name=exterior]').fill('Misano Blue'), '3 colour to Misano Blue');
  await change(() => p.locator('.sheet-body .carfacts textarea[name=options]').fill('Carbon ceramic brakes\nExecutive package'), '4 options added');
  await p.locator('.sheet-tabs .tab[data-tab=case]').click(); await p.waitForTimeout(700);
  await p.locator('.sheet-body .basis').evaluate((e) => e.scrollIntoView({ block: 'start' })).catch(() => {}); await p.waitForTimeout(400);
  await p.screenshot({ path: '/tmp/e2e/details-case.png' });
  await p.locator('.sheet-body .tocar').click(); await p.waitForTimeout(700);
  log('5 Change goes to Car details', { tab: await p.locator('.sheet-tabs .tab.on, .sheet-tabs .tab[aria-selected=true]').first().innerText().catch(() => '?'), focused: await p.evaluate(() => { let a = document.activeElement; while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement; return a && a.name; }) });
  await p.screenshot({ path: '/tmp/e2e/details-car.png' });
  toasts.length = 0;
  await p.locator('.sheet-body .carfacts input[name=seller]').fill('Somebody Motors'); await p.locator('.sheet-body .carfacts button[type=submit]').click();
  for (let i = 0; i < 10; i++) { await p.waitForTimeout(400); await grab(); }
  log('6 a change that does not move the price', { toasts, offerCalls: calls(/offer call:/g).length });
  log('errors', { exc: await p.locator('[data-testid="stException"]').count(), errs });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
