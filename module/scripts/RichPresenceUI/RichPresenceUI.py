import re
from typing import Optional

from maya import OpenMayaUI
from maya import cmds, mel

from .Qt import QtWidgets, QtCore, QtGui, QtCompat

from pathlib import Path


# scripts/RichPresenceUI/ inside the module. Found from this file rather than through Maya's module list,
# which the installer can't update during a session when the user's folder has an accent.
MODULE_PATH = Path(__file__).resolve().parents[2]

MENU_NAME = "RichPresenceMenu"
PLACEHOLDERS = ("{task}", "{scene}", "{project}", "{stats}")


def add_menu():
    if cmds.about(batch=True):
        return  # no menu bar without the user interface
    remove_menu()  # a menu left by a previous load would otherwise be duplicated
    maya_window = mel.eval('$tempMelVar=$gMainWindow')
    cmds.menu(MENU_NAME, label="Rich Presence", tearOff=True, parent=maya_window)
    cmds.menuItem(label="Settings", command=lambda *args: show())


def remove_menu():
    if cmds.menu(MENU_NAME, exists=True):
        cmds.deleteUI(MENU_NAME, menu=True)


def exec_dialog(dialog):
    # exec_ is deprecated with Qt 6, and exec doesn't exist in older PySide2 versions
    return (getattr(dialog, "exec", None) or dialog.exec_)()


class TypedSettings(QtCore.QSettings):

    _CONFIG_PATH = MODULE_PATH / "config/config.ini"

    def __init__(self):
        super().__init__(self._CONFIG_PATH.as_posix(), QtCore.QSettings.Format.IniFormat)

    def get(self, setting: str, default: bool = False):
        # INI files store booleans as text, and bool("false") would be True
        return self.value(setting, default, type=bool)

    def set(self, setting: str, value: bool):
        assert isinstance(value, bool)
        self.setValue(setting, value)

    def get_text(self, setting: str):
        return self.value(setting, "", type=str)

    def set_text(self, setting: str, value: str):
        self.setValue(setting, value)

    def get_idle_minutes(self):
        return self.value("idle_minutes", IdleSettings.DEFAULT_MINUTES, type=int)

    def get_idle_action(self):
        action = self.get_text("idle_action")
        return action if action in IdleSettings.ACTIONS else IdleSettings.DEFAULT_ACTION


def apply_saved_settings():
    """
    Sends the text settings to the plug-in when it loads. The plug-in reads the other settings itself,
    but Qt quotes and escapes some text in config.ini, so it is read back here with Qt.
    """
    settings = TypedSettings()
    cmds.richPresence(buttonLabel=settings.get_text("button_label"), buttonUrl=settings.get_text("button_url"),
                      idleMinutes=settings.get_idle_minutes(), idleAction=settings.get_idle_action(),
                      customDetails=settings.get_text("custom_details"), customState=settings.get_text("custom_state"))


