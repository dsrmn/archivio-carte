#!/usr/bin/env python3
"""
Backup dell'archivio DSR Archive: legge tutte le tabelle da Supabase e le salva
in un file JSON con lo stesso formato del "Backup JSON" della web-app.
Usa la chiave service_role (secret SUPABASE_SERVICE_KEY), che legge i dati
anche con le regole di sicurezza attive. Il file viene poi cifrato dal workflow.
"""
import json, os, re, sys, urllib.request, datetime

url = os.environ.get("SUPABASE_URL", "").strip().strip('"\'')
key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip().strip('"\'')
out = sys.argv[1] if len(sys.argv) > 1 else "backup.json"
if not url or not key:
    sys.exit("Mancano SUPABASE_URL o SUPABASE_SERVICE_KEY")
m = re.match(r"(https?://[^/]+)", url if "://" in url else "https://" + url)
base = m.group(1)


def fetch(table, order):
    rows, start = [], 0
    while True:
        req = urllib.request.Request(f"{base}/rest/v1/{table}?select=*&order={order}",
                                     headers={"apikey": key, "Authorization": f"Bearer {key}",
                                              "Range-Unit": "items", "Range": f"{start}-{start + 999}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            chunk = json.load(r)
        rows += chunk
        if len(chunk) < 1000:
            return rows
        start += 1000


data = {"app": "DSR Archive", "version": 1, "exported_at": datetime.datetime.utcnow().isoformat() + "Z"}
for t in ("cards", "lots", "orders", "copies"):
    try:
        data[t] = fetch(t, "created_at")
    except urllib.error.HTTPError as e:
        if t == "orders" and e.code in (400, 404):
            data[t] = []
        else:
            raise
try:
    s = fetch("settings", "user_id")
    data["settings"] = s[0]["data"] if s else None
except Exception:
    data["settings"] = None

with open(out, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
print(f"Backup: {len(data['cards'])} carte, {len(data['copies'])} righe di copie, {len(data['lots'])} lotti, {len(data['orders'])} vendite")
if not data["cards"] and not data["copies"]:
    sys.exit("Il backup è vuoto: controlla che SUPABASE_SERVICE_KEY sia la chiave service_role")
