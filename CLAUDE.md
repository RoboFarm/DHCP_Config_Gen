# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

The shipping product is `oran-dhcp-gen`, a **single-file Python 3 script**.

```
bin/oran-dhcp-gen                     # the generator (~1270 lines) — edit this
examples/oran_dhcp.yaml.example       # full data model (richer than the Lab4 YAML)
packaging/debian/changelog            # the real changelog (most accurate history), plain text
packaging/debian/oran-dhcp-gen.1      # man page, plain roff; gzipped at build time
packaging/debian/{control,postinst,prerm,copyright}
packaging/debian/build-deb.sh         # builds the .deb; substitutes the version
tests/run_tests.py                    # test suite (works with or without pytest)
tests/golden/{lab4,example}/          # expected output for both reference inputs
tests/update_goldens.sh               # regenerate goldens after an intended change
docs/ORAN_DHCP_USER_GUIDE.md          # user guide

References/oran-dhcp-gen_2_2_3_all.deb   # the original v2.2.3 package, kept for reference
References/isc/Lab03/                    # hand-written golden ISC configs from a real lab (pre-generator)
References/kea/Lab4/                     # oran_dhcp.yaml + the kea-dhcp{4,6}.conf it generates
```

Build output lands in `build/` and `dist/`; both are gitignored and disposable.

Run the script directly during development: `python3 bin/oran-dhcp-gen ...`.

**The version lives only in `__version__`.** `control`, `postinst` and the man page carry
`@VERSION@` and are filled in by `build-deb.sh`, which also refuses to build unless the
changelog leads with the same version and generates the postinst "what's new" banner from
the top changelog entry. Do not hand-write a version into those files; a test enforces it.

**Keep the user guide in sync.** `docs/ORAN_DHCP_USER_GUIDE.md` was rewritten for v2.2.3 on 2026-08-24 (guide v4.0.0) and documents `lease_profiles`, `ca_ra_profiles`, optional per-class ranges, the CA/RA sub-option codes, and `--deploy`/`--restart`. It had previously drifted two minor versions behind, which is how the 2.2.x features went undocumented — when you change behaviour, update the guide and the changelog in the same change. The man page no longer needs manual attention: `build-deb.sh` stamps it from `__version__`.

## Commands

```bash
# Generate (targets: isc | kea | all)
oran-dhcp-gen oran_dhcp.yaml --target all --outdir /tmp/out/

# Deploy to system paths with timestamped .bak backups, then restart services
sudo oran-dhcp-gen oran_dhcp.yaml --target kea --deploy --restart   # --restart requires --deploy

# Byte-reproducible output (used by the tests)
oran-dhcp-gen oran_dhcp.yaml --target all --outdir /tmp/out/ --no-timestamp

# Validate generated output before trusting it
sudo dhcpd -t   -cf /tmp/out/dhcpd.conf
sudo dhcpd -6 -t -cf /tmp/out/dhcpd6.conf
kea-dhcp4 -t /tmp/out/kea-dhcp4.conf
kea-dhcp6 -t /tmp/out/kea-dhcp6.conf

# Test, then build
python3 tests/run_tests.py
bash packaging/debian/build-deb.sh
```

## Testing

`tests/run_tests.py` compares generated output against `tests/golden/` for both reference
inputs, and additionally asserts three properties on the emitted files:

- ISC and Kea emit the **same O-RAN sub-option codes for every class** (decoded from the
  ISC hex chain and from Kea's per-class `option-data`).
- Every Kea vendor `option-def` is **typed**, never `binary` — a blob is the shape the
  2.2.x defect took.
- Sub-option `0x81` appears at the **top level** of the option-43 chain, not nested.

Those three are the guard against a repeat of the 2.2.0–2.2.2 defect, which shipped three
times because `kea-dhcp4 -t` validates schema and not wire bytes.

`References/isc/Lab03/*` are hand-written and predate the generator — treat them as the
semantic ISC target, not as byte-exact expected output.

After an intended output change: `bash tests/update_goldens.sh`, then read `git diff
tests/golden/` before committing.

## Architecture

`oran_dhcp.yaml` is the single source of truth; five files are generated from it and must never be hand-edited:

| Generated file | Deployed to |
|---|---|
| `dhcpd.conf`, `dhcpd6.conf` | `/etc/dhcp/` |
| `isc-dhcp-server` | `/etc/default/` |
| `kea-dhcp4.conf`, `kea-dhcp6.conf` | `/etc/kea/` |

Pipeline inside the script: `validate()` → range parsers → **TLV resolution** → five `gen_*()` emitters → optional deploy/restart.

- `validate(cfg)` returns three name-keyed lookup dicts — `(controllers, lease_profiles, ca_ra_profiles)` — that every emitter threads through. All errors call `die()` (print + `sys.exit(1)`); the generator never emits partial output.
- **Two parallel representations of the same O-RAN vendor options exist**, and this is the central design constraint:
  - `build_option43_chunks_simple` / `build_option17_chunks_simple` / `build_ca_ra_chunks` → raw byte chunks, used to emit ISC hex-octet strings.
  - `build_subopts_simple` / `build_subopts_ca_ra` → *structured* sub-option dicts, used to emit Kea `option-def` + `option-data` entries so **Kea** builds the TLVs.
  - `resolve_suboptions()` re-encodes the structured form via `_subopt_value_bytes()` and asserts it equals the ISC byte builders' output for every class and family, dying on mismatch. **Any change to one representation must be mirrored in the other**, or generation aborts by design.
- Kea must emit *typed* per-sub-option data, never a pre-built binary blob. v2.2.0–2.2.2 nested the whole payload under sub-option code `0x01`, so Kea wrapped it in its own TLV (`01 LL 81 04 …`); O-RUs skipped the unknown code and never learned the controller IP, while `kea-dhcp4 -t` still validated cleanly. v2.2.3 fixed this — do not regress it.
- `ISC_MULTILINE_CHUNK_THRESHOLD = 3` splits long ISC option chains across continuation lines. Presentation only; wire bytes are identical.
- `group_classes_by_range()` merges classes that share an IP range into one ISC pool. `resolve_lease_params()` resolves `lease_profile` references and emits lease times at **pool** scope (ISC ignores them at class scope).

## Domain rules that constrain edits

- O-RU M-Plane discovery: DHCPv4 **option 43** and DHCPv6 **option 17** (O-RAN enterprise ID **53148**) carry the NETCONF controller address. Sub-options: `0x81` controller IP, `0x86` call-home mode (`01` = TLS, absent/`00` = SSH), `0x82` FQDN, and `0x01/0x03/0x04/0x05/0x06` for the CA/RA bootstrap chain. Call-home ports: SSH 4334, TLS 4335.
- `match_length` is **auto-derived** from `len(match_prefix)` — it is not a YAML field.
- The catch-all class uses `match_prefix: ""` and **must be last**; ISC matches it via an empty substring, Kea via `not member(...)` of every other class.
- Ranges use hyphens, not tildes: `192.168.44.160-169`, `fd00:8b36:f2a9::160-169`.
- A `ca_ra` block on a class only takes effect when `protocol: tls`.
