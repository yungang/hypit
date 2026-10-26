"""Render the Settings dialog to a PNG (offscreen) with a few providers filled in, to check the layout."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from hypit_desktop.credentials import MemoryStore, key_name  # noqa: E402
from hypit_desktop.settings import Settings  # noqa: E402
from hypit_desktop.ui.settings_dialog import SettingsDialog  # noqa: E402

app = QApplication([])
store = MemoryStore()
store.set(key_name("deepseek"), "ds-key")
store.set(key_name("ark"), "ark-key")
dialog = SettingsDialog(Settings(Path(tempfile.mkdtemp()) / "s.json"), store)
dialog.llm_provider.setCurrentIndex(dialog.llm_provider.findData("openai"))
dialog.service.setCurrentIndex(dialog.service.findData("gemini"))
dialog.show()
app.processEvents()
dialog.grab().save(sys.argv[1])
