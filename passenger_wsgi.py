"""نقطة دخول لاستضافات cPanel («Setup Python App» / Phusion Passenger)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import load_env  # noqa: E402

load_env.load()

from server import create_app  # noqa: E402

application = create_app()
