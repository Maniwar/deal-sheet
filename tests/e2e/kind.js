// A car whose plain search returns only the model's other kinds (automatics for a manual, an open car for a coupe).
// kindfew: the app searches again for exactly this kind and the Sold tab fills. kindnone: nothing of the kind exists,
// so the Sold tab says what was left out, and Search for sales looks for the exact kind on every site.
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  const errs = [], wrong = [];
  const calls = () => fs.readFileSync('/tmp/e2e/calls.log', 'utf8');
  const build = async (key) => {
    const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
    await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
    const p = await ctx.newPage(); p.on('pageerror', e => errs.push(String(e).slice(0, 200)));
    await p.goto('http://localhost:8766/', { waitUntil: 'domcontentloaded', timeout: 90000 }); await p.waitForTimeout(18000);
    await p.locator('.dockbar input[type=password]').fill(key); await p.locator('.dockbar .go').click(); await p.waitForTimeout(6000);
    await p.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/1'); await p.locator('.dockbar .go').click();
    for (let i = 0; i < 400; i++) { await p.waitForTimeout(500); if (!(await p.locator('.stage.busy').count()) && i > 6) break; }
    await p.waitForTimeout(5000);
    return p; };
  const sold = async (p) => { await p.locator('.tabs .tab[data-tab=comps]').click().catch(() => p.locator('.sheet-tabs .tab[data-tab=comps]').click()); await p.waitForTimeout(1500);
    return { tab: (await p.locator('.sheet-tabs .tab[data-tab=comps]').innerText()).replace(/\s+/g, ' '), cards: await p.locator('.sheet-body .card').evaluateAll((els) => els.map((e) => e.innerText.replace(/\s+/g, ' ').slice(0, 70)).filter(Boolean)),
      text: (await p.locator('.sheet-body').innerText()).replace(/\s+/g, ' ').slice(0, 420) }; };
  const steps = async (p) => { await p.locator('.sheet-tabs .tab[data-tab=case]').click(); await p.waitForTimeout(1200); await p.locator('.sheet-body .steplog summary').click().catch(() => {}); await p.waitForTimeout(400);
    return { lines: await p.locator('.sheet-body .steplog .livelog div').allInnerTexts(), body: (await p.locator('.sheet-body').innerText()).replace(/\s+/g, ' ') }; };

  // 1. the second search finds the car's own kind
  const A = await build('sk-ant-test-kindfew');
  const a = await sold(A), aSteps = await steps(A);
  const one = { tab: a.tab, cards: a.cards, said: aSteps.lines.filter((t) => /Fewer than three sales of this exact kind|Left out: /.test(t)).slice(0, 3),
    summary: (aSteps.body.match(/The first search held fewer than three[^.]*\./) || [''])[0], exactSearches: (calls().match(/exact_kind=True/g) || []).length };
  log('1 plain search gave only other kinds; the second search', one);
  if (a.cards.length !== 3 || a.cards.some((c) => !/Manual/.test(c)) || !/found 3 more/.test(one.summary) || one.exactSearches < 2) wrong.push('1: the second search did not fill the Sold tab with the three manual sales');
  await A.context().close();

  // 2. nothing of the kind anywhere: the tab says why, and the button searches for the exact kind
  const before = (calls().match(/exact_kind=True/g) || []).length;
  const B = await build('sk-ant-test-kindnone');
  const bSold = await sold(B);
  const during = (calls().match(/exact_kind=True/g) || []).length;
  await B.locator('.sheet-body .more[data-kind=sold]').click();
  for (let i = 0; i < 240; i++) { await B.waitForTimeout(500); if (!(await B.locator('.sheet-body .more[disabled]').count()) && i > 8) break; }
  await B.waitForTimeout(3000);
  const sites = [...new Set((calls().split('exact_kind=True').slice(during - before + 1).join('').match(/only=\[[^\]]*\]/g) || []))];
  const after = (calls().match(/exact_kind=True/g) || []).length;
  const two = { tab: bSold.tab, says: bSold.text.slice(0, 330), searchedAgainForExactKind: after - during, toast: await B.locator('.toast').evaluate((e) => (e.hidden ? '' : e.textContent)).catch(() => '') };
  log('2 nothing of the kind exists', two);
  if (!/Sold ?0/.test(two.tab) || !/left out/.test(two.says) || !/exact body style and gearbox/.test(two.says) || two.searchedAgainForExactKind < 3) wrong.push('2: the empty Sold tab did not say why, or the button did not search every site for the exact kind');
  log('errors', { exc: await B.locator('[data-testid="stException"]').count(), errs: errs.concat(wrong) });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
