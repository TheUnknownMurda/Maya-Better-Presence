"""
What the user is doing in Maya, polled by the plug-in every 2 seconds.
Edit the tables and texts below to change the wording shown in Discord, no recompiling needed.
"""
from maya import cmds, mel

from .Qt import QtWidgets


# Text shown for each task. The keys are also the names of the task icons, in assets/icons.
TASKS = {
    "modeling": "Modeling",
    "sculpting": "Sculpting",
    "uv": "UV editing",
    "shading": "Shading",
    "lighting": "Lighting",
    "animating": "Animating",
    "rigging": "Rigging",
    "simulating": "Simulating",
    "rendering": "Rendering",
    "scripting": "Scripting",
    "painting": "Painting",
}

# Tools that tell the task on their own, by the class of their context
TOOL_TASKS = {
    "sculptMeshCache": "sculpting",
    "art3dPaint": "painting",
    "artAttrColorPerVertex": "painting",
    "artAttrSkin": "rigging",
    "jointTool": "rigging",
}

# Windows that aren't panels, found from the widget with the keyboard focus
WINDOW_TASKS = {
    "MayaLightEditorWindowWorkspaceControl": "lighting",
    "ArnoldRenderView": "rendering",
}

# The focused editor says more about the current task than the menu set, so it is checked first
PANEL_TASKS = {
    "polyTexturePlacementPanel": "uv",
    "hyperShadePanel": "shading",
    "graphEditor": "animating",
    "dopeSheetPanel": "animating",
    "timeEditorPanel": "animating",
    "renderWindowPanel": "rendering",
    "scriptEditorPanel": "scripting",
}

# Menu sets picked with F2 to F6 or the drop-down at the top left of Maya
MENU_SET_TASKS = {
    "modelingMenuSet": "modeling",
    "riggingMenuSet": "rigging",
    "animationMenuSet": "animating",
    "dynamicsMenuSet": "simulating",
    "renderingMenuSet": "rendering",
}

# Tools used all the time, whose name says nothing: their context class, or their context name
BASIC_TOOLS = {"selectTool", "manipMove", "manipRotate", "manipScale", "xformManipulator", "ModelingToolkitSuperCtx"}

IDLE = "Idle"
PLAYBLASTING = "Playblasting"
SEPARATOR = " · "

# The small icons over the Maya logo are downloaded by Discord from the plug-in's GitHub repository.
# After changing an icon, raise v= so Discord doesn't keep showing the old one.
ICON_URL = "https://raw.githubusercontent.com/TheUnknownMurda/Maya-Better-Presence/master/assets/icons/{}.png?v=1"

# Renderers with their own icon, renderer-<name in lower case>.png. The others get renderer.png.
RENDERER_ICONS = {"arnold", "vray", "redshift", "renderman", "mayaSoftware", "mayaHardware2"}

# Plug-ins whose version is shown with the renderer's name
RENDERER_PLUGINS = {"vray": "vrayformaya", "redshift": "redshift4maya", "renderman": "RenderMan_for_Maya"}

# Renderer display names and versions, looked up once per renderer
_renderer_names = {}
_renderer_versions = {}
# Task of the window that had the focus when Maya was last the active application
_last_window_task = None


def current_task():
    """Returns a short label like "Modeling", or an empty string when nothing fits."""
    return TASKS.get(_task(), "")


def _task():
    """The key of the current task in TASKS, or None."""
    # Each check can fail on its own (panels, tools and menu sets only exist with the user interface,
    # and some tools don't answer contextInfo), without preventing the next ones
    try:
        task = TOOL_TASKS.get(cmds.contextInfo(cmds.currentCtx(), c=True))
        if task:
            return task
    except Exception:
        pass

    try:
        task = _focused_window_task()
        if task:
            return task
    except Exception:
        pass

    try:
        panel = cmds.getPanel(withFocus=True)
        if panel and cmds.getPanel(typeOf=panel) == "scriptedPanel":
            task = PANEL_TASKS.get(cmds.scriptedPanel(panel, query=True, type=True))
            if task:
                return task
    except Exception:
        pass

    try:
        return MENU_SET_TASKS.get(cmds.menuSet(query=True, currentMenuSet=True))
    except Exception:
        return None


def _focused_window_task():
    # Maya keeps reporting the last focused panel while another window like the Light Editor has the focus
    global _last_window_task
    if cmds.about(batch=True):
        return None
    # Qt only knows which widget has the focus while Maya is the active application,
    # and switching to Discord to check the status shouldn't change the task
    if QtWidgets.QApplication.activeWindow() is None:
        return _last_window_task
    widget = QtWidgets.QApplication.focusWidget()
    task = None
    while widget is not None and not task:
        task = WINDOW_TASKS.get(widget.objectName())
        widget = widget.parentWidget()
    _last_window_task = task
    return task


