"""The still-for-sale rule against pages written the way dealer, marketplace and auction sites write them."""
import sys
sys.path.insert(0, "/home/claude/deal-sheet")
import previews

V, OTHER = "WBS1J3C03L7H24156", "WBS1J3C02L7H33303"
PAD = "<p>" + "Financing available. Call us today for a test drive. " * 12 + "</p>"
U = "https://dealer.example/used/2020-bmw-m2-cs-" + V.lower()

def page(title, body, head=""):
    return f"<html><head><title>{title}</title>{head}</head><body>{body}{PAD}</body></html>"

CAR = '<h1>Used 2020 BMW M2 CS</h1><div class="price">$89,000</div>'
cases = [
  # (what it is, html, asked, final, vin, price, year, want state)
  ("VIN on the page", page("Used 2020 BMW M2 CS | Dealer", CAR + f"<div>VIN: {V}</div>"), U, U, V, 89000, "2020", "live"),
  ("VIN only in the page's data", page("Used 2020 BMW M2 CS", CAR + f'<script type="application/ld+json">{{"vehicleIdentificationNumber":"{V}"}}</script>'), U, U, V, 89000, "2020", "live"),
  ("VIN only where the page repeats its own address", page("Used cars | Dealer", "<h1>Used inventory</h1><div>2019 BMW M4 $61,000</div>", f'<link rel="canonical" href="{U}">'), U, U, V, 89000, "2020", "unknown"),
  ("same address now lists other cars", page("Used cars | Dealer", "<h1>Used inventory</h1>" + "".join(f"<div>Car {i} $5{i},900</div>" for i in range(6))), U, U, V, 89000, "2020", "unknown"),
  ("sent to the inventory list", page("Used cars | Dealer", "<h1>Used inventory</h1>"), "https://dealer.example/used/stock-482913", "https://dealer.example/used/", "", 89000, "2020", "gone"),
  ("sent to the home page", page("Dealer", "<h1>Welcome</h1>"), "https://dealer.example/inventory/2020-bmw-m2-cs/", "https://dealer.example/", "", 89000, "2020", "gone"),
  ("https and trailing slash only", page("Used 2020 BMW M2 CS", CAR + f"<div>VIN: {V}</div>"), "http://dealer.example/used/abc/", "https://www.dealer.example/used/abc", V, 89000, "2020", "live"),
  ("says no longer available", page("Used 2020 BMW M2 CS", CAR + f"<div>VIN: {V}</div><p>This vehicle is no longer available.</p>"), U, U, V, 89000, "2020", "gone"),
  ("sold badge on its own", page("Used 2020 BMW M2 CS", CAR + f'<span class="badge">SOLD</span><div>VIN: {V}</div>'), U, U, V, 89000, "2020", "gone"),
  ("sale pending badge", page("Used 2020 BMW M2 CS", CAR + f'<div class="ribbon">Sale Pending</div><div>VIN: {V}</div>'), U, U, V, 89000, "2020", "gone"),
  ("title starts with Sold", page("[SOLD] 2020 BMW M2 CS 6MT - Forum", CAR), U, U, "", 89000, "2020", "gone"),
  ("title says page not found", page("Page Not Found | Dealer", "<h1>Hmm</h1>"), U, U, V, 89000, "2020", "gone"),
  ("vehicle data says out of stock", page("Used 2020 BMW M2 CS", CAR + f'<div>VIN: {V}</div><script type="application/ld+json">{{"availability":"https://schema.org/OutOfStock"}}</script>'), U, U, V, 89000, "2020", "gone"),
  ("another car's VIN", page("Used 2021 BMW M4", f"<h1>Used 2021 BMW M4</h1><div>VIN: {OTHER}</div>"), U, U, V, 89000, "2020", "gone"),
  ("auction that ended", page("2020 BMW M2 CS | Auctions", CAR + "<div>Sold for $84,500 on 11/02/26</div>"), U, U, "", 84500, "2020", "gone"),
  ("posting deleted", page("craigslist", "<h2>This posting has been deleted by its author.</h2>"), U, U, "", 89000, "2020", "gone"),
  ("built by scripts", '<html><head><title>Dealer</title></head><body><div id="app"></div><script>window.x={"vin":"' + V + '"}</script></body></html>', U, U, V, 89000, "2020", "unknown"),
  ("live, as-is disclaimer", page("Used 2020 BMW M2 CS", CAR + f"<div>VIN: {V}</div><p>Vehicle sold as-is. Can't find the car you're looking for? Call us.</p>"), U, U, V, 89000, "2020", "live"),
  ("live, similar cars marked sold and for sale", page("2020 BMW M2 CS", CAR + f"<div>VIN: {V}</div><div>Similar</div><span>Sold</span><span>For Sale</span><span>Sold</span>"), U, U, V, 89000, "2020", "live"),
  ("live, Sold only as a menu link", page("2020 BMW M2 CS", '<nav><a href="/sold">Sold</a></nav>' + CAR + f"<div>VIN: {V}</div>"), U, U, V, 89000, "2020", "live"),
  ("no VIN known, page states one", page("Used 2020 BMW M2 CS", CAR + f"<div>VIN: {V}</div>"), U, U, "", 91000, "2020", "live"),
  ("no VIN known, price and year match", page("Used 2020 BMW M2 CS", CAR), U, U, "", 89000, "2020", "live"),
  ("no VIN known, price changed", page("Used 2020 BMW M2 CS", CAR), U, U, "", 92500, "2020", "unknown"),
  ("no VIN known, price matches on a list page", page("Used cars | Dealer", "<h1>Used inventory</h1><div>BMW M2 $89,000</div>"), U, U, "", 89000, "2020", "unknown"),
  ("no VIN known, the price figure is a mileage", page("Used 2020 BMW M2 CS", "<h1>Used 2020 BMW M2 CS</h1><div>89,000 miles</div><div>Call for price</div>"), U, U, "", 89000, "2020", "unknown"),
  ("VIN known, page shows none, price and year match", page("2020 BMW M2 CS - Classifieds", CAR), U, U, V, 89000, "2020", "live"),
  ("VIN known, page shows none, another year", page("2018 BMW M2 - Classifieds", "<h1>2018 BMW M2</h1><div>$89,000</div>"), U, U, V, 89000, "2020", "unknown"),
  ("a list of cars, each with a VIN", page("Used BMW | Dealer", "<h1>Used BMW</h1>" + "".join(f"<div>VIN: {v}</div>" for v in (OTHER, "WP0AD2A89MS281685", "1HGCM82633A004352"))), U, U, "", 89000, "2020", "unknown"),
  ("in stock in the page's data, year in heading", page("Used 2020 BMW M2 CS", "<h1>Used 2020 BMW M2 CS</h1><script type=\"application/ld+json\">{\"availability\":\"https://schema.org/InStock\"}</script>"), U, U, "", 0, "2020", "live"),
]
bad = 0
for name, html_, asked, final, vin, price, year, want in cases:
    state, stated, gear, why, code = previews.judge_page(html_, asked, final, vin, price, year)
    ok = state == want; bad += not ok
    print(f"{'ok ' if ok else 'BAD'} {name:52} -> {state}")
gear_cases = [("labelled automatic", page("x", CAR + "<dl><dt>Transmission</dt><dd>7-Speed M DCT</dd></dl>"), "automatic"), ("labelled manual", page("x", CAR + "<div>Transmission: 6-Speed Manual</div>"), "manual"),
              ("in the page's data", page("x", CAR + '<script type="application/ld+json">{"vehicleTransmission":"Automatic"}</script>'), "automatic"),
              ("only a filter naming both", page("x", CAR + "<div>Transmission</div><div>Automatic</div><div>Manual</div>"), ""),
              ("this car manual, similar cars automatic", page("x", CAR + "<div>Transmission: Manual</div><h3>Similar</h3><div>Transmission: Automatic</div>"), "manual"),
              ("not stated", page("x", CAR + "<p>Automatic climate control. Owner's manual included.</p>"), "")]
for name, html_, want in gear_cases:
    got = previews.judge_page(html_, U, U, "", 89000, "2020")[2]; ok = got == want; bad += not ok
    print(f"{'ok ' if ok else 'BAD'} gearbox: {name:43} -> {got or '-'}")
print("cases:", len(cases) + len(gear_cases), "failures:", bad)
