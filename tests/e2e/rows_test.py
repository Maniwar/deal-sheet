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
NOV17 = calc.date_key("Nov 17, 2026")
comps = calc.clean_comps(calc.market_comps(rows, MARKET, today=NOV17))
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
     [("sold", 108000, ""), ("sold", 110000, ""), ("sold", 82500, ""), ("high_bid", 66850, ""), ("asking", 74900, "yes")]),      # an asking price from April 2025 is history
    ([(comp["status"], comp["price"]) for comp in calc.market_comps(rows, MARKET, today=calc.date_key("Dec 1, 2025"))][-1], ("asking", 77000)),
    ([comp["price"] for comp in calc.market_comps(rows, MARKET, old=True, today=NOV17)], [108000, 110000, 82500, 66850]),       # an old copy: 'for sale' may not be
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
     [MARKET]),                                                           # the market kept for this kind, not the general one
    (calc.market_pages(CAB, ["https://www.classic.com/m/porsche/911/991/", "https://www.classic.com/m/porsche/911/"]), ["https://www.classic.com/m/porsche/911/991/"]),
    (calc.market_fits(CAB, MARKET.replace("cabriolet-manual", "50th-anniversary-manual")), False),      # another version's market
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
    (len(merged), 6),
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
pair = calc.clean_comps([
    {"status": "sold", "title": "2014 Porsche 911 Carrera S Cabriolet", "price": 90000, "miles": 21000, "date": "Sep 1, 2026", "source": "Some Dealer",
     "url": MARKET, "note": "Listed on Classic.com. " + calc.DEALER_SOLD},
    {"status": "sold", "title": "2013 Porsche 911 Carrera S Cabriolet", "price": 90500, "miles": 30000, "date": "Aug 1, 2026", "source": "Bring a Trailer",
     "url": MARKET, "note": "Listed on Classic.com. Auction result."}])
cases += [(calc.cite_sales(CAB, pair, limit=1, offer=91000, today=NOV17)[0]["price"], 90500)]

