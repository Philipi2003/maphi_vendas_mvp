import psycopg
from firebase_functions import https_fn
from firebase_functions.params import SecretParam
from psycopg.rows import dict_row

from api import REGION, handle_request


SUPABASE_DB_URL = SecretParam("SUPABASE_DB_URL")


def _connection_factory() -> psycopg.Connection:
    return psycopg.connect(
        SUPABASE_DB_URL.value,
        connect_timeout=8,
        prepare_threshold=None,
        row_factory=dict_row,
        sslmode="require",
    )


@https_fn.on_request(
    region=REGION,
    secrets=[SUPABASE_DB_URL],
    timeout_sec=60,
    max_instances=5,
    concurrency=10,
)
def api(request: https_fn.Request) -> https_fn.Response:
    return handle_request(request, _connection_factory)
