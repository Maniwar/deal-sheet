"""The words a sales search has to name for a car of an uncommon kind (an open car, a manual), and the requests that carry them."""
import sys
sys.path.insert(0, ".")
import calc, llm

cab = {"year": 2014, "make": "Porsche", "model": "911", "trim": "Carrera S", "body": "Convertible", "transmission": "7-Speed Manual"}
cases = [
    (calc.kind_words(cab), "Cabriolet 7-speed manual"),                                   # a dealer's 'Convertible' is Porsche's Cabriolet
    (calc.kind_words({**cab, "body": "Coupe", "transmission": "PDK"}), ""),                 # the common kind: nothing to add
    (calc.kind_words({**cab, "body": "Coupe", "transmission": "PDK"}, every=True), "Coupe PDK"),
    (calc.kind_words({**cab, "body": "Targa", "transmission": "7-speed PDK"}), "Targa"),
    (calc.kind_words({"make": "BMW", "model": "M4", "body": "Convertible", "transmission": "8-speed automatic"}), "Convertible"),
    (calc.kind_words({"make": "BMW", "model": "M4", "body": "Convertible", "transmission": "8-speed automatic"}, every=True), "Convertible automatic"),
    (calc.kind_words({"make": "BMW", "model": "M2", "trim": "CS", "body": "Coupe", "transmission": "6-speed manual"}), "6-speed manual"),
    (calc.kind_words({"make": "Porsche", "model": "718", "trim": "Spyder", "body": "Convertible", "transmission": "Manual"}), "Spyder manual"),
    (calc.kind_words({"make": "Toyota", "model": "Camry", "body": "Sedan", "transmission": ""}, every=True), ""),
    (calc.kind_words({"make": "Mazda", "model": "MX-5", "body": "Roadster", "transmission": "6MT"}), "Roadster manual"),
]
site = llm._site_prompt(cab, "November 16, 2026", "Bring a Trailer", 3)
wide = llm._research_prompt(cab, "November 16, 2026", 3)
second = llm._research_prompt(cab, "November 16, 2026", 3, focus=True)
plain = llm._site_prompt({**cab, "body": "Coupe", "transmission": "PDK"}, "November 16, 2026", "Bring a Trailer", 2)
cases += [
    ('"2014 Porsche 911 Carrera S Cabriolet 7-speed manual"' in site, True),
    ('"Porsche 911 Carrera S Cabriolet 7-speed manual sold"' in site, True),
    ("kind is: Cabriolet 7-speed manual" in site and "neighbouring model year" in site, True),
    ("bringatrailer.com 2014 Porsche 911 Carrera S Cabriolet 7-speed manual sold" in wide, True),
    ("only for this exact kind" in second and "only for this exact kind" not in wide, True),
    ("Cabriolet" in plain or "kind is:" in plain, False),                                   # a PDK coupe is searched as before
    ('"2014 Porsche 911 Carrera S"' in plain, True),
    ("market for this car's kind (Cabriolet 7-speed manual)" in llm._site_prompt(cab, "November 16, 2026", "Classic.com", 3), True),
    ("market for this car's kind" in llm._site_prompt(cab, "November 16, 2026", "Cars & Bids", 3), False),
    ("market for this car's kind" in llm._site_prompt({**cab, "body": "Coupe", "transmission": "PDK"}, "November 16, 2026", "Classic.com", 2), False),
]
bad = [(i, got, want) for i, (got, want) in enumerate(cases) if got != want]
for row in bad:
    print("FAILED", row)
print(f"kind cases: {len(cases)} failures: {len(bad)}")

# A sale is never left out for its price. An earlier version set aside sales with no page and no VIN that sat far
# from the rest; in a market that had moved, the two it set aside were real auction results ($108,000 on Bring a
# Trailer, $110,000 on Cars & Bids). Rows it marked are counted again when the car is opened.
def sale(price, url="https://www.classic.com/m/porsche/911/991/9911/carrera-s/cabriolet-manual/", vin="", aside=""):
    comp = calc.clean_comp({"status": "sold", "title": "2013 Porsche 911 Carrera S Cabriolet", "price": price, "url": url, "vin": vin,
                            "source": "Classic.com market", "date": "Apr 4, 2025", "miles": 20000})
    comp["aside"] = aside
    return comp

