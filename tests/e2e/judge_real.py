"""The still-for-sale rule against the way real sites word their pages for one car (a 2020 BMW M2 CS), as plain
text the way a page reader returns it. The wording follows pages read on 2026-11-15; the text here is rebuilt."""
import sys
sys.path.insert(0, "/home/claude/deal-sheet")
import previews

PAD = "\n".join(["Contact us about this car.", "Financing is available.", "Schedule a visit.", "We ship worldwide."] * 12)
def text(*rows): return "\n".join(rows) + "\n" + PAD

V = "WBS1J3C09L7H37333"
comps = []
for i, (status, amount) in enumerate([("For Sale", "$85,900"), ("Last Asking", "$74,900"), ("Last Asking", "$97,947"), ("Sold", "$86,500"), ("Last Asking", "$103,900"),
                                      ("For Sale", "$88,998"), ("Last Asking", "$79,995"), ("Not Sold", "$101,000"), ("Last Asking", "$82,990"), ("For Sale", "$79,198")]):
    comps += ["2020 BMW M2 CS", "Original & Highly Original", f"{i + 3}k mi", "Manual transmission Automatic", "LHD steering LHD", status, amount]
    if status == "Last Asking":
        comps += ["info", "This listing was either sold, or removed, by the seller. The last asking price is the last price detected by Classic.com."]

