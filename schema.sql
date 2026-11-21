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
