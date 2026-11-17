"""Classic.com's market page read by the app itself, the search that finds a sale's own auction page, and the
check of a sale against that page."""
import sys
sys.path.insert(0, ".")
import calc

CAB = {"year": 2014, "make": "Porsche", "model": "911", "trim": "Carrera S", "body": "Cabriolet", "transmission": "7-speed manual",
       "miles": 20178, "price": 99995}
MARKET = "https://www.classic.com/m/porsche/911/991/9911/carrera-s/cabriolet-manual/"

# The page as Claude's page reader returns it: one fact a line, no links.
PAGE = """2014 Porsche 911 Carrera S Cabriolet - Manual Market - CLASSIC.COM
Markets
Porsche 911 - 991 Carrera S Cabriolet - Manual
CMB $72,418
For Sale 3
Sold 14
### 2014 Porsche 911 Carrera S Cabriolet 7-Speed
Original & Highly Original
6865 mi 10k mi
Manual transmission Manual
LHD steering LHD
Palm Springs, California, USA
Sold
$108,000
Aug 22, 2026
$108,000
Bring a Trailer
Auction
Aug 22, 2026
2 months ago
### 2014 Porsche 911 Carrera S Cabriolet
Original & Highly Original
6865 mi 43k mi
Manual transmission Manual
LHD steering LHD
Saint Louis, Missouri, USA
Sold
$110,000
Jul 2, 2026
$110,000
Cars & Bids
Auction
Jul 2, 2026
4 months ago
### 2015 Porsche 911 Carrera S Cabriolet
Original & Highly Original
6865 mi 29.5k mi
Manual transmission Manual
LHD steering LHD
Ann Arbor, Michigan, USA
Sold
$82,500
Jun 16, 2025
$82,500
SellYourSportscar.Net
Fixed-price
Jun 16, 2025
1 year ago
### 2012 Porsche 911 Carrera S Cabriolet - Manual
Original & Highly Original
6865 mi 29k mi
Manual transmission Manual
LHD steering LHD
Hingham, Massachusetts, USA
Not Sold
$66,850
Jun 24, 2025
Highest Bid
PCARMARKET
Auction
Jun 24, 2025
1 year ago
### 2013 Porsche 911 Carrera S Cabriolet
Modified
6865 mi 51k mi
Manual transmission Manual
LHD steering LHD
Dallas, Texas, USA
For Sale
$74,900
Porsche Plano
Fixed-price
Oct 30, 2026
2 weeks ago
### 2014 Porsche 911 Carrera S Cabriolet
Original & Highly Original
Manual transmission Manual
Scottsdale, Arizona, USA
Price Undisclosed
Mecum
Auction
### 2013 Porsche 911 Carrera S Cabriolet 7-Speed
6865 mi 20k mi
Manual transmission Manual
Tampa, Florida, USA
Last Asking
$77,000
Apr 4, 2025
Some Dealer LLC
Fixed-price
"""
# The same page as a search shows it: a row a line, each with the car's own page.
LINKED = ("2017 Lotus Evora 400 Market\n"
          "[2017 Lotus Evora 400](https://www.classic.com/veh/2017-lotus-evora-400-scclmdvn1hha10600-WLO2NOn/) Sold $72,000 May 14, 2026 5k mi Bring a Trailer\n"
          "[2017 Lotus Evora 400](/veh/2017-lotus-evora-400-scclmdvn1hha21306-pJQb6gW/) Not Sold Highest Bid $55,500 Jun 18, 2026 18k mi Cars & Bids\n"
          "[2017 Lotus Evora 400](/veh/2017-lotus-evora-400-scclmdvn7hha21021-Wbwoevp/) For Sale $67,900 Oct 5, 2026 27k mi Autopro Of Nashville")

