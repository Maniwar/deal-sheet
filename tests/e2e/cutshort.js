// A run cut short by the next tap must not lose the car it was loading. The app is started so that it waits two seconds
// before drawing a car it has just loaded; meanwhile this test flips a switch on the page, which cuts that run short.
// Before the fix, the browser's older fields then replaced the car: the sample was saved under the car's name.
// Run as cutshort_shared.js the same happens with the garage store on, where the wrong car would have gone to every device.
const { chromium } = require('playwright');
const shared = /shared/.test(process.argv[1]);
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  const errs = [];
  const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
  await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
  const p = await ctx.newPage(); p.on('pageerror', e => errs.push(String(e).slice(0, 200)));
  const saved = async () => (shared ? (await (await fetch('http://127.0.0.1:8895/dump')).json()).saved.map((s) => s[1] + ' ' + s[2]) : []);
  const see = async () => ({ chips: (await p.locator('.garage .chip').allInnerTexts()).map((t) => t.trim()), head: (await p.locator('.head .title').innerText()).replace(/\s+/g, ' ') + ' · ' + (await p.locator('.head .sub').innerText()).replace(/\s+/g, ' ').slice(0, 44) });
  const wrong = [];
  const check = (step, state, onScreen) => {                 // the car must still be the car: by name in the garage, on screen, and in what was sent to the store
    if (!state.chips.includes('M2 Competition') || state.chips.includes('911 Carrera S')) wrong.push(step + ': garage shows ' + state.chips.join(', '));
    if (onScreen && !onScreen.test(state.head)) wrong.push(step + ': on screen ' + state.head);
    for (const sent of state.sentToStore || []) if (!/^M2 /.test(sent)) wrong.push(step + ': sent to the store ' + sent);
    return state; };
  const flip = () => p.evaluate(() => { const l = [...document.querySelectorAll('label')].find((x) => /Preview my private copy/.test(x.textContent)); const i = l && l.querySelector('input'); if (i) i.click(); return !!i; }).catch(() => false);
  await p.goto('http://localhost:8766/', { waitUntil: 'networkidle' }); await p.waitForTimeout(14000);
  await p.locator('.dockbar input[type=password]').fill('sk-ant-test-cut1'); await p.locator('.dockbar .go').click(); await p.waitForTimeout(7000);
  await p.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/1'); await p.locator('.dockbar .go').click();
  for (let i = 0; i < 400; i++) { await p.waitForTimeout(500); if (!(await p.locator('.stage.busy').count()) && i > 6) break; }
  await p.waitForTimeout(8000);
  log('1 built', await see());
  for (let round = 2; round <= 3; round++) {              // twice: the second time starts from whatever the first left in the browser
    await p.reload({ waitUntil: 'domcontentloaded' });
    let flips = 0;
    for (let i = 0; i < 60; i++) { await p.waitForTimeout(250); if (await flip()) flips++; }      // 15 seconds of taps while the garage comes back
    await p.waitForTimeout(9000);
    log(round + ' reloaded with taps arriving mid-run', check(round, { flips, ...(await see()), sentToStore: await saved() }, /M2 Competition/));
  }
  await p.reload({ waitUntil: 'domcontentloaded' }); await p.waitForTimeout(20000);
  log('4 reloaded quietly', check(4, { ...(await see()), sentToStore: await saved() }, /M2 Competition/));
  // switching between cars with taps arriving mid-run
  for (let k = 0; k < 2; k++) {
    await p.locator('.garage .chip:not(.on):not(.add)').first().click();
    for (let i = 0; i < 24; i++) { await p.waitForTimeout(250); await flip(); }
    await p.waitForTimeout(5000);
    log('5 switched car with taps arriving mid-run', check(5, await see(), k ? /M2 Competition/ : /911 Carrera S/));
  }
  await p.reload({ waitUntil: 'domcontentloaded' }); await p.waitForTimeout(20000);
  log('6 reloaded quietly', check(6, { ...(await see()), sentToStore: await saved() }, /M2 Competition/));
  log('errors', { exc: await p.locator('[data-testid="stException"]').count(), errs: errs.concat(wrong) });
  await b.close();
})().catch(e => { console.log('TEST ERROR', String(e).slice(0, 900)); process.exit(1); });
