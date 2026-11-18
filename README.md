# Deal Sheet

A Streamlit app that turns a car listing into a negotiation brief: what the car is worth, the
evidence for it, what to offer, and a sheet you can print and hand over.

## The short version

The whole app is one screen with a 3D car on a studio floor and one bar at the bottom.

1. Paste your Anthropic API key in the bar (once; the app can remember it on your device).
2. Give it a car: paste a listing link, paste or pick a screenshot, or type the car's name.
3. In about two minutes the car rolls in, the comps drop onto the price line, and you get an
   opening offer, a target and a walk-away price. Drag the handles to change them.

No listing yet? Type the car instead ("2020 BMW M2 CS, manual, about 15,000 miles"). The app finds
what that car has been selling for and gives you a typical sale price, the comps and an offer range.

## What you see

- **The car.** The app searches Sketchfab's public library for the car and shows the model that
  fits it best. It asks with the car's full name first and then with shorter ones ("Lotus Evora 400
  2+2", then "Lotus Evora 400", then "Lotus Evora"), because a full name often finds nothing. A
  model fits when its name gives the model, or when its page says it is that car, or, failing
  both, when its name gives the nameplate; trim, year and body style then decide, and a model
  named as another version (a GT430 for a 400) is marked down. When the model is not the car by
  name, the credit under it says "closest model found". It is used for every car of that make and
  model in your garage. Change it or remove it in the **3D model** tab, which lists the other
  models found. If nothing in the library is the car, or you removed the model, the place where
  the car goes shows the choices to tap instead. The app does not draw a stand-in car of its own.
- **If the app restarts while you wait** (a new version went out, or it had gone to sleep), the page
  notices, reconnects your saved key, brings your cars and settings back and sends your request
  again, instead of waiting for an answer that will not come.
- **The listing photo.** The listing's own picture sits beside the title on a phone and beside the
  car on a wide screen. Tap it to see it large. If the site would not give the app a picture, tap
  **Add photo**.
- **The price and the reason.** The asking price, how far it sits from the median of the sold comps,
  and one line of evidence. **See the case** opens the full reasoning: each point links to the sale
  or listing it rests on, followed by the car's options, what the seller is likely to say and how to
  answer, and what the search found.
- **The price chart.** One line of prices. Every comp is a dot above it (solid for sold, hollow for
  asking, amber ring for an auction that ended without a sale; faded when left out), with a dashed
  line at the median sale and a solid line at the asking price. Your offer is the green band on the
  line: drag its handles to set the open, target and walk-away prices, and the out-the-door total and
  monthly payment follow. Tap a dot to see that car.
- **Options.** The car's options and original sticker price are read from the listing, including
  the dealer's description, and shown under the title; comps carry theirs too, and the offer
  reasoning accounts for the difference. You can add options at any time under **The case**: paste
  or pick a picture of the window sticker, or paste the dealer's description.
- **Accident and title history.** What the listing says about accidents, damage and title shows as a
  chip under the title (green when clean, red when not, amber when the listing says nothing) and on
  each comp that states it. The offer reasoning weighs it.
- **VINs.** The car's VIN shows under the title and each comp's VIN on its card; tap one to copy it.
  When a listing leaves the VIN out, the app says so. Comp VINs are also read out of links that
  contain them (Classic.com's do).
- **Sold, and for sale now.** Completed sales and the cars you could buy today are separate lists,
  each with a **Search for more** button that looks for cars not already found. For-sale cars come
  from live auctions, enthusiast classifieds and dealers. The app opens each for-sale page, where
  the site allows it; **Check they are still for sale** does that again. Every answer comes from
  one set of rules, written against how real dealer, auction, classified and listing-copy sites
  word their pages, and every card says what its answer rests on:
  - **For sale** needs proof that this car is on the seller's page: its VIN (or chassis number),
    or, when the page states none, a heading that names one car of its model year together with
    its price, an in-stock mark in the page's own data, or an Available badge. A page that lists
    several cars is not proof.
  - **Listed elsewhere** is the same proof on a site that only copies sellers' listings
    (Classic.com, Capital One, CarGurus, Cars.com, Autotrader, KBB, Edmunds and the like). Such a
    page can outlive the car by days or weeks, so it is shown, never counted as confirmed.
  - **Listing ended** needs proof too: a missing page, a link that now leads elsewhere on the site
    (the usual answer for a sold car), an address or a title that says sold, words such as sold,
    sale pending, off the market, final bid or no longer available, a Sold badge standing on its
    own, out-of-stock in the page's data, or another car's VIN at that address.
  - **Not confirmed** is everything else, with the reason: the site shuts apps out, it turned the
    reader away, the page is built by scripts, or it loaded without this car's VIN or price.
  Two readers apply those rules. The app opens every page itself, all at once. Pages it could not
  read go to Claude's own page reader when a key is connected (one small request each, billed as
  tokens only): it runs on Anthropic's side, keeps to each site's rules itself, and is asked for
  a fresh copy, not a cached one. The reader only fetches; the verdict is the same rules run on
  the text it brings back, and a copy more than six hours old cannot show a car is still for
  sale. The check also re-opens listings it marked ended, and one that is provably back returns
  to the list. A listing that has ended leaves the For sale now tab for a fold at the bottom of
  the Sold tab, labelled with its last asking price and not counted, so For sale now holds only
  cars you can buy. A link the app opened and found the car on is treated as confirmed. Both
  lists sort by price, miles or date.
