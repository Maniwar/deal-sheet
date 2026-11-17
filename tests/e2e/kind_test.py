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