rows = calc.classic_rows(PAGE, "Porsche")
flat = calc.classic_rows(" ".join(PAGE.split()), "Porsche")
linked = calc.classic_rows(LINKED, "Lotus")
by_price = {row["price"]: row for row in rows}
comps = calc.clean_comps(calc.market_comps(rows, MARKET))
sold = {comp["price"]: comp for comp in comps}
cases = [
    (len(rows), 6),                                                       # the heading, the estimate and the undisclosed price are no rows
    ([row["price"] for row in rows], [108000, 110000, 82500, 66850, 74900, 77000]),
    ([(row["price"], row["state"], row["date"], row["miles"], row["seller"], row["kind"]) for row in flat],
     [(row["price"], row["state"], row["date"], row["miles"], row["seller"], row["kind"]) for row in rows]),     # one long line reads the same
    ((by_price[108000]["state"], by_price[108000]["date"], by_price[108000]["miles"], by_price[108000]["seller"], by_price[108000]["kind"]),
     ("sold", "Aug 22, 2026", 10000, "Bring a Trailer", "auction")),
    (by_price[108000]["place"], "Palm Springs, California, USA"),
    (by_price[108000]["title"], "2014 Porsche 911 Carrera S Cabriolet 7-Speed"),
    (by_price[82500]["miles"], 29500),                                    # '29.5k mi'
    ((by_price[82500]["seller"], by_price[82500]["kind"]), ("SellYourSportscar.Net", "fixed")),
    ((by_price[66850]["state"], by_price[66850]["seller"]), ("not sold", "PCARMARKET")),
    ((by_price[74900]["state"], by_price[74900]["seller"]), ("for sale", "Porsche Plano")),      # a dealer named after the make starts no row
    ((by_price[77000]["state"], by_price[77000]["seller"]), ("last asking", "Some Dealer LLC")),
    (all(row["gearbox"] == "manual" for row in rows), True),
    ([(row["price"], row["seller"], row["page"].split("-")[-1]) for row in linked],
     [(72000, "Bring a Trailer", "WLO2NOn/"), (55500, "Cars & Bids", "pJQb6gW/"), (67900, "Autopro Of Nashville", "Wbwoevp/")]),
    (len(calc.classic_rows(LINKED)), 3),                                  # with no make to go by
    (calc.classic_rows("Nothing here but words. Sold 14. For Sale 3.", "Porsche"), []),
    # ---- as comps
    ([(comp["status"], comp["price"], comp.get("available")) for comp in comps],
     [("sold", 108000, ""), ("sold", 110000, ""), ("sold", 82500, ""), ("high_bid", 66850, ""), ("asking", 74900, "yes"), ("asking", 77000, "no")]),
    (sold[108000]["source"], "Bring a Trailer"),
    (sold[108000]["note"].startswith("Listed on Classic.com. Auction result."), True),
    (calc.DEALER_SOLD in sold[82500]["note"] and calc.DEALER_SOLD not in sold[108000]["note"], True),
    (sold[108000]["url"], MARKET),
    ((calc.proof(sold[108000]), calc.is_lead(sold[108000])), ("auction", False)),      # a named auction on a known day: it counts
    ((calc.proof(sold[82500]), calc.is_lead(sold[82500])), ("list", True)),            # a dealer's listing: nothing to look up
    (calc.own_page(sold[108000]), False),                                 # but it has no page of its own yet
    # ---- which market pages to read
    (calc.classic_market(MARKET + "year-2014/", whole=True), MARKET),
    (calc.classic_market("https://www.classic.com/veh/2014-porsche-911-x/"), ""),
    (calc.market_fits(CAB, MARKET), True),
    (calc.market_fits(CAB, MARKET.replace("cabriolet-manual", "coupe-manual")), False),
    (calc.market_fits(CAB, MARKET.replace("cabriolet-manual", "cabriolet-pdk")), False),
    (calc.market_pages(CAB, [MARKET + "year-2014/", MARKET + "year-2015", "https://www.classic.com/m/porsche/911/991/",
                             MARKET.replace("cabriolet-manual", "coupe-pdk"), "https://bringatrailer.com/porsche/"]),
     [MARKET, "https://www.classic.com/m/porsche/911/991/"]),
    # ---- a lot of an auction on Classic.com is one car's page; the auction's page is a list
    (calc.is_list_page("https://www.classic.com/a/bring-a-trailer-auctions-JknXEWB/lots/2012-porsche-911-carrera-s-cabriolet-abc/"), False),
    (calc.is_list_page("https://www.classic.com/a/bring-a-trailer-auctions-JknXEWB/"), True),
    (calc.is_list_page(MARKET), True),
]

