const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "");
const money = (v) => "$" + Math.round(v).toLocaleString("en-US");
const ARROW = '<svg viewBox="0 0 12 12" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9 9 3M4.2 3H9v4.8"/></svg>';
const ICON_SEND = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';
const ICON_PIC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="5" width="17" height="14" rx="3"/><circle cx="9" cy="10" r="1.6"/><path d="m5 17 5-4.5 3.5 3 2.5-2 3.5 3.5"/></svg>';
const STEPS = ["Reading the listing", "Finding recent sales", "Working out your offer", "Writing the message"];
const KEY_SLOT = "dealsheet.key";
const PREFS_SLOT = "dealsheet.prefs";

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  let d = {};
  try { d = typeof data === "string" ? JSON.parse(data) : (data || {}); } catch (e) { d = {}; }
  const root = parentElement.querySelector(".stage");
  if (!root) return;
  const S = root.__st || (root.__st = create(root));
  S.send = setTriggerValue;
  S.update(d);
}

/* ------------------------------------------------------------------ storage on this device */
const store = {
  db: null,
  open() {
    if (this.db) return this.db;
    this.db = new Promise((done, fail) => {
      const req = indexedDB.open("dealsheet", 1);
      req.onupgradeneeded = () => req.result.createObjectStore("garage");
      req.onsuccess = () => done(req.result);
      req.onerror = () => fail(req.error);
    });
    return this.db;
  },
  async run(mode, fn) {
    const db = await this.open();
    return new Promise((done, fail) => {
      const tx = db.transaction("garage", mode), out = fn(tx.objectStore("garage"));
      tx.oncomplete = () => done(out && "result" in out ? out.result : undefined);
      tx.onerror = () => fail(tx.error);
    });
  },
  get(key) { return this.run("readonly", (s) => s.get(key)); },
  set(key, value) { return this.run("readwrite", (s) => s.put(value, key)); },
  del(key) { return this.run("readwrite", (s) => s.delete(key)); },
  keys() { return this.run("readonly", (s) => s.getAllKeys()); },
};

