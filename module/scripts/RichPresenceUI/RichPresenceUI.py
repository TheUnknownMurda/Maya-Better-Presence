"""
The Rich Presence menu in Maya's menu bar, and the settings window.

The window shows what friends see in Discord, read from the plug-in every second,
and every change is applied and saved right away.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

from maya import OpenMayaUI
from maya import cmds, mel

from . import context
from .Qt import QtWidgets, QtCore, QtGui, QtCompat


# scripts/RichPresenceUI/ inside the module. Found from this file rather than through Maya's module list,
# which the installer can't update during a session when the user's folder has an accent.
MODULE_PATH = Path(__file__).resolve().parents[2]
ICONS_PATH = Path(__file__).resolve().parent / "icons"

MENU_NAME = "RichPresenceMenu"
STATUS_MENU_ITEM = "RichPresenceStatusMenuItem"
PLACEHOLDERS = ("{task}", "{scene}", "{project}", "{stats}")

# Values understood by the richPresence command, with their label in the window
IDLE_ACTIONS = {"show": "Show “Idle”", "hide": "Hide my status", "off": "Do nothing"}
DEFAULT_IDLE_ACTION = "show"
DEFAULT_IDLE_MINUTES = 10
SMALL_ICONS = {"task": "Task", "renderer": "Renderer", "custom": "My image", "none": "None"}
DEFAULT_SMALL_ICON = "task"

# Switches of a new installation, also used by "Reset to defaults"
DEFAULT_SWITCHES = {"enabled": True, "task": True, "details": True, "state": True,
                    "reset_time_with_scene": True, "custom_text_while_idle": False}

DISCORD_PROCESSES = ("discord.exe", "discordptb.exe", "discordcanary.exe")

# The settings window, while it is open
_window = None


def maya_main_window():
    pointer = OpenMayaUI.MQtUtil.mainWindow()
    return QtCompat.wrapInstance(int(pointer), QtWidgets.QWidget) if pointer else None


def add_menu():
    if cmds.about(batch=True):
        return  # no menu bar without the user interface
    remove_menu()  # a menu left by a previous load would otherwise be duplicated
    maya_window = mel.eval('$tempMelVar=$gMainWindow')
    cmds.menu(MENU_NAME, label="Rich Presence", tearOff=True, parent=maya_window)
    cmds.menuItem(STATUS_MENU_ITEM, label="Show My Status in Discord", checkBox=TypedSettings().get("enabled"),
                  command=lambda *args: set_status_enabled(cmds.menuItem(STATUS_MENU_ITEM, query=True, checkBox=True)))
    cmds.menuItem(divider=True)
    cmds.menuItem(label="Settings...", command=lambda *args: show())


def remove_menu():
    if cmds.menu(MENU_NAME, exists=True):
        cmds.deleteUI(MENU_NAME, menu=True)


def set_status_enabled(enabled):
    """Shows or hides the status in Discord, from the menu or the settings window, and remembers it."""
    TypedSettings().set("enabled", enabled)
    cmds.richPresence(enabled=enabled)
    check_menu_item(enabled)
    if _window is not None:
        _window.show_enabled(enabled)


def check_menu_item(enabled):
    if not cmds.about(batch=True) and cmds.menuItem(STATUS_MENU_ITEM, exists=True):
        cmds.menuItem(STATUS_MENU_ITEM, edit=True, checkBox=enabled)


class TypedSettings(QtCore.QSettings):

    _CONFIG_PATH = MODULE_PATH / "config/config.ini"

    def __init__(self):
        super().__init__(self._CONFIG_PATH.as_posix(), QtCore.QSettings.Format.IniFormat)

    def get(self, setting: str, default=None):
        # INI files store booleans as text, and bool("false") would be True. A switch missing from the file
        # is read as the plug-in reads it: status and task shown, everything else off.
        if default is None:
            default = setting in ("enabled", "task")
        return self.value(setting, default, type=bool)

    def set(self, setting: str, value: bool):
        assert isinstance(value, bool)
        self.setValue(setting, value)

    def get_text(self, setting: str):
        return self.value(setting, "", type=str)

    def set_text(self, setting: str, value: str):
        self.setValue(setting, value)

    def get_idle_minutes(self):
        return self.value("idle_minutes", DEFAULT_IDLE_MINUTES, type=int)

    def get_idle_action(self):
        action = self.get_text("idle_action")
        return action if action in IDLE_ACTIONS else DEFAULT_IDLE_ACTION

    def get_small_icon(self):
        icon = self.get_text("small_icon")
        return icon if icon in SMALL_ICONS else DEFAULT_SMALL_ICON


def apply_saved_settings():
    """
    Sends the text settings to the plug-in when it loads. The plug-in reads the other settings itself,
    but Qt quotes and escapes some text in config.ini, so it is read back here with Qt.
    """
    settings = TypedSettings()
    cmds.richPresence(buttonLabel=settings.get_text("button_label"), buttonUrl=settings.get_text("button_url"),
                      idleMinutes=settings.get_idle_minutes(), idleAction=settings.get_idle_action(),
                      customDetails=settings.get_text("custom_details"), customState=settings.get_text("custom_state"),
                      smallIcon=settings.get_small_icon(),
                      smallIconUrl=usable_link(settings.get_text("small_icon_url")),
                      smallIconText=settings.get_text("small_icon_text"))


def unknown_placeholder(*texts):
    """Returns the first brace that isn't part of a known placeholder, like "{task]", or an empty string."""
    for text in texts:
        for placeholder in PLACEHOLDERS:
            text = text.replace(placeholder, " ")
        match = re.search(r"\{[^\s{}]*[}\])]?|\}", text)
        if match:
            return match.group()
    return ""


