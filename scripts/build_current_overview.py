"""Keep the lightweight homepage in sync with the current gameplay overview."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
html = (root / 'aktualni-hra.html').read_text()
# Old links addressed notebook sections at the root. Keep those links useful.
forward = '''<script>
function openNotebookSection() {
  const section = location.hash.slice(1);
  if (section && !document.getElementById(section)) {
    location.replace('zapisnik.html' + location.hash);
  }
}
addEventListener('hashchange', openNotebookSection);
openNotebookSection();
</script>'''
(root / 'index.html').write_text(html.replace('</body>', forward + '\n</body>'))