def small_image(mode, idle=False, playblasting=False):
    """
    Returns the small icon shown over the Maya logo and the text shown when hovering it, as [image, text],
    or empty strings for no icon. mode is "task" or "renderer", as chosen in the settings.
    """
    if mode == "renderer":
        name = _renderer()
        if not name:
            return ["", ""]
        icon = f"renderer-{name.lower()}" if name in RENDERER_ICONS else "renderer"
        return [ICON_URL.format(icon), _renderer_label(name)]

    # Idle, a playblast and a render in progress say more than the task
    if idle:
        return [ICON_URL.format("idle"), IDLE]
    if playblasting:
        return [ICON_URL.format("playblasting"), _join(PLAYBLASTING, _frame_range())]
    if _arnold_ipr_running():
        return [ICON_URL.format("rendering"), _join(TASKS["rendering"], _render_settings())]

    task = _task()
    if task not in TASKS:
        return ["", ""]
    return [ICON_URL.format(task), _join(TASKS[task], _task_detail(task))]


def _task_detail(task):
    """What the text of a task's icon adds after the task, like the active tool."""
    if task in ("animating", "simulating"):
        return _frame_range()
    if task in ("shading", "lighting"):
        return _renderer_label(_renderer())
    if task == "rendering":
        return _render_settings()
    if task == "scripting":
        return None
    return _tool_name()


def _join(*parts):
    return SEPARATOR.join(part for part in parts if part)


def _tool_name():
    """The name of the active tool, like "Grab Tool", or None for the basic tools used all the time."""
    try:
        context = cmds.currentCtx()
        if context in BASIC_TOOLS or cmds.contextInfo(context, c=True) in BASIC_TOOLS:
            return None
        return cmds.contextInfo(context, title=True) or None
    except Exception:
        return None


def _frame_range():
    """Like "1–240 · 24 fps"."""
    try:
        start = cmds.playbackOptions(query=True, minTime=True)
        end = cmds.playbackOptions(query=True, maxTime=True)
        fps = mel.eval("currentTimeUnitToFPS()")
        return f"{start:g}–{end:g}{SEPARATOR}{fps:g} fps"
    except Exception:
        return None


def _render_settings():
    """Like "Arnold 7.5.2 · 1920×1080"."""
    try:
        width = cmds.getAttr("defaultResolution.width")
        height = cmds.getAttr("defaultResolution.height")
        resolution = f"{width}×{height}"
    except Exception:
        resolution = None
    return _join(_renderer_label(_renderer()), resolution)


def _arnold_ipr_running():
    # The Arnold RenderView only answers once it has been opened
    try:
        return (cmds.workspaceControl("ArnoldRenderView", exists=True)
                and cmds.arnoldRenderView(get="Run IPR") == "1")
    except Exception:
        return False


def _renderer():
    """The scene's renderer, like "arnold", or None when its plug-in isn't loaded yet."""
    try:
        name = cmds.getAttr("defaultRenderGlobals.currentRenderer")
        if name not in _renderer_names:
            if name not in (cmds.renderer(query=True, namesOfAvailableRenderers=True) or []):
                return None  # asked again on the next poll
            _renderer_names[name] = cmds.renderer(name, query=True, rendererUIName=True)
        return name
    except Exception:
        return None


def _renderer_label(name):
    """Like "Arnold 7.5.2": the renderer's name, with its version when it is known."""
    if not name:
        return None
    if name not in _renderer_versions:
        _renderer_versions[name] = _renderer_version(name)
    display_name = _renderer_names.get(name, name)
    if display_name.endswith(" Renderer"):
        display_name = display_name[:-len(" Renderer")]  # "Arnold Renderer" reads better as "Arnold"
    version = _renderer_versions[name]
    return f"{display_name} {version}" if version else display_name


def _renderer_version(name):
    try:
        if name == "arnold":
            import arnold
            return ".".join(arnold.AiGetVersionString().split(".")[:3])
        if name in RENDERER_PLUGINS:
            return cmds.pluginInfo(RENDERER_PLUGINS[name], query=True, version=True)
    except Exception:
        pass
    return None


def current_renderer():
    """Returns the name of the scene's renderer, like "Arnold Renderer"."""
    return _renderer_names.get(_renderer(), "")


def format_statistics(meshes, polygons):
    """
    Text shown instead of the project when Maya's default project is used, like "12 objects · 45.2k polygons".
    The plug-in counts the meshes and polygons itself, which is much faster than doing it in Python.
    """
    if not meshes:
        return "Empty scene"
    return (f"{meshes} object{'s' if meshes > 1 else ''} · "
            f"{_short_number(polygons)} polygon{'s' if polygons != 1 else ''}")


def _short_number(number):
    units = ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "k"))
    for index, (limit, suffix) in enumerate(units):
        if number >= limit:
            text = f"{number / limit:.1f}".rstrip("0").rstrip(".")
            # 999,950 would round to "1000k", which reads better as "1M"
            if text == "1000" and index > 0:
                return "1" + units[index - 1][1]
            return text + suffix
    return str(number)