class RichPresenceUI(QtWidgets.QDialog):

    def __init__(self):
        parent = QtCompat.wrapInstance(int(OpenMayaUI.MQtUtil.mainWindow()), QtWidgets.QWidget)
        super().__init__(parent)
        with open(Path(__file__).parent / "style.qss", "r") as f:
            stylesheet = f.read()
            self.setStyleSheet(stylesheet)

        self.setWindowTitle("Rich Presence For Maya Settings")

        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        bar = QtWidgets.QMenuBar()
        menu = QtWidgets.QMenu("File")
        menu.setStyleSheet(stylesheet)
        action = QtWidgets.QAction("Reset to defaults", self)
        action.triggered.connect(self.reset_options)
        menu.addAction(action)
        bar.addMenu(menu)
        root_layout.addWidget(bar)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(11, 0, 11, 11)
        root_layout.addLayout(layout)

        layout.addWidget(SettingsWidget())

        button_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(button_layout)
        self._save_btn = QtWidgets.QPushButton("Save")
        self._save_btn.clicked.connect(self.save)
        button_layout.addWidget(self._save_btn)

        self._cancel_btn = QtWidgets.QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.close)
        button_layout.addWidget(self._cancel_btn)

    def save(self):
        button = self.findChild(ButtonSettings)
        error = button.validate()
        if error:
            QtWidgets.QMessageBox.warning(self, "Rich Presence", error)
            return

        custom = self.findChild(CustomTextSettings)
        typo = custom.unknown_placeholder()
        if typo:
            answer = QtWidgets.QMessageBox.question(
                self, "Rich Presence",
                f'"{typo}" isn\'t a known placeholder and will be shown as is.\n\n'
                f"Placeholders: {' '.join(PLACEHOLDERS)}\n\nSave anyway?")
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return

        settings = TypedSettings()
        arguments = {}
        for entry in self.findChildren(SettingsEntry):
            settings.set(entry.objectName(), entry.is_checked)
            arguments[entry.command] = entry.is_checked

        settings.set_text("button_label", button.label)
        settings.set_text("button_url", button.url)
        arguments["buttonLabel"] = button.label
        arguments["buttonUrl"] = button.url

        settings.set_text("custom_details", custom.details)
        settings.set_text("custom_state", custom.state)
        arguments["customDetails"] = custom.details
        arguments["customState"] = custom.state

        idle = self.findChild(IdleSettings)
        settings.setValue("idle_minutes", idle.minutes)
        settings.set_text("idle_action", idle.action)
        arguments["idleMinutes"] = idle.minutes
        arguments["idleAction"] = idle.action

        cmds.richPresence(**arguments)

        self.close()

    def reset_options(self):
        for entry in self.findChildren(SettingsEntry):
            entry.reset()
        self.findChild(CustomTextSettings).clear()
        self.findChild(ButtonSettings).clear()
        self.findChild(IdleSettings).reset()


class SettingsWidget(QtWidgets.QWidget):

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(SettingsEntry("Details", "Show or hide the scene name.", "displayScene"))
        layout.addWidget(Separator())
        layout.addWidget(SettingsEntry("Task", "Show what you are doing: modeling, sculpting, animating...",
                                       "displayTask", default=True))
        layout.addWidget(Separator())
        layout.addWidget(SettingsEntry("State", "Show the project, or scene statistics when no project is set.",
                                       "displayProject"))

        layout.addWidget(Separator())
        layout.addWidget(SettingsEntry("Reset Time With Scene", "Reset the timer when a new scene is opened.", "resetTimeOnChange"))

        layout.addWidget(Separator())
        layout.addWidget(CustomTextSettings())

        layout.addWidget(Separator())
        layout.addWidget(IdleSettings())
        layout.addWidget(SettingsEntry("Custom Text While Idle",
                                       "Keep showing your custom text when idle, instead of \"Idle\".",
                                       "customTextWhileIdle", reset_value=False))

        layout.addWidget(Separator())
        layout.addWidget(ButtonSettings())


class Separator(QtWidgets.QFrame):

    def __init__(self):
        super().__init__()
        self.setFrameShape(QtWidgets.QFrame.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Plain)


class SettingsEntry(QtWidgets.QWidget):

    def __init__(self, label: str, desc:str, command: str, default: bool = False, reset_value: bool = True):
        super().__init__()
        assert command
        self._command = command
        self._reset_value = reset_value

        self.setObjectName(label.replace(" ", "_").lower())
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QtWidgets.QLabel(f"{label}")
        self._label.setStyleSheet("QLabel { font-weight: bold; font-size: 10pt; }")
        layout.addWidget(self._label, 0, 0, 1, 1)

        self._desc = QtWidgets.QLabel(desc)
        layout.addWidget(self._desc, 1, 0, 1, 1)

        layout.addItem(QtWidgets.QSpacerItem(100, 0, QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Minimum), 0, 1, 1, 2)
        layout.setColumnStretch(1, True)

        self._checkbox = AnimatedCheckBox(TypedSettings().get(self.objectName(), default))
        layout.addWidget(self._checkbox, 0, 2, 2, 1)

    @property
    def name(self):
        return self._label.text()

    @property
    def is_checked(self):
        return self._checkbox.isChecked()

    def set_checked(self, checked):
        self._checkbox.setChecked(checked)

    def reset(self):
        self.set_checked(self._reset_value)

    @property
    def command(self):
        return self._command


