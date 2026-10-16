import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication
from cutimage.app import make_icon

app = QApplication([])
target = Path(__file__).resolve().parents[1] / "assets" / "app.ico"
target.parent.mkdir(exist_ok=True)
if not make_icon().pixmap(QSize(64, 64)).save(str(target), "ICO"):
    raise SystemExit("Failed to save icon")
print(target)
