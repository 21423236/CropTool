"""Generate an internal demo image and native desktop screenshot."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QApplication

from cutimage.app import MainWindow
from cutimage.model import Region

app = QApplication([])
app.setStyle("Fusion")
directory = Path(__file__).resolve().parents[1] / "artifacts"
directory.mkdir(exist_ok=True)
image = QImage(1200, 850, QImage.Format.Format_ARGB32)
image.fill(QColor(245, 241, 230))
painter = QPainter(image)
painter.setRenderHint(QPainter.RenderHint.Antialiasing)
painter.setPen(QPen(QColor(48, 67, 92), 6))
painter.setBrush(QColor(255, 186, 71))
painter.drawEllipse(QRectF(130, 150, 270, 270))
painter.setBrush(QColor(91, 170, 244))
painter.drawRoundedRect(QRectF(530, 170, 330, 230), 35, 35)
painter.setBrush(QColor(104, 193, 153))
painter.drawPolygon(QPolygonF([QPointF(330, 540), QPointF(150, 740), QPointF(510, 740)]))
painter.setBrush(QColor(194, 144, 222))
painter.drawEllipse(QRectF(660, 530, 300, 210))
painter.end()
image_path = directory / "demo.png"
image.save(str(image_path))
window = MainWindow()
window.show()
app.processEvents()
window.open_path(str(image_path))
window.canvas.regions = [Region(105, 125, 320, 320, "圆形图案"), Region(505, 145, 380, 280, "圆角图案"), Region(125, 510, 410, 250, "三角图案")]
window.canvas.set_active(window.canvas.regions[1].uid)
window.canvas.set_mode("select")
window.commit()
app.processEvents()
target = directory / "preview.png"
window.grab().save(str(target))
window.saved_state = window.snapshot()
window.close()
print(target)
