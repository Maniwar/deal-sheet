# Tests

`tests/e2e/run.sh` runs the app in a phone-sized browser against stand-ins, so nothing real is called and no
API key is needed:

| File | What it stands in for |
| --- | --- |
| `fake_api.py` | The Anthropic API: searches, opened pages, the offer and the message. Keys ending in `oldfetch`, `nofetch`, `blockfetch`, `nocg`, `noads` and `lists1` play a key with an older page reader, none, one every site turns away, a search tool that cannot be limited to a site, and a second run with changed prices. |
| `site.py` | Car listing pages: live, sold, redirected, blocked by robots.txt, another car's VIN, and so on. |
| `fake_vin.py`, `fake_skfb.py` | The VIN decoder and the 3D model search. |
| `fake_db.py` | The garage store (the two functions of `tools/garage_store.sql`), kept in memory. Only the `shared` and `cutshort_shared` tests start the app with it. |

`shared.js` plays two devices with one key (the car appears on the second with no search, the newer copy
wins, a removed car stays removed, another key sees nothing, the store goes down and comes back).
`cutshort.js` starts the app so that it waits before drawing a car it has just loaded, and taps the page
meanwhile: the car must survive a run that is cut short.
`kind.js` uses keys ending `kindfew` and `kindnone`, for which a plain search returns only the model's other
kinds (automatics, an open car): the app must search again for the car's exact kind, and say what was left
out when nothing of the kind exists. `kind_test.py` checks the words the searches name for such a car.
`market.js` uses a key ending `market`: the search opens Classic.com's market page for one model year and
the model copies one row of it with no seller named, as real runs do. The app must read every row itself,
open the whole market on its own, tell an auction result from a dealer's asking price, offer a search for
each auction's own page, and take the price from that page when its link is pasted. `rows_test.py` checks
the reading of the page (as the page reader returns it and as a search shows it) and of an auction's page.
The page layout in these tests is the one seen in search results on Nov 17, 2026; whether the page reader
returns the same layout is checked on a real run, and the step log says so when no row could be read.

The tests (`*.js`) each print what they saw and end with an `errors:` line. `judge_test.py` and
`judge_real.py` are unit tests of how a listing page's wording is read (for sale, sold, gone).

What these tests cannot show is how the real sites and the real API behave: page formats, which sites let a
reader in, what a search returns. That is checked by running the live app with a real key, and the step log
("Every step of the last search" in The case) is written to make that check quick: it names every page
opened, how much text came back and how many cars it held.
