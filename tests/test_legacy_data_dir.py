"""A previous kickr-pi data folder is adopted instead of starting empty."""

from pathlib import Path

from steadygrind.config import adopt_legacy_database, adopt_legacy_directory


def test_empty_new_folder_takes_the_previous_directory(tmp_path: Path) -> None:
    old = tmp_path / "kickr-pi"
    new = tmp_path / "steadyGrind"
    old.mkdir()
    (old / "rides").mkdir()
    (old / "kickr_pi.db").write_text("db")

    adopt_legacy_directory(new, old)

    assert new.is_dir()
    assert not old.exists()
    assert (new / "rides").is_dir()
    assert adopt_legacy_database(new).name == "steadygrind.db"
    assert (new / "steadygrind.db").read_text() == "db"
    assert not (new / "kickr_pi.db").exists()


def test_existing_new_folder_is_left_in_place(tmp_path: Path) -> None:
    old = tmp_path / "kickr-pi"
    new = tmp_path / "steadyGrind"
    old.mkdir()
    (old / "kickr_pi.db").write_text("old")
    new.mkdir()
    (new / "steadygrind.db").write_text("new")

    adopt_legacy_directory(new, old)

    assert (new / "steadygrind.db").read_text() == "new"
    assert (old / "kickr_pi.db").read_text() == "old"