class CustomTextSettings(QtWidgets.QWidget):

    # Discord shows at most 128 bytes per line
    _MAX_LENGTH = 128

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QtWidgets.QLabel("Custom Text")
        title.setStyleSheet("QLabel { font-weight: bold; font-size: 10pt; }")
        layout.addWidget(title, 0, 0, 1, 2)
        layout.addWidget(QtWidgets.QLabel("Write your own text, or leave a line empty to keep it automatic.\n"
                                          "{task} {scene} {project} {stats} are replaced by their value."), 1, 0, 1, 2)

        settings = TypedSettings()
        self._details = QtWidgets.QLineEdit(settings.get_text("custom_details"))
        self._details.setPlaceholderText("Automatic, e.g. {task} · {scene}")
        self._details.setMaxLength(self._MAX_LENGTH)
        layout.addWidget(QtWidgets.QLabel("First line"), 2, 0)
        layout.addWidget(self._details, 2, 1)

        self._state = QtWidgets.QLineEdit(settings.get_text("custom_state"))
        self._state.setPlaceholderText("Automatic, e.g. {project} or {stats}")
        self._state.setMaxLength(self._MAX_LENGTH)
        layout.addWidget(QtWidgets.QLabel("Second line"), 3, 0)
        layout.addWidget(self._state, 3, 1)

    @property
    def details(self):
        return self._details.text().strip()

    @property
    def state(self):
        return self._state.text().strip()

    def unknown_placeholder(self):
        """Returns the first brace that isn't part of a known placeholder, like "{task]", or an empty string."""
        for text in (self.details, self.state):
            for placeholder in PLACEHOLDERS:
                text = text.replace(placeholder, " ")
            match = re.search(r"\{[^\s{}]*[}\])]?|\}", text)
            if match:
                return match.group()
        return ""

    def clear(self):
        self._details.clear()
        self._state.clear()


class IdleSettings(QtWidgets.QWidget):

    # Values understood by the richPresence command, with their label in the settings
    ACTIONS = {"show": 'Show "Idle"', "hide": "Hide my status", "off": "Do nothing"}
    DEFAULT_ACTION = "show"
    DEFAULT_MINUTES = 10

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QtWidgets.QLabel("Idle")
        title.setStyleSheet("QLabel { font-weight: bold; font-size: 10pt; }")
        layout.addWidget(title, 0, 0, 1, 3)
        layout.addWidget(QtWidgets.QLabel("When you stop using Maya for a while, the timer pauses\n"
                                          "and the time away isn't counted."), 1, 0, 1, 3)

        settings = TypedSettings()
        layout.addWidget(QtWidgets.QLabel("After"), 2, 0)
        self._minutes = QtWidgets.QSpinBox()
        self._minutes.setRange(1, 240)
        self._minutes.setSuffix(" min")
        self._minutes.setValue(settings.get_idle_minutes())
        layout.addWidget(self._minutes, 2, 1)

        self._action = QtWidgets.QComboBox()
        for value, label in self.ACTIONS.items():
            self._action.addItem(label, value)
        self._action.setCurrentIndex(self._action.findData(settings.get_idle_action()))
        layout.addWidget(self._action, 2, 2)
        layout.setColumnStretch(2, 1)

    @property
    def minutes(self):
        return self._minutes.value()

    @property
    def action(self):
        return self._action.currentData()

    def reset(self):
        self._minutes.setValue(self.DEFAULT_MINUTES)
        self._action.setCurrentIndex(self._action.findData(self.DEFAULT_ACTION))


