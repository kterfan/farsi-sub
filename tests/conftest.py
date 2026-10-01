"""pytest setup: keep the suite away from the real data folder.

Same rule as run_tests.py -- the editor tests save projects and the window
layout, and from a source checkout the default data folder is the app's own.
"""

import os
import tempfile

os.environ.setdefault("FARSISUB_DATA", tempfile.mkdtemp(prefix="farsisub-tests-"))
