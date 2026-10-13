"""Put the source trees in src/ on sys.path so the tests import the code that gets packaged."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "src/eclipse-os-core/root/usr/lib/arclight"
INSTALLER = ROOT / "src/eclipse-os-installer/root/usr/lib/arclight/installer"
for p in (CORE, INSTALLER):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
