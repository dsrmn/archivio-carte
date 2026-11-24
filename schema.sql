-- =============================================================
-- CardArchive — schema per Supabase
-- Supabase → SQL Editor → New query → incolla tutto → Run
-- Si può rieseguire senza danni (usa "if not exists").
-- =============================================================

create extension if not exists pgcrypto;

-- Una riga = uno "slot" carta (stesso gioco + espansione + nome + rarità)
create table if not exists public.cards (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references auth.users(id) on delete cascade,
  game        text not null,
  expansion   text not null default '',
  name        text not null,
  rarity      text not null default '',
  image_url   text,
  created_at  timestamptz not null default now()
);
create unique index if not exists cards_slot_unique
  on public.cards (user_id, lower(game), lower(expansion), lower(name), lower(rarity));

-- Lotti: solo descrizione, data e prezzo totale (il costo resta condiviso)
create table if not exists public.lots (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null default auth.uid() references auth.users(id) on delete cascade,
  description  text not null,
  buy_date     date,
  total_price  numeric(12,2) not null default 0,
  created_at   timestamptz not null default now()
);

-- Copie: ogni acquisto (o parte venduta) di una carta
create table if not exists public.copies (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references auth.users(id) on delete cascade,
  card_id     uuid not null references public.cards(id) on delete cascade,
  lot_id      uuid references public.lots(id) on delete set null,
  qty         integer not null default 1 check (qty > 0),
  condition   text,
  edition     text,
  language    text,
  buy_date    date,
  buy_price   numeric(12,2),          -- prezzo unitario (vuoto se la carta viene da un lotto)
  status      text not null default 'disponibile' check (status in ('disponibile','venduto')),
  sell_date   date,
  sell_price  numeric(12,2),          -- incasso totale per le copie di questa riga
  platform    text,
  notes       text,
  created_at  timestamptz not null default now()
);
create index if not exists copies_card_idx on public.copies (card_id);
create index if not exists copies_lot_idx  on public.copies (lot_id);

-- Ogni utente vede e modifica solo i propri dati
alter table public.cards  enable row level security;
alter table public.lots   enable row level security;
alter table public.copies enable row level security;

drop policy if exists cards_own  on public.cards;
drop policy if exists lots_own   on public.lots;
drop policy if exists copies_own on public.copies;

create policy cards_own  on public.cards  for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy lots_own   on public.lots   for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy copies_own on public.copies for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

-- =============================================================
-- Immagini delle carte (Supabase Storage)
-- =============================================================
insert into storage.buckets (id, name, public)
values ('card-images', 'card-images', true)
on conflict (id) do nothing;

drop policy if exists card_images_read   on storage.objects;
drop policy if exists card_images_insert on storage.objects;
drop policy if exists card_images_update on storage.objects;
drop policy if exists card_images_delete on storage.objects;

create policy card_images_read on storage.objects for select
  using (bucket_id = 'card-images');
create policy card_images_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'card-images' and (storage.foldername(name))[1] = auth.uid()::text);
create policy card_images_update on storage.objects for update to authenticated
  using (bucket_id = 'card-images' and (storage.foldername(name))[1] = auth.uid()::text);
create policy card_images_delete on storage.objects for delete to authenticated
  using (bucket_id = 'card-images' and (storage.foldername(name))[1] = auth.uid()::text);

-- =============================================================
-- Vendite come ordini + impostazioni (commissioni, spedizioni)
-- =============================================================
create table if not exists public.orders (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null default auth.uid() references auth.users(id) on delete cascade,
  sell_date         date,
  platform          text,
  buyer             text,
  shipping_charged  numeric(12,2) not null default 0,   -- spedizione pagata dall'acquirente
  shipping_cost     numeric(12,2) not null default 0,   -- tuo costo di spedizione + imballaggio
  fee               numeric(12,2) not null default 0,   -- commissione della piattaforma
  notes             text,
  created_at        timestamptz not null default now()
);
alter table public.copies add column if not exists order_id uuid references public.orders(id) on delete set null;
create index if not exists copies_order_idx on public.copies (order_id);

create table if not exists public.settings (
  user_id     uuid primary key default auth.uid() references auth.users(id) on delete cascade,
  data        jsonb not null default '{}'::jsonb,
  updated_at  timestamptz not null default now()
);

alter table public.orders   enable row level security;
alter table public.settings enable row level security;
drop policy if exists orders_own   on public.orders;
drop policy if exists settings_own on public.settings;
create policy orders_own   on public.orders   for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy settings_own on public.settings for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

-- =============================================================
-- Collegamento delle carte al catalogo Cardmarket
-- =============================================================
alter table public.cards add column if not exists cm_id bigint;   -- idProduct Cardmarket (-1 = nessuna corrispondenza)

-- =============================================================
-- Prezzo di vendita richiesto per copia
-- =============================================================
alter table public.copies add column if not exists ask_price numeric(12,2);   -- in vendita a (per copia)
alter table public.copies add column if not exists ask_date  date;            -- da quando è in vendita a quel prezzo

-- =============================================================
-- Posizione delle copie e stato delle spedizioni
-- =============================================================
alter table public.copies add column if not exists location     text;   -- dove si trova (raccoglitore, scatola, pagina)
alter table public.orders add column if not exists ship_status  text;   -- da_spedire | spedito | consegnato (vuoto = ordine vecchio)
alter table public.orders add column if not exists tracking     text;   -- codice di tracciamento
alter table public.orders add column if not exists shipped_date date;   -- data di spedizione

-- =============================================================
-- Vetrina: link di sola lettura con le carte disponibili
-- Chi ha il link (con il codice segreto) vede solo nome, espansione,
-- rarità, immagine, quantità, condizioni e lingue. Niente prezzi.
-- =============================================================
create table if not exists public.share_links (
  token       text primary key,
  user_id     uuid not null default auth.uid() references auth.users(id) on delete cascade,
  created_at  timestamptz not null default now()
);
alter table public.share_links add column if not exists title         text;     -- nome della vetrina
alter table public.share_links add column if not exists whatsapp      text;     -- numero per le richieste
alter table public.share_links add column if not exists telegram      text;     -- username per le richieste
alter table public.share_links add column if not exists show_location boolean not null default false;
alter table public.share_links enable row level security;
drop policy if exists share_links_own on public.share_links;
create policy share_links_own on public.share_links for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

drop function if exists public.guest_stock(text);
create function public.guest_stock(p_token text)
returns table (card_id uuid, game text, expansion text, name text, rarity text, image_url text,
               qty bigint, conditions text, languages text, locations text)
language sql stable security definer set search_path = public as $$
  select c.id, c.game, c.expansion, c.name, c.rarity, c.image_url,
         sum(cp.qty)::bigint,
         string_agg(distinct cp.condition, ','),
         string_agg(distinct cp.language, ','),
         case when bool_or(s.show_location) then string_agg(distinct cp.location, ', ') end
  from share_links s
  join cards  c  on c.user_id = s.user_id
  join copies cp on cp.card_id = c.id and cp.status = 'disponibile'
  where s.token = p_token and length(p_token) >= 24
  group by c.id
$$;
revoke all on function public.guest_stock(text) from public;
grant execute on function public.guest_stock(text) to anon, authenticated;

create or replace function public.guest_info(p_token text)
returns table (title text, whatsapp text, telegram text)
language sql stable security definer set search_path = public as $$
  select s.title, s.whatsapp, s.telegram from share_links s
  where s.token = p_token and length(p_token) >= 24
$$;
revoke all on function public.guest_info(text) from public;
grant execute on function public.guest_info(text) to anon, authenticated;
