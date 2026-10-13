"""
Syntropic137 hero scene for Blender (4.0+; tested headless on 4.0.2).

Builds the "run city" (one cube per day of agent runs) and the Syntropic137 S made
of cubes standing in it, using the same geometry and palette as the Skyline design
boards. Optionally animates the city rising and the S dropping in cube by cube.

Usage (headless):
  blender -b -P build_hero.py -- --shot hero --res 1600x900 --samples 64 --out renders/hero.png
  blender -b -P build_hero.py -- --shot hero --animate --res 1920x1080 --samples 48 --out renders/frames/hero_####.png
  blender -b -P build_hero.py -- --shot hero --save scenes/hero.blend      # just build and save, then open in Blender

Shots: hero (wide 16:9, the S in the city), banner (3:1 header), mark (the S alone, close).
Everything after `--` is ours; Blender ignores it.
"""
import argparse
import math
import sys

import bpy
from mathutils import Vector

# ---------------------------------------------------------------- args
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument('--shot', default='hero', choices=['hero', 'banner', 'mark'])
ap.add_argument('--res', default='1600x900')
ap.add_argument('--samples', type=int, default=64)
ap.add_argument('--out', default='')
ap.add_argument('--save', default='')
ap.add_argument('--animate', action='store_true')
ap.add_argument('--fps', type=int, default=24)
ap.add_argument('--seconds', type=float, default=6.0)
ap.add_argument('--accent', default='#4D80FF')
ap.add_argument('--engine', default='CYCLES', choices=['CYCLES', 'BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'])
ap.add_argument('--device', default='CPU', choices=['CPU', 'GPU'])
ap.add_argument('--only-s', action='store_true', help='hide the city: the S alone (pair with --transparent)')
ap.add_argument('--border', default='', help='render only this region, x0,x1,y0,y1 in 0..1 (origin bottom-left), cropped')
ap.add_argument('--transparent', action='store_true', help='transparent background (RGBA PNG); the floor becomes a shadow catcher')
ap.add_argument('--no-denoise', action='store_true', help='for Blender builds without OpenImageDenoise (e.g. Ubuntu apt)')
args = ap.parse_args(argv)


def hex_rgb(h, a=1.0):
    h = h.lstrip('#')
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]
    return (*lin, a)


# Palette: the canvas syn137 theme
ACCENT = args.accent
BG = '#06080E'
DARK = '#262F4D'
DARK_TOP = '#2B3350'
FAIL = '#FF6F61'
ERR = '#E5B450'

# ---------------------------------------------------------------- reset scene
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = args.fps


# ---------------------------------------------------------------- materials
def mat(name, color, rough=0.4, metal=0.0, emit=0.0, emit_color=None, transmission=0.0, ior=1.45, alpha=1.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = hex_rgb(color)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    for key in ('Transmission Weight', 'Transmission'):
        if key in b.inputs:
            b.inputs[key].default_value = transmission
    b.inputs['IOR'].default_value = ior
    for key in ('Emission Color', 'Emission'):
        if key in b.inputs:
            b.inputs[key].default_value = hex_rgb(emit_color or color)
            break
    if 'Emission Strength' in b.inputs:
        b.inputs['Emission Strength'].default_value = emit
    if 'Coat Weight' in b.inputs:
        b.inputs['Coat Weight'].default_value = 0.25
    b.inputs['Alpha'].default_value = alpha
    return m


M = {
    'blue': mat('S Blue', ACCENT, rough=0.28, emit=0.35),
    'blue_live': mat('City Live', ACCENT, rough=0.3, emit=3.0),
    'city': mat('City Block', ACCENT, rough=0.45, emit=0.08),
    'city_dim': mat('City Block Dim', '#2A3B66', rough=0.55, emit=0.02),
    'dark': mat('S Dark', DARK, rough=0.3, metal=0.35),
    'glass': mat('S Glass', '#E8EEFB', rough=0.04, transmission=1.0, ior=1.5),
    'fail': mat('City Failed', FAIL, rough=0.35, emit=2.2),
    'err': mat('City Errored', ERR, rough=0.35, emit=1.4),
    'floor': mat('Floor', BG, rough=0.85),
}


# ---------------------------------------------------------------- geometry helpers
def cube(name, loc, size, height, material, bevel=0.03):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(loc[0], loc[1], height / 2))
    o = bpy.context.active_object
    o.name = name
    o.scale = (size, size, height)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        bv = o.modifiers.new('bevel', 'BEVEL')
        bv.width = bevel
        bv.segments = 3
        bv.limit_method = 'ANGLE'
    o.data.materials.append(material)
    # origin at the base so scaling Z "grows" the block from the floor
    bpy.context.scene.cursor.location = (loc[0], loc[1], 0)
    bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
    return o