- **Manual or automatic.** When your car states its transmission, the other kind is left out:
  the searches are told to skip it and to record what each source states, and when the app opens
  a for-sale page it reads the transmission from the page's own labelled field, which outranks
  what a results list said. A car whose page states the other kind is removed, and each one is
  named in "Every step of the last search" with where that was read. Cards show Manual or
  Automatic ("on its page" when read there), and a car whose transmission nobody states is
  flagged and ranked lower. Free text only counts when it is about the gearbox, so "owner's
  manual" and "automatic rev-matching" decide nothing.
  Each comp has a button that opens that car's own page. A link that opens a list of
  results instead of one car is flagged on the screen and on the PDF, and is never offered as the
  proof link for a point in the case.
- **Message.** Your offer message, written right there: **Write it with Claude** (as a text or an
  email) or **Use the plain version**, which needs no key. Edit it in place; your changes are kept.
- **Car details.** Every fact about the car, to correct in place: year, make, model, trim, body,
  transmission, miles, asking price, VIN and the rest.
- **Nothing sends you elsewhere.** The Sold and For sale tabs each have a form to add a car you know
  of. When something needs your key and you have not connected it, the key box appears on the spot
  and the app then carries on with what you asked.
- **What it is doing.** While it works, the screen shows each step as it happens: the car it read,
  each search as it is sent ("Cars & Bids: searching ..."), how many pages came back and from
  where, how many cars each site gave, and a running clock.
- **Only the sales that count.** The Sold tab lists the sales counted in the typical price, and the
  number on the tab is those. A car of another trim is dropped when there are three or more exact
  matches. When exact matches are scarce it is kept as a guide to the range, not counted, and
  folded away under "Show N not counted" with the reason on each card. **Count it** and **Leave it
  out** move a sale between the two.
- **A sale is never left out for its price.** For one day the app set aside sales with no page of
  their own that sat far from the rest, taking them for dealers' asking prices. In a market that
  had moved they were the newest and truest sales in the list: two real auction results. That
  rule is gone, and any sale it set aside is counted again when the car is opened. The offer is
  told that prices move: it prices from the last twelve months' sales when those sit clearly
  above or below older ones, and treats special equipment (a power kit, paint to sample) as a
  reason a sale says less about a car without it.