real = [sale(p) for p in (52500, 108000, 110000, 68500, 86000, 70000, 82500, 78500, 77000, 62500, 54101, 59500, 71250, 75000)]
real.append(sale(64250, url="https://bringatrailer.com/listing/2012-porsche-911-carrera-s-cabriolet-41/", vin="WP0CB2A91CS754100"))
marked = [sale(60000), dict(sale(108000), use=False, aside="far"), dict(sale(110000), use=False, aside="far"), dict(sale(90000), use=False, aside="mine")]
far = [
    (calc.set_aside_leads(real), 0),                                          # nothing is set aside for its price
    (sum(c["use"] for c in real), 15),
    (calc.restore_far(marked), 2),
    ([(c["price"], c["use"]) for c in marked], [(60000, True), (108000, True), (110000, True), (90000, False)]),   # the buyer's own choice stays
    (calc.restore_far(marked), 0),
]
bad = [(i, got, want) for i, (got, want) in enumerate(far) if got != want]
for row in bad:
    print("FAILED", row)
print(f"kind and far-sale cases: {len(cases) + len(far)} failures: {len(bad) + len([1 for got, want in cases if got != want])}")

# The buyer's own car is not a comparison, and one VIN for sale is one car (rows from a real garage).
def row(status, price, vin="", url="", source="", available="yes", title="2020 BMW M2 CS", date="", aside=""):
    comp = calc.clean_comp({"status": status, "title": title, "price": price, "vin": vin, "url": url, "source": source, "available": available, "date": date, "miles": 2000})
    comp["aside"] = aside
    return comp

me = {"year": 2014, "make": "Porsche", "model": "911", "trim": "Carrera S", "vin": "WP0CB2A98ES154726", "url": "https://racperformance.com/2014-porsche-911-carrera-s-carrollton-tx-75006/7525914"}
edm = "https://www.edmunds.com/bmw/m2-cs/2020/vin/WBS1J3C01L7H18422/"
veh = "https://www.classic.com/veh/2020-bmw-m2-cs-wbs1j3c01l7g34827-pPEG7N4/"
rows = [
    row("asking", 100220, "WP0CB2A98ES154726", "https://www.cars.com/shopping/results/", "RAC Performance", title="2014 Porsche 911 2dr Cabriolet Carrera S"),   # the car itself, on Cars.com
    row("sold", 64000, "WP0CB2A98ES154726", "https://bringatrailer.com/listing/2014-porsche-911-carrera-s-cabriolet-9/", "Bring a Trailer", date="Mar 3, 2023"),  # its own earlier sale stays
    row("asking", 106900, "WBS1J3C01L7H18422", edm + "?national=true", "Edmunds", title="2020 BMW M2 CS Base Coupe"),
    row("asking", 106900, "WBS1J3C01L7H18422", edm + "?radius=500", "Edmunds"),                                                                                 # the same car again
    row("sold", 86500, "WBS1J3C01L7G34827", veh, "Classic.com", date="Jan 19, 2023"),
    row("sold", 104000, "WBS1J3C01L7G34827", veh, "Classic.com", date="May 15, 2022"),                                                                          # one VIN, two prices: both stay, flagged
    row("sold", 86500, "WBS1J3C01L7G34827", veh, "Classic.com", date="Jan 19, 2023"),                                                                           # the same sale again
    row("asking", 99000, "", "https://racperformance.com/2014-porsche-911-carrera-s-carrollton-tx-75006/7525914/", "RAC Performance"),                          # the car's own listing page, no VIN
]
kept, tidied = calc.tidy_comps(me, rows)
tidy = [
    ([c["price"] for c in kept], [64000, 106900, 86500, 104000]),
    ([c["price"] for c in tidied["own"]], [100220, 99000]),
    (tidied["twice"], 2),
    (calc.vins_on_two_sales(kept), {"WBS1J3C01L7G34827"}),
    ("RAC Performance, $100,220" in calc.tidy_note(tidied) and "2 second copies" in calc.tidy_note(tidied), True),
    (calc.tidy_comps(me, kept)[1] == {"own": [], "twice": 0}, True),                                                       # nothing more to take out the second time
    ([c["price"] for c in calc.tidy_comps({}, rows[2:4] + [row("asking", 105000, "WBS1J3C01L7H18422", edm, "Edmunds", aside="mine")])[0]], [105000]),   # the buyer's own row is the one kept
]
bad = [(i, got, want) for i, (got, want) in enumerate(tidy) if got != want]
for item in bad:
    print("FAILED", item)
print(f"tidy cases: {len(tidy)} failures: {len(bad)}")

# A message cites only what supports the offer (the rows of a real car whose message cited $108,000 and $110,000
# sales for an $81,000 offer and explained them away with a "hotter market").
mkt = "https://www.classic.com/m/porsche/911/991/9911/carrera-s/cabriolet-manual/"
def car_row(status, price, miles, date="", vin="", url=mkt, source="Classic.com market listing", available=""):
    return calc.clean_comp({"status": status, "title": "2014 Porsche 911 Carrera S Cabriolet", "price": price, "miles": miles, "date": date,
                            "vin": vin, "url": url, "source": source, "available": available})

