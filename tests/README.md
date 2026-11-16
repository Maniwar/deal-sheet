# Tests

`tests/e2e/run.sh` runs the app in a phone-sized browser against stand-ins, so nothing real is called and no
API key is needed:

| File | What it stands in for |
| --- | --- |
| `fake_api.py` | The Anthropic API: searches, opened pages, the offer and the message. Keys ending in `oldfetch`, `nofetch`, `blockfetch`, `nocg`, `noads` and `lists1` play a key with an older page reader, none, one every site turns away, a search tool that cannot be limited to a site, and a second run with changed prices. |
| `site.py` | Car listing pages: live, sold, redirected, blocked by robots.txt, another car's VIN, and so on. |
| `fake_vin.py`, `fake_skfb.py` | The VIN decoder and the 3D model search. |

The tests (`*.js`) each print what they saw and end with an `errors:` line. `judge_test.py` and
`judge_real.py` are unit tests of how a listing page's wording is read (for sale, sold, gone).

What these tests cannot show is how the real sites and the real API behave: page formats, which sites let a
reader in, what a search returns. That is checked by running the live app with a real key, and the step log
("Every step of the last search" in The case) is written to make that check quick: it names every page
opened, how much text came back and how many cars it held.