class ButtonSettings(QtWidgets.QWidget):

    # Limits set by Discord
    _MAX_LABEL_LENGTH = 32
    _MAX_URL_LENGTH = 512

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QtWidgets.QLabel("Button")
        title.setStyleSheet("QLabel { font-weight: bold; font-size: 10pt; }")
        layout.addWidget(title, 0, 0, 1, 2)
        layout.addWidget(QtWidgets.QLabel("Add a link to your status, like your portfolio.\n"
                                          "Others can click it, but Discord doesn't show it to you."), 1, 0, 1, 2)

        settings = TypedSettings()
        self._label = QtWidgets.QLineEdit(settings.get_text("button_label"))
        self._label.setPlaceholderText("My portfolio")
        self._label.setMaxLength(self._MAX_LABEL_LENGTH)
        layout.addWidget(QtWidgets.QLabel("Text"), 2, 0)
        layout.addWidget(self._label, 2, 1)

        self._url = QtWidgets.QLineEdit(settings.get_text("button_url"))
        self._url.setPlaceholderText("https://www.artstation.com/...")
        self._url.setMaxLength(self._MAX_URL_LENGTH)
        layout.addWidget(QtWidgets.QLabel("Link"), 3, 0)
        layout.addWidget(self._url, 3, 1)

    @property
    def label(self):
        return self._label.text().strip()

    @property
    def url(self):
        return self._url.text().strip()

    def validate(self):
        """Returns an error message, or an empty string if the button can be saved."""
        if bool(self.label) != bool(self.url):
            return "Fill in both the text and the link of the button, or leave both empty."
        if self.url and not self.url.startswith(("https://", "http://")):
            return "The link of the button must start with https://"
        if " " in self.url:
            return "The link of the button can't contain spaces."
        return ""

    def clear(self):
        self._label.clear()
        self._url.clear()


class AnimatedCheckBox(QtWidgets.QCheckBox):

    _ACTIVE_COLOR = QtGui.QColor(88, 101, 242)
    _INACTIVE_COLOR = QtGui.QColor(77, 80, 91)
    _BUTTON_COLOR = QtGui.QColor("white")

    _BUTTON_MARGIN = 6

    def __init__(self, checked = False):
        super().__init__()
        self.setChecked(checked)

        aspect_ratio = 2
        width = 45
        height = round(width / aspect_ratio)
        self._size = QtCore.QSize(width, height)

        self.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Fixed)
        self.setMinimumSize(QtCore.QSize(width, height))

        self._background_path: Optional[QtGui.QPainterPath] = None
        self.init_painter_paths()

        self._handle_position = self.isChecked()

        self._animation = QtCore.QPropertyAnimation(self, b"handle_position")
        self._animation.setEasingCurve(QtCore.QEasingCurve.Type.InQuad)
        self._animation.setDuration(100)

        self.toggled.connect(self._start_anim)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.fillPath(self._background_path, self.lerp_color(self._INACTIVE_COLOR, self._ACTIVE_COLOR, self._handle_position))

        painter.setBrush(self._BUTTON_COLOR)
        painter.setPen(QtCore.Qt.NoPen)
        diameter = self._size.height() - self._BUTTON_MARGIN
        margin = round(self._BUTTON_MARGIN / 2)

        end_pos = self._size.width() - diameter - margin
        x_offset = round(self.lerp(margin, end_pos, self._handle_position))

        rect = QtCore.QRect(x_offset, margin, diameter, diameter)
        painter.drawEllipse(rect)

    @staticmethod
    def lerp(start, end, t):
        return start + (end - start) * t

    @staticmethod
    def lerp_color(start, end, t):
        return QtGui.QColor(
            int(start.red() + (end.red() - start.red()) * t),
            int(start.green() + (end.green() - start.green()) * t),
            int(start.blue() + (end.blue() - start.blue()) * t)
        )

    def init_painter_paths(self):
        rect = QtCore.QRect(0, 0, self._size.width(), self._size.height())
        radius = rect.height() / 2
        path = QtGui.QPainterPath()
        path.moveTo(rect.center())
        path.addRoundedRect(rect, radius, radius)

        self._background_path = path

    @QtCore.Property(float)
    def handle_position(self):
        return self._handle_position

    @handle_position.setter
    def handle_position(self, handle_position: float):
        self._handle_position = handle_position
        self.update()

    def mouseReleaseEvent(self, event):
        # The base class isn't called, so the pressed state it set on press is cleared here
        self.setDown(False)
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            # position() only exists in Qt 6, Maya 2023 and 2024 still use Qt 5
            position = event.position() if hasattr(event, "position") else QtCore.QPointF(event.pos())
            if self._background_path.contains(position):
                self.toggle()

    def _start_anim(self):
        self._animation.stop()
        self._animation.setEndValue(float(self.isChecked()))
        self._animation.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)


def show():
    dialog = RichPresenceUI()
    exec_dialog(dialog)
    # Parented to Maya's main window, it would otherwise stay in memory after every opening
    dialog.deleteLater()