# The page as a browser shows it (what a person copies and pastes): statuses in capitals, a count of photos
# above some titles, the seller named for a dealer and locked for a past auction, a live auction with no price.
BROWSER = """Showing 24 of 30 related listings
Default Sort
Price (lowest first)
Vehicle Year (oldest first)
bookmark_border
33
2013 Porsche 911 Carrera S
ORIGINAL & HIGHLY ORIGINAL
89k mi
Manual
LHD
Indio, California, USA
FOR SALE
$76,029*
Oct 23, 2026
Updated 25 days ago
Desert Private Collection
verified
Fixed-price
CONTACT SELLER
bookmark_border
2012 Porsche 911 Carrera S
ORIGINAL & HIGHLY ORIGINAL
25k mi
Manual
LHD
Las Vegas, Nevada, USA
FOR SALE
Nov 20, 2026
Ends in 3 days
Bring a Trailer
Auction
VIEW AUCTION
bookmark_border
2015 Porsche 911 Carrera S
ORIGINAL & HIGHLY ORIGINAL
44k mi
Manual
LHD
Naples, Florida, USA
SOLD
$88,000
Aug 27, 2026
2 months ago
Auction
View Source
lock
bookmark_border
2014 Porsche 911 Carrera S
ORIGINAL & HIGHLY ORIGINAL
10k mi
Manual
LHD
Palm Springs, California, USA
SOLD
$108,000
Aug 22, 2026
2 months ago
Auction
View Source
lock
bookmark_border
29
2012 Porsche 911 Carrera S
ORIGINAL & HIGHLY ORIGINAL
29k mi
Manual
LHD
City of Glen Cove, New York, USA
LAST ASKING
$109,995
Jul 21, 2026
3 months ago
Fixed-price
bookmark_border
11
"""
# An old copy of the page, as a page reader hands it back: the town above a second title, icon names as words,
# a notice after a last asking price, no seller for an auction, and the page's footer after the last car.
STALE = """Showing 5 of 5 related listings
2014 Porsche 911 Carrera S
City of Glen Cove, New York, USA
34
2014 Porsche 911 Carrera S
Original & Highly Original
6865 mi 453 mi
Manual transmission Manual
LHD steering LHD
Last Asking
$109,995
info
This listing was either sold, or removed, by the seller. The last asking price is the last price detected by Classic.com.
Ryan Friedman Motor Cars
verified
verified Verified Seller
Feb 8, 2025
2014 Porsche 911 Carrera S
Akron, OH, USA
2014 Porsche 911 Carrera S
Original & Highly Original
6865 mi 37k mi
Manual transmission Manual
LHD steering LHD
Price Undisclosed
Jul 9, 2022
2014 Porsche 911 Carrera S Cabriolet 7-Speed
San Diego, CA, USA
12
2014 Porsche 911 Carrera S Cabriolet 7-Speed
Original & Highly Original
6865 mi 23k mi
Manual transmission Manual
LHD steering LHD
Sold
$75,000
Mar 16, 2021
Taxonomy
Make Porsche
"""
seen = calc.classic_rows(BROWSER, "Porsche")
aged = calc.classic_rows(STALE, "Porsche")
pasted = calc.clean_comps(calc.market_comps(seen, MARKET, today=NOV17))
cases += [
    ([(row["state"], row["price"], row["date"], row["miles"], row["seller"], row["kind"], row["place"]) for row in seen],
     [("for sale", 76029, "Oct 23, 2026", 89000, "Desert Private Collection", "fixed", "Indio, California, USA"),
      ("sold", 88000, "Aug 27, 2026", 44000, "", "auction", "Naples, Florida, USA"),
      ("sold", 108000, "Aug 22, 2026", 10000, "", "auction", "Palm Springs, California, USA"),
      ("last asking", 109995, "Jul 21, 2026", 29000, "", "fixed", "Glen Cove, New York, USA")]),     # the live auction has no price: no row
    (seen[1]["title"], "2015 Porsche 911 Carrera S"),
    ([(row["state"], row["price"], row["date"], row["miles"], row["seller"], row["place"]) for row in aged],
     [("last asking", 109995, "Feb 8, 2025", 453, "Ryan Friedman Motor Cars", "Glen Cove, New York, USA"),
      ("sold", 75000, "Mar 16, 2021", 23000, "", "San Diego, CA, USA")]),
    ((calc.proof(pasted[1]), pasted[1]["source"], pasted[1]["note"]), ("auction", "Classic.com", "Listed on Classic.com. Auction result. Naples, Florida, USA.")),
    (calc.auction_find(pasted[1], CAB), ("https://www.google.com/search?q=%28site%3Abringatrailer.com+OR+site%3Acarsandbids.com+OR+site%3Apcarmarket.com%29"
                                         "+2015+Porsche+911+Carrera+S+Cabriolet+%22%2488%2C000%22", "the auction sites")),
    (calc.rows_newest(seen) == calc.date_key("Oct 23, 2026") and calc.rows_newest(aged) == calc.date_key("Feb 8, 2025"), True),
]

# a browser's copy hides who sold a past auction: pasting it never takes away a seller's name already held
known = calc.clean_comps([{"status": "sold", "title": "2014 Porsche 911 Carrera S Cabriolet 7-Speed", "price": 108000, "date": "Aug 22, 2026", "miles": 10000,
                           "source": "Bring a Trailer", "url": MARKET, "note": "Listed on Classic.com. Auction result. Palm Springs, California, USA."},
                          {"status": "sold", "title": "2015 Porsche 911 Carrera S Cabriolet (Naples sale)", "price": 88000, "date": "Aug 27, 2026",
                           "source": "Classic.com market (seller not named)", "url": MARKET, "note": "Listed on Classic.com market page."}])
