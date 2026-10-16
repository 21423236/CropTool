# 图案框选工具 / CutImage

Windows 本地桌面工具，无浏览器、无服务端、不上传图片。

## 启动

双击 `dist\CutImage.exe`，或运行根目录的 `run.bat`。

## 使用

1. 点击「打开图片」，或把图片拖入右侧画布。
2. 在右侧原图上拖动左键，创建框选；可重复创建多个。
3. 创建后自动进入调整模式。拖动选区内部移动；拖动四角、四边中点调整大小。
4. 需要在已有框选上再框选时，点击「添加框选」或按 `N`。
5. 左侧列表显示缩略图和尺寸；点击切换选区。属性区支持名称、X/Y、宽/高精确编辑。
6. 「导出选中」或「全部导出」，选择文件夹，每个选区输出一张 PNG。

导出依据原图像素而非屏幕显示尺寸，保留透明度；保留矩形内背景，不自动抠图。重名自动添加编号，不覆盖已有文件。坐标以经过 EXIF 方向校正的图片左上角为原点。动态图片仅读取首帧。关闭或换图前会提醒尚未全部导出的改动；不保存框选工程文件。

## 快捷键

| 操作 | 快捷键 |
| --- | --- |
| 打开图片 | Ctrl+O |
| 新建框选 / 选择调整 / 平移 | N / V / H |
| 缩放 | 鼠标滚轮 |
| 临时平移 | 空格+左键拖动，或中键拖动 |
| 撤销 / 重做 | Ctrl+Z / Ctrl+Y |
| 取消当前拖动 | Esc |
| 删除选区 | Delete |
| 导出选中 / 全部 | Ctrl+E / Ctrl+Shift+E |

## 开发与构建

使用 Python 3.11+，在 PowerShell 运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

构建脚本安装隔离依赖、运行测试、生成图标并打包单文件 Windows GUI EXE。用户运行 EXE 不需要安装 Python。源码运行：`.\.venv\Scripts\python.exe main.py`。

异常日志位于 `%LOCALAPPDATA%\CutImage\error.log`。依赖锁定版本记录在 `requirements-lock.txt`。
