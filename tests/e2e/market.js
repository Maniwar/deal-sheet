// Classic.com's market page, read by the app. The search opens the market page for one model year and the model
// copies one row of it without the seller's name, as real runs do. The app reads every row of that page itself,
// opens the whole market (every model year) on its own, names who sold each car and whether that was an auction,
// offers a search for each auction's own page, and checks a sale against that page when its link is pasted.
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
  await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
  const p = await ctx.newPage(); const errs = [], wrong = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 240)));
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  const calls = () => fs.readFileSync('/tmp/e2e/calls.log', 'utf8');
  const toast = () => p.locator('.toast').evaluate((e) => (e.hidden ? '' : e.textContent.replace(/\s+/g, ' '))).catch(() => '');
  const cards = () => p.locator('.sheet-body .card').evaluateAll((els) => els.map((e) => e.innerText.replace(/\s+/g, ' ')).filter(Boolean));
  await p.goto('http://localhost:8766/', { waitUntil: 'domcontentloaded', timeout: 90000 }); await p.waitForTimeout(18000);
  await p.locator('.dockbar input[type=password]').fill('sk-ant-test-market'); await p.locator('.dockbar .go').click(); await p.waitForTimeout(6000);
  await p.locator('.dockbar textarea').fill('2014 Porsche 911 Carrera S Cabriolet 7-speed manual'); await p.locator('.dockbar .go').click();
  for (let i = 0; i < 400; i++) { await p.waitForTimeout(500); if (!(await p.locator('.stage.busy').count()) && i > 6) break; }
  await p.waitForTimeout(5000);

  // 1. the Sold tab holds every sale on the page, each with who sold it
  await p.locator('.tabs .tab[data-tab=comps]').click().catch(() => p.locator('.sheet-tabs .tab[data-tab=comps]').click()); await p.waitForTimeout(1500);
  const sold = await cards();
  const one = { tab: (await p.locator('.sheet-tabs .tab[data-tab=comps]').innerText()).replace(/\s+/g, ' '), cards: sold.map((t) => t.slice(0, 150)) };
  log('1 sold tab', one);
  const has = (price, ...words) => sold.some((t) => t.includes(price) && words.every((w) => t.includes(w)));
  if (!has('$108,000', 'Bring a Trailer', 'Aug 22, 2026', '10,000 mi')) wrong.push('1: the $108,000 sale is not there with Bring a Trailer, its date and miles');
  if (!has('$110,000', 'Cars & Bids')) wrong.push('1: the $110,000 sale the model left out is not there');
  if (!has('$77,000', 'Bring a Trailer', 'Apr 4, 2025')) wrong.push('1: a sale of another model year, from the whole market, is not there');
  // with four auction results to count, a dealer's listing marked sold is kept out of the numbers and says why
  await p.locator('.sheet-body .leftout summary').click().catch(() => {}); await p.waitForTimeout(600);
  const dealer = (await cards()).find((t) => t.includes('$82,500')) || '';
  log('1b dealer listing', dealer.slice(0, 260));
  if (!/not counted: a dealer's last asking price/i.test(dealer) || !/what the dealer last asked, not a public sale price/.test(dealer)) wrong.push('1: the dealer listing is counted, or does not say its price is an asking price');
  if (!/Sold ?4/.test(one.tab)) wrong.push('1: the Sold tab does not count the four auction results');
  if (sold.filter((t) => t.includes('$108,000')).length !== 1) wrong.push('1: the $108,000 sale is there twice (the model\'s copy and the page\'s row)');
  if (sold.some((t) => /seller not named/.test(t))) wrong.push('1: the model\'s copy of a row is still there');

  // 2. what the app did, in the step log and in the requests
  const text = calls();
  const two = { wholeMarketOpened: /market page read by the app: tokens=24000 whole=True/.test(text), pcarmarketAsked: /only=\['pcarmarket\.com'\]/.test(text),
    find: await p.locator('.sheet-body .card', { hasText: '$108,000' }).locator('a.c-find').first().evaluate((a) => [a.textContent.trim().slice(0, 40), a.href]).catch(() => null) };
  log('2 the app read the page', two);
  if (!two.wholeMarketOpened) wrong.push('2: the app did not open the whole market page itself');
  if (!two.pcarmarketAsked) wrong.push('2: PCARMARKET was not searched for a Porsche');
  if (!two.find || !/Find this auction on Bring a Trailer/.test(two.find[0]) || !/site%3Abringatrailer\.com/.test(two.find[1]) || !/%24108%2C000/.test(two.find[1])) wrong.push('2: no search for the auction\'s own page on the $108,000 card');
  await p.locator('.sheet-tabs .tab[data-tab=case]').click(); await p.waitForTimeout(1200);
  const caseText = (await p.locator('.sheet-body').innerText()).replace(/\s+/g, ' ');
  const said = (caseText.match(/The app read Classic\.com's market page itself[^.]*\./) || [''])[0];
  log('3 summary', said);
  if (!/7 cars, 5 of them sold \(4 at auction\)/.test(said)) wrong.push('3: the summary does not say what the app read off the page');

  // 4. the no-sale at $86,000: paste the auction's own link, and the card takes what that page says
  await p.locator('.sheet-tabs .tab[data-tab=comps]').click(); await p.waitForTimeout(1200);
  const row = p.locator('.sheet-body .card', { hasText: 'Naples' }).first();
  const before = (await row.innerText()).replace(/\s+/g, ' ').slice(0, 160);
  await row.locator('.setlink input').fill('http://127.0.0.1:8898/auction/259826'); await row.locator('.setlink button').click();
  let t = ''; for (let i = 0; i < 60; i++) { await p.waitForTimeout(400); t = await toast(); if (t) break; }
  await p.waitForTimeout(2500);
  const after = (await cards()).find((c) => c.includes('Naples')) || '';
  log('4 pasted the auction link', { before, toast: t.slice(0, 260), after: after.slice(0, 260) });
  if (!/says sold for \$88,000, where the list had a high bid of \$86,000/.test(t)) wrong.push('4: the toast does not say what the auction page showed');
  if (!/\$88,000/.test(after) || !/Checked on the auction's own page: sold for \$88,000 on Aug 26, 2026/.test(after) || !/Sold/i.test(after.slice(0, 20))) wrong.push('4: the card did not become a sale at $88,000, checked on the page');
  await p.locator('.sheet-body .card', { hasText: 'Naples' }).first().evaluate((e) => e.scrollIntoView({ block: 'start' })).catch(() => {});
  await p.screenshot({ path: '/tmp/e2e/market.png', timeout: 120000 }).catch(() => {});
  log('errors', { exc: await p.locator('[data-testid="stException"]').count(), errs: errs.concat(wrong) });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
