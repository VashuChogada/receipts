import shutil
from pathlib import Path

import pytest

from app import config, db as dbmod

TESSERACT = shutil.which("tesseract") or (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe" if Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists() else None
)


@pytest.fixture(autouse=True)
def settings(tmp_path, monkeypatch):
    """Every test gets its own data folder and database."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "receipts.db"))
    monkeypatch.setenv("STATIC_DIR", str(tmp_path / "static"))
    monkeypatch.setenv("SEMANTIC_SEARCH", "off")
    # Models download once into backend/.models, not into each test's folder.
    monkeypatch.setenv("MODEL_CACHE", str(Path(__file__).resolve().parent.parent / ".models"))
    monkeypatch.setenv("OCR_ENABLED", "on" if TESSERACT else "off")
    if TESSERACT:
        import pytesseract

        monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd", TESSERACT)
    s = config.load()
    monkeypatch.setattr(config, "settings", s)
    return s


@pytest.fixture
def db(settings):
    from app import categorize

    conn = dbmod.connect()
    dbmod.migrate(conn)
    categorize.seed(conn)
    yield conn
    conn.close()


@pytest.fixture(scope="session", autouse=True)
def stop_model_helper():
    yield
    from app.modelhost import host

    host.stop()
