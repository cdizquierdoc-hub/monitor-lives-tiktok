"""Diagnóstico 8: más vendidos y precio a crédito por plataforma."""
import gzip, json, re, urllib.request, urllib.error, urllib.parse
from concurrent.futures import ThreadPoolExecutor
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"

def get(url, accept="application/json,text/html;q=0.9", headers=None):
    h = {"User-Agent": UA, "Accept": accept, "Accept-Language": "es-EC,es;q=0.9"}; h.update(headers or {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=40) as r:
            raw = r.read(); raw = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
            return r.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e: return e.code, ""
    except Exception as e: return 0, str(e)

def f(s, n): return re.sub(r"\s+", " ", s)[:n]
def ctx(b, pat, a=500, d=900):
    m = re.search(pat, b, re.I); return f(b[max(0, m.start()-a):m.end()+d], a+d) if m else "(no)"

def vtex(host):
    o = [f"## VTEX {host}"]
    s, b = get(f"https://{host}/api/catalog_system/pub/products/search?O=OrderByTopSaleDESC&_from=0&_to=4")
    try: d = json.loads(b)
    except Exception: return "\n".join(o + [f"{s} {b[:200]}"])
    o.append("top: " + str([p["productName"][:50] for p in d]))
    p = d[0]
    o.append("product keys: " + str([k for k in p.keys()]))
    specs = {k: p[k] for k in p if isinstance(p[k], list) and k not in ("items","categories","categoriesIds","allSpecifications","allSpecificationsGroups","clusterHighlights","searchableClusters","productClusters") }
    o.append("listas: " + json.dumps(specs, ensure_ascii=False)[:600])
    o.append("allSpecifications: " + str(p.get("allSpecifications")))
    o.append("clusters: " + json.dumps(p.get("productClusters"), ensure_ascii=False)[:300])
    co = p["items"][0]["sellers"][0]["commertialOffer"]
    o.append("offer keys: " + str(list(co.keys())))
    o.append("Price/List/PriceWithoutDiscount: " + str([co.get("Price"), co.get("ListPrice"), co.get("PriceWithoutDiscount")]))
    inst = co.get("Installments") or []
    o.append(f"installments({len(inst)}): " + json.dumps(sorted({(i.get('PaymentSystemName'), i.get('NumberOfInstallments'), i.get('Value'), i.get('TotalValuePlusInterestRate')) for i in inst}, key=str)[:25], ensure_ascii=False)[:1200])
    o.append("teasers: " + json.dumps(co.get("Teasers") or co.get("PromotionTeasers"), ensure_ascii=False)[:300])
    # página del producto: texto de crédito
    s2, h = get(p["link"], "text/html")
    o.append("PDP credito ctx: " + ctx(h, r"cr[eé]dito|cuota|semanal|mensual", 300, 700))
    return "\n".join(o)

def woo(host):
    s, b = get(f"https://{host}/wp-json/wc/store/v1/products?per_page=5&orderby=popularity")
    try: d = json.loads(b); return f"## WOO {host} popularity: " + str([x["name"][:40] for x in d])
    except Exception: return f"## WOO {host} {s} {b[:150]}"

def presta(host, ruta):
    s, b = get(f"https://{host}/{ruta}?order=product.sales.desc&from-xhr", headers={"X-Requested-With": "XMLHttpRequest"})
    try: d = json.loads(b); return f"## PRESTA {host} sales: " + str([x["name"][:40] for x in d["products"][:5]]) + " sort_orders=" + str([x.get("urlParameter") for x in d.get("sort_orders", [])])
    except Exception: return f"## PRESTA {host} {s} {b[:150]}"

def mage(host, ruta):
    o = [f"## MAGE {host}"]
    s, b = get(f"https://{host}/{ruta}?product_list_order=bestsellers&product_list_limit=12", "text/html")
    o.append("orders: " + str(sorted(set(re.findall(r'<option value="([a-z_]+)"[^>]*>', b)))[:20]))
    o.append("names: " + str([f(x, 50) for x in re.findall(r'class="product-item-link"[^>]*>\s*([^<]+)<', b)[:5]]))
    o.append("credit ctx: " + ctx(b, r"cr[eé]dito|credit-price|cuota", 300, 1400))
    return "\n".join(o)

def hybris():
    o = ["## HYBRIS etafashion"]
    s, b = get("https://www.etafashion.com/es_EC/HOGAR/LINEA-BLANCA/c/1090221/results?q=%3AtopSellers&page=0&sort=topSellers", headers={"X-Requested-With": "XMLHttpRequest"})
    s2, b2 = get("https://www.etafashion.com/es_EC/HOGAR/c/109/results?q=%3AtopSellers&page=0", headers={"X-Requested-With": "XMLHttpRequest"})
    for bb in (b, b2):
        try:
            d = json.loads(bb); o.append("sorts: " + str([x.get("code") for x in d.get("sorts", [])]) + " names: " + str([x["name"][:40] for x in d["results"][:5]]))
            o.append("credit: " + json.dumps(d["results"][0].get("clientCreditPriceData"), ensure_ascii=False)[:900]); break
        except Exception as e: o.append(f"err {e} {bb[:120]}")
    return "\n".join(o)

def artefacta():
    o = ["## ARTEFACTA"]
    s, b = get("https://www.artefacta.com/rest/V1/products-render-info?searchCriteria[pageSize]=3&searchCriteria[currentPage]=1&searchCriteria[sortOrders][0][field]=bestsellers&storeId=16&currencyCode=USD")
    o.append(f"sort bestsellers {s} " + f(b, 300))
    s, b = get("https://www.artefacta.com/rest/V1/products-render-info?searchCriteria[pageSize]=1&searchCriteria[currentPage]=1&storeId=16&currencyCode=USD")
    try:
        it = json.loads(b)["items"][0]; o.append("keys: " + str(list(it.keys()))); o.append("price_info: " + json.dumps(it.get("price_info"))[:700]); o.append("ext: " + json.dumps(it.get("extension_attributes"))[:900])
        s, h = get(it["url"], "text/html"); o.append("PDP credito ctx: " + ctx(h, r"cr[eé]dito|cuota|semanal|mensual", 300, 900))
    except Exception as e: o.append(f"err {e}")
    s, h = get("https://www.artefacta.com/c/linea-blanca/refrigeracion/refrigeradoras", "text/html")
    o.append("cat credito ctx: " + ctx(h, r"cr[eé]dito|cuota|semanal", 300, 900))
    return "\n".join(o)

T = [lambda: vtex("www.crecos.com"), lambda: vtex("www.orvehogar.com"), lambda: vtex("www.almacenesjapon.com"), lambda: vtex("www.marcimex.com"),
     lambda: vtex("www.comandato.com"), lambda: vtex("www.pycca.com"), lambda: vtex("www.unitystores.com"), lambda: vtex("www.estuardosanchez.com"),
     lambda: woo("bodeguitadelahorro.com"), lambda: woo("www.computron.com.ec"), lambda: presta("eljuri.store", "3-electrodomesticos"),
     lambda: mage("www.tia.com.ec", "electrodomesticos"), lambda: mage("coralhipermercados.com", "electrodomesticos.html"), hybris, artefacta]
with ThreadPoolExecutor(6) as ex:
    for r in ex.map(lambda t: t(), T): print("\n" + r, flush=True)