# ---------------------------------------------------------------- the run city
# Same activity function as gen_landing2.city(): rises toward the front (recent),
# with a deterministic wobble and some quiet days.
def city(cols, rows, cell=1.0, gap=0.12, live=(), fails=(), errs=(), skip=()):
    blocks = []
    for j in range(rows):
        for i in range(cols):
            k = j * cols + i
            if (i, j) in skip:
                continue
            ramp = (i + (rows - j) * 0.35) / (cols + rows * 0.35)
            wob = ((k * 37) % 13) / 13
            act = (0.12 + 0.88 * ramp) * (0.4 + 0.6 * wob)
            if (k * 17) % 9 == 0:
                act *= 0.2
            h = 0.08 + act * 2.4
            if k in fails:
                m = M['fail']
            elif k in errs:
                m = M['err']
            elif k in live:
                m = M['blue_live']
            else:
                m = M['city'] if act > 0.35 else M['city_dim']
            x = (i - cols / 2) * cell
            y = (j - rows / 2) * cell
            o = cube(f'day_{k:03d}', (x, y), cell - gap, h, m, bevel=0.02)
            blocks.append((o, i + j))
    return blocks


# ---------------------------------------------------------------- the S, in cubes
# Rows top -> bottom; B blue, D dark, G glass. Matches logo.png.
S_GRID = ['BBG', 'B..', 'DDD', '..D', 'DDD']


def s_mark(origin, size, gap=0.06):
    """Cubes stacked in one vertical plane (X = along the plane, Z = up)."""
    cubes = []
    rows = len(S_GRID)
    for r, line in enumerate(S_GRID):
        for c, t in enumerate(line):
            if t == '.':
                continue
            level = rows - 1 - r
            m = {'B': M['blue'], 'D': M['dark'], 'G': M['glass']}[t]
            x = origin[0] + c * size
            y = origin[1]
            bpy.ops.mesh.primitive_cube_add(size=size - gap, location=(x, y, origin[2] + level * size + size / 2))
            o = bpy.context.active_object
            o.name = f'S_{r}{c}_{t}'
            bv = o.modifiers.new('bevel', 'BEVEL')
            bv.width = size * 0.035
            bv.segments = 4
            o.data.materials.append(m)
            cubes.append((o, r * 3 + c))
    return cubes


# ---------------------------------------------------------------- compose shot
shot = args.shot
if shot == 'mark':
    cols, rows = 10, 6
else:
    cols, rows = (30, 14) if shot == 'banner' else (24, 12)

S_SIZE = 1.9 if shot != 'mark' else 2.4
s_origin = (-S_SIZE, 0.0, 0.0)
# clear the city where the S stands
skip = set()
for c in range(-4, 5):
    for jj in range(-2, 3):
        skip.add((cols // 2 + c, rows // 2 + jj))
blocks = city(cols, rows, live=(150, 171, 199, 222, 61, 97), fails=(88, 260, 33), errs=(141,), skip=skip)
s_cubes = s_mark(s_origin, S_SIZE)

# floor
bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, 0))
floor = bpy.context.active_object
floor.name = 'Floor'
floor.data.materials.append(M['floor'])
if args.only_s:
    for o, _ in blocks:
        o.hide_render = True
if args.transparent:
    floor.is_shadow_catcher = True  # keeps shadows + reflections, drops the floor itself
