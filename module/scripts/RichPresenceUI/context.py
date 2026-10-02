"""
What the user is doing in Maya, polled by the plug-in every 2 seconds.
Edit the tables and texts below to change the wording shown in Discord, no recompiling needed.
"""
from maya import cmds


# The focused editor says more about the current task than the menu set, so it is checked first
PANEL_TASKS = {
    "polyTexturePlacementPanel": "UV editing",
    "hyperShadePanel": "Shading",
    "graphEditor": "Animating",
    "dopeSheetPanel": "Animating",
    "timeEditorPanel": "Animating",
    "renderWindowPanel": "Rendering",
}

# Menu sets picked with F2 to F6 or the drop-down at the top left of Maya
MENU_SET_TASKS = {
    "modelingMenuSet": "Modeling",
    "riggingMenuSet": "Rigging",
    "animationMenuSet": "Animating",
    "dynamicsMenuSet": "Simulating",
    "renderingMenuSet": "Rendering",
}

SCULPTING = "Sculpting"

# Renderer display names, looked up once per renderer
_renderer_names = {}


def current_task():
    """Returns a short label like "Modeling", or an empty string when nothing fits."""
    # Each check can fail on its own (panels, tools and menu sets only exist with the user interface,
    # and some tools don't answer contextInfo), without preventing the next ones
    try:
        context = cmds.currentCtx()
        if context and cmds.contextInfo(context, c=True) == "sculptMeshCache":
            return SCULPTING
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
        return MENU_SET_TASKS.get(cmds.menuSet(query=True, currentMenuSet=True), "")
    except Exception:
        return ""


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


def current_renderer():
    """Returns the name of the scene's renderer, like "Arnold Renderer"."""
    try:
        name = cmds.getAttr("defaultRenderGlobals.currentRenderer")
    except Exception:
        return ""
    if name not in _renderer_names:
        try:
            available = cmds.renderer(query=True, namesOfAvailableRenderers=True) or []
            if name not in available:
                return ""  # its plug-in isn't loaded yet, asked again on the next poll
            _renderer_names[name] = cmds.renderer(name, query=True, rendererUIName=True)
        except Exception:
            return ""
    return _renderer_names[name]
