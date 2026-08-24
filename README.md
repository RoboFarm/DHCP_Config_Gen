# oran-dhcp-gen — O-RAN DHCP Configuration Generator

Generates ISC DHCP and Kea DHCP server configs for **O-RU M-Plane discovery** from a single
YAML data model. One `oran_dhcp.yaml` is the source of truth; change a controller address or
add an O-RU class in one place and regenerate, instead of hand-editing five config files.

On power-up an O-RU sends a DHCP request carrying its vendor-class-identifier. The server
matches that prefix to a class and returns the NETCONF controller address in the O-RAN
vendor options — DHCPv4 **option 43** and DHCPv6 **option 17** (enterprise ID **53148**) —
so the O-RU knows where to call home (SSH 4334 / TLS 4335).

Current version: **2.3.0** · Python 3, no dependencies beyond `python3-yaml`.

## Repository layout

| Path | What it is |
|---|---|
| `bin/oran-dhcp-gen` | The generator — a single ~1270-line Python script. **Edit this.** |
| `examples/oran_dhcp.yaml.example` | Full 2.2.x+ data model, including `lease_profiles` and `ca_ra_profiles` |
| `packaging/debian/` | `control`, `postinst`, `prerm`, `copyright`, plain-text `changelog` and man page, and `build-deb.sh` |
| `tests/run_tests.py` | Test suite — runs with or without pytest |
| `tests/golden/` | Expected output for both reference inputs |
| `docs/ORAN_DHCP_USER_GUIDE.md` | User guide |
| `References/isc/Lab03/` | Hand-written ISC configs from a real lab, predating the generator |
| `References/kea/Lab4/` | A working `oran_dhcp.yaml` plus the Kea configs generated from it |
| `CLAUDE.md` | Architecture notes, invariants, and the domain rules that constrain edits |

Build output goes to `build/` and `dist/`, both gitignored.

## Usage

```bash
# Generate (targets: isc | kea | all)
oran-dhcp-gen oran_dhcp.yaml --target all --outdir /tmp/out/

# Deploy to /etc with timestamped .bak backups, then restart the services
sudo oran-dhcp-gen oran_dhcp.yaml --target kea --deploy --restart

# Byte-reproducible output, for diffing against a known-good config
oran-dhcp-gen oran_dhcp.yaml --target kea --outdir /tmp/out/ --no-timestamp

# Run straight from this repo, no install needed
python3 bin/oran-dhcp-gen References/kea/Lab4/oran_dhcp.yaml --target kea --outdir /tmp/out/
```

Five files are generated and **must never be hand-edited** — regenerate instead:

| File | Deployed to |
|---|---|
| `dhcpd.conf`, `dhcpd6.conf` | `/etc/dhcp/` |
| `isc-dhcp-server` | `/etc/default/` |
| `kea-dhcp4.conf`, `kea-dhcp6.conf` | `/etc/kea/` |

Always validate before restarting a live server:

```bash
sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf     # and: dhcpd -6 -t -cf /etc/dhcp/dhcpd6.conf
kea-dhcp4 -t /etc/kea/kea-dhcp4.conf       # and: kea-dhcp6 -t /etc/kea/kea-dhcp6.conf
```

Note that `kea-dhcp4 -t` checks the schema, **not the wire bytes** — it validated every
one of the broken 2.2.0–2.2.2 configs. See the encoding note below.

## Testing

```bash
python3 tests/run_tests.py        # or: pytest -q tests/
```

Golden-file regression for both reference inputs, plus the checks that matter most:
ISC and Kea must emit the same O-RAN sub-option codes for every class, every Kea vendor
`option-def` must be typed rather than a pre-built blob, and sub-option `0x81` must appear
at the top level of the option-43 chain.

After an intended change to generated output:

```bash
bash tests/update_goldens.sh && git diff tests/golden/
```

Read that diff. The golden files are the only thing between a wire-format regression and
a lab.

## Building the package

```bash
bash packaging/debian/build-deb.sh
sudo apt install ./dist/oran-dhcp-gen_<version>_all.deb
```

**The version lives in exactly one place: `__version__` in `bin/oran-dhcp-gen`.** The build
substitutes it into `control`, `postinst` and the man page, and refuses to run unless the
changelog leads with the same version. To release: bump `__version__`, add a changelog
entry, run `tests/update_goldens.sh`, rebuild.

(This replaced five hand-edited copies of the version, which had already drifted — the
shipped 2.2.3 man page said 2.2.2, and its postinst announced "What's new in 2.2.2" under
a "v2.2.3 installed" header.)

## Notes before you change anything

- **The vendor options are built twice** — as raw bytes for ISC, and as structured
  sub-options for Kea to encode itself. `resolve_suboptions()` re-encodes the structured form
  and aborts generation if it does not match the ISC bytes exactly. Change one representation
  and you must change the other.
- Kea must emit *typed* per-sub-option data, never a pre-built blob. Versions 2.2.0–2.2.2
  nested the whole payload under sub-option `0x01`, so Kea wrapped it in its own TLV; O-RUs
  skipped the unknown code and never learned the controller IP, while `kea-dhcp4 -t` still
  validated clean. v2.2.3 fixed this, and `tests/run_tests.py` now guards it — do not regress it.

See `CLAUDE.md` for the full architecture walkthrough and the O-RAN encoding rules.
