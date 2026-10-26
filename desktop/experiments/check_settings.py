"""Run the Settings page's connection checks with the real keys from the environment (free), and render the dialog."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from hypit_desktop import connection  # noqa: E402
from hypit_desktop.credentials import MemoryStore  # noqa: E402
from hypit_desktop.settings import Settings  # noqa: E402
from hypit_desktop.ui.settings_dialog import SettingsDialog  # noqa: E402

out = Path(sys.argv[1])
lines = [
    f"ark  good key : {connection.test_ark(os.environ['ARK_API_KEY'])}",
    f"ark  bad key  : {connection.test_ark('ark-badbadbad')}",
    f"llm  good key : {connection.test_llm('https://api.deepseek.com/anthropic', 'deepseek-flash', os.environ['DEEPSEEK_API_KEY'])}",
    f"llm  bad key  : {connection.test_llm('https://api.deepseek.com/anthropic', 'deepseek-flash', 'sk-bad')}",
    f"llm  bad model: {connection.test_llm('https://api.deepseek.com/anthropic', 'nope', os.environ['DEEPSEEK_API_KEY'])}",
]
out.with_suffix(".txt").write_text("\n".join(lines), encoding="utf-8")

app = QApplication([])
store = MemoryStore()
store.set("ark-api-key", "x")
dialog = SettingsDialog(Settings(Path(tempfile.mkdtemp()) / "s.json"), store)
dialog.ark_status.setText("✓ 连接正常,密钥有效,Seedance 2.0 Mini 已开通。")
dialog.ark_status.setStyleSheet("color: #1a7f37;")
dialog.show()
app.processEvents()
dialog.grab().save(str(out))
