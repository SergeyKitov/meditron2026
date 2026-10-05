import pytest
from app.demo_reset import main


@pytest.mark.parametrize(
    ("database_url", "reset_mode"),
    [
        ("sqlite:////tmp/patient-pathway-protected.db", "compose"),
        ("postgresql+psycopg://meditron:secret@db:5432/meditron", ""),
        ("postgresql+psycopg://meditron:secret@other-host:5432/meditron", "compose"),
    ],
)
def test_demo_reset_refuses_unapproved_database(monkeypatch, database_url, reset_mode):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("MEDITRON_DEMO_RESET", reset_mode)

    with pytest.raises(SystemExit, match="Сброс разрешён только"):
        main()
