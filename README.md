# Deal Sheet

A Streamlit app that turns a car listing into a printable negotiation sheet.

1. **Car.** Paste a listing or add a screenshot. Claude fills in the car's details.
2. **Comps.** Claude searches the web for completed sales, unsold auctions and asking prices.
   You can also add comps by hand, or paste a results page and let Claude structure it.
3. **Offer.** Claude suggests an opening offer, a target and a walk-away price from your comps.
   The app works out tax, the out-the-door total and the monthly payment.
4. **Sheet.** Download a PDF with every link printed in full beside a large QR code (1.1 in, or 1.5 in
   if you pick Extra large), plus an offer message.
   The seller copy leaves out your target, walk-away price and notes. The private copy keeps them.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app opens with a sample deal so you can see every screen before adding a key.

## API key

Claude features need an Anthropic API key (https://console.anthropic.com). Either:

- paste it into the sidebar (kept for that session only), or
- copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and put the key there, or
- set the `ANTHROPIC_API_KEY` environment variable.

Usage is billed to that key. Web research is billed per search on top of tokens, and the sidebar
caps the number of searches per run.

## Put it online (so it works on a phone)

1. Push this folder to a GitHub repository.
2. Create an app on Streamlit Community Cloud that points at `app.py`.
3. Paste the contents of your `secrets.toml` into the app's Secrets box.
4. Set `APP_PASSWORD` in the secrets if the app is public, so strangers cannot spend your key.

## What to expect from the web research

- Results come from Claude's web search tool, so they are search results, not page scrapes.
  Classic.com, Cars.com and Bring a Trailer block automated visits; the app does not work around that.
- Every comp is labeled sold, high bid or asking, and its link is checked against the URLs the
  search actually returned. A link that was not in the results is flagged in amber.
- Treat every comp as a lead. Open the link and confirm it before you put it in front of a seller.
- For a blocked site, open the page yourself and paste its text or a screenshot into
  "Add comps from a pasted page or screenshot".

## Files

| File | What it does |
| --- | --- |
| `app.py` | The screens and the state |
| `llm.py` | Claude calls: read a listing, research comps, suggest an offer, draft a message |
| `sheet.py` | Builds the PDF and its QR codes |
| `calc.py` | Money math and comp helpers |
| `styles.py` | The app's stylesheet |
| `sample_deal.json` | The sample deal (2020 911 Carrera S, researched Nov 14, 2026) |
| `static/`, `assets/fonts/` | DM Sans and JetBrains Mono (SIL Open Font License) for the app and the PDF |

Deals can be saved and reopened as JSON files from the sidebar. Nothing is stored on a server.
