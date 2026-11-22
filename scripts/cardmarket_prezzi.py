#!/usr/bin/env python3
"""
Scarica ogni giorno catalogo e listino prezzi pubblici di Cardmarket e prepara
un file compatto per gioco (cm_<idGame>.json) che la web-app DSR Archive legge.

Formato di uscita:
{
  "game": "Yu-Gi-Oh!", "idGame": 3, "createdAt": "...",
  "exp": {"<idExpansion>": "<nome espansione>", ...},
  "cols": ["id","name","exp","trend","avg30","low","avg7","trendFoil","rar","code","img"],
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


# ---------- rarità e codici dai database pubblici ----------
def fold(s):
    import unicodedata
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def base_name(n):
    n = str(n).replace('""', '"')
    n = re.sub(r"\s*\[[^\]]*\]", "", n)
    n = re.sub(r"\s*\(V\.\s*\d+[^)]*\)", "", n, flags=re.I)
    n = re.sub(r"\s*\((?:[A-Z]{1,6}\d{0,3}[a-z]?-[A-Z]{0,3}\d{1,4}[a-z]?|\d+/\d+)\)", "", n)
    return fold(n)


def version_no(n):
    m = re.search(r"\(V\.\s*(\d+)", str(n), re.I)
    return int(m.group(1)) if m else 0


YGO_IMG = {}   # nome carta -> id immagine ufficiale (YGOPRODeck)


def ygo_sets():
    """nome carta -> {nome set: [(rarità, codice)]} da YGOPRODeck"""
    try:
        d = get("https://db.ygoprodeck.com/api/v7/cardinfo.php")
    except Exception as e:
        print("YGOPRODeck non disponibile:", e)
        return {}
    out = {}
    for c in d.get("data", []):
        imgs = c.get("card_images") or []
        YGO_IMG[fold(c["name"])] = imgs[0]["id"] if imgs else c.get("id")
        m = out.setdefault(fold(c["name"]), {})
        for st in c.get("card_sets") or []:
            m.setdefault(fold(st.get("set_name")), []).append((st.get("set_rarity") or "", st.get("set_code") or ""))
    print("YGOPRODeck:", len(out), "carte")
    return out


def pkm_sets():
    """(nome set, nome carta) -> [(numero, rarità, codice)] dal database PokemonTCG/pokemon-tcg-data"""
    import io, zipfile
    try:
        req = urllib.request.Request("https://codeload.github.com/PokemonTCG/pokemon-tcg-data/zip/refs/heads/master", headers={"User-Agent": "DSR-Archive/1.0"})
        z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(req, timeout=180).read()))
    except Exception as e:
        print("Database Pokémon non disponibile:", e)
        return {}
    names = [n for n in z.namelist() if n.endswith(".json")]
    setfile = next((n for n in names if n.endswith("/sets/en.json")), None)
    sets = {x["id"]: x for x in json.loads(z.read(setfile))} if setfile else {}
    out = {}
    for n in names:
        if "/cards/en/" not in n:
            continue
        sid = os.path.basename(n)[:-5]
        st = sets.get(sid, {})
        for c in json.loads(z.read(n)):
            num = c.get("number", "")
            code = f"{st.get('ptcgoCode') or sid.upper()} {num}".strip()
            out.setdefault((fold(st.get("name", sid)), fold(c["name"])), []).append((num, c.get("rarity") or "", code, f"{sid}/{num}"))
    for k in out:
        out[k].sort(key=lambda x: (int(re.sub(r"\D", "", x[0]) or 0), x[0]))
    print("Database Pokémon:", len(out), "gruppi carta/set")
    return out


def add_rarities(gid, rows, exp, ygo, pkm):
    """aggiunge rarità e codice a ogni prodotto quando si riesce a capirli con certezza"""
    groups = {}
    for r in rows:
        groups.setdefault((r[2], base_name(r[1])), []).append(r)
    found = 0
    for (eid, bn), rs in groups.items():
        en = fold(exp.get(str(eid), ""))
        rs.sort(key=lambda r: (version_no(r[1]), r[0]))
        for r in rs:
            m = re.search(r"\(V\.\s*\d+\s*-\s*([^)]+)\)", r[1])
            r.extend([m.group(1).strip() if m else "", "", ""])
            if gid == 3 and bn in YGO_IMG:
                r[10] = str(YGO_IMG[bn])
        if gid == 3 and en:
            sets = ygo.get(bn, {})
            prints = sets.get(en, [])
            if not prints and len(en) >= 4 and not re.search(r"\b(japanese|ocg|korean|asian|chinese)\b", en):  # nome del set abbreviato su Cardmarket (es. "... Legend" / "... Legend Collection")
                cand = [k for k in sets if k.startswith(en + " ") or (len(k) >= 6 and en.startswith(k + " "))]
                if len(cand) == 1: prints = sets[cand[0]]
            rars = list(dict.fromkeys(p[0] for p in prints))
            for r in rs:
                if r[8]:
                    hit = [p for p in prints if fold(p[0]) == fold(r[8])]
                    if hit: r[9] = hit[0][1]
                elif len(rars) == 1:
                    r[8] = rars[0]; r[9] = prints[0][1]
                elif len(rars) > 1:
                    r[8] = " / ".join(rars)
                    codes = {p[1] for p in prints}
                    if len(codes) == 1: r[9] = prints[0][1]
        elif gid == 6 and en:
            prints = pkm.get((en, bn), [])
            if prints and len(prints) == len(rs):
                for r, p in zip(rs, prints):
                    r[8] = r[8] or p[1]; r[9] = p[2]; r[10] = p[3]
            elif prints:
                rars = list(dict.fromkeys(p[1] for p in prints if p[1]))
                for r in rs:
                    if not r[8] and rars: r[8] = rars[0] if len(rars) == 1 else " / ".join(rars)
        found += sum(1 for r in rs if r[8])
    return found


def main():
    os.makedirs(OUT, exist_ok=True)
    summary = {}
    ygo, pkm = ygo_sets(), pkm_sets()
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
        n_rar = add_rarities(gid, rows, exp, ygo, pkm)
        doc = {"game": gname, "idGame": gid, "createdAt": prices.get("createdAt") or singles.get("createdAt"),
               "exp": exp, "cols": ["id", "name", "exp", "trend", "avg30", "low", "avg7", "trendFoil", "rar", "code", "img"], "p": rows}
        path = os.path.join(OUT, f"cm_{gid}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        n_exp = len({r[2] for r in rows})
        summary[gname] = {"prodotti": len(rows), "con_prezzo": sum(1 for r in rows if r[3] is not None), "con_rarita": n_rar,
                          "espansioni": n_exp, "espansioni_con_nome": len(exp), "MB": round(os.path.getsize(path) / 1e6, 2)}
        print(f"[{gname}] {summary[gname]}")
        print("  esempi espansioni:", list(exp.items())[:8])
        print("  esempi prodotti:", rows[:3])
        print("  esempi con rarità:", [r for r in rows if r[8]][:5])
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"games": {str(k): v for k, v in GAMES.items()}, "summary": summary}, f, ensure_ascii=False)
    if not summary:
        sys.exit("Nessun gioco scaricato")


if __name__ == "__main__":
    main()
