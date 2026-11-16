// The shared garage: two devices with the same key show the same cars; the newer copy of a car wins; a removed car stays removed;
// another key sees nothing; a store that is down holds nothing up, and what was missed is sent when it is back.
const { chromium } = require('playwright');
const fs = require('fs');
const { execSync, spawn } = require('child_process');
let pagesOut = [];
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const log = (k, v) => console.log(k + ':', JSON.stringify(v));
  const errs = [], pages = []; pagesOut = pages;
  const dump = async () => (await fetch('http://127.0.0.1:8895/dump')).json();
  const searches = () => (fs.readFileSync('/tmp/e2e/calls.log', 'utf8').match(/budget:/g) || []).length;
  const device = async (key) => {
    const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1 });
    await ctx.route('https://api.sketchfab.com/**', (r) => r.abort());
    const p = await ctx.newPage(); pages.push(p); p.on('pageerror', e => errs.push(String(e).slice(0, 200)));
    await p.goto('http://localhost:8766/', { waitUntil: 'domcontentloaded', timeout: 90000 }); await p.waitForTimeout(18000);
    if (key) { await p.locator('.dockbar input[type=password]').fill(key); await p.locator('.dockbar .go').click(); await p.waitForTimeout(7000); }
    return p; };
  const see = async (p) => ({ chips: (await p.locator('.garage .chip').allInnerTexts()).map((t) => t.trim()), head: (await p.locator('.head').innerText()).replace(/\s+/g, ' ').slice(0, 70),
    tabs: (await p.locator('.tabs .tab').allInnerTexts()).slice(1, 3).map((t) => t.replace(/\s+/g, ' ')) });
  // One device draws at a time: the others wait on an empty page, as a phone in a pocket would. Coming back is a fresh visit.
  let exc = 0;
  const park = async (p) => { exc += await p.locator('[data-testid="stException"]').count(); await p.goto('about:blank'); };
  const reload = async (p) => { await p.goto('http://localhost:8766/', { waitUntil: 'domcontentloaded', timeout: 90000 }); await p.waitForTimeout(20000); };
  const settings = async (p) => { try { await p.locator('.gear').click({ timeout: 8000 }); } catch (e) { await p.screenshot({ path: '/tmp/e2e/shared_stuck.png' }); return 'could not open Settings'; } await p.waitForTimeout(1500); const t = await p.locator('[data-testid="stSidebar"]').innerText();
    await p.keyboard.press('Escape'); await p.locator('[data-testid="stSidebarCollapseButton"] button, [data-testid="stSidebarCollapseButton"]').first().click().catch(() => {}); await p.waitForTimeout(1000);
    return ((t.match(/Shared garage[\s\S]{0,330}/i) || ['no shared garage section'])[0]).replace(/\s+/g, ' ').slice(0, 300); };

  // device A builds a car
  const A = await device('sk-ant-test-sync1');
  await A.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/1'); await A.locator('.dockbar .go').click();
  for (let i = 0; i < 400; i++) { await A.waitForTimeout(500); if (!(await A.locator('.stage.busy').count()) && i > 6) break; }
  await A.waitForTimeout(5000);
  const one = { ...(await see(A)), store: await dump(), settings: await settings(A) };
  log('1 device A built a car', one);
  await park(A);

  // device B, same key, nothing in its browser: the car is there, with no search run
  const before = searches();
  const B = await device('sk-ant-test-sync1');
  await B.waitForTimeout(3000);
  const two = { ...(await see(B)), searchesRun: searches() - before };
  log('2 device B with the same key', two);

  // B changes the miles; A reloads and has the change
  await B.locator('.tabs .tab[data-tab=car]').click(); await B.waitForTimeout(1000);
  await B.locator('.sheet-body .carfacts input[name=miles]').fill('12,345'); await B.locator('.sheet-body .carfacts button[type=submit]').click();
  for (let i = 0; i < 60; i++) { await B.waitForTimeout(500); const t = await B.locator('.toast').evaluate((e) => (e.hidden ? '' : e.textContent)).catch(() => ''); if (/worked out again for/.test(t)) break; }
  await B.waitForTimeout(4000);
  const afterB = await dump();
  await park(B);
  await reload(A);
  const three = { storeMiles: afterB.rows.map((r) => r.miles), A: await see(A) };
  log('3 B changed the miles, A reloaded', three);

  // A removes the car; B reloads: gone there too, and B's own browser copy does not bring it back
  await A.locator('.garage .chipx').click(); await A.waitForTimeout(400); await A.locator('.garage .chipx').click(); await A.waitForTimeout(6000);
  const afterRemove = await dump();
  await park(A);
  await reload(B);
  const bAfter = await see(B);
  await park(B);
  await reload(B);
  const four = { store: afterRemove.rows.map((r) => [r.deleted, r.keys.length]), B: bAfter, BAgain: (await see(B)).chips, rowsNow: (await dump()).rows.length };
  log('4 A removed it, B reloaded twice', four);
  await park(B);

  // another key: another garage
  const C = await device('sk-ant-test-sync2');
  await C.waitForTimeout(2000);
  const five = await see(C);
  log('5 a device with another key', five);

  await park(C);
  await B.context().close(); await C.context().close();
  pagesOut.length = 1;
  await reload(A);

  // the store goes down: the app carries on; when it is back, what was missed is sent
  try { execSync('pkill -f "fake_d[b].py"'); } catch (e) {} await A.waitForTimeout(1000);
  await A.locator('.dockbar textarea').fill('http://127.0.0.1:8898/listing/21'); await A.locator('.dockbar .go').click();
  for (let i = 0; i < 400; i++) { await A.waitForTimeout(500); if (!(await A.locator('.stage.busy').count()) && i > 6) break; }
  await A.waitForTimeout(4000);
  const flip = () => A.evaluate(() => { const l = [...document.querySelectorAll('label')].find((x) => /Preview my private copy/.test(x.textContent)); const i = l && l.querySelector('input'); if (i) i.click(); return !!i; });
  await flip(); await A.waitForTimeout(3000);            // Settings says how the store stood at the last tap
  const down = { ...(await see(A)), settings: await settings(A) };
  spawn('python3', ['fake_db.py'], { cwd: '/tmp/e2e', detached: true, stdio: 'ignore' }).unref(); await A.waitForTimeout(5000);
  await flip(); await A.waitForTimeout(4000);            // any tap that reaches the app: the next run sends what was missed
  await flip(); await A.waitForTimeout(5000);
  const six = { down, storeAfter: (await dump()).rows.map((r) => [r.deleted, r.miles, r.comps]), settings: await settings(A) };
  log('6 store down while A built another car, then back', six);
  const wrong = [];
  const want = (ok, what) => { if (!ok) wrong.push(what); };
  want(one.chips.includes('M2 Competition') && one.store.rows.length === 1 && /On\. Every device/.test(one.settings), '1: the car was not built and saved');
  want(two.chips.includes('M2 Competition') && two.searchesRun === 0, '2: the second device did not get the car without searching');
  want(/12,345/.test(three.A.head) && three.storeMiles[0] === 12345 && three.A.chips.includes('M2 Competition'), '3: the change did not reach the first device');
  want(!four.B.chips.includes('M2 Competition') && !four.BAgain.includes('M2 Competition') && four.store[0][0] === true, '4: the removed car came back');
  want(!five.chips.includes('M2 Competition'), '5: another key saw the car');
  want(six.down.chips.includes('M2 Competition') && /Not saving just now/.test(six.down.settings), '6: the app did not carry on, or did not say the store was down');
  want(six.storeAfter.some((r) => r[0] === false && r[2] > 0) && /On\. Every device/.test(six.settings), '6: what was missed was not sent once the store was back');
  log('errors', { exc: (await A.locator('[data-testid="stException"]').count()) + exc, errs: errs.concat(wrong) });
  await b.close();
})().catch(async (e) => { console.log('TEST ERROR', String(e).slice(0, 900));
  for (let i = 0; i < pagesOut.length; i++) await pagesOut[i].screenshot({ path: '/tmp/e2e/shared_stuck' + i + '.png' }).catch(() => {});
  process.exit(1); });
