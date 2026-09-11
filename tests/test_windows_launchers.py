from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_run_bat_prompts_only_for_required_token():
    text = (ROOT / "run.bat").read_text(encoding="utf-8")

    assert 'if "!BOT_TOKEN!"=="" (' in text
    assert 'if "!BOT_ALLOWED_USER_IDS!"=="" (' not in text
    assert 'if "%BOT_TOKEN%"=="" (' not in text
    assert 'if "%BOT_ALLOWED_USER_IDS%"=="" (' not in text
    assert text.count("System.Text.UTF8Encoding($false)") == 1


def test_run_silent_uses_its_script_directory():
    text = (ROOT / "run_silent.vbs").read_text(encoding="utf-8")

    assert "WScript.ScriptFullName" in text
    assert "WshShell.CurrentDirectory = ScriptDir" in text
    assert "WScript.Path" not in text
