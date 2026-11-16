"""Assemble stage.py, in the repo's root, from its parts.

The main screen is one Streamlit component. Its Python head, HTML, CSS and JavaScript are kept apart here so
each can be edited and the JavaScript can be syntax-checked; `python tools/stage/build.py` puts them together.
Edit these files, never stage.py itself: it is written over on every build.
"""
import os
import subprocess
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(os.path.dirname(here))


def part(name: str) -> str:
    with open(os.path.join(here, name), encoding="utf-8") as handle:
        return handle.read()


js = part("stage.js").replace("/*__WHEELTEX__*/", part("wheeltex.js").rstrip()).replace("/*__BODIES__*/", part("bodies.js").rstrip())
with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as check:
    check.write(js)
try:
    result = subprocess.run(["node", "--check", check.name], capture_output=True, text=True)
except FileNotFoundError:                                  # no Node here: build without the syntax check
    result = None
    print("node was not found, so the JavaScript was not syntax-checked")
finally:
    os.unlink(check.name)
if result is not None and result.returncode:
    print(result.stderr[:1500])
    sys.exit(1)
html, css = part("stage.html"), part("stage.css")
for name, body in (("html", html), ("css", css), ("js", js)):
    assert '"""' not in body, name
out = (part("head.py") + 'HTML = r"""\n' + html.strip() + '\n"""\n\nCSS = r"""\n' + css.strip()
       + '\n"""\n\nJS = r"""\n' + js.strip() + '\n"""\n')
target = os.path.join(root, "stage.py")
with open(target, "w", encoding="utf-8") as handle:
    handle.write(out)
subprocess.run([sys.executable, "-m", "py_compile", target], check=True)
print("stage.py written:", len(out), "chars")