# the model's copies of the page give way to the page's own rows; a car it found on its own page stays and is filled in
model = calc.clean_comps([
    {"status": "sold", "title": "2014 Porsche 911 Carrera S Cabriolet (Palm Springs, CA)", "price": 108000, "date": "Aug 22, 2026", "miles": 10000,
     "source": "Classic.com market (seller not named)", "url": MARKET + "year-2014/", "note": "Listed on Classic.com market page; no VIN shown."},
    {"status": "high_bid", "title": "2014 Porsche 911 Carrera S Cabriolet", "price": 110000, "source": "Classic.com", "url": MARKET,
     "note": "Listed on Classic.com."},                                   # the model misread a sale as a no-sale
    {"status": "sold", "title": "2015 Porsche 911 Carrera S Cabriolet", "price": 82500, "source": "Classic.com",
     "url": "https://www.classic.com/veh/2015-porsche-911-carrera-s-cabriolet-wp0cb2a98fs155165-XyZ/", "note": "7-speed manual."},
    {"status": "sold", "title": "2012 Porsche 911 Carrera S Cabriolet", "price": 71250, "date": "Feb 25, 2024", "source": "Classic.com",
     "url": MARKET, "note": "Listed on Classic.com."},                    # not on the page the app read: it stays
])
merged = calc.swap_in_rows(model, comps)
at = {(comp["status"], comp["price"]): comp for comp in merged}
cases += [
    (len(merged), 7),
    (at[("sold", 108000)]["source"], "Bring a Trailer"),
    (("high_bid", 110000) in at, False),
    (at[("sold", 110000)]["source"], "Cars & Bids"),
    (at[("sold", 82500)]["url"].endswith("XyZ/"), True),                  # its own page is kept
    (at[("sold", 82500)]["source"], "SellYourSportscar.Net"),             # and it learns who sold it
    (calc.DEALER_SOLD in at[("sold", 82500)]["note"], True),
    (at[("sold", 82500)]["vin"], "WP0CB2A98FS155165"),
    (("sold", 71250) in at, True),
]

# cars held from an earlier search, copied off the market page by the model, take what the page says
held = calc.clean_comps([
    {"status": "sold", "title": "2014 Porsche 911 Carrera S Cabriolet (Palm Springs, CA)", "price": 108000, "date": "Aug 22, 2026", "miles": 10000, "use": True,
     "aside": "mine", "source": "Classic.com market (seller not named)", "url": MARKET + "year-2014/", "note": "Listed on Classic.com market page; no VIN shown."},
    {"status": "sold", "title": "2015 Porsche 911 Carrera S Cabriolet (Ann Arbor, MI)", "price": 82500, "date": "Jun 16, 2025", "source": "SellYourSportscar.Net",
     "url": MARKET, "note": "Listed on Classic.com market page."},
    {"status": "sold", "title": "2015 Porsche 911 Carrera S Cabriolet 7-Speed", "price": 52500, "source": "PCARMARKET",
     "url": "https://www.pcarmarket.com/auction/marketplace-2015-porsche-911-carrera-s-cabriolet/", "note": "Its own page."},
    {"status": "sold", "title": "2014 Porsche 911 Carrera S Cabriolet", "price": 110000, "source": "Added by you", "url": MARKET, "note": "Added by you."},
])
count = calc.take_rows(held, comps)
cases += [
    (count, 2),
    ((held[0]["source"], held[0]["title"], held[0]["aside"], held[0]["use"]), ("Bring a Trailer", "2014 Porsche 911 Carrera S Cabriolet 7-Speed", "mine", True)),
    (held[0]["note"], "Listed on Classic.com. Auction result. Palm Springs, California, USA."),
    (calc.DEALER_SOLD in held[1]["note"], True),
    (held[2]["note"], "Its own page."),                                   # a car on its own page is left alone
    (held[3]["source"], "Added by you"),                                  # and so is one the buyer added
    (calc.take_rows(held, comps), 0),                                     # nothing more to bring up to date
]

# a search that finds the auction's own page
find, on = calc.auction_find(at[("sold", 108000)])
cases += [
    (on, "Bring a Trailer"),
    (find, "https://www.google.com/search?q=site%3Abringatrailer.com+2014+Porsche+911+Carrera+S+Cabriolet+7-Speed+%22%24108%2C000%22"),
    (calc.auction_find(at[("sold", 82500)]), ("", "")),                   # a dealer's listing has no auction page
    (calc.auction_find({**at[("sold", 108000)], "url": "https://bringatrailer.com/listing/2014-porsche-911-carrera-s-cabriolet-20/"}), ("", "")),
    (calc.auction_find(sold[74900]), ("", "")),                           # nor has a car for sale
]

