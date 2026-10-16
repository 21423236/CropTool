import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cutimage.app import MainWindow
from cutimage.model import Region, export_regions, moved_bounds, new_bounds, resized_bounds, safe_filename

APP = QApplication.instance() or QApplication([])


class GeometryTests(unittest.TestCase):
    def test_reverse_drag_and_clamp(self):
        self.assertEqual(new_bounds(98.8, 70.2, -10, -2, 100, 80), (0, 0, 99, 71))
        self.assertEqual(new_bounds(100, 80, 150, 150, 100, 80), (99, 79, 1, 1))

    def test_move_clamps_without_changing_size(self):
        r = Region(10, 15, 20, 30, "demo")
        self.assertEqual(moved_bounds(r, -100, 100, 100, 80), (0, 50, 20, 30))

    def test_all_resize_handles_stay_valid(self):
        r = Region(10, 15, 20, 30, "demo")
        for handle in ("nw", "n", "ne", "e", "se", "s", "sw", "w"):
            for dx, dy in [(-1000, -1000), (1000, 1000), (7, -8)]:
                x, y, w, h = resized_bounds(r, handle, dx, dy, 100, 80)
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertGreaterEqual(w, 1)
                self.assertGreaterEqual(h, 1)
                self.assertLessEqual(x+w, 100)
                self.assertLessEqual(y+h, 80)

    def test_filename_safety(self):
        self.assertEqual(safe_filename('a/b:c*?'), "a_b_c__")
        self.assertEqual(safe_filename('CON'), "_CON")
        self.assertEqual(safe_filename('...'), "选区")


class ExportTests(unittest.TestCase):
    def test_pixel_exact_alpha_and_collision(self):
        image = QImage(20, 16, QImage.Format.Format_ARGB32)
        for y in range(image.height()):
            for x in range(image.width()):
                image.setPixelColor(x, y, QColor(x*10, y*10, 90, (x+y)*7 % 256))
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "中文图片"
            r = Region(3, 4, 8, 6, "图案")
            first = export_regions(image, [r, r], directory)
            second = export_regions(image, [r], directory)
            self.assertEqual([p.name for p in first + second], ["图案.png", "图案_2.png", "图案_3.png"])
            result = QImage(str(first[0]))
            self.assertEqual((result.width(), result.height()), (8, 6))
            for y in range(6):
                for x in range(8):
                    self.assertEqual(result.pixelColor(x, y), image.pixelColor(x+3, y+4))

    def test_reject_invalid_crop(self):
        image = QImage(20, 16, QImage.Format.Format_ARGB32)
        image.fill(QColor("red"))
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(OSError):
                export_regions(image, [Region(19, 15, 5, 5, "bad")], temp)
            self.assertEqual(list(Path(temp).iterdir()), [])


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.image_path = Path(self.temp.name) / "原图.png"
        image = QImage(800, 600, QImage.Format.Format_ARGB32)
        image.fill(QColor(220, 100, 40, 180))
        image.save(str(self.image_path))
        self.window = MainWindow()
        self.window.show()
        APP.processEvents()
        self.assertTrue(self.window.open_path(str(self.image_path)))
        APP.processEvents()

    def tearDown(self):
        self.window.saved_state = self.window.snapshot()
        self.window.close()
        APP.processEvents()
        self.temp.cleanup()

    def drag_scene(self, start, end):
        canvas = self.window.canvas
        p1 = canvas.mapFromScene(QPointF(*start))
        p2 = canvas.mapFromScene(QPointF(*end))
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p1)
        QTest.mouseMove(canvas.viewport(), p2, 15)
        QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p2)
        APP.processEvents()

    def test_draw_select_move_resize_undo_redo(self):
        w = self.window
        self.drag_scene((100, 100), (300, 250))
        self.assertEqual(len(w.canvas.regions), 1)
        self.assertEqual(w.canvas.mode, "select")
        r = w.canvas.active
        self.assertAlmostEqual(r.width, 200, delta=3)
        self.assertAlmostEqual(r.height, 150, delta=3)
        self.assertEqual(w.region_list.count(), 1)
        old = r.snapshot()
        self.drag_scene((180, 170), (220, 200))
        self.assertAlmostEqual(r.x, old["x"]+40, delta=3)
        self.assertEqual(r.width, old["width"])
        old = r.snapshot()
        self.drag_scene((r.x+r.width, r.y+r.height), (r.x+r.width+40, r.y+r.height+20))
        self.assertGreater(r.width, old["width"])
        self.assertGreater(r.height, old["height"])
        w.undo()
        self.assertEqual(w.canvas.active.snapshot(), old)
        w.redo()
        self.assertGreater(w.canvas.active.width, old["width"])
        w.canvas.set_mode("draw")
        self.drag_scene((150, 120), (250, 200))
        self.assertEqual(len(w.canvas.regions), 2)
        w.region_list.setCurrentRow(0)
        self.assertEqual(w.canvas.active.uid, w.canvas.regions[0].uid)
        w.delete_active()
        self.assertEqual(w.region_list.count(), 1)
        w.undo()
        self.assertEqual(w.region_list.count(), 2)

    def test_zoom_and_numeric_edit_export(self):
        w = self.window
        w.canvas.set_zoom(1.6)
        self.drag_scene((100, 100), (200, 180))
        self.assertEqual(len(w.canvas.regions), 1)
        self.assertAlmostEqual(w.canvas.active.width, 100, delta=2)
        for field, value in [("x", 50), ("y", 60), ("width", 123), ("height", 87)]:
            w.spins[field].setValue(value)
        w.name_edit.setText("自定义图案")
        w.rename_active()
        r = w.canvas.active
        self.assertEqual((r.x, r.y, r.width, r.height, r.name), (50, 60, 123, 87, "自定义图案"))
        paths = export_regions(w.canvas.image, [r], Path(self.temp.name) / "导出")
        output = QImage(str(paths[0]))
        self.assertEqual((output.width(), output.height()), (123, 87))
        self.assertEqual(output.pixelColor(0, 0), w.canvas.image.pixelColor(50, 60))

    def test_escape_cancels_new_region(self):
        canvas = self.window.canvas
        p1 = canvas.mapFromScene(QPointF(100, 100))
        p2 = canvas.mapFromScene(QPointF(230, 200))
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p1)
        QTest.mouseMove(canvas.viewport(), p2, 15)
        self.assertEqual(len(canvas.regions), 1)
        QTest.keyClick(canvas, Qt.Key.Key_Escape)
        QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p2)
        self.assertEqual(len(canvas.regions), 0)
        self.assertEqual(self.window.history_index, 0)

    def test_typing_name_does_not_activate_shortcuts(self):
        self.drag_scene((100, 100), (300, 250))
        w = self.window
        w.name_edit.setFocus()
        w.name_edit.selectAll()
        QTest.keyClicks(w.name_edit, "new-vivid-h")
        self.assertEqual(w.name_edit.text(), "new-vivid-h")
        self.assertEqual(w.canvas.mode, "select")
        QTest.keyClick(w.name_edit, Qt.Key.Key_Return)
        self.assertEqual(w.canvas.active.name, "new-vivid-h")


if __name__ == "__main__":
    unittest.main()
