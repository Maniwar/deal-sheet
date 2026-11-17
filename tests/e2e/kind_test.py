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

# A sale nobody can open or check that sits far from the others is not counted (15 sales from one real search).
def sale(price, url="https://www.classic.com/m/porsche/911/991/9911/carrera-s/cabriolet-manual/", vin="", aside=""):
    comp = calc.clean_comp({"status": "sold", "title": "2013 Porsche 911 Carrera S Cabriolet", "price": price, "url": url, "vin": vin,
                            "source": "Classic.com market", "date": "Apr 4, 2025", "miles": 20000})
    comp["aside"] = aside
    return comp

real = [sale(p) for p in (52500, 108000, 110000, 68500, 86000, 70000, 82500, 78500, 77000, 62500, 54101, 59500, 71250, 75000)]
real.append(sale(64250, url="https://bringatrailer.com/listing/2012-porsche-911-carrera-s-cabriolet-41/", vin="WP0CB2A91CS754100"))
far = [
    (calc.set_aside_leads(real), 2),
    (sorted(c["price"] for c in real if c.get("aside") == "far"), [108000, 110000]),
    (calc.median([c["price"] for c in real if c["use"]]), 70000),
    (calc.set_aside_leads([sale(p) for p in (60000, 62000, 64000, 66000)] + [sale(120000, url="https://bringatrailer.com/listing/x-1/", vin="WP0CB2A98ES154077")]), 0),   # its own page and VIN: checkable
    (calc.set_aside_leads([sale(p) for p in (60000, 62000, 64000, 150000)]), 0),                # too few sales to judge by
    (calc.set_aside_leads([sale(p) for p in (60000, 62000, 64000, 66000, 68000)] + [sale(120000, aside="mine")]), 0),   # the buyer chose to count it
]
bad = [(i, got, want) for i, (got, want) in enumerate(far) if got != want]
for row in bad:
    print("FAILED", row)
print(f"kind and far-sale cases: {len(cases) + len(far)} failures: {len(bad) + len([1 for got, want in cases if got != want])}")
