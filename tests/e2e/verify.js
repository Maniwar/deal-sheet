// Verifiable first: sold cars open on their own page with a checked VIN; cars with nothing to open are folded away;
// a Marketplace lead gets a search link and a box for its direct link, and moves up once the link is pasted.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
  await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 240)));
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  const cards = (sel) => p.locator(sel).evaluateAll((els) => els.map((e) => { const a = e.querySelector('a.c-link'), v = e.querySelector('.vin'); return { pill: (e.querySelector('.pill') || {}).innerText, price: (e.querySelector('.c-price') || {}).innerText, vin: v ? v.innerText.replace(/\s+/g, ' ') : '', link: a ? a.innerText.replace(/\s+/g, ' ').trim() : '', to: a ? a.href.replace('https://www.', '').slice(0, 62) : '', paste: !!e.querySelector('.setlink'), out: ((e.querySelector('.pill.out') || {}).innerText || '') }; }));
  await p.goto('http://localhost:8766/', { waitUntil: 'networkidle' }); await p.waitForTimeout(14000);
  await p.locator('.dockbar input[type=password]').fill('sk-ant-test-abcd1234'); await p.locator('.dockbar .go').click(); await p.waitForTimeout(5000);
  await p.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/1'); await p.locator('.dockbar .go').click();
  for (let i = 0; i < 120; i++) { await p.waitForTimeout(500); if (!(await p.locator('.stage.busy').count()) && i > 6) break; }
  await p.waitForTimeout(2500);
  log('0 tabs', (await p.locator('.tabs .tab').allInnerTexts()).slice(0, 3));
  await p.locator('.tabs .tab[data-tab=comps]').click(); await p.waitForTimeout(1200);
  log('1 sold, counted', await cards('.sheet-body > .card'));
  log('2 sold, folded', { label: await p.locator('.sheet-body .leftout summary').first().innerText().catch(() => 'none'), cards: await cards('.sheet-body .leftout .card') });
  await p.locator('.sheet-tabs .tab[data-tab=sale]').click(); await p.waitForTimeout(1000);
  log('3 for sale, shown', await cards('.sheet-body > .card'));
  log('4 for sale, leads', { label: await p.locator('.sheet-body .leftout summary').first().innerText().catch(() => 'none'), cards: await cards('.sheet-body .leftout .card') });
  // the buyer found the Marketplace car and pastes its own link
  await p.locator('.sheet-body .leftout summary').first().click(); await p.waitForTimeout(400);
  const form = p.locator('.sheet-body .leftout .card .setlink').first();
  await form.locator('input').fill('https://www.facebook.com/marketplace/nyc/lotus-evora/'); await form.locator('button').click(); await p.waitForTimeout(4000);
  log('5 a list link is refused', ((await p.locator('.toast').innerText().catch(() => '')) || '').slice(0, 120));
  if (!(await p.locator('.sheet-body .leftout[open]').count())) { await p.locator('.sheet-body .leftout summary').first().click(); await p.waitForTimeout(300); }
  const form2 = p.locator('.sheet-body .leftout .card .setlink').first();
  await form2.locator('input').fill('https://www.facebook.com/marketplace/item/1234567890123456/'); await form2.locator('button').click(); await p.waitForTimeout(4500);
  log('6 its own link is saved', { toast: ((await p.locator('.toast').innerText().catch(() => '')) || '').slice(0, 90), shown: (await cards('.sheet-body > .card')).filter((c) => /marketplace\/item/.test(c.to)), leadsLeft: await p.locator('.sheet-body .leftout .card').count(), tab: await p.locator('.sheet-tabs .tab[data-tab=sale]').innerText() });
  log('errors', { exc: await p.locator('[data-testid="stException"]').count(), errs });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
