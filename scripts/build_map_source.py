"""Regenerate the supplementary PDF previews and metadata (requires PyMuPDF).

The PDF is reference data; no embedded instructions or scripts are executed.
Run this after replacing the source PDF, then run build_primary_source.py.
"""
from pathlib import Path
import hashlib
import json
import fitz

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'sources/prague-post/Mapa_prazske_potrubni_posty_1932-1939.pdf'
OUTPUT = ROOT / 'sources/prague-post/mapa'
OUTPUT.mkdir(parents=True, exist_ok=True)
TITLES = ['Přehled sítě a legenda', 'Soupis větví a prameny', 'Soukromé přípojky v centru']
pages, links = [], []
with fitz.open(SOURCE) as doc:
    for number, page in enumerate(doc, 1):
        preview = OUTPUT / f'strana-{number}.png'
        transcript = OUTPUT / f'strana-{number}.txt'
        page.get_pixmap(matrix=fitz.Matrix(2, 2)).save(preview)
        transcript.write_text(page.get_text())
        pages.append({
            'number': number,
            'title': TITLES[number-1] if number <= len(TITLES) else f'Strana {number}',
            'image': preview.relative_to(ROOT).as_posix(),
            'text': transcript.relative_to(ROOT).as_posix(),
            'image_sha256': hashlib.sha256(preview.read_bytes()).hexdigest(),
        })
        for link in page.get_links():
            if link.get('uri', '').startswith(('https://', 'http://')):
                links.append({
                    'page': number, 'url': link['uri'],
                    'label': ' '.join(page.get_textbox(link['from']).split()) or link['uri'],
                })
manifest = {
    'source': SOURCE.relative_to(ROOT).as_posix(),
    'sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    'page_count': len(pages), 'pages': pages, 'links': links,
}
(OUTPUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
print(f'PDF source: {len(pages)} pages, {len(links)} external-link occurrences.')
