# oran-dhcp-gen — O-RAN DHCP Configuration Generator

Generates ISC DHCP and Kea DHCP server configs for **O-RU M-Plane discovery** from a single
YAML data model. One `oran_dhcp.yaml` is the source of truth; change a controller address or
add an O-RU class in one place and regenerate, instead of hand-editing five config files.

On power-up an O-RU sends a DHCP request carrying its vendor-class-identifier. The server
matches that prefix to a class and returns the NETCONF controller address in the O-RAN
vendor options — DHCPv4 **option 43** and DHCPv6 **option 17** (enterprise ID **53148**) —
so the O-RU knows where to call home (SSH 4334 / TLS 4335).

Current version: **2.2.3** · Python 3, no dependencies beyond `python3-yaml`.

## Repository layout

| Path | What it is |
|---|---|
| `pkg/usr/local/bin/oran-dhcp-gen` | The generator — a single ~1250-line Python script. **Edit this.** |
| `pkg/usr/share/oran-dhcp-gen/oran_dhcp.yaml.example` | Full 2.2.x data model, including `lease_profiles` and `ca_ra_profiles` |
| `pkg/` (rest) | Debian package layout — `DEBIAN/control`, man page, changelog |
| `References/ORAN_DHCP_USER_GUIDE.md` | User guide. **Documents v2.0.0 and lags the code** — see below |
| `References/oran-dhcp-gen_2_2_3_all.deb` | The shipped package `pkg/` was extracted from |
| `References/isc/Lab03/` | Hand-written ISC configs from a real lab, predating the generator |
| `References/kea/Lab4/` | A working `oran_dhcp.yaml` plus the Kea configs generated from it |
| `CLAUDE.md` | Architecture notes, invariants, and the domain rules that constrain edits |

## Usage

```bash
# Generate (targets: isc | kea | all)
oran-dhcp-gen oran_dhcp.yaml --target all --outdir /tmp/out/

# Deploy to /etc with timestamped .bak backups, then restart the services
sudo oran-dhcp-gen oran_dhcp.yaml --target kea --deploy --restart

# Run straight from this repo, no install needed
python3 pkg/usr/local/bin/oran-dhcp-gen References/kea/Lab4/oran_dhcp.yaml --target kea --outdir /tmp/out/
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

## Building the package

```bash
fakeroot dpkg-deb --build pkg oran-dhcp-gen_<version>_all.deb
sudo apt install ./oran-dhcp-gen_<version>_all.deb
```

Bump the version in **four** places together: `pkg/DEBIAN/control`, `__version__`, the module
docstring changelog, and `pkg/usr/share/doc/oran-dhcp-gen/changelog.gz`.

## Testing

There is no test suite. The regression check is a byte-diff against the reference configs:
regenerate from `References/kea/Lab4/oran_dhcp.yaml` and diff against the `kea-dhcp{4,6}.conf`
next to it — only the timestamp in the `user-context` header should differ.

Diff the **v6** output too, not just v4. Both Lab4 controllers share one IPv4, so a
controller mix-up produces no v4 diff at all; that is exactly how a stale `ctrl_primary.ipv6`
went unnoticed until it was found and fixed.

## Notes before you change anything

- **The user guide lags the code.** It describes v2.0.0; v2.2.3 adds `lease_profiles`,
  `ca_ra_profiles`, optional per-class `ipv4_range`/`ipv6_range`, `--deploy` and `--restart`.
  Trust the script and the packaged changelog over the guide.
- **The vendor options are built twice** — as raw bytes for ISC, and as structured
  sub-options for Kea to encode itself. `resolve_suboptions()` re-encodes the structured form
  and aborts generation if it does not match the ISC bytes exactly. Change one representation
  and you must change the other.
- Kea must emit *typed* per-sub-option data, never a pre-built blob. Versions 2.2.0–2.2.2
  nested the whole payload under sub-option `0x01`, so Kea wrapped it in its own TLV; O-RUs
  skipped the unknown code and never learned the controller IP, while `kea-dhcp4 -t` still
  validated clean. v2.2.3 fixed this — do not regress it.

See `CLAUDE.md` for the full architecture walkthrough and the O-RAN encoding rules.
