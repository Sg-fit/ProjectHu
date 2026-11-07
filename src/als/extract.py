"""Raw model text -> candidate package references.

This is the module most likely to silently wreck the numbers, so it is
conservative on purpose and records *why* each name was extracted
(``surface_form``) plus the surrounding ``context`` for hand auditing.

Resolution semantics (what a name means for metrics):
  direct   - the text names a distribution (install command, requirements,
             manifest, prose "the `x` library", JS import specifier)
  alias    - Python import mapped to a distribution via names.IMPORT_ALIASES
  identity - Python import NOT in the alias table; distribution name assumed to
             equal the import name. Never counted as hallucinated on its own:
             a missing identity-import is bucketed `unresolved`.
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import asdict, dataclass

from .names import (
    NODE_BUILTINS,
    PY_STDLIB,
    import_to_distribution,
    normalize,
    npm_package_from_specifier,
)


@dataclass(frozen=True)
class Extraction:
    ecosystem: str
    name_raw: str
    name_norm: str
    surface_form: str
    resolution: str
    context: str

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- helpers

_FENCE = re.compile(r"^[ \t]*(```|~~~)[ \t]*([^\n`]*)\n(.*?)(?:^[ \t]*\1[ \t]*$|\Z)", re.M | re.S)
_PYPI_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
_NPM_NAME = re.compile(r"^(?:@[a-z0-9][\w.-]*/)?[a-z0-9][\w.-]*", re.I)

PLACEHOLDERS = frozenset(
    {
        "package", "packages", "package-name", "package_name", "packagename", "pkg",
        "your-package", "your_package", "yourpackage", "library", "library-name",
        "module", "module-name", "name", "foo", "bar", "baz", "example", "xyz",
        "something", "dependency", "dependencies", "deps", "lib", "libname",
    }
)

PY_LANGS = {"python", "py", "python3", "ipython", "pycon", "jupyter"}
JS_LANGS = {"js", "javascript", "jsx", "ts", "typescript", "tsx", "mjs", "cjs", "node"}
SHELL_LANGS = {"bash", "sh", "shell", "zsh", "console", "terminal", "cmd", "powershell", "ps", "bat", "dockerfile", ""}
REQ_LANGS = {"requirements", "requirements.txt", "pip-requirements", "pip"}


def _ctx(text: str, start: int, end: int, width: int = 80) -> str:
    a, b = max(0, start - width), min(len(text), end + width)
    return text[a:b].replace("\n", "\\n")


@dataclass
class _Block:
    lang: str
    body: str
    start: int  # offset of body in full text
    preamble: str  # up to 200 chars of text before the fence


def _split_blocks(text: str) -> tuple[list[_Block], str]:
    """Return fenced blocks and the prose with blocks blanked out (offsets preserved)."""
    blocks: list[_Block] = []
    prose = list(text)
    for m in _FENCE.finditer(text):
        info = m.group(2).strip().lower()
        lang = info.split()[0] if info else ""
        lang = lang.lstrip("{.").rstrip("}")
        blocks.append(_Block(lang, m.group(3), m.start(3), text[max(0, m.start() - 200) : m.start()]))
        for i in range(m.start(), m.end()):
            if prose[i] != "\n":
                prose[i] = " "
    return blocks, "".join(prose)


# ------------------------------------------------------- install commands

# Leading context allowed before a command: start, whitespace, backtick, prompt chars, shell operators.
_INSTALL = re.compile(
    r"(?:^|(?<=[\s`$;&|(!%>]))"
    r"(?P<tool>python3?(?:\.\d+)?\s+-m\s+pip|py(?:\s+-3(?:\.\d+)?)?\s+-m\s+pip|pip3?(?:\.\d+)?|uv\s+pip|uv|poetry|pipx|pipenv|pdm|rye|conda|mamba|npm|yarn|pnpm|bun|npx)"
    r"\s+(?P<verb>install|add|i)\b(?P<rest>[^\n`]*)",
    re.I | re.M,
)
_TERMINATORS = re.compile(r"\s(?:&&|\|\||;|\||#)\s?|[;)]|\s+2?>")

_PIP_VALUE_FLAGS = {
    "-r", "--requirement", "-c", "--constraint", "-e", "--editable", "-i", "--index-url",
    "--extra-index-url", "-f", "--find-links", "-t", "--target", "--prefix", "--root",
    "--trusted-host", "--platform", "--python-version", "--implementation", "--abi",
    "--src", "--log", "--proxy", "--cert", "--client-cert", "--cache-dir", "--python",
    "-p", "--group", "--source", "--channel", "--index", "--default-index", "--only-binary",
    "--no-binary", "--progress-bar", "--report", "--config-settings", "-C", "--retries", "--timeout",
}
_NPM_VALUE_FLAGS = {"--registry", "--prefix", "--tag", "--cache", "--userconfig", "-w", "--workspace", "--filter"}

_PY_TOOLS_ECOSYSTEM = "pypi"


def _tool_ecosystem(tool: str) -> str | None:
    t = tool.lower()
    if t in {"npm", "yarn", "pnpm", "bun", "npx"}:
        return "npm"
    if t.startswith("conda") or t.startswith("mamba"):
        return None  # conda channels are not PyPI; out of scope
    return "pypi"


def _surface(tool: str) -> str:
    t = tool.lower().split()[0]
    if "pip" in tool.lower():  # pip, pip3, python -m pip, uv pip, pipx, pipenv
        return "pip_install"
    return {
        "uv": "uv_add", "poetry": "poetry_add", "pipx": "pip_install", "pipenv": "pip_install",
        "pdm": "uv_add", "rye": "uv_add", "npm": "npm_install", "yarn": "npm_install",
        "pnpm": "npm_install", "bun": "npm_install",
    }.get(t, "pip_install")


def _clean_pypi_token(tok: str) -> str | None:
    tok = tok.strip().strip("'\"")
    if not tok or tok.startswith(("-", ".", "/", "~", "<", "$", "{", "[")):
        return None
    low = tok.lower()
    if "://" in tok or low.startswith(("git+", "hg+", "svn+", "bzr+", "file:")) or low.endswith((".whl", ".tar.gz", ".zip", ".txt")):
        return None
    if "/" in tok or "\\" in tok or "@" in tok and " @ " not in tok and not tok.split("@")[0]:
        return None
    tok = tok.split("@")[0]  # PEP 508 direct ref: name @ url
    m = _PYPI_NAME.match(tok)
    if not m:
        return None
    name = m.group(0)
    if name.lower() in PLACEHOLDERS:
        return None
    return name


def _clean_npm_token(tok: str) -> str | None:
    tok = tok.strip().strip("'\"")
    if not tok or tok.startswith(("-", ".", "/", "~", "<", "$", "{")) or "://" in tok:
        return None
    if tok.startswith(("git+", "github:", "file:", "link:", "workspace:", "npm:")):
        return None
    # strip version: @scope/name@1.2 or name@^1
    if tok.startswith("@"):
        head, _, rest = tok[1:].partition("@")
        tok = "@" + head
    else:
        tok = tok.split("@")[0]
    m = _NPM_NAME.match(tok)
    if not m or m.group(0) != tok:
        return None
    if tok.lower() in PLACEHOLDERS or tok in NODE_BUILTINS:
        return None
    return tok


def _install_commands(text: str) -> list[Extraction]:
    out: list[Extraction] = []
    for m in _INSTALL.finditer(text):
        tool = re.sub(r"\s+", " ", m.group("tool"))
        eco = _tool_ecosystem(tool)
        if eco is None:
            continue
        verb = m.group("verb").lower()
        tl = tool.lower()
        # `uv add`, `poetry add`, `npm i`, `yarn add`... reject verb/tool mismatches like `pip add`
        if verb == "add" and ("pip" in tl and not tl.startswith("uv")):
            continue
        if verb == "i" and eco != "npm":
            continue
        rest = _TERMINATORS.split(m.group("rest"), maxsplit=1)[0]
        try:
            tokens = shlex.split(rest, posix=True)
        except ValueError:
            tokens = rest.split()
        skip_next = False
        value_flags = _NPM_VALUE_FLAGS if eco == "npm" else _PIP_VALUE_FLAGS
        for tok in tokens:
            if skip_next:
                skip_next = False
                continue
            if tok.startswith("-"):
                if "=" not in tok and tok in value_flags:
                    skip_next = True
                continue
            name = _clean_npm_token(tok) if eco == "npm" else _clean_pypi_token(tok)
            if name:
                out.append(
                    Extraction(eco, name, normalize(name, eco), _surface(tool), "direct", _ctx(text, m.start(), m.end()))
                )
    return out


# ------------------------------------------------------ requirements / manifests

_REQ_LINE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(?:\[[^\]]*\])?\s*"
    r"(?:(?:===|==|>=|<=|~=|!=|>|<)\s*[\w.*+!-]+\s*,?\s*)*(?:;.*)?(?:#.*)?$"
)


def _requirements_block(block: _Block, full: str) -> list[Extraction]:
    lines = [ln for ln in block.body.splitlines()]
    content = [ln for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    if not content:
        return []
    first_comment = next((ln for ln in lines if ln.strip()), "")
    labeled = (
        block.lang in REQ_LANGS
        or "requirements" in block.preamble[-120:].lower()
        or ("requirements" in first_comment.lower() and first_comment.strip().startswith("#"))
    )
    if not labeled and block.lang not in {"", "txt", "text", "plain", "plaintext", "ini", "cfg"}:
        return []
    if not labeled:
        return []
    out = []
    for ln in content:
        s = ln.strip()
        if s.startswith(("-", "git+", "http", ".", "/")):
            continue
        m = _REQ_LINE.match(s)
        if not m:
            return []  # not actually a requirements file; bail rather than guess
        name = m.group("name")
        if name.lower() in PLACEHOLDERS:
            continue
        off = block.start + block.body.find(ln)
        out.append(Extraction("pypi", name, normalize(name), "requirements", "direct", _ctx(full, off, off + len(ln))))
    return out


_TOML_DEPS = re.compile(r"(?ms)^\s*(?:dependencies|requires|dev-dependencies)\s*=\s*\[(.*?)\]")
_TOML_STR = re.compile(r"[\"']([^\"']+)[\"']")
_POETRY_SECTION = re.compile(r"(?ms)^\[tool\.poetry\.(?:dev-)?dependencies\]\s*\n(.*?)(?=^\[|\Z)")


def _toml_block(block: _Block, full: str) -> list[Extraction]:
    out = []
    for m in _TOML_DEPS.finditer(block.body):
        for s in _TOML_STR.finditer(m.group(1)):
            name = _clean_pypi_token(s.group(1).split(";")[0].replace(" ", ""))
            if name and name.lower() not in {"setuptools", "wheel"} | PLACEHOLDERS:
                off = block.start + m.start()
                out.append(Extraction("pypi", name, normalize(name), "manifest", "direct", _ctx(full, off, off + 60)))
    for m in _POETRY_SECTION.finditer(block.body):
        for ln in m.group(1).splitlines():
            k = ln.split("=")[0].strip().strip("\"'")
            if k and k.lower() != "python" and _PYPI_NAME.fullmatch(k):
                off = block.start + m.start()
                out.append(Extraction("pypi", k, normalize(k), "manifest", "direct", _ctx(full, off, off + 60)))
    return out


def _package_json_block(block: _Block, full: str) -> list[Extraction]:
    try:
        data = json.loads(block.body)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    out = []
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        deps = data.get(key)
        if isinstance(deps, dict):
            for name in deps:
                n = _clean_npm_token(name)
                if n:
                    out.append(Extraction("npm", n, normalize(n, "npm"), "manifest", "direct", _ctx(full, block.start, block.start + 60)))
    return out


# --------------------------------------------------------------- imports

_PY_IMPORT = re.compile(r"^[ \t]*import[ \t]+([^\n#;]+)", re.M)
_PY_FROM = re.compile(r"^[ \t]*from[ \t]+([A-Za-z_][\w.]*)[ \t]+import\b", re.M)
_LOCAL_FILE = re.compile(r"\b([A-Za-z_]\w*)\.py\b")


def _looks_python(body: str) -> bool:
    return bool(re.search(r"^\s*(?:def |class |import |from \w[\w.]* import |print\()", body, re.M))


def _python_imports(block: _Block, full: str, local_modules: set[str]) -> list[Extraction]:
    mods: list[tuple[str, int]] = []
    for m in _PY_IMPORT.finditer(block.body):
        for part in m.group(1).split(","):
            mod = part.strip().split(" as ")[0].strip().strip("()")
            if re.fullmatch(r"[A-Za-z_][\w.]*", mod):
                mods.append((mod, m.start()))
    for m in _PY_FROM.finditer(block.body):
        mods.append((m.group(1), m.start()))
    out = []
    for mod, pos in mods:
        if mod.split(".")[0] in local_modules:
            continue
        dist, resolution = import_to_distribution(mod)
        if dist is None:
            continue
        off = block.start + pos
        out.append(Extraction("pypi", dist, normalize(dist), "python_import", resolution, _ctx(full, off, off + len(mod) + 12)))
    return out


_JS_SPECS = [
    re.compile(r"""\brequire\(\s*['"]([^'"\n]+)['"]\s*\)"""),
    re.compile(r"""^\s*import\s[^'"\n]*?\bfrom\s+['"]([^'"\n]+)['"]""", re.M),
    re.compile(r"""^\s*import\s+['"]([^'"\n]+)['"]""", re.M),
    re.compile(r"""\bimport\(\s*['"]([^'"\n]+)['"]\s*\)"""),
    re.compile(r"""^\s*export\s[^'"\n]*?\bfrom\s+['"]([^'"\n]+)['"]""", re.M),
]


