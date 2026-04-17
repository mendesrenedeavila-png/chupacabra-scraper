"""Helper: creates hand-crafted sample output pages for CLI smoke tests."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import formatter

PAGES = [
    ('alpha', (
        '---\n'
        'title: "Alpha Page"\n'
        'source_url: "https://example.com/alpha"\n'
        'scraped_at: "2026-04-17T00:00:00Z"\n'
        'breadcrumb: ["Root"]\n'
        '---\n\n'
        '## Introduction\n\n'
        'This is the **alpha** page content.\n'
    )),
    ('beta', (
        '---\n'
        'title: "Beta Page"\n'
        'source_url: "https://example.com/beta"\n'
        'scraped_at: "2026-04-17T00:01:00Z"\n'
        'breadcrumb: ["Root", "Sub"]\n'
        '---\n\n'
        '## Overview\n\n'
        'The **beta** page discusses another topic.\n'
    )),
]

OUT = pathlib.Path('/home/renem/CHUPACABRA/output')
OUT.mkdir(parents=True, exist_ok=True)

for stem, md in PAGES:
    (OUT / f'{stem}.md').write_text(md, encoding='utf-8')
    (OUT / f'{stem}.txt').write_text(formatter.to_txt(md), encoding='utf-8')
    (OUT / f'{stem}.html').write_text(formatter.to_html(md), encoding='utf-8')
    (OUT / f'{stem}.pdf').write_bytes(formatter.to_pdf(md))
    print(f'  created {stem}.{{md,txt,html,pdf}}')