- **Bring a Trailer's own record is read by the app.** Bring a Trailer keeps a page for each model
  (the 991 Carrera S, say), and that page carries every auction of the model it has run: the
  title, the price, the day it ended, whether the car sold, and the address of the auction's own
  page. The site serves these pages to anyone and its robots.txt allows them, so the app reads
  them itself (`bat.py`): no search, no model copying a table, and the same answer on every run.
  It finds the model's page on the make's page (when one trim has a page in several generations,
  the one holding the car's model year), keeps the last three years, takes the miles from the
  title, and tells a manual from an automatic the way the site does (a manual's title names its
  gears). It then opens the few auctions nearest the buyer's car, one at a time, and puts on each
  the VIN, the miles, the gearbox, the town and the equipment the page lists, and takes the price
  from the page's own words: one auction's record and headline showed the last bid, $86,000,
  where its page says the car sold for $88,000. Every one of these sales opens on the auction's
  own page, which is what a seller cannot argue with. Now and then a model page arrives with its
  newest two dozen auctions only: the app asks once more, and says so when that is all it got. The app asks
  slowly on purpose: one request at a time, a second apart as the site asks, each page kept ten
  minutes, about ten requests for a car, and a refusal ends it.
- **Classic.com: what can and cannot be had from it.** Classic.com keeps its past prices for
  members. On the page a browser shows, sold and ended prices are blurred and cannot be selected;
  its market pages are refused to other readers (the app's own request gets a 403, and the app
  does not go around a refusal); and Claude's page reader hands back a copy it saved earlier,
  which on Nov 17, 2026 was about a year old. The app reads that old copy row by row for its
  history (the status, price, date, miles, town, seller, and whether it was an auction or a
  dealer's fixed price), never takes "for sale" from it, drops asking prices that ended more than
  a year ago, reads only the market kept for the car's own body style and gearbox, and writes in
  the summary how old the copy is. It is background now: this year's sales come from Bring a
  Trailer's record and from the searches.
- **A page the app cannot open can be added as a screenshot.** The Sold tab has **Add sales from a
  screenshot of a results page**, for Cars & Bids' past auctions, another auction house or a
  dealer's sold list: Claude reads every row from the picture in one request. Pasted text is read
  too, with no request, and when it is Classic.com's page the app says how many sales came without
  a price and why.
- **An auction result and a dealer's price are told apart.** A result at a named auction on a
  known day (Bring a Trailer, Aug 22, 2026) is one auction that anyone can look up, so it
  counts. A dealer's listing that Classic.com marks sold shows what the dealer last asked, not
  what was paid: its card says so, the offer weighs it below an auction result, the message
  cites auction results first, and once three checkable sales are in hand it is not counted.
  Rows from the market page of another body style, gearbox or version are never kept.
- **Each auction result can be proven on the auction's own page.** A card that came from
  Classic.com's table has **Find this auction on Bring a Trailer** (or Cars & Bids, or
  PCARMARKET): a search of that site for the car and the price. Paste the page's link into the
  card and the app reads the result off the page itself and puts it on the card: "Checked on the
  auction's own page: sold for $88,000 on Aug 26, 2026". The page wins when it disagrees with the
  list, which happens: an auction's headline can go on showing the highest bid after the car
  sold for more once the auction had closed. Sales that already open on an auction's page are
  checked the same way when they are found. A price index is never trusted for this: one of
  them had a $108,000 sale down as $85,000.
- **PCARMARKET is searched for Porsches**, as its own source next to Classic.com and Cars & Bids.
- **The message cites only what supports the offer.** A sale above the offer argues the seller's
  case, so the message names only sales at the offer or within a few percent of it: from the last
  twelve months when there are any, since a seller waves away an older, cheaper sale, else from
  the last three years. When there is none it names cars for sale now at about the offer and near this
  car's miles, as asking prices. When there is none of those either it cites nothing and stays
  short. It never explains a price with a reason that is not in the data. The offer also prices a car from its whole generation, never from its own
  model year alone.
- **Never the car itself, never a car twice.** A car for sale that carries your car's VIN, or sits
  on its own listing page, is your car on another site: it is taken out of the comparisons and
  named in a note. Two for-sale rows with one VIN are one car, and one VIN sold at one price is one
  sale. An earlier sale of your own car stays and is marked. One VIN on two different sales stays
  too, with a flag on both cards: a car can sell twice, but one of the two may be matched to the
  wrong page. A list already saved is tidied the same way the next time it is opened.
- **What each site gave.** "What the search found" lists every site that was searched with the
  number of cars it gave, or the reason it did not finish, and **Every step of the last search**
  opens the full list of searches that were run.
- **Garage.** Each car you add is a chip at the top. Tap one to switch. The sample car stays until
  you remove it; **Remove this car** is at the bottom of Car details. Cars are saved in this
  browser on this device. With the shared garage set up (see "One garage on every device"), a
  phone and a computer that use the same key show the same cars.
- **Edit and print**, below the main screen: correct any detail of the car, the comps or the offer
  by hand, and make the PDF. The PDF prints every link in full beside a large QR code. The seller
  copy leaves out your target, walk-away price and notes.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app opens with a sample deal so you can try the screen before adding a key.

## Bring your own key

Claude features need an Anthropic API key. Each person pastes their own into the bar at the bottom
of the screen; a link beside it opens the Claude Console keys page
(https://platform.claude.com/settings/keys).

- The key is checked with a free call when it is pasted.
- With **Remember it on this device** ticked, the key is saved in that browser's storage for this
  site, so the next visit connects by itself. Untick it on a shared computer.
- **Forget my key** (in the settings panel, the button at the top right) disconnects and deletes
  the saved copy.
- The key is never written to the server's disk, logged, put in a saved garage file or printed on
  the PDF. It is used only to call Anthropic.
- The app never reads a key from secrets or environment variables, so a public copy cannot spend
  the owner's key.
- Usage is billed to whoever's key is connected. Web research is billed per search on top of
  tokens, and the settings panel caps the number of searches per run. Every run ends with a line
  saying what it used: how many web searches, how many tokens in, how many of those came from
  the cache, and how many out. It is in The case, under "What the search found".
- **What keeps a run cheap.** The API runs a search's steps in a loop and reads everything found
  so far again at each step. Prompt caching is on from the first request, so the API puts a cache
  point after each search result and each later step reads the earlier results from the cache at
  a tenth of the price. With the default setting a run sends at most 17 searches and opens at
  most 7 pages: two per auction site, three across the web, five for cars for sale, two to find
  the listing sites' results pages, one to find eBay's, and two on Marketplace; plus up to
  three listing-site pages, one eBay Motors page and (with a ZIP code) one Craigslist page,
  opened live. Those pages are the largest single cost of a run (up to 30,000 tokens each), and
  they replace opening each of those cars one by one. The searches are told to stop when a search brings back cars they
  already have, a search that does not record is asked again at most twice, and a search that
  failed is run again only when the failure was a busy server or a dropped connection.
- **Long work runs on its own.** A build, a search and a check of the for-sale pages each run on
  their own thread on the server, filed under a name this browser keeps. Nothing you do while one
  runs starts it again or throws its work away: you can choose another car, open tabs, or let the
  phone sleep. A page that comes back (reloaded, or reconnected) finds the work still running, or
  finished and waiting. Results go to the car the work was started for, even when another car is
  on screen by then; the notice then starts with that car's name. One piece of long work runs at
  a time per browser.
- **The offer follows the car.** Change the car's miles, colours, options, asking price or
  history in Car details (options can be typed there, one to a line, or read from a sticker in
  The case) and the offer is worked out again by itself from the comps you already have: two
  short requests, no new searches. The message to the seller is written again at the same time,
  so its miles and its figure never disagree with the offer.
  - The case says what the numbers were worked out for ("15,000 miles, Misano Blue, 2 options
    listed") with a Change link, and warns when the car has changed since.
  - Under it, **What this car's details change** gives one line each for miles, colour, options
    and history: how far each moved the price against the comps, and why. "Not priced" means
    the comps give nothing to price it with, which is said instead of a guess.
  - Miles weigh most. Sales nearest the car's miles lead, old sales count for less, and a very
    low-mile example of a limited car is priced from low-mile sales when there are any.
  - The offer uses only the sales that are counted.
  - The case has a **Work out the offer again** button for the other times: after you change
    which sales are counted, or find more. The typical sale price stays the plain median of the
    counted sales; the offer is where the car's own details are weighed.
- **Price another listing without a new search.** The case has a **Price another listing**
  form for when you are looking at several of the same model: put in what is different about
  the other one (its miles, gearbox, colour, options, asking price) and it is priced from the
  sales you already have, in one short request.
  - Each one is kept in a list under the form, beside this car: its fair deal, opening offer
    and limit, how its asking price compares, and which details moved the price ("Miles
    +$9,000, Transmission -$6,000"). The list is saved with the car.
  - **Make this the car** gives the car those details and works the offer and the message out
    again. **Remove** drops it from the list.
  - A different gearbox is searched for first: the sales held were gathered for this car's
    gearbox, so sales of the other kind are found and it is priced from those. If none turn up
    it is priced as a rough guide from this car's sales, and says so.
- **Searches run when they are needed.** When the car becomes a different one as far as sales
  go (its gearbox, trim, body style, year or model is changed in Car details, or a version with
  the other gearbox is made the car), the app searches again for the car as it now is, in place
  of the sales found for the car as it was, then works out the offer and writes the message
  from them. Comps you added yourself are kept.
- **Craigslist and eBay Motors are read live.** Their ads end within weeks and search engines
  keep the dead ones, so nothing is taken from a search result. Instead each site's own results
  page is opened as it is now:
  - **eBay Motors:** one search finds eBay's page of cars for the model, and that page is read.
  - **Craigslist** is searched one area at a time, so it needs to know where you are. Put your
    **ZIP code** in Settings (the box under the search slider; the For sale now tab links to it)
    and each search for cars for sale also reads Craigslist's cars-and-trucks search for the
    model within 250 miles of you. With no ZIP code, Craigslist is skipped.
  - An ad is kept only when the opened page gives its own link with that price beside it, and
    it is a whole car: an ad priced like a part, or named like one and cheap, is left out.
  - A kept ad opens on its own page and is marked for sale with the reason ("on the Craigslist
    results page, read live"). Ads read live today are not opened again one by one. Later
    checks open the ad's page; one that has ended is marked gone.
  - The ZIP code is kept in this browser with the other settings. It is turned into a town
    name on the app's own server and goes only into the Craigslist address that is opened.
  - If the open for-sale search brings back a Craigslist or eBay ad when pages cannot be read
    live, it is shown only once its own page has been opened and still shows the car.
- **The message cites the right sales.** It quotes the two or three completed sales nearest the
  car in miles and most recent, newest first, with plain dates. A sale that is years old, far
  from the car's miles, or well above the offer is left out when closer ones exist. A sale whose
  link opens that sale's own page is preferred, and a link is given only then: a sale known
  only from a results page is cited by where it is recorded ("per Classic.com").
- **A listing you paste is matched to what is already there.** In For sale now, "Add a car for
  sale you know of" takes just the link: the price, miles and VIN are read from the page where
  it shows them (some dealers' pages put the price only in the title). If a car already found
  has the same VIN, or the same price to the dollar and model year, it is the same car: its
  card keeps the VIN and miles and now opens the page you gave, with the other site named in
  its note. Dealers' own pages are often missing from a search because the listing sites show
  the car without naming the dealer.
- **Removing a car.** The car on screen carries a small cross beside its name in the row at the
  top. Tap it, then tap **Remove?** to take the car out of the garage (Car details has the same
  button). It is removed from this device too, so it does not come back. A search still running
  for a removed car is left to finish and its results are dropped.
- **A blank car is only a place to start.** When the garage is empty the app shows one blank
  car. It is never saved to the device or brought back, it goes as soon as it is not the car on
  screen and a real car exists, and it has a cross of its own whenever there is another car.
- **A car being loaded is never lost to the next tap.** A run that is cut short by another tap,
  before it has drawn the car it was loading, keeps what it had filled in and draws it on the
  next run. Before this, the fields still showing in the browser could replace the car being
  loaded, and the car that had been on screen was then saved under its name.
- **Saving to the device is careful.** The garage is saved only from a settled page, never from
  the pass that is about to add, switch or remove cars. Saves run one at a time, in order. A car
  is deleted from the device only if this page had it and no longer does, so a second tab of the
  app cannot delete the first tab's cars.

Everything except the Claude features works without a key.

## What is kept on your device

Your cars (with their comps, offers and photos) and your settings (tax, fees, loan terms, your first
name, the model and the search limit) are saved in the browser you used, and come back when you
reopen the app there. Removing a car removes its saved copy. Unless the shared garage below is set
up, nothing is stored on a server. To move your cars to another device by hand or keep a backup,
save the garage to a file from the settings panel and open that file on the other device.

## One garage on every device

Optional. Give the app a small database and every device that uses the same API key shows the same
cars, with no searches run again.

- **What is kept there.** Each car's details, comps, offer, summary and message. Never the API
  key, and no photos: a photo stays with the browser that loaded it, and the other devices load
  their own from the listing.
- **Whose garage.** A garage is named by a one-way hash of your API key, so only a device holding
  that key can name it, and the key itself cannot be worked back from the name. Change the key
  and the devices start a new shared garage from the cars they hold.
- **When devices are brought together.** When the app opens, and when you tap **Get the latest
  from my other devices** in Settings. A change made here is saved as it happens. A device left
  open does not watch for changes made elsewhere: use the button, or reload.
- **Which copy wins.** The one changed last. A car removed on one device is removed on the
  others the next time they are brought together, unless it was changed there after the removal.
  Cars added separately on two devices before they are brought together are both kept.
- **If the database cannot be reached** the app carries on from the browser's copy, Settings says
  so, and what was missed is sent on a later tap once it is back.

To set it up: run `tools/garage_store.sql` once in a Supabase project (SQL editor), then add the
project's address and its publishable key to the app's secrets as `DEALSHEET_DB_URL` and
`DEALSHEET_DB_KEY`. The table cannot be read or written directly; the only way in is two functions
that need a garage's name, and they limit a car's size, the cars in a garage and the size of the
table. Without those two secrets the app works as before, one garage per browser.

## Links, screenshots and names

- **A link** works when the site lets apps read its pages: the app fetches the page the way a link
  preview does, obeying robots.txt, and hands its text to Claude. Many big marketplaces refuse
  (Cars.com, Classic.com, Facebook Marketplace). If you give only a blocked link,
  the app reads the words in the link itself (often the year, make and model) and tells you what is
  missing.
- **A screenshot** always works. Paste it into the bar, drop it on the page, or tap the picture
  button. Long screenshots are cut into page-sized pieces so nothing is lost.
- **A name** gives you market pricing without a listing.

## Models

The app offers Claude Haiku 5.5, Sonnet 5.5 and Opus 5.5, and uses **Haiku 5.5 unless you pick
another** under Settings. Haiku is the fastest and cheapest; Sonnet and Opus read listings and
follow the matching rules more carefully, so switch for a car that matters. The checks the app
makes itself (body style, trim, VIN, duplicate sales, price-guide pages) apply whichever you use.

Prompt caching is used where it pays: when a search runs to a second round, the search so far is
sent again and is read from the cache. Every other request is new each time (another car, another
site, fresh results), and writing those to the cache would cost more, not less. Each search line
on screen ends with the tokens it used and how many came from the cache.

Sonnet 5.5 and Opus 5.5 reject a forced
tool choice, think by default and count thinking toward the output limit, so `llm.py` asks for
tool calls in the prompt, retries once when a reply has none, and sets generous output limits.

## Where the pictures come from

1. **Your upload.** A car photo you add under Edit and print.
2. **Your screenshots.** Claude finds the car photo inside a listing screenshot, and each car's photo
   inside a results-page screenshot, and the app cuts them out.
3. **The listing's own preview image.** For each link, the app asks the page for the picture it
   publishes for sharing (its `og:image`), the way a chat app builds a link preview.

The preview fetch identifies itself, obeys each site's robots.txt, only talks to public internet
hosts, and never tries to get past a block. Classic.com and Cars.com refuse automated visits, so
comps from those sites have no photo unless you add a screenshot. The app does
not use a headless or stealth browser, on purpose. Turn the fetch off in the settings panel.

## Put it online

1. Push this folder to a GitHub repository.
2. Create an app on Streamlit Community Cloud that points at `app.py`.
3. No secrets are required. Visitors paste their own key.
4. Optional: set `APP_PASSWORD` in the app's Secrets box to put a password in front of the app.
5. Optional: set `DEALSHEET_DB_URL` and `DEALSHEET_DB_KEY` for one garage on every device (above).

## What to expect from the web research

- Results come from Claude's web search tool, so they are search results, not page scrapes.
- Every run looks for completed sales and, at the same time, for cars for sale right now: live
  auctions (Bring a Trailer, Cars & Bids, PCARMARKET), enthusiast classifieds (for a Porsche,
  Rennlist and the PCA Mart), the maker's pre-owned finder, dealers, listing sites and Facebook
  Marketplace. Price-guide mirrors such as KBB are left out because they keep listings up after
  the car has gone.
- **Most reliable first, and colour-coded.** Every list is sorted "Most reliable" by default: cars
  that open on their own page, have a VIN and leave nothing to confirm, then cars with
  something left to confirm (no VIN, transmission not stated, a for-sale page the app could not
  confirm, or a car read from a listing site), then the rest, confirmed listings and newest first within each. The price line uses the same three colours (green, white, grey), and shape
  for what a car is: a filled dot is a sale, a ring is a car for sale, a diamond is a no-sale.
  Each card carries the same coloured dot.
- **What can be checked comes first.** A car counts when its link opens that one car's own page
  and the search (or a page the search opened) gave that link. Each card shows the VIN, with a tick
  when its check digit is right and its model year matches the title, and a warning when the VIN is
  for another year. A car with nothing to open (read from a list, or with a link the search did
  not return) is a lead: once a car has three results that can be checked, leads are folded away
  and left out of the numbers. Paste a lead's own link into the box on its card and it is counted.
- **The big listing sites are read live.** Most ordinary cars (a Tesla, a Tacoma, a 3 Series)
  are sold by dealers who list on Cars.com, CarGurus, Autotrader, Edmunds and TrueCar, and their sale
  prices are published nowhere, so asking prices on those sites are most of what there is to know.
  - A search engine's copy of a results page is not good enough. Copies of the same site's city
    pages are taken on different days, so one car shows up at several prices (a 17,089-mile
    M2 CS read $69,976, $74,724 and $74,976 on three copies when the live page said $72,876),
    often without its VIN and with the page's city in place of the car's.
  - So one search, limited to those sites, only finds each site's results page. Claude's page
    reader then opens up to three of them, one per site, as they are now, and the cars are read
    off the opened pages: price, miles, gearbox, dealer, town, VIN and the car's own page.
  - A car is kept only when an opened page bears it out: its VIN is on the page and its price
    stands beside that VIN. No VIN, another model year, a price from the wrong row or a car that
    only a stored copy showed is left out, and the step log says how many were.
  - The same VIN on two sites is one card, at the lower price, with the other named in its note
    ("Also on Cars.com at $56,490"). A dealer's own page for that VIN wins over both.
  - Each card says where and when it was read ("on the Edmunds results page, read live") and is
    marked "Listed elsewhere", since a listing site can run days behind the dealer. Cars read
    live today are not opened again one by one.
  - Refresh reads the pages again. A car seen again takes today's price, with the old one kept
    in its note ("Was $53,400 when seen Nov 10"). One that is no longer on the page is marked
    not confirmed. Cars an earlier version took from stored copies, with no VIN, are cleared.
  - If no page can be opened (the key has no page reader, or every site turns it away), cars the
    search results show with a VIN are kept as leads only: not counted, and marked as coming
    from a stored copy whose price may have changed. With the plain page reader, which may hand
    back its own stored copy, the card gives that copy's date.
  - The open for-sale search is kept off those five sites while their own search runs. If the
    search tool will not be limited to one of the sites, that site is dropped.
- **Drive type is checked.** When the car states its drive (AWD, RWD, FWD), a found car whose
  title or trim states the other is left out, as with body style: a rear-wheel-drive Model Y is
  not a comp for an all-wheel-drive one.
- Facebook Marketplace is searched for ads themselves: the search is limited to ad pages
  (facebook.com/marketplace/item), so each result is one car at its own address, with the price,
  the miles, the town and how long ago it was listed. Ads that are marked sold, older than twelve
  weeks, abroad or not in dollars are left out. The search index holds only some of Marketplace's
  ads, so a rare car may have none. A Marketplace car read from a city list by an earlier version
  has no address of its own and is cleared on the next refresh.
- The app cannot open sites that block automated visits, so some for-sale cars are marked "not
  confirmed". Open those yourself.
- Body style and trim are hard requirements: a coupe is compared only with coupes and a Carrera S
  only with Carrera S. Cars of another body style are dropped. A car of another trim is kept only
  as context: its note starts "Different trim", and it is switched off so it stays out of the
  numbers. The check compares the trim each source states, so a source that names no trim passes.
  When the car's trim line is only a detail of the car (2+2 seats, a body word, a gearbox) and not
  a version, every car of that model counts as the same version: an Evora 400 2+2 is compared with
  every Evora 400, whether or not the sale's page repeats "2+2".
- When a listing shows a VIN, the app looks it up in NHTSA's public VIN decoder
  (vpic.nhtsa.dot.gov) to check the trim. If the VIN is plainly more specific (the listing says
  Carrera, the VIN says Carrera S) the trim is corrected and a note says so; if the two disagree
  any other way, the note asks you to check it. Only the VIN is sent.
- The searches use Claude's built-in web search. Completed sales come from three or four searches
  that run at the same time: Classic.com, Cars & Bids, Bring a Trailer and the wider web. Each of
  the first three is limited to that one site, so it returns the site's own pages. Classic.com is
  the main source: it records the results of Bring a Trailer, Cars & Bids, PCARMARKET, Hagerty,
  Hemmings and Collecting Cars auctions with the price, the date, the miles and the VIN. Its
  search also opens Classic.com's market page for the model (Claude's web fetch tool) and reads
  every car on it with the link to that car's own page, which holds the VIN. If a key cannot use
  the fetch tool, the search carries on from the search results alone. Cars &
  Bids pages in search results are often copies made while the auction was still running, so they
  show no final price; those sales come through Classic.com.
- Some sites cannot be searched from the inside (the search tool turns the request down, as it
  does for Bring a Trailer). The app remembers that and does not ask again: the site's sales come
  from Classic.com, which records them, and from the search of the wider web.
- **An open car or a manual is searched for by name.** A plain search for a model returns its
  common kind (coupes, automatics), and those are no comparison for a Cabriolet or a manual, so
  they are left out. For such a car every sales search names the body style and the gearbox
  ("Porsche 911 Carrera S Cabriolet 7-speed manual"), runs across the generation's model years,
  and Classic.com's search opens the market it keeps for that exact kind. If fewer than three
  sales of the car's own body style and gearbox come back for any car, the app searches once
  more for exactly that kind (Classic.com and the wider web) and adds what it finds. An empty
  Sold tab says what the last search left out, and **Search for sales** then looks for the exact
  kind on every site.
- A sale read from one of Classic.com's lists of results, when that car's own page was not among
  the search results, links to the list and says "Listed on Classic.com" in its note.
- Results are merged so the same sale is not listed twice: the same page, the same VIN, or the
  same price and model year within three days. The record with a date and its own page is kept.
- If the search service is busy, a site's search is tried once more. If your key's rate limit is
  reached, the app waits as long as the API asks (40 seconds at most), says so in the live lines,
  and carries on; it gives up only after two waits. Every search of a run goes out at the same
  time (up to six requests at once), and the for-sale pages are opened, all together, as soon as
  that search is back, while the sales searches are still running. If the key's rate limit is
  reached, the app drops to two requests at a time for a minute and a half, so the searches take
  turns instead of failing together.
- KBB and J.D. Power listing pages are left out of every search: they copy dealers' listings and stay
  up after the car has gone. Any already saved are moved to the ended list.
- Every comp shows its VIN under its title, in the lists and in the pop-up on the chart; tap it to
  copy. When the app can open a for-sale page it also reads the VIN from it. The case shows how many comps came from each place, including "none" for those two.
- Every comp is labeled sold, high bid or asking, and its link is checked against the URLs the
  search actually returned. A link that was not in the results is flagged.
- Claude is told to record each car's own page, never a results page, and the app checks the link's
  shape for the common sites. It cannot open blocked sites to confirm a page still shows that car,
  and says "Not confirmed" for those instead of guessing.
- **Refresh results**, the button under the price on the main screen (and on The case tab), runs
  every search again for the car on screen: sales, no-sales and cars for sale now. While it runs,
  the button shows a clock and the line under it says what is happening. What you have stays, new finds are added, each for-sale page is
  opened again, and a sale that had been set aside only because its page left out a detail of the
  trim line is counted again.
- Treat every comp as a lead. Open the link and confirm it before you put it in front of a seller.

## Credits

- **3D coupe:** "Car Concept" by Eric Chadwick, (c) 2024 Darmstadt Graphics Group GmbH, licensed
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), from the
  [Khronos glTF Sample Assets](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/CarConcept).
  Modified for this app: logos removed, simplified and repainted. Details in `static/models/CREDITS.md`.
  The credit shows under the car whenever the model is on screen.
- **three.js** and its glTF loader (MIT), **DM Sans** and **JetBrains Mono** (SIL Open Font License).

**A 3D model of the actual car.** The app does not ship models of real cars. The picker on the
main screen and **Find models** in the **3D model** tab search Sketchfab's public library and show
the results in the app. Tap one and it plays on the main screen in Sketchfab's own viewer, with the
artist's name on it: no account, and nothing is downloaded or stored in the app. The app sets that
viewer's backdrop to the studio's own colour and frames the car the way the studio camera would
(same lens, distance and height), turns it slowly while nobody is touching it, and lays the page's
shading and a ground shadow over it. Some models stand the car on a floor or platform much bigger
than the car, which would make the car tiny: the app measures the car itself (it asks the viewer
where rays through the scene land), frames that, and hides a floor that is a separate piece. So the car sits in the page instead of in a window. Touch and
mouse go to the viewer's own controls; when you let go, the app returns the car to its framing. (The viewer's picture cannot be made see-through on a free account, which
is why the studio around a live car is one flat colour.) With a free Sketchfab account you can instead
download a model into the studio (paste your API token once), or load a `.glb` file or link you
already have. Your choice is kept in your browser on your device only and is used for every car of
that make and model in your garage. Use only models whose licence allows it.

To bundle another model with the app, put a `.glb` in `static/models/`, add it to `PRO_MODELS` in
`showcase.py` with its credit, and name its body-paint material `Paint`.

## Files

| File | What it does |
| --- | --- |
| `app.py` | The state, the Claude steps, and the Edit and print section |
| `stage.py` | The main screen (a Streamlit v2 component: HTML, CSS, JavaScript with three.js) |
| `showcase.py` | Paint colors, body shapes and the credited 3D models the main screen uses |
| `previews.py` | Listing pages and photos: link previews and screenshot crops |
| `llm.py` | Claude calls: read a listing, research comps, suggest an offer, draft a message |
| `sheet.py` | Builds the PDF and its QR codes |
| `calc.py` | Money math, comp helpers, the direct-link check, and the reading of Classic.com's and Bring a Trailer's pages |
| `bat.py` | Asks Bring a Trailer for its own record of a model's auctions, slowly and only where its robots.txt allows |
| `sync.py` | The shared garage: loads and saves cars in the garage store, and decides which copy of a car stays |
| `styles.py` | The stylesheet for the Streamlit widgets |
| `sample_deal.json` | The sample car (2020 911 Carrera S, researched Nov 14, 2026) |
| `static/` | Fonts, three.js with its glTF loader, and the 3D model in `static/models/` |
| `tools/` | The script that prepared the 3D model from the original file, and `garage_store.sql`, which sets up the shared garage's table |
| `tools/stage/` | The main screen's own source: its Python head, HTML, CSS and JavaScript. `python tools/stage/build.py` checks the JavaScript and writes `stage.py` from them. Edit these, never `stage.py` |
| `tests/` | Browser tests that run the app against stand-ins for the API and for car sites, with no key and nothing real called. `tests/e2e/run.sh` runs them; `tests/README.md` says what they can and cannot show |
| `assets/fonts/` | The same fonts as TTF for the PDF |
