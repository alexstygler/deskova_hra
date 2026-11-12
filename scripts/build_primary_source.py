"""Render the user-designated DOCX source, using only the Python standard library.

Run from any working directory: python scripts/build_primary_source.py
The DOCX is data: field instructions, macros, and embedded code are never executed.
"""
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from html import escape
from urllib.parse import urlsplit
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'sources' / 'prague-post'
DOCX = ASSETS / 'Prazska_potrubni_posta.docx'
NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
}
W, R = NS['w'], NS['r']

def plain(node):
    return ''.join(t.text or '' for t in node.findall('.//w:t', NS))

def style(node):
    st = node.find('w:pPr/w:pStyle', NS)
    return st.get(f'{{{W}}}val', '') if st is not None else ''

with ZipFile(DOCX) as z:
    document = ET.fromstring(z.read('word/document.xml'))
    body = document.find('w:body', NS)
    relationships = {
        rel.get('Id'): {'target': rel.get('Target', ''), 'mode': rel.get('TargetMode', '')}
        for rel in ET.fromstring(z.read('word/_rels/document.xml.rels'))
    }
    paragraphs = list(body.findall('.//w:p', NS))
    paragraph_ids = {id(p): f'odstavec-{i}' for i, p in enumerate(paragraphs, 1)}
    captions = {}
    for i, p in enumerate(paragraphs[:-1]):
        if p.findall('.//a:blip', NS) and style(paragraphs[i+1]) == 'FigureCaption':
            captions[id(p)] = plain(paragraphs[i+1])
    images = []
    links = []

    def inline(node, caption=''):
        local = node.tag.rsplit('}', 1)[-1]
        if local in {'pPr', 'rPr', 'sectPr', 'instrText'}:
            return ''
        if local == 't':
            return escape(node.text or '')
        if local == 'tab':
            return ' '
        if local in {'br', 'cr'}:
            return '<br>'
        if local == 'drawing':
            output = []
            for blip in node.findall('.//a:blip', NS):
                rid = blip.get(f'{{{R}}}embed')
                target = relationships.get(rid, {}).get('target', '')
                if not re.fullmatch(r'media/[A-Za-z0-9_.-]+', target):
                    raise ValueError(f'Unsupported embedded image: {target}')
                filename = Path(target).name
                image_path = ASSETS / 'images' / filename
                image_path.parent.mkdir(parents=True, exist_ok=True)
                data = z.read('word/' + target)
                image_path.write_bytes(data)
                url = f'sources/prague-post/images/{filename}'
                images.append({'path': url, 'sha256': hashlib.sha256(data).hexdigest()})
                output.append(f'<a href="{url}" target="_blank" rel="noopener"><img src="{url}" alt="{escape(caption or filename, quote=True)}" loading="lazy" decoding="async"></a>')
            return ''.join(output)
        content = ''.join(inline(child, caption) for child in node)
        if local == 'hyperlink':
            rel = relationships.get(node.get(f'{{{R}}}id'), {})
            href = rel.get('target', '')
            if urlsplit(href).scheme.lower() in {'http', 'https'}:
                links.append(href)
                return f'<a href="{escape(href, quote=True)}">{content}</a>'
        if local == 'r':
            if node.find('w:rPr/w:b', NS) is not None:
                content = f'<strong>{content}</strong>'
            if node.find('w:rPr/w:i', NS) is not None:
                content = f'<em>{content}</em>'
        return content

    toc = []

    def paragraph(p):
        st = style(p)
        pid = paragraph_ids[id(p)]
        content = inline(p, captions.get(id(p), ''))
        if not content:
            return ''
        if st in {'Heading1', 'Heading2'}:
            level = 'h2' if st == 'Heading1' else 'h3'
            if st == 'Heading1':
                toc.append((pid, plain(p)))
            return f'<{level} id="{pid}">{content}</{level}>'
        if st == 'Image':
            return f'<div class="source-image" id="{pid}">{content}</div>'
        classes = {'Title': 'document-title', 'Subtitle': 'subtitle', 'Sources': 'citations',
                   'FigureCaption': 'caption', 'IndexedBullet': 'sheet-note', 'NoteBullet': 'note'}
        return f'<p id="{pid}" class="{classes.get(st, "text")}">{content}</p>'

    def block(node):
        local = node.tag.rsplit('}', 1)[-1]
        if local == 'p':
            return paragraph(node)
        if local == 'tbl':
            rows = []
            for i, row in enumerate(node.findall('w:tr', NS)):
                cells = []
                for cell in row.findall('w:tc', NS):
                    tag = 'th' if i == 0 else 'td'
                    span = cell.find('w:tcPr/w:gridSpan', NS)
                    attrs = f' colspan="{int(span.get(f"{{{W}}}val"))}"' if span is not None else ''
                    if i == 0:
                        attrs += ' scope="col"'
                    cells.append(f'<{tag}{attrs}>' + ''.join(block(x) for x in cell) + f'</{tag}>')
                rows.append('<tr>' + ''.join(cells) + '</tr>')
            return '<div class="table-wrap"><table>' + ''.join(rows) + '</table></div>'
        return ''

    rendered = '\n'.join(block(node) for node in body)
    toc_html = ''.join(f'<li><a href="#{pid}">{escape(label)}</a></li>' for pid, label in toc)
    manifest = {
        'source': 'sources/prague-post/Prazska_potrubni_posta.docx',
        'sha256': hashlib.sha256(DOCX.read_bytes()).hexdigest(),
        'paragraphs_with_text': sum(bool(plain(p).strip()) for p in paragraphs),
        'embedded_image_occurrences': len(images),
        'unique_images': len({x['path'] for x in images}),
        'external_link_occurrences': len(links),
        'images': images,
    }
    (ASSETS / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')

page = '''<!doctype html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Zdrojové materiály — Pražská potrubní pošta</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, sans-serif; color: #24332d; background: #f5f3eb; }
    body { max-width: 980px; margin: auto; padding: 28px 20px 64px; line-height: 1.7; }
    h1,h2,h3 { line-height: 1.25; } h1 { font-size: clamp(2rem,6vw,3rem); }
    h2 { margin-top: 2.5rem; border-bottom: 1px solid #d8dfd3; padding-bottom: 12px; }
    a { color: #245e45; overflow-wrap: anywhere; }
    nav.site-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 28px; }
    .site-tabs a { padding: 10px 18px; border: 1px solid #397558; border-radius: 8px; text-decoration: none; }
    .site-tabs a[aria-current="page"] { background: #245e45; color: white; }
    section, article { background: #fffef9; padding: 24px; border: 1px solid #d8dfd3; border-radius: 12px; margin: 20px 0; }
    .label { color: #526756; font-size: .85rem; text-transform: uppercase; letter-spacing: .06em; }
    .document-title { font-size: 1.6rem; font-weight: 700; } .subtitle { font-size: 1.15rem; }
    .citations,.caption { font-size: .9rem; color: #526756; }
    .caption { margin-top: 6px; } .source-image { margin-top: 24px; }
    .source-image img { display: block; width: auto; max-width: 100%; height: auto; margin: auto; }
    .note,.sheet-note { padding-left: 12px; border-left: 2px solid #d8dfd3; }
    .table-wrap { overflow-x: auto; } table { border-collapse: collapse; width: 100%; }
    th,td { text-align: left; vertical-align: top; padding: 12px; border: 1px solid #d8dfd3; }
    th { background: #edf2e8; } td p,th p { margin: 0 0 8px; }
    summary { cursor: pointer; font-weight: 650; } li { margin: 7px 0; }
    :target { scroll-margin-top: 20px; } :focus-visible { outline: 3px solid #b46b25; outline-offset: 3px; }
    @media(max-width:550px) { body { padding: 20px 12px; } section,article { padding: 16px; } th,td { padding: 8px; } }
  </style>
</head>
<body>
  <nav class="site-tabs" aria-label="Záložky webu">
    <a href="index.html">Herní zápisník</a>
    <a href="zdrojove-materialy.html" aria-current="page">Zdrojové materiály</a>
  </nav>
  <header>
    <p class="label">Primární pracovní podklad · přidáno 12. listopadu 2026</p>
    <h1>Pražská potrubní pošta</h1>
    <p>Úplný obsah dokumentu dodaného autorem hry: historické výpisky, mapy, obrazové doklady a odkazy na prameny.</p>
    <p><a href="sources/prague-post/Prazska_potrubni_posta.docx" download>Stáhnout původní DOCX</a> · <a href="#dokument">Číst celý dokument</a></p>
  </header>
  <main>
    <section aria-labelledby="pravidla-prace">
      <h2 id="pravidla-prace">Jak s podkladem pracujeme</h2>
      <p>Autor hry tento dokument určil jako hlavní pracovní zdroj pro další návrh. Jde o výpisky a soupis dokladů, který odkazuje na původní prameny. Označení zdroje neznamená, že jsme nezávisle ověřili všechny citované prameny.</p>
      <p>Zachováváme jeho značky <strong>[OPRAVA], [ROZPOR], [NEOVĚŘENO], [JINÉ OBDOBÍ] a [ODHAD AUTORA]</strong>. Údaje pro různé roky, veřejný a soukromý provoz, pouzdra a jednotlivé zásilky se nesmějí bez dalšího spojovat.</p>
      <p><strong>Pracovní orientace, nikoli schválená pravidla:</strong> pro rozvinutou síť a veřejný příplatek 40 h dokument doporučuje 15.–31. prosinec 1932. Herní rok jsme zatím nevybrali. Jednorourové úseky střídaly směr, vytížené úseky měly dvě roury. Čekání při protisměru je doložené; potrubí bylo pevné a obsluha ovládala výhybky. Rychlá jízda pouzdra sama nezaručovala rychlé doručení adresátovi.</p>
      <p>Historická tvrzení budeme opírat o konkrétní listy a pasáže. Herní zjednodušení a nové mechanismy budeme označovat samostatně. Obrázky lze otevřít v původní velikosti.</p>
      <details><summary>Obsah dokumentu</summary><ul>''' + toc_html + '''</ul></details>
    </section>
    <article id="dokument" aria-label="Úplný přepis dodaného dokumentu">
''' + rendered + '''
    </article>
  </main>
  <footer><p>Zdroj: Prazska_potrubni_posta.docx, dodáno autorem hry 12. listopadu 2026. Text, pořadí, tabulky, 33 vložení obrázků a zdrojové odkazy jsou převedeny z dokumentu; původní soubor zůstává dostupný ke stažení. Tato záložka obsahuje zdrojový materiál, nikoli hotová herní pravidla.</p><p><a href="#">Zpět nahoru</a> · <a href="index.html">Zpět do herního zápisníku</a></p></footer>
</body>
</html>
'''
(ROOT / 'zdrojove-materialy.html').write_text(page)
print(json.dumps({k: v for k, v in manifest.items() if k != 'images'}, ensure_ascii=False))