_fb = M['floor'].node_tree.nodes['Principled BSDF']
for key in ('Specular IOR Level', 'Specular'):
    if key in _fb.inputs:
        _fb.inputs[key].default_value = 0.0
# lights light the scene but never show up as shapes in the frame
for _o in bpy.data.objects:
    pass

# ---------------------------------------------------------------- world + lights
world = bpy.data.worlds.new('World')
scene.world = world
world.use_nodes = True
world.node_tree.nodes['Background'].inputs['Color'].default_value = hex_rgb(BG)
world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.35


def area(name, loc, energy, color, size, target=(0, 0, 1)):
    bpy.ops.object.light_add(type='AREA', location=loc)
    l = bpy.context.active_object
    l.name = name
    l.data.energy = energy
    l.data.color = hex_rgb(color)[:3]
    l.data.size = size
    d = Vector(target) - Vector(loc)
    l.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    l.visible_camera = False
    return l


area('Key', (-14, -18, 22), 5200, '#DCE6FF', 14)
area('Rim', (16, 18, 10), 3800, ACCENT, 10)
# Back: no glossy visibility, else its 8 m panel mirrors in the city's block tops as a grey square
area('Back', (-18, 14, 12), 2600, '#9DB8FF', 8, target=(s_origin[0] + S_SIZE, 0, S_SIZE * 2.5)).visible_glossy = False
area('Fill', (20, -6, 6), 700, '#9AA8C7', 8)
area('S Spot', (-6, -8, 14), 900, '#FFFFFF', 3, target=(s_origin[0] + S_SIZE, 0, S_SIZE * 2.5))

# ---------------------------------------------------------------- camera
bpy.ops.object.camera_add()
cam = bpy.context.active_object
scene.camera = cam
if shot == 'mark':
    cam.data.type = 'PERSP'
    cam.data.lens = 70
    cam.location = (14, -16, 12)
    look = Vector((s_origin[0] + S_SIZE, 0, S_SIZE * 2.4))
else:
    # true isometric, like the boards: orthographic, 54.7356 deg down, 45 deg around
    cam.data.type = 'ORTHO'
    cam.data.ortho_scale = 34 if shot == 'banner' else 27
    cam.rotation_euler = (math.radians(54.7356), 0, math.radians(45))
    d = 60
    look = Vector((s_origin[0] + S_SIZE, 0, S_SIZE * 2.1))
    cam.location = look + Vector((d * math.sin(math.radians(45)) * math.sin(math.radians(54.7356)),
                                  -d * math.cos(math.radians(45)) * math.sin(math.radians(54.7356)),
                                  d * math.cos(math.radians(54.7356))))
if cam.data.type == 'PERSP':
    cam.rotation_euler = (look - cam.location).to_track_quat('-Z', 'Y').to_euler()
cam.data.clip_end = 400

# ---------------------------------------------------------------- render settings
w, h = (int(x) for x in args.res.lower().split('x'))
r = scene.render
r.resolution_x, r.resolution_y = w, h
r.resolution_percentage = 100
r.engine = args.engine
if args.engine == 'CYCLES':
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = not args.no_denoise
    scene.cycles.device = args.device
    if args.device == 'GPU':
        prefs = bpy.context.preferences.addons['cycles'].preferences
        for backend in ('METAL', 'OPTIX', 'CUDA', 'HIP'):
            try:
                prefs.compute_device_type = backend
                prefs.get_devices()
                for dvc in prefs.devices:
                    dvc.use = True
                break
            except Exception:
                continue
    scene.cycles.max_bounces = 6
    scene.cycles.transmission_bounces = 6
r.film_transparent = args.transparent
if args.border:
    r.border_min_x, r.border_max_x, r.border_min_y, r.border_max_y = (float(v) for v in args.border.split(','))
    r.use_border = r.use_crop_to_border = True
