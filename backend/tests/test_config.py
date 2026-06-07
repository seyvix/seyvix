from pathlib import Path

from app.core.config import Settings, _settings_env_files


def test_settings_env_files_are_absolute_and_cwd_independent(tmp_path: Path) -> None:
    config_file = tmp_path / "repo" / "backend" / "app" / "core" / "config.py"
    config_file.parent.mkdir(parents=True)
    config_file.touch()

    env_files = _settings_env_files(config_file)

    assert env_files == (
        tmp_path / "repo" / ".env",
        tmp_path / "repo" / "backend" / ".env",
    )
    assert all(path.is_absolute() for path in env_files)


def test_settings_uses_cwd_independent_env_files() -> None:
    env_files = Settings.model_config["env_file"]

    assert env_files == _settings_env_files()