cases = [
  # (what, text, title, url, vin, price, year, want state, want gearbox or None)
  ("dealer, marked Available, chassis number shown", text("Go Back", "The Garage", "2020 BMW M2 CS", "Available", "2020 BMW M2 CS", "Optioned With A 6-Speed & Carbon Ceramic Brakes", "Overview", f"Chassis #{V}", "Manual", "1,943 mi", "Hockenheim Silver"),
   "2020 BMW M2 CS — Animoya Garage", "https://www.animoyagarage.com/2020-bmw-m2-cs", V, 120000, "2020", "live", None),
  ("the same dealer page once marked Sold", text("Go Back", "The Garage", "2020 BMW M2 CS", "Sold", "2020 BMW M2 CS", "Overview", f"Chassis #{V}", "Manual", "1,943 mi"),
   "2020 BMW M2 CS — Animoya Garage", "https://www.animoyagarage.com/2020-bmw-m2-cs", V, 120000, "2020", "gone", None),
  ("dealer, VIN only in the address, price and in-stock data", text("See photos and info on this 2020 BMW M2 CS", "$82,448", "(330) 555-0100", "# 2020 BMW M2", "Description", "6-Speed Manual Transmission, only 14,000 miles", "Retail Price $82,000",
        '{"name":"2020 BMW M2 CS","modelDate":2020,"vehicleTransmission":"6-Speed Manual","offers":{"price":82448,"priceCurrency":"USD","availability":"http://schema.org/InStock"}}'),
   "2020 BMW M2 CS at Sarchione Auto Gallery", "https://sarchioneautogallery.com/inventory/Used-2020-BMW-M2-CS-WBS1J3C03L7H38526", "WBS1J3C03L7H38526", 82000, "2020", "live", "manual"),
  ("the same page after a price change", text("See photos and info on this 2020 BMW M2 CS", "$79,900", "# 2020 BMW M2", "6-Speed Manual Transmission",
        '{"name":"2020 BMW M2 CS","offers":{"price":79900,"availability":"http://schema.org/InStock"}}'),
   "2020 BMW M2 CS at Sarchione Auto Gallery", "https://sarchioneautogallery.com/inventory/Used-2020-BMW-M2-CS-WBS1J3C03L7H38526", "WBS1J3C03L7H38526", 82000, "2020", "live", "manual"),
  ("Classic.com, off market", text("2020 BMW M2 CS 6-Speed", "7,000 mi Manual LHD Original & Highly Original See all specs", "2020 BMW M2 CS 6-Speed", "Off Market", "Last Seen on Apr 10, 2024", "VIN WBS1J3C0XL7H08097", "Specs", "**Transmission**: Manual"),
   "2020 BMW M2 CS 6-Speed VIN: WBS1J3C0XL7H08097 - CLASSIC.COM", "https://www.classic.com/veh/2020-bmw-m2-cs-6-speed-wbs1j3c0xl7h08097-p6j7Xjp/", "WBS1J3C0XL7H08097", 89000, "2020", "gone", None),
  ("Classic.com, for sale, above a column of other cars", text("2020 BMW M2 CS", "VIN WBS1J3C05L7H43582", "Apr 16, 2026", "What's special about this listing", "6-Speed Manual, only 9,650 miles", "Comps", *comps, "GTO Car Specialists", "For Sale", "Specs", "Transmission", "Manual"),
   "2020 BMW M2 CS VIN: WBS1J3C05L7H43582 - CLASSIC.COM", "https://www.classic.com/veh/2020-bmw-m2-cs-wbs1j3c05l7h43582-WR83Br4", "WBS1J3C05L7H43582", 84900, "2020", "listed", ""),
  ("consignment site, off the market", text("2020 BMW M2 CS Coupe", "6-Speed Manual | Carbon Fiber Roof", "LOT #", "240313432", "This vehicle is currently off the market.", "Sign up to be notified when this vehicle or one similar is available.", "OFF MARKET VEHICLE", "VIN:", "WBS1J3C07L7H21728"),
   "2020 BMW M2 CS Coupe", "https://www.exoticcartrader.com/listing/2020-bmw-m2-cs-coupe-2", "WBS1J3C07L7H21728", 75000, "2020", "gone", None),
  ("classifieds, title says sold", text("This vehicle has been sold", "This vehicle is no longer available for sale on this site.", "For Sale: 2020 BMW M2 in Miami, Florida", "Price: $91,429 (OBO)", "VIN:WBS1J3C08L7H54494"),
   "This vehicle has been sold", "https://classiccars.com/listings/view/1709869/2020-bmw-m2-for-sale-in-miami-florida-33129", "WBS1J3C08L7H54494", 91429, "2020", "gone", None),
  ("dealer's sold section", text("Sold", "SOLD 01/25", "2020 BMW", "M2 CS", "VINWBS1J3C07L7H24175", "Transmission6-speed manual", "StatusSold", "StockFJ2955"),
   "2020 BMW M2 CS", "https://www.fantasyjunction.com/sold/2020-bmw-m2-cs/overview", "WBS1J3C07L7H24175", 99000, "2020", "gone", None),
  ("auction that sold", text("5k-Mile 2020 BMW M2 CS 6-Speed", "Sold", "Final bid:$83,750", "Auction type: ReserveSold", "26 bids, 16 comments", "VIN: WBS1J3C04L7H22819"),
   "5k-Mile 2020 BMW M2 CS 6-Speed", "https://www.pcarmarket.com/auction/2020-bmw-m2-cs-6-speed", "WBS1J3C04L7H22819", 83750, "2020", "gone", None),
  ("auction that ended unsold", text("3k-Mile 2020 BMW M2 CS 6-Speed", "Ended", "Final bid:$85,500", "Auction type: ReserveEnded", "VIN: WBS1J3C02L7H21734"),
   "3k-Mile 2020 BMW M2 CS 6-Speed", "https://www.pcarmarket.com/auction/2020-bmw-m2-cs", "WBS1J3C02L7H21734", 85500, "2020", "gone", None),
  ("auction, sold for a sum in USD", text("2020 BMW M2 CS 6-Speed", "Sold for USD $86,500 on 1/19/23", "Chassis: WBS1J3C09L7H37333"),
   "2020 BMW M2 CS 6-Speed", "https://bringatrailer.com/listing/2020-bmw-m2-cs-9/", V, 86500, "2020", "gone", None),
  ("auction still running", text("2020 BMW M2 CS 6-Speed", "Current Bid: USD $70,000", "Ends in 2 days", "Chassis: WBS1J3C09L7H37333", "6-Speed Manual Transmission"),
   "2020 BMW M2 CS 6-Speed", "https://bringatrailer.com/listing/2020-bmw-m2-cs-12/", V, 70000, "2020", "live", "manual"),
  ("classifieds, title ends SOLD", text("2020 BMW M2 CS - VAT Qualifying SOLD", "Right Hand Drive", "800 Miles", "Manual, 6 speed"),
   "2020 BMW M2 CS - VAT Qualifying SOLD", "https://www.carandclassic.com/car/C2066612", "", 99000, "2020", "gone", None),
  ("site that copies listings, price and year match", text("Used 2020 BMW M2", "CS", "Dublin, OH 43017 (352 mi away)", "Great Price", "$71,800See price and payment details", "21,106 mi", "Specs", "6-Speed Manual Transmission", "2 wheel drive - rear", "| Listing Price | $71,800 |"),
   "Used 2020 BMW M2", "https://www.kbb.com/cars-for-sale/vehicle/754183782", "", 71800, "2020", "listed", "manual"),
  ("a results list with the car's year in its title", text("# Used 2020 BMW M2 CS for Sale Near Me", *[f"2020 BMW M2 CS Base Coupe ${p:,}" for p in (82000, 97995, 75900, 76888, 97695, 85000, 95995, 75995, 69976, 79995, 77900)],
        *['{"offers":{"availability":"https://schema.org/InStock","price":82000}}'] * 5),
   "Used 2020 BMW M2 CS for Sale Near Me", "https://www.edmunds.com/bmw/m2-cs/2020/", "", 82000, "2020", "unknown", None),
  ("dealer, chassis number, price on request", text("2020 BMW M2 CS", "Make: BMW", "Model: M2CS", "Year: 2020", "Miles: 24,000", "Chassis#: WBS1J3C03L7H54483", "Gearbox: Paddle Shift 7-Speed Twin-Clutch Auto", "Price:", "Inquire"),
   "2020 BMW M2 CS", "https://www.grandprixclassics.com/vehicle/2020-bmw-m2-cs", "WBS1J3C03L7H54483", 0, "2020", "live", "automatic"),
  ("a wall instead of the page", "Pardon Our Interruption\nAs you were browsing something about your browser made us think you were a bot.\nPlease verify you are a human to continue.\n" + PAD,
   "Pardon Our Interruption", "https://www.cars.com/vehicledetail/abc/", V, 90000, "2020", "unknown", None),
  ("lender's copy, no longer available", text("Sorry, this vehicle is no longer available", "Browse similar cars"),
   "Capital One Auto Navigator", "https://www.capitalone.com/cars/vehicle-details/2020-bmw-m2/x", V, 90000, "2020", "gone", None),
]
bad = 0
for name, body, title, url, vin, price, year, want, gear in cases:
    state, stated, gearbox, why, code = previews.judge_page(body, url, url, vin, price, year, title=title)
    ok = state == want and (gear is None or gearbox == gear); bad += not ok
    print(f"{'ok ' if ok else 'BAD'} {name:52} -> {state:8} {('gearbox ' + gearbox + ' ') if gearbox else ''}| {why}{' [' + code + ']' if code else ''}")
print("real-site cases:", len(cases), "failures:", bad)