/* ------------------------------------------------------------------ the screen */
function create(root) {
  const $ = (q) => root.querySelector(q);
  const S = { d: {}, offer: {}, busy: false, shot: "", tab: "", outbox: [], waiting: false, remember: true, known: new Set() };   /* known: the cars this page has shown */
  const el = { garage: $(".garage"), head: $(".head"), verdict: $(".verdict"), rail: $(".rail"), legend: $(".legend"), track: $(".track"), nums: $(".nums"),
    tabs: $(".tabs"), dock: $(".dockbar"), pop: $(".pop"), sheet: $(".sheet"), sheetTabs: $(".sheet-tabs"), sheetBody: $(".sheet-body"),
    scrim: $(".scrim"), light: $(".lightbox"), toast: $(".toast"), photo: $(".photo"), progress: $(".progress"), empty: $(".empty"), live: $(".liveview"), shadow: $(".liveshadow"), zone: $(".zone"), picker: $(".pick3d") };

  /* one message to Python at a time: each one makes the app run again */
  /* A name for this browser, kept on the device. Work it starts is filed under it on the server, so a page that
     comes back as a new visit (reloaded, or reconnected after the phone slept) finds that work instead of asking again. */
  const CID = (() => {
    let id = ""; try { id = localStorage.getItem("dealsheet.client") || ""; } catch (e) {}
    if (!/^[0-9a-f]{16}$/.test(id)) { id = Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => b.toString(16).padStart(2, "0")).join(""); try { localStorage.setItem("dealsheet.client", id); } catch (e) {} }
    return id;
  })();
  const post = (name, value) => { if (["build", "more", "verify", "prefs", "reoffer", "version"].includes(name) && value && typeof value === "object" && !Array.isArray(value)) value = { ...value, cid: CID }; S.outbox.push([name, value]); pump(); };
  const pump = () => { if (S.waiting || !S.outbox.length || !S.send) return; const [name, value] = S.outbox.shift(); S.waiting = true; clearTimeout(S.waitTimer); S.waitTimer = setTimeout(() => { S.waiting = false; pump(); }, 4000); S.send(name, value); };

  let toastTimer = 0;
  const toast = (text, bad, ms) => { el.toast.style.top = ($(".zone").offsetTop + 6) + "px"; el.toast.textContent = text; el.toast.className = "toast" + (bad ? " bad" : ""); el.toast.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.toast.hidden = true; }, ms || 7000); };
  el.toast.onclick = () => { el.toast.hidden = true; };
  S.toastOut = (text) => toast(text, true, 12000);

  /* ---------- top bar ---------- */
  function paintTop(d) {
    /* the car on screen carries a small cross: two taps take it out of the garage */
    const chips = (d.garage || []).map((c) => `<button type="button" class="chip${c.active ? " on" : ""}" data-id="${esc(c.id)}">${esc(c.label)}</button>` +
      (c.active && (d.hasCar || (d.garage || []).length > 1) ? `<button type="button" class="chipx" data-drop="${esc(c.id)}" aria-label="Remove ${esc(c.label)} from the garage">×</button>` : "")).join("");
    el.garage.innerHTML = chips + '<button type="button" class="chip add" data-add="1">+ Add a car</button>';
    /* keep the car on screen, and the cross that removes it, in view: the row scrolls sideways */
    const on = el.garage.querySelector(".chip.on"), cross = el.garage.querySelector(".chipx") || on;
    if (on) {
      const left = on.offsetLeft - el.garage.offsetLeft, right = cross.offsetLeft - el.garage.offsetLeft + cross.offsetWidth, room = el.garage.clientWidth;
      if (right > el.garage.scrollLeft + room) el.garage.scrollLeft = right - room + 6;
      if (left < el.garage.scrollLeft) el.garage.scrollLeft = Math.max(0, left - 6);
    }
  }
  el.garage.onclick = (e) => {
    const x = e.target.closest(".chipx");
    if (x) {
      if (S.busy) return;
      if (x.dataset.sure) { x.disabled = true; S.switching = "-"; post("remove", { id: x.dataset.drop, at: Date.now() }); return; }
      x.dataset.sure = "1"; x.textContent = "Remove?"; x.classList.add("sure");
      setTimeout(() => { if (x.isConnected) { delete x.dataset.sure; x.textContent = "×"; x.classList.remove("sure"); } }, 4000);
      return;
    }
    const b = e.target.closest(".chip"); if (!b || S.busy) return;
    if (b.dataset.add) { focusBar(); return; }
    if (!b.classList.contains("on")) { el.garage.querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", c === b)); S.switching = b.dataset.id; post("switch", b.dataset.id); }
  };
  const openSettings = () => {
    const btn = document.querySelector('[data-testid="stExpandSidebarButton"]') || document.querySelector('[data-testid="stSidebarCollapsedControl"] button') || document.querySelector('[data-testid="stSidebarCollapsedControl"]');
    if (btn) btn.click();
  };
  $(".gear").onclick = openSettings;

  /* the listing photo opens large; with no photo, the tile adds one; the missing-options chip opens the case */
  const photoPick = document.createElement("input"); photoPick.type = "file"; photoPick.accept = "image/*"; photoPick.hidden = true; root.appendChild(photoPick);
  photoPick.onchange = async () => {
    const f = photoPick.files[0]; photoPick.value = ""; if (!f) return;
    try {
      const bmp = await createImageBitmap(f), k = Math.min(1, 1400 / Math.max(bmp.width, bmp.height));
      const c = document.createElement("canvas"); c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
      c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
      post("photo", { image: c.toDataURL("image/jpeg", 0.86) });
    } catch (e) { toast("That picture could not be read. Try a PNG or JPG.", true); }
  };
  el.head.addEventListener("click", (e) => {
    const shot = e.target.closest(".shot");
    if (shot) { if (shot.classList.contains("add")) photoPick.click(); else { el.light.querySelector("img").src = S.d.photo; el.light.hidden = false; } return; }
    if (e.target.closest(".addopts")) { openSheet("case"); setTimeout(() => { const box = el.sheetBody.querySelector(".optbox"); if (box) { el.sheetBody.scrollTop = Math.max(0, box.offsetTop - 120); box.focus({ preventScroll: true }); } }, 380); }
  });

  /* a VIN, shown in full; a tap copies it */
  const vinChip = (vin, cls, ok, year) => `<button type="button" class="vin${cls ? " " + cls : ""}${ok === "ok" ? " good" : ok === "off" ? " odd" : ""}" data-vin="${esc(vin)}" title="${ok === "ok" ? "Copy the VIN. Its check digit is right and it is a " + esc(year) + " model year." : "Copy the VIN"}"><b>VIN</b>${esc(vin)}${ok === "ok" ? '<i class="tick" aria-label="checks out">✓</i>' : ""}</button>` +
    (ok === "off" ? `<span class="vinwarn">This VIN is for a ${esc(year)} model year, not the year in the title. Check it.</span>` : "");
  root.addEventListener("click", (e) => {
    const chip = e.target.closest && e.target.closest(".vin"); if (!chip || !chip.dataset.vin) return;
    e.preventDefault(); e.stopPropagation();
    const vin = chip.dataset.vin || "";
    const done = () => toast("VIN copied: " + vin);
    try { navigator.clipboard.writeText(vin).then(done, () => toast("VIN: " + vin)); } catch (_) { toast("VIN: " + vin); }
  });

  /* ---------- title ---------- */
  function paintHead(d) {
    if (S.busy) { el.head.innerHTML = `<h1 class="title">Building your deal sheet</h1><div class="sub">${esc(S.asked || "")}</div>`; return; }
    if (!d.hasCar) { el.head.innerHTML = ""; return; }
    const c = d.case || {};
    let row = d.sample ? '<span class="tag">Sample car</span>' : "";
    let shot = "";
    if (d.photo) shot = `<button type="button" class="shot" aria-label="Open the listing photo"><img src="${esc(d.photo)}" alt=""><span>Listing photo</span></button>`;
    else if (d.listed && !d.sample) shot = '<button type="button" class="shot add" aria-label="Add a photo of this car"><b>+</b><span>Add photo</span></button>';
    if (d.vin) row += vinChip(d.vin);
    else if (d.listed) row += '<span class="opt none">VIN not listed</span>';
    if (d.history) row += `<span class="opt ${d.histFlag === "bad" ? "bad" : d.histFlag === "clean" ? "good" : ""}">${esc(d.history.length > 46 ? d.history.slice(0, 44) + "…" : d.history)}</span>`;
    else if (d.listed) row += '<span class="opt none">Accident history not stated</span>';
    if ((c.options || []).length) row += c.options.slice(0, 3).map((o) => `<span class="opt">${esc(o)}</span>`).join("") + (c.options.length > 3 ? `<span class="opt">+${c.options.length - 3} more</span>` : "");
    else if (d.listed) row += '<button type="button" class="opt none addopts">Options missing: add</button>';
    if (c.msrp) row += `<span class="opt">Sticker ${esc(c.msrp)}</span>`;
    if (d.seller) row += `<span class="seller">${esc(d.seller)}</span>`;
    el.head.innerHTML = `${shot}<h1 class="title">${esc(d.title)}</h1><div class="sub">${(d.chips || []).map(esc).join(" · ")}</div><div class="opts">${row}</div>`;
  }

  /* ---------- price and the one-line case ---------- */
  let shownNumber = null, numberTimer = 0;
  function countTo(node, target, text) {
    cancelAnimationFrame(numberTimer);
    if (shownNumber == null || !target || matchMedia("(prefers-reduced-motion:reduce)").matches) { node.textContent = text; shownNumber = target || null; return; }
    const from = shownNumber, t0 = performance.now();
    const tick = (now) => { const k = Math.min((now - t0) / 650, 1), e = 1 - Math.pow(1 - k, 3); node.textContent = money(from + (target - from) * e); if (k < 1) numberTimer = requestAnimationFrame(tick); else { node.textContent = text; shownNumber = target; } };
    numberTimer = requestAnimationFrame(tick);
  }
  function paintVerdict(d) {
    if (S.busy || !d.hasCar) { el.verdict.innerHTML = ""; shownNumber = null; return; }
    const url = safeUrl(d.url), c = d.case || {};
    const gap = d.gap && d.gap.text ? `<span class="gap is-${esc(d.gap.tone)}">${esc(d.gap.text)}</span>` : "";
    const link = url ? `<a class="listing" href="${esc(url)}" target="_blank" rel="noopener">Open the listing ${ARROW}</a>` : "";
    const why = c.line ? `<button type="button" class="why">${esc(c.line)} <b>See the case</b></button>` : "";
    el.verdict.innerHTML = `<div class="lbl">${esc(d.priceLabel || "Asking")}</div><div class="num"></div><div class="side">${gap}<span class="rslot"></span>${link}</div><div class="rlog" hidden></div>${why}`;
    countTo(el.verdict.querySelector(".num"), d.priceValue, d.priceText || "");
    const w = el.verdict.querySelector(".why"); if (w) w.onclick = () => openSheet("case");
    paintRefresh();
  }
  /* Refresh: every search again for the car on screen, one tap, with what is happening shown under the price */
  const TURN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.6-5.9"/><path d="M20 4v5h-5"/></svg>';
  function paintRefresh() {
    const slot = el.verdict.querySelector(".rslot"), lines = el.verdict.querySelector(".rlog");
    if (!slot) return;
    const on = S.moreBusy === "all";
    slot.innerHTML = `<button type="button" class="refresh${on ? " on" : ""}"${S.moreBusy ? " disabled" : ""} title="Search again for sales and cars for sale">${TURN}${on ? `Refreshing <span class="rclock">${clock()}</span>` : "Refresh results"}</button>`;
    if (lines) { lines.hidden = !on; lines.innerHTML = on ? `<div class="livelog">${logHtml(1) || "<div class=\"now\">Starting</div>"}</div>` : ""; }
    slot.querySelector(".refresh").onclick = refreshAll;
  }
  function refreshAll() {
    if (S.busy || S.moreBusy || !S.d.hasCar) return;
    if (!S.d.connected) {                                    /* the key goes in the bar at the bottom */
      toast("Connect your Anthropic API key in the bar below, then tap Refresh results.", true);
      const key = el.dock.querySelector("input[type=password]"); if (key) key.focus();
      return;
    }
    S.moreBusy = "all"; S.busyAt = Date.now(); S.log = [];
    post("more", { kind: "all", at: Date.now() });
    paintRefresh();
    if (S.tab === "case") renderSheet();
  }

  /* ---------- the price line ---------- */
  const pos = (v) => { const a = S.d.axis; return Math.max(0, Math.min(100, ((v - a.lo) / (a.hi - a.lo)) * 100)); };
  let dotsKey = "";
  function paintRail(d) {
    const a = d.axis;
    el.rail.hidden = S.busy || !a || !d.hasCar;
    if (el.rail.hidden) { dotsKey = ""; return; }
    if (!S.dragging) S.offer = { open: d.offer.open || null, target: d.offer.target || null, walk: d.offer.walk || null };
    const width = el.track.clientWidth || 340;
    const key = JSON.stringify([a.lo, a.hi, d.ask, a.median, Math.round(width / 40), !!(d.offer.target || d.offer.open), (d.comps || []).map((k) => [k.price, k.group, k.use, k.trust])]);
    if (key !== dotsKey) {
      const fresh = dotsKey === "" || key.length !== dotsKey.length;
      dotsKey = key;
      let h = '<div class="line"></div><div class="band"></div>';
      h += (a.ticks || []).map((t) => `<span class="tick" style="left:${pos(t.v)}%">${esc(t.label)}</span>`).join("");
      if (a.median) h += `<div class="medmark" style="left:${pos(a.median)}%"></div>`;
      if (d.ask) h += `<div class="askmark" style="left:${pos(d.ask)}%"><span>ASK</span></div>`;
      // cars priced close together stack upward, so each one stays visible
      const comps = d.comps || [], near = (13 / width) * 100, placed = [], level = {};
      comps.map((k, i) => i).sort((x, y) => comps[x].price - comps[y].price || x - y).forEach((i) => {
        const x = pos(comps[i].price); let lv = 0;
        while (lv < 2 && placed.some((q) => q.lv === lv && Math.abs(q.x - x) < near)) lv++;
        placed.push({ x, lv }); level[i] = lv;
      });
      h += comps.map((k, i) => `<button type="button" class="dot ${esc(k.status)} t${k.trust || 3}${k.use && k.group !== "ended" ? "" : " off"}${fresh ? "" : " in"}" data-i="${i}" style="left:${pos(k.price)}%;top:${40 - level[i] * 13}px" aria-label="${esc(k.label)} ${esc(k.priceText)}"></button>`).join("");
      const has = (s) => comps.some((k) => k.group === s);
      const tier = (n) => comps.some((k) => (k.trust || 3) === n);
      el.legend.innerHTML = (has("sold") ? '<span><i class="sold"></i>Sold</span>' : "") + (has("high_bid") ? '<span><i class="high_bid"></i>No sale</span>' : "") +
        (has("live") ? '<span><i class="asking"></i>For sale now</span>' : "") + (a.median ? `<span><i class="med"></i>Median sale ${esc(a.medianText)}</span>` : "") +
        '<span class="lg-break"></span>' + (tier(1) ? '<span><i class="t1"></i>Own page + VIN</span>' : "") + (tier(2) ? '<span><i class="t2"></i>To confirm</span>' : "") + (tier(3) ? '<span><i class="t3"></i>Not checkable</span>' : "");
      h += '<button type="button" class="knob open" data-k="open" aria-label="Opening offer"></button><button type="button" class="knob walk" data-k="walk" aria-label="Walk-away price"></button><button type="button" class="knob target" data-k="target" aria-label="Target price"></button>';
      el.track.innerHTML = h;
      if (fresh) el.track.querySelectorAll(".dot").forEach((dot, i) => setTimeout(() => dot.classList.add("in"), 250 + i * 90));
    }
    place();
  }
  function place() {
    const o = S.offer, band = el.track.querySelector(".band");
    for (const k of ["open", "target", "walk"]) { const knob = el.track.querySelector(".knob." + k); if (!knob) continue; knob.hidden = !o[k]; if (o[k]) knob.style.left = pos(o[k]) + "%"; }
    const lo = o.open || o.target, hi = o.walk || o.target;
    if (band) { band.style.display = lo && hi && hi > lo ? "" : "none"; if (lo && hi) { band.style.left = pos(lo) + "%"; band.style.width = Math.max(0, pos(hi) - pos(lo)) + "%"; } }
    paintNums();
  }
  function paintNums() {
    const o = S.offer, m = S.d.money || {}, price = o.target || o.open;
    let otd = "", per = "";
    if (price) {
      const total = price * (1 + (m.tax || 0) / 100) + (m.fees || 0); otd = money(total);
      const loan = Math.max(total - (m.down || 0), 0), r = (m.apr || 0) / 1200, n = m.months || 0;
      if (n > 0 && loan > 0) per = "about " + money(r ? (loan * r) / (1 - Math.pow(1 + r, -n)) : loan / n) + "/mo";
    }
    const cell = (cls, k, v, s) => `<div class="${cls}"><div class="k">${k}</div><div class="v">${v || "n/a"}</div><div class="s">${s}</div></div>`;
    el.nums.innerHTML = cell("open", "Open", o.open && money(o.open), "first offer") + cell("target", "Target", o.target && money(o.target), "where to close") +
      cell("walk", "Walk away", o.walk && money(o.walk), "the ceiling") + cell("otd", "Out the door", otd, per || "at target, with tax");
  }
  /* drag a handle along the line */
  el.track.addEventListener("pointerdown", (e) => {
    const knob = e.target.closest(".knob");
    if (knob) {
      e.preventDefault(); if (S.busy) return;
      S.dragging = knob.dataset.k; knob.classList.add("live"); try { knob.setPointerCapture(e.pointerId); } catch (_) {}
      el.pop.hidden = true; return;
    }
    const dot = e.target.closest(".dot");
    if (dot) showComp(+dot.dataset.i, dot); else el.pop.hidden = true;
  });
  el.track.addEventListener("pointermove", (e) => {
    if (!S.dragging) return;
    const r = el.track.getBoundingClientRect(), a = S.d.axis, span = a.hi - a.lo, step = span > 40000 ? 500 : span > 8000 ? 250 : 100;
    let v = a.lo + Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * span;
    v = Math.round(v / step) * step;
    const o = S.offer, k = S.dragging;
    if (k === "open") v = Math.min(v, (o.target || o.walk || v));
    if (k === "target") v = Math.max(Math.min(v, o.walk || v), o.open || v);
    if (k === "walk") v = Math.max(v, (o.target || o.open || v));
    o[k] = v; place();
  });
  const drop = () => {
    if (!S.dragging) return;
    el.track.querySelectorAll(".knob").forEach((k) => k.classList.remove("live"));
    const o = S.offer; S.dragging = "";
    const was = S.d.offer || {};
    if (o.open !== (was.open || null) || o.target !== (was.target || null) || o.walk !== (was.walk || null)) post("offer", { open: o.open, target: o.target, walk: o.walk });
  };
  el.track.addEventListener("pointerup", drop); el.track.addEventListener("pointercancel", drop);

  /* ---------- a comp, as a card ---------- */
  const compCard = (k, big) => {
    const url = safeUrl(k.url);
    const flag = k.kind === "find" ? ""                      /* the fold it sits in says what it is */
      : k.proof === "listed" ? (k.seen === "listed" ? "" : '<div class="c-flag">Read from a listing site\'s results, with its VIN. The link opens those results, not this car alone.</div>')
      : k.kind === "page" ? '<div class="c-flag">This link opens a results page, not this car.</div>' : (k.linkOk === false ? '<div class="c-flag">Link not confirmed. Open it before you cite it.</div>' : "");
    /* what the last look at its page found, and what that rests on */
    const because = k.seenWhy ? ` (${esc(k.seenWhy)})` : "";
    const seen = k.kind === "find" ? "" : k.group === "ended" ? (k.seen === "gone" && k.seenWhy ? `<div class="c-seen">Checked ${esc(k.seenOn)}: no longer for sale${because}.</div>` : "")
      : k.group !== "live" ? "" : k.seen === "live" ? `<div class="c-seen ok">Checked ${esc(k.seenOn)}: still for sale${because || " (the page still shows it)"}.</div>`
      : k.seen === "listed" && k.proof === "listed" ? `<div class="c-seen">Checked ${esc(k.seenOn)}: ${esc(k.seenWhy || "seen on a listing site")}, with its VIN. The link opens those results, not this car alone: find it there by VIN or dealer, or call the dealer with the VIN. Listing sites can run days behind the dealer.</div>`
      : k.seen === "listed" ? `<div class="c-seen">Checked ${esc(k.seenOn)}: ${esc(k.seenWhy || "a site that copies listings still shows it")}. That site copies sellers' listings and can be days behind, so open it to be sure.</div>`
      : k.seen === "unknown" ? `<div class="c-seen">Checked ${esc(k.seenOn)}: could not confirm it is still for sale${because}. Open it to check.</div>`
      : '<div class="c-seen">Not checked yet. Tap Check they are still for sale.</div>';
    const out = big && k.group === "sold" && !k.use, flip = big && k.group === "sold" ? `<button type="button" class="textbtn usebtn" data-i="${k.idx}" data-price="${k.price}" data-use="${k.use ? 0 : 1}">${k.use ? "Leave it out" : "Count it"}</button>` : "";
    const text = `<div><i class="tdot t${k.trust || 3}" title="${k.trust === 1 ? "Opens on its own page, has a VIN, nothing left to confirm" : k.trust === 2 ? (k.proof === "listed" ? "Read from a listing site's results, with its VIN" : "Opens on its own page, with something left to confirm") : "Nothing to open and check"}"></i><span class="pill ${esc(k.group)}${k.unsure ? " unsure" : ""}">${esc(k.label)}</span>${out ? `<span class="pill out">Not counted: ${esc(k.why)}</span>` : ""}<span class="c-price">${esc(k.priceText)}</span>${k.delta ? `<span class="c-delta">${esc(k.delta)}</span>` : ""}` +
      `<div class="c-title">${esc(k.title)}</div><div class="c-meta">${esc(k.meta)}</div><div>${k.vin ? vinChip(k.vin, "c-vin", k.vinOk, k.vinYear) : '<span class="vin none c-vin"><b>VIN</b>not found</span>'}</div>${k.options ? `<div class="c-note">Options: ${esc(k.options)}</div>` : ""}${k.note ? `<div class="c-note">${esc(k.note)}</div>` : ""}${k.gearFlag ? '<div class="c-flag">Manual or automatic is not stated. Check before you count on it.</div>' : ""}${k.history ? `<div class="c-hist ${esc(k.histFlag)}">${k.histFlag === "bad" ? "⚠ " : ""}${esc(k.history)}</div>` : ""}${seen}${flag}` +
      (url ? `<a class="c-link" href="${esc(url)}" target="_blank" rel="noopener">${k.kind === "find" ? "Find it on Marketplace" : k.kind === "page" ? "Open the results" : "Open"} ${ARROW} <small>${esc(k.kind === "find" ? "" : k.host)}</small></a>` : "") +
      /* seen on a listing site, with a VIN: one tap to find the seller's own page for it */
      (k.group === "live" && k.vin && k.vinOk === "ok" && (k.seen === "listed" || k.proof === "listed") ? `<a class="c-find" href="https://www.google.com/search?q=%22${encodeURIComponent(k.vin)}%22" target="_blank" rel="noopener">Find the seller's page by VIN ${ARROW}</a>` : "") +
      (big && (k.proof === "list" || k.proof === "listed" || k.proof === "loose" || k.proof === "none") ? `<form class="linkrow setlink" data-i="${k.idx}" data-price="${k.price}"><input type="url" class="linkbox" placeholder="${k.kind === "find" ? "Found it? Share, Copy link, paste here" : "Have its own link? Paste it here"}" inputmode="url" aria-label="This car's own link"><button type="submit" class="btn ghost">Save</button></form>` : "") +
      (flip ? `<div>${flip}</div>` : "") + "</div>";
    return big ? `<div class="card${k.use ? "" : " off"}">${text}${k.image ? `<img src="${esc(k.image)}" alt="" loading="lazy">` : "<span></span>"}</div>` : text;
  };
  function showComp(i, dot) {
    const k = (S.d.comps || [])[i]; if (!k) return;
    el.track.querySelectorAll(".dot").forEach((x) => x.classList.toggle("sel", x === dot));
    el.pop.innerHTML = compCard(k, false); el.pop.hidden = false;
    const R = root.getBoundingClientRect(), D = dot.getBoundingClientRect(), w = el.pop.offsetWidth, h = el.pop.offsetHeight;
    el.pop.style.left = Math.max(10, Math.min(R.width - w - 10, D.left - R.left + D.width / 2 - w / 2)) + "px";
    el.pop.style.top = Math.max(10, D.top - R.top - h - 14) + "px";
  }
  root.addEventListener("pointerdown", (e) => { if (!el.pop.hidden && !e.target.closest(".pop") && !e.target.closest(".dot")) { el.pop.hidden = true; el.track.querySelectorAll(".dot.sel").forEach((x) => x.classList.remove("sel")); } });

  /* ---------- tabs and the sheet ---------- */
  const counts = (d) => [(d.comps || []).filter((k) => k.group === "sold" && k.use).length, (d.comps || []).filter((k) => k.group === "live" && !k.lead).length];
  function paintTabs(d) {
    if (S.busy || !d.hasCar) { el.tabs.innerHTML = ""; return; }
    const c = d.case || {}, [nSold, nSale] = counts(d);
    el.tabs.innerHTML = `<button type="button" class="tab${(c.reasons || []).length ? " lead" : ""}" data-tab="case">The case</button>` +
      `<button type="button" class="tab" data-tab="comps">Sold<b>${nSold}</b></button>` +
      `<button type="button" class="tab" data-tab="sale">For sale now<b>${nSale}</b></button>` +
      `<button type="button" class="tab" data-tab="message">Message</button>` +
      `<button type="button" class="tab" data-tab="car">Car details</button>` +
      `<button type="button" class="tab" data-tab="model">3D model</button>` +
      `<button type="button" class="tab" data-tab="details">Edit and print ↓</button>`;
  }
  el.tabs.onclick = (e) => { const b = e.target.closest(".tab"); if (!b) return; if (b.dataset.tab === "details") { const t = document.querySelector(".st-key-details"); if (t) t.scrollIntoView({ behavior: "smooth", block: "start" }); } else openSheet(b.dataset.tab); };
  function openSheet(tab) { S.tab = tab; renderSheet(); el.sheet.classList.add("open"); el.sheet.setAttribute("aria-hidden", "false"); el.scrim.hidden = false; el.pop.hidden = true; }
  function closeSheet() { S.tab = ""; el.sheet.classList.remove("open"); el.sheet.setAttribute("aria-hidden", "true"); el.scrim.hidden = true; }
  $(".close").onclick = closeSheet; el.scrim.onclick = closeSheet;
  el.sheetTabs.onclick = (e) => { const b = e.target.closest(".tab"); if (b) { S.tab = b.dataset.tab; renderSheet(); } };
  function renderSheet() {
    const d = S.d, c = d.case || {}, [nSold, nSale] = counts(d);
    const sort = S.sort || (S.sort = { key: "trust", dir: 1 });
    /* most reliable first: own page with a VIN, then own page, then the rest; newest first within each. Cars missing a value go last. */
    const order = (x, y) => { if (sort.key === "trust") return ((x.trust || 3) - (y.trust || 3)) * sort.dir || (x.group === "live" ? ({ live: 0, listed: 1 }[x.seen] ?? 2) : 0) - (y.group === "live" ? ({ live: 0, listed: 1 }[y.seen] ?? 2) : 0) || (y.when || 0) - (x.when || 0) || x.price - y.price;
      const p = x[sort.key] || 0, q = y[sort.key] || 0; if (!p || !q) return (q ? 1 : 0) - (p ? 1 : 0); return (p - q) * sort.dir; };
    const list = (groups, title, only, lead) => { const rows = (d.comps || []).filter((k) => groups.includes(k.group) && (!only || only(k))).sort(order); return rows.length ? `<h3>${title} · ${rows.length}</h3>${lead || ""}` + rows.map((k) => compCard(k, true)).join("") : ""; };
    const arrow = (key) => (sort.key === key ? (sort.dir > 0 ? " ↑" : " ↓") : "");
    const sorter = `<div class="sortrow">Sort by ${[["trust", "Most reliable"], ["price", "Price"], ["miles", "Miles"], ["when", "Date"]].map(([key, name]) => `<button type="button" class="sortbtn${sort.key === key ? " on" : ""}" data-sort="${key}">${name}${arrow(key)}</button>`).join("")}</div>`;
    el.sheetTabs.innerHTML = [["case", "The case"], ["comps", `Sold<b>${nSold}</b>`], ["sale", `For sale now<b>${nSale}</b>`], ["message", "Message"], ["car", "Car details"], ["model", "3D model"]].map(([id, t]) => `<button type="button" class="tab${S.tab === id ? " lead" : ""}" data-tab="${id}">${t}</button>`).join("");
    let h = "";
    if (d.connected) S.needKey = "";
    /* something here needs the key: ask for it on the spot, then carry on with what was asked */
    const keyAsk = S.needKey === S.tab ? '<div class="hintbox">That needs your Anthropic API key. Paste it here and it carries on.</div><form class="linkrow keyform"><input type="password" class="linkbox keybox" autocomplete="off" placeholder="Paste your Anthropic API key" aria-label="Anthropic API key"><button type="submit" class="btn">Connect</button></form>' +
      '<div class="tiny"><label><input type="checkbox" class="keykeep" checked> Remember it on this device</label> · <a href="https://platform.claude.com/settings/keys" target="_blank" rel="noopener">Get a key</a> · Used only to call Anthropic. Billed to your key.</div>' : "";
    const liveLog = (on) => (on ? `<div class="livelog">${logHtml(5)}</div>` : "");
    const byHand = (kind) => `<details class="byhand"${S.handOpen === kind ? " open" : ""}><summary>${kind === "sold" ? "Add a sale you know of" : "Add a car for sale you know of"}</summary><form class="carform handform" data-kind="${kind}">` +
      `<label class="fld"><span>${kind === "sold" ? "Sold for" : "Asking"}</span><input class="linkbox" name="price" inputmode="numeric" placeholder="$"></label><label class="fld"><span>Miles</span><input class="linkbox" name="miles" inputmode="numeric"></label>` +
      `<label class="fld wide"><span>Car</span><input class="linkbox" name="title" value="${esc(d.title || "")}"></label>` +
      (kind === "sold" ? '<label class="fld"><span>Date sold</span><input class="linkbox" name="date" placeholder="Jun 3, 2026"></label>' : "") +
      `<label class="fld${kind === "sold" ? "" : " wide"}"><span>VIN</span><input class="linkbox" name="vin" autocapitalize="characters" spellcheck="false"></label>` +
      '<label class="fld wide"><span>Link</span><input class="linkbox" name="url" inputmode="url" placeholder="https://"></label><button type="submit" class="btn ghost">Add it</button></form></details>';
    if (S.tab === "case") {
      h += `<div class="lead-line">${esc(c.headline || "")}</div>${c.sub ? `<div class="lead-sub">${esc(c.sub)}</div>` : ""}`;
      /* the offer follows the car's miles, price and history on its own; this runs it by hand, after comps change */
      if ((d.comps || []).some((k) => k.use)) h += `<div><button type="button" class="btn ghost reoffer"${S.moreBusy ? " disabled" : ""}>${S.moreBusy === "offer" ? "Working it out" : (d.offer.open || d.offer.target) ? "Work out the offer again" : "Work out an offer"}</button></div>` +
        liveLog(S.moreBusy === "offer") + '<div class="tiny">It runs by itself when you change the miles, the colour, the options, the asking price or the history in Car details. Tap it after you change which sales are counted or find more.</div>';
      /* what the numbers were worked out for, so a wrong detail is seen and fixed */
      if (c.basis) h += `<div class="basis"><span class="basis-k">Worked out for</span> ${esc(c.basis)}. <button type="button" class="textbtn tocar">Change</button></div>` +
        ((c.stale || []).length ? `<div class="c-flag">The car's ${esc(c.stale.join(" and "))} ${c.stale.length > 1 ? "have" : "has"} changed since. Tap Work out the offer again.</div>` : "");
      if ((c.moves || []).length) h += '<h3>What this car\'s details change</h3><div class="moves">' + c.moves.map((m) =>
        `<div class="move"><span class="mv-k">${esc(m.factor.charAt(0).toUpperCase() + m.factor.slice(1))}</span><span class="mv-e${/^\+/.test(m.effect) ? " up" : /^[-−]/.test(m.effect) ? " down" : ""}">${esc(m.effect)}</span><span class="mv-w">${esc(m.why)}</span></div>`).join("") + "</div>";
      /* another listing of the same model: change the details, price it from the same sales */
      if ((d.comps || []).some((k) => k.use) && (d.offer.open || d.offer.target)) {
        const e = d.edit || {}, shown = ((d.garage || []).find((g) => g.active) || {}).id || "";
        if (S.vformCar !== shown) { S.vform = null; S.vformCar = shown; }      /* what was typed for one car is not carried to another */
        const v = S.vform || (S.vform = { miles: "", price: "", gear: "", exterior: "", options: e.options || "" });
        const busy = S.moreBusy === "version";
        h += '<h3>Price another listing</h3><div class="tiny">Looking at another one of these? Put in what is different about it and it is priced from the sales you already have. A different gearbox is searched for first, since those are different sales. Leave a box empty to keep this car\'s value.</div>' +
          `<form class="carform vform"><label class="fld"><span>Miles</span><input class="linkbox" name="miles" inputmode="numeric" autocomplete="off" placeholder="${esc(e.miles || "")}" value="${esc(v.miles)}"></label>` +
          `<label class="fld"><span>Its asking price</span><input class="linkbox" name="price" inputmode="numeric" autocomplete="off" placeholder="optional" value="${esc(v.price)}"></label>` +
          `<label class="fld"><span>Gearbox</span><select class="linkbox" name="gear"><option value=""${v.gear ? "" : " selected"}>Same as this car</option><option value="Manual"${v.gear === "Manual" ? " selected" : ""}>Manual</option><option value="Automatic"${v.gear === "Automatic" ? " selected" : ""}>Automatic</option></select></label>` +
          `<label class="fld"><span>Colour</span><input class="linkbox" name="exterior" autocomplete="off" placeholder="${esc(e.exterior || "")}" value="${esc(v.exterior)}"></label>` +
          `<label class="fld wide"><span>Its options, one to a line</span><textarea class="linkbox" name="options" rows="3" autocomplete="off">${esc(v.options)}</textarea></label>` +
          `<button type="submit" class="btn"${S.moreBusy ? " disabled" : ""}>${busy ? "Pricing it" : "Price it"}</button></form>` + liveLog(busy);
        const rows = c.versions || [];
        if (rows.length) h += '<div class="versions">' +
          `<div class="ver mine"><div class="ver-l"><b>This car</b> ${esc(c.mine.label)}</div><div class="ver-p">${c.mine.fair ? "Fair deal " + esc(c.mine.fair) : ""}</div></div>` +
          rows.slice().reverse().map((r) => `<div class="ver"><div class="ver-l">${esc(r.label)}</div><div class="ver-p">${r.fair ? "Fair deal " + esc(r.fair) : "No price"}${r.open && r.walk ? ` <span class="ver-r">open ${esc(r.open)}, most ${esc(r.walk)}</span>` : ""}</div>` +
            (r.gap ? `<div class="ver-g">${esc(r.gap)}</div>` : "") +
            (r.basis ? `<div class="ver-m">${esc(r.basis)}</div>` : "") +
            ((r.moves || []).length ? `<div class="ver-m">${r.moves.filter((m) => !/^(no change|not priced)$/i.test(m.effect)).map((m) => `${esc(m.factor.charAt(0).toUpperCase() + m.factor.slice(1))} ${esc(m.effect)}`).join(" · ") || "Nothing about it moves the price against the sales"}</div>` : "") +
            `<div class="ver-b"><button type="button" class="textbtn veruse" data-id="${esc(r.id)}">Make this the car</button><button type="button" class="textbtn verdrop" data-id="${esc(r.id)}">Remove</button></div></div>`).join("") + "</div>";
      }
      if ((c.reasons || []).length) h += "<h3>The evidence</h3>" + c.reasons.map((r, i) => `<div class="ev"><span class="n">${i + 1}</span><span class="t">${esc(r.text)}</span>${(r.links || []).filter((l) => safeUrl(l.url)).map((l) => `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ${ARROW}</a>`).join("")}</div>`).join("");
      h += "<h3>Options</h3>";
      const have = (c.options || []).length > 0;
      if (have) h += `<div class="opts">${c.options.map((o) => `<span class="opt">${esc(o)}</span>`).join("")}${c.msrp ? `<span class="opt">Sticker ${esc(c.msrp)}</span>` : ""}</div>`;
      else h += '<div class="hintbox">No options were read for this car, and they can move the price by thousands. Add a picture of the window sticker, or paste the dealer\'s description.</div>';
      if (have && !S.optOpen) h += '<button type="button" class="btn ghost optmore">Add more from a sticker or description</button>';
      else h += keyAsk + `<textarea class="optbox" rows="3" placeholder="Paste the dealer's description, or paste a picture of the window sticker"></textarea>` +
        `<input type="file" class="optfile" accept="image/*" hidden><div class="optrow"><button type="button" class="btn ghost optpic">${S.optShot ? "Change the picture" : "Add a sticker picture"}</button>` +
        `${S.optShot ? `<span class="optthumb"><img src="${esc(S.optShot)}" alt=""><button type="button" class="optdrop" aria-label="Remove the picture">×</button></span>` : ""}` +
        `<button type="button" class="btn readopts"${S.optBusy ? " disabled" : ""}>${S.optBusy ? "Reading" : "Read the options"}</button></div>`;
      if ((c.pushback || []).length) h += "<h3>What the seller will say</h3>" + c.pushback.map((p) => `<div class="say"><div class="q">${esc(p.say)}</div>${p.reply ? `<div class="a">${esc(p.reply)}</div>` : ""}</div>`).join("");
      if (c.summary || (c.sources || []).length || (c.log || []).length) {
        h += "<h3>What the search found</h3>";
        if ((c.sources || []).length) h += `<div class="srcs">${c.sources.map((s) => `<span class="src${s.n ? "" : " zero"}">${esc(s.name)}<b>${s.n || "none"}</b></span>`).join("")}</div>`;
        if (c.summary) h += `<div class="lead-sub">${esc(c.summary)}</div>`;
        if ((c.log || []).length) h += `<details class="byhand steplog"><summary>Every step of the last search (${c.log.length})</summary><div class="livelog">${c.log.map((t) => `<div>${esc(t)}</div>`).join("")}</div></details>`;
      }
      /* every search again for this car, in one tap */
      h += "<h3>Refresh</h3>" + (h.includes("keyform") ? "" : keyAsk) +
        `<div><button type="button" class="btn ghost more" data-kind="all"${S.moreBusy ? " disabled" : ""}>${S.moreBusy === "all" ? "Searching" : "Refresh results"}</button></div>` +
        '<div class="tiny">Runs every search again for this car: sales, no-sales and cars for sale now. What you have stays, new finds are added, and each for-sale page is opened again.</div>' + liveLog(S.moreBusy === "all");
    } else if (S.tab === "comps") {
      const rows = list(["sold"], "Sales counted in the typical price", (k) => k.use) +
        (() => { const out = (d.comps || []).filter((k) => k.group === "sold" && !k.use); if (!out.length) return "";
          const why = [...new Set(out.map((k) => k.why))].slice(0, 2).join(", or ");
          return `<details class="byhand leftout"${S.outOpen ? " open" : ""}><summary>Show ${out.length} not counted (${why})</summary><div class="lead-sub">Left out of the typical price: another trim, or nothing to open and check. Paste a car's own link, or tap Count it.</div>${out.sort(order).map((k) => compCard(k, true)).join("")}</details>`; })() +
        list(["high_bid"], "Auctions that ended without a sale");
      const ended = (() => { const out = (d.comps || []).filter((k) => k.group === "ended"); if (!out.length) return "";
          return `<details class="byhand endedfold"${S.endOpen ? " open" : ""}><summary>Show ${out.length} listing${out.length === 1 ? "" : "s"} that ended</summary><div class="lead-sub">These were for sale and their pages now say sold or gone. The price is the last asking price, not what the car sold for, so they are not counted.</div>${out.sort(order).map((k) => compCard(k, true)).join("")}</details>`; })();
      const find = `<button type="button" class="btn${rows ? " ghost" : ""} more" data-kind="sold"${S.moreBusy ? " disabled" : ""}>${S.moreBusy === "sold" ? "Searching" : rows ? "Search for more sales" : "Search for sales"}</button>`;
      h = (rows ? sorter + rows : '<div class="lead-line">No completed sales yet</div><div class="lead-sub">The search goes through Cars &amp; Bids, Bring a Trailer, the other auction sites and then the wider web.</div>') +
        ended + keyAsk + `<div>${find}</div>` + liveLog(S.moreBusy === "sold") + byHand("sold");
    } else if (S.tab === "sale") {
      const rows = list(["live"], "For sale now", (k) => !k.lead) +
        (() => { const out = (d.comps || []).filter((k) => k.group === "live" && k.lead); if (!out.length) return "";
          return `<details class="byhand leftout"${S.outOpen ? " open" : ""}><summary>Show ${out.length} lead${out.length === 1 ? "" : "s"} with no page of ${out.length === 1 ? "its" : "their"} own to check</summary><div class="lead-sub">No page of their own to open and no VIN, so they are not counted. Found one? Paste its link and it moves up.</div>${out.sort(order).map((k) => compCard(k, true)).join("")}</details>`; })() +
        (() => { const n = (d.comps || []).filter((k) => k.group === "ended").length;
          return n ? `<div class="tiny endednote">${n} listing${n === 1 ? " that has" : "s that have"} sold or gone ${n === 1 ? "is" : "are"} under the Sold tab. <button type="button" class="textbtn toended">Show ${n === 1 ? "it" : "them"}</button></div>` : ""; })();
      const tools = (nSale ? `<button type="button" class="btn ghost verify"${S.moreBusy ? " disabled" : ""}>${S.moreBusy === "verify" ? "Opening each page" : "Check they are still for sale"}</button> ` : "") +
        `<button type="button" class="btn ghost more" data-kind="sale"${S.moreBusy ? " disabled" : ""}>${S.moreBusy === "sale" ? "Searching" : "Search for more cars for sale"}</button>`;
      h = (nSale ? '<div class="lead-sub">Other cars you could buy today, from live auctions, classifieds, dealers and the big listing sites (Cars.com, CarGurus, Autotrader, Edmunds, TrueCar), eBay Motors and Craigslist. Asking prices sit above what cars sell for, so use these as alternatives and leverage, not as the price.</div>'
        : '<div class="lead-sub">No cars for sale found yet. The search covers live auctions, classifieds, dealers, the big listing sites, eBay Motors and Craigslist.</div>') +
        ((d.prefs && d.prefs.zip) ? "" : '<div class="tiny">Craigslist is searched one area at a time. Add your ZIP code in Settings and each search also reads Craigslist around you. <button type="button" class="textbtn tozip">Open Settings</button></div>') +
        keyAsk + `<div>${tools}</div>` + liveLog(S.moreBusy === "sale" || S.moreBusy === "verify") + (nSale ? sorter : "") + rows + byHand("sale");
    } else if (S.tab === "message") {
      const chan = S.msgChannel || "text";
      const kind = `<div class="choice chan">${[["text", "As a text"], ["email", "As an email"]].map(([id, t]) => `<button type="button" class="btn ghost${chan === id ? " on" : ""}" data-chan="${id}">${t}</button>`).join("")}</div>`;
      const write = `<div><button type="button" class="btn msgai"${S.msgBusy ? " disabled" : ""}>${S.msgBusy === "claude" ? "Writing" : d.message ? "Write it again with Claude" : "Write it with Claude"}</button> ` +
        `<button type="button" class="btn ghost msgplain"${S.msgBusy ? " disabled" : ""}>${S.msgBusy === "template" ? "Writing" : "Use the plain version"}</button></div>`;
      h = d.message
        ? `<textarea class="linkbox msgbox" rows="12" aria-label="Your offer message">${esc(d.message)}</textarea><div class="tiny">Edit it here before you send it. Your changes are kept.</div><div><button type="button" class="btn copy">Copy the message</button></div><h3>Write it again</h3>${keyAsk}${kind}${write}${liveLog(S.msgBusy === "claude")}`
        : `<div class="lead-line">Send the seller your offer</div><div class="lead-sub">A short message with your offer and the sales that back it up. You can edit it here before you copy it.</div>${keyAsk}${kind}${write}${liveLog(S.msgBusy === "claude")}`;
    } else if (S.tab === "car") {
      const e = d.edit || {};
      const fields = [["miles", "Miles", 1], ["price", "Asking price", 1], ["exterior", "Exterior color"], ["interior", "Interior color"], ["year", "Year", 1], ["make", "Make"], ["model", "Model"], ["trim", "Trim"], ["body", "Body style"], ["transmission", "Transmission"], ["drivetrain", "Drivetrain"], ["vin", "VIN"], ["seller", "Seller"], ["location", "Location"], ["history", "Accident and title history"]];
      h = d.hasCar
        ? `<div class="lead-line">Car details</div><div class="lead-sub">Fix anything the listing got wrong. Change the miles, the colours, the options, the asking price or the history and the offer and the message are worked out again for the car as it is. Comps are matched to the year, model, trim and body style.</div><form class="carform carfacts">` +
          fields.map(([k, label, num]) => `<label class="fld${k === "history" || k === "vin" ? " wide" : ""}"><span>${label}</span><input class="linkbox" name="${k}" value="${esc(e[k] || "")}" autocomplete="off"${num ? ' inputmode="numeric"' : ""}${k === "vin" ? ' autocapitalize="characters" spellcheck="false"' : ""}></label>`).join("") +
          `<label class="fld wide"><span>Options, one to a line</span><textarea class="linkbox" name="options" rows="4" autocomplete="off">${esc(e.options || "")}</textarea></label>` +
          `<button type="submit" class="btn">Save</button></form>` +
          `<div class="dropzone"><button type="button" class="btn ghost dropcar">${d.sample ? "Remove the sample car" : "Remove this car from the garage"}</button></div>`
        : '<div class="lead-sub">Add a car first: paste a listing link or a screenshot in the bar on the main screen, or just name the car.</div>';
    }
    if (S.tab === "model") { renderModelTab(); return; }
    el.sheetBody.innerHTML = h; el.sheetBody.scrollTop = 0;
    el.sheetBody.querySelectorAll(".sortbtn").forEach((b) => { b.onclick = () => { const key = b.dataset.sort; S.sort = S.sort.key === key ? { key, dir: -S.sort.dir } : { key, dir: key === "when" ? -1 : 1 }; const y = el.sheetBody.scrollTop; renderSheet(); el.sheetBody.scrollTop = y; }; });
    const keep = () => { const y = el.sheetBody.scrollTop; renderSheet(); el.sheetBody.scrollTop = y; };
    /* no key yet: ask for it here, then press the same button again for them */
    const needKey = (button) => {
      S.needKey = S.tab; S.afterKey = () => { const b = el.sheetBody.querySelector(button); if (b) b.click(); };
      renderSheet(); const box = el.sheetBody.querySelector(".keybox");
      if (box) { el.sheetBody.scrollTop = Math.max(0, box.offsetTop - 90); box.focus({ preventScroll: true }); }
    };
    const keyform = el.sheetBody.querySelector(".keyform");
    if (keyform) keyform.onsubmit = (e) => {
      e.preventDefault();
      const value = keyform.querySelector(".keybox").value.trim(), go = keyform.querySelector("button");
      if (!value) { toast("Paste your Anthropic API key first.", true); return; }
      S.remember = el.sheetBody.querySelector(".keykeep").checked; S.pendingKey = value; S.keyTried = true;
      go.disabled = true; go.textContent = "Connecting"; post("key", { value, saved: false });
    };
    const again = (name, value, flag) => { if ((name === "more" || name === "reoffer") && !S.d.connected) { needKey(name === "more" ? `.more[data-kind="${value.kind}"]` : ".reoffer"); return; } S.moreBusy = flag; S.busyAt = Date.now(); S.log = []; keep(); post(name, value); paintRefresh(); };
    /* the offer message, written and edited right here */
    el.sheetBody.querySelectorAll("[data-chan]").forEach((b) => { b.onclick = () => { S.msgChannel = b.dataset.chan; keep(); }; });
    const msgbox = el.sheetBody.querySelector(".msgbox"), msgai = el.sheetBody.querySelector(".msgai"), msgplain = el.sheetBody.querySelector(".msgplain");
    const draft = (kind) => { S.msgBusy = kind; S.log = []; keep(); post("message", { kind, channel: S.msgChannel || "text", at: Date.now() }); };
    if (msgbox) msgbox.onchange = () => { S.d.message = msgbox.value; post("message", { kind: "edit", text: msgbox.value }); };
    if (msgai) msgai.onclick = () => { if (!S.d.connected) { needKey(".msgai"); return; } draft("claude"); };
    if (msgplain) msgplain.onclick = () => draft("template");
    /* the car's facts, corrected right here */
    const facts = el.sheetBody.querySelector(".carfacts");
    if (facts) facts.onsubmit = (e) => {
      e.preventDefault();
      const was = S.d.edit || {}, out = {};
      for (const box of facts.querySelectorAll("input, textarea")) { const v = box.value.trim(); if (v !== (was[box.name] || "").trim()) out[box.name] = v; }
      if (!Object.keys(out).length) { toast("Nothing was changed."); return; }
      const go = facts.querySelector("button"); go.disabled = true; go.textContent = "Saving";
      post("car", { ...out, at: Date.now() });
    };
    const leftout = el.sheetBody.querySelector(".leftout");
    if (leftout) leftout.ontoggle = () => { S.outOpen = leftout.open; };
    const endedfold = el.sheetBody.querySelector(".endedfold");
    if (endedfold) endedfold.ontoggle = () => { S.endOpen = endedfold.open; };
    const vform = el.sheetBody.querySelector(".vform");
    if (vform) {
      vform.oninput = () => { const v = S.vform || (S.vform = {}); for (const box of vform.querySelectorAll("input, select, textarea")) v[box.name] = box.value; };
      vform.onsubmit = (e) => {
        e.preventDefault();
        const v = S.vform || {}, was = S.d.edit || {}, facts = {};
        if ((v.miles || "").trim()) facts.miles = v.miles.trim();
        if ((v.price || "").trim()) facts.price = v.price.trim();
        if (v.gear) facts.transmission = v.gear;
        if ((v.exterior || "").trim()) facts.exterior = v.exterior.trim();
        if ((v.options || "").trim() !== (was.options || "").trim()) facts.options = (v.options || "").trim();
        if (!Object.keys(facts).length) { toast("Change at least one thing about it first: its miles, gearbox, colour or options."); return; }
        if (!S.d.connected) { needKey(".vform button[type=submit]"); return; }
        S.moreBusy = "version"; S.busyAt = Date.now(); S.log = []; keep(); post("version", { kind: "price", facts, at: Date.now() }); paintRefresh();
      };
    }
    el.sheetBody.querySelectorAll(".verdrop").forEach((b) => { b.onclick = () => post("version", { kind: "drop", id: b.dataset.id }); });
    el.sheetBody.querySelectorAll(".veruse").forEach((b) => { b.onclick = () => { S.vform = null; post("version", { kind: "use", id: b.dataset.id, at: Date.now() }); }; });
    const tozip = el.sheetBody.querySelector(".tozip");
    if (tozip) tozip.onclick = () => { closeSheet(); openSettings(); };
    const tocar = el.sheetBody.querySelector(".tocar");
    if (tocar) tocar.onclick = () => { S.tab = "car"; renderSheet(); const box = el.sheetBody.querySelector('.carfacts [name="miles"]'); if (box) box.focus({ preventScroll: true }); };
    const toended = el.sheetBody.querySelector(".toended");
    if (toended) toended.onclick = () => { S.tab = "comps"; S.endOpen = true; renderSheet(); const f = el.sheetBody.querySelector(".endedfold"); if (f) el.sheetBody.scrollTop = Math.max(0, f.offsetTop - 70); };
    /* count a sale in the typical price, or leave it out */
    el.sheetBody.querySelectorAll(".setlink").forEach((f) => { f.onsubmit = (e) => {
      e.preventDefault();
      const box = f.querySelector("input"), url = (box.value || "").trim();
      if (!url) { box.focus(); return; }
      const b = f.querySelector("button"); b.disabled = true; b.textContent = "Saving";
      post("link", { i: +f.dataset.i, price: +f.dataset.price, url, at: Date.now() });
    }; });
    el.sheetBody.querySelectorAll(".usebtn").forEach((b) => { b.onclick = () => { b.disabled = true; b.textContent = "Saving"; post("usecomp", { i: +b.dataset.i, price: +b.dataset.price, use: b.dataset.use === "1", at: Date.now() }); }; });
    /* take this car out of the garage: a second tap confirms */
    const dropcar = el.sheetBody.querySelector(".dropcar");
    if (dropcar) dropcar.onclick = () => {
      if (dropcar.dataset.sure) { dropcar.disabled = true; closeSheet(); S.switching = "-"; post("remove", { id: S.d.activeId || "", at: Date.now() }); return; }
      dropcar.dataset.sure = "1"; dropcar.textContent = "Tap again to remove it";
      setTimeout(() => { if (dropcar.isConnected) { delete dropcar.dataset.sure; dropcar.textContent = S.d.sample ? "Remove the sample car" : "Remove this car from the garage"; } }, 4000);
    };
    /* a sale or a listing the person knows of */
    el.sheetBody.querySelectorAll(".byhand").forEach((box) => { const form = box.querySelector(".handform"); if (!form) return; const kind = form.dataset.kind; box.ontoggle = () => { if (box.open) S.handOpen = kind; else if (S.handOpen === kind) S.handOpen = ""; }; });
    el.sheetBody.querySelectorAll(".handform").forEach((f) => { f.onsubmit = (e) => {
      e.preventDefault();
      const v = Object.fromEntries([...f.querySelectorAll("input")].map((box) => [box.name, box.value.trim()]));
      if (!/\d/.test(v.price) && !/^https?:\/\//i.test(v.url || "")) { toast("Give the price, or paste the listing's link.", true); return; }
      const go = f.querySelector("button"); go.disabled = true; go.textContent = "Adding"; S.handOpen = "";
      post("addcomp", { ...v, status: f.dataset.kind === "sold" ? "sold" : "asking", at: Date.now() });
    }; });
    el.sheetBody.querySelectorAll(".more").forEach((b) => { b.onclick = () => again("more", { kind: b.dataset.kind, at: Date.now() }, b.dataset.kind); });
    const verify = el.sheetBody.querySelector(".verify");
    if (verify) verify.onclick = () => again("verify", { at: Date.now() }, "verify");
    const reoffer = el.sheetBody.querySelector(".reoffer");
    if (reoffer) reoffer.onclick = () => again("reoffer", { at: Date.now() }, "offer");
    const optbox = el.sheetBody.querySelector(".optbox"), readopts = el.sheetBody.querySelector(".readopts");
    const more = el.sheetBody.querySelector(".optmore");
    if (more) more.onclick = () => { S.optOpen = true; const y = el.sheetBody.scrollTop; renderSheet(); el.sheetBody.scrollTop = y; };
    if (optbox) {
      if (S.optText) optbox.value = S.optText;
      optbox.oninput = () => { S.optText = optbox.value; };
      const attach = async (blob) => { try { S.optShot = await shrink(blob); const y = el.sheetBody.scrollTop; renderSheet(); el.sheetBody.scrollTop = y; } catch (e) { toast("That picture could not be read. Try a PNG or JPG.", true); } };
      optbox.addEventListener("paste", (e) => { const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/")); if (item) { e.preventDefault(); attach(item.getAsFile()); } });
      const pick = el.sheetBody.querySelector(".optfile");
      el.sheetBody.querySelector(".optpic").onclick = () => pick.click();
      pick.onchange = () => { if (pick.files[0]) attach(pick.files[0]); };
      const drop = el.sheetBody.querySelector(".optdrop");
      if (drop) drop.onclick = () => { S.optShot = ""; const y = el.sheetBody.scrollTop; renderSheet(); el.sheetBody.scrollTop = y; };
      readopts.onclick = () => {
        const text = optbox.value.trim();
        if (!S.d.connected) { needKey(".readopts"); return; }
        if (text.length < 8 && !S.optShot) { toast("Add a picture of the sticker or paste the description first.", true); return; }
        S.optBusy = true; S.log = []; readopts.disabled = true; readopts.textContent = "Reading";
        post("options", { text, image: S.optShot || "" });
      };
    }
    const copy = el.sheetBody.querySelector(".copy");
    if (copy) copy.onclick = async () => { try { await navigator.clipboard.writeText(msgbox ? msgbox.value : S.d.message); copy.textContent = "Copied"; } catch (e) { if (msgbox) { msgbox.focus(); msgbox.select(); } toast("Could not copy for you. The message is selected: copy it from there.", true); } };
  }

  /* ---------- a 3D model of the actual car: the person finds and loads it; it stays on their device ---------- */
  const modelSlot = () => "glb:" + (S.d.modelKey || S.d.activeId || "");
  const isGlb = (buf) => buf.byteLength > 12 && new DataView(buf).getUint32(0, true) === 0x46546c67;
  /* models come straight from Sketchfab's library: the person searches, taps one, and it downloads into this browser */
  const SK_SLOT = "dealsheet.sketchfab";
  const skApi = () => root.dataset.skfb || "https://api.sketchfab.com";
  const skSite = () => root.dataset.skfbSite || "https://sketchfab.com";
  /* The live model plays in Sketchfab's viewer. Its picture is opaque, so the studio around it is one flat
     colour, the same one the viewer is told to use. The page frames the car the way the studio camera would
     (same lens, same distance in car lengths, same height) and turns it slowly while nobody is touching it.
     Touch and mouse go to the viewer itself: when the camera is not where the page last put it, the person
     is moving it, and the page waits until they have stopped. */
  const LIVE_BG = [27, 29, 33];            /* --studio in the stylesheet: the two must be the same colour */
  const live = { api: null, base: null, o: null, cmd: null, geo: null, fov: 0, userAt: 0, away: false, holdUntil: 0, timer: 0, last: 0 };
  const stillLife = matchMedia("(prefers-reduced-motion:reduce)").matches;
  let liveKey = "", skLib = null;
  S.paintLive = () => paintLive();
  const skLoad = () => skLib || (skLib = new Promise((ok, fail) => {
    if (window.Sketchfab) { ok(); return; }
    const s = document.createElement("script"); s.src = "https://static.sketchfab.com/api/sketchfab-viewer-1.12.1.js"; s.async = true;
    s.onload = () => (window.Sketchfab ? ok() : fail(new Error("no viewer")));
    s.onerror = () => { skLib = null; fail(new Error("blocked")); };
    document.head.appendChild(s);
  }));
  /* where the studio draws a car and how big: its camera has a 30 degree lens and sits D metres away */
  function liveGeo() {
    const R = root.getBoundingClientRect(), Z = el.zone.getBoundingClientRect(), zw = Math.max(Z.width, 10), zh = Math.max(Z.height, 10), H = Math.max(R.height, 10);
    let perUnit = Math.min(zw / 6.7, zh / 2.75), cx = zw / 2;
    if (el.photo.offsetWidth) {                                  /* the listing photo beside the car: make room for it */
      const edge = el.photo.getBoundingClientRect().left - Z.left - 18;
      if (cx + perUnit * 3.1 > edge && edge > 200) { perUnit = Math.min(perUnit, edge / 6.7); cx = edge / 2; }
    }
    const D = H / (2 * Math.tan(Math.PI / 12) * perUnit), L = 4.5 * perUnit;
    return { zh, cx, perUnit, L, D, elev: Math.atan((D * 0.17 + 0.5 - 0.72) / D), fov: 2 * Math.atan(Math.tan(Math.PI / 12) * zh / H) * 180 / Math.PI, w: Math.min(Math.max(L * 1.3, 300), zw) };
  }
  /* put the viewer's camera on its circle around the car. Sketchfab scenes have z up. */
  function livePlace(seconds) {
    const o = live.o, flat = o.R * Math.cos(o.elev);
    live.cmd = [o.T[0] + flat * Math.cos(o.az), o.T[1] + flat * Math.sin(o.az), o.T[2] + o.R * Math.sin(o.elev)];
    try { live.api.setCameraLookAt(live.cmd, o.T, seconds || 0); } catch (e) {}
    if (seconds) live.holdUntil = performance.now() + seconds * 1000 + 400;
  }
  /* back to the studio's framing, seen from whatever side the car is on now */
  function liveReset(seconds) {
    const g = live.geo, b = live.base; if (!g || !b || !live.o) return;
    if (Math.abs(g.fov - live.fov) > 0.01) { live.fov = g.fov; try { live.api.setFov(g.fov, () => {}); } catch (e) {} }
    Object.assign(live.o, { T: b.T.slice(), R: g.D * b.carLength / 4.5, elev: g.elev });
    livePlace(seconds);
  }
  function liveLayout() {
    if (!root.classList.contains("live-blend")) return;
    const g = live.geo = liveGeo(), sw = g.L * 1.12, sh = g.L * 0.2;
    el.live.style.left = (g.cx - g.w / 2) + "px"; el.live.style.width = g.w + "px";
    el.shadow.style.cssText = `left:${g.cx - sw / 2}px;top:${g.zh / 2 + 0.72 * g.perUnit * Math.cos(g.elev) + g.L * 0.012 - sh / 2}px;width:${sw}px;height:${sh}px`;
    if (live.o) liveReset(0);
  }
  function liveTick() {
    live.timer = 0;
    const api = live.api, o = live.o;
    if (!api || !o || !root.isConnected || !root.classList.contains("live-blend")) return;
    const now = performance.now(), dt = Math.min((now - (live.last || now)) / 1000, 0.1), far = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
    const again = () => { if (live.api === api && !live.timer) live.timer = setTimeout(liveTick, 33); };
    live.last = now;
    if (document.hidden || S.busy || now < live.holdUntil) { again(); return; }
    try {
      api.getCameraLookAt((err, cam) => {
        if (live.api !== api) return;
        if (!err && cam && Array.isArray(cam.position) && Array.isArray(cam.target) && live.cmd) {
          if (far(cam.position, live.cmd) > o.R * 0.002 || far(cam.target, o.T) > o.R * 0.002) {     /* the person is moving it */
            live.userAt = now; live.away = true; live.cmd = cam.position.slice(); o.T = cam.target.slice();
            o.az = Math.atan2(cam.position[1] - cam.target[1], cam.position[0] - cam.target[0]);
          } else if (!stillLife && now - live.userAt > 3500) {
            if (live.away) { live.away = false; liveReset(0.7); } else { o.az -= dt * 0.09; livePlace(0); }
          }
        }
        again();
      });
    } catch (e) { again(); }
  }
  function liveStop() {
    if (live.timer) clearTimeout(live.timer);
    Object.assign(live, { api: null, base: null, o: null, cmd: null, geo: null, fov: 0, away: false, holdUntil: 0, timer: 0 });
    root.classList.remove("live-blend"); el.live.style.left = el.live.style.width = ""; el.shadow.removeAttribute("style");
  }
  if (window.ResizeObserver) { const ro = new ResizeObserver(() => liveLayout()); ro.observe(root); ro.observe(el.zone); }
  /* Some models stand the car on a floor or a platform far bigger than the car, and the viewer then frames the
     floor: the car comes out tiny. This finds the car by casting rays down through the scene (z is up). A ring
     of rays that mostly lands at one height means there is a floor; rays from the middle outwards then find
     where the car ends in sixteen directions, and the narrowest box round those points is the car.
     Resolves to { T, length, floor, hide } or to null when the scene is just the car, or cannot be read. */
  async function liveMeasure(api, T, r) {
    const ray = (x, y) => new Promise((done) => {
      const t = setTimeout(() => done(null), 1500);
      try {
        api.pickFromScene([x, y, T[2] + 4 * r], [x, y, T[2] - 4 * r], (err, hit) => {
          clearTimeout(t); const p = !err && hit && hit.position3D;
          done(p ? { x: +p[0], y: +p[1], z: +p[2], id: hit.instanceID } : null);
        });
      } catch (e) { clearTimeout(t); done(null); }
    });
    const all = (pts) => Promise.all(pts.map((p) => ray(p[0], p[1])));
    if (!(r > 0) || typeof api.pickFromScene !== "function") return null;
    const ringAt = [];
    for (let i = 0; i < 12; i++) { const a = i * Math.PI / 6 + 0.26; ringAt.push([T[0] + 0.55 * r * Math.cos(a), T[1] + 0.55 * r * Math.sin(a)]); }
    const ring = (await all(ringAt)).filter(Boolean);
    if (ring.length < 7) return null;                                   /* nothing wide under the car: the scene is the car */
    const zs = ring.map((h) => h.z).sort((a, b) => a - b), zf = zs[Math.floor(zs.length / 4)];
    const flat = ring.filter((h) => Math.abs(h.z - zf) < 0.015 * r);
    if (flat.length < 7) return null;
    const floor = new Set(flat.map((h) => h.id)), body = new Set();
    let grid = [];
    for (let i = -2; i <= 2; i++) for (let j = -2; j <= 2; j++) grid.push([T[0] + i * 0.08 * r, T[1] + j * 0.08 * r]);
    const tall = (h) => !!h && h.z > zf + 0.012 * r;
    let hits = (await all(grid)).filter(tall);
    if (!hits.length) {                                                 /* the car is not in the middle: look wider */
      grid = []; for (let i = -6; i <= 6; i++) for (let j = -6; j <= 6; j++) grid.push([T[0] + i * 0.15 * r, T[1] + j * 0.15 * r]);
      hits = (await all(grid)).filter(tall);
    }
    if (!hits.length) return null;
    let top = Math.max(...hits.map((h) => h.z));
    const H0 = top - zf, high = hits.filter((h) => h.z > zf + 0.35 * H0);
    const cx = high.reduce((sum, h) => sum + h.x, 0) / high.length, cy = high.reduce((sum, h) => sum + h.y, 0) / high.length;
    const inside = (h) => !!h && h.z > zf + 0.08 * H0;
    const K = 16, lo = new Array(K).fill(0), hi = new Array(K).fill(r), dir = [];
    for (let k = 0; k < K; k++) dir.push([Math.cos(k * 2 * Math.PI / K), Math.sin(k * 2 * Math.PI / K)]);
    if ((await all(dir.map((d) => [cx + d[0] * r, cy + d[1] * r]))).filter(inside).length > 3) return null;     /* walls, not a floor */
    for (let step = 0; step < 9; step++) {
      const mid = lo.map((v, k) => (v + hi[k]) / 2);
      (await all(dir.map((d, k) => [cx + d[0] * mid[k], cy + d[1] * mid[k]]))).forEach((h, k) => {
        if (inside(h)) { lo[k] = mid[k]; top = Math.max(top, h.z); body.add(h.id); } else hi[k] = mid[k];
      });
    }
    const edge = dir.map((d, k) => [cx + d[0] * (lo[k] + hi[k]) / 2, cy + d[1] * (lo[k] + hi[k]) / 2]);
    let box = null;
    for (let deg = 0; deg < 180; deg += 3) {
      const a = deg * Math.PI / 180, u = [Math.cos(a), Math.sin(a)], v = [-u[1], u[0]];
      const pu = edge.map((p) => p[0] * u[0] + p[1] * u[1]), pv = edge.map((p) => p[0] * v[0] + p[1] * v[1]);
      const eu = Math.max(...pu) - Math.min(...pu), ev = Math.max(...pv) - Math.min(...pv);
      if (!box || eu * ev < box.area) {
        const mu = (Math.max(...pu) + Math.min(...pu)) / 2, mv = (Math.max(...pv) + Math.min(...pv)) / 2;
        box = { area: eu * ev, L: Math.max(eu, ev), W: Math.min(eu, ev), c: [u[0] * mu + v[0] * mv, u[1] * mu + v[1] * mv] };
      }
    }
    const H = top - zf;
    /* only trust a box shaped like a car: longer than wide, lower than long, and smaller than the scene */
    if (!box || !(box.L > 0.08 * r && box.L < 1.7 * r) || box.W / box.L < 0.25 || box.W / box.L > 0.8 || H / box.L < 0.12 || H / box.L > 0.75) return null;
    const apart = ![...floor].some((id) => body.has(id));                 /* the floor is its own piece, not part of the car */
    return { T: [box.c[0], box.c[1], zf + H / 2], length: box.L, floor: [...floor], hide: apart && 0.55 * r > 0.9 * box.L };
  }
  /* once the viewer has framed the whole car, read its camera and lens: they give the car's size in the model's own units */
  function settle(api, uid) {
    let last = "", tries = 0, done = false;
    const finish = (cam, lens) => {
      if (done || liveKey !== uid) return; done = true;
      let shown = false;
      const show = (base, d, far) => {
        if (shown || liveKey !== uid) return; shown = true;
        root.classList.add("live-blend"); live.geo = liveGeo();
        if (base) Object.assign(live, { api, base, o: { T: base.T.slice(), R: far, elev: 0, az: Math.atan2(d[1], d[0]) }, fov: 0, userAt: 0, away: false, last: 0 });
        liveLayout();
        setTimeout(() => { if (liveKey === uid) el.live.classList.add("ready"); }, base ? 260 : 0);
        if (base && !live.timer) live.timer = setTimeout(liveTick, 300);
      };
      if (!cam) { show(null); return; }
      const T = cam.target.slice(), d = cam.position.map((v, i) => v - T[i]), far = Math.hypot(d[0], d[1], d[2]) || 1;
      /* the viewer fits the scene's bounding ball in its lens, and a car is about 1.77 ball radii long */
      const ball = far * Math.sin((lens || 45) * Math.PI / 360), whole = { T, carLength: 1.773 * ball };
      setTimeout(() => show(whole, d, far), 2500);                        /* never hold the car back for the measuring */
      liveMeasure(api, T, ball).then((car) => {
        if (liveKey !== uid) return;
        if (!car) { show(whole, d, far); return; }
        if (car.hide) car.floor.forEach((id) => { try { api.hide(id, () => {}); } catch (e) {} });     /* the studio has its own floor */
        const base = { T: car.T, carLength: car.length };
        if (!shown) show(base, d, far);
        else if (live.api === api) { live.base = base; live.away = false; liveReset(0.7); }             /* it was shown small: glide in */
      }, () => show(whole, d, far));
    };
    const read = () => {
      if (done || liveKey !== uid) return;
      try {
        api.getCameraLookAt((err, cam) => {
          const ok = !err && cam && Array.isArray(cam.position) && Array.isArray(cam.target), pos = ok ? cam.position.map((v) => (+v).toFixed(3)).join() : "";
          if ((ok && pos === last) || ++tries > 14) {
            if (!ok) { finish(null); return; }
            try { api.getFov((e2, lens) => finish(cam, e2 ? 0 : +lens)); } catch (e) { finish(cam, 0); }
            return;
          }
          last = pos; setTimeout(read, 220);
        });
      } catch (e) { finish(null); }
    };
    setTimeout(read, 300); setTimeout(() => finish(null), 7000);
  }
  function startLive(frame, uid) {
    let linked = false;
    const plain = () => {                                   /* without the viewer API: an ordinary embed, shown as a framed window */
      if (liveKey !== uid) return;
      liveStop(); el.live.classList.add("plain", "ready");
      frame.src = `${skSite()}/models/${encodeURIComponent(uid)}/embed?autostart=1&autospin=0.2&preload=1&ui_hint=0&ui_theme=dark&dnt=1`;
    };
    liveStop(); el.live.classList.remove("plain", "ready"); frame.removeAttribute("src");
    if (root.dataset.skfbSite) { plain(); return; }
    skLoad().then(() => {
      if (liveKey !== uid) return;
      new window.Sketchfab(frame).init(uid, {
        autostart: 1, autospin: 0, preload: 1, camera: 0, scrollwheel: 0, ui_hint: 0, ui_theme: "dark", dnt: 1,
        success: (api) => {
          linked = true; api.start();
          api.addEventListener("viewerready", () => {
            if (liveKey !== uid) return;
            try {
              api.setBackground({ color: LIVE_BG.map((v) => v / 255) }, () => {});
              api.setEnableCameraConstraints(false, { preventCameraConstraintsFocus: true }, () => {});
              api.recenterCamera(() => {});
            } catch (e) {}
            settle(api, uid);
          });
        },
        error: plain,
      });
    }).catch(plain);
    setTimeout(() => { if (liveKey === uid && !linked) plain(); }, 12000);     /* never leave it hidden */
  }
  /* No model picked for this car yet: its choices from the model library sit where the car will go. */
  const pick = { key: "", car: "", items: null, best: null, busy: false, failed: false };
  async function findModels(q) {
    const res = await fetch(`${skApi()}/v3/search?type=models&count=12&q=${encodeURIComponent(q)}`);
    if (!res.ok) throw new Error("status " + res.status);
    return ((await res.json()).results || []).filter((m) => m && m.uid).map((m) => {
      const imgs = (((m.thumbnails || {}).images) || []).slice().sort((x, y) => (x.width || 0) - (y.width || 0));
      const im = imgs.find((i) => (i.width || 0) >= 240) || imgs[imgs.length - 1] || {};
      return { uid: String(m.uid), name: m.name || "Model", author: ((m.user || {}).displayName || (m.user || {}).username || "unknown artist"), thumb: safeUrl(im.url) || "", size: 0, down: !!m.isDownloadable, url: safeUrl(m.viewerUrl) || "",
        tags: skWords((m.tags || []).map((t) => (t && (t.name || t.slug)) || "").join(" ")), about: skWords(String(m.description || "").slice(0, 600)), likes: +m.likeCount || 0,
        vehicle: (m.categories || []).some((c) => /car|vehicle/i.test(String((c && (c.name || c.slug)) || ""))) };
    });
  }
  /* What the library is asked, from the car's full name down to its make and model. A full name ("Lotus Evora
     400 2+2") often finds nothing where a shorter one ("Lotus Evora 400", "Lotus Evora") finds the car. */
  function modelQueries() {
    const d = S.d, e = d.edit || {}, tidy = (t) => String(t || "").replace(/\s+/g, " ").trim();
    const make = tidy(e.make), model = tidy(e.model), trim = tidy(e.trim).split(" ").filter(Boolean), mw = model.split(" ").filter(Boolean);
    const out = [], add = (q) => { q = tidy(q); if (q && !out.some((x) => x.toLowerCase() === q.toLowerCase())) out.push(q); };
    if (!model) { add(d.find3d || d.title); return out; }
    add([make, model, ...trim].join(" "));
    for (let n = Math.min(trim.length - 1, 2); n >= 1; n--) add([make, model, ...trim.slice(0, n)].join(" "));
    add(make + " " + model);
    for (let n = mw.length - 1; n >= 1; n--) add([make, ...mw.slice(0, n)].join(" "));
    if (make) add(model);
    return out.slice(0, 6);
  }
  const skWords = (t) => String(t || "").toLowerCase().replace(/[^a-z0-9.]+/g, " ").split(" ").map((w) => w.replace(/^\.+|\.+$/g, "")).filter(Boolean);
  const SK_BODY = { coupe: "coupe", cabriolet: "open", convertible: "open", cabrio: "open", roadster: "open", spyder: "open", spider: "open", speedster: "open", volante: "open", targa: "targa", sedan: "sedan", saloon: "sedan", wagon: "wagon", estate: "wagon", avant: "wagon", touring: "wagon", hatchback: "hatch", suv: "suv", pickup: "truck" };
  const SK_PARTS = new Set("wheel wheels rim rims steering engine seat seats logo badge emblem key keychain tire tires tyre tyres caliper brake brakes exhaust headlight headlights taillight taillights bumper spoiler chassis cockpit dashboard gearbox garage showroom diorama pack collection".split(" "));
  const SK_ODD = new Set("wrecked crashed destroyed damaged rusty abandoned burnt police taxi lego toy cartoon rally drift widebody liberty rocket livery concept".split(" "));
  const SK_FILLER = new Set("the a an of by and for with in 3d model car cars vehicle free hd hq high mid poly rigged game ready pbr real racing 3 2 edition version new".split(" "));
  const SK_MAKES = new Set("acura alfa aston audi bentley bmw bugatti buick cadillac chevrolet chevy chrysler citroen dodge ferrari fiat ford genesis gmc honda hyundai infiniti jaguar jeep kia koenigsegg lamborghini lancia lexus lincoln lotus maserati mazda mclaren mercedes mini mitsubishi nissan opel pagani peugeot pontiac porsche renault rolls saab subaru suzuki tesla toyota volkswagen vw volvo".split(" "));
  const SK_GENERIC = new Set("model series class type".split(" "));
  const SK_STYLE = new Set("ink sketch silhouette wireframe hologram stylized stylised voxel pixel papercraft clay".split(" "));
  function carWords() {
    const e = S.d.edit || {}, trim = skWords(e.trim).filter((w) => !/^\d$/.test(w) && !SK_BODY[w] && !["base", "standard", "package", "pack"].includes(w));
    const car = { make: skWords(e.make), model: skWords(e.model), trim, year: +e.year || 0, kind: "" };
    for (const w of skWords(e.body).concat(skWords(e.trim), skWords(e.model))) if (SK_BODY[w] && !car.kind) car.kind = SK_BODY[w];
    car.all = new Set([...car.make, ...car.model, ...skWords(e.trim), ...skWords(e.body)]);
    return car;
  }
  /* How well a library model fits the car, or null when it is not this car at all. The model must be named:
     in the model's own name (best), or on its page together with the make ("EVO 400", described as a Lotus
     Evora 400), or at least by its nameplate ("Evora" for an Evora 400). Trim, year and body style then decide. */
  function rateModel(m, car) {
    const name = skWords(m.name), tags = m.tags || [], about = m.about || [];
    const inName = (w) => name.includes(w), said = (w) => inName(w) || tags.includes(w) || about.includes(w);
    const has = (list, phrase) => phrase.length > 0 && (" " + list.join(" ") + " ").includes(" " + phrase.join(" ") + " ");
    const onPage = (phrase) => has(name, phrase) || has(tags, phrase) || has(about, phrase);
    if (!car.model.length || name.some((w) => SK_PARTS.has(w) && !car.all.has(w))) return null;
    const makeSaid = car.make.length > 0 && car.make.every(said);
    if (!makeSaid && !m.vehicle) return null;                                       /* nothing says it is this make, or a car at all */
    const other = name.some((w) => SK_MAKES.has(w) && !car.make.includes(w));       /* it names another maker's car */
    const plate = car.model.filter((w) => /[a-z]/.test(w) && !SK_GENERIC.has(w));
    const spare = name.filter((w) => !car.all.has(w) && !/^(19|20)\d\d$/.test(w) && !SK_FILLER.has(w) && !SK_BODY[w] && !SK_MAKES.has(w));
    const exact = car.model.every(inName), named = plate.length > 0 && plate.every(inName);
    /* a name that gives the nameplate and then something else ("Evora GT430" for an Evora 400) is another version,
       whatever its page goes on to mention; a name that gives neither ("EVO 400") is told apart by its page */
    const byPage = !exact && !other && makeSaid && !(named && spare.length);
    const whole = byPage && onPage(car.model.concat(car.trim));                    /* its page names the car in full */
    const near = byPage && !whole && onPage(car.model);
    const close = !exact && !whole && !near && !other && named;
    if (!exact && !whole && !near && !close) return null;
    let fit = exact ? 30 : whole ? 31 : near ? 22 : 14;
    if (car.make.length) fit += car.make.every(inName) ? 4 : makeSaid ? 2 : 0;
    if (other) fit -= 6;
    for (const w of car.trim) fit += inName(w) ? 2 : said(w) ? 1 : 0;
    if (car.trim.length && !car.trim.some(inName) && spare.length) fit -= 5;        /* it names another version: a GT4 for a GTS, a GT430 for a 400 */
    const years = name.concat(tags).filter((w) => /^(19[5-9]\d|20[0-3]\d)$/.test(w)).map(Number);
    if (car.year && years.length) { const gap = Math.min(...years.map((y) => Math.abs(y - car.year))); fit += gap <= 2 ? 4 - gap : gap === 3 ? 0.5 : -Math.min(gap, 10) * 0.4; }
    const kinds = name.concat(tags).filter((w) => SK_BODY[w] && !car.all.has(w)).map((w) => SK_BODY[w]);
    const wrongBody = !!car.kind && kinds.length > 0 && !kinds.includes(car.kind);      /* a wagon for a sedan, a cabriolet for a coupe */
    if (car.kind && kinds.length) fit += wrongBody ? -4 : 1;
    fit -= Math.min(name.filter((w) => SK_ODD.has(w) && !car.all.has(w)).length, 3) * 2;
    if (name.concat(tags).some((w) => SK_STYLE.has(w))) fit -= 3;
    if (name.includes("lowpoly") || (name.includes("low") && name.includes("poly"))) fit -= 2;
    fit -= Math.min(spare.length, 6) * 0.3;
    fit += Math.min(Math.log10((m.likes || 0) + 1), 3) * 0.3;
    return { fit, full: exact && car.trim.every(inName) && !wrongBody };
  }
  /* Ask the library with each wording in turn until a model that names the car turns up. Returns the models
     found, best fit first, and the best one (or null when none of them is this car). */
  async function gatherModels() {
    const asks = modelQueries(), car = carWords(), found = [], have = new Set(), e = S.d.edit || {};
    const plain = (String(e.make || "") + " " + String(e.model || "")).replace(/\s+/g, " ").trim().toLowerCase();
    const bareAt = Math.max(0, asks.findIndex((q) => q.toLowerCase() === plain));       /* the first wording without the trim */
    let best = null, failed = 0;
    for (let i = 0; i < asks.length; i++) {
      let items = [];
      try { items = await findModels(asks[i]); } catch (e) { failed++; continue; }
      for (const m of items) if (!have.has(m.uid)) { have.add(m.uid); m.rate = rateModel(m, car); m.order = found.length; found.push(m); }
      best = found.reduce((top, m) => (m.rate && (!top || m.rate.fit > top.rate.fit) ? m : top), null);
      if (best && best.rate.full) break;                              /* it names the car, trim and all */
      if (best && best.rate.fit >= 30 && i >= bareAt) break;          /* it names the model: a wider search will not name it better */
      if (found.length >= 36) break;
    }
    if (!found.length && failed === asks.length && asks.length) throw new Error("library unreachable");
    found.sort((a, b) => ((b.rate ? b.rate.fit : -1) - (a.rate ? a.rate.fit : -1)) || (a.order - b.order));
    return { items: found, best, asks };
  }
  /* The search box: when the words find nothing, drop the last word and ask again, down to one word. */
  async function findWide(q) {
    const parts = String(q || "").trim().split(/\s+/).filter(Boolean);
    for (let n = parts.length; n >= 1; n--) {
      const ask = parts.slice(0, n).join(" "), items = await findModels(ask);
      if (items.length || n === 1) return { items, ask };
    }
    return { items: [], ask: String(q || "") };
  }
  const modelTile = (m, cls) => `<button type="button" class="skitem${cls || ""}" data-uid="${esc(m.uid)}">${m.thumb ? `<img src="${esc(m.thumb)}" alt="" loading="lazy">` : '<span class="noimg"></span>'}<b>${esc(m.name)}</b><span>${esc(m.author)}${m.size ? " · " + mb(m.size) : ""}</span></button>`;
  async function showModel(m, quiet) {
    try { await store.set(modelSlot(), { embed: m.uid, name: m.name, author: m.author, url: m.url || skSite() + "/3d-models/" + m.uid, down: m.down, auto: !!quiet, near: !!quiet && !(m.rate && m.rate.full) }); }
    catch (e) { if (!quiet) toast("That choice could not be saved on this device.", true); return false; }
    paintLive(); if (S.scene) S.scene.reload(S.d);
    if (!quiet) toast("Showing “" + m.name + "”. Drag it to look around.");
    return true;
  }
  function paintPicker(rec, chose) {
    const d = S.d, wanted = !!d.hasCar && !S.busy && !rec && !(d.model && d.model.url), q = modelQueries().join("|");
    root.classList.toggle("picking", wanted); el.picker.hidden = !wanted;
    if (!wanted) return;
    const key = (d.modelKey || d.activeId || "") + "|" + q;
    if (pick.key !== key) Object.assign(pick, { key, car: d.modelKey || d.activeId || "", items: null, best: null, busy: false, failed: false });
    if (!pick.items && !pick.busy && !pick.failed && q) {
      pick.busy = true;
      gatherModels().then((got) => { if (pick.key === key) { pick.items = got.items; pick.best = got.best; } }, () => { if (pick.key === key) pick.failed = true; })
        .then(async () => {
          if (pick.key !== key) return;
          pick.busy = false;
          const auto = chose ? null : pick.best;                   /* pick the car's model for them, unless they removed one */
          if (auto && await showModel(auto, true)) return;
          paintLive();
        });
    }
    const more = '<button type="button" class="p-more">Search or load a file</button>';
    el.picker.innerHTML = pick.items && pick.items.length
      ? `<div class="p-head"><span>${chose ? "Pick a 3D model of this car" : "None of these names this car. Pick one"}</span>${more}</div><div class="p-row">${pick.items.slice(0, 12).map((m) => modelTile(m)).join("")}</div>`
      : `<div class="p-note">${pick.busy || (!pick.items && !pick.failed) ? "Looking for 3D models of this car" : pick.failed ? "The model library could not be reached." : "No 3D model of this car turned up."}${pick.busy ? "" : " " + more}</div>`;
    el.picker.querySelectorAll(".skitem").forEach((b) => { b.onclick = () => { const m = (pick.items || []).find((x) => x.uid === b.dataset.uid); if (m) showModel(m); }; });
    const btn = el.picker.querySelector(".p-more"); if (btn) btn.onclick = () => openSheet("model");
  }
  async function paintLive() {
    const d = S.d; let rec = null;
    try { if (d.hasCar) rec = await store.get(modelSlot()); } catch (e) {}
    const frame = el.live.querySelector("iframe");
    const chose = !!rec && !!rec.none;               /* the person took the model away: offer choices, do not pick again */
    if (rec && !rec.embed && !rec.file) rec = null;
    if (rec && rec.embed) {
      el.live.hidden = false; root.classList.add("live3d");
      if (liveKey !== rec.embed) { liveKey = rec.embed; startLive(frame, rec.embed); }
      const credit = $(".credit");
      credit.innerHTML = `3D view: ${rec.near ? "closest model found, " : ""}${safeUrl(rec.url) ? `<a href="${esc(rec.url)}" target="_blank" rel="noopener">“${esc(rec.name)}”</a>` : "“" + esc(rec.name) + "”"} by ${esc(rec.author || "its artist")}, shown live from Sketchfab`;
      credit.hidden = false;
    } else if (liveKey || !el.live.hidden) {
      liveKey = ""; liveStop(); frame.removeAttribute("src"); el.live.hidden = true; el.live.classList.remove("plain", "ready"); root.classList.remove("live3d");
    }
    paintPicker(d.hasCar && !S.busy ? rec : null, chose);
  }
  const skToken = () => { try { return localStorage.getItem(SK_SLOT) || ""; } catch (e) { return ""; } };
  const mb = (n) => (n ? (n / 1048576).toFixed(n < 10485760 ? 1 : 0) + " MB" : "");
  async function renderModelTab() {
    let rec = null;
    try { rec = await store.get(modelSlot()); } catch (e) {}
    if (rec && !rec.embed && !rec.file) rec = null;
    if (S.tab !== "model") return;
    const d = S.d, name = d.modelName || "this car";
    const sk = S.skfb || (S.skfb = {});
    if (sk.key !== (d.modelKey || d.activeId)) Object.assign(sk, { key: d.modelKey || d.activeId, q: modelQueries()[0] || d.title || "", items: null, busy: false, ask: "", pulling: "", used: "" });
    if (!sk.items && !sk.busy && pick.items && pick.items.length && pick.car === (d.modelKey || d.activeId || "")) sk.items = pick.items;   /* what the app already found for this car */
    const site = "https://sketchfab.com/search?features=downloadable&type=models&q=" + encodeURIComponent(sk.q || name);
    const card = (m) => modelTile(m, sk.pulling === m.uid ? " busy" : "");
    const live = rec && rec.embed, mine = rec && rec.file;
    el.sheetBody.innerHTML = `<div class="lead-line">${live ? "Showing a live 3D model" : mine ? "Showing your 3D model" : (d.model ? "Showing the built-in concept coupe" : "No 3D model picked yet")}</div>` +
      `<div class="lead-sub">${live ? "“" + esc(rec.name) + "” by " + esc(rec.author || "its artist") : mine ? esc(rec.name) + " · " + mb(rec.file.byteLength) : "Find a 3D model of the actual car and it takes the place of this one. No account needed."}</div>` +
      (live ? `<div><button type="button" class="btn ghost drop">Remove</button></div>` + (rec.down ? `<div class="tiny"><button type="button" class="textbtn skdown" data-uid="${esc(rec.embed)}">Have a Sketchfab account? Download it into the studio instead</button></div>` : "") : "") +
      (mine ? `<div><button type="button" class="btn ghost turn">Turn 90°</button> <button type="button" class="btn ghost drop">Remove</button></div>` +
        `<h3>Credit shown under the car</h3><textarea class="credit-text" rows="2" placeholder="“Model name” by Artist, CC BY 4.0, link">${esc(rec.credit || "")}</textarea><button type="button" class="btn ghost save">Save the credit</button>` : "") +
      `<h3>${rec ? "Pick a different model" : "Find a model of the actual car"}</h3>` +
      `<form class="linkrow skform"><input type="search" class="linkbox skq" value="${esc(sk.q)}" placeholder="Make and model" enterkeyhint="search"><button type="submit" class="btn sksearch"${sk.busy ? " disabled" : ""}>${sk.busy ? "Searching" : "Find models"}</button></form>` +
      (sk.ask ? `<div class="hintbox skask"><b>One-time step.</b> Downloads need a free Sketchfab account. Paste your API token and the model downloads straight away. <a href="https://sketchfab.com/settings/password" target="_blank" rel="noopener">Get your token ${ARROW}</a>` +
        `<div class="linkrow"><input type="password" class="linkbox sktoken" placeholder="Sketchfab API token" autocomplete="off"><button type="button" class="btn sksave">Download</button></div><div class="tiny">Kept in this browser only and sent only to Sketchfab.</div></div>` : "") +
      (sk.used ? `<div class="tiny">Nothing came back for “${esc(sk.q)}”, so these are for “${esc(sk.used)}”.</div>` : "") +
      (sk.items ? (sk.items.length ? `<div class="skgrid">${sk.items.map(card).join("")}</div><div class="tiny">Tap a model to show it on the main screen. It plays in Sketchfab's own viewer, with the artist's name on it, and nothing is downloaded.</div>`
        : '<div class="lead-sub">No models came back, even for the first word alone. Try the make or the model by itself.</div>') : "") +
      `<h3>Or load a file you already have</h3><input type="file" class="glb" accept=".glb,model/gltf-binary" hidden><button type="button" class="btn ghost pick">Choose a .glb file</button>` +
      `<div class="linkrow"><input type="url" class="linkbox linkurl" placeholder="or paste a link to a .glb file" inputmode="url"><button type="button" class="btn ghost loadlink">Load</button></div>` +
      `<div class="hintbox">Your choice is kept in this browser, on this device only. Nothing is uploaded to the app or stored in it, and it is used for every ${esc(name)} in your garage. Use models you have the right to use, and keep the artist's credit.</div>` +
      `<div class="tiny"><a href="${esc(site)}" target="_blank" rel="noopener">Open the full library ${ARROW}</a>${skToken() ? ' · <button type="button" class="textbtn skforget">Forget my Sketchfab token</button>' : ""}</div>` +
      (d.canDetail ? `<h3>Built-in car</h3><div class="choice"><button type="button" class="btn ghost${d.detailed ? "" : " on"}" data-detail="0">None</button><button type="button" class="btn ghost${d.detailed ? " on" : ""}" data-detail="1">Concept coupe</button></div>` : "");
    const file = el.sheetBody.querySelector(".glb"), refresh = () => { renderModelTab(); paintLive(); if (S.scene) S.scene.reload(S.d); };
    const keep = async (buf, label, credit) => {
      if (buf.byteLength > 80 * 1048576) { toast("That model is over 80 MB, which is too heavy for a phone. Pick a smaller one.", true); return false; }
      if (!isGlb(buf)) { toast("That is not a GLB file. Pick the GLB format when you download a model.", true); return false; }
      try { await store.set(modelSlot(), { name: label, file: buf, credit: credit || (rec && rec.credit) || "", turn: 0 }); refresh(); toast(credit ? "Loaded. The artist's credit is under the car." : "Loaded. Add the artist's credit so it shows under the car."); return true; }
      catch (e) { toast("That model could not be saved on this device.", true); return false; }
    };
    const on = (q, fn) => { const b = el.sheetBody.querySelector(q); if (b) b.onclick = fn; };
    /* search the library */
    el.sheetBody.querySelector(".skform").onsubmit = async (e) => {
      e.preventDefault();
      sk.q = el.sheetBody.querySelector(".skq").value.trim(); if (!sk.q || sk.busy) return;
      sk.busy = true; sk.items = null; sk.used = ""; renderModelTab();
      try {
        const got = await findWide(sk.q);
        sk.items = got.items; sk.used = got.items.length && got.ask.toLowerCase() !== sk.q.toLowerCase() ? got.ask : "";
      } catch (err) { sk.items = null; toast("The model library could not be reached. Check your connection and try again.", true); }
      sk.busy = false; renderModelTab();
    };
    /* download the one that was tapped */
    const pull = async (uid) => {
      const token = skToken();
      if (!token) { sk.ask = uid; renderModelTab(); el.sheetBody.scrollTop = 0; return; }
      if (sk.pulling) return;
      sk.pulling = uid; sk.ask = ""; renderModelTab(); toast("Downloading the model", false, 60000);
      try {
        let res = await fetch(`${skApi()}/v3/models/${encodeURIComponent(uid)}/download`, { headers: { Authorization: "Token " + token } });
        if (res.status === 401) res = await fetch(`${skApi()}/v3/models/${encodeURIComponent(uid)}/download`, { headers: { Authorization: "Bearer " + token } });
        if (res.status === 401 || res.status === 403) { try { localStorage.removeItem(SK_SLOT); } catch (e) {} sk.pulling = ""; sk.ask = uid; renderModelTab(); toast("Sketchfab did not accept that token, or this model is not open for download. Paste the token again or pick another model.", true); return; }
        if (!res.ok) throw new Error("status " + res.status);
        const links = await res.json(), glb = links.glb;
        if (!glb || !glb.url) { sk.pulling = ""; renderModelTab(); toast("This model has no GLB download. Pick another one.", true); return; }
        if ((glb.size || 0) > 80 * 1048576) { sk.pulling = ""; renderModelTab(); toast("That model is " + mb(glb.size) + ", too heavy for a phone. Pick a smaller one.", true); return; }
        const buf = await (await fetch(glb.url)).arrayBuffer();
        let info = {};
        try { info = await (await fetch(`${skApi()}/v3/models/${encodeURIComponent(uid)}`)).json(); } catch (e) {}
        const hit = (sk.items || []).find((m) => m.uid === uid) || {};
        const title = info.name || hit.name || "3D model", by = ((info.user || {}).displayName || (info.user || {}).username || hit.author || "unknown artist");
        const lic = ((info.license || {}).label || "licence on its page");
        sk.pulling = "";
        await keep(buf, title, `“${title}” by ${by}, ${lic}, ${info.viewerUrl || "https://sketchfab.com/3d-models/" + uid}`);
      } catch (err) { sk.pulling = ""; renderModelTab(); toast("The download did not finish. Try again, or pick another model.", true); }
    };
    /* tap a result: it plays on the main screen in the library's own viewer */
    el.sheetBody.querySelectorAll(".skitem").forEach((b) => { b.onclick = async () => {
      const m = (sk.items || []).find((x) => x.uid === b.dataset.uid); if (!m) return;
      if (await showModel(m)) { renderModelTab(); closeSheet(); }
    }; });
    on(".skdown", () => pull(el.sheetBody.querySelector(".skdown").dataset.uid));
    on(".sksave", () => { const v = el.sheetBody.querySelector(".sktoken").value.trim(); if (v.length < 8) { toast("Paste your Sketchfab API token first.", true); return; } try { localStorage.setItem(SK_SLOT, v); } catch (e) {} const uid = sk.ask; sk.ask = ""; pull(uid); });
    on(".skforget", () => { try { localStorage.removeItem(SK_SLOT); } catch (e) {} renderModelTab(); toast("Sketchfab token forgotten on this device."); });
    /* a file or a link the person already has */
    on(".pick", () => file.click());
    file.onchange = async () => { const f = file.files[0]; if (f) keep(await f.arrayBuffer(), f.name); };
    on(".loadlink", async () => {
      const url = el.sheetBody.querySelector(".linkurl").value.trim();
      if (!/^https:\/\//i.test(url)) { toast("Paste a link that starts with https://", true); return; }
      toast("Loading the model");
      try {
        const res = await fetch(url, { credentials: "omit" });
        if (!res.ok) throw new Error("status " + res.status);
        keep(await res.arrayBuffer(), decodeURIComponent(url.split("?")[0].split("/").pop() || "model.glb"));
      } catch (e) { toast("That site does not let the app load the file from a link. Download it and choose the file instead.", true); }
    });
    on(".turn", async () => { rec.turn = ((rec.turn || 0) + 1) % 4; await store.set(modelSlot(), rec); refresh(); });
    on(".drop", async () => { await store.set(modelSlot(), { none: true }); refresh(); });
    on(".save", async () => { rec.credit = el.sheetBody.querySelector(".credit-text").value.trim(); await store.set(modelSlot(), rec); refresh(); });
    el.sheetBody.querySelectorAll("[data-detail]").forEach((b) => { b.onclick = () => { if (!b.classList.contains("on")) post("detail", b.dataset.detail === "1"); }; });
  }

  /* ---------- the bar: a key first, then cars ---------- */
  let dockMode = "";
  function paintDock(d) {
    const mode = d.connected ? "car" : "key";
    if (mode === dockMode) return;
    dockMode = mode;
    if (mode === "key") {
      el.dock.innerHTML = `<form class="bar"><input type="password" autocomplete="off" placeholder="Paste your Anthropic API key to start" aria-label="Anthropic API key"><button type="submit" class="go text">Connect</button></form>` +
        `<div class="note"><label><input type="checkbox" class="remember" checked> Remember it on this device</label><a href="https://platform.claude.com/settings/keys" target="_blank" rel="noopener">Get a key ${ARROW}</a><span class="fine">Used only to call Anthropic. Billed to your key.</span></div>`;
      el.dock.querySelector("form").onsubmit = (e) => {
        e.preventDefault();
        const value = el.dock.querySelector("input[type=password]").value.trim();
        if (!value) { toast("Paste your Anthropic API key first.", true); return; }
        S.remember = el.dock.querySelector(".remember").checked; S.pendingKey = value; S.keyTried = true;
        post("key", { value, saved: false });
      };
    } else {
      el.dock.innerHTML = `<form class="bar"><button type="button" class="tool pic" aria-label="Add a screenshot" title="Add a screenshot">${ICON_PIC}</button><input type="file" accept="image/*" hidden>` +
        `<span class="thumb" hidden><img alt=""><button type="button" aria-label="Remove the screenshot">×</button></span>` +
        `<textarea rows="1" placeholder="Link or car name" aria-label="Add a car"></textarea>` +
        `<button type="button" class="tool paste">Paste</button><button type="submit" class="go" aria-label="Build the deal sheet">${ICON_SEND}</button></form>`;
      const form = el.dock.querySelector("form"), box = form.querySelector("textarea"), file = form.querySelector("input[type=file]");
      form.querySelector(".pic").onclick = () => file.click();
      file.onchange = () => { if (file.files[0]) takeImage(file.files[0]); file.value = ""; };
      form.querySelector(".thumb button").onclick = () => setShot("");
      box.addEventListener("input", () => { box.style.height = "auto"; box.style.height = Math.min(box.scrollHeight, 96) + "px"; });
      box.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
      box.addEventListener("paste", (e) => { const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/")); if (item) { e.preventDefault(); takeImage(item.getAsFile()); } });
      form.querySelector(".paste").onclick = async () => {
        try {
          if (navigator.clipboard.read) {
            for (const item of await navigator.clipboard.read()) {
              const type = item.types.find((t) => t.startsWith("image/"));
              if (type) { takeImage(await item.getType(type)); return; }
            }
          }
          const text = await navigator.clipboard.readText();
          if (text) { box.value = (box.value ? box.value + " " : "") + text.trim(); box.dispatchEvent(new Event("input")); box.focus(); } else toast("Nothing to paste. Copy a link or a picture first.", true);
        } catch (e) { toast("Your browser did not allow reading the clipboard. Press and hold the box and choose Paste, or use the picture button.", true); }
      };
      form.onsubmit = (e) => {
        e.preventDefault(); if (S.busy) return;
        const text = box.value.trim();
        if (!text && !S.shot) { toast("Paste a link, add a screenshot, or name a car.", true); return; }
        sendBuild(text, S.shot);
      };
    }
  }
  /* ask for a deal sheet. The request is remembered, so it can be sent again if the app restarts while it is out. */
  function sendBuild(text, image) {
    S.lastBuild = { text, image };
    S.busy = true; S.sentSeq = S.d.seq; S.busyAt = Date.now(); S.asked = text || "From your screenshot"; S.step = 1; S.log = []; el.toast.hidden = true;
    closeSheet(); paintAll(); post("build", { text, image });
  }
  const focusBar = () => { const f = el.dock.querySelector("textarea, input[type=password]"); if (f) f.focus(); };
  function setShot(url) { S.shot = url; const t = el.dock.querySelector(".thumb"); if (t) { t.hidden = !url; if (url) t.querySelector("img").src = url; } }
  /* shrink a picture in the browser before it is sent: long screenshots keep their length */
  /* a picture, made small enough to send: long screenshots keep their length so the text stays readable */
  async function shrink(blob) {
    const bmp = await createImageBitmap(blob);
    let w = bmp.width, h = bmp.height, k = 1;
    if (h > 2.2 * w) k = Math.min(1, 1080 / w, 15000 / h); else k = Math.min(1, 2200 / Math.max(w, h));
    const c = document.createElement("canvas"); c.width = Math.round(w * k); c.height = Math.round(h * k);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    return c.toDataURL("image/jpeg", 0.86);
  }
  async function takeImage(blob) {
    if (!blob) return;
    try { setShot(await shrink(blob)); } catch (e) { toast("That picture could not be read. Try a PNG or JPG screenshot.", true); }
  }
  root.addEventListener("dragover", (e) => { e.preventDefault(); });
  root.addEventListener("drop", (e) => { e.preventDefault(); const f = [...(e.dataTransfer?.files || [])].find((x) => x.type.startsWith("image/")); if (f && S.d.connected) takeImage(f); });

  /* ---------- while Claude works ---------- */
  /* what the server says it is doing right now: each search as it is sent and what came back */
  function logHtml(count) {
    const lines = (S.log || []).slice(-count);
    return lines.length ? lines.map((t, i) => `<div class="${i === lines.length - 1 ? "now" : ""}">${esc(t)}</div>`).join("") : '<div class="now">Starting</div>';
  }
  const clock = () => { const s = Math.max(0, Math.round((Date.now() - (S.busyAt || Date.now())) / 1000)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
  function paintBusy() {
    el.progress.hidden = !S.busy;
    if (!S.busy) return;
    el.progress.innerHTML = STEPS.map((t, i) => `<div class="step ${i + 1 < S.step ? "done" : i + 1 === S.step ? "now" : ""}"><i></i>${esc(t)}</div>`).join("") +
      `<div class="livelog">${logHtml(4)}</div><div class="clock">${clock()}</div>`;
  }
  setInterval(() => {
    if (!S.busy && !S.moreBusy && !S.msgBusy && !S.optBusy) return;
    const p = document.getElementById("ds-progress");
    let log = null;
    try { log = p && p.dataset.log ? JSON.parse(p.dataset.log) : null; } catch (e) {}
    if (Array.isArray(log) && log.length && log.join("\n") !== (S.log || []).join("\n")) {
      S.log = log.map(String);
      if (S.busy) paintBusy(); else { const box = el.sheetBody.querySelector(".livelog"); if (box) box.innerHTML = logHtml(5); }
      if (S.moreBusy === "all") { const box = el.verdict.querySelector(".rlog .livelog"); if (box) box.innerHTML = logHtml(1); }
    }
    if (S.moreBusy === "all") { const tick = el.verdict.querySelector(".rclock"); if (tick) tick.textContent = clock(); }
    if (!S.busy) return;
    const tick = el.progress.querySelector(".clock"); if (tick) tick.textContent = clock();
    const n = p ? +p.dataset.step || 0 : 0;
    const step = Math.max(n, S.step || 1);
    if (step !== S.step) { S.step = step; paintBusy(); }
    if (Date.now() - S.busyAt > 420000) { S.busy = false; paintAll(); toast("That took too long and was stopped. Try again.", true); }
  }, 400);

  /* ---------- the listing photo ---------- */
  function paintPhoto(d) {
    const show = !S.busy && !!d.photo;
    el.photo.hidden = !show; if (show) el.photo.querySelector("img").src = d.photo;
    root.classList.toggle("has-photo", show);
  }
  el.photo.onclick = () => { el.light.querySelector("img").src = S.d.photo; el.light.hidden = false; };
  el.light.onclick = () => { el.light.hidden = true; };

  function paintEmpty(d) {
    const show = !S.busy && !d.hasCar;
    el.empty.hidden = !show;
    if (show) el.empty.innerHTML = `<div><div class="big">Which car are you looking at?</div><div class="small">${d.connected ? "Paste a listing link or a screenshot below, or just name the car." : "Connect your key below, then paste a listing link or a screenshot, or just name the car."}</div></div>`;
  }

  function paintAll() {
    const d = S.d;
    root.classList.toggle("busy", S.busy);
    paintTop(d); paintHead(d); paintVerdict(d); paintRail(d); paintTabs(d); paintDock(d); paintBusy(); paintPhoto(d); paintEmpty(d);
    if (S.tab) renderSheet();
    if (S.scene) { S.scene.setBusy(S.busy); if (!S.busy) S.scene.setData(d); S.scene.layout(); }
  }

  /* ---------- the key and the garage, kept on this device ---------- */
  function keyAndGarage(d) {
    let saved = "";
    try { saved = localStorage.getItem(KEY_SLOT) || ""; } catch (e) {}
    if (d.keyForgotten) { try { localStorage.removeItem(KEY_SLOT); } catch (e) {} saved = ""; }
    if (d.connected) {
      if (S.pendingKey && S.remember) { try { localStorage.setItem(KEY_SLOT, S.pendingKey); } catch (e) {} }
      S.pendingKey = ""; S.keyTried = false;
    } else if (d.keyError && S.keyTried) {
      toast(d.keyError, true); S.keyTried = false; S.pendingKey = "";
      if (S.usedSaved) { try { localStorage.removeItem(KEY_SLOT); } catch (e) {} }
    } else if (!S.triedSaved && saved && !d.keyForgotten) { S.keyTried = true; S.usedSaved = true; post("key", { value: saved, saved: true }); }
    S.triedSaved = true;

    if (d.prefsAsk) {
      if (!S.triedPrefs) {
        S.triedPrefs = true;
        let kept = null;
        try { kept = JSON.parse(localStorage.getItem(PREFS_SLOT) || "null"); } catch (e) {}
        post("prefs", kept && typeof kept === "object" ? kept : {});
      }
    } else if (d.prefs) {
      const now = JSON.stringify(d.prefs);
      if (now !== S.prefsKept) { try { localStorage.setItem(PREFS_SLOT, now); } catch (e) {} S.prefsKept = now; }
    }

    if (d.fresh) {
      if (!S.triedRestore) {
        S.triedRestore = true;
        (async () => {
          try {
            const index = await store.get("index");
            if (!index || !(index.order || []).length) return;
            const cars = [];
            for (const id of index.order) { S.known.add(id); const car = await store.get("car:" + id); if (car && car.deal) cars.push({ ...car.deal, _id: id, car_photo: car.photo || "", photos: car.photos || {} }); }
            if (cars.length) post("restore", { cars, active: Math.max(0, index.order.indexOf(index.active)) });
          } catch (e) { /* storage is unavailable: nothing to restore */ }
        })();
      }
      return;
    }
    S.triedRestore = true;
    const p = d.persist; if (!p || d.busy) return;           /* a pass that is about to add, switch or remove cars is not the garage yet */
    /* One save at a time, in the order the pages arrived: two that overlap can delete what the other just wrote. */
    S.saving = (S.saving || Promise.resolve()).then(() => saveGarage(p, d)).catch(() => { /* saving is best effort */ });
  }
  async function saveGarage(p, d) {
    const order = p.cars.map((c) => c.id);
    order.forEach((id) => S.known.add(id));
    for (const c of p.cars) {
      const old = (await store.get("car:" + c.id)) || {};
      const rec = { deal: c.deal, photo: old.photo || "", photos: old.photos || {} };
      if (c.id === p.active) {
        rec.photo = d.photoOwn ? d.photo : "";
        const mine = {}; (d.comps || []).forEach((k) => { if (k.img && k.image) mine[k.img] = k.image; });
        rec.photos = mine;
      }
      await store.set("car:" + c.id, rec);
    }
    /* Cars this page has never shown belong to another tab of the app: they stay on the device and in the list.
       Only a car this page had, and no longer has, is taken off the device. */
    const was = (await store.get("index")) || {}, others = [];
    for (const id of was.order || []) { if (!order.includes(id) && !S.known.has(id) && (await store.get("car:" + id))) others.push(id); }
    await store.set("index", { order: [...order, ...others], active: p.active, saved: Date.now() });
    for (const key of await store.keys()) { const [kind, id] = String(key).split(":"); if ((kind === "car" || kind === "model") && id && S.known.has(id) && !order.includes(id) && id !== p.active) await store.del(key); }
  }

  /* ---------- new data from Python ---------- */
  let noticeKey = "";
  S.update = (d) => {
    /* Choosing another car takes the server two passes: one that saves the car on screen, then one that shows
       the car chosen. The first still describes the old car, so drawing it would flip the screen back before
       it flips forward. Wait for the second. */
    if (S.switching && d.busy) {
      S.waiting = false; clearTimeout(S.waitTimer);
      if (d.error) toast(d.error, true, 12000); else if ((d.notices || []).length) toast(d.notices.join(" "), false, 12000);
      pump(); return;
    }
    S.switching = "";
    S.d = d; S.waiting = false; clearTimeout(S.waitTimer);
    /* The app restarted underneath this page (a new version went out, or it had been asleep). The server has
       forgotten the key, the settings, the cars and anything it was working on, so bring them back and send
       again what was out, instead of waiting for an answer that will never come. */
    if (S.sid && d.sid && d.sid !== S.sid) {
      const out = S.busy ? S.lastBuild : null, lost = S.busy || S.moreBusy || S.msgBusy || S.optBusy;
      Object.assign(S, { triedSaved: false, triedPrefs: false, triedRestore: false, keyTried: false, busy: false, moreBusy: "", msgBusy: "", optBusy: false, resend: out });
      let saved = ""; try { saved = localStorage.getItem(KEY_SLOT) || ""; } catch (e) {}
      if (lost) toast(out ? (saved ? "The app restarted. Reconnecting and sending that again." : "The app restarted and lost your key. Paste it again and your request is sent.") : "The app restarted, so that was lost. Tap it again.", !saved || !out);
    }
    if (d.sid) S.sid = d.sid;
    if (S.moreBusy && d.seq !== S.optSeq) { S.moreBusy = ""; if (S.tab === "comps" || S.tab === "sale" || S.tab === "case") { const y = el.sheetBody.scrollTop; setTimeout(() => { renderSheet(); el.sheetBody.scrollTop = y; }, 0); } }
    if (S.optBusy && d.seq !== S.optSeq) { S.optBusy = false; if (!d.error) { S.optShot = ""; S.optText = ""; S.optOpen = false; } if (S.tab === "case") renderSheet(); }
    if (S.msgBusy && d.seq !== S.optSeq) S.msgBusy = "";
    S.optSeq = d.seq;
    /* Work that is under way on the server (a build, a search, a check). It runs on its own there, so the page
       may have been reloaded or another car chosen since it began: show it as working where it belongs. */
    const w = d.working, onScreen = ((d.garage || []).find((c) => c.active) || {}).id || "";
    if (w && w.kind === "build") {
      if (!S.busy) { S.busy = true; S.sentSeq = d.seq; S.busyAt = Date.now() - (w.secs || 0) * 1000; S.asked = w.asked || "Your car"; S.step = Math.max(1, w.step || 1); S.log = S.log || []; }
      S.resend = null;                                         /* it is already under way: nothing to send again */
    } else if (w) {
      const mine = w.car === onScreen;
      if (mine && S.moreBusy !== w.flag) { S.moreBusy = w.flag || "sold"; S.busyAt = Date.now() - (w.secs || 0) * 1000; }
      else if (!mine && S.moreBusy) S.moreBusy = "";            /* the search is for another car: this one's buttons are free to read */
    }
    if (d.connected && S.afterKey) { const go = S.afterKey; S.afterKey = null; setTimeout(go, 60); }
    if (d.connected && S.resend && !S.busy) { const again = S.resend; S.resend = null; setTimeout(() => sendBuild(again.text, again.image), 80); }
    if (S.busy && d.seq !== S.sentSeq && !d.busy) {
      S.busy = false;
      if (d.error) toast(d.error, true, 12000);
      else { setShot(""); const box = el.dock.querySelector("textarea"); if (box) { box.value = ""; box.style.height = "auto"; } }
    }
    if (!S.busy && d.error && d.error !== S.lastError) toast(d.error, true, 12000);
    S.lastError = d.error || "";
    const notes = (d.notices || []).join(" ");
    if (notes && notes !== noticeKey && !d.error) toast(notes, false, 12000);
    noticeKey = notes;
    paintAll(); paintLive(); keyAndGarage(d); pump();
  };

  /* ---------- 3D ---------- */
  Promise.all([loadThree(), loadAddons().catch(() => null)]).then(([THREE, addons]) => {
    try { S.scene = makeScene(THREE, addons, root, S); root.classList.add("has-gl"); S.scene.setBusy(S.busy); if (!S.busy) S.scene.setData(S.d); S.scene.layout(); }
    catch (e) { console.warn("Deal Sheet: the 3D view is unavailable.", e); root.classList.add("no-gl"); }
  }).catch((e) => { console.warn("Deal Sheet: could not load three.js.", e); root.classList.add("no-gl"); });
  return S;
}

/* ------------------------------------------------------------------ three.js, loaded once per page */
function loadThree() {
  if (window.__dsThree) return window.__dsThree;
  window.__dsThree = (async () => {
    try {
      const res = await fetch(new URL("app/static/vendor/three.module.min.js", document.baseURI).href);
      if (!res.ok) throw new Error("local copy missing");
      window.__dsThreeUrl = URL.createObjectURL(new Blob([await res.text()], { type: "text/javascript" }));
      return await import(/* webpackIgnore: true */ window.__dsThreeUrl);
    } catch (e) {
      window.__dsThreeUrl = "https://unpkg.com/three@0.160.0/build/three.module.min.js";
      return await import(/* webpackIgnore: true */ window.__dsThreeUrl);
    }
  })();
  return window.__dsThree;
}
/* the glTF loader and a studio-light environment, linked against the same copy of three.js */
function loadAddons() {
  if (window.__dsAddons) return window.__dsAddons;
  window.__dsAddons = (async () => {
    await loadThree();
    const res = await fetch(new URL("app/static/vendor/three-addons.module.min.js", document.baseURI).href);
    if (!res.ok) throw new Error("model loader missing");
    const code = (await res.text()).split('from"three"').join('from"' + window.__dsThreeUrl + '"');
    return await import(/* webpackIgnore: true */ URL.createObjectURL(new Blob([code], { type: "text/javascript" })));
  })();
  return window.__dsAddons;
}

/* ------------------------------------------------------------------ the studio */
function makeScene(THREE, addons, root, S) {
  const canvas = root.querySelector(".gl"), zone = root.querySelector(".zone"), credit = root.querySelector(".credit");
  const calm = matchMedia("(prefers-reduced-motion:reduce)").matches;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.12;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 120);
  if (addons) { const pm = new THREE.PMREMGenerator(renderer); scene.environment = pm.fromScene(new addons.RoomEnvironment(), 0.04).texture; pm.dispose(); }
  scene.add(new THREE.HemisphereLight(0xffffff, 0x15171b, addons ? 0.5 : 1.6));
  const keyLight = new THREE.DirectionalLight(0xffffff, addons ? 1.6 : 2.8); keyLight.position.set(5, 9, 7); scene.add(keyLight);
  const rimLight = new THREE.DirectionalLight(0xcfe0ff, 0.9); rimLight.position.set(-7, 4, -6); scene.add(rimLight);

  const disc = (inner, outer, alpha) => {
    const c = document.createElement("canvas"); c.width = c.height = 256; const g = c.getContext("2d"), grd = g.createRadialGradient(128, 128, 0, 128, 128, 128);
    grd.addColorStop(0, inner); grd.addColorStop(alpha, outer); grd.addColorStop(1, "rgba(0,0,0,0)"); g.fillStyle = grd; g.fillRect(0, 0, 256, 256);
    return new THREE.CanvasTexture(c);
  };
  const shadeTex = disc("rgba(0,0,0,.9)", "rgba(0,0,0,.5)", 0.55);
/*__WHEELTEX__*/
  /* the turntable: a dark glossy pad the car is mirrored in, with a thin bright rim */
  const floor = new THREE.Mesh(new THREE.CircleGeometry(26, 64), new THREE.MeshBasicMaterial({ map: disc("rgba(14,15,18,.9)", "rgba(14,15,18,.9)", 0.5), transparent: true, depthWrite: false, toneMapped: false }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = 0.0005; floor.renderOrder = 2; scene.add(floor);
  const pad = new THREE.Mesh(new THREE.CircleGeometry(3.85, 96), new THREE.MeshBasicMaterial({ color: 0x08090b, transparent: true, opacity: 0.5, depthWrite: false, toneMapped: false }));
  pad.rotation.x = -Math.PI / 2; pad.position.y = 0.001; pad.renderOrder = 2; scene.add(pad);
  const rimMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.22, toneMapped: false });
  const rim = new THREE.Mesh(new THREE.TorusGeometry(3.85, 0.011, 8, 220), rimMat); rim.rotation.x = Math.PI / 2; rim.position.y = 0.004; scene.add(rim);

  const rig = new THREE.Group(); scene.add(rig);          /* turns with the car */
  const upright = new THREE.Group(), mirrored = new THREE.Group(); mirrored.scale.y = -1; rig.add(upright, mirrored);
  let carKey = "", alive = true, busy = false, angle = -0.62, vel = 0, slideFrom = -1e9, held = 0;

  const dispose = (obj) => obj.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => {
      for (const k in m) { const v = m[k]; if (v && v.isTexture && v !== wheelTex && v !== shadeTex) v.dispose(); }
      m.dispose();
    });
  });
  const shadow = (L, W) => { const m = new THREE.Mesh(new THREE.PlaneGeometry(L * 1.2, W * 1.55), new THREE.MeshBasicMaterial({ map: shadeTex, transparent: true, depthWrite: false, toneMapped: false })); m.rotation.x = -Math.PI / 2; m.position.y = 0.012; m.renderOrder = 3; m.userData.floorOnly = true; return m; };

/*__BODIES__*/
  /* a simple car of the right body type, in studio paint */
  function buildShape(paintHex, shape) {
    const spec = bodySpec(shape), { L, W, r } = spec, hl = L / 2, crown = 0.035;
    const g = new THREE.Group();
    const belt = curve(spec.belt), roof = curve(spec.roof);
    const bottom = (x) => spec.g + 0.17 * Math.pow(Math.abs(x) / hl, 6);
    const hw = (x) => { const t = Math.min(Math.abs(x) / hl, 1); return Math.max(0.012, (W / 2) * (1 - (x > 0 ? 0.17 : 0.12) * Math.pow(t, 2.4)) * Math.sqrt(Math.max(0, 1 - Math.pow(t, 20)))); };
    const endX = (z, dir) => { let lo = hl * 0.7, hi = hl; for (let i = 0; i < 24; i++) { const mid = (lo + hi) / 2; if (hw(dir * mid) > z) lo = mid; else hi = mid; } return dir * lo; };
    const paintMat = new THREE.MeshPhysicalMaterial({ color: new THREE.Color(paintHex), metalness: 0.3, roughness: 0.4, clearcoat: 1, clearcoatRoughness: 0.06, side: THREE.DoubleSide });
    const glassMat = new THREE.MeshPhysicalMaterial({ color: 0x0a0f16, metalness: 0.2, roughness: 0.05, side: THREE.DoubleSide, transparent: true, opacity: 0.92 });
    const darkMat = new THREE.MeshBasicMaterial({ color: 0x050608, side: THREE.DoubleSide });
    const N = 64, bodyRings = [];
    for (let i = 0; i < N; i++) {
      const x = hl * Math.sin((-1 + (2 * i) / (N - 1)) * Math.PI / 2);
      const w = hw(x), yb = bottom(x), yt = Math.max(belt(x), yb + 0.05), h = yt - yb;
      const half = [[0, yb], [w * 0.72, yb], [w * 0.95, yb + Math.min(0.07, h * 0.2)], [w, yb + h * 0.32], [w, yb + h * 0.62], [w * 0.975, yb + h * 0.86], [w * 0.9, yb + h * 0.975], [w * 0.6, yt + crown * 0.6], [0, yt + crown]];
      const ring = half.map((p) => [x, p[1], p[0]]);
      for (let k = 7; k >= 1; k--) ring.push([x, half[k][1], -half[k][0]]);
      bodyRings.push(ring);
    }
    g.add(new THREE.Mesh(loft(bodyRings, true, () => 0, 1), [paintMat]));
    const xs = new Set(), r0 = spec.roof[0][0], r1 = spec.roof[spec.roof.length - 1][0];
    for (let i = 0; i <= 44; i++) xs.add(+(r0 + ((r1 - r0) * i) / 44).toFixed(4));
    spec.roof.forEach((p) => xs.add(p[0]));
    const topRings = [...xs].sort((a, b) => a - b).map((x) => {
      const w = hw(x), yt = belt(x), yr = Math.max(roof(x), yt), gh = yr - yt, k = Math.min(1, gh / 0.3), edge = w * (0.9 - 0.2 * k);
      const half = [[w * 0.9, yt], [w * (0.9 - 0.09 * k), yt + gh * 0.55], [edge, yt + gh * 0.94], [edge * 0.55, yr + 0.012 * k], [0, yr + 0.02 * k]];
      const ring = half.map((p) => [x, p[1], p[0]]);
      for (let q = 3; q >= 0; q--) ring.push([x, half[q][1], -half[q][0]]);
      return ring;
    });
    const painted = (x) => spec.paint.some((q) => x >= q[0] && x <= q[1]);
    const topMat = (x, j) => (j < 2 || j > 5 ? (x >= spec.glass[0] && x <= spec.glass[1] ? 1 : 0) : (painted(x) ? 0 : 1));
    g.add(new THREE.Mesh(loft(topRings, false, topMat, 2), [paintMat, glassMat]));
    const inset = (x0, x1, share) => {
      const pos = [], idx = [], seg = 14;
      for (let i = 0; i <= seg; i++) { const x = x0 + ((x1 - x0) * i) / seg, y = belt(x) + crown + 0.012, z = hw(x) * share; pos.push(x, y, z, x, y, -z); if (i < seg) { const a = i * 2; idx.push(a, a + 2, a + 1, a + 1, a + 2, a + 3); } }
      const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3)); geo.setIndex(idx);
      g.add(new THREE.Mesh(geo, darkMat));
    };
    if (spec.cabin) {
      inset(spec.cabin[0], spec.cabin[1], 0.68);
      const seatMat = new THREE.MeshStandardMaterial({ color: 0x1c2026, roughness: 0.7 }), sx = spec.cabin[1] - 0.98;
      for (const s of [1, -1]) { const seat = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.3, 0.42), seatMat); seat.position.set(sx, belt(sx) + 0.05, s * hw(sx) * 0.36); seat.rotation.z = 0.18; g.add(seat); }
    }
    if (spec.bed) inset(spec.bed[0], spec.bed[1], 0.82);
    const tireMat = new THREE.MeshStandardMaterial({ color: 0x0a0b0d, roughness: 0.85 });
    const faceMat = new THREE.MeshBasicMaterial({ map: wheelTex, side: THREE.DoubleSide });
    for (const x of spec.ax) for (const s of [1, -1]) {
      const w = hw(x);
      const well = new THREE.Mesh(new THREE.CircleGeometry(r * 1.2, 40, 0, Math.PI), darkMat); well.position.set(x, r, s * (w + 0.004)); g.add(well);
      const tire = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 0.25, 40), tireMat); tire.rotation.x = Math.PI / 2; tire.position.set(x, r, s * (w - 0.1)); g.add(tire);
      const face = new THREE.Mesh(new THREE.CircleGeometry(r * 0.99, 40), faceMat); face.position.set(x, r, s * (w + 0.027)); g.add(face);
    }
    const lampY = (x) => bottom(x) + (belt(x) - bottom(x)) * 0.62;
    for (const s of [1, -1]) {
      const z = (W / 2) * 0.56, x = endX(z + 0.05, 1);
      const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.075, 16, 12), new THREE.MeshBasicMaterial({ color: 0xf4f9ff, toneMapped: false })); lamp.scale.set(0.8, 0.55, 1.9); lamp.position.set(x, lampY(x), s * z); g.add(lamp);
    }
    const tail = [];
    for (let i = -8; i <= 8; i++) { const z = (i / 8) * (W / 2) * 0.8, x = endX(Math.abs(z) + 0.03, -1) - 0.012; tail.push(new THREE.Vector3(x, lampY(x), z)); }
    g.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(tail), 40, 0.02, 6), new THREE.MeshBasicMaterial({ color: 0xff3d4f, toneMapped: false })));
    const top = Math.max(...spec.roof.map((p) => p[1])), k = Math.min(5.8 / L, 1.9 / top);
    g.add(shadow(L, W)); g.scale.setScalar(k);
    return g;
  }

  /* a detailed model that ships with the app, repainted for this car */
  const showCredit = (c) => {
    if (!c) { credit.hidden = true; credit.innerHTML = ""; return; }
    const link = (text, url) => (safeUrl(url) ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text));
    credit.innerHTML = `3D model: ${link("“" + c.title + "”", c.source)} by ${esc(c.author)}<span class="long">, ${esc(c.owner)}</span>, ${link(c.license, c.license_url)}, ${esc(c.changes)}`;
    credit.hidden = false;
  };
  function dressModel(model, d) {
    const g = new THREE.Group();
    const paint = new THREE.Color(d.paint || d.color), cabin = new THREE.Color(d.cabin || "#24272d");
    model.traverse((o) => {
      if (!o.isMesh) return;
      (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => {
        if (m.name === "Paint") { m.color.copy(paint); m.metalness = 0.3; m.roughness = 0.4; m.clearcoat = 1; m.clearcoatRoughness = 0.06; }
        else if (m.name === "Interior") m.color.copy(cabin);
      });
    });
    model.rotation.y = Math.PI / 2; model.updateMatrixWorld(true);          /* glTF cars face +z; the stage wants the nose toward +x */
    const box = new THREE.Box3().setFromObject(model), size = box.getSize(new THREE.Vector3()), mid = box.getCenter(new THREE.Vector3());
    const k = Math.min(5.8 / size.x, 1.9 / size.y);
    model.scale.setScalar(k); model.position.set(-mid.x * k, -box.min.y * k, -mid.z * k);
    g.add(model); g.add(shadow(size.x * k, size.z * k));
    return g;
  }
  const modelFiles = new Map();
  function loadModel(d, key) {
    const m = d.model;
    (async () => {
      if (!modelFiles.has(m.url)) modelFiles.set(m.url, fetch(new URL(m.url, document.baseURI).href).then((r) => { if (!r.ok) throw new Error("model file " + r.status); return r.arrayBuffer(); }));
      const file = await modelFiles.get(m.url);
      const gltf = await new Promise((done, fail) => new addons.GLTFLoader().parse(file.slice(0), "", done, fail));
      if (carKey !== key || !alive) { dispose(gltf.scene); return; }
      place(dressModel(gltf.scene, d), false); showCredit(m.credit); root.dataset.car = "model";
    })().catch((e) => { modelFiles.delete(m.url); console.warn("Deal Sheet: the detailed 3D model is unavailable, keeping the simple shape.", e); });
  }
  /* put a car on the turntable, with its mirror image under the floor */
  function place(obj, enter) {
    for (const holder of [upright, mirrored]) while (holder.children.length) { const old = holder.children.pop(); if (holder === upright) dispose(old); }
    upright.add(obj);
    const twin = obj.clone(true); twin.traverse((o) => { if (o.userData.floorOnly) o.visible = false; }); mirrored.add(twin);
    if (enter && !calm) slideFrom = performance.now();
  }
  /* a model file the person chose for this car: shown as it is, with their credit */
  function loadOwn(rec, key) {
    (async () => {
      const gltf = await new Promise((done, fail) => new addons.GLTFLoader().parse(rec.file.slice(0), "", done, fail));
      if (carKey !== key || !alive) { dispose(gltf.scene); return; }
      const g = new THREE.Group(), model = gltf.scene;
      model.rotation.y = Math.PI / 2 + (rec.turn || 0) * Math.PI / 2; model.updateMatrixWorld(true);
      const box = new THREE.Box3().setFromObject(model), size = box.getSize(new THREE.Vector3()), mid = box.getCenter(new THREE.Vector3());
      const k = Math.min(5.8 / Math.max(size.x, 0.01), 1.9 / Math.max(size.y, 0.01), 5.8 / Math.max(size.z, 0.01) * 1.6);
      model.scale.setScalar(k); model.position.set(-mid.x * k, -box.min.y * k, -mid.z * k);
      g.add(model); g.add(shadow(size.x * k, size.z * k));
      place(g, false); root.dataset.car = "own";
      credit.textContent = rec.credit ? "3D model: " + rec.credit : "3D model: your own file. Add its credit under 3D model."; credit.hidden = false;
    })().catch((e) => { console.warn("Deal Sheet: that 3D file could not be opened.", e); if (S.toastOut) S.toastOut("That 3D file could not be opened. If it is Draco-compressed, download the plain glTF Binary (.glb) version instead."); });
  }
  function setCar(d, force) {
    const key = d.hasCar ? JSON.stringify([d.activeId, d.modelKey, d.shape, d.paint, d.cabin, d.model ? d.model.url : ""]) : "none";
    if (key === carKey && !force) return;
    const first = carKey === ""; carKey = key; showCredit(null);
    if (!d.hasCar) { for (const holder of [upright, mirrored]) while (holder.children.length) { const old = holder.children.pop(); if (holder === upright) dispose(old); } root.dataset.car = "none"; return; }
    for (const holder of [upright, mirrored]) while (holder.children.length) { const old = holder.children.pop(); if (holder === upright) dispose(old); }
    root.dataset.car = "none";
    if (!first) angle = -0.62;
    if (!addons) return;
    store.get("glb:" + (d.modelKey || d.activeId || "")).catch(() => null).then((rec) => {
      if (carKey !== key) return;
      if (rec && rec.embed) { if (S.paintLive) S.paintLive(); return; }   /* shown live by the page, in the library's viewer */
      if (rec && rec.none) rec = null;
      if (rec && rec.file) loadOwn(rec, key); else if (d.model && d.model.url) loadModel(d, key);
    });
  }

  /* the camera frames the car inside its part of the screen, wherever the layout puts it */
  function layout() {
    const R = root.getBoundingClientRect(), Z = zone.getBoundingClientRect();
    const W = Math.max(R.width, 10), H = Math.max(R.height, 10), zw = Math.max(Z.width, 10), zh = Math.max(Z.height, 10);
    renderer.setSize(W, H, false);
    let perUnit = Math.min(zw / 6.7, zh / 2.75), cx = Z.left - R.left + zw / 2;   /* pixels one metre of car should cover */
    const card = zone.querySelector(".photo");                         /* the listing photo beside the car: make room for it */
    if (card && card.offsetWidth) {
      const edge = card.getBoundingClientRect().left - R.left - 18, room = edge - (Z.left - R.left);
      if (cx + perUnit * 3.1 > edge && room > 200) { perUnit = Math.min(perUnit, room / 6.7); cx = Z.left - R.left + room / 2; }
    }
    const D = H / (2 * Math.tan((camera.fov * Math.PI) / 360) * perUnit);
    camera.aspect = W / H; camera.position.set(0, D * 0.17 + 0.5, D); camera.lookAt(0, 0.72, 0);
    camera.setViewOffset(W, H, W / 2 - cx, H / 2 - (Z.top - R.top + zh * 0.5), W, H);
    camera.updateProjectionMatrix();
    renderer.render(scene, camera);                                     /* a resize clears the canvas: draw at once */
  }

  let down = null;
  canvas.addEventListener("pointerdown", (e) => { down = { x: e.clientX, moved: 0 }; canvas.classList.add("drag"); try { canvas.setPointerCapture(e.pointerId); } catch (_) {} });
  canvas.addEventListener("pointermove", (e) => { if (!down) return; const dx = e.clientX - down.x; down.x = e.clientX; down.moved += Math.abs(dx); vel = dx * 0.0065; angle += vel; held = performance.now(); });
  const lift = () => { down = null; canvas.classList.remove("drag"); };
  canvas.addEventListener("pointerup", lift); canvas.addEventListener("pointercancel", lift);

  const ro = new ResizeObserver(layout); ro.observe(root); ro.observe(zone);
  let visible = true; const io = new IntersectionObserver((en) => { visible = en[0].isIntersecting; }); io.observe(root);
  let last = performance.now(), t = 0;
  function frame(now) {
    if (!alive) return;
    if (!root.isConnected) { alive = false; ro.disconnect(); io.disconnect(); renderer.dispose(); if (root.__st) root.__st.scene = null; return; }
    requestAnimationFrame(frame);
    const dt = Math.min((now - last) / 1000, 0.05); last = now;
    if (!visible || document.hidden || root.classList.contains("live3d")) return;   /* nothing to draw while a live model covers the car */
    t += dt;
    if (!down) { angle += vel; vel *= 0.93; if (!calm && now - held > 3500 && !busy) angle += dt * 0.09; }
    const slide = Math.max(0, 1 - (now - slideFrom) / 1250), ease = slide * slide * slide;
    rig.rotation.y = angle - ease * 0.9; rig.position.x = ease * 7.5;
    rig.visible = !busy;
    rimMat.opacity = busy ? 0.3 + Math.sin(t * 3.2) * 0.22 : 0.22;
    renderer.render(scene, camera);
  }
  layout(); requestAnimationFrame(frame);
  return { setData: (d) => setCar(d, false), reload: (d) => setCar(d, true), setBusy(v) { busy = !!v; }, layout };
}
