#!/usr/bin/env python3
"""Feature census: which X3D features survive into the glb, engine writer vs shape-tree exporter.
Usage: census_compare.py OLD_census.json NEW_GLB_DIR [out.json]
OLD_census.json rows: {key, x3d:{texture,vcolor,light,camera,anim,inline,lines,points,text}, glb:{...}}"""
import sys, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glb_inspect import inspect
old = json.load(open(sys.argv[1])); newdir = sys.argv[2]
feat = ['texture', 'vcolor', 'light', 'camera', 'anim', 'lines', 'points']
res = {f: {'x3d': 0, 'engine_writer': 0, 'shape_tree_exporter': 0} for f in feat}
rows = []
for r in old:
    p = f"{newdir}/{r['key']}.glb"
    i = inspect(p)
    modes = {str(k) for k in i['modes']} if isinstance(i['modes'], dict) else set()
    n = {'texture': i['textures'] > 0, 'vcolor': 'COLOR_0' in i['attributes'], 'light': i['lights'] > 0,
         'camera': i['cameras'] > 0, 'anim': i['animations'] > 0,
         'lines': bool(modes & {'1', '2', '3'}), 'points': '0' in modes, 'meshes': i['meshes']}
    rows.append({'key': r['key'], 'x3d': r['x3d'], 'old_glb': r['glb'], 'new_glb': n})
    for f in feat:
        if r['x3d'].get(f):
            res[f]['x3d'] += 1
            res[f]['engine_writer'] += 1 if r['glb'].get(f) else 0
            res[f]['shape_tree_exporter'] += 1 if n[f] else 0
tot_old = sum(r['old_glb']['meshes'] for r in rows); tot_new = sum(r['new_glb']['meshes'] for r in rows)
empty_old = sum(1 for r in rows if r['old_glb']['meshes'] == 0); empty_new = sum(1 for r in rows if r['new_glb']['meshes'] == 0)
print(f"{'feature':10} {'scenes':>6} {'engine':>7} {'new':>5}")
for f in feat:
    c = res[f]; print(f"{f:10} {c['x3d']:6} {c['engine_writer']:7} {c['shape_tree_exporter']:5}")
print(f"meshes total: engine {tot_old}, new {tot_new}; scenes with zero meshes: engine {empty_old}, new {empty_new}")
if len(sys.argv) > 3:
    json.dump({'features': res, 'meshes_engine': tot_old, 'meshes_new': tot_new, 'empty_engine': empty_old, 'empty_new': empty_new, 'rows': rows}, open(sys.argv[3], 'w'), indent=1)
