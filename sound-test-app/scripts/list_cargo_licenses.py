#!/usr/bin/env python3
import json, subprocess, sys

result = subprocess.run(
    ["cargo", "metadata", "--format-version", "1"],
    capture_output=True, text=True,
    cwd="/Users/qabulls/Documents/sound/sound-test-app/src-tauri"
)
data = json.loads(result.stdout)

pkg_map = {p['id']: p for p in data['packages']}
resolve_map = {n['id']: n['deps'] for n in data['resolve']['nodes']}

our_node = None
for node in data['resolve']['nodes']:
    if node['id'].startswith('path+'):
        our_node = node
        break

visited = set()
queue = [our_node['id']]
while queue:
    current = queue.pop()
    if current in visited:
        continue
    visited.add(current)
    for dep_node in resolve_map.get(current, []):
        queue.append(dep_node['pkg'])

seen = set()
results = []
for pid in sorted(visited):
    if pid in pkg_map:
        p = pkg_map[pid]
        if p['name'] == 'sound-test-app':
            continue
        if p['name'] not in seen:
            seen.add(p['name'])
            lic = p.get('license', 'unknown')
            results.append((p['name'], p['version'], lic))

for name, ver, lic in sorted(results):
    print(f"{name} {ver}: {lic}")
