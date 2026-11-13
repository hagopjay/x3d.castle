#!/usr/bin/env python3
"""Run x3d-castle-convert over a list of scenes; keep per-scene logs, export.json and a timing table.
Scenes that reference .webp textures are exported from a patched COPY (webp_prepass.py), because Castle cannot decode WebP.
Usage: export_all.py scenes.txt OUTDIR CONVERTER REPO_ROOT [extra converter args...]"""
import sys, os, subprocess, time, json, re
scenes, out, conv, root = sys.argv[1:5]; extra = sys.argv[5:]
os.makedirs(f'{out}/glb', exist_ok=True); os.makedirs(f'{out}/logs', exist_ok=True)
rows = []
for line in open(scenes):
    p = line.strip()
    if not p: continue
    if '=' in p and not os.path.exists(p): name, p = p.split('=', 1)
    else: name = os.path.relpath(p, root).rsplit('.', 1)[0].replace('/', '__')
    g = f'{out}/glb/{name}.glb'
    src = p
    try:
        if p.endswith('.x3d') and re.search(r'\.webp', open(p, encoding='utf-8', errors='replace').read(), re.I):
            q = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'webp_prepass.py'), p, os.path.abspath(f'{out}/prepass/{name}')],
                               capture_output=True, text=True)
            if q.returncode == 0 and q.stdout.strip():
                src = q.stdout.strip().splitlines()[0]
    except OSError:
        pass
    t = time.time()
    r = subprocess.run([conv, src, g, '--verbose'] + extra, capture_output=True, text=True, timeout=300)
    dt = time.time() - t
    open(f'{out}/logs/{name}.log', 'w').write(r.stderr + r.stdout)
    rows.append({'key': name, 'x3d': p, 'webp_prepass': src != p, 'glb': g, 'rc': r.returncode, 'seconds': round(dt, 2),
                 'ok': r.returncode == 0 and os.path.exists(g),
                 'bytes': os.path.getsize(g) if os.path.exists(g) else 0})
    print(f"{name[-48:]:48} rc={r.returncode} {dt:5.2f}s {rows[-1]['bytes']}B", flush=True)
json.dump(rows, open(f'{out}/export-run.json', 'w'), indent=1)
print('ok', sum(r['ok'] for r in rows), 'of', len(rows))
