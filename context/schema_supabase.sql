-- MaphiApp PostgreSQL schema for Supabase.
-- Authentication is handled externally; auth_uid stores the provider's user ID.

CREATE TABLE IF NOT EXISTS public.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_uid text NOT NULL UNIQUE,
    name text NOT NULL,
    email text NOT NULL UNIQUE,
    phone text,
    role text NOT NULL DEFAULT 'CLIENTE'
        CHECK (role IN ('DONO', 'CLIENTE')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.item_types (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    description text,
    image_url text,
    is_custom_order_only boolean NOT NULL DEFAULT false,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    item_type_id uuid NOT NULL
        REFERENCES public.item_types (id) ON DELETE RESTRICT,
    status text NOT NULL DEFAULT 'DISPONIVEL'
        CHECK (status IN (
            'DISPONIVEL',
            'RESERVADO',
            'VENDIDO_PRESENCIAL',
            'EM_OFERTA_PRESENCIAL'
        )),
    expiration_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.pickup_spots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    address text NOT NULL,
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pickup_spots_window_order
        CHECK (window_end > window_start)
);

CREATE TABLE IF NOT EXISTS public.reservations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL
        REFERENCES public.users (id) ON DELETE RESTRICT,
    pickup_spot_id uuid NOT NULL
        REFERENCES public.pickup_spots (id) ON DELETE RESTRICT,
    sale_type text NOT NULL
        CHECK (sale_type IN ('PROMOCAO', 'NORMAL')),
    status text NOT NULL DEFAULT 'ATIVA'
        CHECK (status IN ('ATIVA', 'CONCLUIDA', 'CANCELADA')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.reservation_items (
    reservation_id uuid NOT NULL
        REFERENCES public.reservations (id) ON DELETE RESTRICT,
    item_id uuid NOT NULL
        REFERENCES public.items (id) ON DELETE RESTRICT,
    item_type_name_snapshot text NOT NULL,
    CONSTRAINT reservation_items_pkey
        PRIMARY KEY (reservation_id, item_id)
);

CREATE INDEX IF NOT EXISTS items_item_type_status_idx
    ON public.items (item_type_id, status);

CREATE INDEX IF NOT EXISTS reservations_user_status_idx
    ON public.reservations (user_id, status);

CREATE INDEX IF NOT EXISTS reservations_pickup_spot_status_idx
    ON public.reservations (pickup_spot_id, status);

CREATE INDEX IF NOT EXISTS reservation_items_item_id_idx
    ON public.reservation_items (item_id);

-- Deny direct access through the Supabase Data API unless explicit policies
-- are added later. The trusted backend must use a server-side database role.
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.item_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pickup_spots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reservation_items ENABLE ROW LEVEL SECURITY;