# how an auction ended, read off its own page: the page's words before its title
BAT = ("Page title: 10k-Mile 2014 Porsche 911 Carrera S Cabriolet 7-Speed for sale on BaT Auctions - sold for $108,000 on August 22, 2026 (Lot #259,232) | Bring a Trailer\n"
       "Page text: 10k-Mile 2014 Porsche 911 Carrera S Cabriolet 7-Speed Sold for USD $108,000 on 8/22/26 Chassis: WP0CB2A96ES154062 10k Miles")
LATER = ("Page title: 44k-Mile 2015 Porsche 911 Carrera S Cabriolet 7-Speed for sale on BaT Auctions - bid to $86,000 on August 26, 2026 (Lot #259,826) | Bring a Trailer\n"
         "Page text: 44k-Mile 2015 Porsche 911 Carrera S Cabriolet 7-Speed Sold for USD $88,000 on 8/26/26 Chassis: WP0CB2A98FS155165")
NOSALE = "Page title: 2013 Porsche 911 Carrera S Cabriolet | Cars & Bids\nPage text: Reserve not met. Bid to $61,500 on September 9, 2026"
cases += [
    (calc.auction_result(BAT), {"status": "sold", "price": 108000, "date": "8/22/26"}),
    (calc.auction_result(LATER), {"status": "sold", "price": 88000, "date": "8/26/26"}),       # sold after the auction closed
    (calc.auction_result(NOSALE), {"status": "high_bid", "price": 61500, "date": "September 9, 2026"}),
    (calc.auction_result("Page title: Used 2019 BMW M2 | Test Motors\nPage text: $54,900 Call us today."), {}),
]
same = dict(at[("sold", 108000)])
said = calc.settle_sale(same, calc.auction_result(BAT))
off = calc.clean_comp({"status": "high_bid", "title": "2015 Porsche 911 Carrera S Cabriolet", "price": 86000, "date": "Aug 26, 2026",
                       "source": "Bring a Trailer", "url": "https://bringatrailer.com/listing/2015-porsche-911-carrera-s-cabriolet-12/", "note": "Listed on Classic.com."})
fixed = calc.settle_sale(off, calc.auction_result(LATER))
far = dict(at[("sold", 108000)])
warned = calc.settle_sale(far, {"status": "sold", "price": 51911, "date": ""})
cases += [
    (said, "The auction's own page agrees: sold for $108,000."),
    (same["note"].startswith("Checked on the auction's own page: sold for $108,000 on Aug 22, 2026."), True),
    ("Listed on Classic.com" in same["note"] or "Auction result" in same["note"], False),
    ((off["status"], off["price"], off["date"]), ("sold", 88000, "Aug 26, 2026")),
    ("says sold for $88,000, where the list had a high bid of $86,000" in fixed, True),
    ((far["price"], "nothing was changed" in warned), (108000, True)),
    (calc.settle_sale(dict(same), {}), ""),
]

# a message cites an auction result before a dealer's last asking price
NOV17 = calc.date_key("Nov 17, 2026")
pair = calc.clean_comps([
    {"status": "sold", "title": "2014 Porsche 911 Carrera S Cabriolet", "price": 90000, "miles": 21000, "date": "Sep 1, 2026", "source": "Some Dealer",
     "url": MARKET, "note": "Listed on Classic.com. " + calc.DEALER_SOLD},
    {"status": "sold", "title": "2013 Porsche 911 Carrera S Cabriolet", "price": 90500, "miles": 30000, "date": "Aug 1, 2026", "source": "Bring a Trailer",
     "url": MARKET, "note": "Listed on Classic.com. Auction result."}])
cases += [(calc.cite_sales(CAB, pair, limit=1, offer=91000, today=NOV17)[0]["price"], 90500)]

bad = [(i, got, want) for i, (got, want) in enumerate(cases) if got != want]
for row in bad:
    print("FAILED", row)
print(f"market page cases: {len(cases)} failures: {len(bad)}")
