#!/usr/bin/env python3
"""Regression tests for oran-dhcp-gen.

Run directly (no dependencies beyond python3-yaml, which the generator needs
anyway) or under pytest:

    python3 tests/run_tests.py
    pytest -q tests/

What matters most here is `test_isc_and_kea_agree_on_suboption_codes` and
`test_kea_vendor_options_are_typed_not_blob`.  Versions 2.2.0 through 2.2.2
shipped Kea configs whose option-43/17 payload was a pre-built binary blob
nested under sub-option code 1; Kea then wrapped it in that sub-option's own
TLV header, so O-RUs walking the top-level sub-options hit an unknown code,
skipped it, and never learned the controller address.  DHCP still worked, the
lease was fine, and `kea-dhcp4 -t` validated cleanly -- which is exactly why it
survived three releases.  Those two tests compare the emitted ISC and Kea files
against each other, so a repeat of that defect fails here instead of in a lab.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)
GEN = os.path.join(REPO_ROOT, "bin", "oran-dhcp-gen")
GOLDEN_DIR = os.path.join(TESTS_DIR, "golden")

INPUTS = {
    "lab4": os.path.join(REPO_ROOT, "References", "kea", "Lab4", "oran_dhcp.yaml"),
    "example": os.path.join(REPO_ROOT, "examples", "oran_dhcp.yaml.example"),
}
OUTPUT_FILES = ("dhcpd.conf", "dhcpd6.conf", "isc-dhcp-server",
                "kea-dhcp4.conf", "kea-dhcp6.conf")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def generate(yaml_path, outdir, *extra):
    """Run the generator; return CompletedProcess."""
    return subprocess.run(
        [sys.executable, GEN, yaml_path, "--target", "all",
         "--outdir", outdir, *extra],
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=120,
    )


def generate_ok(yaml_path, outdir, *extra):
    proc = generate(yaml_path, outdir, *extra)
    assert proc.returncode == 0, (
        "generator failed for %s:\n%s" % (yaml_path, proc.stdout.decode()))
    return proc


def isc_class_blocks(text):
    """{class name: block body} for every `class "NAME" { ... }` in ISC output."""
    return {m.group(1): m.group(2)
            for m in re.finditer(r'class\s+"([^"]+)"\s*\{(.*?)\n\}', text, re.S)}


def _hex_to_bytes(chain):
    return bytes(int(b, 16) for b in chain.replace("\n", "")
                 .replace(" ", "").strip().strip(";").split(":") if b)


def isc_v4_suboption_codes(block):
    """Decode `option vendor-encapsulated-options <hex>;` into sub-option codes.

    DHCPv4 vendor sub-options are 1-byte code, 1-byte length, value.  The chain
    may be split across continuation lines, so it is collected up to the `;`.
    """
    m = re.search(r'option\s+vendor-encapsulated-options\s+(.*?);', block, re.S)
    if not m:
        return None
    raw = _hex_to_bytes(m.group(1))
    codes, i = [], 0
    while i + 1 < len(raw):
        code, length = raw[i], raw[i + 1]
        codes.append(code)
        i += 2 + length
    assert i == len(raw), "v4 TLV chain is not self-consistent: %r" % (raw,)
    return codes


def isc_v6_suboption_codes(block):
    """Decode `option dhcp6.vendor-opts <eid> <hex>;` into sub-option codes.

    DHCPv6 vendor sub-options are 2-byte code, 2-byte length, value.
    """
    m = re.search(r'option\s+dhcp6\.vendor-opts\s+\d+\s+(.*?);', block, re.S)
    if not m:
        return None
    raw = _hex_to_bytes(m.group(1))
    codes, i = [], 0
    while i + 3 < len(raw):
        code = (raw[i] << 8) | raw[i + 1]
        length = (raw[i + 2] << 8) | raw[i + 3]
        codes.append(code)
        i += 4 + length
    assert i == len(raw), "v6 TLV chain is not self-consistent: %r" % (raw,)
    return codes


def kea_vendor_codes_by_class(kea_cfg, root_key):
    """{class name: sorted sub-option codes} from Kea per-class option-data."""
    cfg = kea_cfg[root_key]
    name_to_code = {d["name"]: d["code"] for d in cfg.get("option-def", [])}
    vendor_spaces = {d["space"] for d in cfg.get("option-def", [])}
    out = {}
    for cl in cfg.get("client-classes", []):
        codes = []
        for od in cl.get("option-data", []):
            if od.get("space") not in vendor_spaces:
                continue
            code = od.get("code", name_to_code.get(od.get("name")))
            if code is not None:
                codes.append(code)
        out[cl["name"]] = sorted(codes)
    return out


def load_generated(outdir):
    """Read every generated file from outdir into a dict."""
    return {f: open(os.path.join(outdir, f)).read() for f in OUTPUT_FILES}


# ---------------------------------------------------------------------------
# Golden-file regression
# ---------------------------------------------------------------------------

def _check_golden(name):
    tmp = tempfile.mkdtemp(prefix="oran-gen-test-")
    try:
        generate_ok(INPUTS[name], tmp, "--no-timestamp")
        for fname in OUTPUT_FILES:
            got = open(os.path.join(tmp, fname)).read()
            golden_path = os.path.join(GOLDEN_DIR, name, fname)
            assert os.path.exists(golden_path), (
                "missing golden %s -- run tests/update_goldens.sh" % golden_path)
            want = open(golden_path).read()
            assert got == want, (
                "%s/%s differs from its golden file.\n"
                "If the change is intended, run tests/update_goldens.sh and "
                "review the diff before committing." % (name, fname))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_golden_lab4():
    _check_golden("lab4")


def test_golden_example():
    _check_golden("example")


# ---------------------------------------------------------------------------
# Determinism and the --no-timestamp contract
# ---------------------------------------------------------------------------

def test_output_is_deterministic():
    a = tempfile.mkdtemp(prefix="oran-gen-a-")
    b = tempfile.mkdtemp(prefix="oran-gen-b-")
    try:
        generate_ok(INPUTS["example"], a, "--no-timestamp")
        generate_ok(INPUTS["example"], b, "--no-timestamp")
        for fname in OUTPUT_FILES:
            assert open(os.path.join(a, fname)).read() == \
                   open(os.path.join(b, fname)).read(), \
                   "%s differs between two --no-timestamp runs" % fname
    finally:
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)


def test_timestamp_present_by_default_and_omitted_on_request():
    with_ts = tempfile.mkdtemp(prefix="oran-gen-ts-")
    without = tempfile.mkdtemp(prefix="oran-gen-nots-")
    try:
        generate_ok(INPUTS["lab4"], with_ts)
        generate_ok(INPUTS["lab4"], without, "--no-timestamp")
        a = open(os.path.join(with_ts, "dhcpd.conf")).read()
        b = open(os.path.join(without, "dhcpd.conf")).read()
        assert re.search(r"Generated by oran-dhcp-gen v\S+ on \d{4}-\d{2}-\d{2}", a), \
            "default output should carry a generation timestamp"
        assert "Generated by oran-dhcp-gen" in b
        assert " on 20" not in b.split("\n")[1], \
            "--no-timestamp output must not carry a generation time"
    finally:
        shutil.rmtree(with_ts, ignore_errors=True)
        shutil.rmtree(without, ignore_errors=True)


# ---------------------------------------------------------------------------
# Kea structural correctness -- the 2.2.0-2.2.2 regression guards
# ---------------------------------------------------------------------------

def test_kea_configs_are_strict_json():
    for name in INPUTS:
        for fname in ("kea-dhcp4.conf", "kea-dhcp6.conf"):
            path = os.path.join(GOLDEN_DIR, name, fname)
            try:
                json.load(open(path))
            except ValueError as e:
                raise AssertionError("%s/%s is not valid JSON: %s" % (name, fname, e))


def test_kea_vendor_options_are_typed_not_blob():
    """Every vendor-space option-def must carry a real type.

    A `binary` (or absent) type is the shape the 2.2.x defect took: the whole
    payload handed to Kea as one opaque blob for Kea to re-wrap.  Kea must be
    told the type of each sub-option so it builds the TLVs itself.
    """
    for name in INPUTS:
        for fname, root in (("kea-dhcp4.conf", "Dhcp4"), ("kea-dhcp6.conf", "Dhcp6")):
            cfg = json.load(open(os.path.join(GOLDEN_DIR, name, fname)))[root]
            defs = cfg.get("option-def", [])
            assert defs, "%s/%s defines no vendor sub-options" % (name, fname)
            for d in defs:
                assert d.get("type") not in (None, "binary", "empty"), (
                    "%s/%s: option-def %r (code %s) has type %r -- vendor "
                    "sub-options must be typed so Kea encodes the TLV itself, "
                    "never handed over as a pre-built blob"
                    % (name, fname, d.get("name"), d.get("code"), d.get("type")))


def test_isc_and_kea_agree_on_suboption_codes():
    """The two targets must emit the same O-RAN sub-options for every class.

    The generator cross-checks its two internal representations at generation
    time; this checks the artefacts that actually reach a server, which is
    where the 2.2.x defect lived.
    """
    for name in INPUTS:
        g = os.path.join(GOLDEN_DIR, name)
        for isc_file, kea_file, root, decode in (
            ("dhcpd.conf", "kea-dhcp4.conf", "Dhcp4", isc_v4_suboption_codes),
            ("dhcpd6.conf", "kea-dhcp6.conf", "Dhcp6", isc_v6_suboption_codes),
        ):
            isc_blocks = isc_class_blocks(open(os.path.join(g, isc_file)).read())
            kea_codes = kea_vendor_codes_by_class(
                json.load(open(os.path.join(g, kea_file))), root)

            shared = set(isc_blocks) & set(kea_codes)
            assert shared, "%s/%s: no classes in common with %s" % (
                name, isc_file, kea_file)

            for cls in sorted(shared):
                isc = decode(isc_blocks[cls])
                if isc is None:
                    continue        # class carries no vendor options on this family
                assert sorted(isc) == kea_codes[cls], (
                    "%s class %r: ISC emits sub-option codes %s but Kea emits %s "
                    "(%s vs %s)" % (name, cls, sorted(isc), kea_codes[cls],
                                    isc_file, kea_file))


def test_isc_v4_controller_ip_is_top_level_suboption_129():
    """0x81 must be a top-level sub-option, not nested inside another TLV.

    The pre-2.2.3 wire bytes were `01 06 81 04 c0 a8 2c 06`; correct is
    `81 04 c0 a8 2c 06`.  Decoding the chain and finding 129 at the top level
    is precisely the difference.
    """
    for name in INPUTS:
        text = open(os.path.join(GOLDEN_DIR, name, "dhcpd.conf")).read()
        seen = False
        for cls, block in isc_class_blocks(text).items():
            codes = isc_v4_suboption_codes(block)
            if codes is None:
                continue
            seen = True
            assert 129 in codes, (
                "%s class %r: no top-level sub-option 0x81 (controller IP) in %s"
                % (name, cls, codes))
        assert seen, "%s: no class emitted an option-43 chain at all" % name


# ---------------------------------------------------------------------------
# Validation: bad input must fail cleanly, never emit partial output
# ---------------------------------------------------------------------------

def _write_yaml(tmpdir, text):
    path = os.path.join(tmpdir, "bad.yaml")
    open(path, "w").write(text)
    return path


def test_missing_subnets_fails_without_emitting_files():
    tmp = tempfile.mkdtemp(prefix="oran-gen-bad-")
    try:
        bad = _write_yaml(tmp, "global:\n  oran_enterprise_id: 53148\n"
                               "controllers:\n  main:\n    ipv4: 192.168.1.1\n")
        out = os.path.join(tmp, "out")
        os.makedirs(out, exist_ok=True)
        proc = generate(bad, out)
        assert proc.returncode != 0, "missing subnets should fail"
        assert not os.listdir(out), \
            "generator must not leave partial output on a validation failure"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_unparseable_yaml_fails_cleanly():
    tmp = tempfile.mkdtemp(prefix="oran-gen-bad2-")
    try:
        bad = _write_yaml(tmp, "global: [unclosed\n")
        proc = generate(bad, tmp)
        assert proc.returncode != 0, "malformed YAML should fail"
        assert b"Traceback" not in proc.stdout, \
            "malformed YAML should produce a message, not a traceback:\n%s" \
            % proc.stdout.decode()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_missing_input_file_fails_cleanly():
    proc = generate("/nonexistent/oran_dhcp.yaml", tempfile.gettempdir())
    assert proc.returncode != 0
    assert b"Traceback" not in proc.stdout


# ---------------------------------------------------------------------------
# Packaging invariants
# ---------------------------------------------------------------------------

def test_version_matches_changelog():
    src = open(GEN).read()
    version = re.search(r'^__version__ = "([^"]+)"', src, re.M).group(1)
    changelog = open(os.path.join(REPO_ROOT, "packaging", "debian", "changelog")).read()
    top = re.match(r'oran-dhcp-gen \(([^)]+)\)', changelog).group(1)
    assert version == top, (
        "__version__ is %s but the changelog leads with %s -- add a changelog "
        "entry before releasing" % (version, top))


def test_packaging_templates_carry_no_literal_version():
    """control/postinst/man must use @VERSION@, not a hard-coded number.

    The version used to live in five hand-edited places and had drifted: the
    shipped 2.2.3 man page said 2.2.2, and its postinst announced "What's new
    in 2.2.2".  build-deb.sh substitutes from __version__ instead.
    """
    deb = os.path.join(REPO_ROOT, "packaging", "debian")

    # Only lines that state the *package* version are checked. Historical
    # references ("NEW in 2.2.0" in the man page) are legitimate prose.
    checks = [
        ("control", r'^Version:\s*(\S+)', "Version: field"),
        ("postinst", r'oran-dhcp-gen v(\S+?) installed', "install banner"),
        ("postinst", r"What's new in (\S+?):", "what's-new banner"),
        ("oran-dhcp-gen.1", r'^\.TH\s+\S+\s+\d+\s+"[^"]*"\s+"([^"]*)"', ".TH version"),
    ]
    for fname, pattern, what in checks:
        text = open(os.path.join(deb, fname)).read()
        m = re.search(pattern, text, re.M)
        assert m, "packaging/debian/%s: could not find the %s" % (fname, what)
        assert m.group(1) == "@VERSION@", (
            "packaging/debian/%s: %s is %r, not @VERSION@ -- build-deb.sh fills "
            "it from __version__, and hand-editing is how the shipped 2.2.3 man "
            "page ended up saying 2.2.2" % (fname, what, m.group(1)))


# ---------------------------------------------------------------------------
# Runner (so the suite works without pytest)
# ---------------------------------------------------------------------------

def main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as e:                     # noqa: BLE001 - report and continue
            failed += 1
            print("FAIL %s\n     %s" % (name, str(e).replace("\n", "\n     ")))
        else:
            passed += 1
            print("PASS %s" % name)
    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
