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
    "lab01": os.path.join(REPO_ROOT, "References", "isc", "Lab01", "oran_dhcp.yaml"),
}

# The hand-written ISC configs a lab actually ran, paired with the model that
# is supposed to reproduce them.  Compared by decoded sub-option chain, not by
# bytes: these predate the generator and carry their own comments, logging and
# line breaks.
HANDWRITTEN = {
    "lab01": os.path.join(REPO_ROOT, "References", "isc", "Lab01"),
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


def isc_v4_suboptions(block):
    """Decode `option vendor-encapsulated-options <hex>;` into (code, value).

    DHCPv4 vendor sub-options are 1-byte code, 1-byte length, value.  The chain
    may be split across continuation lines, so it is collected up to the `;`.
    Anchored at line start: hand-written lab configs keep the alternative
    SSH/TLS chain commented out directly above the live one, and an unanchored
    match reads the comment instead.
    """
    m = re.search(r'^[ \t]*option\s+vendor-encapsulated-options\s+(.*?);',
                  block, re.S | re.M)
    if not m:
        return None
    raw = _hex_to_bytes(m.group(1))
    subs, i = [], 0
    while i + 1 < len(raw):
        code, length = raw[i], raw[i + 1]
        subs.append((code, raw[i + 2:i + 2 + length]))
        i += 2 + length
    assert i == len(raw), "v4 TLV chain is not self-consistent: %r" % (raw,)
    return subs


def isc_v6_suboptions(block):
    """Decode `option dhcp6.vendor-opts <eid> <hex>;` into (code, value).

    DHCPv6 vendor sub-options are 2-byte code, 2-byte length, value.
    """
    m = re.search(r'^[ \t]*option\s+dhcp6\.vendor-opts\s+\d+\s+(.*?);',
                  block, re.S | re.M)
    if not m:
        return None
    raw = _hex_to_bytes(m.group(1))
    subs, i = [], 0
    while i + 3 < len(raw):
        code = (raw[i] << 8) | raw[i + 1]
        length = (raw[i + 2] << 8) | raw[i + 3]
        subs.append((code, raw[i + 4:i + 4 + length]))
        i += 4 + length
    assert i == len(raw), "v6 TLV chain is not self-consistent: %r" % (raw,)
    return subs


def isc_v4_suboption_codes(block):
    subs = isc_v4_suboptions(block)
    return None if subs is None else [c for c, _ in subs]


def isc_v6_suboption_codes(block):
    subs = isc_v6_suboptions(block)
    return None if subs is None else [c for c, _ in subs]


def kea_vendor_data_by_class(kea_cfg, root_key):
    """{class name: {sub-option code: data string}} from Kea option-data."""
    cfg = kea_cfg[root_key]
    name_to_code = {d["name"]: d["code"] for d in cfg.get("option-def", [])}
    vendor_spaces = {d["space"] for d in cfg.get("option-def", [])}
    out = {}
    for cl in cfg.get("client-classes", []):
        entry = {}
        for od in cl.get("option-data", []):
            if od.get("space") not in vendor_spaces:
                continue
            code = od.get("code", name_to_code.get(od.get("name")))
            if code is not None:
                entry[code] = od.get("data")
        out[cl["name"]] = entry
    return out


def kea_plain_option_data(kea_cfg, root_key, class_name):
    """{option name: data} for the non-vendor option-data of one class."""
    cfg = kea_cfg[root_key]
    vendor_spaces = {d["space"] for d in cfg.get("option-def", [])}
    for cl in cfg.get("client-classes", []):
        if cl["name"] != class_name:
            continue
        return {od["name"]: od.get("data")
                for od in cl.get("option-data", [])
                if od.get("space") not in vendor_spaces}
    return {}


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


def test_golden_lab01():
    _check_golden("lab01")


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
# Call-home over TLS: sub-option 0x87 and the T1/T2 parity it travels with
# ---------------------------------------------------------------------------

CALLHOME_PORT_CODE = 0x87


def _u16(b):
    return (b[0] << 8) | b[1]


def test_callhome_port_agrees_between_isc_and_kea():
    """0x87 must carry the same port in both backends, for every class.

    Telling an O-RU `protocol: tls` (0x86 = 01) without telling it a port
    leaves it on its firmware default -- 4334, the SSH call-home port on the
    Fujitsu units -- so the TLS listener never sees the connection.  The two
    backends disagreeing on the port is the same failure with extra steps.
    """
    for name in INPUTS:
        g = os.path.join(GOLDEN_DIR, name)
        for isc_file, kea_file, root, decode in (
            ("dhcpd.conf", "kea-dhcp4.conf", "Dhcp4", isc_v4_suboptions),
            ("dhcpd6.conf", "kea-dhcp6.conf", "Dhcp6", isc_v6_suboptions),
        ):
            isc_blocks = isc_class_blocks(open(os.path.join(g, isc_file)).read())
            kea_data = kea_vendor_data_by_class(
                json.load(open(os.path.join(g, kea_file))), root)
            for cls in sorted(set(isc_blocks) & set(kea_data)):
                subs = decode(isc_blocks[cls])
                if subs is None:
                    continue
                isc_port = dict(subs).get(CALLHOME_PORT_CODE)
                kea_port = kea_data[cls].get(CALLHOME_PORT_CODE)
                if isc_port is None and kea_port is None:
                    continue
                assert isc_port is not None and kea_port is not None, (
                    "%s class %r: sub-option 0x87 present in only one backend "
                    "(%s=%r, %s=%r)" % (name, cls, isc_file, isc_port,
                                        kea_file, kea_port))
                assert _u16(isc_port) == int(kea_port), (
                    "%s class %r: call-home port is %d in %s but %s in %s"
                    % (name, cls, _u16(isc_port), isc_file, kea_port, kea_file))


def test_tls_classes_carry_the_tls_callhome_port():
    """A TLS class that sets a call-home port must say 4335, never 4334.

    0x86 = 01 selects TLS; 0x87 must then select the TLS port.  Emitting
    0x86 = 01 alongside port 4334 points the O-RU's TLS client at the SSH
    listener, which is the exact misconfiguration this sub-option exists to
    prevent.
    """
    g = os.path.join(GOLDEN_DIR, "example")
    blocks = isc_class_blocks(open(os.path.join(g, "dhcpd6.conf")).read())
    checked = 0
    for cls, block in blocks.items():
        subs = isc_v6_suboptions(block)
        if subs is None:
            continue
        by_code = dict(subs)
        mode = by_code.get(0x86)
        port = by_code.get(CALLHOME_PORT_CODE)
        if port is None:
            continue
        checked += 1
        if mode == b"\x01":                       # TLS
            assert _u16(port) == 4335, (
                "class %r is TLS (0x86=01) but call-home port is %d -- "
                "an O-RU told TLS will connect to the SSH listener"
                % (cls, _u16(port)))
        else:                                     # SSH: 0x86 absent or 0x00
            assert _u16(port) == 4334, (
                "class %r is SSH (0x86=%r) but call-home port is %d"
                % (cls, mode, _u16(port)))
    assert checked, "no class in the example golden emits 0x87"


def test_callhome_port_is_opt_in():
    """A model that does not set callhome_port emits no 0x87 at all.

    The lab4 reference sets no callhome_port anywhere, so its wire bytes must
    be exactly what they were before the sub-option existed -- upgrading the
    generator must not change what a deployed lab sends.
    """
    g = os.path.join(GOLDEN_DIR, "lab4")
    for isc_file, decode in (("dhcpd.conf", isc_v4_suboptions),
                             ("dhcpd6.conf", isc_v6_suboptions)):
        blocks = isc_class_blocks(open(os.path.join(g, isc_file)).read())
        for cls, block in blocks.items():
            subs = decode(block)
            if subs is None:
                continue
            assert CALLHOME_PORT_CODE not in dict(subs), (
                "lab4 sets no callhome_port, but %s class %r emits 0x87"
                % (isc_file, cls))
    for kea_file, root in (("kea-dhcp4.conf", "Dhcp4"), ("kea-dhcp6.conf", "Dhcp6")):
        cfg = json.load(open(os.path.join(g, kea_file)))[root]
        codes = [d["code"] for d in cfg.get("option-def", [])]
        assert CALLHOME_PORT_CODE not in codes, (
            "lab4 sets no callhome_port, but %s defines option code 135" % kea_file)


# --- Inline models: properties neither reference input covers ---------------

_TLS_MODEL = """
global:
  default_lease_time: 43200
  max_lease_time: 86400
  oran_enterprise_id: 53148
controllers:
  - name: ctrl
    ipv4: "192.168.36.220"
    ipv6: "fd00:8b36:f2a9::24:dc"
lease_profiles:
  bringup:
    default_lease_time: 140
    max_lease_time: 150
    preferred_lifetime: 140
    renewal_time: 60
    rebinding_time: 120
oru_classes:
  - name: Tls4
    match_prefix: "o-ran-ru2/FJ/44R14"
    controller: ctrl
    protocol: tls
    callhome_port: auto
    lease_profile: bringup
    ipv4_range: "192.168.36.160-169"
    ipv6_range: "fd00:8b36:f2a9::160-169"
  - name: Unmatched
    match_prefix: ""
    controller: ctrl
    protocol: ssh
    ipv4_range: "192.168.36.180-189"
    ipv6_range: "fd00:8b36:f2a9::180-189"
subnets:
  ipv4:
    - subnet: "192.168.36.0/24"
      gateway: "192.168.36.1"
      interface: "eth0"
  ipv6:
    - subnet: "fd00:8b36:f2a9::/64"
      interface: "eth0"
"""


def _generate_model(text):
    """Generate from an inline YAML model.

    Returns (tmpdir, {filename: contents}); the caller removes tmpdir.
    """
    tmp = tempfile.mkdtemp(prefix="oran-gen-model-")
    path = os.path.join(tmp, "model.yaml")
    open(path, "w").write(text)
    out = os.path.join(tmp, "out")
    os.makedirs(out)
    generate_ok(path, out, "--no-timestamp")
    return tmp, load_generated(out)


def test_kea_v4_carries_t1_t2_like_isc_does():
    """T1/T2 from a lease_profile must reach both backends.

    Kea has no per-client-class renew-timer/rebind-timer, so these have to go
    out as DHCPv4 options 58/59 the way the ISC class block does.  Handing Kea
    the short bring-up lifetimes without their T1/T2 left the two backends
    renewing on different schedules for exactly the classes doing TLS
    enrolment.  Neither reference input has a v4 class on a lease profile, so
    this model supplies one.
    """
    tmp, files = _generate_model(_TLS_MODEL)
    try:
        isc = isc_class_blocks(files["dhcpd.conf"])["Tls4"]
        assert "option dhcp-renewal-time 60;" in isc
        assert "option dhcp-rebinding-time 120;" in isc

        kea = kea_plain_option_data(json.loads(files["kea-dhcp4.conf"]),
                                    "Dhcp4", "Tls4")
        assert kea.get("dhcp-renewal-time") == "60", (
            "ISC emits T1=60 for class Tls4 but Kea DHCPv4 emits %r"
            % kea.get("dhcp-renewal-time"))
        assert kea.get("dhcp-rebinding-time") == "120", (
            "ISC emits T2=120 for class Tls4 but Kea DHCPv4 emits %r"
            % kea.get("dhcp-rebinding-time"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_callhome_port_auto_resolves_per_protocol():
    """`auto` means 4335 on a TLS class and 4334 on an SSH one."""
    model = _TLS_MODEL.replace(
        "    protocol: ssh\n    ipv4_range",
        "    protocol: ssh\n    callhome_port: auto\n    ipv4_range")
    tmp, files = _generate_model(model)
    try:
        blocks = isc_class_blocks(files["dhcpd.conf"])
        ports = {cls: _u16(dict(isc_v4_suboptions(blocks[cls]))[CALLHOME_PORT_CODE])
                 for cls in ("Tls4", "Unmatched")}
        assert ports == {"Tls4": 4335, "Unmatched": 4334}, \
            "callhome_port: auto resolved to %r" % (ports,)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_tls_ca_controller_key_is_rejected():
    """The phantom `tls_ca:` schema must fail loudly, not be ignored.

    A commented-out tls_ca block shipped in the Lab4 reference YAML, so
    uncommenting it looked like the way to turn on TLS bootstrap.  The
    generator had no such field: it emitted a payload with no CA/RA
    sub-options and said nothing.
    """
    tmp = tempfile.mkdtemp(prefix="oran-gen-tlsca-")
    try:
        bad = _write_yaml(tmp, _TLS_MODEL.replace(
            '    ipv6: "fd00:8b36:f2a9::24:dc"',
            '    ipv6: "fd00:8b36:f2a9::24:dc"\n'
            '    tls_ca:\n'
            '      ipv6: "fd00:8b36:f2a9::95:240"\n'
            '      port: 8091'))
        out = os.path.join(tmp, "out")
        os.makedirs(out)
        proc = generate(bad, out, "--no-timestamp")
        assert proc.returncode != 0, "a tls_ca block must not be silently ignored"
        assert b"ca_ra_profiles" in proc.stdout, (
            "the tls_ca error should point at the real schema:\n%s"
            % proc.stdout.decode())
        assert not os.listdir(out), "must not leave partial output"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_bad_callhome_port_is_rejected():
    for value in ("70000", "0", "'ssh'"):
        tmp = tempfile.mkdtemp(prefix="oran-gen-port-")
        try:
            bad = _write_yaml(tmp, _TLS_MODEL.replace(
                "    callhome_port: auto", "    callhome_port: %s" % value))
            proc = generate(bad, tmp, "--no-timestamp")
            assert proc.returncode != 0, \
                "callhome_port: %s should be rejected" % value
            assert b"Traceback" not in proc.stdout, \
                "callhome_port: %s produced a traceback" % value
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Reproducing a hand-written lab config
# ---------------------------------------------------------------------------

def test_generator_reproduces_lab01_vendor_chains():
    """The generated chains must equal the ones Lab01 actually ran.

    Lab01's dhcpd.conf / dhcpd6.conf came from the lab and predate the
    generator, so the files differ in comments, logging and line breaks.  What
    has to be identical is the decoded option-43 / option-17 sub-option chain
    of every class on every family -- that is what reaches an O-RU.
    """
    src = os.path.join(HANDWRITTEN["lab01"], "oran_dhcp.yaml")
    tmp = tempfile.mkdtemp(prefix="oran-gen-lab01-")
    try:
        generate_ok(src, tmp, "--no-timestamp")
        for fname, decode in (("dhcpd.conf", isc_v4_suboptions),
                              ("dhcpd6.conf", isc_v6_suboptions)):
            ref = isc_class_blocks(
                open(os.path.join(HANDWRITTEN["lab01"], fname)).read())
            got = isc_class_blocks(open(os.path.join(tmp, fname)).read())
            assert ref, "%s: no classes found in the hand-written config" % fname
            for cls in sorted(ref):
                assert cls in got, (
                    "%s: hand-written config has class %r, generated does not"
                    % (fname, cls))
                want, have = decode(ref[cls]), decode(got[cls])
                assert want == have, (
                    "%s class %r: generated chain differs from the config the "
                    "lab ran.\n  lab: %s\n  gen: %s"
                    % (fname, cls,
                       [(hex(c), v.hex(':')) for c, v in (want or [])],
                       [(hex(c), v.hex(':')) for c, v in (have or [])]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_ca_ra_port_can_differ_per_family():
    """A per-family ca_ra.port must reach each family's chain separately.

    Lab01 fronts the same CMP endpoint on a different port per family --
    TDDn77 on v4 8081 / v6 8080.  Before 2.5.0 `port` was a single scalar used
    for both, so this could not be expressed at all.
    """
    src = os.path.join(HANDWRITTEN["lab01"], "oran_dhcp.yaml")
    tmp = tempfile.mkdtemp(prefix="oran-gen-port-fam-")
    try:
        generate_ok(src, tmp, "--no-timestamp")
        expected = {                       # class -> (v4 port, v6 port)
            "TDDn77":    (8081, 8080),
            "FDDn25n66": (8083, 8082),
        }
        for cls, (want4, want6) in expected.items():
            v4 = dict(isc_v4_suboptions(
                isc_class_blocks(open(os.path.join(tmp, "dhcpd.conf")).read())[cls]))
            v6 = dict(isc_v6_suboptions(
                isc_class_blocks(open(os.path.join(tmp, "dhcpd6.conf")).read())[cls]))
            assert _u16(v4[0x03]) == want4, (
                "class %r: IPv4 CA port is %d, expected %d"
                % (cls, _u16(v4[0x03]), want4))
            assert _u16(v6[0x03]) == want6, (
                "class %r: IPv6 CA port is %d, expected %d"
                % (cls, _u16(v6[0x03]), want6))
            assert want4 != want6, "this test is pointless if the ports match"

        # Kea must carry the same split.
        for fname, root, want_key in (("kea-dhcp4.conf", "Dhcp4", 0),
                                      ("kea-dhcp6.conf", "Dhcp6", 1)):
            data = kea_vendor_data_by_class(
                json.load(open(os.path.join(tmp, fname))), root)
            for cls, ports in expected.items():
                assert int(data[cls][0x03]) == ports[want_key], (
                    "%s class %r: CA port is %s, expected %d"
                    % (fname, cls, data[cls][0x03], ports[want_key]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_ca_ra_port_mapping_must_cover_every_served_family():
    """A port mapping that omits a family the class serves must fail.

    Silently falling back would send the wrong port to that family, which is
    the failure the mapping exists to prevent.
    """
    model = _TLS_MODEL.replace(
        "    callhome_port: auto\n",
        "    ca_ra:\n"
        "      profile: ca\n"
        "      port:\n"
        "        ipv6: 8080\n")            # Tls4 has an ipv4_range too
    model = model.replace(
        "lease_profiles:",
        "ca_ra_profiles:\n"
        "  ca:\n"
        "    ca_server_ipv4: \"192.168.36.235\"\n"
        "    ca_server_ipv6: \"fd00:8b36:f2a9::24:eb\"\n"
        "    uri_path: \"/pkix/\"\n"
        "    subject_dn: \"/CN=Test\"\n"
        "    app_protocol: \"http\"\n"
        "lease_profiles:")
    tmp = tempfile.mkdtemp(prefix="oran-gen-portmap-")
    try:
        bad = _write_yaml(tmp, model)
        out = os.path.join(tmp, "out")
        os.makedirs(out)
        proc = generate(bad, out, "--no-timestamp")
        assert proc.returncode != 0, \
            "a ca_ra.port mapping missing the ipv4 port must be rejected"
        assert b"ipv4" in proc.stdout, \
            "the error should name the missing family:\n%s" % proc.stdout.decode()
        assert not os.listdir(out), "must not leave partial output"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# defaults: block -- enabling or disabling TLS lab-wide in one edit
# ---------------------------------------------------------------------------

_DEFAULTS_MODEL = """
global:
  default_lease_time: 43200
  max_lease_time: 86400
  oran_enterprise_id: 53148
controllers:
  - name: ctrl
    ipv4: "192.168.36.220"
    ipv6: "fd00:8b36:f2a9::24:dc"
ca_ra_profiles:
  ca:
    ca_server_ipv4: "192.168.36.235"
    ca_server_ipv6: "fd00:8b36:f2a9::24:eb"
    uri_path: "/pkix/"
    subject_dn: "/CN=Test"
    app_protocol: "http"
defaults:
  controller: ctrl
  protocol: tls
  callhome_port: auto
  ca_ra:
    profile: ca
    port: 8080
oru_classes:
  - name: Inherits
    match_prefix: "o-ran-ru2/FJ/44R14"
    ipv4_range: "192.168.36.100-109"
    ipv6_range: "fd00:8b36:f2a9::100-109"
  - name: OwnPort
    match_prefix: "o-ran-ru2/FJ/44R26"
    ipv4_range: "192.168.36.110-119"
    ipv6_range: "fd00:8b36:f2a9::110-119"
    ca_ra:
      port: 9090
  - name: Unmatched
    match_prefix: ""
    protocol: ssh
    ipv4_range: "192.168.36.180-189"
    ipv6_range: "fd00:8b36:f2a9::180-189"
subnets:
  ipv4:
    - subnet: "192.168.36.0/24"
      gateway: "192.168.36.1"
      interface: "eth0"
  ipv6:
    - subnet: "fd00:8b36:f2a9::/64"
      interface: "eth0"
"""


def test_defaults_are_inherited_by_classes():
    """A class that sets nothing gets the whole default TLS setup."""
    tmp, files = _generate_model(_DEFAULTS_MODEL)
    try:
        subs = dict(isc_v4_suboptions(
            isc_class_blocks(files["dhcpd.conf"])["Inherits"]))
        assert sorted(subs) == [0x01, 0x03, 0x04, 0x05, 0x06, 0x81, 0x86, 0x87], \
            "inherited class emitted %s" % sorted(hex(c) for c in subs)
        assert _u16(subs[0x03]) == 8080, "inherited CA port"
        assert _u16(subs[0x87]) == 4335, "inherited callhome_port: auto -> TLS"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_class_setting_overrides_the_default():
    """protocol: ssh on one class opts it out of a TLS-by-default lab."""
    tmp, files = _generate_model(_DEFAULTS_MODEL)
    try:
        subs = dict(isc_v4_suboptions(
            isc_class_blocks(files["dhcpd.conf"])["Unmatched"]))
        assert sorted(subs) == [0x81, 0x87], (
            "an ssh class in a tls-default lab should carry only the "
            "controller IP (and its port), got %s"
            % sorted(hex(c) for c in subs))
        assert _u16(subs[0x87]) == 4334, \
            "callhome_port: auto must resolve per the class's own protocol"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_ca_ra_merges_one_level_with_the_default():
    """A class overriding only ca_ra.port keeps the inherited profile."""
    tmp, files = _generate_model(_DEFAULTS_MODEL)
    try:
        subs = dict(isc_v4_suboptions(
            isc_class_blocks(files["dhcpd.conf"])["OwnPort"]))
        assert _u16(subs[0x03]) == 9090, "class port should win"
        assert 0x04 in subs and 0x05 in subs, \
            "the inherited profile's URI path and DN should survive the merge"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_ca_ra_is_not_inherited_into_an_ssh_class():
    """An SSH class in a TLS-default lab must not warn about an unused block.

    ca_ra only takes effect under protocol: tls, so inheriting it into every
    SSH class would emit a "ca_ra will be ignored" warning nobody asked for.
    """
    tmp = tempfile.mkdtemp(prefix="oran-gen-inherit-")
    try:
        path = _write_yaml(tmp, _DEFAULTS_MODEL)
        out = os.path.join(tmp, "out")
        os.makedirs(out)
        proc = generate(path, out, "--no-timestamp")
        assert proc.returncode == 0
        assert b"ca_ra will be ignored" not in proc.stdout, (
            "inheriting ca_ra into an SSH class produced a spurious warning:\n%s"
            % proc.stdout.decode())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_defaults_rejects_a_non_inheritable_key():
    """ipv4_range and friends cannot be defaulted -- they define the class."""
    tmp = tempfile.mkdtemp(prefix="oran-gen-baddef-")
    try:
        bad = _write_yaml(tmp, _DEFAULTS_MODEL.replace(
            "defaults:\n  controller: ctrl",
            'defaults:\n  ipv4_range: "192.168.36.1-9"\n  controller: ctrl'))
        out = os.path.join(tmp, "out")
        os.makedirs(out)
        proc = generate(bad, out, "--no-timestamp")
        assert proc.returncode != 0, "defaults must reject ipv4_range"
        assert b"ipv4_range" in proc.stdout
        assert not os.listdir(out), "must not leave partial output"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_tls_without_callhome_port_warns():
    """The trap: 0x86 says TLS, nothing says which port.

    The O-RU then uses its firmware default -- 4334, the SSH call-home port,
    on the Fujitsu units -- and TLS call-home never completes while the lease
    still looks healthy.  Not fatal, because firmware that already defaults to
    4335 is fine and refusing would break configs that work today, but it must
    not be silent.
    """
    tmp = tempfile.mkdtemp(prefix="oran-gen-trap-")
    try:
        path = _write_yaml(tmp, _DEFAULTS_MODEL.replace(
            "  callhome_port: auto\n", ""))
        out = os.path.join(tmp, "out")
        os.makedirs(out)
        proc = generate(path, out, "--no-timestamp")
        assert proc.returncode == 0, "this must warn, not fail"
        text = proc.stdout.decode()
        assert "callhome_port" in text and "4334" in text, (
            "a tls class with no callhome_port must say so:\n%s" % text)
        assert "Inherits" in text, "the warning should name the class"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_warning_when_tls_class_sets_the_port():
    tmp = tempfile.mkdtemp(prefix="oran-gen-notrap-")
    try:
        path = _write_yaml(tmp, _DEFAULTS_MODEL)
        out = os.path.join(tmp, "out")
        os.makedirs(out)
        proc = generate(path, out, "--no-timestamp")
        assert b"sets no callhome_port" not in proc.stdout, (
            "callhome_port is set lab-wide; nothing should warn:\n%s"
            % proc.stdout.decode())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# --explain
# ---------------------------------------------------------------------------

def _explain(yaml_path, *extra):
    proc = subprocess.run(
        [sys.executable, GEN, yaml_path, "--explain", *extra],
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=120)
    assert proc.returncode == 0, proc.stdout.decode()
    return proc.stdout.decode()


def _explain_wire_lines(text):
    """{(class, family): wire hex} from an --explain report."""
    out, cls, family = {}, None, None
    for line in text.splitlines():
        m = re.match(r'^(\S+)(   — |$)', line)
        if m and not line.startswith((' ', '=', '[')):
            cls = m.group(1)
        m = re.match(r'^  (ipv4|ipv6)\s', line)
        if m:
            family = m.group(1)
        m = re.match(r'^\s+wire: (\S+)$', line)
        if m and cls and family:
            out[(cls, family)] = m.group(1)
    return out


def test_explain_wire_matches_the_generated_config():
    """Every `wire:` line must be the chain the config actually carries.

    --explain is only worth having if it cannot disagree with what is emitted.
    It is built on resolve_suboptions(), the same structured form the Kea
    backend consumes, so this checks the report against the ISC files rather
    than against itself.
    """
    for name, src in INPUTS.items():
        text = _explain(src)
        wire = _explain_wire_lines(text)
        assert wire, "%s: --explain produced no wire lines" % name

        tmp = tempfile.mkdtemp(prefix="oran-gen-explain-")
        try:
            generate_ok(src, tmp, "--no-timestamp")
            for fname, family, decode in (
                ("dhcpd.conf", "ipv4", isc_v4_suboptions),
                ("dhcpd6.conf", "ipv6", isc_v6_suboptions),
            ):
                blocks = isc_class_blocks(open(os.path.join(tmp, fname)).read())
                for cls, block in blocks.items():
                    subs = decode(block)
                    if subs is None:
                        continue
                    hdr = 2 if family == "ipv4" else 4
                    raw = b"".join(
                        (bytes([c, len(v)]) if family == "ipv4"
                         else bytes([c >> 8, c & 0xFF, len(v) >> 8, len(v) & 0xFF]))
                        + v for c, v in subs)
                    want = ":".join("%02x" % b for b in raw)
                    got = wire.get((cls, family))
                    assert got is not None, (
                        "%s: --explain reported no %s chain for class %r"
                        % (name, family, cls))
                    assert got == want, (
                        "%s class %r (%s): --explain says\n  %s\nbut %s carries\n  %s"
                        % (name, cls, family, got, fname, want))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def test_explain_writes_nothing():
    tmp = tempfile.mkdtemp(prefix="oran-gen-explain-ro-")
    try:
        out = os.path.join(tmp, "out")
        os.makedirs(out)
        proc = subprocess.run(
            [sys.executable, GEN, INPUTS["lab01"], "--explain",
             "--outdir", out, "--target", "all"],
            cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=120)
        assert proc.returncode == 0, proc.stdout.decode()
        assert not os.listdir(out), \
            "--explain must not write files, found %s" % os.listdir(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_explain_flags_a_tls_class_with_no_callhome_port():
    """The report has to surface the trap, not just list bytes."""
    text = _explain(INPUTS["lab01"])
    assert "no 0x87" in text, \
        "Lab01's TLS classes send no 0x87; --explain should say so:\n%s" % text
    assert "4334" in text and "4335" in text, \
        "the flag should name both the wrong default and the right port"


def test_explain_refuses_to_deploy():
    proc = subprocess.run(
        [sys.executable, GEN, INPUTS["lab01"], "--explain", "--deploy"],
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=120)
    assert proc.returncode != 0, "--explain --deploy should be refused"
    assert b"Traceback" not in proc.stdout


def test_explain_covers_every_class_and_names_unserved_families():
    """A class absent from the report is worse than no report at all."""
    text = _explain(INPUTS["example"])
    import yaml as _yaml
    model = _yaml.safe_load(open(INPUTS["example"]))
    for cls in model["oru_classes"]:
        assert re.search(r'^%s(   — |$)' % re.escape(cls["name"]), text, re.M), \
            "--explain omitted class %r" % cls["name"]
    assert "not served (no ipv4_range)" in text, \
        "a class with no ipv4_range should be shown as not served on that family"


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