calc.take_rows(known, pasted)
cases += [
    ((known[0]["source"], known[0]["title"]), ("Bring a Trailer", "2014 Porsche 911 Carrera S Cabriolet 7-Speed")),
    ((known[1]["source"], known[1]["title"], known[1]["miles"]), ("Classic.com", "2015 Porsche 911 Carrera S", 44000)),
    (calc.proof(known[1]), "auction"),
]

# The page copied out of a browser (select all, copy): labels run into values, and the sold prices are not
# there at all, because the page does not let them be selected.
COPIED = """bookmark_border
2013 Porsche 911 Carrera S
Photos
33
2013 Porsche 911 Carrera S
Original & Highly Original
6865 mi89k mi
Manual transmissionManual
LHD steeringLHD

Indio, California, USA
For Sale
$76,029*
Oct 23, 2026
Updated 25 days ago
Desert Private Collection
verified
Fixed-price

Contact Seller
bookmark_border
2014 Porsche 911 Carrera S
2014 Porsche 911 Carrera S
Original & Highly Original
6865 mi10k mi
Manual transmissionManual
LHD steeringLHD

Palm Springs, California, USA
Sold
Aug 22, 2026
2 months ago
Auction

View Source
lock

bookmark_border
2015 Porsche 911 Carrera S
Original & Highly Original
6865 mi
Manual transmissionManual
LHD steeringLHD

Naples, Florida, USA
Sold
Aug 27, 2026
2 months ago
Auction
"""
copied = calc.classic_rows(COPIED, "Porsche")
cases += [
    ([(row["state"], row["price"], row["miles"], row["seller"], row["place"]) for row in copied],
     [("for sale", 76029, 89000, "Desert Private Collection", "Indio, California, USA")]),     # a sale with no price is no row
    (calc.unpriced_sales(COPIED), 2),
    (calc.unpriced_sales(BROWSER), 0),
    (calc.classic_rows("2015 Porsche 911 Carrera S\n6865 mi\nNaples, Florida, USA\nSold\n$88,000\nAug 27, 2026", "Porsche")[0]["miles"], None),   # the odometer icon alone is no mileage
]

# a car Claude read off a picture of the page is made to look like one the app read from its text
shot = [calc.market_copy(calc.clean_comp(row), MARKET) for row in (
    {"status": "sold", "title": "2013 Porsche 911 Carrera S", "price": 91500, "miles": 31000, "date": "Oct 2, 2026", "note": "Auction result. Austin, Texas."},
    {"status": "sold", "title": "2015 Porsche 911 Carrera S", "price": 82500, "date": "Jun 16, 2025", "source": "SellYourSportscar.Net", "note": "Dealer listing, fixed price. Ann Arbor, Michigan."},
    {"status": "asking", "available": "yes", "title": "2013 Porsche 911 Carrera S", "price": 76029, "source": "Desert Private Collection", "note": "Indio, California."})]
cases += [
    ((shot[0]["url"], shot[0]["source"], shot[0]["gearbox"], shot[0]["note"]), (MARKET, "Classic.com", "manual", "Listed on Classic.com. Auction result. Austin, Texas.")),
    (calc.proof(shot[0]), "auction"),
    (shot[1]["note"], "Listed on Classic.com. " + calc.DEALER_SOLD + " Ann Arbor, Michigan."),
    ((shot[2]["source"], shot[2]["note"]), ("Desert Private Collection", "Listed on Classic.com. Indio, California.")),
]

# a model's copy of a row gets the labels the app's own reading gives
copy_dealer = calc.clean_comp({"status": "sold", "title": "2015 Porsche 911 Carrera S Cabriolet", "price": 82500, "date": "Jun 16, 2025", "source": "SellYourSportscar.Net",
                               "url": MARKET, "note": "Listed on Classic.com market page; Fixed-price."})
