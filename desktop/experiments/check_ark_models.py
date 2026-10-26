"""Free check of which Ark Seedance models the key can use (an incomplete task is sent per model, never billed)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hypit_desktop import connection  # noqa: E402

print(connection.ark_models())
ok, text = connection.test_ark(os.environ["ARK_API_KEY"])
Path(sys.argv[1]).write_text(f"{ok}\n{text}\n", encoding="utf-8")
