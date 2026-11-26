"""Diagnóstico 9: bloque de precio a crédito de Tía y medios de pago VTEX."""
import gzip, json, re, urllib.request
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
def get(url, accept="application/json"):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept}), timeout=40) as r:
        raw = r.read(); raw = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw; return raw.decode("utf-8", "replace")
f = lambda s, n: re.sub(r"\s+", " ", s)[:n]
b = get("https://www.tia.com.ec/electrodomesticos/electromayores/refrigeradoras-y-congeladores", "text/html")
i = b.find("content-price")
print("TIA block:", f(b[i:i+4500], 4500))
print("\nTIA credit words:", sorted(set(re.findall(r'class="([^"]*credit[^"]*)"', b)))[:20])
for h in ["www.marcimex.com", "www.comandato.com", "www.crecos.com", "www.pycca.com", "www.unitystores.com", "www.estuardosanchez.com"]:
    d = json.loads(get(f"https://{h}/api/catalog_system/pub/products/search?fq=C:/&O=OrderByTopSaleDESC&_from=0&_to=2") or "[]") or json.loads(get(f"https://{h}/api/catalog_system/pub/products/search?O=OrderByTopSaleDESC&_from=0&_to=2"))
    names = {}
    for p in d:
        for it in p["items"][:1]:
            co = it["sellers"][0]["commertialOffer"]
            for x in co.get("Installments") or []:
                n = x["PaymentSystemName"]; names.setdefault(n, set()).add((x["NumberOfInstallments"], x["Value"], x["TotalValuePlusInterestRate"]))
            print(h, p["productName"][:40], "Price", co["Price"], "List", co["ListPrice"])
    print(h, "medios:", {k: sorted(v)[-1] for k, v in names.items()})