def _js_imports(block: _Block, full: str) -> list[Extraction]:
    out = []
    for rx in _JS_SPECS:
        for m in rx.finditer(block.body):
            pkg = npm_package_from_specifier(m.group(1))
            if pkg and _clean_npm_token(pkg):
                off = block.start + m.start()
                out.append(Extraction("npm", pkg, normalize(pkg, "npm"), "js_import", "direct", _ctx(full, off, off + 60)))
    return out


# ------------------------------------------------------------------ prose

_PROSE_TICK = re.compile(r"`([^`\s]{2,60})`|\*\*([A-Za-z0-9][\w.-]{1,60})\*\*")
_PKG_WORDS = re.compile(r"\b(librar(?:y|ies)|packages?|modules?|dependenc(?:y|ies)|lib|SDK|wrapper|toolkit|framework)\b", re.I)
_NPM_HINT = re.compile(r"\b(npm|node(?:\.js)?|javascript|typescript|yarn|pnpm|js)\b", re.I)
_PY_HINT = re.compile(r"\b(pip|pypi|python)\b", re.I)


def _prose(prose: str, default_ecosystem: str) -> list[Extraction]:
    out = []
    for m in _PROSE_TICK.finditer(prose):
        tok = m.group(1) or m.group(2)
        # sentence-ish window around the token
        a = max(prose.rfind(".", 0, m.start()), prose.rfind("\n", 0, m.start()), m.start() - 80)
        b_candidates = [i for i in (prose.find(". ", m.end()), prose.find("\n", m.end())) if i != -1]
        b = min(b_candidates + [m.end() + 80])
        window = prose[a + 1 : b]
        if not _PKG_WORDS.search(window):
            continue
        # the package word must be adjacent-ish: within 40 chars of the token
        near = prose[max(0, m.start() - 40) : m.end() + 40]
        if not _PKG_WORDS.search(near):
            continue
        eco = default_ecosystem
        if _NPM_HINT.search(window) and not _PY_HINT.search(window):
            eco = "npm"
        elif _PY_HINT.search(window):
            eco = "pypi"
        if eco == "npm":
            name = _clean_npm_token(tok)
        else:
            name = _clean_pypi_token(tok) if _PYPI_NAME.fullmatch(tok) else None
        if not name or "." in name:
            continue
        low = name.lower()
        if eco == "pypi" and (name in PY_STDLIB or low in PY_STDLIB):
            continue
        if low in _PROSE_STOP:
            continue
        out.append(Extraction(eco, name, normalize(name, eco), "prose", "direct", _ctx(prose, m.start(), m.end())))
    return out


