// Analisi CardTrader: per le carte Yu-Gi-Oh!, One Piece e Pokémon dell'utente cerca la stampa su CardTrader
// (immagine, rarità, numero) e salva le proposte in card_proposals. Non modifica le carte.
// Per i Pokémon che CardTrader non trova prova il database pubblico PokémonTCG (api.pokemontcg.io).
// Segreto richiesto: CARDTRADER_TOKEN (Edge Functions → Secrets).
import { createClient } from "jsr:@supabase/supabase-js@2";

const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type", "Access-Control-Allow-Methods": "POST, OPTIONS" };
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { ...CORS, "Content-Type": "application/json" } });
const API = "https://api.cardtrader.com/api/v2";
const GAMES: Record<string, RegExp> = { "Yu-Gi-Oh!": /yu-?gi-?oh/i, "One Piece": /one\s*piece/i, "Pokémon": /pok[eé]mon/i };
type Bp = Record<string, unknown> & { id: number; name: string; version?: string; expansion_id: number; image_url?: string; card_market_ids?: number[] };

const fold = (s: unknown) => String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/&/g, " and ").replace(/[^a-z0-9]+/g, " ").trim();
const baseName = (n: string) => fold(String(n).replace(/\s*\([^()]*\)\s*$/, "").replace(/\s*\[[^\]]*\]\s*$/, ""));
const numKey = (s: unknown) => { const m = String(s ?? "").toUpperCase().match(/([A-Z]{1,5}\d{0,2}-?[A-Z]{0,2})?\s*0*(\d{1,4}[A-Z]?)(?:\s*\/\s*\d+)?\s*$/); return m ? (m[1] ? m[1].replace(/[^A-Z0-9]/g, "") + "-" : "") + m[2] : ""; };
const numOnly = (s: unknown) => (String(s ?? "").match(/0*(\d{1,4})[A-Z]?(?:\s*\/\s*\d+)?\s*$/i) || [])[1] || "";
const cardNum = (name: string) => { const v = String(name).match(/\(([^()]*)\)\s*$/)?.[1] || ""; const part = v.split("|").map((x) => x.trim()).find((x) => /\d/.test(x) && !/^©/.test(x)); return part ? part.replace(/^No\.?\s*/i, "") : ""; };
/** "mega" corrisponde a "mega evolution" ma non a "megalo cannon": confronto per parole intere */
const hasWords = (a: string, b: string) => b.length > 2 && (" " + a + " ").includes(" " + b + " ");
const expKey = (n: string) => fold(n).replace(/\b(the|ocg|tcg)\b/g, " ").replace(/\s+/g, " ").trim();
/** primo valore stringa con chiave che contiene `part` (cerca anche negli oggetti annidati) */
function findProp(o: unknown, part: RegExp, depth = 0): string {
  if (!o || typeof o !== "object" || depth > 3) return "";
  for (const [k, v] of Object.entries(o as Record<string, unknown>)) {
    if (part.test(k) && (typeof v === "string" || typeof v === "number") && String(v).trim()) return String(v).trim();
  }
  for (const v of Object.values(o as Record<string, unknown>)) { const r = findProp(v, part, depth + 1); if (r) return r; }
  return "";
}
const imgOf = (b: Bp) => {
  const im = (b as Record<string, any>).image;
  const u = im?.show?.url || im?.url || (b.image_url as string) || "";
  return u ? (u.startsWith("http") ? u : "https://www.cardtrader.com" + u) : "";
};