scene.view_settings.view_transform = 'AgX' if 'AgX' in [v.identifier for v in scene.view_settings.bl_rna.properties['view_transform'].enum_items] else 'Filmic'
try:
    scene.view_settings.look = 'AgX - Punchy' if scene.view_settings.view_transform == 'AgX' else 'Medium High Contrast'
except TypeError:
    pass

# bloom via compositor glare
if hasattr(scene, 'compositing_node_group'):
    # Blender 5.x: compositor is a node group, Glare settings are inputs
    nt = bpy.data.node_groups.new('Compositor', 'CompositorNodeTree')
    scene.compositing_node_group = nt
    nt.interface.new_socket('Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    rl = nt.nodes.new('CompositorNodeRLayers')
    glare = nt.nodes.new('CompositorNodeGlare')
    glare.inputs['Type'].default_value = 'Fog Glow'
    glare.inputs['Quality'].default_value = 'High'
    glare.inputs['Threshold'].default_value = 0.6
    glare.inputs['Size'].default_value = 0.5  # = 4.x size 8
    comp = nt.nodes.new('NodeGroupOutput')
    nt.links.new(rl.outputs['Image'], glare.inputs['Image'])
    nt.links.new(glare.outputs['Image'], comp.inputs['Image'])
else:
    scene.use_nodes = True
    nt = scene.node_tree
    nt.nodes.clear()
    rl = nt.nodes.new('CompositorNodeRLayers')
    glare = nt.nodes.new('CompositorNodeGlare')
    glare.glare_type = 'FOG_GLOW'
    glare.quality = 'HIGH'
    glare.threshold = 0.6
    glare.size = 8
    comp = nt.nodes.new('CompositorNodeComposite')
    nt.links.new(rl.outputs['Image'], glare.inputs['Image'])
    nt.links.new(glare.outputs['Image'], comp.inputs['Image'])

# ---------------------------------------------------------------- animation
frames = int(args.fps * args.seconds)
scene.frame_start, scene.frame_end = 1, frames
if args.animate:
    rise_end = int(frames * 0.45)
    for o, order in blocks:
        start = 1 + int(order * 0.9)
        o.scale.z = 0.001
        o.keyframe_insert('scale', index=2, frame=start)
        o.scale.z = 1.0
        o.keyframe_insert('scale', index=2, frame=min(start + 18, rise_end))
    drop_start = int(frames * 0.08)  # S builds alongside the city rise, both land by ~45% of the clip
    for o, idx in sorted(s_cubes, key=lambda t: (-t[0].location.z, t[1])):
        pass
    order = sorted(s_cubes, key=lambda t: t[0].location.z)  # bottom first, so cubes stack
    for n, (o, _) in enumerate(order):
        f0 = drop_start + n * 3
        z = o.location.z
        o.location.z = z + 14
        o.keyframe_insert('location', index=2, frame=f0)
        o.location.z = z
        o.keyframe_insert('location', index=2, frame=f0 + 10)
    for o in [b[0] for b in blocks] + [c[0] for c in s_cubes]:
        ad = o.animation_data
        if ad and ad.action:
            if hasattr(ad.action, 'fcurves'):
                fcurves = ad.action.fcurves
            else:  # Blender 5.x layered actions
                from bpy_extras.anim_utils import action_get_channelbag_for_slot
                fcurves = action_get_channelbag_for_slot(ad.action, ad.action_slot).fcurves
            for fc in fcurves:
                for kp in fc.keyframe_points:
                    kp.interpolation = 'CUBIC' if o.name.startswith('S_') else 'EXPO'  # S: plain ease-out, no overshoot
                    kp.easing = 'EASE_OUT'
else:
    scene.frame_set(frames)

# ---------------------------------------------------------------- output
if args.save:
    bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath('//') + args.save if args.save.startswith('//') else args.save)
if args.out:
    r.filepath = args.out
    r.image_settings.file_format = 'PNG'
    r.image_settings.color_mode = 'RGBA' if args.transparent else 'RGB'
    if args.animate:
        bpy.ops.render.render(animation=True)
    else:
        bpy.ops.render.render(write_still=True)
print('done', shot, args.res, 'frames' if args.animate else 'still')