def link_problem(link):
    """Why a web link can't be used, or an empty string."""
    if not link.startswith(("https://", "http://")):
        return "must start with https://"
    if " " in link:
        return "can't contain spaces"
    return ""


def usable_link(link):
    """The link, or an empty string when Discord couldn't use it."""
    return link if link and not link_problem(link) else ""


def read_status():
    """What Discord is shown, as reported by the plug-in, or None when the plug-in isn't loaded."""
    try:
        lines = cmds.richPresence(preview=True) or []
    except Exception:
        return None
    return dict(line.split("=", 1) for line in lines if "=" in line)


class DiscordWatcher:
    """Tells whether the Discord app is open, from Windows' task list read without making Maya wait."""

    def __init__(self):
        self.running = True  # until told otherwise
        self._process = None

    def poll(self):
        """Called regularly: starts a check, or reads the result of the one started before."""
        if sys.platform != "win32":
            return
        if self._process is None:
            try:
                # Filtered on Discord's processes, so the short output never fills the pipe
                self._process = subprocess.Popen(
                    ["tasklist", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq discord*"], stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True, errors="ignore", creationflags=subprocess.CREATE_NO_WINDOW)
            except OSError:
                pass
            return
        if self._process.poll() is None:
            return
        output = self._process.stdout.read().lower()
        self._process.stdout.close()
        self._process = None
        self.running = any(f'"{name}"' in output for name in DISCORD_PROCESSES)


def uses_default_project():
    """True with Maya's own default project, which says nothing about the work."""
    try:
        root = cmds.workspace(query=True, rootDirectory=True)
        default = cmds.internalVar(userWorkspaceDir=True) + "default/"
        return root.lower() == default.lower()
    except Exception:
        return True


def show():
    """Opens the settings window, or brings it to the front when it is already open."""
    global _window
    if _window is not None:
        _window.showNormal()
        _window.raise_()
        _window.activateWindow()
        return
    _window = SettingsWindow(maya_main_window())
    _window.destroyed.connect(_forget_window)
    _window.show()


def _forget_window(*args):
    global _window
    _window = None


# ---------------------------------------------------------------------------------------------------------------
# Drawing


def rounded_pixmap(image, size, radius, ratio):
    """The image as a square of size logical pixels with rounded corners, sharp on high-density screens."""
    pixmap = QtGui.QPixmap(round(size * ratio), round(size * ratio))
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
    rect = QtCore.QRectF(0, 0, size * ratio, size * ratio)
    path = QtGui.QPainterPath()
    path.addRoundedRect(rect, radius * ratio, radius * ratio)
    painter.setClipPath(path)
    painter.drawImage(rect, image)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def badge_pixmap(image, size, ring, ring_color, ratio):
    """A round icon in a ring of the card's color, the way Discord draws the small image."""
    pixmap = QtGui.QPixmap(round(size * ratio), round(size * ratio))
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(QtGui.QColor(ring_color))
    painter.drawEllipse(QtCore.QRectF(0, 0, size * ratio, size * ratio))
    inner = QtCore.QRectF(ring * ratio, ring * ratio, (size - 2 * ring) * ratio, (size - 2 * ring) * ratio)
    path = QtGui.QPainterPath()
    path.addEllipse(inner)
    painter.setClipPath(path)
    if image is not None:
        painter.drawImage(inner, image)
    else:
        # The user's own image is on the web: a picture symbol stands for it
        painter.fillRect(inner, QtGui.QColor("#4E5058"))
        pen = QtGui.QPen(QtGui.QColor("white"), 1.6 * ratio)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        frame = inner.adjusted(inner.width() * 0.28, inner.height() * 0.3, -inner.width() * 0.28, -inner.height() * 0.3)
        painter.drawRoundedRect(frame, 1.5 * ratio, 1.5 * ratio)
        mountain = QtGui.QPainterPath()
        mountain.moveTo(frame.left(), frame.bottom())
        mountain.lineTo(frame.center().x() - frame.width() * 0.05, frame.top() + frame.height() * 0.45)
        mountain.lineTo(frame.right(), frame.bottom())
        painter.drawPath(mountain)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def icon_image(name):
    image = QtGui.QImage(str(ICONS_PATH / f"{name}.png"))
    return None if image.isNull() else image


def elapsed_text(start):
    seconds = max(0, int(time.time()) - int(start))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{seconds:02} elapsed" if hours else f"{minutes:02}:{seconds:02} elapsed"


# ---------------------------------------------------------------------------------------------------------------
# Controls


class Switch(QtWidgets.QCheckBox):
    """An on/off switch, in Discord's colors."""

    _ON = QtGui.QColor("#5865F2")
    _OFF = QtGui.QColor("#4E5058")
    _KNOB = QtGui.QColor("white")
    _FOCUS = QtGui.QColor("#8C96FF")

    def __init__(self, checked=False):
        super().__init__()
        self.setChecked(checked)
        self.setFixedSize(40, 22)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._position = float(checked)
        self._animation = QtCore.QPropertyAnimation(self, b"position")
        self._animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._animation.setDuration(120)
        self.toggled.connect(self._animate)

    def hitButton(self, position):
        return self.rect().contains(position)  # the whole switch reacts to clicks

    def _animate(self, checked):
        self._animation.stop()
        self._animation.setEndValue(float(checked))
        self._animation.start()

    def paintEvent(self, event):
        if self._animation.state() != QtCore.QAbstractAnimation.State.Running:
            self._position = float(self.isChecked())  # also follows changes made with signals blocked
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        track = QtCore.QRectF(1, 1, self.width() - 2, self.height() - 2)
        t = self._position
        color = QtGui.QColor(
            round(self._OFF.red() + (self._ON.red() - self._OFF.red()) * t),
            round(self._OFF.green() + (self._ON.green() - self._OFF.green()) * t),
            round(self._OFF.blue() + (self._ON.blue() - self._OFF.blue()) * t))
        painter.setPen(QtGui.QPen(self._FOCUS, 1.5) if self.hasFocus() else QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        diameter = track.height() - 6
        x = track.left() + 3 + (track.width() - diameter - 6) * t
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self._KNOB)
        painter.drawEllipse(QtCore.QRectF(x, track.top() + 3, diameter, diameter))

    def _get_position(self):
        return self._position

    def _set_position(self, value):
        self._position = value
        self.update()

    position = QtCore.Property(float, _get_position, _set_position)


class Segmented(QtWidgets.QFrame):
    """A choice between a few options, all visible at once."""

    changed = QtCore.Signal(str)

    def __init__(self, choices, value=None):
        super().__init__()
        self.setObjectName("segmented")
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self._buttons = {}
        self._value = None
        for key, label in choices.items():
            button = QtWidgets.QPushButton(label)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, key=key: self._pick(key))
            layout.addWidget(button)
            self._buttons[key] = button
        self.set_value(value if value in choices else next(iter(choices)))

    def value(self):
        return self._value

    def set_value(self, value):
        self._value = value
        for key, button in self._buttons.items():
            button.setChecked(key == value)

    def _pick(self, value):
        changed = value != self._value
        self.set_value(value)  # a click on the chosen option would otherwise uncheck it
        if changed:
            self.changed.emit(value)


class Card(QtWidgets.QFrame):
    """A group of settings, with a title and a short explanation."""

    changed = QtCore.Signal()

    def __init__(self, title, hint=""):
        super().__init__()
        self.setObjectName("card")
        self.content = QtWidgets.QVBoxLayout(self)
        self.content.setContentsMargins(16, 14, 16, 16)
        self.content.setSpacing(10)
        heading = QtWidgets.QVBoxLayout()
        heading.setSpacing(3)
        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("cardTitle")
        heading.addWidget(title_label)
        self.hint = QtWidgets.QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        heading.addWidget(self.hint)
        self.content.addLayout(heading)
        self.set_hint(hint)

    def set_hint(self, hint):
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))


