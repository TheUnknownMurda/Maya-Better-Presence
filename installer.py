import filecmp
import os
import pathlib
import shutil
import subprocess
import sys
import time
import traceback

from maya import cmds, OpenMayaUI

try:
    from PySide2 import QtWidgets, QtGui
    from shiboken2 import wrapInstance
except ImportError:
    from PySide6 import QtWidgets, QtGui
    from shiboken6 import wrapInstance


module_name = "DRPForMaya"
plugin_name = "DRPForMaya"

# The module path is relative to the .mod file: Maya ignores modules whose absolute path contains
# an accent, as in C:\Users\Sébastien\Documents, while a relative path works with any user name
module_template = """+ MAYAVERSION:{version} {module_name} Any ./{module_name}
plug-ins: plug-ins/{version}
scripts: scripts
PATH+:= bin
"""

discord_processes = ("discord.exe", "discordptb.exe", "discordcanary.exe")

preserved_files = ("config.ini",)

# Every Maya version the plug-in is built for. A download can hold only some of them.
supported_versions = ("2023", "2024", "2025", "2026", "2027")
releases_url = "https://github.com/TheUnknownMurda/Maya-Better-Presence/releases/latest"


class PluginBlocked(Exception):
    """Maya didn't load the plug-in, usually because Deny was clicked in its security warning."""


def get_maya_main_window():
    ptr = OpenMayaUI.MQtUtil.mainWindow()
    if ptr is None:
        return None
    return wrapInstance(int(ptr), QtWidgets.QWidget)


def is_discord_running():
    if sys.platform != "win32":
        return True
    try:
        result = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                                errors="ignore", creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError:
        return True  # we can't tell, so don't bother the user
    processes = result.stdout.lower()
    return any(f'"{name}"' in processes for name in discord_processes)


