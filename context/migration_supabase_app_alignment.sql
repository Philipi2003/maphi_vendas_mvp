-- Align an existing Supabase database with the current MaphiApp features.
-- Apply this once in the Supabase SQL Editor before deploying the new API.

ALTER TABLE public.item_types
    ADD COLUMN IF NOT EXISTS regular_price numeric(10, 2),
    ADD COLUMN IF NOT EXISTS promotional_price numeric(10, 2);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'item_types_regular_price_check'
          AND conrelid = 'public.item_types'::regclass
    ) THEN
        ALTER TABLE public.item_types
            ADD CONSTRAINT item_types_regular_price_check
            CHECK (regular_price IS NULL OR regular_price > 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'item_types_promotional_price_check'
          AND conrelid = 'public.item_types'::regclass
    ) THEN
        ALTER TABLE public.item_types
            ADD CONSTRAINT item_types_promotional_price_check
            CHECK (
                promotional_price IS NULL
                OR (
                    promotional_price > 0
                    AND regular_price IS NOT NULL
                    AND promotional_price < regular_price
                )
            );
    END IF;
END;
$$;

ALTER TABLE public.items
    DROP CONSTRAINT IF EXISTS items_status_check;

ALTER TABLE public.items
    ADD CONSTRAINT items_status_check
    CHECK (status IN (
        'DISPONIVEL',
        'RESERVADO',
        'VENDIDO',
        'VENDIDO_PRESENCIAL',
        'EM_OFERTA_PRESENCIAL',
        'REMOVIDO'
    ));

ALTER TABLE public.pickup_spots
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz;

ALTER TABLE public.reservations
    ADD COLUMN IF NOT EXISTS user_name_snapshot text,
    ADD COLUMN IF NOT EXISTS pickup_spot_name_snapshot text,
    ADD COLUMN IF NOT EXISTS pickup_spot_address_snapshot text,
    ADD COLUMN IF NOT EXISTS pickup_window_start_snapshot timestamptz,
    ADD COLUMN IF NOT EXISTS pickup_window_end_snapshot timestamptz,
    ADD COLUMN IF NOT EXISTS cancelled_by text,
    ADD COLUMN IF NOT EXISTS cancelled_at timestamptz,
    ADD COLUMN IF NOT EXISTS completed_at timestamptz,
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz;

UPDATE public.reservations AS r
SET user_name_snapshot = COALESCE(r.user_name_snapshot, u.name),
    pickup_spot_name_snapshot = COALESCE(r.pickup_spot_name_snapshot, p.name),
    pickup_spot_address_snapshot = COALESCE(r.pickup_spot_address_snapshot, p.address),
    pickup_window_start_snapshot = COALESCE(r.pickup_window_start_snapshot, p.window_start),
    pickup_window_end_snapshot = COALESCE(r.pickup_window_end_snapshot, p.window_end)
FROM public.users AS u, public.pickup_spots AS p
WHERE u.id = r.user_id
  AND p.id = r.pickup_spot_id;

ALTER TABLE public.reservations
    DROP CONSTRAINT IF EXISTS reservations_cancelled_by_check;

ALTER TABLE public.reservations
    ADD CONSTRAINT reservations_cancelled_by_check
    CHECK (cancelled_by IS NULL OR cancelled_by IN ('DONO', 'CLIENTE'));

ALTER TABLE public.reservation_items
    ADD COLUMN IF NOT EXISTS item_type_id_snapshot uuid,
    ADD COLUMN IF NOT EXISTS unit_price_snapshot numeric(10, 2);

UPDATE public.reservation_items AS ri
SET item_type_id_snapshot = COALESCE(ri.item_type_id_snapshot, i.item_type_id),
    unit_price_snapshot = COALESCE(
        ri.unit_price_snapshot,
        CASE
            WHEN (
                SELECT sale_type
                FROM public.reservations
                WHERE id = ri.reservation_id
            ) = 'PROMOCAO'
                THEN COALESCE(t.promotional_price, t.regular_price)
            ELSE t.regular_price
        END
    )
FROM public.items AS i
JOIN public.item_types AS t ON t.id = i.item_type_id
WHERE i.id = ri.item_id;

CREATE INDEX IF NOT EXISTS reservations_pickup_spot_active_idx
    ON public.reservations (pickup_spot_id, created_at)
    WHERE status = 'ATIVA' AND deleted_at IS NULL;

-- Existing item types need an owner-provided regular_price before reservations
-- can be created. Do not invent prices during migration.
SELECT id, name
FROM public.item_types
WHERE regular_price IS NULL;

-- Existing reservation items with no recoverable price remain NULL to avoid
-- fabricating historical values. New reservations always store a price snapshot.
SELECT ri.reservation_id, ri.item_id
FROM public.reservation_items AS ri
WHERE ri.unit_price_snapshot IS NULL;
