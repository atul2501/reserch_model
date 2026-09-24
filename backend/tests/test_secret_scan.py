from scripts.secret_scan import main, scan_text


def test_flags_real_looking_secrets_without_echoing_them():
    key = "0x" + "12" * 32
    text = f"HYPERLIQUID_PRIVATE_KEY={key}\nOLLAMA_API_KEY=abcdef0123456789\nDATABASE_URL=postgresql://u:" + "hunter2" + "secret@h/db\n"
    rules = {r for _, _, r in scan_text("x.env", text)}
    assert "hex-private-key" in rules
    assert "secret-assignment:HYPERLIQUID_PRIVATE_KEY" in rules
    assert "secret-assignment:OLLAMA_API_KEY" in rules
    assert "db-url-password" in rules


def test_placeholders_and_empty_values_pass():
    text = "HYPERLIQUID_PRIVATE_KEY=\nOLLAMA_API_KEYS=\nDATABASE_URL=postgresql://u:CHANGE_ME@h/db\nOLLAMA_API_KEY=your-key\n"
    assert scan_text(".env.example", text) == []


def test_repository_tracked_files_are_clean(capsys):
    assert main([]) == 0, capsys.readouterr().out