class SwitchRow(QtWidgets.QWidget):
    """A switch, what it does, and an example underneath."""

    toggled = QtCore.Signal(bool)

    def __init__(self, label, example=""):
        super().__init__()
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(1)
        text = QtWidgets.QLabel(label)
        text.setObjectName("switchLabel")
        layout.addWidget(text, 0, 0)
        if example:
            example_label = QtWidgets.QLabel(example)
            example_label.setObjectName("hint")
            example_label.setWordWrap(True)
            layout.addWidget(example_label, 1, 0)
        self.switch = Switch()
        layout.addWidget(self.switch, 0, 1, 2 if example else 1, 1,
                         QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        layout.setColumnStretch(0, 1)
        self.switch.toggled.connect(self.toggled)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        # A click on the text works too, not only on the switch.
        # position() only exists in Qt 6, Maya 2023 and 2024 still use Qt 5.
        position = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self.rect().contains(position):
            self.switch.toggle()
        super().mouseReleaseEvent(event)

    def is_on(self):
        return self.switch.isChecked()

    def set_on(self, on):
        self.switch.blockSignals(True)
        self.switch.setChecked(on)
        self.switch.blockSignals(False)
        self.switch.update()


class PlaceholderBar(QtWidgets.QWidget):
    """Buttons inserting in a text field a placeholder that Discord shows as its value."""

    BUTTONS = (("{task}", "Task", "What you're doing, like Modeling"),
               ("{scene}", "Scene", "The scene's name, like hero.ma"),
               ("{project}", "Project", "The project's name"),
               ("{stats}", "Stats", "The size of the scene, like 12 objects · 45.2k polygons"))

    def __init__(self, field):
        super().__init__()
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label = QtWidgets.QLabel("Insert")
        label.setObjectName("hint")
        layout.addWidget(label)
        for placeholder, name, tip in self.BUTTONS:
            button = QtWidgets.QPushButton(name)
            button.setObjectName("chip")
            button.setToolTip(f"{placeholder}: {tip}")
            button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)  # keeps the text cursor in the field
            button.clicked.connect(lambda checked=False, text=placeholder: self._insert(field, text))
            layout.addWidget(button)
        layout.addStretch()

    @staticmethod
    def _insert(field, text):
        field.insert(text)
        field.setFocus()