/** ripiego per i Pokémon che CardTrader non trova: database pubblico PokémonTCG (carte inglesi, scansioni ufficiali) */
const PTCG = "https://api.pokemontcg.io/v2/cards";
type Ptcg = { id: string; name: string; number: string; rarity?: string; set: { id: string; name: string; printedTotal?: number; total?: number }; images?: { small?: string; large?: string } };
async function ptcgFind(c: Record<string, unknown>): Promise<{ hit: Ptcg | null; n: number }> {
  const raw = String(c.name).replace(/\s*\([^()]*\)\s*$/, "").replace(/"/g, "").trim();
  const num = numOnly(cardNum(String(c.name)));
  const tot = (String(c.name).match(/\/\s*0*(\d+)\s*\)?\s*$/) || [])[1];
  const key = Deno.env.get("POKEMONTCG_API_KEY");
  const get = async (q: string): Promise<Ptcg[]> => {
    let last = "";
    for (let i = 0; i < 3; i++) {   // il servizio a volte risponde 500 o va in timeout: riprova con una pausa
      if (i) await new Promise((s) => setTimeout(s, 1500 * i));
      try {
        const r = await fetch(`${PTCG}?q=${encodeURIComponent(q)}&pageSize=250&select=id,name,number,rarity,set,images`, { headers: key ? { "X-Api-Key": key } : {}, signal: AbortSignal.timeout(12000) });
        if (r.status >= 500 || r.status === 429) { last = String(r.status); continue; }
        if (!r.ok) throw new Error(`PokémonTCG: ${r.status}`);
        return ((await r.json()).data ?? []).filter((x: Ptcg) => fold(x.name) === fold(raw));
      } catch (e) { if (String((e as Error)?.message).startsWith("PokémonTCG")) throw e; last = String((e as Error)?.name || e); }
    }
    throw new Error(`PokémonTCG: ${last} (3 tentativi)`);
  };
  const rar = String(c.rarity ?? "").replace(/"/g, "").trim();
  // dalla ricerca più stretta alla più larga: numero → rarità → solo nome
  let list = num ? await get(`name:"${raw}" number:${num}`) : [];
  if (!list.length && rar) list = await get(`name:"${raw}" rarity:"${rar}"`);
  if (!list.length) list = await get(`name:"${raw}"`);
  const k = expKey(String(c.expansion ?? "")).replace(/^sv /, "scarlet and violet ").replace(/^swsh /, "sword and shield ").replace(/^sm /, "sun and moon ");
  const pick = (f: (x: Ptcg) => boolean) => { const y = list.filter(f); if (y.length) list = y; };
  if (list.length > 1 && k) { const ex = list.filter((x) => expKey(x.set.name) === k); if (ex.length) list = ex; else pick((x) => { const e = expKey(x.set.name); return hasWords(e, k) || hasWords(k, e); }); }
  if (list.length > 1 && tot) pick((x) => String(x.set.printedTotal) === tot);
  if (list.length > 1 && c.rarity) pick((x) => fold(x.rarity) === fold(c.rarity));
  return { hit: list.length === 1 ? list[0] : null, n: list.length };
}

let cache: { at: number; games: Record<string, number>; exps: { id: number; game_id: number; name: string; code: string }[] } | null = null;
async function ct(path: string, token: string) {
  for (let i = 0; i < 3; i++) {
    const r = await fetch(API + path, { headers: { Authorization: `Bearer ${token}` } });
    if (r.status === 429) { await new Promise((s) => setTimeout(s, 1500)); continue; }
    if (!r.ok) throw new Error(`CardTrader ${path}: ${r.status}`);
    return await r.json();
  }
  throw new Error(`CardTrader ${path}: troppe richieste`);
}
async function catalog(token: string) {
  if (cache && Date.now() - cache.at < 30 * 60_000) return cache;
  const games = await ct("/games", token), list = Array.isArray(games) ? games : games.array ?? [];
  const g: Record<string, number> = {};
  for (const [name, re] of Object.entries(GAMES)) { const x = list.find((y: Record<string, string>) => re.test(y.name) || re.test(y.display_name)); if (x) g[name] = x.id; }
  const ex = await ct("/expansions", token);
  cache = { at: Date.now(), games: g, exps: (Array.isArray(ex) ? ex : ex.array ?? []).filter((e: { game_id: number }) => Object.values(g).includes(e.game_id)) };
  return cache;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  try {
    const token = Deno.env.get("CARDTRADER_TOKEN");
    if (!token) return json({ error: "Manca il token CardTrader (CARDTRADER_TOKEN) nei segreti di Supabase." }, 500);
    const db = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, { auth: { persistSession: false } });
    const jwt = (req.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
    const { data: ud } = await db.auth.getUser(jwt);
    const user = ud?.user; if (!user) return json({ error: "Accesso richiesto." }, 401);
    const body = await req.json().catch(() => ({}));
    const offset = Math.max(0, Number(body.offset) || 0), limit = Math.min(40, Math.max(1, Number(body.limit) || 12));

    const cat = await catalog(token);
    // carte dell'utente raggruppate per (gioco, espansione)
    const cards: Record<string, unknown>[] = [];
    for (let from = 0; ; from += 1000) {
      const { data, error } = await db.from("cards").select("id,game,expansion,name,rarity,image_url,cm_id").eq("user_id", user.id).in("game", Object.keys(cat.games)).range(from, from + 999);
      if (error) throw error; cards.push(...(data ?? [])); if (!data || data.length < 1000) break;
    }
    const groups = [...new Set(cards.map((c) => `${c.game}\u0001${c.expansion ?? ""}`))].sort();
    const slice = groups.slice(offset, offset + limit);
    const rows: Record<string, unknown>[] = [], info: Record<string, unknown> = { games: cat.games, expansions: cat.exps.length, offset, groups: groups.length };
    const unmatched: string[] = [], errors: string[] = [];
    for (const gk of slice) {
      const [game, expansion] = gk.split("\u0001");
      try {
      const gid = cat.games[game], mine = cards.filter((c) => c.game === game && (c.expansion ?? "") === expansion);
      const k = expKey(expansion);
      let exps = cat.exps.filter((e) => e.game_id === gid && expKey(e.name) === k);
      if (!exps.length && k) exps = cat.exps.filter((e) => e.game_id === gid && (hasWords(expKey(e.name), k) || hasWords(k, expKey(e.name))))
        .sort((a, b) => Number(expKey(b.name).startsWith(k + " ")) - Number(expKey(a.name).startsWith(k + " ")) || a.name.length - b.name.length);
      if (!exps.length) {
        unmatched.push(`${game} · ${expansion}`);
        for (const c of mine) rows.push({ card_id: c.id, user_id: user.id, status: "espansione_non_trovata", candidates: 0, analyzed_at: new Date().toISOString() });
        continue;
      }
      const bps: Bp[] = [];
      for (const e of exps.slice(0, 4)) {
        try { const r = await ct(`/blueprints/export?expansion_id=${e.id}`, token); bps.push(...(Array.isArray(r) ? r : r.array ?? []).map((b: Bp) => ({ ...b, _exp: e.name }))); }
        catch (err) { errors.push(`${game} · ${expansion}: ${String((err as Error)?.message || err)}`); }
      }
      if (!bps.length){ for (const c of mine) rows.push({ card_id: c.id, user_id: user.id, status: "non_trovata", candidates: 0, ct_expansion: exps[0].name, analyzed_at: new Date().toISOString() }); continue; }
      if (!info.sample && bps.length) info.sample = bps.slice(0, 2);
      for (const c of mine) {
        const bn = baseName(String(c.name));
        let cand = bps.filter((b) => baseName(b.name) === bn);
        const num = cardNum(String(c.name));
        const byCm = c.cm_id ? bps.filter((b) => (b.card_market_ids ?? []).includes(Number(c.cm_id))) : [];
        if (byCm.length) cand = byCm;
        else if (num) { const nk = numKey(num), no = numOnly(num);
          const byNum = bps.filter((b) => { const cn = findProp((b as Record<string, unknown>).fixed_properties, /collector/i); return cn && (numKey(cn) === nk || (no && numOnly(cn) === no)); });
          const both = byNum.filter((b) => cand.includes(b));
          if (both.length) cand = both; else if (!cand.length && byNum.length === 1) cand = byNum; }
        if (cand.length > 1 && c.cm_id) { const f = cand.filter((b) => (b.card_market_ids ?? []).includes(Number(c.cm_id))); if (f.length) cand = f; }
        if (cand.length > 1 && c.rarity) { const f = cand.filter((b) => fold(findProp((b as Record<string, unknown>).fixed_properties ?? b, /rarity/i)) === fold(c.rarity)); if (f.length) cand = f; }
        if (cand.length > 1) { const v = String(c.name).match(/\(([^()]*)\)\s*$/)?.[1]; if (v && !num) { const f = cand.filter((b) => fold(b.version).includes(fold(v))); if (f.length) cand = f; } }
        if (cand.length > 1) { const f = cand.filter((b) => !b.version); if (f.length === 1) cand = f; }
        const b = cand[0], one = cand.length === 1;
        const rars = [...new Set(cand.map((x) => findProp((x as Record<string, unknown>).fixed_properties ?? x, /rarity/i)).filter(Boolean))];
        rows.push({ card_id: c.id, user_id: user.id, status: !cand.length ? "non_trovata" : one ? "trovata" : "ambigua", candidates: cand.length,
          ct_blueprint: one ? b.id : null, ct_expansion: b ? String(b._exp) : exps[0].name, ct_name: b ? b.name : null, ct_version: one ? (b.version ?? null) : null,
          image_url: one ? imgOf(b) || null : null, rarity: one ? findProp((b as Record<string, unknown>).fixed_properties ?? b, /rarity/i) || null : rars.length === 1 ? rars[0] : null,
          number: one ? findProp((b as Record<string, unknown>).fixed_properties ?? b, /collector/i) || null : null, analyzed_at: new Date().toISOString() });
      }
      } catch (err) { errors.push(`${game} · ${expansion}: ${String((err as Error)?.message || err)}`); }
    }
    // Pokémon non trovati o incerti su CardTrader → PokémonTCG
    const byId = new Map(cards.map((c) => [c.id, c]));
    for (const row of rows) {
      const c = byId.get(row.card_id); if (!c || c.game !== "Pokémon" || row.status === "trovata") continue;
      try {
        const { hit } = await ptcgFind(c);
        if (hit) Object.assign(row, { status: "trovata", source: "pokemontcg", candidates: 1, ct_blueprint: null, ct_expansion: hit.set.name, ct_name: hit.name, ct_version: null,
          image_url: hit.images?.large || hit.images?.small || null, rarity: hit.rarity || null, number: hit.set.printedTotal ? `${hit.number}/${hit.set.printedTotal}` : hit.number });
      } catch (err) { errors.push(`Pokémon · ${c.name}: ${String((err as Error)?.message || err)}`); }
      await new Promise((s) => setTimeout(s, 120));
    }
    for (const row of rows) if (!row.source) row.source = "cardtrader";
    for (let i = 0; i < rows.length; i += 500) { const { error } = await db.from("card_proposals").upsert(rows.slice(i, i + 500)); if (error) throw error; }
    info.unmatched = unmatched; info.errors = errors; info.saved = rows.length;
    await db.from("ct_runs").insert({ user_id: user.id, info });
    const next = offset + slice.length;
    return json({ ok: true, done: next >= groups.length, next, total: groups.length, saved: rows.length });
  } catch (e) {
    return json({ error: String((e as Error)?.message || e) }, 500);
  }
});
