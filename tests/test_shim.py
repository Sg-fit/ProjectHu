import io

from als.oracle import Oracle
from als.shim.interpose import (EXIT_BLOCKED, EXIT_NEEDS_APPROVAL, EXIT_OK, Shim, packages_in_command,
                                run_guarded)


def _shim(store, transport, policy):
    return Shim(policy, store, Oracle.from_policy(store, policy, transport=transport))


def test_parse_install_commands(tmp_path):
    assert packages_in_command(["pip", "install", "-U", "requests==2.0", "numpy"]) == ("pypi", ["requests", "numpy"])
    assert packages_in_command(["npm", "i", "left-pad@1.0"]) == ("npm", ["left-pad"])
    assert packages_in_command(["ls", "-la"]) == (None, [])
    req = tmp_path / "r.txt"
    req.write_text("flask>=2\n# comment\nfastjson-parse==1.0\n")
    assert packages_in_command(["pip", "install", "-r", str(req)]) == ("pypi", ["flask", "fastjson-parse"])


def test_block_never_executes(store, transport, policy, monkeypatch):
    ran = []
    monkeypatch.setattr("als.shim.interpose.subprocess.call", lambda argv: ran.append(argv) or 0)
    out = io.StringIO()
    code = run_guarded(["pip", "install", "flask", "fastjson-parse"], _shim(store, transport, policy), out=out)
    assert code == EXIT_BLOCKED and not ran
    msg = out.getvalue()
    assert "BLOCKED" in msg and "fastjson-parse" in msg and "Do NOT retry" in msg


def test_flag_needs_approval_noninteractive(store, transport, policy, monkeypatch):
    ran = []
    monkeypatch.setattr("als.shim.interpose.subprocess.call", lambda argv: ran.append(argv) or 0)
    shim = _shim(store, transport, policy)
    out = io.StringIO()
    assert run_guarded(["pip", "install", "fresh-pkg"], shim, interactive=False, out=out) == EXIT_NEEDS_APPROVAL
    assert not ran and "ALS_SHIM_APPROVE=fresh-pkg" in out.getvalue()
    monkeypatch.setenv("ALS_SHIM_APPROVE", "fresh-pkg")
    assert run_guarded(["pip", "install", "fresh-pkg"], shim, interactive=False, out=io.StringIO()) == EXIT_OK
    assert ran


def test_allow_passes_through(store, transport, policy, monkeypatch):
    ran = []
    monkeypatch.setattr("als.shim.interpose.subprocess.call", lambda argv: ran.append(argv) or 0)
    assert run_guarded(["pip", "install", "requests"], _shim(store, transport, policy), out=io.StringIO()) == EXIT_OK
    assert ran == [["pip", "install", "requests"]]


def test_non_install_command_passthrough(store, transport, policy, monkeypatch):
    ran = []
    monkeypatch.setattr("als.shim.interpose.subprocess.call", lambda argv: ran.append(argv) or 0)
    assert run_guarded(["python", "app.py"], _shim(store, transport, policy), out=io.StringIO()) == EXIT_OK
    assert ran and not transport.calls
