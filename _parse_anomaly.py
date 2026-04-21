import re, glob

clean = lambda s: re.sub(r'<[^>]+>', '', s).strip()

for f in sorted(glob.glob('reports/2026-04-01/hybrid_report_*.html'))[-5:]:
    html = open(f).read()
    rows = re.findall(
        r'<tr>\s*<td[^>]*>([\s\S]*?)</td>\s*<td[^>]*>([\s\S]*?)</td>\s*<td[^>]*>([\s\S]*?)</td>'
        r'\s*<td[^>]*>([\s\S]*?)</td>\s*<td[^>]*>([\s\S]*?)</td>\s*<td[^>]*>([\s\S]*?)</td>'
        r'\s*<td[^>]*>([\s\S]*?)</td>',
        html
    )
    anomalies = []
    for row in rows:
        t_text = clean(row[1])
        if t_text in ('묵음', '깨짐'):
            anomalies.append(tuple(clean(c) for c in row))
    if anomalies:
        name = f.split('/')[-1]
        print(f'\n=== {name} ===')
        for a in anomalies[:15]:
            print(f'  {a[1]:4s} | {a[2]:8s} | {a[3]:30s} | gain={a[4]:8s} | corr={a[5]:6s} | {a[6]}')
