import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import load_env

load_env.load()

from server import create_app

app = create_app()
app.url_map.strict_slashes = False