_PROSE_STOP = frozenset(
    "true false none null python pip npm node javascript typescript json yaml http https api cli "
    "async await import from install requirements main init self class def return error utils "
    "config settings app server client test tests src lib index".split()
)


# ------------------------------------------------------------------- main


def extract(text: str, default_ecosystem: str = "pypi") -> list[Extraction]:
    """Extract every candidate package reference from model output.

    Deduplicates on (ecosystem, name_norm, surface_form) - the first occurrence's
    context is kept.
    """
    blocks, prose = _split_blocks(text)
    local_modules = set(_LOCAL_FILE.findall(text))
    found: list[Extraction] = []

    found += _install_commands(text)  # commands appear in code blocks *and* inline prose

    for blk in blocks:
        lang = blk.lang
        if lang in {"toml"} or "[project]" in blk.body or "[tool.poetry" in blk.body:
            found += _toml_block(blk, text)
        elif lang in {"json", "jsonc"} and '"dependencies"' in blk.body or (lang == "" and blk.body.lstrip().startswith("{") and '"dependencies"' in blk.body):
            found += _package_json_block(blk, text)
        found += _requirements_block(blk, text)
        if lang in PY_LANGS or (lang == "" and _looks_python(blk.body)):
            found += _python_imports(blk, text, local_modules)
        elif lang in JS_LANGS:
            found += _js_imports(blk, text)

    found += _prose(prose, default_ecosystem)

    seen: set[tuple[str, str, str]] = set()
    out: list[Extraction] = []
    for e in found:
        key = (e.ecosystem, e.name_norm, e.surface_form)
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out