copy_auction = calc.clean_comp({"status": "sold", "title": "2014 Porsche 911 Carrera S Cabriolet", "price": 108000, "date": "Aug 22, 2026", "source": "Bring a Trailer",
                                "url": MARKET, "note": "Listed on Classic.com; Palm Springs."})
copy_bare = calc.clean_comp({"status": "sold", "title": "2014 Porsche 911 Carrera S Cabriolet", "price": 110000, "date": "Jul 2, 2026", "source": "Classic.com market (seller not named)",
                             "url": MARKET, "note": "Listed on Classic.com market page; no VIN shown."})
for one in (copy_dealer, copy_auction, copy_bare):
    calc.label_market_copy(one)
cases += [
    (copy_dealer["note"].startswith("Listed on Classic.com. " + calc.DEALER_SOLD), True),
    (copy_auction["note"], "Listed on Classic.com. Auction result. Palm Springs."),
    (copy_bare["note"], "Listed on Classic.com market page; no VIN shown."),     # nothing says which it was: left as it is
    (calc.proof(copy_bare), "list"),
]

# ---- Bring a Trailer's own record: a make's page names its model pages, a model page carries every auction,
# and an auction's page lists the car's details
import calendar, datetime, html, json
def stamp(day): return calendar.timegm(datetime.datetime.strptime(day, "%Y-%m-%d").timetuple()) + 20 * 3600
def auction(title, amount, day, slug): return {"amount": str(amount), "timestamp": str(stamp(day)), "title": title, "url": f"https://bringatrailer.com/listing/{slug}/"}
names = [("Porsche 997 911 Carrera S", "997-911"), ("Porsche 991 911 Carrera S", "991-911"), ("Porsche 991 911 Carrera 4S", "991-911-carrera-4s"),
         ("Porsche 991 911 Carrera", "991-911-carrera"), ("Porsche 991 911 Carrera S Endurance Racing Edition", "991-911-carrera-s-endurance-racing-edition"),
         ("Porsche 991 911 Parts and Automobilia", "991-911-parts-and-automobilia"), ("Porsche 718 Cayman GTS 4.0", "718-cayman-gts-4-0"), ("Porsche 718 Cayman", "718-cayman")]
make_page = '<div data-items="' + html.escape(json.dumps([{"title": title, "url": f"https://bringatrailer.com/porsche/{slug}/"} for title, slug in names],
                                                           separators=(",", ":")).replace("/", "\\/")) + '"></div>'
models = calc.bat_models(make_page)
record = {"items": [{"url": "https://bringatrailer.com/listing/c/", "excerpt": "This 2013 cabriolet has a <b>seven-speed PDK</b> automatic transaxle."}],
          "stats": {"sold": [auction("14k-Mile 2012 Porsche 911 Carrera S Coupe", 86000, "2026-11-16", "a"),
                             auction("10k-Mile 2014 Porsche 911 Carrera S Cabriolet 7-Speed", 108000, "2026-08-22", "b"),
                             auction("34k-Mile 2013 Porsche 911 Carrera S Cabriolet", 85900, "2026-10-18", "c"),
                             auction("1,200-Kilometer 2013 Porsche 911 Carrera S Cabriolet", 90000, "2026-05-01", "d"),
                             auction("2012 Porsche 911 Carrera S Cabriolet 7-Speed", 51000, "2021-03-02", "e")],
                    "unsold": [auction("2015 Porsche 911 Carrera S Cabriolet 7-Speed", 54000, "2026-01-22", "f")]}}
