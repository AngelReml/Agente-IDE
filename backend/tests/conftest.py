import os
import sys
import tempfile
from pathlib import Path

# Make the backend package importable.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Isolated project root for the whole test session.
os.environ["PROJECT_ROOT"] = tempfile.mkdtemp(prefix="swarm-test-")
