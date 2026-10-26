import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .agent.factory import make_backend_factory
from .credentials import default_store
from .db import TaskStore
from .featured_seed import seed_featured
from .publish.mock import MockPublisher
from .settings import Settings
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    frozen = "__compiled__" in globals() or getattr(sys, "frozen", False)  # Nuitka / PyInstaller
    default_dir = (Path(os.environ["LOCALAPPDATA"]) / "HypitDesktop" if frozen
                   else Path(__file__).resolve().parents[1] / "data")
    data_dir = Path(os.environ.get("HYPIT_DESKTOP_DATA", default_dir))
    store = TaskStore(data_dir / "tasks.db")
    settings = Settings(data_dir / "settings.json")
    seed_featured(store, settings)
    credentials = default_store()
    window = MainWindow(store, make_backend_factory(data_dir, credentials), MockPublisher(), settings, data_dir,
                        credentials=credentials)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