# noinspection PyUnresolvedReferences
class Installer(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Discord Rich Presence Installer")
        self.setMinimumSize(520, 300)
        self.path = pathlib.Path(__file__).parent
        self.source_dir = self.path / "module"
        self.plugin_dir = self.source_dir / "plug-ins"
        # Maya's own user folder, which follows MAYA_APP_DIR and OneDrive redirected Documents
        self.maya_module_dir = pathlib.Path(cmds.internalVar(userAppDir=True)) / "modules"
        self.module_file = self.maya_module_dir / f"{module_name}.mod"
        self.target_dir = self.maya_module_dir / module_name
        self.maya_version = cmds.about(majorVersion=True)
        self.plugin_file = self.target_dir / "plug-ins" / self.maya_version / f"{plugin_name}.mll"

        layout = QtWidgets.QVBoxLayout(self)
        self.console = Console("")
        layout.addWidget(self.console)

        self.installed = False
        self.changed_files = []
        self.button = QtWidgets.QPushButton("Install")
        self.button.clicked.connect(self.on_button_clicked)
        layout.addWidget(self.button)

        self.check_requirements()

    def on_button_clicked(self):
        # One slot for both states, rather than swapping slots while the signal is being emitted
        if self.installed:
            self.accept()
        else:
            self.install()

    def check_requirements(self):
        if not self.plugin_dir.is_dir():
            self.console.error("Could not find the 'module' folder next to installer.py.\n\n"
                               "Extract the whole .zip file first, then drag installer.py\n"
                               "from the extracted folder into Maya.", clear=True)
            self.button.setEnabled(False)
            return

        versions = sorted(self.find_versions(self.plugin_dir))
        if self.maya_version not in versions and self.maya_version in supported_versions:
            self.console.error(f"This download is for Maya {', '.join(versions)}, not Maya {self.maya_version}.\n\n"
                               f"Download the zip for Maya {self.maya_version}, or the one for all versions, from:\n"
                               f"{releases_url}", clear=True)
            self.button.setEnabled(False)
            return
        if self.maya_version not in versions:
            self.console.error(f"Maya {self.maya_version} is not supported yet.\n\n"
                               f"Supported versions: {', '.join(supported_versions)}", clear=True)
            self.button.setEnabled(False)
            return

        self.console.log(f"Ready to install Discord Rich Presence for Maya {self.maya_version}.\n\n"
                         f"Click Install. No restart needed.", clear=True)
        self.console.add_divider()
        self.console.log("Maya will then show a security warning about DRPForMaya.mll.\n"
                         "This is normal: Maya asks for every plug-in not made by Autodesk.\n"
                         "Tick \"Apply to all plugins in this location\" and click Allow.")
        if not is_discord_running():
            self.console.add_divider()
            self.console.warning("Discord doesn't seem to be running.\n"
                                 "Your status will show up as soon as you open the Discord desktop app\n"
                                 "(the browser version of Discord doesn't work).")

    def install(self):
        # A plug-in loaded in this session is never unloaded here: an older version could leave callbacks
        # behind in the Discord SDK that crash Maya once its code is gone. Its files are swapped instead
        # and the new version starts with Maya.
        already_loaded = cmds.pluginInfo(plugin_name, query=True, loaded=True)
        try:
            self.remove_old_files()
            self.changed_files = []
            shutil.copytree(self.source_dir, self.target_dir, dirs_exist_ok=True, copy_function=self.copy_if_changed)
            # Written after copying, so it lists every version installed so far: installing the zip for one
            # version must not drop the versions installed earlier from another zip
            self.write_module_file()
            self.activate_plugin()
        except PluginBlocked:
            traceback.print_exc()
            self.console.error("The files are installed, but Maya didn't load the plug-in.\n\n"
                               "If you clicked Deny in Maya's security warning, run the installer again\n"
                               "and click Allow this time. Details are in the Script Editor.", clear=True)
            return
        except Exception:
            traceback.print_exc()
            self.console.error(f"Something went wrong while attempting to install.\n"
                               f"Close Maya, delete {self.target_dir} and try again.\n\n"
                               f"Details are in the Script Editor.", clear=True)
            return

        if already_loaded and self.changed_files:
            self.console.log("Discord Rich Presence has been updated.\n"
                             "Restart Maya to use the new version.\n"
                             "If Maya shows a security warning about DRPForMaya.mll, click Allow.", clear=True)
        elif already_loaded:
            self.console.log("Discord Rich Presence is already up to date and active.", clear=True)
        else:
            self.console.log("Discord Rich Presence is installed and active!\n"
                             "It will load automatically every time you start Maya.", clear=True)
        if not is_discord_running():
            self.console.add_divider()
            self.console.warning("Discord doesn't seem to be running.\n"
                                 "Your status will show up as soon as you open the Discord desktop app.")
        self.console.add_divider()
        self.console.log("Settings are in the new 'Rich Presence' menu of Maya's menu bar.\n"
                         "To hide your status, unload DRPForMaya.mll in\n"
                         "Windows > Settings/Preferences > Plug-in Manager.")
        self.console.add_divider()
        self.console.log(f"To uninstall, simply delete {module_name}.mod and the {module_name} directory from \n{self.target_dir.parent}")

        self.installed = True
        self.button.setText("Close")

    def copy_if_changed(self, src, dst):
        dst_path = pathlib.Path(dst)
        if dst_path.exists():
            # Keep the user's settings when updating
            if dst_path.name in preserved_files:
                return dst
            # Skipping identical files lets a re-install succeed even if one of them is still in use
            if filecmp.cmp(src, dst, shallow=False):
                return dst
            # Files used by this Maya session can't be overwritten but can be renamed,
            # and Maya keeps using the renamed file until it restarts
            try:
                result = shutil.copy2(src, dst)
                self.changed_files.append(dst)
                return result
            except PermissionError:
                dst_path.replace(dst_path.with_name(f"{dst_path.name}.{int(time.time())}.old"))
        result = shutil.copy2(src, dst)
        self.changed_files.append(dst)
        return result

    def remove_old_files(self):
        # Files swapped out by a previous update, no longer in use once Maya has restarted
        if self.target_dir.exists():
            for old_file in self.target_dir.rglob("*.old"):
                try:
                    old_file.unlink()
                except OSError:
                    pass

    def write_module_file(self):
        installed = sorted(self.find_versions(self.target_dir / "plug-ins"))
        module = "\n".join(self.format_template(version) for version in installed)
        self.maya_module_dir.mkdir(parents=True, exist_ok=True)
        with open(self.module_file, 'w', encoding="utf-8") as f:
            f.write(module)

    def activate_plugin(self):
        if not cmds.pluginInfo(plugin_name, query=True, loaded=True):
            # Maya only reads modules when it starts. loadModule could register ours without a restart,
            # but it ignores paths with an accent and resolves relative ones from Maya's own folder,
            # so the module's folders are added by hand for this session instead.
            bin_dir = str(self.target_dir / "bin")
            if bin_dir.lower() not in os.environ.get("PATH", "").lower().split(os.pathsep):
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")  # for the Discord SDK
            scripts_dir = (self.target_dir / "scripts").as_posix()
            if scripts_dir not in sys.path:
                sys.path.append(scripts_dir)
            try:
                cmds.loadPlugin(self.plugin_file.as_posix())
            except RuntimeError as error:
                raise PluginBlocked() from error
            if not cmds.pluginInfo(plugin_name, query=True, loaded=True):
                raise PluginBlocked()
        cmds.pluginInfo(plugin_name, edit=True, autoload=True)
        cmds.pluginInfo(savePluginPrefs=True)

    @staticmethod
    def find_versions(plugin_dir):
        """Maya versions with a built plug-in in plug-ins/<version>."""
        for version in plugin_dir.iterdir():
            if (version / f"{plugin_name}.mll").is_file():
                yield version.name

    def format_template(self, version):
        return module_template.format(version=version, module_name=module_name)


class Console(QtWidgets.QPlainTextEdit):

    def __init__(self, text):
        super().__init__(text)
        self.setReadOnly(True)

    def log(self, text, clear=False):
        if clear:
            self.clear()
        self.appendPlainText(text)

    def error(self, text, clear=False):
        tf = self.currentCharFormat()
        tf.setForeground(QtGui.QColor("red"))
        self.setCurrentCharFormat(tf)
        self.log(text, clear)
        tf.setForeground(QtGui.QColor("white"))
        self.setCurrentCharFormat(tf)

    def warning(self, text, clear=False):
        tf = self.currentCharFormat()
        tf.setForeground(QtGui.QColor("yellow"))
        self.setCurrentCharFormat(tf)
        self.log(text, clear)
        tf.setForeground(QtGui.QColor("white"))
        self.setCurrentCharFormat(tf)

    def add_divider(self):
        self.appendPlainText("───────────────────────────────")


# noinspection PyPep8Naming
def onMayaDroppedPythonFile(*_):
    gui = Installer(get_maya_main_window())
    # exec_ is deprecated with Qt 6, and exec doesn't exist in older PySide2 versions
    (getattr(gui, "exec", None) or gui.exec_)()
    gui.deleteLater()
