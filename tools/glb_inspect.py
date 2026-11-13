#!/usr/bin/env python3
"""Summarise a .glb: counts, attribute names used, materials (with extensions), lights, cameras. Usage: glb_inspect.py a.glb [b.glb ...]"""
import json, struct, sys, collections
def inspect(p):
    b = open(p, "rb").read()
    if len(b) < 20 or b[:4] != b"glTF":
        return dict(file=p, error="not a glb")
    ln, typ = struct.unpack_from("<II", b, 12)
    j = json.loads(b[20:20 + ln])
    attrs = collections.Counter(a for m in j.get("meshes", []) for pr in m["primitives"] for a in pr.get("attributes", {}))
    modes = collections.Counter(pr.get("mode", 4) for m in j.get("meshes", []) for pr in m["primitives"])
    mats = j.get("materials", [])
    return dict(file=p.split("/")[-1], bytes=len(b), generator=j["asset"].get("generator", "")[:30], nodes=len(j.get("nodes", [])), meshes=len(j.get("meshes", [])),
                primitives=sum(len(m["primitives"]) for m in j.get("meshes", [])), modes=dict(modes), attributes=dict(attrs), materials=len(mats),
                mat_ext=sorted({e for m in mats for e in m.get("extensions", {})}), pbr_keys=sorted({k for m in mats for k in m.get("pbrMetallicRoughness", {})}),
                textures=len(j.get("textures", [])), images=len(j.get("images", [])), lights=len(j.get("extensions", {}).get("KHR_lights_punctual", {}).get("lights", [])),
                cameras=len(j.get("cameras", [])), animations=len(j.get("animations", [])), ext_used=j.get("extensionsUsed", []), skins=len(j.get("skins", [])))
if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(json.dumps(inspect(p)))
