import os
import shutil
from typing import Type

import bpy

import arm.assets as assets
from arm.exporter import ArmoryExporter
import arm.log as log
import arm.make as make
import arm.make_state as state
import arm.utils

# Current patch id
patch_id = 0

# Any object can act as a message bus owner
msgbus_owner = object()


def start():
    log.debug("Live patch session started")

    listen(bpy.types.Object, "location", "obj_location")
    listen(bpy.types.Object, "rotation_euler", "obj_rotation")
    listen(bpy.types.Object, "scale", "obj_scale")


def patch_export():
    """Re-export the current scene and update the game accordingly."""
    if state.proc_build is not None:
        return

    assets.invalidate_enabled = False
    fp = arm.utils.get_fp()

    with arm.utils.WorkingDir(fp):
        asset_path = arm.utils.get_fp_build() + '/compiled/Assets/' + arm.utils.safestr(bpy.context.scene.name) + '.arm'
        ArmoryExporter.export_scene(bpy.context, asset_path, scene=bpy.context.scene)

        if not os.path.isdir(arm.utils.build_dir() + '/compiled/Shaders/std'):
            raw_shaders_path = arm.utils.get_sdk_path() + '/armory/Shaders/'
            shutil.copytree(raw_shaders_path + 'std', arm.utils.build_dir() + '/compiled/Shaders/std')
        node_path = arm.utils.get_node_path()
        khamake_path = arm.utils.get_khamake_path()

        cmd = [
            node_path, khamake_path, 'krom',
            '--shaderversion', '330',
            '--parallelAssetConversion', '4',
            '--to', arm.utils.build_dir() + '/debug',
            '--nohaxe',
            '--noproject'
        ]

        assets.invalidate_enabled = True
        state.proc_build = make.run_proc(cmd, patch_done)


def patch_done():
    """Signal Iron to reload the running scene after a re-export."""
    js = 'iron.Scene.patch();'
    write_patch(js)
    state.proc_build = None
    bpy.msgbus.clear_by_owner(msgbus_owner)


def write_patch(js: str):
    """Write the given javascript code to 'krom.patch'."""
    global patch_id
    with open(arm.utils.get_fp_build() + '/debug/krom/krom.patch', 'w') as f:
        patch_id += 1
        f.write(str(patch_id) + '\n')
        f.write(js)


def listen(rna_type: Type[bpy.types.Struct], prop: str, event_id: str):
    """Subscribe to '<rna_type>.<prop>'. The event_id can be choosen
    freely but must match with the id used in send_event().
    """
    bpy.msgbus.subscribe_rna(
        key=(rna_type, prop),
        owner=msgbus_owner,
        args=(event_id, ),
        notify=send_event
        # options={"PERSISTENT"}
    )


def send_event(event_id: str):
    """Send the result of the given event to Krom."""
    if hasattr(bpy.context, 'object') and bpy.context.object is not None:
        obj = bpy.context.object.name

        if bpy.context.object.mode == "OBJECT":
            if event_id == "obj_location":
                vec = bpy.context.object.location
                js = f'var o = iron.Scene.active.getChild("{obj}"); o.transform.loc.set({vec[0]}, {vec[1]}, {vec[2]}); o.transform.dirty = true;'
                write_patch(js)

            elif event_id == 'obj_scale':
                vec = bpy.context.object.scale
                js = f'var o = iron.Scene.active.getChild("{obj}"); o.transform.scale.set({vec[0]}, {vec[1]}, {vec[2]}); o.transform.dirty = true;'
                write_patch(js)

            elif event_id == 'obj_rotation':
                vec = bpy.context.object.rotation_euler.to_quaternion()
                js = f'var o = iron.Scene.active.getChild("{obj}"); o.transform.rot.set({vec[1]}, {vec[2]}, {vec[3]}, {vec[0]}); o.transform.dirty = true;'
                write_patch(js)

        else:
            patch_export()


def on_operator(operator_id: str):
    """As long as bpy.msgbus doesn't listen to changes made by
    operators (*), additionally notify the callback manually.

    (*) https://developer.blender.org/T72109
    """
    # Don't re-export the scene for the following operators
    if operator_id in ("VIEW3D_OT_select", "OUTLINER_OT_item_activate", "OBJECT_OT_editmode_toggle"):
        return

    if operator_id == "TRANSFORM_OT_translate":
        send_event("obj_location")
    elif operator_id == "TRANSFORM_OT_rotate":
        send_event("obj_rotation")
    elif operator_id == "TRANSFORM_OT_resize":
        send_event("obj_scale")

    # Rebuild
    else:
        patch_export()
