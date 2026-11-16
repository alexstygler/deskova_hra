"""Create smaller inline previews; preserve all historical source assets unchanged.

Requires Pillow. Run before build_primary_source.py after replacing source assets.
"""
from pathlib import Path
from PIL import Image, ImageOps
import hashlib
import json
root = Path(__file__).resolve().parents[1]
assets = root / 'sources/prague-post'
out = assets / 'previews'
out.mkdir(exist_ok=True)
entries = {}
for source in sorted([*assets.glob('images/*'), *assets.glob('mapa/*.png')]):
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert('RGB')
        image.thumbnail((1200, 1800), Image.Resampling.LANCZOS)
        target = out / (source.stem + '.webp')
        image.save(target, 'WEBP', quality=85, method=6)
        entries[source.relative_to(root).as_posix()] = {
            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'preview': target.relative_to(root).as_posix(),
            'width': image.width, 'height': image.height,
        }
(assets / 'preview-manifest.json').write_text(json.dumps(entries, ensure_ascii=False, indent=2) + '\n')
print(f'Created {len(entries)} previews: {sum(p.stat().st_size for p in out.glob("*.webp")):,} bytes')
