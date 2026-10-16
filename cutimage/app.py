from __future__ import annotations

import logging
import math
import os
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QActionGroup, QColor, QDesktopServices, QIcon,
    QImage, QImageReader, QKeySequence, QPainter, QPen, QPixmap, QShortcut)
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QGraphicsScene, QGraphicsView, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QSpinBox, QSplitter, QToolBar, QVBoxLayout, QWidget)

from .model import Region, export_regions, moved_bounds, new_bounds, resized_bounds

APP_TITLE = "图案框选工具"
ACCENT = QColor(79, 140, 255)


def make_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(35, 54, 88))
    painter.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    painter.setPen(QPen(ACCENT, 4))
    painter.setBrush(QColor(79, 140, 255, 45))
    painter.drawRect(QRectF(17, 17, 30, 30))
    painter.setBrush(QColor(235, 242, 255))
    for x, y in [(17, 17), (47, 17), (17, 47), (47, 47)]:
        painter.drawRect(QRectF(x - 3, y - 3, 6, 6))
    painter.end()
    return QIcon(pixmap)


class Canvas(QGraphicsView):
    committed = Signal()
    active_changed = Signal(str)
    geometry_changed = Signal()
    zoom_changed = Signal(float)
    mode_changed = Signal(str)
    pointer_changed = Signal(str)
    file_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor(22, 27, 36))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.image = QImage()
        self.regions = []
        self.active_uid = ""
        self.mode = "select"
        self.gesture = None
        self.space_down = False
        self.fit_mode = True
        self.serial = 1

    @property
    def active(self):
        return next((r for r in self.regions if r.uid == self.active_uid), None)

    @property
    def zoom(self):
        return self.transform().m11()

    def set_image(self, image):
        self.scene().clear()
        self.image = image
        self.scene().addPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(QRectF(0, 0, image.width(), image.height()))
        self.regions = []
        self.serial = 1
        self.gesture = None
        self.set_active("")
        self.fit_image()

    def set_mode(self, mode):
        self.mode = mode
        self.refresh_cursor()
        self.mode_changed.emit(mode)

    def refresh_cursor(self):
        cursor = Qt.CursorShape.OpenHandCursor if self.space_down or self.mode == "pan" else (
            Qt.CursorShape.CrossCursor if self.mode == "draw" else Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(cursor)

    def set_active(self, uid):
        self.active_uid = uid
        self.active_changed.emit(uid)
        self.viewport().update()

    def fit_image(self):
        if self.image.isNull():
            return
        self.fitInView(self.sceneRect().adjusted(-12, -12, 12, 12), Qt.AspectRatioMode.KeepAspectRatio)
        self.fit_mode = True
        self.zoom_changed.emit(self.zoom)
        self.viewport().update()

    def set_zoom(self, value, anchor=None):
        if self.image.isNull():
            return
        value = max(0.005, min(32.0, value))
        anchor = anchor or self.viewport().rect().center()
        before = self.mapToScene(anchor)
        self.scale(value / self.zoom, value / self.zoom)
        after = self.mapToScene(anchor)
        delta = after - before
        self.translate(delta.x(), delta.y())
        self.fit_mode = False
        self.zoom_changed.emit(self.zoom)
        self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_mode:
            self.fit_image()

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        if self.image.isNull():
            return
        # Checkerboard reveals transparency without modifying source pixels.
        painter.save()
        painter.setClipRect(self.sceneRect())
        painter.fillRect(self.sceneRect(), QColor(215, 219, 226))
        visible = rect.intersected(self.sceneRect())
        tile = max(12.0, 14 / max(self.zoom, 0.005))
        left = math.floor(visible.left() / tile)
        top = math.floor(visible.top() / tile)
        for row in range(top, math.ceil(visible.bottom() / tile)):
            for col in range(left, math.ceil(visible.right() / tile)):
                if (row + col) % 2 == 0:
                    painter.fillRect(QRectF(col * tile, row * tile, tile, tile), QColor(242, 244, 248))
        painter.restore()

    def handle_points(self, region):
        x, y, w, h = region.x, region.y, region.width, region.height
        return {"nw": QPointF(x, y), "n": QPointF(x+w/2, y), "ne": QPointF(x+w, y),
                "e": QPointF(x+w, y+h/2), "se": QPointF(x+w, y+h),
                "s": QPointF(x+w/2, y+h), "sw": QPointF(x, y+h), "w": QPointF(x, y+h/2)}

    def drawForeground(self, painter, rect):
        if self.image.isNull():
            painter.save()
            painter.resetTransform()
            area = QRectF(self.viewport().rect())
            painter.setPen(QColor(235, 240, 250))
            font = painter.font()
            font.setPointSize(22)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(area.adjusted(0, -40, 0, -40), Qt.AlignmentFlag.AlignCenter, "打开图片，开始框选")
            font.setPointSize(11)
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor(148, 161, 184))
            painter.drawText(area.adjusted(0, 40, 0, 40), Qt.AlignmentFlag.AlignCenter, "点击「打开图片」或将图片拖入窗口\n支持多次框选 · 自由调整 · 原图像素导出")
            painter.restore()
            return
        painter.save()
        painter.resetTransform()
        for index, region in enumerate(self.regions, 1):
            active = region.uid == self.active_uid
            corners = self.mapFromScene(QRectF(region.x, region.y, region.width, region.height))
            box = QRectF(corners.boundingRect())
            pen = QPen(ACCENT if active else QColor(72, 210, 167), 2 if active else 1.5)
            if not active:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(QColor(79, 140, 255, 36 if active else 12))
            painter.drawRect(box)
            text = f"{index:02d}  {region.width} × {region.height}"
            metrics = painter.fontMetrics()
            label_w = metrics.horizontalAdvance(text) + 16
            label_y = box.top() - 25 if box.top() >= 25 else box.top() + 3
            label = QRectF(box.left(), label_y, label_w, 22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ACCENT if active else QColor(26, 112, 90))
            painter.drawRoundedRect(label, 4, 4)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(label, Qt.AlignmentFlag.AlignCenter, text)
        # Draw active handles last so overlapping rectangles never obscure them.
        if self.active:
            painter.setPen(QPen(ACCENT, 1.5))
            painter.setBrush(QColor(255, 255, 255))
            for point in self.handle_points(self.active).values():
                p = self.mapFromScene(point)
                painter.drawRect(QRectF(p.x() - 4, p.y() - 4, 8, 8))
        painter.restore()

    def hit_handle(self, position):
        if self.active:
            for name, point in self.handle_points(self.active).items():
                p = self.mapFromScene(point)
                if abs(p.x() - position.x()) <= 7 and abs(p.y() - position.y()) <= 7:
                    return name
        return None

    def hit_region(self, scene_point):
        for region in reversed(self.regions):
            if QRectF(region.x, region.y, region.width, region.height).contains(scene_point):
                return region
        return None

    def bounded_point(self, point):
        return QPointF(max(0, min(self.image.width(), point.x())),
                       max(0, min(self.image.height(), point.y())))

    def mousePressEvent(self, event):
        self.setFocus()
        pos = event.position().toPoint()
        if event.button() == Qt.MouseButton.MiddleButton or (event.button() == Qt.MouseButton.LeftButton and (self.space_down or self.mode == "pan")):
            self.gesture = {"kind": "pan", "last": pos}
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton or self.image.isNull():
            return super().mousePressEvent(event)
        point = self.mapToScene(pos)
        handle = self.hit_handle(pos) if self.mode == "select" else None
        hit = self.hit_region(point) if self.mode == "select" else None
        if handle:
            self.gesture = {"kind": "resize", "start": point, "handle": handle,
                            "original": Region(**self.active.snapshot())}
        elif hit:
            self.set_active(hit.uid)
            self.gesture = {"kind": "move", "start": point, "original": Region(**hit.snapshot())}
        elif self.sceneRect().contains(point):
            self.gesture = {"kind": "draw", "start": self.bounded_point(point), "viewport_start": pos, "uid": None}
            self.set_active("")
        else:
            self.set_active("")
        event.accept()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        point = self.mapToScene(pos)
        if not self.image.isNull():
            self.pointer_changed.emit(f"X {max(0, min(self.image.width()-1, int(point.x())))}   Y {max(0, min(self.image.height()-1, int(point.y())))}")
        if not self.gesture:
            if self.mode == "select" and not self.space_down:
                handle = self.hit_handle(pos)
                cursors = {"nw": Qt.CursorShape.SizeFDiagCursor, "se": Qt.CursorShape.SizeFDiagCursor,
                    "ne": Qt.CursorShape.SizeBDiagCursor, "sw": Qt.CursorShape.SizeBDiagCursor,
                    "n": Qt.CursorShape.SizeVerCursor, "s": Qt.CursorShape.SizeVerCursor,
                    "w": Qt.CursorShape.SizeHorCursor, "e": Qt.CursorShape.SizeHorCursor}
                self.viewport().setCursor(cursors.get(handle, Qt.CursorShape.SizeAllCursor if self.hit_region(point) else Qt.CursorShape.CrossCursor))
            return super().mouseMoveEvent(event)
        gesture = self.gesture
        if gesture["kind"] == "pan":
            delta = pos - gesture["last"]
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            gesture["last"] = pos
            self.fit_mode = False
            return
        if gesture["kind"] == "draw":
            if not gesture["uid"]:
                if (pos - gesture["viewport_start"]).manhattanLength() < 4:
                    return
                region = Region(0, 0, 1, 1, f"选区_{self.serial:03d}")
                self.serial += 1
                self.regions.append(region)
                gesture["uid"] = region.uid
                self.set_active(region.uid)
            end = self.bounded_point(point)
            start = gesture["start"]
            bounds = new_bounds(start.x(), start.y(), end.x(), end.y(), self.image.width(), self.image.height())
        else:
            original = gesture["original"]
            dx, dy = point.x() - gesture["start"].x(), point.y() - gesture["start"].y()
            if gesture["kind"] == "move":
                bounds = moved_bounds(original, dx, dy, self.image.width(), self.image.height())
            else:
                bounds = resized_bounds(original, gesture["handle"], dx, dy, self.image.width(), self.image.height())
        if self.active:
            self.active.x, self.active.y, self.active.width, self.active.height = bounds
            self.geometry_changed.emit()
            self.viewport().update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if not self.gesture:
            return super().mouseReleaseEvent(event)
        if event.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            return super().mouseReleaseEvent(event)
        gesture = self.gesture
        self.gesture = None
        if gesture["kind"] != "pan":
            self.committed.emit()
            if gesture["kind"] == "draw" and gesture["uid"]:
                self.set_mode("select")
        self.refresh_cursor()
        event.accept()

    def wheelEvent(self, event):
        if self.image.isNull():
            return
        self.set_zoom(self.zoom * (1.15 ** (event.angleDelta().y() / 120)), event.position().toPoint())
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.space_down = True
            self.refresh_cursor()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            if self.gesture:
                gesture = self.gesture
                self.gesture = None
                if gesture["kind"] == "draw" and gesture["uid"]:
                    self.regions = [r for r in self.regions if r.uid != gesture["uid"]]
                    self.set_active("")
                elif gesture["kind"] in ("move", "resize"):
                    old = gesture["original"]
                    for i, r in enumerate(self.regions):
                        if r.uid == old.uid:
                            self.regions[i] = old
                    self.geometry_changed.emit()
                self.viewport().update()
            self.set_mode("select")
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.space_down = False
            self.refresh_cursor()
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.space_down = False
        self.refresh_cursor()
        super().focusOutEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and event.mimeData().urls()[0].isLocalFile():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.file_dropped.emit(event.mimeData().urls()[0].toLocalFile())
            event.acceptProposedAction()