model_page = "<script>\nvar auctionsCompletedInitialData = " + json.dumps(record) + ";\nvar x = 1;\n</script>"
found = calc.bat_results(model_page)
sales = calc.clean_comps(calc.bat_comps(found, today=NOV17))
by = {comp["url"][-2]: comp for comp in sales}
LISTING = ('<div class="essentials"><strong>Seller</strong>: <a>x</a><strong>Location</strong>: <a href="#">Palm Springs, California 92262</a><strong>Listing Details</strong><ul>'
           '<li>Chassis: <a href="#">WP0CB2A96ES154062</a></li><li>10k Miles</li><li>3.8-Liter Flat-Six</li><li>Seven-Speed Manual Transaxle </li><li>Sport Chrono Package</li>'
           '<li>Heated &amp; Ventilated Seats</li><li>Clean Carfax Report</li></ul><strong>Private Party or Dealer</strong>: Private Party<strong>Lot</strong> #259232</div>')
facts = calc.bat_listing(LISTING)
opened = dict(by["b"]); calc.bat_fill(opened, facts, {"status": "sold", "price": 108000, "date": "8/22/26"})
# an auction whose record shows the last bid while its page says what the car sold for afterwards
later = calc.clean_comp({"status": "sold", "title": "2015 Porsche 911 Carrera S Cabriolet 7-Speed", "price": 86000, "date": "Aug 26, 2026", "source": "Bring a Trailer",
                         "url": "https://bringatrailer.com/listing/g/", "note": calc.BAT_NOTE, "link_ok": True})
calc.bat_fill(later, {"place": "Naples, Florida", "vin": "WP0CB2A98FS155165"}, {"status": "sold", "price": 88000, "date": "8/26/26"})
unsaid = dict(by["f"]); calc.bat_fill(unsaid, {"place": "Reno, Nevada", "vin": "WP0CB2A98FS155165"}, {})          # a page that does not say how it ended
newest = {"items": [{"title": "44k-Mile 2015 Porsche 911 Carrera S Cabriolet 7-Speed", "url": "https://bringatrailer.com/listing/g/", "current_bid": 86000,
                     "sold_text": "Sold for USD $88,000 <span> on 8/26/2026 </span>", "timestamp_end": stamp("2026-08-26")},
                    {"title": "2013 Porsche 911 Carrera S Cabriolet", "url": "https://bringatrailer.com/listing/h/", "current_bid": 62000,
                     "sold_text": "Bid to USD $62,000 <span> on 9/25/2026 </span>", "timestamp_end": stamp("2026-09-25")}], "stats": {"sold": [], "unsold": []}}
short_page = "<script>\nvar auctionsCompletedInitialData = " + json.dumps(newest) + ";\nvar x = 1;\n</script>"
held = calc.clean_comps([{"status": "sold", "title": "2014 Porsche 911 Carrera S Cabriolet (Palm Springs, CA sale)", "price": 108000, "date": "Aug 22, 2026", "use": True, "aside": "mine",
                          "source": "Classic.com market (seller not named)", "url": MARKET, "note": "Listed on Classic.com market page; no VIN shown."}])