def text_field(placeholder, max_length):
    field = QtWidgets.QLineEdit()
    field.setPlaceholderText(placeholder)
    field.setMaxLength(max_length)
    field.setClearButtonEnabled(True)
    return field


def message_label(kind):
    label = QtWidgets.QLabel()
    label.setObjectName(kind)
    label.setWordWrap(True)
    label.hide()
    return label


def show_message(label, text):
    label.setText(text)
    label.setVisible(bool(text))


def set_text_quietly(field, text):
    field.blockSignals(True)
    field.setText(text)
    field.blockSignals(False)


# ---------------------------------------------------------------------------------------------------------------
# Groups of settings


class LineCard(Card):
    """A line of the status: automatic, set with switches, or the user's own text."""

    def __init__(self, title, hint, switches, example):
        super().__init__(title, hint)
        self.mode = Segmented({"auto": "Automatic", "custom": "My own text"})
        self.content.addWidget(self.mode)

        self._automatic = QtWidgets.QWidget()
        automatic_layout = QtWidgets.QVBoxLayout(self._automatic)
        automatic_layout.setContentsMargins(0, 2, 0, 0)
        automatic_layout.setSpacing(10)
        self.switches = {}
        for key, (label, example_text) in switches.items():
            row = SwitchRow(label, example_text)
            row.toggled.connect(self.changed)
            automatic_layout.addWidget(row)
            self.switches[key] = row
        self.content.addWidget(self._automatic)

        self._custom = QtWidgets.QWidget()
        custom_layout = QtWidgets.QVBoxLayout(self._custom)
        custom_layout.setContentsMargins(0, 2, 0, 0)
        custom_layout.setSpacing(6)
        self.field = text_field(f"e.g. {example}", 128)
        custom_layout.addWidget(self.field)
        custom_layout.addWidget(PlaceholderBar(self.field))
        self.note = message_label("warning")
        custom_layout.addWidget(self.note)
        self.content.addWidget(self._custom)

        # Text suggested when "My own text" is chosen, so the line doesn't start empty
        self.suggestion = ""
        self.mode.changed.connect(self._mode_changed)
        self.field.textChanged.connect(self._text_changed)

    def load(self, text, switches):
        for key, on in switches.items():
            self.switches[key].set_on(on)
        set_text_quietly(self.field, text)
        self.mode.set_value("custom" if text else "auto")
        self._show_mode()
        self._check_text()

    def text(self):
        """The text for the plug-in: empty for the automatic text."""
        return self.field.text().strip() if self.mode.value() == "custom" else ""

    def _mode_changed(self, mode):
        if mode == "custom" and not self.field.text().strip():
            set_text_quietly(self.field, self.suggestion)
        self._show_mode()
        self._check_text()
        if mode == "custom":
            self.field.setFocus()
            self.field.end(False)
        self.changed.emit()

    def _show_mode(self):
        custom = self.mode.value() == "custom"
        self._automatic.setVisible(not custom)
        self._custom.setVisible(custom)

    def _text_changed(self):
        self._check_text()
        self.changed.emit()

    def _check_text(self):
        text = self.field.text().strip()
        typo = unknown_placeholder(text)
        if typo:
            show_message(self.note, f"“{typo}” isn't a placeholder and will be shown as is. "
                                    f"Use the buttons above to insert one.")
        elif not text:
            show_message(self.note, "Empty: the automatic text is shown.")
        elif "{project}" in text and uses_default_project():
            show_message(self.note, "No project is set in Maya (File > Set Project), so {project} is empty.")
        else:
            show_message(self.note, "")


