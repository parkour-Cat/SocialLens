from __future__ import annotations

from pathlib import Path

from sociallens import config


def test_data_dir_in_source_checkout():
    assert config.default_data_dir() == config.REPO_DIR / "data"


def test_data_dir_when_installed_as_package(tmp_path, monkeypatch):
    # installed: sociallens/ sits in site-packages, no pyproject.toml / extension/ next to it
    monkeypatch.setattr(config, "BACKEND_DIR", tmp_path / "site-packages")
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    assert config.default_data_dir() == Path.home() / ".sociallens"


def test_data_dir_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCIALLENS_DATA_DIR", str(tmp_path / "d"))
    assert config.Settings().data_dir == tmp_path / "d"