STYLE = """
QMainWindow, QWidget { background: #1d2430; color: #e6edf8; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 10pt; }
QToolBar { border: none; border-bottom: 1px solid #344055; background: #252f3f; spacing: 6px; padding: 10px 8px; }
QToolButton { padding: 7px 10px; border: 1px solid transparent; border-radius: 5px; }
QToolButton:hover { background: #344461; } QToolButton:checked { background: #31528a; border-color: #5b91ef; }
QToolButton:disabled, QPushButton:disabled { color: #68768e; }
QPushButton { border: 1px solid #43536b; border-radius: 5px; padding: 7px 12px; background: #2b374b; }
QPushButton:hover { background: #354963; } QPushButton#primary { background: #3874d9; border-color: #4f8cff; color: white; }
QListWidget { background: #19212e; border: 1px solid #344055; border-radius: 7px; outline: none; padding: 5px; }
QListWidget::item { padding: 8px 4px; margin: 2px; border: 1px solid transparent; border-radius: 5px; }
QListWidget::item:selected { background: #2c446a; border-color: #4f8cff; color: #ffffff; } QListWidget::item:hover { background: #27374d; }
QLineEdit, QSpinBox, QDoubleSpinBox { background: #161f2d; border: 1px solid #43536b; border-radius: 4px; padding: 5px; selection-background-color: #3874d9; }
QLabel#heading { font-size: 12pt; font-weight: bold; } QLabel#muted { color: #96a5bd; }
QSplitter::handle { background: #344055; width: 2px; } QStatusBar { background: #252f3f; color: #aab9d0; }
QToolTip { background: #314159; color: white; border: 1px solid #617799; padding: 5px; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(make_icon())
        self.resize(1280, 820)
        self.setMinimumSize(960, 640)
        self.image_path = None
        self.last_export_dir = ""
        self.history = [[]]
        self.history_index = 0
        self.saved_state = []
        self.canvas = Canvas()
        self._build_toolbar()
        self._build_body()
        self._build_status()
        self.setStyleSheet(STYLE)
        self.canvas.committed.connect(self.commit)
        self.canvas.active_changed.connect(self.sync_selection)
        self.canvas.geometry_changed.connect(self.sync_inspector)
        self.canvas.zoom_changed.connect(self.sync_zoom)
        self.canvas.mode_changed.connect(lambda mode: self.mode_actions[mode].setChecked(True))
        self.canvas.pointer_changed.connect(self.pointer_label.setText)
        self.canvas.file_dropped.connect(self.open_path)
        self.refresh_list()
        self.update_actions()

    def action(self, text, callback, shortcut=None):
        action = QAction(text, self)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        return action

    def _build_toolbar(self):
        toolbar = QToolBar("操作", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.open_action = self.action("打开图片", self.open_dialog, "Ctrl+O")
        toolbar.addAction(self.open_action)
        toolbar.addSeparator()
        self.mode_actions = {}
        group = QActionGroup(self)
        group.setExclusive(True)
        for mode, label, key in [("select", "选择 / 调整", "V"), ("draw", "添加框选", "N"), ("pan", "平移", "H")]:
            action = self.action(label, lambda checked=False, m=mode: self.canvas.set_mode(m))
            shortcut = QShortcut(QKeySequence(key), self.canvas)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda m=mode: self.canvas.set_mode(m))
            action.setCheckable(True)
            action.setToolTip(f"{label}（{key}）")
            group.addAction(action)
            toolbar.addAction(action)
            self.mode_actions[mode] = action
        self.mode_actions["select"].setChecked(True)
        toolbar.addSeparator()
        self.undo_action = self.action("撤销", self.undo, "Ctrl+Z")
        self.redo_action = self.action("重做", self.redo, "Ctrl+Y")
        toolbar.addActions([self.undo_action, self.redo_action])
        toolbar.addSeparator()
        self.export_one_action = self.action("导出选中", lambda: self.export(False), "Ctrl+E")
        self.export_all_action = self.action("全部导出", lambda: self.export(True), "Ctrl+Shift+E")
        toolbar.addActions([self.export_one_action, self.export_all_action])
        self.delete_action = self.action("删除选区", self.delete_active)
        self.addAction(self.delete_action)
        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction(self.open_action)
        file_menu.addSeparator()
        file_menu.addActions([self.export_one_action, self.export_all_action])
        file_menu.addSeparator()
        file_menu.addAction(self.action("退出", self.close, "Alt+F4"))
        edit_menu = self.menuBar().addMenu("编辑")
        edit_menu.addActions([self.undo_action, self.redo_action, self.delete_action])
        help_menu = self.menuBar().addMenu("帮助")
        help_menu.addAction(self.action("使用说明", self.show_help))

    def _build_body(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        panel = QWidget()
        panel.setMinimumWidth(270)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        header = QHBoxLayout()
        self.count_label = QLabel("框选列表 · 0")
        self.count_label.setObjectName("heading")
        header.addWidget(self.count_label)
        header.addStretch()
        self.clear_button = QPushButton("清空")
        self.clear_button.clicked.connect(self.clear_regions)
        header.addWidget(self.clear_button)
        layout.addLayout(header)
        self.region_list = QListWidget()
        self.region_list.setIconSize(QSize(72, 60))
        self.region_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.region_list.currentItemChanged.connect(self.list_selected)
        self.region_list.itemDoubleClicked.connect(lambda item: self.name_edit.setFocus())
        self.region_list.setMinimumHeight(160)
        for widget in (self.region_list, self.canvas):
            shortcut = QShortcut(QKeySequence("Delete"), widget)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self.delete_active)
        layout.addWidget(self.region_list, 1)
        self.empty_list_hint = QLabel("在右侧图片上拖动，即可创建选区")
        self.empty_list_hint.setObjectName("muted")
        self.empty_list_hint.setWordWrap(True)
        layout.addWidget(self.empty_list_hint)
        detail_title = QLabel("选区属性")
        detail_title.setObjectName("heading")
        layout.addWidget(detail_title)
        self.inspector = QWidget()
        form = QFormLayout(self.inspector)
        form.setContentsMargins(0, 0, 0, 0)
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(100)
        self.name_edit.setPlaceholderText("选择一个框选")
        self.name_edit.editingFinished.connect(self.rename_active)
        form.addRow("名称", self.name_edit)
        self.spins = {}
        for field, label in [("x", "X 坐标"), ("y", "Y 坐标"), ("width", "宽度"), ("height", "高度")]:
            spin = QSpinBox()
            spin.setRange(0, 1000000)
            spin.setSuffix(" px")
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda value, f=field: self.edit_geometry(f, value))
            self.spins[field] = spin
            form.addRow(label, spin)
        layout.addWidget(self.inspector)
        row = QHBoxLayout()
        self.delete_button = QPushButton("删除选区")
        self.delete_button.clicked.connect(self.delete_active)
        self.export_button = QPushButton("导出选中")
        self.export_button.setObjectName("primary")
        self.export_button.clicked.connect(lambda: self.export(False))
        row.addWidget(self.delete_button)
        row.addWidget(self.export_button)
        layout.addLayout(row)
        hint = QLabel("滚轮缩放 · 空格 / 中键拖动平移\nN 新建框选 · V 调整 · Delete 删除\nCtrl+Z 撤销 · PNG 保留原图透明度")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        view_bar = QWidget()
        view_layout = QHBoxLayout(view_bar)
        view_layout.setContentsMargins(16, 8, 16, 8)
        self.file_label = QLabel("未打开图片")
        self.file_label.setObjectName("muted")
        self.file_label.setMinimumWidth(0)
        view_layout.addWidget(self.file_label, 1)
        self.zoom_spin = QDoubleSpinBox()
        self.zoom_spin.setRange(0.5, 3200)
        self.zoom_spin.setDecimals(1)
        self.zoom_spin.setSuffix(" %")
        self.zoom_spin.setValue(100)
        self.zoom_spin.setKeyboardTracking(False)
        self.zoom_spin.setFixedWidth(106)
        self.zoom_spin.valueChanged.connect(lambda value: self.canvas.set_zoom(value / 100))
        view_layout.addWidget(self.zoom_spin)
        self.fit_button = QPushButton("适应窗口")
        self.fit_button.clicked.connect(self.canvas.fit_image)
        view_layout.addWidget(self.fit_button)
        self.actual_button = QPushButton("1:1")
        self.actual_button.clicked.connect(lambda: self.canvas.set_zoom(1))
        view_layout.addWidget(self.actual_button)
        right_layout.addWidget(view_bar)
        right_layout.addWidget(self.canvas, 1)
        splitter.addWidget(panel)
        splitter.addWidget(right)
        splitter.setSizes([320, 960])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)
        self.setCentralWidget(splitter)

    def _build_status(self):
        self.statusBar().showMessage("打开图片后，在右侧拖动框选；导出不会修改原图")
        self.pointer_label = QLabel("")
        self.image_info = QLabel("原图像素导出")
        self.statusBar().addPermanentWidget(self.pointer_label)
        self.statusBar().addPermanentWidget(self.image_info)

    def snapshot(self):
        return [r.snapshot() for r in self.canvas.regions]

    def commit(self):
        state = self.snapshot()
        if state != self.history[self.history_index]:
            self.history = self.history[:self.history_index + 1] + [state]
            self.history_index += 1
        self.refresh_list()
        self.update_actions()

    def restore(self):
        uid = self.canvas.active_uid
        self.canvas.regions = [Region(**r) for r in self.history[self.history_index]]
        self.canvas.set_active(uid if any(r.uid == uid for r in self.canvas.regions) else (self.canvas.regions[-1].uid if self.canvas.regions else ""))
        self.refresh_list()
        self.update_actions()

    def undo(self):
        if self.history_index > 0:
            self.history_index -= 1
            self.restore()

    def redo(self):
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.restore()

    def refresh_list(self):
        self.region_list.blockSignals(True)
        self.region_list.clear()
        for index, region in enumerate(self.canvas.regions, 1):
            crop = self.canvas.image.copy(region.x, region.y, region.width, region.height)
            thumbnail = QPixmap.fromImage(crop).scaled(72, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            item = QListWidgetItem(QIcon(thumbnail), f"{index:02d}  {region.name}\n{region.width} × {region.height} px")
            item.setData(Qt.ItemDataRole.UserRole, region.uid)
            item.setToolTip(f"{region.name}\nX {region.x}, Y {region.y} · {region.width} × {region.height} px\n双击后可在属性中修改名称")
            self.region_list.addItem(item)
            if region.uid == self.canvas.active_uid:
                self.region_list.setCurrentItem(item)
        self.region_list.blockSignals(False)
        count = len(self.canvas.regions)
        self.count_label.setText(f"框选列表 · {count}")
        self.empty_list_hint.setVisible(count == 0)
        self.sync_inspector()
        self.canvas.viewport().update()

    def sync_selection(self, uid):
        self.region_list.blockSignals(True)
        self.region_list.setCurrentRow(-1)
        for index in range(self.region_list.count()):
            if self.region_list.item(index).data(Qt.ItemDataRole.UserRole) == uid:
                self.region_list.setCurrentRow(index)
                break
        self.region_list.blockSignals(False)
        self.sync_inspector()
        self.update_actions()

    def list_selected(self, item, previous):
        self.canvas.set_active(item.data(Qt.ItemDataRole.UserRole) if item else "")
        self.canvas.set_mode("select")
        if self.canvas.active:
            r = self.canvas.active
            self.canvas.ensureVisible(QRectF(r.x, r.y, r.width, r.height), 30, 30)

    def sync_inspector(self):
        region = self.canvas.active
        self.inspector.setEnabled(region is not None)
        self.name_edit.blockSignals(True)
        self.name_edit.setText(region.name if region else "")
        self.name_edit.blockSignals(False)
        for field, spin in self.spins.items():
            spin.blockSignals(True)
            if region:
                if field == "x":
                    spin.setRange(0, self.canvas.image.width() - region.width)
                elif field == "y":
                    spin.setRange(0, self.canvas.image.height() - region.height)
                elif field == "width":
                    spin.setRange(1, self.canvas.image.width() - region.x)
                else:
                    spin.setRange(1, self.canvas.image.height() - region.y)
                spin.setValue(getattr(region, field))
            else:
                spin.setRange(0, 1000000)
                spin.setValue(0)
            spin.blockSignals(False)

    def sync_zoom(self, value):
        self.zoom_spin.blockSignals(True)
        self.zoom_spin.setValue(value * 100)
        self.zoom_spin.blockSignals(False)

    def update_actions(self):
        loaded = not self.canvas.image.isNull()
        active = self.canvas.active is not None
        self.undo_action.setEnabled(self.history_index > 0)
        self.redo_action.setEnabled(self.history_index < len(self.history) - 1)
        self.export_one_action.setEnabled(active)
        self.export_all_action.setEnabled(bool(self.canvas.regions))
        self.delete_action.setEnabled(active)
        self.export_button.setEnabled(active)
        self.delete_button.setEnabled(active)
        self.clear_button.setEnabled(bool(self.canvas.regions))
        for action in self.mode_actions.values():
            action.setEnabled(loaded)
        for widget in (self.zoom_spin, self.fit_button, self.actual_button):
            widget.setEnabled(loaded)
        dirty = self.snapshot() != self.saved_state
        title = f"{self.image_path.name} — {APP_TITLE}" if self.image_path else APP_TITLE
        self.setWindowTitle(("* " if dirty else "") + title)

    def rename_active(self):
        if self.canvas.active:
            name = self.name_edit.text().strip()
            if name:
                self.canvas.active.name = name
                self.commit()
            else:
                self.sync_inspector()

    def edit_geometry(self, field, value):
        if self.canvas.active:
            setattr(self.canvas.active, field, value)
            self.commit()

    def delete_active(self):
        uid = self.canvas.active_uid
        if not uid:
            return
        self.canvas.regions = [r for r in self.canvas.regions if r.uid != uid]
        self.canvas.set_active(self.canvas.regions[-1].uid if self.canvas.regions else "")
        self.commit()

    def clear_regions(self):
        if not self.canvas.regions:
            return
        answer = QMessageBox.question(self, "清空框选", "清空全部框选？清空后可以按 Ctrl+Z 撤销。")
        if answer == QMessageBox.StandardButton.Yes:
            self.canvas.regions = []
            self.canvas.set_active("")
            self.commit()

    def confirm_discard(self):
        if self.snapshot() == self.saved_state:
            return True
        answer = QMessageBox.question(self, "尚有未导出的框选",
            "有新增或修改的框选尚未全部导出。继续将丢弃当前框选，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开图片", str(self.image_path.parent) if self.image_path else "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff *.gif);;所有文件 (*)")
        if path:
            self.open_path(path)

    def open_path(self, path):
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            QMessageBox.warning(self, "无法打开图片", f"无法读取该图片：\n{path}\n\n{reader.errorString()}")
            return False
        if not self.confirm_discard():
            return False
        self.image_path = Path(path)
        self.canvas.set_image(image)
        self.history = [[]]
        self.history_index = 0
        self.saved_state = []
        self.file_label.setText(self.image_path.name)
        self.file_label.setToolTip(str(self.image_path))
        self.image_info.setText(f"{image.width()} × {image.height()} px")
        self.refresh_list()
        self.canvas.set_mode("draw")
        self.update_actions()
        self.statusBar().showMessage("拖动鼠标创建选区；完成后可拖动边框控制点调整大小")
        self.canvas.setFocus()
        return True

    def export(self, all_regions):
        regions = list(self.canvas.regions) if all_regions else ([self.canvas.active] if self.canvas.active else [])
        if not regions:
            return
        folder = QFileDialog.getExistingDirectory(self, "选择导出文件夹", self.last_export_dir or str(self.image_path.parent))
        if not folder:
            return
        self.last_export_dir = folder
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            written = export_regions(self.canvas.image, regions, folder)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        if all_regions or len(regions) == len(self.canvas.regions):
            self.saved_state = self.snapshot()
        self.update_actions()
        self.statusBar().showMessage(f"已导出 {len(written)} 张 PNG 到 {folder}", 15000)
        box = QMessageBox(self)
        box.setWindowTitle("导出完成")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"已成功导出 {len(written)} 张 PNG 图片")
        box.setInformativeText(f"{folder}\n\n按原图像素裁剪，重名文件自动编号，不覆盖已有文件。")
        open_button = box.addButton("打开文件夹", QMessageBox.ButtonRole.ActionRole)
        box.addButton("完成", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() == open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def show_help(self):
        QMessageBox.information(self, "使用说明",
            "1. 打开或拖入图片。\n2. 在原图上按住左键拖动，新建矩形框选。\n3. 框选结束后自动切换到调整模式；拖动内部移动，拖动八个控制点调整大小。\n4. 按 N 可在已有选区上继续框选；空白处也可直接新建。\n5. 左侧列表切换选区，属性区可修改名称、坐标和尺寸。\n6. 导出选中或全部导出，每个选区生成一张 PNG。\n\n滚轮：缩放；空格+拖动或中键：平移；Esc：取消当前拖动。\nCtrl+Z / Ctrl+Y：撤销 / 重做；Delete：删除。\nCtrl+E / Ctrl+Shift+E：导出选中 / 全部导出。\n\n裁剪保留框内背景和原始透明度，不会自动抠图。\n动态图片仅使用第一帧；原图文件不会被修改。")

    def closeEvent(self, event):
        if self.confirm_discard():
            event.accept()
        else:
            event.ignore()


def run():
    app = QApplication(sys.argv)
    app.setApplicationName("CutImage")
    app.setOrganizationName("CutImage")
    app.setStyle("Fusion")
    log_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CutImage"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(log_dir / "error.log"), level=logging.ERROR, encoding="utf-8")

    def exception_hook(exc_type, exc, traceback):
        logging.error("Unhandled exception", exc_info=(exc_type, exc, traceback))
        QMessageBox.critical(None, "程序错误", f"{exc}\n\n详细日志：{log_dir / 'error.log'}")

    sys.excepthook = exception_hook
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        QTimer.singleShot(0, lambda: window.open_path(sys.argv[1]))
    return app.exec()
