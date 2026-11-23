# Controlli automatici

`run_tests.py` apre `index.html` in Chromium (modalità senza account, dati nel browser) e prova:
import Excel, CSV Cardmarket (anche come lotto) e CardTrader (+5%), aggiunta carte dai suggerimenti,
doppio clic, vendite e annullamenti, prezzo richiesto, selezione multipla, modifica e unione carte,
immagini, tutte le pagine (anche da telefono), coerenza dei conti, backup cifrato e ripristino.

Il catalogo Cardmarket è sostituito da `fixtures/cm_*.json` (un estratto del listino vero), così i test
non dipendono da internet. Su GitHub girano da soli a ogni modifica (workflow "Controlli automatici").

In locale: `pip install playwright && python -m playwright install chromium && python tests/run_tests.py`
