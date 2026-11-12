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
manifest_path = ASSETS / 'manifest.json'
previous_images = set()
if manifest_path.exists():
    previous_images = {item['path'] for item in json.loads(manifest_path.read_text()).get('images', [])}

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
    for obsolete in previous_images - {item['path'] for item in images}:
        candidate = ROOT / obsolete
        if candidate.resolve().parent != (ASSETS / 'images').resolve():
            raise ValueError(f'Unexpected managed image path: {obsolete}')
        candidate.unlink(missing_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')

map_html = ''
map_manifest_path = ASSETS / 'mapa' / 'manifest.json'
if map_manifest_path.exists():
    map_manifest = json.loads(map_manifest_path.read_text())
    pdf_url = escape(map_manifest['source'], quote=True)
    figures = []
    for entry in map_manifest['pages']:
        number = int(entry['number'])
        title = escape(entry['title'])
        preview = escape(entry['image'], quote=True)
        transcript = escape((ROOT / entry['text']).read_text())
        figures.append(f'''<figure id="mapa-strana-{number}">
          <figcaption><h3>Strana {number}: {title}</h3></figcaption>
          <a href="{preview}" target="_blank" rel="noopener"><img src="{preview}" alt="Strana {number}: {title}. Úplné PDF a textový přepis jsou dostupné v této sekci." loading="lazy" decoding="async"></a>
          <p><a href="{pdf_url}#page={number}" target="_blank" rel="noopener">Otevřít stranu {number} v PDF</a> · <a href="{preview}" target="_blank" rel="noopener">Zvětšit náhled</a></p>
          <details><summary>Textový přepis strany {number}</summary><pre class="map-transcript">{transcript}</pre></details>
        </figure>''')
    map_links = []
    seen = set()
    for link in map_manifest.get('links', []):
        if link['url'] not in seen and urlsplit(link['url']).scheme.lower() in {'https', 'http'}:
            seen.add(link['url'])
            map_links.append(f'<li><a href="{escape(link["url"], quote=True)}">{escape(link["label"])}</a> (strana {int(link["page"])})</li>')
    map_html = f'''<section id="mapa-podklad" aria-labelledby="mapa-nadpis">
      <p class="label">Doplňkový mapový podklad · dodáno 12. listopadu 2026</p>
      <h2 id="mapa-nadpis">Mapa pražské potrubní pošty 1932–1939</h2>
      <p>Uživatelem dodaná třístránková pramenná rekonstrukce z 12. listopadu 2026. Doplňuje hlavní dokument; nenahrazuje jej a není schválenou herní deskou. Jednotlivé mapové prvky vycházejí z různých dobových podkladů a pozdějších dokladů.</p>
      <p><a href="{pdf_url}" download>Stáhnout původní mapu v PDF</a> · <a href="{pdf_url}" target="_blank" rel="noopener">Otevřít celé PDF</a></p>
      <ul>
        <li><strong>Míra doložení:</strong> tmavé barvy odlišují počet rour výslovně doložený Schmidtem, světlejší barvy odečet z kresby. Šedé přerušované vedení může být plán, rozpor nebo neověřený stav. Zelená 86 je doložena v roce 1936.</li>
        <li><strong>Topologie:</strong> společný uliční koridor ani křížení čar samo neprokazuje společnou výhybku. Průběh tras je schematický; mapa není inventurou k jednomu dni.</li>
        <li><strong>Jedna versus dvě roury:</strong> jedna střídá směry a blokuje protější vysílač; dvě umožňují souběh směrů. Výslovné technické doklady se nesmějí zaměňovat za odhad celé větve.</li>
        <li><strong>Dvě číselné řady:</strong> hlavní mapa používá čísla dobových pošt. Na straně 3 čísla 1–15 označují soukromé účastníky ze Šmídova seznamu. Zde přerušovaná čára znamená soukromou přípojku, nikoli automaticky neověřený spoj nebo počet rour.</li>
        <li><strong>Otevřené otázky:</strong> například konce 59/60 na Smíchově, část holešovických větví, 11–51, přesné zapojení některých účastníků a vztah přípojky Šekového úřadu k vnitřním rozvodům.</li>
      </ul>
      <p>Náhledy lze otevřít ve větší velikosti. Originální PDF zachovává vlastní kresbu, legendy a odkazy.</p>
      {''.join(figures)}
      <details><summary>Zdrojové odkazy obsažené v mapovém PDF</summary><ul>{''.join(map_links)}</ul></details>
    </section>'''

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
    #mapa-podklad figure { margin: 24px 0; }
    #mapa-podklad img { display: block; max-width: 100%; height: auto; border: 1px solid #d8dfd3; }
    .map-transcript { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; padding: 12px; background: #f1f4ed; }
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
    <p><a href="sources/prague-post/Prazska_potrubni_posta.docx" download>Stáhnout původní DOCX</a> · <a href="#mapa-podklad">Mapa sítě v PDF</a> · <a href="#dokument">Číst celý dokument</a></p>
  </header>
  <main>
    <section aria-labelledby="pravidla-prace">
      <h2 id="pravidla-prace">Jak s podkladem pracujeme</h2>
      <p>Autor hry tento dokument určil jako hlavní pracovní zdroj pro další návrh. Jde o výpisky a soupis dokladů, který odkazuje na původní prameny. Označení zdroje neznamená, že jsme nezávisle ověřili všechny citované prameny.</p>
      <p>Zachováváme jeho značky <strong>[OPRAVA], [ROZPOR], [NEOVĚŘENO], [JINÉ OBDOBÍ] a [ODHAD AUTORA]</strong>. Údaje pro různé roky, veřejný a soukromý provoz, pouzdra a jednotlivé zásilky se nesmějí bez dalšího spojovat.</p>
      <p><strong>Správná verze podkladu:</strong> autor 12. listopadu 2026 nahradil původně zaslaný soubor tímto dokumentem. Závěrečná kapitola nyní pokrývá provoz od 15. prosince 1932 do 31. května 1939 a jako dobře doložené jednotné zasazení navrhuje rok 1937. Starší doporučení omezit zasazení na konec prosince 1932 už nepoužíváme jako aktuální orientaci. Herní rok jsme zatím nevybrali.</p>
      <p><strong>Pracovní orientace, nikoli schválená pravidla:</strong> jednorourové úseky střídaly směr, vytížené úseky měly dvě roury. Čekání při protisměru je doložené; potrubí bylo pevné a obsluha ovládala výhybky. Rychlá jízda pouzdra sama nezaručovala rychlé doručení adresátovi. Od 1. března 1937 se mění příplatek za místního posla, nikoli samotný 40haléřový potrubní příplatek.</p>
      <p>Historická tvrzení budeme opírat o konkrétní listy a pasáže. Herní zjednodušení a nové mechanismy budeme označovat samostatně. Obrázky lze otevřít v původní velikosti.</p>
      <details><summary>Obsah dokumentu</summary><ul>''' + toc_html + '''</ul></details>
    </section>
''' + map_html + '''
    <article id="dokument" aria-label="Úplný přepis dodaného dokumentu">
''' + rendered + '''
    </article>
  </main>
  <footer><p>Zdroj: Prazska_potrubni_posta.docx, opravená verze dodaná autorem hry 12. listopadu 2026. Text, pořadí, tabulky, ''' + str(len(images)) + ''' vložení obrázků a zdrojové odkazy jsou převedeny z aktuálního dokumentu; jeho originál zůstává dostupný ke stažení. Tato záložka obsahuje zdrojový materiál, nikoli hotová herní pravidla.</p><p><a href="#">Zpět nahoru</a> · <a href="index.html">Zpět do herního zápisníku</a></p></footer>
</body>
</html>
'''
(ROOT / 'zdrojove-materialy.html').write_text(page)
print(json.dumps({k: v for k, v in manifest.items() if k != 'images'}, ensure_ascii=False))
