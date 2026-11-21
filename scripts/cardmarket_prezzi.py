#!/usr/bin/env python3
"""
Scarica ogni giorno catalogo e listino prezzi pubblici di Cardmarket e prepara
un file compatto per gioco (cm_<idGame>.json) che la web-app DSR Archive legge.

Formato di uscita:
{
  "game": "Yu-Gi-Oh!", "idGame": 3, "createdAt": "...",
  "exp": {"<idExpansion>": "<nome espansione>", ...},
  "cols": ["id","name","exp","trend","avg30","low","avg7","trendFoil"],
  "p": [[idProduct, "nome", idExpansion, trend, avg30, low, avg7, trendFoil], ...]
}
"""
import json, os, re, sys, urllib.request, collections

BASE = "https://downloads.s3.cardmarket.com/productCatalog"
GAMES = {3: "Yu-Gi-Oh!", 6: "Pokémon", 18: "One Piece"}
OUT = sys.argv[1] if len(sys.argv) > 1 else "out"

# parole generiche dei prodotti sigillati da togliere per ottenere il nome dell'espansione
GENERIC = r"(booster|boosters|box|display|pack|packs|case|blister|bundle|tin|tins|deck|decks|sleeved|collection|set|kit|lot|bundle|elite|trainer|etb|starter|structure|special|edition|1st|unlimited|english|german|french|italian|spanish|korean|chinese|portuguese|en|de|fr|it|es|jp|kr|-|–|—|:|\+|&|\(\d+[^)]*\)|\d+x)"
GENERIC_RE = re.compile(r"(?:\s+" + GENERIC + r")+$", re.I)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "DSR-Archive/1.0 (github actions)"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


STOP = {"the", "of", "and", "a", "de", "vs", "vs.", "&", "-", "of the", "le", "la", "du"}
W = lambda w: w.lower().strip(":,;.!")


def common_prefix_words(names):
    ws = [n.split() for n in names]
    out = []
    for parts in zip(*ws):
        if all(W(p) == W(parts[0]) for p in parts):
            out.append(parts[0])
        else:
            break
    return " ".join(out)


def expansion_names(nonsingles):
    by = collections.defaultdict(list)
    for p in nonsingles:
        if p.get("idExpansion"):
            by[p["idExpansion"]].append(p["name"])
    res = {}
    for eid, names in by.items():
        names = sorted(set(names), key=len)
        boosters = [n for n in names if re.search(r"booster|display", n, re.I)]
        cand = common_prefix_words(boosters) if len(boosters) > 1 else (boosters[0] if boosters else "")
        if len(cand.split()) < 1 or len(cand) < 3:
            cand = common_prefix_words(names) if len(names) > 1 else names[0]
        cand = GENERIC_RE.sub("", cand).strip(" -–—:")
        if not cand or W(cand.split()[-1]) in STOP:
            alt = GENERIC_RE.sub("", (boosters or names)[0]).strip(" -–—:")
            if alt and W(alt.split()[-1]) not in STOP:
                cand = alt
        if len(cand) >= 3:
            res[str(eid)] = cand
    return res


def r2(v):
    return None if v is None else round(float(v), 2)


def main():
    os.makedirs(OUT, exist_ok=True)
    summary = {}
    for gid, gname in GAMES.items():
        try:
            singles = get(f"{BASE}/productList/products_singles_{gid}.json")
            prices = get(f"{BASE}/priceGuide/price_guide_{gid}.json")
        except Exception as e:
            print(f"[{gname}] ERRORE download: {e}")
            continue
        try:
            nons = get(f"{BASE}/productList/products_nonsingles_{gid}.json").get("products", [])
        except Exception as e:
            print(f"[{gname}] nessun file prodotti sigillati ({e})")
            nons = []
        exp = expansion_names(nons)
        pg = {x["idProduct"]: x for x in prices.get("priceGuides", [])}
        rows = []
        for p in singles.get("products", []):
            g = pg.get(p["idProduct"], {})
            rows.append([p["idProduct"], p["name"], p.get("idExpansion"), r2(g.get("trend")), r2(g.get("avg30")),
                         r2(g.get("low")), r2(g.get("avg7")), r2(g.get("trend-foil"))])
        doc = {"game": gname, "idGame": gid, "createdAt": prices.get("createdAt") or singles.get("createdAt"),
               "exp": exp, "cols": ["id", "name", "exp", "trend", "avg30", "low", "avg7", "trendFoil"], "p": rows}
        path = os.path.join(OUT, f"cm_{gid}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        n_exp = len({r[2] for r in rows})
        summary[gname] = {"prodotti": len(rows), "con_prezzo": sum(1 for r in rows if r[3] is not None),
                          "espansioni": n_exp, "espansioni_con_nome": len(exp), "MB": round(os.path.getsize(path) / 1e6, 2)}
        print(f"[{gname}] {summary[gname]}")
        print("  esempi espansioni:", list(exp.items())[:8])
        print("  esempi prodotti:", rows[:3])
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"games": {str(k): v for k, v in GAMES.items()}, "summary": summary}, f, ensure_ascii=False)
    if not summary:
        sys.exit("Nessun gioco scaricato")


if __name__ == "__main__":
    main()
