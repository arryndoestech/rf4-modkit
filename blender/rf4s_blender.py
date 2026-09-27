"""
RF4S motions -- a small Blender add-on for the modding toolkit's Export for Blender /
Export all motions files.

Install once: Blender > Edit > Preferences > Add-ons > the drop-down arrow at the top right >
Install from Disk... > pick this file (rf4s_blender.py). Then:

  File > Import > RF4S model / motions (.glb)
      sets the scene to the game's 60 frames per second BEFORE importing (so every game frame
      lands on a Blender frame), imports the file, and fits the timeline to the motion.
  Timeline fitting
      whenever the armature's action changes (picking another motion in the Action Editor),
      the scene range becomes that motion: frame 0 .. its last frame. Frame N = game frame N.
      Turn it off in the add-on's preferences.
  File > Export > RF4S motions (.glb)
      Blender's glTF export with the settings the toolkit expects (binary .glb, every action);
      refuses when the frame rate is not 60, which would smooth fast moves away.

Bring the result back with the toolkit's Import motion... or Import all motions....
"""

bl_info = {
    "name": "RF4S motions",
    "author": "rf4s modding toolkit",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "File > Import / Export > RF4S model / motions (.glb)",
    "description": "60 fps import, timeline fitted to the active motion, and export for the RF4S modding toolkit",
    "category": "Import-Export",
}

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

GAME_FPS = 60
_last = {"action": None}


def _prefs():
    addon = bpy.context.preferences.addons.get(__name__)
    return addon.preferences if addon else None


def _active_action(scene):
    """The action of the active armature (else of the first armature that has one)."""
    obs = [bpy.context.view_layer.objects.active] if bpy.context.view_layer else []
    obs += [o for o in scene.objects if o.type == "ARMATURE"]
    for o in obs:
        if o is not None and o.type == "ARMATURE" and o.animation_data and o.animation_data.action:
            return o.animation_data.action
    return None


def fit_timeline(scene, action=None):
    """Scene range = the action's frames (0 .. last key, or its manual range)."""
    action = action or _active_action(scene)
    if action is None:
        return False
    start, end = (int(round(v)) for v in action.frame_range)
    if end <= start:
        end = start + 1
    if (scene.frame_start, scene.frame_end) != (start, end):
        scene.frame_start, scene.frame_end = start, end
    if not start <= scene.frame_current <= end:
        scene.frame_current = start
    return True


@persistent
def _on_update(scene, _depsgraph=None):
    p = _prefs()
    if p is not None and not p.fit_timeline:
        return
    act = _active_action(scene)
    key = act.name_full if act else None
    if key != _last["action"]:
        _last["action"] = key
        if act is not None:
            fit_timeline(scene, act)


class RF4S_OT_import(bpy.types.Operator, ImportHelper):
    """Import a model / motions .glb from the RF4S modding toolkit at the game's 60 fps"""
    bl_idname = "import_scene.rf4s_glb"
    bl_label = "Import RF4S model / motions"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".glb"
    filter_glob: StringProperty(default="*.glb;*.gltf", options={"HIDDEN"})

    def execute(self, context):
        scene = context.scene
        if scene.render.fps != GAME_FPS or scene.render.fps_base != 1.0:
            scene.render.fps, scene.render.fps_base = GAME_FPS, 1.0
            self.report({"INFO"}, "Frame rate set to 60 (the game's)")
        res = bpy.ops.import_scene.gltf(filepath=self.filepath)
        if "FINISHED" not in res:
            return res
        _last["action"] = None
        _on_update(scene)
        n = sum(1 for a in bpy.data.actions)
        self.report({"INFO"}, f"Imported {n} motion(s); the timeline follows the active one")
        return {"FINISHED"}


class RF4S_OT_export(bpy.types.Operator, ExportHelper):
    """Export every action as a .glb for the toolkit's Import motion / Import all motions"""
    bl_idname = "export_scene.rf4s_glb"
    bl_label = "Export RF4S motions"
    filename_ext = ".glb"
    filter_glob: StringProperty(default="*.glb", options={"HIDDEN"})

    def execute(self, context):
        r = context.scene.render
        if r.fps != GAME_FPS or r.fps_base != 1.0:
            self.report({"ERROR"}, f"The frame rate is {r.fps / r.fps_base:g}, not 60: fast moves would "
                                   f"be smoothed away. Set Output > Frame Rate to 60 and re-import the "
                                   f"toolkit's file (File > Import > RF4S model / motions)")
            return {"CANCELLED"}
        return bpy.ops.export_scene.gltf(filepath=self.filepath, export_format="GLB",
                                         export_animations=True)


class RF4S_OT_fit(bpy.types.Operator):
    """Set the scene's frame range to the active motion"""
    bl_idname = "scene.rf4s_fit_timeline"
    bl_label = "Fit Timeline to Motion"

    def execute(self, context):
        if not fit_timeline(context.scene):
            self.report({"WARNING"}, "No armature with an action")
            return {"CANCELLED"}
        return {"FINISHED"}


class RF4S_Prefs(bpy.types.AddonPreferences):
    bl_idname = __name__
    fit_timeline: BoolProperty(name="Fit the timeline to the active motion", default=True,
                               description="When the armature's action changes, set the scene's "
                                           "frame range to it (frame 0 .. its last frame)")

    def draw(self, _context):
        self.layout.prop(self, "fit_timeline")


def _menu_import(self, _context):
    self.layout.operator(RF4S_OT_import.bl_idname, text="RF4S model / motions (.glb)")


def _menu_export(self, _context):
    self.layout.operator(RF4S_OT_export.bl_idname, text="RF4S motions (.glb)")


def _menu_timeline(self, _context):
    self.layout.operator(RF4S_OT_fit.bl_idname)


_classes = (RF4S_OT_import, RF4S_OT_export, RF4S_OT_fit, RF4S_Prefs)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)
    bpy.types.TOPBAR_MT_file_export.append(_menu_export)
    if hasattr(bpy.types, "TIME_MT_view"):
        bpy.types.TIME_MT_view.append(_menu_timeline)
    if hasattr(bpy.types, "DOPESHEET_MT_view"):
        bpy.types.DOPESHEET_MT_view.append(_menu_timeline)
    if _on_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_update)


def unregister():
    if _on_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_update)
    for mt in ("TIME_MT_view", "DOPESHEET_MT_view"):
        if hasattr(bpy.types, mt):
            getattr(bpy.types, mt).remove(_menu_timeline)
    bpy.types.TOPBAR_MT_file_export.remove(_menu_export)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