took = calc.upgrade_leads(held, [opened])
cases += [
    (calc.make_slug("Mercedes-Benz"), "mercedes-benz"),
    (len(models), 8),
    ([(title, own) for title, url, own in calc.bat_pick(CAB, models)], [("Porsche 991 911 Carrera S", True), ("Porsche 997 911 Carrera S", True)]),      # one trim, two generations
    (calc.bat_pick(CAB, models)[0][1], "https://bringatrailer.com/porsche/991-911/"),
    ([title for title, url, own in calc.bat_pick({"make": "Porsche", "model": "718 Cayman", "trim": "GTS 4.0"}, models)], ["Porsche 718 Cayman GTS 4.0"]),
    ([(title, own) for title, url, own in calc.bat_pick({"make": "Porsche", "model": "718 Cayman", "trim": "GT4"}, models)], [("Porsche 718 Cayman", False)]),   # no page for the trim
    (calc.bat_pick({"make": "Porsche", "model": "Taycan", "trim": "4S"}, models), []),
    ((len(found), calc.bat_year_fit(CAB, found), found[0]["price"]), (6, 1, 86000)),
    (len(sales), 5),                                                       # the one from 2021 is left out
    ((by["b"]["status"], by["b"]["price"], by["b"]["date"], by["b"]["miles"], by["b"]["gearbox"], by["b"]["title"], by["b"]["source"]),
     ("sold", 108000, "Aug 22, 2026", 10000, "manual", "2014 Porsche 911 Carrera S Cabriolet 7-Speed", "Bring a Trailer")),
    ((calc.proof(by["b"]), calc.own_page(by["b"])), ("own", True)),
    ((by["c"]["gearbox"], "Taken for an automatic" in by["c"]["note"]), ("automatic", False)),      # its own lines say PDK
    ((by["d"]["gearbox"], by["d"]["miles"], "Taken for an automatic" in by["d"]["note"]), ("automatic", 746, True)),     # no gears in its title
    ((by["f"]["status"], "Not sold" in by["f"]["note"]), ("high_bid", True)),
    (calc.bat_results("<html>no data here</html>"), []),
    (facts, {"place": "Palm Springs, California", "vin": "WP0CB2A96ES154062", "miles": 10000, "gearbox": "manual", "history": "Clean Carfax Report",
             "options": "3.8-Liter Flat-Six, Seven-Speed Manual Transaxle, Sport Chrono Package, Heated & Ventilated Seats"}),
    ((opened["vin"], opened["gear_seen"], opened["note"]), ("WP0CB2A96ES154062", "page", "Checked on the auction's own page: sold for $108,000 on Aug 22, 2026. Palm Springs, California.")),
    ([comp["url"][-2] for comp in calc.bat_closest(CAB, sales)], ["b", "f"]),          # the cabriolets with this gearbox, sales first
    ((later["price"], later["note"]), (88000, "Checked on the auction's own page: sold for $88,000 on Aug 26, 2026. Naples, Florida.")),
    ((calc.CHECKED in unsaid["note"], unsaid["note"]), (False, calc.BAT_NOTE + " Reno, Nevada. Not sold: the price is the highest bid.")),
    (calc.bat_closest(CAB, [unsaid]), []),                                             # it has its VIN: not opened again
    ((calc.bat_whole(model_page), calc.bat_whole(short_page)), (True, False)),
    ([(row["price"], row["sold"]) for row in calc.bat_results(short_page)], [(62000, False), (88000, True)]),      # what it sold for, not the last bid
    (calc.bat_closest(CAB, [opened]), []),                                             # one already opened is not opened again
    # a copy of the sale off Classic.com's page takes the auction's own page, and stays the buyer's choice
    ((took, held[0]["url"], held[0]["source"], held[0]["vin"], held[0]["aside"], held[0]["title"]),
     (1, "https://bringatrailer.com/listing/b/", "Bring a Trailer", "WP0CB2A96ES154062", "mine", "2014 Porsche 911 Carrera S Cabriolet 7-Speed")),
    ("Sport Chrono Package" in held[0]["options"], True),
]

# ---- one page for every version of a model: the first M2, the Competition, the CS, the next generation, wheels.
# Only the auctions of cars like the buyer's are kept.
import bat
M2 = [("15k-Mile 2018 BMW M2", 39750, "2026-11-10"), ("2020 BMW M2 Competition", 42222, "2026-11-05"), ("2018 BMW M2 6-Speed", 42250, "2026-10-30"),
      ("11k-Mile 2020 BMW M2 Competition 6-Speed", 57000, "2026-10-20"), ("2018 BMW M2 Track Car", 35000, "2026-10-18"), ("2025 BMW M2 6-Speed", 62000, "2026-10-16"),
      ("No Reserve: 19x9.5 and 20x10.5 BMW Style 930M Wheels", 1125, "2026-10-10"), ("19k-Mile 2021 BMW M2 Competition 6-Speed", 51000, "2026-10-01"),
      ("Individual Velvet Blue Metallic 2026 BMW M2 CS", 110000, "2026-09-20"), ("3,500-Mile 2020 BMW M2 CS", 76500, "2026-09-15"),
      ("2020 BMW M2 CS 6-Speed", 78000, "2026-06-23"), ("8k-Mile 2020 BMW M2 CS 6-Speed", 74000, "2026-03-02"), ("2024 BMW M2 6-Speed", 58500, "2026-06-27")]
