// A full build through the stand-in API: sold and for-sale searches at once, a refused site, a busy search, list-page results, Marketplace lists.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
  await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 240)));
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  await p.goto('http://localhost:8766/', { waitUntil: 'networkidle' }); await p.waitForTimeout(14000);
  await p.locator('.dockbar input[type=password]').fill('sk-ant-test-abcd1234'); await p.locator('.dockbar .go').click(); await p.waitForTimeout(5000);
  await p.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/1'); await p.locator('.dockbar .go').click();
  const t0 = Date.now(), live = new Set();
  for (let i = 0; i < 160; i++) { await p.waitForTimeout(500); for (const t of await p.locator('.working .livelog div, .busybox .livelog div, .livelog div').allInnerTexts().catch(() => [])) live.add(t); if (!(await p.locator('.stage.busy').count()) && i > 6) break; }
  log('1 built', { seconds: Math.round((Date.now() - t0) / 1000), title: await p.locator('.head .title').innerText(), linesSeenLive: live.size, sample: [...live].slice(0, 4) });
  await p.waitForTimeout(2500);
  await p.locator('.tabs .tab[data-tab=case]').click(); await p.waitForTimeout(1200);
  log('2 tabs', await p.locator('.sheet-tabs .tab').allInnerTexts());
  const body = await p.locator('.sheet-body').innerText();
  const at = body.toLowerCase().indexOf('what the search found');
  log('3 what the search found', body.slice(at, at + 620).replace(/\s+/g, ' '));
  await p.locator('.sheet-body .steplog summary').click().catch(() => {}); await p.waitForTimeout(400);
  const steps = await p.locator('.sheet-body .steplog .livelog div').allInnerTexts();
  log('4 step log', { count: steps.length, notable: steps.filter((t) => /cannot look inside|busy|rate limit|Waiting|did not|Facebook|same time|used all/i.test(t)) });
  await p.locator('.sheet-tabs .tab[data-tab=comps]').click(); await p.waitForTimeout(1000);
  const soldCards = await p.locator('.sheet-body .card').evaluateAll(els => els.map(e => e.innerText.replace(/\s+/g, ' ').slice(0, 84)));
  log('5 sold tab', { tab: await p.locator('.sheet-tabs .tab[data-tab=comps]').innerText(), cards: soldCards });
  await p.locator('.sheet-tabs .tab[data-tab=sale]').click(); await p.waitForTimeout(1000);
  log('6 for sale tab', { tab: await p.locator('.sheet-tabs .tab[data-tab=sale]').innerText(), cards: await p.locator('.sheet-body .card').evaluateAll(els => els.map(e => e.innerText.replace(/\s+/g, ' ').slice(0, 330))) });
  await p.screenshot({ path: '/tmp/e2e/build2-sale.png' });
  // an uncommon kind (a manual) is named in the searches from the start
  const kindNamed = [...new Set((require('fs').readFileSync('/tmp/e2e/calls.log', 'utf8').match(/names_kind=[^\n]+/g) || []))];
  log('7 the searches name the kind', kindNamed);
  if (!kindNamed.includes('names_kind=6-speed manual')) errs.push('the sales searches did not name the gearbox');
  log('errors', { exc: await p.locator('[data-testid="stException"]').count(), errs });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
