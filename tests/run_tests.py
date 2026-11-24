#!/usr/bin/env python3
"""
Controlli automatici di DSR Archive.

Apre index.html in un browser vero (Chromium, modalità "senza account" che salva nel browser)
e prova le funzioni principali dell'archivio. Il catalogo Cardmarket è sostituito da un piccolo
catalogo di prova (tests/fixtures) e le immagini esterne da un'immagine finta, così i risultati
non dipendono da internet.

Uso:   python3 tests/run_tests.py
       LOCAL_LIBS=/percorso/node_modules python3 tests/run_tests.py   (librerie senza internet)
Esce con codice 1 se un controllo fallisce.
"""
import asyncio, base64, json, os, re, subprocess, sys, tempfile, traceback
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
URL = (ROOT / "index.html").as_uri()
LIBS = os.environ.get("LOCAL_LIBS")
LIB_FILES = {"xlsx": "xlsx/dist/xlsx.full.min.js", "supabase": "@supabase/supabase-js/dist/umd/supabase.js"}
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("  ✔ " if cond else "  ✘ ") + name + ("" if cond else f"   → {detail}"))


async def main():
    tmp = Path(tempfile.mkdtemp())
    async with async_playwright() as p:
        exe = os.environ.get("CHROME_PATH")
        browser = await p.chromium.launch(**({"executable_path": exe} if exe else {}), args=["--no-sandbox"])
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
        page = await ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            u = r.request.url
            if LIBS and "jsdelivr" in u:
                for k, f in LIB_FILES.items():
                    if k in u:
                        return await r.fulfill(path=str(Path(LIBS) / f), content_type="application/javascript")
            m = re.search(r"cm-data/(cm_\d+\.json)", u)
            if m:
                f = FIX / m.group(1)
                return await (r.fulfill(path=str(f), content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}) if f.exists() else r.fulfill(status=404, body=""))
            if re.search(r"images\.(pokemontcg|ygoprodeck)|onepiece-cardgame", u):
                return await r.fulfill(body=PNG, content_type="image/png", headers={"Access-Control-Allow-Origin": "*"})
            if u.startswith("file://") or "jsdelivr" in u:
                return await r.continue_()
            return await r.fulfill(status=404, body="")   # niente chiamate verso altri siti durante i test
        await page.route("**/*", route)

        W = lambda ms=300: page.wait_for_timeout(ms)
        ev = page.evaluate

        async def go(h):
            await page.goto(URL + h); await W(350)

        async def pick_name(game, text, idx=0):
            await page.click(".top-actions [data-act=addCard]"); await W(300)
            await page.select_option("select[name=game]", game); await W(1200)
            await page.type("input[name=name]", text, delay=10); await W(800)
            for _ in range(idx + 1):
                await page.keyboard.press("ArrowDown")
            await page.keyboard.press("Enter"); await W(250)

        async def step(title, fn):
            print(f"\n▶ {title}")
            try:
                await fn()
            except Exception as e:
                check(title + " (eseguito senza eccezioni)", False, f"{e}\n{traceback.format_exc(limit=2)}")

        # ---------------------------------------------------------------
        async def avvio():
            await page.goto(URL); await W(300)
            await page.click("#loc"); await W(500)
            check("l'app si apre in modalità locale", await page.is_visible("text=Il tuo archivio"))
        await step("Avvio", avvio)

        async def import_excel():
            await go("#/dati")
            await page.set_input_files("#imf", str(FIX / "tracker_prova.xlsx")); await W(600)
            note = await page.inner_text("#impv .note")
            check("anteprima dell'import Excel", "righe lette" in note, note)
            await page.click("#impgo"); await W(900)
            n = await ev("({cards: S.cards.size, copies: [...S.copies.values()].reduce((t,c)=>t+c.qty,0), lots: S.lots.size})")
            check("import Excel: carte, copie e lotti attesi", n == {"cards": 3, "copies": 8, "lots": 1}, n)
        await step("Import del tracker Excel", import_excel)

        async def import_cm():
            await go("#/dati")
            await page.set_input_files("#imf", str(FIX / "ArticlesFromShipment1308570102.csv")); await W(1500)
            note = await page.inner_text("#impv .note")
            check("CSV Cardmarket riconosciuto, nessun codice sconosciuto", "non trovati" not in note and "ordine Cardmarket" in note, note)
            await page.fill("#cmship", "1,50"); await W(100)
            before = await ev("[...S.copies.values()].reduce((t,c)=>t+(c.buy_price||0)*c.qty,0)")
            await page.click("#cmgo"); await W(1000)
            after = await ev("[...S.copies.values()].reduce((t,c)=>t+(c.buy_price||0)*c.qty,0)")
            check("spedizione divisa sulle carte (totale = 8,35 + 1,50)", abs((after - before) - 9.85) < 0.06, after - before)
            dup = await ev("(() => { const k = new Map(); for (const c of S.cards.values()) { const x = [c.game,c.expansion,c.name,c.rarity].join('|').toLowerCase(); k.set(x,(k.get(x)||0)+1) } return [...k.values()].some(v=>v>1) })()")
            check("nessuna carta doppia dopo l'import", not dup)
            await go("#/dati")
            await page.set_input_files("#imf", str(FIX / "ArticlesFromShipment1308570102.csv")); await W(900)
            check("avviso se lo stesso ordine viene reimportato", "già stato importato" in await page.inner_text("#impv .note"))
            await page.click("#cmm button[data-v=newlot]"); await page.fill("#cmship", "1,50"); await W(150)
            check("prezzo del nuovo lotto = carte + spedizione", (await page.input_value("#cmlp")) == "9,85", await page.input_value("#cmlp"))
            await page.click("#cmgo"); await W(900)
            lot = await ev("[...S.lots.values()].find(l => l.description.includes('1308570102'))")
            inlot = await ev(f"[...S.copies.values()].filter(c => c.lot_id === '{lot['id']}')") if lot else []
            check("ordine importato come lotto (costo condiviso)", lot and lot["total_price"] == 9.85 and inlot and all(c["buy_price"] is None for c in inlot), lot)
        await step("Import di un ordine Cardmarket (CSV)", import_cm)

        async def add_card():
            await pick_name("Yu-Gi-Oh!", "ash blossom macr")
            vals = [await page.input_value(f"input[name={n}]") for n in ("name", "expansion", "rarity")]
            check("il suggerimento compila nome, espansione e rarità", vals == ["Ash Blossom & Joyous Spring", "Maximum Crisis", "Secret Rare"], vals)
            await page.fill("input[name=buy_price]", "8")
            await page.dblclick("#acf button.pri"); await W(1200)
            rows = await ev("[...S.copies.values()].filter(c => S.cards.get(c.card_id).name.startsWith('Ash Blossom') && S.cards.get(c.card_id).expansion === 'Maximum Crisis' && c.buy_price === 8)")
            check("doppio clic su Salva crea una sola copia", len(rows) == 1 and rows[0]["qty"] == 1, rows)
            cm = await ev("[...S.cards.values()].find(c => c.name.startsWith('Ash Blossom') && c.expansion === 'Maximum Crisis').cm_id")
            check("la carta è collegata al prodotto Cardmarket", bool(cm), cm)
            await W(1500)
            img = await ev("[...S.cards.values()].find(c => c.name.startsWith('Ash Blossom') && c.expansion === 'Maximum Crisis').image_url || ''")
            check("immagine della stampa esatta", "ygoprodeck" in img, img)
        await step("Aggiunta di una carta dai suggerimenti", add_card)

        async def codice_posizione():
            await pick_name("Yu-Gi-Oh!", "CRMS-IT008")
            vals = [await page.input_value(f"[name={n}]") for n in ("name", "rarity", "language")]
            check("il codice del set trova la stampa e la lingua", vals == ["Blackwing - Gale the Whirlwind", "Rare", "IT"], vals)
            await page.fill("input[name=location]", "Raccoglitore 2"); await page.fill("input[name=buy_price]", "1")
            await page.click("#acf button.pri"); await W(1000)
            cp = await ev("[...S.copies.values()].find(c => S.cards.get(c.card_id).name === 'Blackwing - Gale the Whirlwind' && c.language === 'IT')")
            check("la posizione viene salvata", cp and cp.get("location") == "Raccoglitore 2", cp)
            check("la scheda carta mostra la posizione", "Raccoglitore 2" in await page.inner_text("#app"))
            await go("#/collezione"); await page.select_option("#floc", "Raccoglitore 2"); await W(400)
            rows = await page.query_selector_all("#ctab tbody tr")
            check("filtro per posizione nella Collezione", len(rows) == 1, len(rows))
            await page.select_option("#floc", ""); await W(200)
            await ev(f"SEL.clear(); SEL.add('{cp['card_id']}'); selLocForm()"); await W(300)
            await page.fill("#slc input[name=v]", "Scatola A"); await page.click("#slc button.pri"); await W(800)
            locs = await ev(f"copiesOf('{cp['card_id']}').filter(c => c.status !== 'venduto').map(c => c.location)")
            check("posizione cambiata per le carte selezionate", locs and all(l == "Scatola A" for l in locs), locs)
            await page.fill("#fq", "scatola a"); await W(500)
            check("la ricerca trova anche la posizione", len(await page.query_selector_all("#ctab tbody tr")) == 1)
            await page.fill("#fq", ""); await W(300)
            await pick_name("Yu-Gi-Oh!", "Number 39")
            check("un nome simile a un codice cerca comunque per nome", True)
            await page.keyboard.press("Escape"); await ev("closeModal()")
        await step("Codice del set e posizione", codice_posizione)

        async def vendita():
            ash = await ev("[...S.copies.values()].find(c => c.status !== 'venduto' && S.cards.get(c.card_id).name.startsWith('Ash Blossom') && c.buy_price === 8).id")
            await ev(f"orderForm({{items: ['{ash}']}})"); await W(400)
            await page.fill("input[name=platform]", "cardmarket")   # minuscolo: la commissione deve funzionare lo stesso
            await page.fill("#orows [data-p]", "20"); await W(200)
            check("commissione 5% calcolata anche con 'cardmarket' minuscolo", (await page.input_value("input[name=fee]")) == "1,00", await page.input_value("input[name=fee]"))
            await page.fill("input[name=sc]", "1,20"); await page.fill("input[name=sk]", "1,50"); await W(150)
            await page.dblclick("#of button.ok"); await W(1000)
            orders = await ev("[...S.orders.values()]")
            check("doppio clic su Registra vendita crea un solo ordine", len(orders) == 1, len(orders))
            net = await ev("(index(), oc([...S.orders.values()][0]).net)")
            check("netto = 20 + 1,20 − 1,00 − 1,50 = 18,70", abs(net - 18.70) < 0.001, net)
            await page.click("[data-act=undo]"); await W(800)
            st = await ev(f"S.copies.get('{ash}')")
            check("Annulla rimette la carta disponibile e toglie l'ordine", st["status"] == "disponibile" and not await ev("S.orders.size"), st)
            await ev(f"orderForm({{items: ['{ash}']}})"); await W(300)
            await page.fill("#orows [data-p]", "20"); await page.click("#of button.ok"); await W(900)
            oid = await ev("[...S.orders.keys()][0]")
            await ev(f"orderView('{oid}')"); await W(300)
            await page.click("#ocancel"); await W(300); await page.click("[data-yes]"); await W(900)
            check("annullare la vendita dall'ordine la rimette disponibile", (await ev(f"S.copies.get('{ash}')"))["status"] == "disponibile" and not await ev("S.orders.size"))
        await step("Vendite e annullamento", vendita)

        async def spedizioni():
            ash = await ev("[...S.copies.values()].find(c => c.status !== 'venduto' && S.cards.get(c.card_id).name.startsWith('Ash Blossom') && c.buy_price === 8).id")
            await ev(f"orderForm({{items: ['{ash}']}})"); await W(300)
            await page.fill("#orows [data-p]", "20"); await page.click("#of button.ok"); await W(900)
            oid = await ev("[...S.orders.keys()][0]")
            check("una nuova vendita è da spedire", await ev(f"S.orders.get('{oid}').ship_status") == "da_spedire")
            await go("#/")
            check("la Home avvisa degli ordini da spedire", "1 ordine da spedire" in await page.inner_text("#app"))
            await go("#/vendite?stato=da_spedire")
            check("la lista da spedire mostra le carte da preparare", "Ash Blossom" in await page.inner_text("#app"))
            await page.click("[data-act=shipOrder]"); await W(300)
            await page.fill("#shf [name=t]", "RR123456789IT"); await page.click("#shf button.pri"); await W(800)
            o = await ev(f"S.orders.get('{oid}')")
            check("segnato come spedito con tracking", o["ship_status"] == "spedito" and o["tracking"] == "RR123456789IT" and o["shipped_date"], o)
            await go("#/vendite?stato=spedito"); await page.click("[data-act=deliverOrder]"); await W(800)
            check("segnato come consegnato", await ev(f"S.orders.get('{oid}').ship_status") == "consegnato")
            await go("#/")
            check("nessun avviso quando non ci sono ordini da spedire", "da spedire" not in await page.inner_text("#app"))
            await ev(f"orderView('{oid}')"); await W(300)
            await page.click("#ocancel"); await W(300); await page.click("[data-yes]"); await W(900)
        await step("Stato delle spedizioni", spedizioni)

        async def prezzo_richiesto():
            cid = await ev("[...S.copies.values()].find(c => c.status !== 'venduto').card_id")
            await go("#/c/" + cid)
            await page.click("a.askl"); await W(200); await page.fill("#askf input[name=p]", "12,50"); await page.click("#askf button.pri"); await W(700)
            await go("#/collezione"); await page.select_option("#fask", "si"); await W(400)
            rows = await page.query_selector_all("#ctab tbody tr")
            check("filtro 'Solo in vendita' mostra la carta con prezzo richiesto", len(rows) == 1, len(rows))
            await page.select_option("#fask", ""); await W(200)
        await step("Prezzo di vendita richiesto", prezzo_richiesto)

        async def selezione():
            await go("#/collezione")
            cks = await page.query_selector_all("[data-ck]")
            for c in cks[:3]:
                await c.check()
            await W(200)
            check("barra della selezione multipla", await page.is_visible("#selbar"))
            await page.click("[data-act=selLang]"); await W(250); await page.select_option("#sff select", "EN-US"); await page.click("#sff button.pri"); await W(900)
            n = await ev("[...S.copies.values()].filter(c => c.language === 'EN-US').length")
            check("lingua cambiata alle copie selezionate", n >= 3, n)
            twins = await ev("(() => { const a = [...S.copies.values()].filter(c => c.status !== 'venduto'); return a.some(x => a.some(y => x.id !== y.id && sameAvail(x, y) && (x.notes||'') === (y.notes||''))) })()")
            check("nessuna riga doppia dopo il cambio (copie unite)", not twins)
            cks = await page.query_selector_all("[data-ck]")
            for c in cks[:2]:
                await c.check()
            await page.click("[data-act=selLot]"); await W(250); await page.fill("#slf input[name=d]", "Lotto test"); await page.click("#slf button.pri"); await W(900)
            check("spostate in un nuovo lotto", "#/lotto/" in page.url and await ev("[...S.lots.values()].some(l => l.description === 'Lotto test')"))
        await step("Selezione multipla", selezione)

        async def modifica_carta():
            cid = await ev("[...S.cards.values()].find(c => c.cm_id && c.name.startsWith('Ash Blossom') && c.expansion === 'Maximum Crisis').id")
            await ev(f"editCardForm('{cid}')"); await W(300)
            await page.fill("#ecf input[name=rarity]", "Ultra Rare"); await page.click("#ecf button.pri"); await W(800)
            c = await ev(f"S.cards.get('{cid}')")
            check("cambiando la rarità il collegamento Cardmarket si ricalcola", c and c["rarity"] == "Ultra Rare" and not c.get("cm_id"), c)
            await ev(f"editCardForm('{cid}')"); await W(300)
            await page.fill("#ecf input[name=rarity]", "Secret Rare"); await page.click("#ecf button.pri"); await W(800)
            n = await ev("[...S.cards.values()].filter(c => c.name.startsWith('Ash Blossom') && c.expansion === 'Maximum Crisis' && c.rarity === 'Secret Rare').length")
            check("carte uguali vengono unite in una sola riga", n == 1, n)
        await step("Modifica di una carta", modifica_carta)

        async def cardtrader():
            await go("#/dati")
            await page.set_input_files("#imf", str(FIX / "ordine_cardtrader.csv")); await W(600)
            await page.click("#ct5"); await page.fill("#ctship", "1,20"); await W(150)
            check("riepilogo CardTrader: 40 + 5% + 1,20 = 43,20", "43,20" in await page.inner_text("#cttot"), await page.inner_text("#cttot"))
            await page.click("#impgo"); await W(900)
            fe = await ev("[...S.copies.values()].find(c => S.cards.get(c.card_id).name === 'Fiendsmith Engraver').buy_price")
            check("costo con commissione e spedizione (20 → 21,60)", abs(fe - 21.6) < 0.01, fe)
        await step("Import di un ordine CardTrader con +5%", cardtrader)

        async def immagini():
            cid = await ev("[...S.cards.values()].find(c => c.image_url).id")
            await go("#/c/" + cid); await page.click(".cimg"); await W(300)
            await page.click("#imgdel"); await W(600)
            await ev(f"imgTried.clear(); queueImages(['{cid}'])"); await W(1500)
            check("un'immagine rimossa non viene rimessa in automatico", not await ev(f"S.cards.get('{cid}').image_url"))
        await step("Immagini", immagini)

        async def pagine():
            hashes = ["#/", "#/g/Yu-Gi-Oh!", "#/collezione", "#/vendite", "#/lotti", "#/giacenze", "#/guadagni", "#/statistiche", "#/vendite?stato=da_spedire", "#/dati", "#/collega",
                      "#/c/" + await ev("[...S.cards.keys()][0]"), "#/lotto/" + await ev("[...S.lots.keys()][0]")]
            bad = []
            for h in hashes:
                await go(h)
                txt = await page.inner_text("#app")
                if "Errore di visualizzazione" in txt or "non trovata" in txt.lower():
                    bad.append(h)
            check("tutte le pagine si aprono senza errori", not bad, bad)
            await go("#/statistiche"); st = await page.inner_text("#app")
            check("statistiche: tempo in magazzino, espansioni e lotti", "Quanto ci metti a vendere" in st and "Espansioni che rendono di più" in st and "Lotti a confronto" in st, st[:300])
            data = await ev("(() => { const s = salesStats(''); return {q: s.qty, b: s.buckets.reduce((t, b) => t + b.n, 0), h: s.held.length} })()")
            check("statistiche: le fasce di tempo contano tutte le copie con date", data["b"] == data["h"] and data["q"] > 0, data)
            for h in ["#/", "#/collezione"]:
                await page.set_viewport_size({"width": 390, "height": 800}); await go(h)
                check(f"vista da telefono {h}", "Errore" not in await page.inner_text("#app"))
            await page.set_viewport_size({"width": 1280, "height": 900})
            cid = await ev("[...S.cards.values()].find(c => c.cm_id || cmFor(c))?.id || [...S.cards.keys()][0]")
            seen = []
            for h in ["#/", "#/collezione", "#/giacenze", "#/lotti", f"#/c/{cid}"]:
                await go(h); t = await page.inner_text("#app")
                if "Mercato" in t or "Trend" in t or "Media 30" in t or "prezzo di mercato" in t.lower(): seen.append(h)
            check("nessun prezzo di mercato Cardmarket mostrato", not seen, seen)
        await step("Tutte le pagine", pagine)

        async def guadagni():
            data = await ev("(() => { index(); const t = totals(); const rows = monthly(''); return {net: t.net, spent: t.spent, mNet: rows.reduce((s,r)=>s+r.net,0), mSpent: rows.reduce((s,r)=>s+r.spent,0)} })()")
            check("Guadagni mensili coerenti con i totali della Home", abs(data["net"] - data["mNet"]) < 0.01 and abs(data["spent"] - data["mSpent"]) < 0.01, data)
        await step("Coerenza dei conti", guadagni)

        async def backup():
            await go("#/dati")
            async with page.expect_download() as dl:
                await page.click("[data-act=exportJson]")
            f = tmp / "bk.json"; await (await dl.value).save_as(f)
            j = json.loads(f.read_text())
            counts = await ev("({cards: S.cards.size, copies: S.copies.size, lots: S.lots.size, orders: S.orders.size})")
            check("il backup JSON contiene tutto", {k: len(j[k]) for k in counts} == counts, counts)
            subprocess.run(f"gzip -kf9 '{f}' && openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -salt -in '{f}.gz' -out '{f}.gz.enc' -pass pass:segreta123", shell=True, check=True)
            await page.click("[data-act=deleteAll]"); await W(200); await page.fill("#delc", "elimina");
            async with page.expect_download():
                await page.click("#delgo")
            await W(900)
            check("Elimina tutto svuota l'archivio", await ev("S.cards.size + S.copies.size") == 0)
            await page.click("[data-act=undo]"); await W(1200)
            check("Annulla ripristina l'archivio eliminato", await ev("({cards: S.cards.size, copies: S.copies.size, lots: S.lots.size, orders: S.orders.size})") == counts)
            await ev("commit('svuota', async tx => { await tx.remove('copies',[...S.copies.keys()]); await tx.remove('orders',[...S.orders.keys()]); await tx.remove('lots',[...S.lots.keys()]); await tx.remove('cards',[...S.cards.keys()]); })"); await W(600)
            await go("#/dati")
            await page.set_input_files("#jsf", str(f) + ".gz.enc"); await W(400)
            await page.fill("#pwf input", "sbagliata"); await page.click("#pwf button.pri"); await W(1500)
            check("password sbagliata: messaggio chiaro, niente importato", "Password sbagliata" in await page.inner_text("#toast") and await ev("S.cards.size") == 0)
            await page.set_input_files("#jsf", str(f) + ".gz.enc"); await W(400)
            await page.fill("#pwf input", "segreta123"); await page.click("#pwf button.pri"); await W(2000)
            check("il backup cifrato si ripristina con la password giusta", await ev("({cards: S.cards.size, copies: S.copies.size, lots: S.lots.size, orders: S.orders.size})") == counts)
            await page.set_input_files("#jsf", str(f)); await W(1200)
            check("ripristinare due volte non crea doppioni", await ev("({cards: S.cards.size, copies: S.copies.size, lots: S.lots.size, orders: S.orders.size})") == counts)
        await step("Backup e ripristino", backup)

        async def vetrina():
            gp = await ctx.new_page(); gerr = []
            gp.on("pageerror", lambda e: gerr.append(str(e)))
            rows = [{"card_id": "a1", "game": "Yu-Gi-Oh!", "expansion": "Maximum Crisis", "name": "Ash Blossom & Joyous Spring", "rarity": "Secret Rare", "image_url": None, "qty": 3, "conditions": "NM,EX", "languages": "EN-EU"},
                    {"card_id": "b2", "game": "Pokémon", "expansion": "151", "name": "Charizard ex", "rarity": "Double Rare", "image_url": None, "qty": 1, "conditions": "NM", "languages": "IT"}]
            calls = []
            async def groute(r):
                u = r.request.url
                if "test.supabase.co" in u:
                    calls.append((r.request.method, u, r.request.post_data))
                    h = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*"}
                    if r.request.method == "OPTIONS":
                        return await r.fulfill(status=200, headers=h, body="")
                    ok = "A" * 30 in (r.request.post_data or "")
                    info = [{"title": "Vetrina di prova", "whatsapp": "333 1234567", "telegram": "dsr_carte"}]
                    body = (rows if "guest_stock" in u else info) if ok else []
                    return await r.fulfill(status=200, headers={**h, "Content-Type": "application/json"}, body=json.dumps(body))
                return await route(r)
            await gp.route("**/*", groute)
            await gp.goto(URL + "#/vetrina/" + "A" * 30 + "?u=https%3A%2F%2Ftest.supabase.co&k=chiave-anon"); await gp.wait_for_timeout(1500)
            txt = await gp.inner_text("#app")
            check("la vetrina si apre senza accesso e mostra le carte disponibili", "Ash Blossom" in txt and "Charizard ex" in txt, txt[:200])
            check("la vetrina non mostra prezzi", "€" not in txt, txt[:300])
            check("la vetrina non ha pulsanti per modificare", not await gp.query_selector("[data-act]"))
            await gp.fill("#gq", "charizard"); await gp.wait_for_timeout(400)
            t2 = await gp.inner_text("#glist")
            check("ricerca nella vetrina", "Charizard" in t2 and "Ash Blossom" not in t2, t2[:200])
            await gp.fill("#gq", "carta che non ho"); await gp.wait_for_timeout(400)
            check("messaggio chiaro se la carta non c'è", "non è disponibile" in await gp.inner_text("#glist"))
            await gp.fill("#gq", ""); await gp.wait_for_timeout(400)
            check("la vetrina mostra il suo nome", "Vetrina di prova" in await gp.inner_text("#app"))
            await gp.click("[data-want='a1']"); await gp.wait_for_timeout(200)
            await gp.select_option("[data-wq='a1']", "2"); await gp.click("[data-want='b2']"); await gp.wait_for_timeout(200)
            bar = await gp.inner_text("#gbar")
            check("barra della richiesta con 2 carte", "2 carte" in bar and "3 copie" in bar, bar)
            await gp.evaluate("() => { window.__open = []; window.open = function (u){ window.__open.push(String(u)); return null; }; }")
            await gp.click("#gbar [data-g=wa]"); await gp.wait_for_timeout(200)
            opened = await gp.evaluate("window.__open")
            from urllib.parse import unquote
            u0 = unquote(opened[0]) if opened else ""
            check("WhatsApp si apre con il messaggio già scritto", u0.startswith("https://wa.me/393331234567?text=") and "2× Ash Blossom" in u0 and "1× Charizard ex" in u0, u0[:160])
            await gp.click("#gbar [data-g=tg]"); await gp.wait_for_timeout(200)
            check("Telegram apre la chat del proprietario", (await gp.evaluate("window.__open"))[-1] == "https://t.me/dsr_carte")
            await gp.click("#gbar [data-g=clear]"); await gp.wait_for_timeout(200)
            check("la richiesta si può svuotare", not await gp.query_selector("#gbar"))
            only_rpc = all("rpc/guest_stock" in c[1] or "rpc/guest_info" in c[1] for c in calls if c[0] != "OPTIONS")
            check("la vetrina usa solo la funzione di sola lettura", calls and only_rpc, calls[:3])
            await gp.goto(URL + "#/vetrina/" + "B" * 30 + "?u=https%3A%2F%2Ftest.supabase.co&k=chiave-anon"); await gp.wait_for_timeout(1200)
            check("un codice sbagliato non mostra nessuna carta", "Nessuna carta disponibile" in await gp.inner_text("#glist"))
            check("nessun errore JavaScript nella vetrina", not gerr, gerr[:3])
            await gp.close()
        await step("Vetrina di sola lettura (link guest)", vetrina)

        print("\n▶ Errori JavaScript durante i test")
        check("nessun errore JavaScript nella pagina", not errors, errors[:5])
        await browser.close()

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} controlli superati")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
