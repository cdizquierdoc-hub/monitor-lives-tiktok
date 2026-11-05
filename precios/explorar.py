"""Diagnóstico 3: cómo arma Artefacta su búsqueda y sus listados."""
import re, sys, json, urllib.request, urllib.error
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
def get(url, accept="text/html,*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "es-EC,es;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status, r.read().decode("utf-8","replace"), r.geturl()
    except urllib.error.HTTPError as e: return e.code, (e.read() or b"").decode("utf-8","replace"), url
    except Exception as e: return 0, str(e), url
for url in ["https://www.artefacta.com/search/refrigeradora", "https://www.artefacta.com/c/linea-blanca/refrigeracion/refrigeradoras", "https://www.artefacta.com/refrigeradora-indurama-side-by-side-2-puertas-568-l-no-frost-ri-7568-158735/p"]:
    s, b, u = get(url)
    print(f"\n######## {url} -> {s} {len(b)} {u}")
    low = b.lower()
    print("marks:", {m: low.count(m) for m in ["algolia","doofinder","klevu","searchanise","amasty","product-item","price-box","data-price-amount","ld+json","__initial","window.checkout","mage-init","x-magento-init","pagebuilder","price","precio","/p\"","itemprop"]})
    print("scripts:", [x for x in re.findall(r'<script[^>]+src="([^"]+)"', b) if "artefacta" not in x or "static" not in x][:20])
    for m in re.finditer(r"\$\s?[0-9]{2,3}[.,][0-9]{2}|\$\s?[0-9],?[0-9]{3}", b):
        print("PRICE CTX:", re.sub(r"\s+"," ",b[max(0,m.start()-400):m.end()+150])); break
    for m in re.finditer(r'href="(https://www\.artefacta\.com/[^"]+/p)"', b):
        print("PRODUCT LINK CTX:", re.sub(r"\s+"," ",b[max(0,m.start()-300):m.end()+700])); break
    for j in re.findall(r'<script type="application/ld\+json">(.*?)</script>', b, re.S)[:3]:
        print("LDJSON:", re.sub(r"\s+"," ",j)[:800])
    for m in re.finditer(r'"(?:api|endpoint|url)"\s*:\s*"([^"]*(?:search|catalog|product)[^"]*)"', b):
        print("ENDPOINT:", m.group(1)[:200])
    print("first 'x-magento-init' blocks w/ search:", [re.sub(r"\s+"," ",x)[:300] for x in re.findall(r'<script type="text/x-magento-init">(.*?)</script>', b, re.S) if "search" in x.lower() or "product" in x.lower()][:4])