class IconCard(Card):
    """The small round icon on the Maya logo."""

    HINTS = {
        "task": "Changes with what you're doing. Hovering it shows the tool, the frame range or the renderer.",
        "renderer": "Your renderer's badge, with its version when hovering it.",
        "custom": "Your own picture, like your logo: a link to a PNG or JPG image on the web.",
        "none": "Only the Maya logo is shown.",
    }

    def __init__(self):
        super().__init__("Small icon")
        self.mode = Segmented(SMALL_ICONS)
        self.content.addWidget(self.mode)
        self.explanation = QtWidgets.QLabel()
        self.explanation.setObjectName("hint")
        self.explanation.setWordWrap(True)
        self.content.addWidget(self.explanation)

        self._custom = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(self._custom)
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.link = text_field("https://.../my-logo.png", 256)
        self.hover = text_field("e.g. {task} on {scene}", 128)
        grid.addWidget(QtWidgets.QLabel("Image link"), 0, 0)
        grid.addWidget(self.link, 0, 1)
        self.link_error = message_label("error")
        grid.addWidget(self.link_error, 1, 1)
        grid.addWidget(QtWidgets.QLabel("On hover"), 2, 0)
        grid.addWidget(self.hover, 2, 1)
        grid.addWidget(PlaceholderBar(self.hover), 3, 1)
        self.hover_note = message_label("warning")
        grid.addWidget(self.hover_note, 4, 1)
        grid.setColumnStretch(1, 1)
        self.content.addWidget(self._custom)

        self.mode.changed.connect(self._mode_changed)
        self.link.textChanged.connect(self._fields_changed)
        self.hover.textChanged.connect(self._fields_changed)

    def load(self, icon, link, hover):
        self.mode.set_value(icon)
        set_text_quietly(self.link, link)
        set_text_quietly(self.hover, hover)
        self._show_mode()
        self._check()

    def choice(self):
        return self.mode.value()

    def link_text(self):
        return self.link.text().strip()

    def hover_text(self):
        return self.hover.text().strip()

    def _mode_changed(self, mode):
        self._show_mode()
        self._check()
        if mode == "custom" and not self.link_text():
            self.link.setFocus()
        self.changed.emit()

    def _fields_changed(self):
        self._check()
        self.changed.emit()

    def _show_mode(self):
        self.explanation.setText(self.HINTS[self.choice()])
        self._custom.setVisible(self.choice() == "custom")

    def _check(self):
        link = self.link_text()
        if not link:
            show_message(self.link_error, "Paste the link of your image to show it.")
        elif link_problem(link):
            show_message(self.link_error, f"The link {link_problem(link)}.")
        else:
            show_message(self.link_error, "")
        typo = unknown_placeholder(self.hover_text())
        show_message(self.hover_note, f"“{typo}” isn't a placeholder and will be shown as is." if typo else "")


class ButtonCard(Card):
    """A button under the status, for friends."""

    def __init__(self):
        super().__init__("Button", "A link under your status that your friends can click, like your portfolio. "
                                   "Discord doesn't show it to you.")
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.label_field = text_field("My portfolio", 32)
        self.link = text_field("https://www.artstation.com/...", 512)
        grid.addWidget(QtWidgets.QLabel("Text"), 0, 0)
        grid.addWidget(self.label_field, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Link"), 1, 0)
        grid.addWidget(self.link, 1, 1)
        self.error = message_label("error")
        grid.addWidget(self.error, 2, 1)
        grid.setColumnStretch(1, 1)
        self.content.addLayout(grid)
        self.label_field.textChanged.connect(self._fields_changed)
        self.link.textChanged.connect(self._fields_changed)

    def load(self, label, link):
        set_text_quietly(self.label_field, label)
        set_text_quietly(self.link, link)
        self._check()

    def label(self):
        return self.label_field.text().strip()

    def link_text(self):
        return self.link.text().strip()

    def _fields_changed(self):
        self._check()
        self.changed.emit()

    def _check(self):
        label, link = self.label(), self.link_text()
        if bool(label) != bool(link):
            show_message(self.error, "Fill in both the text and the link to show the button.")
        elif link and link_problem(link):
            show_message(self.error, f"The link {link_problem(link)}.")
        else:
            show_message(self.error, "")


class AwayCard(Card):
    """What happens when Maya isn't used for a while."""

    def __init__(self):
        super().__init__("When you're away", "The timer pauses while you don't use Maya, "
                                             "and the time away isn't counted.")
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QtWidgets.QLabel("After"))
        self.minutes = QtWidgets.QSpinBox()
        self.minutes.setRange(1, 240)
        self.minutes.setSuffix(" min")
        self.minutes.setFixedWidth(100)
        row.addWidget(self.minutes)
        row.addWidget(QtWidgets.QLabel("without using Maya:"))
        row.addStretch()
        self.content.addLayout(row)
        self.action = Segmented(IDLE_ACTIONS)
        self.content.addWidget(self.action)
        self.keep = SwitchRow("Keep my own text", "Otherwise the first line says Idle.")
        self.content.addWidget(self.keep)
        self.minutes.valueChanged.connect(self.changed)
        self.action.changed.connect(self.changed)
        self.keep.toggled.connect(self.changed)

    def load(self, minutes, action, keep):
        self.minutes.blockSignals(True)
        self.minutes.setValue(minutes)
        self.minutes.blockSignals(False)
        self.action.set_value(action)
        self.keep.set_on(keep)


