// Vetrina DSR Archive: riceve la richiesta del carrello, la salva e la manda su Telegram.
// Segreti (pannello Supabase → Edge Functions → Secrets): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
import { createClient } from "jsr:@supabase/supabase-js@2";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { ...CORS, "Content-Type": "application/json" } });
const clean = (v: unknown, max: number) => String(v ?? "").replace(/[\u0000-\u001f\u007f]+/g, " ").replace(/\s+/g, " ").trim().slice(0, max);
const html = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const MAX_PER_HOUR = 10, MAX_ITEMS = 50;

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ error: "Metodo non consentito." }, 405);
  let body: Record<string, unknown>;
  try { body = await req.json(); } catch { return json({ error: "Richiesta non valida." }, 400); }

  const token = String(body.token ?? "");
  const name = clean(body.name, 60), contact = clean(body.contact, 80), note = clean(body.note, 300);
  const items = Array.isArray(body.items) ? body.items.slice(0, MAX_ITEMS) : [];
  const site = /^https:\/\/[^\s"<>]+$/.test(String(body.site ?? "")) ? String(body.site) : "";
  if (!/^[A-Za-z0-9_-]{24,}$/.test(token)) return json({ error: "Link della vetrina non valido." }, 400);
  if (!name || !contact) return json({ error: "Scrivi nome e contatto." }, 400);
  if (!items.length) return json({ error: "Il carrello è vuoto." }, 400);

  const db = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, { auth: { persistSession: false } });
  const { data: link } = await db.from("share_links").select("user_id,title").eq("token", token).maybeSingle();
  if (!link) return json({ error: "Questo link della vetrina non è più attivo." }, 404);

  const since = new Date(Date.now() - 3600_000).toISOString();
  const { count } = await db.from("vetrina_requests").select("id", { count: "exact", head: true }).eq("user_id", link.user_id).gte("created_at", since);
  if ((count ?? 0) >= MAX_PER_HOUR) return json({ error: "Troppe richieste in poco tempo: riprova più tardi." }, 429);

  // solo carte davvero disponibili, con quantità limitate alle copie presenti
  const { data: stock, error: se } = await db.rpc("guest_stock", { p_token: token });
  if (se) return json({ error: "Impossibile leggere le carte disponibili." }, 500);
  const byId = new Map((stock ?? []).map((r: Record<string, unknown>) => [String(r.card_id), r]));
  const lines: { card_id: string; name: string; expansion: string; rarity: string; qty: number }[] = [];
  for (const it of items as Record<string, unknown>[]) {
    const r = byId.get(String(it?.card_id)) as Record<string, unknown> | undefined;
    if (!r || lines.some((l) => l.card_id === r.card_id)) continue;
    const qty = Math.max(1, Math.min(Number(r.qty) || 1, Math.floor(Number(it.qty) || 1)));
    lines.push({ card_id: String(r.card_id), name: String(r.name ?? ""), expansion: String(r.expansion ?? ""), rarity: String(r.rarity ?? ""), qty });
  }
  if (!lines.length) return json({ error: "Le carte scelte non sono più disponibili." }, 409);
  const total = lines.reduce((a, l) => a + l.qty, 0);

  const { data: ins, error: ie } = await db.from("vetrina_requests")
    .insert({ user_id: link.user_id, token, name, contact, note: note || null, items: lines, total_qty: total }).select("id").single();
  if (ie) return json({ error: "Impossibile salvare la richiesta." }, 500);

  let notified = false;
  const bot = Deno.env.get("TELEGRAM_BOT_TOKEN"), chat = Deno.env.get("TELEGRAM_CHAT_ID");
  if (bot && chat) {
    const text = [
      `🛒 <b>Nuova richiesta dalla vetrina</b>${link.title ? " “" + html(link.title) + "”" : ""}`,
      `👤 ${html(name)}`, `📞 ${html(contact)}`, "",
      ...lines.map((l) => `• <b>${l.qty}×</b> ${html(l.name)}${l.expansion || l.rarity ? " — " + html([l.expansion, l.rarity].filter(Boolean).join(" · ")) : ""}`),
      "", `Totale: ${lines.length} ${lines.length === 1 ? "carta" : "carte"}, ${total} ${total === 1 ? "copia" : "copie"}`,
      ...(note ? [`📝 ${html(note)}`] : []),
      ...(site ? ["", `<a href="${html(site)}#/richieste">Apri le richieste nell'archivio</a>`] : []),
    ].join("\n");
    try {
      const r = await fetch(`https://api.telegram.org/bot${bot}/sendMessage`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: chat, text, parse_mode: "HTML", disable_web_page_preview: true }),
      });
      notified = r.ok;
    } catch { notified = false; }
    await db.from("vetrina_requests").update({ notified }).eq("id", ins.id);
  }
  return json({ ok: true, id: ins.id, notified });
});
