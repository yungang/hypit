import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .agent.replay import replay_backend_factory
from .db import TaskStore
from .featured_seed import seed_featured
from .publish.mock import MockPublisher
from .settings import Settings
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    frozen = "__compiled__" in globals()  # set by Nuitka
    default_dir = (Path(os.environ["LOCALAPPDATA"]) / "HypitDesktop" if frozen
                   else Path(__file__).resolve().parents[1] / "data")
    data_dir = Path(os.environ.get("HYPIT_DESKTOP_DATA", default_dir))
    store = TaskStore(data_dir / "tasks.db")
    settings = Settings(data_dir / "settings.json")
    seed_featured(store, settings)
    window = MainWindow(store, replay_backend_factory, MockPublisher(), settings, data_dir)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