class TimerCard(Card):
    """When the timer of the status starts."""

    def __init__(self):
        super().__init__("Timer")
        self.restart = SwitchRow("Restart it for each scene", "Otherwise it counts the time since Maya was opened.")
        self.content.addWidget(self.restart)
        self.restart.toggled.connect(self.changed)


# ---------------------------------------------------------------------------------------------------------------
# Preview


class PreviewPanel(QtWidgets.QFrame):
    """What friends see in Discord, read from the plug-in."""

    _LOGO_SIZE = 72
    _BADGE_SIZE = 30

    def __init__(self):
        super().__init__()
        self.setObjectName("previewPanel")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        title = QtWidgets.QLabel("WHAT YOUR FRIENDS SEE")
        title.setObjectName("sectionLabel")
        layout.addWidget(title)

        self.banner = message_label("banner")
        layout.addWidget(self.banner)
        self.hidden_note = message_label("hiddenNote")
        layout.addWidget(self.hidden_note)

        self.card = QtWidgets.QFrame()
        self.card.setObjectName("activityCard")
        card_layout = QtWidgets.QVBoxLayout(self.card)
        card_layout.setContentsMargins(12, 10, 12, 12)
        card_layout.setSpacing(10)
        header = QtWidgets.QLabel("PLAYING")
        header.setObjectName("activityHeader")
        card_layout.addWidget(header)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(12)
        images = QtWidgets.QWidget()
        images.setFixedSize(self._LOGO_SIZE + 8, self._LOGO_SIZE + 8)
        self.logo = QtWidgets.QLabel(images)
        self.logo.setGeometry(0, 0, self._LOGO_SIZE, self._LOGO_SIZE)
        self.badge = QtWidgets.QLabel(images)
        offset = self._LOGO_SIZE + 8 - self._BADGE_SIZE
        self.badge.setGeometry(offset, offset, self._BADGE_SIZE, self._BADGE_SIZE)
        row.addWidget(images, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        texts = QtWidgets.QVBoxLayout()
        texts.setSpacing(2)
        name = QtWidgets.QLabel("Autodesk Maya")
        name.setObjectName("activityName")
        texts.addWidget(name)
        self.details = QtWidgets.QLabel()
        self.state = QtWidgets.QLabel()
        self.timer = QtWidgets.QLabel()
        for label, kind in ((self.details, "activityLine"), (self.state, "activityLine"), (self.timer, "activityTimer")):
            label.setObjectName(kind)
            label.setWordWrap(True)
            texts.addWidget(label)
        row.addLayout(texts, 1)
        row.setAlignment(texts, QtCore.Qt.AlignmentFlag.AlignTop)
        card_layout.addLayout(row)
        # As tall as its content: the space left in the panel goes below the hover texts
        self.card.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)
        self.button = QtWidgets.QLabel()
        self.button.setObjectName("activityButton")
        self.button.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.button)
        layout.addWidget(self.card)

        hover_title = QtWidgets.QLabel("WHEN HOVERING")
        hover_title.setObjectName("sectionLabel")
        layout.addWidget(hover_title)
        hover = QtWidgets.QGridLayout()
        hover.setHorizontalSpacing(10)
        hover.setVerticalSpacing(6)
        self.badge_text = QtWidgets.QLabel()
        self.logo_text = QtWidgets.QLabel()
        for line, (caption, label) in enumerate((("Small icon", self.badge_text), ("Maya logo", self.logo_text))):
            caption_label = QtWidgets.QLabel(caption.upper())
            caption_label.setObjectName("hoverName")
            hover.addWidget(caption_label, line, 0, QtCore.Qt.AlignmentFlag.AlignTop)
            label.setObjectName("hoverText")
            label.setWordWrap(True)
            hover.addWidget(label, line, 1)
        hover.setColumnStretch(1, 1)
        layout.addLayout(hover)
        layout.addStretch()
        note = QtWidgets.QLabel("Discord updates your status every few seconds at most.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._logo_image = icon_image("maya")
        self._shown_badge = None
        self._ratio = None

    def show_status(self, status, discord_running):
        show_message(self.banner, "" if discord_running else
                     "Discord isn't open. Your status shows up as soon as the Discord app runs.")
        if status is None:
            status = {"hidden": "unloaded"}
        hidden = status.get("hidden", "")
        show_message(self.hidden_note, {
            "off": "Your status is hidden. Turn on “Show my status” to show it again.",
            "away": "Hidden while you're away. It comes back as soon as you use Maya.",
            "unloaded": "The plug-in isn't loaded: load DRPForMaya.mll in the Plug-in Manager.",
        }.get(hidden, ""))
        # A hidden status is drawn faded. The effect is only set then, since it blurs text a little.
        if hidden and self.card.graphicsEffect() is None:
            fade = QtWidgets.QGraphicsOpacityEffect(self.card)
            fade.setOpacity(0.35)
            self.card.setGraphicsEffect(fade)
        elif not hidden and self.card.graphicsEffect() is not None:
            self.card.setGraphicsEffect(None)

        # Drawn again at the density of the screen the window is on
        ratio = self.devicePixelRatioF()
        if ratio != self._ratio:
            self._ratio = ratio
            self._shown_badge = None
            if self._logo_image is not None:
                self.logo.setPixmap(rounded_pixmap(self._logo_image, self._LOGO_SIZE, 8, ratio))
        for label, key in ((self.details, "details"), (self.state, "state")):
            label.setText(status.get(key, ""))
            label.setVisible(bool(status.get(key)))
        start = status.get("timerStart", "")
        self.timer.setText(elapsed_text(start) if start else "")
        self.timer.setVisible(bool(start))
        button = status.get("buttonLabel", "")
        self.button.setText(button)
        self.button.setVisible(bool(button))

        small_image = status.get("smallImage", "")
        if small_image != self._shown_badge:
            self._shown_badge = small_image
            if not small_image:
                self.badge.clear()
            else:
                # The task and renderer icons ship with the plug-in, the user's own image is on the web
                prefix = context.ICON_URL.split("{}")[0]
                name = small_image[len(prefix):].split("?")[0][:-4] if small_image.startswith(prefix) else None
                image = icon_image(name) if name else None
                self.badge.setPixmap(badge_pixmap(image, self._BADGE_SIZE, 3, "#232428", ratio))
        self.badge_text.setText(status.get("smallText") or ("No text" if small_image else "No small icon"))
        self.logo_text.setText(status.get("largeText", ""))


# ---------------------------------------------------------------------------------------------------------------
# Window


class SettingsWindow(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RichPresenceSettings")
        self.setWindowTitle("Discord Rich Presence")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        with open(Path(__file__).parent / "style.qss", "r", encoding="utf-8") as f:
            self.setStyleSheet(f.read().replace("{icons}", ICONS_PATH.as_posix()))

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(16)
        root.addLayout(self._header())

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(16)
        scroll = self.scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        column = QtWidgets.QWidget()
        column_layout = QtWidgets.QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 10, 0)
        column_layout.setSpacing(12)
        self.first_line = LineCard(
            "First line", "What you're doing in Maya.",
            {"task": ("Task", "Modeling, Sculpting, Animating..."),
             "details": ("Scene name", "hero.ma, with a * when it has unsaved changes")},
            "{task} on {scene}")
        self.second_line = LineCard(
            "Second line", "Your project, or the size of the scene when no project is set.",
            {"state": ("Project or scene size", "Spaceship, or 12 objects · 45.2k polygons")},
            "Client: {project}")
        self.small_icon = IconCard()
        self.button_card = ButtonCard()
        self.away_card = AwayCard()
        self.timer_card = TimerCard()
        self._cards = (self.first_line, self.second_line, self.small_icon, self.button_card,
                       self.away_card, self.timer_card)
        for card in self._cards:
            column_layout.addWidget(card)
        column_layout.addStretch()
        scroll.setWidget(column)
        body.addWidget(scroll, 1)
        self.preview = PreviewPanel()
        self.preview.setFixedWidth(330)
        body.addWidget(self.preview)
        root.addLayout(body, 1)
        root.addLayout(self._footer())

        self._load()

        # Typing is applied once it pauses, every other change right away
        self._apply_timer = QtCore.QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(300)
        self._apply_timer.timeout.connect(self.apply)
        for card in self._cards:
            card.changed.connect(lambda: self._apply_timer.start())
        self._enabled.toggled.connect(lambda checked: self._apply_timer.start())

        self._discord = DiscordWatcher()
        self._discord.poll()
        self._ticks = 0
        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.setInterval(1000)
        self._preview_timer.timeout.connect(self._tick)
        self._preview_timer.start()
        self.refresh_preview()

        available = (self.screen() or QtWidgets.QApplication.primaryScreen()).availableGeometry()
        self.setMinimumSize(780, 520)
        self.resize(min(920, available.width() - 40), min(800, available.height() - 60))

    def _header(self):
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(16)
        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(2)
        title = QtWidgets.QLabel("Discord Rich Presence")
        title.setObjectName("title")
        titles.addWidget(title)
        subtitle = QtWidgets.QLabel("Shows what you're doing in Maya on your Discord profile.")
        subtitle.setObjectName("subtitle")
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        label = QtWidgets.QLabel("Show my status")
        label.setObjectName("switchLabel")
        header.addWidget(label, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        self._enabled = Switch()
        self._enabled.setToolTip("Hides your status from Discord without unloading the plug-in.\n"
                                 "Also in the Rich Presence menu.")
        header.addWidget(self._enabled, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        return header

    def _footer(self):
        footer = QtWidgets.QHBoxLayout()
        footer.setSpacing(12)
        reset = QtWidgets.QPushButton("Reset to defaults")
        reset.setObjectName("flat")
        reset.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(self.reset_to_defaults)
        footer.addWidget(reset)
        footer.addStretch()
        saved = QtWidgets.QLabel("Changes are saved right away.")
        saved.setObjectName("hint")
        footer.addWidget(saved)
        close = QtWidgets.QPushButton("Close")
        close.setObjectName("primary")
        close.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        close.setDefault(True)
        close.clicked.connect(self.close)
        footer.addWidget(close)
        return footer

    def _load(self, settings=None):
        settings = settings or TypedSettings()
        self.show_enabled(settings.get("enabled"), refresh=False)
        self.first_line.load(settings.get_text("custom_details"),
                             {"task": settings.get("task"), "details": settings.get("details")})
        self.second_line.load(settings.get_text("custom_state"), {"state": settings.get("state")})
        self.small_icon.load(settings.get_small_icon(), settings.get_text("small_icon_url"),
                             settings.get_text("small_icon_text"))
        self.button_card.load(settings.get_text("button_label"), settings.get_text("button_url"))
        self.away_card.load(settings.get_idle_minutes(), settings.get_idle_action(), settings.get("custom_text_while_idle"))
        self.timer_card.restart.set_on(settings.get("reset_time_with_scene"))
        self._update_suggestions()
        self._update_visibility()

    def show_enabled(self, enabled, refresh=True):
        self._enabled.blockSignals(True)
        self._enabled.setChecked(enabled)
        self._enabled.blockSignals(False)
        self._enabled.update()
        if refresh:
            self.refresh_preview()

    def apply(self):
        """Saves every setting and sends them to the plug-in."""
        self._apply_timer.stop()
        switches = {
            "enabled": self._enabled.isChecked(),
            "task": self.first_line.switches["task"].is_on(),
            "details": self.first_line.switches["details"].is_on(),
            "state": self.second_line.switches["state"].is_on(),
            "reset_time_with_scene": self.timer_card.restart.is_on(),
            "custom_text_while_idle": self.away_card.keep.is_on(),
        }
        texts = {
            "custom_details": self.first_line.text(),
            "custom_state": self.second_line.text(),
            "small_icon": self.small_icon.choice(),
            "small_icon_url": self.small_icon.link_text(),
            "small_icon_text": self.small_icon.hover_text(),
            "button_label": self.button_card.label(),
            "button_url": self.button_card.link_text(),
            "idle_action": self.away_card.action.value(),
        }
        settings = TypedSettings()
        for key, value in switches.items():
            settings.set(key, value)
        for key, value in texts.items():
            settings.set_text(key, value)
        settings.setValue("idle_minutes", self.away_card.minutes.value())
        settings.sync()

        try:
            cmds.richPresence(enabled=switches["enabled"], displayTask=switches["task"],
                              displayScene=switches["details"], displayProject=switches["state"],
                              resetTimeOnChange=switches["reset_time_with_scene"],
                              customTextWhileIdle=switches["custom_text_while_idle"],
                              customDetails=texts["custom_details"], customState=texts["custom_state"],
                              smallIcon=texts["small_icon"], smallIconUrl=usable_link(texts["small_icon_url"]),
                              smallIconText=texts["small_icon_text"],
                              buttonLabel=texts["button_label"], buttonUrl=texts["button_url"],
                              idleMinutes=self.away_card.minutes.value(), idleAction=texts["idle_action"])
        except Exception:
            pass  # the plug-in isn't loaded: the settings are saved and the preview says so
        check_menu_item(switches["enabled"])
        self._update_suggestions()
        self._update_visibility()
        self.refresh_preview()

    def reset_to_defaults(self):
        answer = QtWidgets.QMessageBox.question(self, "Discord Rich Presence",
                                                "Reset every setting to its default?")
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.show_enabled(DEFAULT_SWITCHES["enabled"], refresh=False)
        self.first_line.load("", {"task": DEFAULT_SWITCHES["task"], "details": DEFAULT_SWITCHES["details"]})
        self.second_line.load("", {"state": DEFAULT_SWITCHES["state"]})
        self.small_icon.load(DEFAULT_SMALL_ICON, "", "")
        self.button_card.load("", "")
        self.away_card.load(DEFAULT_IDLE_MINUTES, DEFAULT_IDLE_ACTION, DEFAULT_SWITCHES["custom_text_while_idle"])
        self.timer_card.restart.set_on(DEFAULT_SWITCHES["reset_time_with_scene"])
        self.apply()

    def refresh_preview(self):
        self.preview.show_status(read_status(), self._discord.running)

    def _tick(self):
        # Discord is looked for every 10 seconds: one second starts the check, the next one reads it
        self._ticks += 1
        if self._ticks % 10 in (0, 1):
            self._discord.poll()
        self.refresh_preview()

    def _update_suggestions(self):
        # "My own text" starts from what the automatic text shows
        self.first_line.suggestion = "{task} · {scene}"
        self.second_line.suggestion = "{stats}" if uses_default_project() else "{project}"

    def _update_visibility(self):
        # Keeping the own text only matters with an own text, while "Idle" is shown
        custom = bool(self.first_line.text() or self.second_line.text())
        self.away_card.keep.setVisible(custom and self.away_card.action.value() == "show")

    def closeEvent(self, event):
        if self._apply_timer.isActive():
            self.apply()  # typing that wasn't applied yet
        self._preview_timer.stop()
        super().closeEvent(event)