m2_rows = [{"title": title, "price": price, "sold": True, "url": f"https://bringatrailer.com/listing/m2-{at}/", "words": "",
            "day": datetime.datetime.strptime(day, "%Y-%m-%d").toordinal()} for at, (title, price, day) in enumerate(M2)]
CS = {"year": 2020, "make": "BMW", "model": "M2", "trim": "CS", "body": "Coupe", "transmission": "6-speed manual"}
titles = lambda car: [comp["title"] for comp in calc.bat_comps(m2_rows, today=NOV17, car=car)]
cases += [
    (titles(CS), ["2020 BMW M2 CS", "2020 BMW M2 CS 6-Speed", "2020 BMW M2 CS 6-Speed"]),      # not the first M2, the Competition, the 2026 CS or the wheels
    (titles({**CS, "trim": "Competition"}), ["2020 BMW M2 Competition", "2020 BMW M2 Competition 6-Speed", "2021 BMW M2 Competition 6-Speed"]),
    (titles({"year": 2018, "make": "BMW", "model": "M2", "trim": ""}), ["2018 BMW M2", "2018 BMW M2 6-Speed", "2018 BMW M2 Track Car"]),      # no trim: none of the page's trims
    (calc.bat_trim_words(m2_rows, CS), {"competition", "cs"}),
    (len(calc.bat_comps(m2_rows, today=NOV17)), 12),                      # with no car to go by, every car on the page (the wheels are no car)
    ([calc.bat_fits(CS, title) for title in ("2020 BMW M2 CS 6-Speed", "8k-Mile 2020 BMW M2 CS", "2018 BMW M2 6-Speed", "2020 BMW M2 Competition", "2026 BMW M2 CS", "BMW M2 CS Wheels")],
     [True, True, False, False, False, False]),
    ([calc.bat_fits(CAB, title) for title in ("10k-Mile 2014 Porsche 911 Carrera S Cabriolet 7-Speed", "2014 Porsche 911 Carrera 4S Cabriolet", "2014 Porsche 911 Carrera Cabriolet", "2019 Porsche 911 Carrera S Coupe")],
     [True, False, False, False]),
]

# asking the site: the model page that arrives with its newest auctions only is asked for again, and what was
# read of the whole record earlier is not thrown away
def record_page(rows, whole=True):
    stats = {"sold": [{"amount": str(row["price"]), "timestamp": str(stamp(datetime.date.fromordinal(row["day"]).isoformat())), "title": row["title"], "url": row["url"]} for row in rows], "unsold": []}
    items = [{"title": row["title"], "url": row["url"], "current_bid": row["price"], "sold_text": f"Sold for USD ${row['price']:,} on 1/1/2026",
              "timestamp_end": stamp(datetime.date.fromordinal(row["day"]).isoformat())} for row in rows[:4]]
    return "<script>\nvar auctionsCompletedInitialData = " + json.dumps({"items": items, "stats": stats if whole else False}) + ";\nvar x = 1;\n</script>"
bmw_make = '<div data-items="' + html.escape(json.dumps([{"title": "BMW M2", "url": "https://bringatrailer.com/bmw/m2/"}], separators=(",", ":")).replace("/", "\\/")) + '"></div>'
served, asked = {"https://bringatrailer.com/bmw/": bmw_make, "https://bringatrailer.com/bmw/m2/": record_page(m2_rows, whole=False)}, []
def fake_page(url):
    asked.append(url)
    return ("ok", served[url]) if url in served else ("missing", "")
