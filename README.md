# Deal Sheet

A Streamlit app that turns a car listing into a negotiation brief you can print and hand over.

## What you see

- **A 3D showroom.** The car sits on a turntable you can drag to spin (WebGL, three.js). With a photo it
  shows the photo as a lit slab; without one it draws a hologram in the car's color. In front of it,
  the comps stand as glowing markers on a price runway, with the asking price as a beacon and your
  offer range as a lit band. Tap a marker to open that listing.
- **A comps carousel.** Each comp is a card with its photo (or a mini price map), and the whole card
  links straight to its source.
- **Four steps underneath.**
  1. **Car.** Paste a listing or add a screenshot. Claude fills in the details and cuts the car's
     photo out of the screenshot.
  2. **Comps.** Claude searches the web for completed sales, unsold auctions and asking prices. You can
     also add comps by hand, or drop in a screenshot of a results page.
  3. **Offer.** Claude suggests an opening offer, a target and a walk-away price. The app works out
     tax, the out-the-door total and the monthly payment.
  4. **Sheet.** A PDF with every link printed in full beside a large QR code (1.1 in, or 1.5 in), plus
     an offer message. The seller copy leaves out your target, walk-away price and notes.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app opens with a sample deal so you can try every screen before adding a key.

## Bring your own key

Claude features need an Anthropic API key. Each person pastes their own into the box at the top of
the page; a button beside it opens the Claude Console keys page (https://platform.claude.com/settings/keys).

- The key is checked with a free call when it is pasted.
- It is held in memory for that browser session only. It is not written to disk, logged, put in a
  saved deal or printed on the PDF, and reloading the page forgets it.
- The app never reads a key from secrets or environment variables, so a public copy cannot spend
  the owner's key.
- Usage is billed to whoever's key is connected. Web research is billed per search on top of
  tokens, and the sidebar caps the number of searches per run.

Everything except the Claude buttons works without a key.

## Where the pictures come from

1. **Your upload.** A car photo you add in the Car tab.
2. **Your screenshots.** Claude finds the car photo inside a listing screenshot, and each car's photo
   inside a results-page screenshot, and the app cuts them out.
3. **The listing's own preview image.** For each link, the app asks the page for the picture it
   publishes for sharing (its `og:image`), the way a chat app builds a link preview.

The preview fetch identifies itself, obeys each site's robots.txt, only talks to public internet
hosts, and never tries to get past a block. Classic.com, Cars.com and Bring a Trailer refuse
automated visits, so comps from those sites show a mini price map instead of a photo unless you
add a screenshot. The app does not use a headless or stealth browser, on purpose.
Turn the fetch off in the sidebar under Photos.

## Put it online

1. Push this folder to a GitHub repository.
2. Create an app on Streamlit Community Cloud that points at `app.py`.
3. No secrets are required. Visitors paste their own key.
4. Optional: set `APP_PASSWORD` in the app's Secrets box to put a password in front of the app.

## What to expect from the web research

- Results come from Claude's web search tool, so they are search results, not page scrapes.
- Every comp is labeled sold, high bid or asking, and its link is checked against the URLs the
  search actually returned. A link that was not in the results is flagged.
- Treat every comp as a lead. Open the link and confirm it before you put it in front of a seller.

## Files

| File | What it does |
| --- | --- |
| `app.py` | The screens and the state |
| `showcase.py` | The 3D showroom and comps carousel (a Streamlit v2 component: HTML, CSS, JavaScript) |
| `previews.py` | Listing photos: link previews and screenshot crops |
| `llm.py` | Claude calls: read a listing, research comps, suggest an offer, draft a message |
| `sheet.py` | Builds the PDF and its QR codes |
| `calc.py` | Money math and comp helpers |
| `styles.py` | The stylesheet for the Streamlit widgets |
| `sample_deal.json` | The sample deal (2020 911 Carrera S, researched Nov 14, 2026) |
| `static/` | Fonts (DM Sans, JetBrains Mono, SIL Open Font License) and three.js (MIT) |
| `assets/fonts/` | The same fonts as TTF for the PDF |

Deals save and reopen as JSON files from the sidebar, photos included. Nothing is stored on a server.
