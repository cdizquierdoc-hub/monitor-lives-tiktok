"""Diagnóstico 4: endpoints REST de Artefacta."""
import re, json, urllib.request, urllib.error, urllib.parse
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
def get(url, accept="application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "X-Requested-With": "XMLHttpRequest"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status, r.read().decode("utf-8","replace")
    except urllib.error.HTTPError as e: return e.code, (e.read() or b"").decode("utf-8","replace")
    except Exception as e: return 0, str(e)
B = "https://www.artefacta.com/rest/art_artefacta_sv/V1/"
tries = [
 B + "products-render-info?searchCriteria[pageSize]=2&searchCriteria[currentPage]=1&storeId=16&currencyCode=USD",
 B + "products-render-info?searchCriteria[pageSize]=2&searchCriteria[currentPage]=1&searchCriteria[filterGroups][0][filters][0][field]=name&searchCriteria[filterGroups][0][filters][0][value]=%25refrigeradora%25&searchCriteria[filterGroups][0][filters][0][conditionType]=like&storeId=16&currencyCode=USD",
 B + "unicomer/live-search-plp/cards",
 B + "unicomer/live-search-plp/cards?q=refrigeradora",
 B + "unicomer/live-search-plp/cards?skus=158735",
 B + "products?searchCriteria[pageSize]=2",
 "https://www.artefacta.com/rest/V1/products-render-info?searchCriteria[pageSize]=2&storeId=16&currencyCode=USD",
]
for u in tries:
    s, b = get(u); print(f"\n## {s} {u}\n{b[:1500]}")
s, b = get("https://www.artefacta.com/c/linea-blanca/refrigeracion/refrigeradoras", "text/html")
cfg = re.findall(r'"Unicomer_LiveSearchProductListing/js/plp-cards":\s*(\{.*?\})\s*\}\s*\}', b, re.S)
print("\nPLP CONFIG:", cfg[0][:2000] if cfg else None)
items = re.findall(r'<li[^>]*class="[^"]*product-item[^"]*"[^>]*>(.*?)</li>', b, re.S)
print("ITEMS:", len(items)); print(re.sub(r"\s+"," ",items[0])[:1500] if items else "")
print("data-sku/ids:", re.findall(r'data-(?:sku|product-id|product-sku)="([^"]+)"', b)[:10])