bat.page, bat.GAP, bat.BASE = fake_page, 0, "https://bringatrailer.com"
said = []
short = bat.sales(CS, said.append)
tries = asked.count("https://bringatrailer.com/bmw/m2/")
served["https://bringatrailer.com/bmw/m2/"] = record_page(m2_rows)
whole_read = bat.sales(CS, None)
served["https://bringatrailer.com/bmw/m2/"] = record_page(m2_rows, whole=False)
after = bat.sales(CS, None)
cases += [
    (tries, 3),                                                           # asked for again, twice
    (len(short["comps"]), 0),                                             # its newest four auctions hold no CS
    ("came with its newest 4 auctions only" in short["note"] and "came with its newest 4 auctions only this time" in said[-1], True),
    ([comp["price"] for comp in whole_read["comps"]], [76500, 78000, 74000]),
    ("13 auctions in all, 3 of them cars like this one (3 sold)" in whole_read["note"], True),
    ([comp["price"] for comp in after["comps"]], [76500, 78000, 74000]),  # the short page again: the record read a moment ago still serves
    (bat.sales({"year": 2020, "make": "Lotus", "model": "Evora", "trim": "GT"}, None)["comps"], []),      # no page for the make
]

# Claude's second look at the auctions the title rules kept: only a plain no with a reason takes one out
import llm
answer = {"rows": [{"n": 1, "same": "no", "why": "an M2 Competition."}, {"n": 2, "same": "yes"}, {"n": 3, "same": "unsure", "why": "no trim named"},
                   {"n": 4, "same": "no"}, {"n": 9, "same": "no", "why": "not on the list"}, {"n": "5", "same": "No", "why": " the next generation  (G87) "}, "junk"]}
kept_row = calc.clean_comps([{"status": "sold", "title": "2020 BMW M2 CS 6-Speed", "price": 78000, "source": "Bring a Trailer", "date": "Jun 23, 2026",
                              "url": "https://bringatrailer.com/listing/2020-bmw-m2-cs-69/", "note": calc.BAT_NOTE}])[0]
undated = calc.clean_comps([{"status": "sold", "title": "2020 BMW M2 CS 6-Speed", "price": 92000, "source": "Bring a Trailer",
                             "url": "https://www.classic.com/a/bring-a-trailer-auctions-JknXEWB/lots/2020-bmw-m2-cs-6-speed-4AjAo3n/", "note": "Auction result."}])[0]
asking = calc.clean_comps([{"status": "asking", "title": "2020 BMW M2 CS", "price": 71800, "source": "Toy Barn", "url": "https://example.com/cs"}])[0]
block = llm._comps_block([kept_row, undated, asking])
cases += [
    (calc.kind_verdicts(answer, 5), {0: "an M2 Competition", 4: "the next generation (G87)"}),
    (calc.kind_verdicts(None, 5), {}), (calc.kind_verdicts({"rows": "no"}, 5), {}), (calc.kind_verdicts({}, 5), {}),
    (calc.bat_row(kept_row), True),                                       # off the model's page: the second look may ask about it
    (calc.bat_row(undated), False),                                       # a copy on another site is not
    (calc.bat_row({**kept_row, "aside": "mine"}), False),                 # one the buyer chose to keep is never asked about
    (calc.bat_row({**kept_row, "status": "asking"}), False),
    ("Jun 23, 2026" in block.splitlines()[0] and "date not known" not in block.splitlines()[0], True),
    ("date not known" in block.splitlines()[1], True),                    # a sale with no date says so, and the offer treats it as old
    ("date not known" in block.splitlines()[2], False),                   # a car for sale has no sale date to miss
    (llm.same_kind(None, "m", CS, []), ({}, {})),                         # nothing to look at: nothing asked
]

bad = [(i, got, want) for i, (got, want) in enumerate(cases) if got != want]
for row in bad:
    print("FAILED", row)
print(f"market page cases: {len(cases)} failures: {len(bad)}")
