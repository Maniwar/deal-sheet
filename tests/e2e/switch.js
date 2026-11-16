// Long work must survive taps and reloads: a refresh is started once, a car switch during it is instant and does
// not flip back, a reload shows it still working, and the result lands on the car it was started for.
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
  await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 240)));
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  const posts = () => (fs.readFileSync('/tmp/e2e/calls.log', 'utf8').match(/budget:/g) || []).length;
  const chips = () => p.locator('.garage .chip:not(.add)').evaluateAll((els) => els.map((e) => (e.classList.contains('on') ? '*' : '') + e.textContent.trim()));
  const title = () => p.locator('.head .title').innerText();
  await p.goto('http://localhost:8766/', { waitUntil: 'networkidle' }); await p.waitForTimeout(14000);
  await p.locator('.dockbar input[type=password]').fill('sk-ant-test-abcd1234'); await p.locator('.dockbar .go').click(); await p.waitForTimeout(5000);
  await p.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/1'); await p.locator('.dockbar .go').click();
  for (let i = 0; i < 400; i++) { await p.waitForTimeout(500); if (!(await p.locator('.stage.busy').count()) && i > 6) break; }
  await p.waitForTimeout(3000);
  const afterBuild = posts();
  log('1 built', { title: (await title()).replace(/\s+/g, ' '), chips: await chips(), searchRequests: afterBuild });

  // every change of the highlighted chip from here on
  await p.locator('.garage').evaluate((host) => { window.__seen = []; const rec = () => { const on = host.querySelector('.chip.on'); const t = on ? on.textContent.trim() : ''; if (window.__seen[window.__seen.length - 1] !== t) window.__seen.push(t); }; rec(); new MutationObserver(rec).observe(host, { subtree: true, childList: true, attributes: true, attributeFilter: ['class'] }); });
  const refresh = p.locator('.verdict .refresh, .refresh').first();
  await refresh.click(); await p.waitForTimeout(2500);
  log('2 refresh running', { label: (await refresh.innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 30) });
  const t0 = Date.now();
  await p.locator('.garage .chip:not(.add):not(.on)').first().click();
  let switched = 0; for (let i = 0; i < 60; i++) { await p.waitForTimeout(250); if (/911/.test(await title())) { switched = Date.now() - t0; break; } }
  log('3 switched to the other car while it ran', { ms: switched, title: (await title()).replace(/\s+/g, ' '), chips: await chips(), refreshLabelOnThisCar: (await p.locator('.refresh').first().innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 30) });
  await p.reload({ waitUntil: 'networkidle' }); await p.waitForTimeout(9000);
  log('4 after a reload mid-search', { title: (await title().catch(() => '')).replace(/\s+/g, ' '), chips: await chips() });
  let notice = ''; for (let i = 0; i < 240; i++) { await p.waitForTimeout(500); const t = await p.locator('.toast').innerText().catch(() => ''); if (/Refreshed/.test(t)) { notice = t; break; } }
  log('5 finished', { notice: notice.replace(/\s+/g, ' ').slice(0, 200), searchRequestsForTheRefresh: posts() - afterBuild });
  await p.waitForTimeout(1500);
  const back = p.locator('.garage .chip:not(.add):not(.on)').first(); await back.click(); await p.waitForTimeout(4000);
  await p.locator('.tabs .tab[data-tab=case]').click(); await p.waitForTimeout(1000);
  log('6 back on the car that was refreshed', { title: (await title()).replace(/\s+/g, ' '), tabs: await p.locator('.sheet-tabs .tab').allInnerTexts() });
  log('7 chip highlight history since the refresh began', await p.evaluate(() => window.__seen || 'lost on reload'));
  log('errors', { exc: await p.locator('[data-testid="stException"]').count(), errs });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
