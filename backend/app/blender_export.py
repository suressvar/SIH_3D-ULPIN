"""Run ONLY by Blender in background mode with an internally generated mesh manifest."""

import json
import sys
from pathlib import Path

import bpy

manifest_path = Path(sys.argv[sys.argv.index("--") + 1])
manifest = json.loads(manifest_path.read_text())
output = manifest_path.parent
bpy.ops.wm.read_factory_settings(use_empty=True)
objects = []
for item in manifest["objects"]:
    mesh = bpy.data.meshes.new(item["id"])
    mesh.from_pydata(item["vertices"], [], item["faces"])
    mesh.update()
    if mesh.validate(verbose=False):
        raise RuntimeError("Blender changed an invalid input mesh")
    obj = bpy.data.objects.new(item["label"], mesh)
    bpy.context.collection.objects.link(obj)
    for key, value in item["metadata"].items():
        if value is not None:
            obj[key] = value
    material = bpy.data.materials.new(item["kind"])
    material.diffuse_color = tuple(item["color"])
    material.use_nodes = True
    node = material.node_tree.nodes.get("Principled BSDF")
    node.inputs["Base Color"].default_value = tuple(item["color"])
    node.inputs["Roughness"].default_value = 0.7
    obj.data.materials.append(material)
    objects.append(obj)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(
        filepath=str(output / (item["id"] + ".glb")),
        export_format="GLB",
        use_selection=True,
        export_extras=True,
        export_yup=True,
        export_materials="EXPORT",
    )
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(
    filepath=str(output / "scene.glb"),
    export_format="GLB",
    use_selection=True,
    export_extras=True,
    export_yup=True,
    export_materials="EXPORT",
)
if manifest.get("appearance"):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from illustrative_exterior import build_appearance

    build_appearance(manifest["appearance"], output)
    (output / "appearance.json").write_text(
        json.dumps(manifest["appearance"], indent=2), encoding="utf-8"
    )
print("ASTRA_EXPORT_COMPLETE")
