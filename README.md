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

- **The car.** A 3D car in the listing's paint color that you can drag to spin: a simple shape of the
  right body type (coupe, convertible, sedan, hatchback, wagon, SUV, pickup or van), or, for coupes,
  a detailed concept coupe if you pick it (see Credits). Neither is a model of any maker's design.
  To see the actual car in 3D, pick a model of it in the **3D model** tab (see below).
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
- **VINs.** The car's VIN shows under the title and each comp's VIN on its card; tap one to copy it.
  When a listing leaves the VIN out, the app says so. Comp VINs are also read out of links that
  contain them (Classic.com's do).
- **Sold, and for sale now.** Completed sales and the cars you could buy today are separate lists,
  each with a **Search for more** button that looks for cars not already found. For-sale cars come
  from live auctions, enthusiast classifieds and dealers. The app opens each for-sale page, where
  the site allows it, and moves a car to "sold or gone" when its page says so; **Check they are
  still for sale** does that again. Each card says whether its page was checked.
  Each comp has a button that opens that car's own page. A link that opens a list of
  results instead of one car is flagged on the screen and on the PDF, and is never offered as the
  proof link for a point in the case.
- **Message.** A drafted offer message with a Copy button.
- **Garage.** Each car you add is a chip at the top. Tap one to switch.
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
  tokens, and the settings panel caps the number of searches per run.

Everything except the Claude features works without a key.

## What is kept on your device

Your cars (with their comps, offers and photos) and your settings (tax, fees, loan terms, your first
name, the model and the search limit) are saved in the browser you used, and come back when you
reopen the app there. Removing a car removes its saved copy. Nothing is stored on a server.
To move your cars to another device or keep a backup, save the garage to a file from the settings
panel and open that file on the other device.

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

The app offers Claude Sonnet 5.5, Haiku 5.5 and Opus 5.5. Sonnet 5.5 and Opus 5.5 reject a forced
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

## What to expect from the web research

- Results come from Claude's web search tool, so they are search results, not page scrapes.
- Every run searches Bring a Trailer and Cars & Bids first, then other auction sites. A second
  search then looks for cars for sale right now: live auctions (Bring a Trailer, Cars & Bids,
  PCARMARKET), enthusiast classifieds (for a Porsche, Rennlist and the PCA Mart), the maker's
  pre-owned finder, dealers and listing sites. Price-guide mirrors such as KBB are left out because
  they keep listings up after the car has gone.
- The app cannot open sites that block automated visits, so some for-sale cars are marked "not
  confirmed". Open those yourself. The case shows how many comps came from each place, including "none" for those two.
- Every comp is labeled sold, high bid or asking, and its link is checked against the URLs the
  search actually returned. A link that was not in the results is flagged.
- Claude is told to record each car's own page, never a results page, and the app checks the link's
  shape for the common sites. It cannot open blocked sites to confirm a page still shows that car.
- Treat every comp as a lead. Open the link and confirm it before you put it in front of a seller.

## Credits

- **3D coupe:** "Car Concept" by Eric Chadwick, (c) 2024 Darmstadt Graphics Group GmbH, licensed
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), from the
  [Khronos glTF Sample Assets](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/CarConcept).
  Modified for this app: logos removed, simplified and repainted. Details in `static/models/CREDITS.md`.
  The credit shows under the car whenever the model is on screen.
- **three.js** and its glTF loader (MIT), **DM Sans** and **JetBrains Mono** (SIL Open Font License).

**A 3D model of the actual car.** The app does not ship models of real cars. In the **3D model** tab,
**Find models** searches Sketchfab's public library and shows the results in the app. Tap one and
it plays on the main screen in Sketchfab's own viewer, with the artist's name on it: no account,
and nothing is downloaded or stored in the app. With a free Sketchfab account you can instead
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
| `calc.py` | Money math, comp helpers and the direct-link check |
| `styles.py` | The stylesheet for the Streamlit widgets |
| `sample_deal.json` | The sample car (2020 911 Carrera S, researched Nov 14, 2026) |
| `static/` | Fonts, three.js with its glTF loader, and the 3D model in `static/models/` |
| `tools/` | The script that prepared the 3D model from the original file |
| `assets/fonts/` | The same fonts as TTF for the PDF |
