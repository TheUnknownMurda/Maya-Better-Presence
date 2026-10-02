"""
Exports the icons of this folder from .svg to .png, the format Discord accepts, at the size it recommends.

    mayapy export_icons.py

Discord downloads the icons from the GitHub repository (ICON_URL in module/scripts/RichPresenceUI/context.py),
so push the .png files after changing an icon.
"""
import pathlib
import sys

try:
    from PySide6 import QtCore, QtGui, QtSvg
except ImportError:
    from PySide2 import QtCore, QtGui, QtSvg

SIZE = 1024


def export(svg_path, png_path, size=SIZE):
    renderer = QtSvg.QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise RuntimeError(f"{svg_path.name} couldn't be read")
    image = QtGui.QImage(size, size, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    if not image.save(str(png_path)):
        raise RuntimeError(f"{png_path} couldn't be written")


def main():
    # Fonts, used by the renderer icons, need an application
    application = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication(sys.argv)
    for svg_path in sorted(pathlib.Path(__file__).resolve().parent.glob("*.svg")):
        export(svg_path, svg_path.with_suffix(".png"))
        print(svg_path.with_suffix(".png").name)


if __name__ == "__main__":
    main()
