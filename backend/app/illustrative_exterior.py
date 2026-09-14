"""Illustrative architecture for explicitly synthetic fixtures, never cadastral geometry."""

import math
from pathlib import Path

import bpy
from mathutils import Vector


def build_appearance(spec, output):
    if not spec or not spec.get("synthetic"):
        return
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    mats = {}
    for name, color, roughness, metal in [
        ("Ivory render", (0.82, 0.82, 0.79, 1), 0.75, 0),
        ("Pale stone", (0.65, 0.64, 0.60, 1), 0.82, 0),
        ("Charcoal frames", (0.075, 0.09, 0.095, 1), 0.45, 0.25),
        ("Smoked glazing", (0.16, 0.22, 0.25, 1), 0.19, 0.45),
        ("Balcony soffit", (0.91, 0.91, 0.87, 1), 0.65, 0),
        ("Warm facade", (0.40, 0.34, 0.27, 1), 0.72, 0),
        ("Paving", (0.64, 0.65, 0.62, 1), 0.95, 0),
        ("Road", (0.48, 0.51, 0.51, 1), 1, 0),
        ("Lawn", (0.29, 0.37, 0.24, 1), 1, 0),
        ("Foliage", (0.23, 0.32, 0.19, 1), 1, 0),
        ("Light foliage", (0.36, 0.43, 0.27, 1), 1, 0),
        ("Bark", (0.23, 0.19, 0.14, 1), 1, 0),
        ("Context", (0.89, 0.90, 0.89, 1), 1, 0),
        ("Parcel blue", (0.15, 0.47, 0.84, 1), 0.65, 0),
    ]:
        material = bpy.data.materials.new(name)
        material.diffuse_color = color
        material.use_nodes = True
        shader = material.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Roughness"].default_value = roughness
        shader.inputs["Metallic"].default_value = metal
        mats[name] = material
    objects = []

    def cube(name, center, size, material="Ivory render"):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(
            [
                (sx * size[0] / 2, sy * size[1] / 2, sz * size[2] / 2)
                for sx, sy, sz in [
                    (-1, -1, -1),
                    (1, -1, -1),
                    (1, 1, -1),
                    (-1, 1, -1),
                    (-1, -1, 1),
                    (1, -1, 1),
                    (1, 1, 1),
                    (-1, 1, 1),
                ]
            ],
            [],
            [
                (0, 3, 2, 1),
                (4, 5, 6, 7),
                (0, 1, 5, 4),
                (1, 2, 6, 5),
                (2, 3, 7, 6),
                (3, 0, 4, 7),
            ],
        )
        mesh.materials.append(mats[material])
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        obj.location = center
        obj["visualization_only"] = True
        obj["source"] = "ILLUSTRATIVE_SYNTHETIC_ARCHITECTURE"
        obj["building_id"] = spec["building_id"]
        objects.append(obj)
        return obj

    # Reuse deterministic canopy meshes to avoid repeated scene-wide operator updates.
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1)
    template_object = bpy.context.object
    template_mesh = template_object.data
    canopies = []
    for n in range(11):
        mesh = template_mesh.copy()
        for vertex in mesh.vertices:
            vertex.co *= 1 + 0.12 * math.sin(vertex.index * 13.37 + n)
        for polygon in mesh.polygons:
            polygon.use_smooth = True
        mesh.materials.append(mats["Foliage" if n % 2 else "Light foliage"])
        canopies.append(mesh)
    bpy.data.objects.remove(template_object, do_unlink=True)

    def tree(x, y, z, scale=1):
        cube(
            "Tree trunk",
            (x, y, z + 1.1 * scale),
            (0.2 * scale, 0.2 * scale, 2.2 * scale),
            "Bark",
        )
        for n, (dx, dy, dz) in enumerate(
            [
                (
                    math.cos(i * 2.4) * 0.85,
                    math.sin(i * 2.4) * 0.85,
                    2.35 + (i % 3) * 0.4,
                )
                for i in range(11)
            ]
        ):
            obj = bpy.data.objects.new("Illustrative canopy", canopies[n])
            bpy.context.collection.objects.link(obj)
            obj.location = (x + dx * scale, y + dy * scale, z + dz * scale)
            obj.scale = (0.85 * scale, 0.8 * scale, 0.95 * scale)
            obj["visualization_only"] = True
            objects.append(obj)

    x0, y0, z0, x1, y1, z1 = spec["bounds"]
    full_w, full_d = x1 - x0, y1 - y0
    w, d = full_w, full_d
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    ground = spec["levels"][0][0]
    # Facades sit inside the recorded building envelope. Details are design illustrations.
    for level, (lo, hi) in enumerate(spec["levels"]):
        h = hi - lo
        top = level == len(spec["levels"]) - 1
        # An illustrative setback uses the existing top floor, not an extra storey.
        w, d = (full_w - 3.2, full_d - 3.2) if top else (full_w, full_d)
        if top:
            cube(
                "Terrace slab",
                (cx, cy, lo + 0.12),
                (full_w, full_d, 0.24),
                "Balcony soffit",
            )
            for sign in [-1, 1]:
                cube(
                    "Terrace railing",
                    (cx, cy + sign * (full_d / 2 - 0.1), lo + 1.1),
                    (full_w, 0.06, 0.07),
                    "Charcoal frames",
                )
                cube(
                    "Terrace railing",
                    (cx + sign * (full_w / 2 - 0.1), cy, lo + 1.1),
                    (0.06, full_d, 0.07),
                    "Charcoal frames",
                )
                for post in range(13):
                    cube(
                        "Terrace post",
                        (
                            cx - full_w / 2 + post * full_w / 12,
                            cy + sign * (full_d / 2 - 0.1),
                            lo + 0.65,
                        ),
                        (0.05, 0.05, 0.9),
                        "Charcoal frames",
                    )
        cube("Floor slab", (cx, cy, lo + 0.12), (w, d, 0.24), "Balcony soffit")
        cube(
            "Interior core",
            (cx, cy, (lo + hi) / 2),
            (w - 3.2, d - 3.2, h - 0.24),
            "Pale stone",
        )
        for side in [-1, 1]:
            y = cy + side * (d / 2 - 0.85)
            cube("Recessed facade", (cx, y, lo + h / 2), (w - 1.6, 0.22, h - 0.25))
            bays = 6
            for bay in range(bays):
                x = cx - w / 2 + 1.5 + (w - 3) * bay / (bays - 1)
                cube(
                    "Stone pier",
                    (x - 1.15, y + side * 0.13, lo + h / 2),
                    (0.32, 0.18, h - 0.3),
                    "Warm facade" if bay % 3 == 0 else "Pale stone",
                )
                cube(
                    "Window frame",
                    (x, y + side * 0.16, lo + h * 0.51),
                    (1.55, 0.12, h * 0.73),
                    "Charcoal frames",
                )
                cube(
                    "Glazing",
                    (x, y + side * 0.235, lo + h * 0.51),
                    (1.4, 0.035, h * 0.68),
                    "Smoked glazing",
                )
                cube(
                    "Window mullion",
                    (x, y + side * 0.265, lo + h * 0.51),
                    (0.055, 0.035, h * 0.72),
                    "Charcoal frames",
                )
                cube(
                    "Window transom",
                    (x, y + side * 0.265, lo + h * 0.64),
                    (1.52, 0.035, 0.055),
                    "Charcoal frames",
                )
                # Alternating balconies leave long recessed facade strips like the reference.
                if bay % 3 != 1 and level > 0:
                    by = y + side * 0.5
                    cube(
                        "Balcony plate",
                        (x, by, lo + 0.17),
                        (2.1, 1.4, 0.18),
                        "Balcony soffit",
                    )
                    ry = y + side * 1.13
                    cube(
                        "Railing top",
                        (x, ry, lo + 1.12),
                        (2.05, 0.07, 0.065),
                        "Charcoal frames",
                    )
                    cube(
                        "Railing base",
                        (x, ry, lo + 0.35),
                        (2.05, 0.05, 0.05),
                        "Charcoal frames",
                    )
                    for post in range(8):
                        cube(
                            "Railing baluster",
                            (x - 0.98 + post * 0.28, ry, lo + 0.72),
                            (0.035, 0.035, 0.79),
                            "Charcoal frames",
                        )
                    for edge in [-1, 1]:
                        cube(
                            "Balcony return",
                            (x + edge * 1.0, by, lo + 1.12),
                            (0.045, 1.32, 0.055),
                            "Charcoal frames",
                        )
            cube(
                "Elevation band",
                (cx, y + side * 0.12, hi - 0.16),
                (w - 1.0, 0.34, 0.18),
                "Balcony soffit",
            )
        for side in [-1, 1]:
            x = cx + side * (w / 2 - 0.55)
            cube("Side elevation", (x, cy, lo + h / 2), (0.25, d - 2, h - 0.26))
            for bay in range(5):
                y = cy - d / 2 + 2 + (d - 4) * bay / 4
                cube(
                    "Side frame",
                    (x + side * 0.15, y, lo + h / 2),
                    (0.10, 1.6, h * 0.72),
                    "Charcoal frames",
                )
                cube(
                    "Side glazing",
                    (x + side * 0.21, y, lo + h / 2),
                    (0.03, 1.44, h * 0.66),
                    "Smoked glazing",
                )
                cube(
                    "Side mullion",
                    (x + side * 0.235, y, lo + h / 2),
                    (0.03, 0.045, h * 0.72),
                    "Charcoal frames",
                )
    roof = spec["levels"][-1][1]
    cube("Roof deck", (cx, cy, roof + 0.08), (w + 0.1, d + 0.1, 0.16), "Balcony soffit")
    for side in [-1, 1]:
        cube(
            "Roof parapet",
            (cx, cy + side * (d / 2 - 0.1), roof + 0.23),
            (w, 0.16, 0.14),
            "Pale stone",
        )
        cube(
            "Roof parapet",
            (cx + side * (w / 2 - 0.1), cy, roof + 0.23),
            (0.16, d, 0.14),
            "Pale stone",
        )
    # No extra storey is invented: roof service details use the defined thin roof extent.
    roof_detail = min(0.25, max(0.1, z1 - roof))
    cube(
        "Roof access cap",
        (cx - 3, cy + 2, roof + 0.16),
        (4, 4, roof_detail),
        "Pale stone",
    )
    for ix in range(3):
        cube(
            "Illustrative roof equipment",
            (cx + 2 + ix * 1.4, cy + 2, roof + 0.22),
            (1.1, 1.7, 0.22),
            "Charcoal frames",
        )
    px0, py0, px1, py1 = spec["parcel_bounds"]
    cube(
        "Parcel paving",
        ((px0 + px1) / 2, (py0 + py1) / 2, ground - 0.17),
        (px1 - px0, py1 - py0, 0.22),
        "Paving",
    )
    for side in [-1, 1]:
        yy = py0 + 0.75 if side < 0 else py1 - 0.75
        cube(
            "Garden bed",
            ((px0 + px1) / 2, yy, ground - 0.025),
            (px1 - px0 - 2, 1.2, 0.12),
            "Lawn",
        )
        for n in range(7):
            tree(px0 + 2 + n * (px1 - px0 - 4) / 6, yy, ground, 0.65 if n % 2 else 0.8)
    for side in [-1, 1]:
        xx = px0 + 0.8 if side < 0 else px1 - 0.8
        for n in range(3):
            tree(xx, py0 + 8 + n * 7, ground, 0.8)
    for side in [-1, 1]:
        xx = px0 if side < 0 else px1
        yy = py0 if side < 0 else py1
        cube(
            "Parcel outline",
            (xx, (py0 + py1) / 2, ground + 0.035),
            (0.07, py1 - py0, 0.035),
            "Parcel blue",
        )
        cube(
            "Parcel outline",
            ((px0 + px1) / 2, yy, ground + 0.035),
            (px1 - px0, 0.07, 0.035),
            "Parcel blue",
        )
    # Clearly illustrative context, intentionally pale; no real surrounding records implied.
    cube("Context base", (cx, cy, ground - 0.5), (160, 160, 0.35), "Context")
    for offset in [-26, 26]:
        cube(
            "Illustrative street",
            (cx + offset, cy, ground - 0.27),
            (7, 160, 0.06),
            "Road",
        )
        cube(
            "Illustrative street",
            (cx, cy + offset, ground - 0.27),
            (160, 7, 0.06),
            "Road",
        )
        for n in range(-7, 8):
            cube(
                "Road marking",
                (cx + offset, cy + n * 6, ground - 0.225),
                (0.09, 2, 0.018),
                "Balcony soffit",
            )
            cube(
                "Road marking",
                (cx + n * 6, cy + offset, ground - 0.225),
                (2, 0.09, 0.018),
                "Balcony soffit",
            )
    for ix in range(-2, 3):
        for iy in range(-2, 3):
            if ix == 0 and iy == 0:
                continue
            xx, yy = cx + ix * 40, cy + iy * 40
            height = 5 + ((ix + 3) * 7 + (iy + 3) * 3) % 10
            cube(
                "Illustrative context building",
                (xx, yy, ground + height / 2),
                (18 + ix % 3 * 2, 17 + iy % 3 * 3, height),
                "Context",
            )
            if abs(ix) < 2 and abs(iy) < 2:
                for n in [-1, 1]:
                    tree(xx + n * 11, yy - 11, ground, 0.9)
    # One visual asset; model extras explicitly distinguish it from cadastral export files.
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=str(Path(output) / "appearance.glb"),
        export_format="GLB",
        use_selection=True,
        export_extras=True,
        export_yup=True,
    )
    # Render an actual preview from this same mesh, never a supplied/fake satellite photo.
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 480
    scene.render.resolution_y = 480
    scene.render.resolution_percentage = 100
    world = bpy.data.worlds.new("Soft daylight")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.85, 0.87, 0.9, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.65
    bpy.ops.object.light_add(type="SUN", location=(cx - 30, cy - 40, ground + 60))
    sun = bpy.context.object
    sun.data.energy = 2
    sun.data.angle = 0.12
    sun.rotation_euler = (0.45, -0.5, -0.4)
    bpy.ops.object.camera_add(location=(cx + 38, cy - 49, roof + 27))
    camera = bpy.context.object
    camera.rotation_euler = (
        (Vector((cx, cy, ground + (roof - ground) / 2)) - camera.location)
        .to_track_quat("-Z", "Y")
        .to_euler()
    )
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(w, d, roof - ground) * 1.75
    scene.camera = camera
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(Path(output) / "appearance.png")
    bpy.ops.render.render(write_still=True)
    camera.location = (cx, cy, ground + 100)
    camera.rotation_euler = (0, 0, 0)
    camera.data.ortho_scale = max(px1 - px0, py1 - py0) * 1.3
    scene.render.filepath = str(Path(output) / "site-preview.png")
    bpy.ops.render.render(write_still=True)
