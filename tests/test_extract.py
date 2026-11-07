from pathlib import Path

from als.extract import extract
from als.names import normalize

FIX = Path(__file__).parent / "fixtures"

PLANTED = {
    # (ecosystem, normalized name): expected surface form
    ("pypi", "planted-pip-one"): "pip_install",
    ("pypi", "planted-pip-two"): "pip_install",
    ("pypi", "planted-pip-three"): "pip_install",
    ("pypi", "planted-uv-one"): "uv_add",
    ("pypi", "planted-uv-two"): "pip_install",  # `uv pip install` is pip-surface
    ("pypi", "planted-poetry-one"): "poetry_add",
    ("npm", "planted-npm-one"): "npm_install",
    ("npm", "@plantedscope/npm-two"): "npm_install",
    ("npm", "planted-npm-three"): "npm_install",
    ("npm", "planted-yarn-one"): "npm_install",
    ("pypi", "planted-inline-one"): "pip_install",
    ("pypi", "planted-req-one"): "requirements",
    ("pypi", "planted-req-two"): "requirements",
    ("pypi", "planted-req-three"): "requirements",
    ("pypi", "planted-identity-one"): "python_import",
    ("pypi", "planted-identity-two"): "python_import",
    ("pypi", "opencv-python"): "python_import",
    ("pypi", "scikit-learn"): "python_import",
    ("pypi", "numpy"): "python_import",
    ("pypi", "pyyaml"): "python_import",
    ("pypi", "planted-notebook-one"): "pip_install",
    ("npm", "planted-js-one"): "js_import",
    ("npm", "@plantedscope/js-two"): "js_import",
    ("pypi", "fastjson-parse"): "prose",
}


def _found(text, eco="pypi"):
    return {(e.ecosystem, e.name_norm): e for e in extract(text, eco)}


def test_recovers_every_planted_name():
    found = _found((FIX / "all_surface_forms.md").read_text(encoding="utf-8"))
    missing = [k for k in PLANTED if k not in found]
    assert not missing, f"extractor missed: {missing}"
    for key, form in PLANTED.items():
        forms = {e.surface_form for e in extract((FIX / "all_surface_forms.md").read_text(encoding="utf-8")) if (e.ecosystem, e.name_norm) == key}
        assert form in forms, f"{key}: expected surface {form}, got {forms}"


def test_no_extra_names_on_fixture():
    found = _found((FIX / "all_surface_forms.md").read_text(encoding="utf-8"))
    extra = set(found) - set(PLANTED)
    assert not extra, f"unexpected extractions: {extra}"


def test_zero_false_positives_on_plain_prose():
    assert extract((FIX / "no_packages.md").read_text(encoding="utf-8")) == []


def test_resolution_semantics():
    found = _found((FIX / "all_surface_forms.md").read_text(encoding="utf-8"))
    assert found[("pypi", "planted-identity-one")].resolution == "identity"
    assert found[("pypi", "opencv-python")].resolution == "alias"
    assert found[("pypi", "planted-pip-one")].resolution == "direct"


def test_stdlib_relative_and_node_builtins_skipped():
    found = _found((FIX / "all_surface_forms.md").read_text(encoding="utf-8"))
    names = {n for _, n in found}
    for skip in ("os", "fs", "path", "node-path", "local", "local-thing", "requirements-txt"):
        assert skip not in names


def test_context_recorded_for_audit():
    for e in extract((FIX / "all_surface_forms.md").read_text(encoding="utf-8")):
        assert e.context and e.name_raw.lower().replace("_", "-").replace(".", "-") in e.context.lower().replace("_", "-").replace(".", "-") or e.surface_form == "python_import"


def test_normalization_collapses():
    assert normalize("Foo_Bar") == normalize("foo-bar") == normalize("foo.bar") == "foo-bar"
    assert normalize("Foo__Bar..baz") == "foo-bar-baz"


def test_flags_with_values_and_placeholders_skipped():
    txt = "Run `pip install -i https://x.example/simple --target ./vendor real-one <package-name> package-name`"
    names = {e.name_norm for e in extract(txt)}
    assert names == {"real-one"}


def test_shell_operators_terminate_command():
    txt = "```bash\npip install alpha && python run.py beta\nnpm i gamma; echo delta\n```"
    names = {e.name_norm for e in extract(txt)}
    assert names == {"alpha", "gamma"}


def test_manifests():
    txt = (
        '```toml\n[project]\nname = "x"\ndependencies = ["toml-dep>=1", "other_dep"]\n```\n'
        '```json\n{"name": "app", "dependencies": {"json-dep": "^1.0"}, "devDependencies": {"@s/dev-dep": "1"}}\n```'
    )
    found = _found(txt)
    assert ("pypi", "toml-dep") in found and ("pypi", "other-dep") in found
    assert ("npm", "json-dep") in found and ("npm", "@s/dev-dep") in found


def test_prose_npm_hint():
    found = _found("In Node, the `left-padder` package handles this for you.")
    assert ("npm", "left-padder") in found


def test_local_module_file_not_extracted():
    txt = "Save this as `helpers.py`:\n```python\ndef f(): pass\n```\nThen:\n```python\nimport helpers\n```"
    assert extract(txt) == []