def phone_rows():
    return [car_row("asking", 91280, 43548, vin="WP0CB2A93ES154200", url="https://www.cars.com/vehicledetail/a1/", source="Coast to Coast Imports", available="yes"),
            car_row("asking", 88370, 46311, vin="WP0CB2A95ES154201", url="https://www.truecar.com/used-cars-for-sale/listing/WP0CB2A95ES154201/", source="Crown", available="yes"),
            car_row("asking", 67076, 57082, vin="WP0CB2A97ES154202", url="https://www.truecar.com/used-cars-for-sale/listing/WP0CB2A97ES154202/", source="Reliable Auto Source", available="yes"),
            car_row("asking", 66202, 72304, vin="WP0CB2A99ES154203", url="https://www.truecar.com/used-cars-for-sale/listing/WP0CB2A99ES154203/", source="The Platinum Collection", available="yes"),
            car_row("sold", 108000, 10000, "Aug 22, 2026"), car_row("sold", 110000, 43000, "Jul 2, 2026"), car_row("sold", 86000, 47000, "Mar 26, 2026"),
            car_row("sold", 75000, 23000, "Mar 16, 2021"),
            car_row("asking", 97900, 39000, "Oct 12, 2026", available="yes"), car_row("asking", 77950, 32000, available="yes"), car_row("asking", 86991, 13000, available="yes"),
            car_row("asking", 85980, 30758, vin="WP0CB2A96ES155261", url="https://switchcars.com/2014-porsche-911/x1", source="Switchcars", available="yes")]

buyer_car = {"year": 2014, "make": "Porsche", "model": "911", "trim": "Carrera S", "miles": 20178, "seller_type": "dealer"}
rows = phone_rows()
plain = llm.template_message(buyer_car, rows, 81000)
low = llm.template_message(buyer_car, rows, 68000)
import datetime
NOV17 = datetime.date(2026, 11, 17).toordinal()
fall = [car_row("sold", 108000, 10000, "Aug 22, 2026", url="https://bringatrailer.com/listing/2014-porsche-911-carrera-s-cabriolet-20/", vin="WP0CB2A96ES154062", source="Bring a Trailer"),
        car_row("sold", 88000, 44000, "Aug 26, 2026", url="https://bringatrailer.com/listing/2015-porsche-911-carrera-s-cabriolet-12/", vin="WP0CB2A98FS155165", source="Bring a Trailer"),
        car_row("sold", 86000, 29000, "Sep 16, 2026", url="https://bringatrailer.com/listing/2012-porsche-911-carrera-s-cabriolet-19-2/", vin="WP0CB2A99CS155039", source="Bring a Trailer"),
        car_row("sold", 77000, 20000, "Apr 4, 2025"), car_row("sold", 71250, 15000, "Feb 25, 2024"), car_row("sold", 70000, 29332, "Jun 24, 2025")]
msg = [
    ([c["price"] for c in calc.cite_sales(buyer_car, rows, offer=81000)], []),            # $86,000 is above the offer, $75,000 is from 2021
    ([c["price"] for c in calc.cite_sales(buyer_car, rows, offer=90000)], [86000]),
    ([c["price"] for c in calc.cite_sales(buyer_car, rows)], [108000, 110000, 86000]),   # without an offer: nearest and newest, as before
    ([c["price"] for c in calc.cite_asks(buyer_car, rows, 90000)], [85980, 91280]),      # nearest in miles first; rows on a list page have nothing to look up
    ([c["price"] for c in calc.cite_asks(buyer_car, rows, 81000)], []),                   # the cheap ones have three times the miles: no comparison
    ("$108,000" in plain or "$110,000" in plain or "hotter" in plain, False),
    ("I'd like to offer $81,000" in plain and "out-the-door" in plain, True),
    ("listed at" in low or "sold for" in low, False),                                    # nothing supports $68,000: the message cites nothing
    ("listed at $85,980" in llm.template_message(buyer_car, rows, 82500) and "asking prices, not sales" in llm.template_message(buyer_car, rows, 82500), True),
    # with sales from the last twelve months, a message cites those and not the older, cheaper ones a seller would wave away
    ([c["price"] for c in calc.cite_sales(buyer_car, fall, offer=91000, today=NOV17)], [86000, 88000]),
    ([c["price"] for c in calc.cite_sales(buyer_car, fall, offer=80000, today=NOV17)], [70000, 77000, 71250]),   # none recent supports it: the older ones, newest first
]
bad = [(i, got, want) for i, (got, want) in enumerate(msg) if got != want]
for item in bad:
    print("FAILED", item)
print(f"message cases: {len(msg)} failures: {len(bad)}")
