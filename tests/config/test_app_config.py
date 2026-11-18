import os

import app_config


def test_loads_public_firebase_settings_from_functions_env(tmp_path, monkeypatch):
    functions_dir = tmp_path / "functions"
    functions_dir.mkdir()
    env_path = functions_dir / ".env"
    env_path.write_text(
        "MAPHI_FIREBASE_API_KEY=\"test-api-key\"\n"
        "MAPHI_AUTH_DOMAIN=\"test.firebaseapp.com\"\n"
        "MAPHI_PROJECT_ID=\"test-project\"\n"
        "SUPABASE_DB_URL: postgres://server-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(app_config, "FUNCTIONS_ENV_PATH", env_path)
    monkeypatch.setattr(app_config, "ENV_PATHS", (env_path,))
    for key in ("FIREBASE_API_KEY", "AUTH_DOMAIN", "PROJECT_ID", "SUPABASE_DB_URL"):
        monkeypatch.delenv(key, raising=False)

    app_config._load_env_file()

    assert os.environ["FIREBASE_API_KEY"] == "test-api-key"
    assert os.environ["AUTH_DOMAIN"] == "test.firebaseapp.com"
    assert os.environ["PROJECT_ID"] == "test-project"
    assert "SUPABASE_DB_URL" not in os.environ
