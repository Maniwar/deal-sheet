-- The garage store: one row for each car, so every device that uses the same API key shows the same garage.
--
-- Run this once in a Postgres database that speaks PostgREST (Supabase does). Then give the app the project's
-- address and its publishable key as DEALSHEET_DB_URL and DEALSHEET_DB_KEY (Streamlit secrets or environment).
--
-- What keeps it safe with a key that may be public:
--   * Row level security is on and there are no policies, so the table cannot be read or written directly.
--   * The only way in is the two functions below, and both need the garage's id: 64 hex characters hashed from
--     the owner's API key. Nobody can list garages, and nobody can name one without that key.
--   * The functions bound what one caller can store: a car's size, the cars in a garage, and the size of the
--     whole table, so a stranger with the public key cannot fill the database.

create table if not exists public.dealsheet_cars (
    garage_id text not null,
    car_id    text not null,
    data      jsonb,
    deleted   boolean not null default false,
    at        double precision not null,          -- when the car last changed, in seconds since 1970, by the app's clock
    saved     timestamptz not null default now(),
    primary key (garage_id, car_id)
);

alter table public.dealsheet_cars enable row level security;
revoke all on public.dealsheet_cars from anon, authenticated;

-- Every car in one garage, removal markers included.
create or replace function public.dealsheet_load(p_garage text)
returns table (car_id text, data jsonb, deleted boolean, at double precision)
language sql security definer set search_path = '' stable
as $$
    select c.car_id, c.data, c.deleted, c.at
    from public.dealsheet_cars c
    where c.garage_id = p_garage and p_garage ~ '^[0-9a-f]{64}$';
$$;

-- Write one car, or the marker that it was removed. The newer copy wins: an older write changes nothing.
create or replace function public.dealsheet_save(p_garage text, p_car text, p_data jsonb, p_deleted boolean, p_at double precision)
returns double precision
language plpgsql security definer set search_path = ''
as $$
declare
    kept double precision;
begin
    if p_garage !~ '^[0-9a-f]{64}$' or p_car !~ '^[0-9a-f]{6,16}$' then
        raise exception 'not a garage or a car';
    end if;
    if p_at is null or p_at <= 0 or p_at > extract(epoch from now()) + 86400 then
        raise exception 'not a time';
    end if;
    if not p_deleted and (p_data is null or pg_column_size(p_data) > 600000) then
        raise exception 'a car must have its facts, and be under 600 KB';
    end if;
    if not p_deleted then
        if pg_total_relation_size('public.dealsheet_cars'::regclass) > 40000000 then      -- 40 MB: about 800 cars
            raise exception 'the garage store is full';
        end if;
        if not exists (select 1 from public.dealsheet_cars c where c.garage_id = p_garage and c.car_id = p_car)
           and (select count(*) from public.dealsheet_cars c where c.garage_id = p_garage and not c.deleted) >= 80 then
            raise exception 'this garage is full: remove a car to make room';
        end if;
    end if;
    -- A removal marker is only needed until every device has seen it: a garage keeps its newest 200.
    delete from public.dealsheet_cars c
    where c.garage_id = p_garage and c.deleted
      and c.car_id in (select d.car_id from public.dealsheet_cars d where d.garage_id = p_garage and d.deleted
                       order by d.at desc offset 200);
    insert into public.dealsheet_cars as c (garage_id, car_id, data, deleted, at, saved)
    values (p_garage, p_car, case when p_deleted then null else p_data end, p_deleted, p_at, now())
    on conflict (garage_id, car_id) do update
        set data = excluded.data, deleted = excluded.deleted, at = excluded.at, saved = now()
        where c.at <= excluded.at;
    select c.at into kept from public.dealsheet_cars c where c.garage_id = p_garage and c.car_id = p_car;
    return kept;
end;
$$;

-- The app calls with the publishable key and no sign-in, so that role alone may run the two functions.
revoke all on function public.dealsheet_load(text) from public, authenticated;
revoke all on function public.dealsheet_save(text, text, jsonb, boolean, double precision) from public, authenticated;
grant execute on function public.dealsheet_load(text) to anon;
grant execute on function public.dealsheet_save(text, text, jsonb, boolean, double precision) to anon;
