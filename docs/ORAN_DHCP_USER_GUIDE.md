# O-RAN DHCP Tools — User Guide

**Version:** 4.4.0
**Last Updated:** 2026-08-25
**Packages Covered:** `oran-dhcp-gen` v2.7.0 · `dhcp-oru-toolkit` v2.1.2

> The lease viewer was renamed. `dhcp-lease-list` 1.3.0 became the
> `dhcp-oru-toolkit` package at 2.0.0, which ships `dhcp-lease-list` and
> `dhcp-forensics`, and now lives in its own repository
> (`RoboFarm/oran-dhcp`).

---

## Table of Contents

1. [Overview](#overview)
2. [Package Summary](#package-summary)
3. [Installation](#installation)
4. [oran-dhcp-gen — Configuration Generator](#oran-dhcp-gen)
   - [Quick Start](#quick-start)
   - [CLI Reference](#cli-reference)
   - [YAML Data Model Reference](#yaml-data-model-reference)
     - [global](#global--global-settings)
     - [controllers](#controllers--o-ru-controller-definitions)
     - [lease_profiles](#lease_profiles--reusable-lease-parameter-sets)
     - [ca_ra_profiles](#ca_ra_profiles--tls-cara-bootstrap-settings)
     - [oru_classes](#oru_classes--o-ru-class-definitions)
     - [subnets](#subnets--network-configuration)
   - [Vendor Option Encoding](#vendor-option-encoding)
   - [Generated Output Files](#generated-output-files)
   - [ISC DHCP vs Kea DHCP — Config Translation](#isc-dhcp-vs-kea-dhcp--config-translation)
   - [Deploying with --deploy](#deploying-with---deploy)
   - [Deploying ISC DHCP Manually](#deploying-isc-dhcp-manually)
   - [Deploying Kea DHCP Manually](#deploying-kea-dhcp-manually)
5. [dhcp-lease-list — Lease Viewer](#dhcp-lease-list)
   - [Quick Start](#quick-start-1)
   - [CLI Reference](#cli-reference-1)
   - [Output Fields](#output-fields)
   - [ISC DHCP Mode](#isc-dhcp-mode)
   - [Kea DHCP Mode](#kea-dhcp-mode)
   - [DHCPv6 DUID MAC Extraction](#dhcpv6-duid-mac-extraction)
6. [O-RAN DHCP Background](#o-ran-dhcp-background)
7. [Troubleshooting](#troubleshooting)
8. [Version History](#version-history)

---

## Overview

This toolset simplifies deployment and monitoring of DHCP services for O-RAN O-RU (Radio Unit) M-Plane discovery. It addresses two key operational needs:

**Configuration management** — a single YAML data model (`oran_dhcp.yaml`) generates all DHCP config files for both ISC DHCP and Kea DHCP. Change a controller IP or add a new O-RU model in one place and regenerate — no manual config editing. Reusable `lease_profiles` and `ca_ra_profiles` keep repeated settings in one place, and `--deploy` rolls the result out with timestamped backups.

**Lease visibility** — a unified lease viewer (`dhcp-lease-list`) displays both IPv4 and IPv6 active leases in one command, supporting both ISC DHCP lease files and Kea DHCP CSV files, with automatic MAC address extraction from DHCPv6 DUIDs.

---

## Package Summary

| Package | Version | Binary | Purpose |
|---------|---------|--------|---------|
| `oran-dhcp-gen` | 2.3.0 | `oran-dhcp-gen` | Generate ISC and Kea DHCP configs from YAML |
| `dhcp-lease-list` | 1.3.0 | `dhcp-lease-list` | View IPv4 + IPv6 leases for ISC and Kea DHCP |

---

## Installation

Both packages are `.deb` files. Install with `apt` for automatic dependency handling.

```bash
# Install config generator (requires python3 >= 3.6, python3-yaml)
sudo apt install ./oran-dhcp-gen_2.3.0_all.deb

# Install lease viewer (requires python3)
sudo apt install ./dhcp-lease-list_1.3.0_all.deb
```

**Verify:**
```bash
oran-dhcp-gen --version   # oran-dhcp-gen 2.3.0
dhcp-lease-list --version # dhcp-lease-list 1.3.0
```

**Remove:**
```bash
sudo apt remove oran-dhcp-gen
sudo apt remove dhcp-lease-list
```

> **Note:** Removing `dhcp-lease-list` automatically restores the original ISC DHCP `dhcp-lease-list` command if one existed before installation.

---

## oran-dhcp-gen

### Quick Start

```bash
# 1. Copy the bundled example YAML
cp /usr/share/oran-dhcp-gen/oran_dhcp.yaml.example ~/oran_dhcp.yaml

# 2. Edit to match your environment
nano ~/oran_dhcp.yaml

# 3a. Generate to a directory and review before touching the live server
oran-dhcp-gen ~/oran_dhcp.yaml --target isc --outdir /tmp/out/   # ISC DHCP
oran-dhcp-gen ~/oran_dhcp.yaml --target kea --outdir /tmp/out/   # Kea DHCP
oran-dhcp-gen ~/oran_dhcp.yaml --target all --outdir /tmp/out/   # Both at once

# 3b. Or generate, back up, install and restart in one step
sudo oran-dhcp-gen ~/oran_dhcp.yaml --target kea --deploy --restart
```

### CLI Reference

```
oran-dhcp-gen <yaml_file> [OPTIONS]

Arguments:
  yaml_file             Path to oran_dhcp.yaml data model

Options:
  --target {isc,kea,all}   Output target (default: isc)
  --explain                Print what each O-RU class will actually receive —
                           decoded sub-option by sub-option — and write
                           nothing. Cannot be combined with --deploy/--restart
  --outdir DIR             Output directory
                           (default: a temp dir when --deploy is used,
                            the current directory otherwise)
  --deploy                 Copy generated files to their system paths,
                           backing up anything already there
  --restart                Restart the DHCP service(s) after a successful
                           deploy. Requires --deploy
  --no-timestamp           Omit the generation time from config headers, so
                           output depends only on the input YAML
  --version                Show version and exit
  --help                   Show help
```

**Examples:**
```bash
# Generate ISC DHCP configs into current directory
oran-dhcp-gen oran_dhcp.yaml

# Generate Kea configs into /tmp/kea-out/
oran-dhcp-gen oran_dhcp.yaml --target kea --outdir /tmp/kea-out/

# Generate all 5 files at once
oran-dhcp-gen oran_dhcp.yaml --target all --outdir /tmp/all-out/

# Validate the YAML without writing anywhere permanent
oran-dhcp-gen oran_dhcp.yaml --target all --outdir /tmp/test/

# Full production rollout, both servers
sudo oran-dhcp-gen oran_dhcp.yaml --target all --deploy --restart

# See what each class will send, without writing or deploying anything
oran-dhcp-gen oran_dhcp.yaml --explain

# Byte-compare against what is currently deployed. --no-timestamp makes the
# output depend only on the YAML, so an empty diff means the configs really
# are identical rather than differing only in their header line.
oran-dhcp-gen oran_dhcp.yaml --target kea --outdir /tmp/new/ --no-timestamp
diff /tmp/new/kea-dhcp4.conf /etc/kea/kea-dhcp4.conf
```

Validation runs before anything is written. On success the generator prints a summary line:

```
[OK] Validation passed — 11 O-RU classes, 1 controllers, 1 lease profiles, 1 ca_ra profiles
```

Any validation failure prints `[ERROR] ...` and exits with status 1 **without generating partial output**.

---

### Seeing what a class actually sends — `--explain`

The wire bytes are where O-RU bring-up goes wrong, and they are the one thing a config file does not show you plainly: `dhcpd.conf` carries a hex chain, `kea-dhcp4.conf` carries a list of typed `option-data` entries, and neither reads as "this O-RU will be told to call home to X on port Y". `--explain` decodes it:

```bash
oran-dhcp-gen oran_dhcp.yaml --explain
```

```
TDDn77   — TDD n77 RU (Fujitsu 44R14 series) — TLS with CMP enrolment
  matches   vendor class starting "o-ran-ru2/FJ/44R14"  (18 bytes)
  protocol  tls    controller ctrl
  ipv4      192.168.56.100 - 192.168.56.119
            DHCPv4 option 43 — 104 bytes, 7 sub-option(s)
              0x01  CA/RA server IP    192.168.56.12
              0x03  CA/RA port         8081
              0x04  CA/RA URI path     "/pkix/"
              0x05  CA/RA subject DN   "/CN=1FinityLab Root CA/OU=WV Lab/..."
              0x06  CA/RA protocol     "http"
              0x81  Controller IP      192.168.56.12
              0x86  Call-home mode     TLS  (0x01)
            wire: 01:04:c0:a8:38:0c:03:02:1f:91:04:06:2f:70:6b:69:78:2f:...
  ipv6      fd00:8b36:f2a9::160 - fd00:8b36:f2a9::169
            DHCPv6 option 17, enterprise 53148 — 142 bytes, 7 sub-option(s)
              ...
              0x03  CA/RA port         8080
              ...
  !         no 0x87: the O-RU picks its own call-home port. Firmware defaulting to
            4334 (the SSH port) will never complete a TLS session. Add
            'callhome_port: auto' to send 4335.
```

Three things it is good for:

- **Before a deploy** — confirm the controller address, CA port and call-home mode each O-RU model will get, without putting a radio on the wire.
- **During bring-up** — the `wire:` line is the exact byte sequence to compare against `tcpdump -vvv 'port 67 or port 68'`. If they differ, the O-RU is not being served by the config you think it is.
- **Catching the silent faults** — a `tls` class sending no `0x87` is flagged with the port the O-RU will fall back to, and a `tls` class with no `ca_ra` block is noted as controller-only. Neither is visible in a hex dump.

The report is generated from the same resolved sub-options the emitters use, and a regression test decodes both the report and the generated configs and requires them to match for every class and family — so `--explain` cannot drift from what is actually written.

`--explain` writes nothing and is refused alongside `--deploy` or `--restart`.

---

### YAML Data Model Reference

`oran_dhcp.yaml` is the **single source of truth** — never edit generated files directly.

Top-level sections: `global`, `controllers`, `lease_profiles` (optional), `ca_ra_profiles` (optional), `oru_classes`, `subnets`.

#### `global` — Global Settings

```yaml
global:
  default_lease_time: 43200      # Lease duration in seconds (12 hours)
  max_lease_time: 86400          # Maximum lease duration (24 hours)
  oran_enterprise_id: 53148      # O-RAN Alliance IANA enterprise ID (do not change)
```

All three fields are required. They apply to every class that does **not** reference a `lease_profile`.

#### `controllers` — O-RU Controller Definitions

Define one or more controllers. Each O-RU class references a controller by name. Multiple controllers allow different O-RU families to point to different management endpoints.

```yaml
controllers:
  - name: ctrl_primary           # Unique name used as reference key
    description: "Primary O-RU controller"
    ipv4: "192.168.36.249"       # Encoded into DHCPv4 option 43 TLV (0x81)
    ipv6: "fd00:8b36:f2a9::24:dc"  # Encoded into DHCPv6 option 17 TLV (0x0081)

  - name: ctrl_lab
    description: "Lab test controller"
    ipv4: "10.0.0.1"
    ipv6: "fd00:dead:beef::1"
```

`name`, `ipv4` and `ipv6` are all required — **both address families, even if a class only uses one.**

> **Keep the two families consistent.** If two controller entries describe the same physical node, give them the same IPv4 *and* the same IPv6. A v6 address that silently disagrees with its v4 partner produces no diff at all in the IPv4 output, so the mistake surfaces only as O-RUs that lease an address and then never call home.

#### `lease_profiles` — Reusable Lease Parameter Sets

*(optional; new in 2.2.0)*

A named set of lease timers that classes can share. Referenced from a class with `lease_profile: <name>`. Classes without a `lease_profile` use the `global` timers.

```yaml
lease_profiles:
  bringup:
    description: "Short lease during bring-up — fast reclaim of stale state."
    default_lease_time:  140
    max_lease_time:      150
    preferred_lifetime:  140    # IPv6 only; ignored for IPv4
    renewal_time:         60    # T1 — emitted as option dhcp-renewal-time
    rebinding_time:      120    # T2 — emitted as option dhcp-rebinding-time
```

Every field is optional; only what you set is emitted.

**Where each value lands** — this split is deliberate, because ISC DHCP ignores lease *times* declared at class scope:

| Field | ISC DHCP | Kea DHCP |
|---|---|---|
| `default_lease_time` | `default-lease-time` inside `pool {}` / `pool6 {}` | `valid-lifetime` on the client class |
| `max_lease_time` | `max-lease-time` inside the pool | `max-valid-lifetime` on the client class |
| `preferred_lifetime` | `preferred-lifetime` inside `pool6 {}` | `preferred-lifetime` on the client class |
| `renewal_time` (T1) | `option dhcp-renewal-time` inside the `class {}` block | *(not emitted)* |
| `rebinding_time` (T2) | `option dhcp-rebinding-time` inside the `class {}` block | *(not emitted)* |

If two classes share an IP range but reference *different* lease profiles, the pool can only carry one set of timers. The generator warns and uses the profile of the first member:

```
[WARN] Pool fd00:8b36:f2a9::150-159 contains classes with different lease_profiles; using profile from 'ATTn25n66-DC'
```

#### `ca_ra_profiles` — TLS CA/RA Bootstrap Settings

*(optional; new in 2.2.0)*

Captures the parts of a TLS certificate-enrolment payload that are identical across classes. Referenced from a class with a `ca_ra:` block. **Only takes effect when the class sets `protocol: tls`** — with `protocol: ssh` the generator warns and ignores the block.

```yaml
ca_ra_profiles:
  att_common:
    description: "SPM CA — shared across all TLS classes"
    ca_server_ipv4:    "192.168.36.240"            # sub-option 0x01 (IPv4 output)
    ca_server_ipv6:    "fd00:8b36:f2a9::95:240"    # sub-option 0x01 (IPv6 output)
    uri_path:          "/pkix/"                    # sub-option 0x04
    subject_dn:        "/OU=SPM/O=1Finity/C=US/CN=ATT-SSL/L=WV/ST=Texas"  # 0x05
    app_protocol:      "http"                      # sub-option 0x06
```

| Field | Required | Notes |
|---|---|---|
| `ca_server_ipv4` | One of the two | Required to emit IPv4 sub-options for a class using this profile |
| `ca_server_ipv6` | One of the two | Required to emit IPv6 sub-options |
| `uri_path` | Yes | Enrolment URI path |
| `subject_dn` | Yes | Certificate subject DN |
| `app_protocol` | Yes | e.g. `http` |
| `netconf_mode_byte` | No | **Deprecated in 2.2.1.** The 0x86 byte is now derived from the class `protocol`. Setting it still overrides, but the generator warns |

#### `oru_classes` — O-RU Class Definitions

Each class matches an O-RU's vendor-class-identifier and maps it to a controller, IP pool, and protocol.

```yaml
oru_classes:
  - name: Gen1TB                           # Unique class name
    description: "Generation 1 Tower Base (Fujitsu N712926R)"
    match_prefix: "o-ran-ru2/FJ/N712926R"  # Vendor-class-identifier prefix
                                           # match_length auto-derived as len(match_prefix)
    controller: ctrl_primary               # Must match a name in controllers list
    protocol: ssh                          # ssh or tls
    ipv4_range: "192.168.36.110-119"       # Format: A.B.C.start-end
    ipv6_range: "fd00:8b36:f2a9::110-119"  # Format: prefix::start-end
    options:                               # Optional per-class overrides
      interface_mtu: 1440                  # Sets DHCP option 26

  # IPv6-only TLS class with certificate enrolment
  - name: ATTn77
    description: "ATT n77 RU (44R14 series) — TLS bootstrap, IPv6-only"
    match_prefix: "o-ran-ru2/FJ/44R14"
    controller: ctrl_primary
    protocol: tls
    callhome_port: auto                    # -> 4335 (sub-option 0x87)
    lease_profile: bringup                 # Reference into lease_profiles
    # ipv4_range omitted — this class is not served on IPv4 at all
    ipv6_range: "fd00:8b36:f2a9::130-149"
    ca_ra:
      profile: att_common                  # Reference into ca_ra_profiles
      port: 8093                           # Per-class CA port (sub-option 0x03)
      mplane_fqdn: "mplane.local"          # Optional (sub-option 0x82)
      include_controller_ip: false         # Optional, default true (sub-option 0x81)

  # Catch-all — always keep this last
  - name: Unmatched
    description: "Fallback for unrecognised vendor class"
    match_prefix: ""                       # Empty string = match anything
    controller: ctrl_primary
    protocol: ssh
    ipv4_range: "192.168.36.180-189"
    ipv6_range: "fd00:8b36:f2a9::180-199"
```

### Turning TLS on and off in one edit

Every class setting can be given once in a top-level `defaults:` block. A class inherits anything it does not set itself:

```yaml
defaults:
  controller: ctrl
  protocol: tls
  callhome_port: auto           # -> 4335 (sub-option 0x87)
  ca_ra:
    profile: onefinity_ca
    port: 8080

oru_classes:
  - name: TDDn77
    match_prefix: "o-ran-ru2/FJ/44R14"
    ipv4_range: "192.168.56.100-119"       # class says only what differs

  - name: Unmatched
    match_prefix: ""
    protocol: ssh                          # opts this one class out
    ipv4_range: "192.168.56.180-189"
```

Changing that one `protocol:` line switches the whole lab: every class goes from the full CA/RA chain (`01 03 04 05 06 81 86 87`) to a bare controller IP (`81`), and back. Before, the same change meant editing `protocol`, `callhome_port` and `ca_ra` on every class — and the failure mode was missing one, leaving a single class on the wrong protocol while looking just like its neighbours in the YAML.

Rules, all chosen so the block never surprises you:

| Behaviour | Why |
|---|---|
| A key set on the class always wins | The default is a starting point, not an override |
| `ca_ra:` with no value on a class overrides an inherited block with nothing | Presence is what counts, not truth — this is how one class opts out of CA/RA while staying `tls` |
| `ca_ra` merges one level deep | A class needing only its own port writes `ca_ra: {port: N}` and keeps the inherited profile |
| `ca_ra` is **not** inherited into an `ssh` class | It only takes effect under `tls`; inheriting it would make every SSH class warn about a block it never asked for |
| `defaults:` rejects `name`, `match_prefix`, `ipv4_range`, `ipv6_range` | Those define a class rather than configure it |

Inheritable keys: `controller`, `protocol`, `callhome_port`, `lease_profile`, `ca_ra`, `options`.

**Field reference:**

| Field | Required | Notes |
|-------|----------|-------|
| `name` | Yes | Unique class identifier |
| `match_prefix` | Yes | Vendor-class-identifier prefix. `""` = catch-all |
| `controller` | Yes | Must match a `name` in the `controllers` list |
| `protocol` | Yes | `ssh` or `tls` |
| `callhome_port` | **New in 2.4.0**, no | NETCONF call-home port (sub-option 0x87). An integer, or `auto` for the RFC 8071 port matching `protocol` — SSH 4334, TLS 4335. Omitting it on a `tls` class **warns since 2.6.0**: no 0x87 goes out and the O-RU falls back to its firmware default of 4334 |
| `ipv4_range` | **Optional since 2.2.0** | Omit to disable IPv4 for this class — no v4 class block, no v4 pool |
| `ipv6_range` | **Optional since 2.2.0** | Omit to disable IPv6 for this class. **At least one range must be present** |
| `lease_profile` | No | Name from `lease_profiles` |
| `ca_ra` | No | CA/RA block; requires `profile` and `port`. Ignored unless `protocol: tls` |
| `ca_ra.port` | Yes, inside `ca_ra` | CA/RA server port (sub-option 0x03). An integer for both families, or **since 2.5.0** a mapping `{ipv4: N, ipv6: M}` when the CA is reached on a different port per family |
| `ca_ra.mplane_fqdn` | No | Emits sub-option 0x82 |
| `ca_ra.include_controller_ip` | No | Default `true`; set `false` to omit sub-option 0x81 |
| `options.interface_mtu` | No | Sets DHCP option 26 (MTU), IPv4 only |

**Shared pools.** Two or more classes that declare the *byte-identical* range string share one pool. ISC emits a single pool with one `allow members of` per class:

```
    # Shared pool: ATTn25n66-DC, ATTn25n66-AC
    pool6 {
        allow members of "ATTn25n66-DC";
        allow members of "ATTn25n66-AC";
        range6 fd00:8b36:f2a9::150 fd00:8b36:f2a9::159;
        default-lease-time 140;
        max-lease-time 150;
        preferred-lifetime 140;
    }
```

Kea has no equivalent of multiple `allow members of` on one pool, so the generator emits **one pool entry per member class with the same range**. Overlapping pool definitions are accepted by some Kea versions and rejected by others — run `kea-dhcp6 -t` before relying on a shared range.

#### `subnets` — Network Configuration

```yaml
subnets:
  ipv4:
    - subnet: "192.168.36.0/24"
      gateway: "192.168.36.1"
      dns_servers:
        - "192.168.36.1"
      interface: "ens20.201"       # M-Plane VLAN listening interface

  ipv6:
    - subnet: "fd00:8b36:f2a9::/64"
      dns_servers:
        - "fd00:8b36:f2a9::1"
      interface: "ens20.201"
```

Both `subnets.ipv4` and `subnets.ipv6` are required, even if every class disables one family. `interface` is required on each entry — it populates `INTERFACESv4` / `INTERFACESv6` in the ISC defaults file and `interfaces-config` in the Kea configs. `gateway` and `dns_servers` are optional and are simply omitted from the output when absent.

---

### Vendor Option Encoding

Sub-option codes are the same for both families. Only the header differs: DHCPv4 uses a 1-byte code + 1-byte length, DHCPv6 uses a 2-byte code + 2-byte length.

| Code | Field | Type | Source |
|---|---|---|---|
| `0x01` | CA server IP | address | `ca_ra_profile.ca_server_ipv4` / `ca_server_ipv6` |
| `0x03` | CA port | uint16 | `class.ca_ra.port` — scalar, or per-family `{ipv4, ipv6}` |
| `0x04` | URI path | string | `ca_ra_profile.uri_path` |
| `0x05` | Subject DN | string | `ca_ra_profile.subject_dn` |
| `0x06` | App protocol | string | `ca_ra_profile.app_protocol` |
| `0x81` | NETCONF controller IP | address | `class.controller` |
| `0x82` | M-Plane FQDN | string | `class.ca_ra.mplane_fqdn` |
| `0x86` | Call-home mode | uint8 | Derived from `class.protocol`: `0x01` = TLS, `0x00` = SSH |
| `0x87` | Call-home port | uint16 | `class.callhome_port` (opt-in; `auto` = 4334 for SSH, 4335 for TLS) |

**Simple form** — a class with no `ca_ra` block emits only 0x81, plus 0x86 when `protocol: tls`:

| Protocol | DHCPv4 option 43 | DHCPv6 option 17 |
|----------|-----------------|-----------------|
| `ssh` | `81:04:<IPv4>` | `00:81:00:10:<IPv6>` |
| `tls` | `81:04:<IPv4>:86:01:01` | `00:81:00:10:<IPv6>:00:86:00:01:01` |

Adding `callhome_port` appends 0x87 to whichever chain the class emits — `…:86:01:01:87:02:10:ef` on IPv4, `…:00:86:00:01:01:00:87:00:02:10:ef` on IPv6.

> **Set `callhome_port` whenever you set `protocol: tls`.** Sub-option 0x86 tells the O-RU to use TLS; nothing in the chain tells it *which port* unless 0x87 is present, so it falls back to its firmware default. On the Fujitsu units in the lab that default is 4334 — the SSH call-home port — so the O-RU opens a TLS connection to the SSH listener and call-home never completes. The DHCP lease is fine and the config validates, which makes this look like an O-RU fault rather than a DHCP one. `callhome_port: auto` picks 4335 from `protocol: tls` and removes the question.

**CA/RA form** — a `protocol: tls` class with a `ca_ra` block emits the full chain in code order: 0x01, 0x03, 0x04, 0x05, 0x06, then 0x81 (unless `include_controller_ip: false`), 0x82 (if `mplane_fqdn` set), 0x86, and 0x87 last (if `callhome_port` set).

**Per-family CA/RA port.** `ca_ra.port` is normally one number used for both families:

```yaml
    ca_ra:
      profile: onefinity_ca
      port: 8080
```

Some deployments front the same CMP endpoint on a different port per family. Give `port` a mapping instead:

```yaml
    ca_ra:
      profile: onefinity_ca
      port:
        ipv4: 8081
        ipv6: 8080
```

Sub-option 0x03 then carries 8081 in `dhcpd.conf` / `kea-dhcp4.conf` and 8080 in `dhcpd6.conf` / `kea-dhcp6.conf`. If the mapping omits a family the class actually serves — an `ipv4_range` is present but no `ipv4` port — generation fails rather than falling back, because a silent fallback sends the wrong port to that family and the O-RU's CMP enrolment fails with a config that still validates.

Chains of three or more sub-options are emitted across multiple lines in the ISC configs, one sub-option per line. This is a readability change only — ISC `dhcpd` parses both forms identically and the wire bytes are the same:

```
class "ATTn77" {
    match if substring(option dhcp6.vendor-class, 6, 18) = "o-ran-ru2/FJ/44R14";
    log (info, "Matched ATTn77 class");
    # Controller: att (fd00:8b36:f2a9::24:dc) protocol: tls
    option dhcp6.vendor-opts 53148 00:01:00:10:fd:00:8b:36:f2:a9:00:00:00:00:00:00:00:95:02:40
    :00:03:00:02:1f:9d
    :00:04:00:06:2f:70:6b:69:78:2f
    :00:05:00:2f:2f:4f:55:3d:53:50:4d:2f:4f:3d:31:46:69:6e:69:74:79:2f:43:3d:55:53:2f:43:4e:3d:41:54:54:2d:53:53:4c:2f:4c:3d:57:56:2f:53:54:3d:54:65:78:61:73
    :00:06:00:04:68:74:74:70
    :00:82:00:0c:6d:70:6c:61:6e:65:2e:6c:6f:63:61:6c
    :00:86:00:01:01;
    option dhcp-renewal-time 60;
    option dhcp-rebinding-time 120;
}
```

**Both backends are checked against each other at generation time.** The Kea path describes each sub-option to Kea as a typed `option-def` and lets Kea build the TLVs; the ISC path builds the bytes directly. Before emitting anything, the generator re-encodes the Kea representation to raw bytes and compares it to the ISC bytes for every class and family. A mismatch aborts generation:

```
[ERROR] internal: structured sub-options for class 'ATTn77' (ipv6) re-encode to ... but ISC builders produce ... — generator bug, refusing to emit divergent configs
```

---

### Generated Output Files

| Target | File | Install Path | Purpose |
|--------|------|-------------|---------|
| ISC | `dhcpd.conf` | `/etc/dhcp/dhcpd.conf` | ISC DHCPv4 server config |
| ISC | `dhcpd6.conf` | `/etc/dhcp/dhcpd6.conf` | ISC DHCPv6 server config |
| ISC | `isc-dhcp-server` | `/etc/default/isc-dhcp-server` | Interface binding |
| Kea | `kea-dhcp4.conf` | `/etc/kea/kea-dhcp4.conf` | Kea DHCPv4 config (JSON) |
| Kea | `kea-dhcp6.conf` | `/etc/kea/kea-dhcp6.conf` | Kea DHCPv6 config (JSON) |

Every generated file records the generator version, a timestamp, and the source YAML — as comment lines in the ISC files, and as a `user-context` object in the Kea JSON:

```json
"user-context": {
    "comment": "Generated by oran-dhcp-gen v2.2.3 on 2026-08-21 19:11",
    "source": "oran_dhcp.yaml",
    "warning": "DO NOT EDIT MANUALLY"
}
```

Kea leases are written to `/var/lib/kea/kea-leases4.csv` and `/var/lib/kea/kea-leases6.csv`, and Kea logs to `/var/log/kea/kea-dhcp4.log` and `kea-dhcp6.log` at `INFO` severity.

---

### ISC DHCP vs Kea DHCP — Config Translation

The same `oran_dhcp.yaml` generates both formats. Here is how key concepts map:

| YAML concept | ISC DHCP | Kea DHCP |
|-------------|----------|----------|
| `match_prefix` (v4) | `substring(option vendor-class-identifier, 0, N) = "..."` | `substring(option[60].hex, 0, N) == '...'` |
| `match_prefix` (v6) | `substring(option dhcp6.vendor-class, 6, N) = "..."` | `substring(vendor-class[53148].data[0], 0, N) == '...'` |
| `ipv4_range` | `range A B` inside `pool {}` | `"pool": "A - B"` with `client-class` |
| `ipv6_range` | `range6 A B` inside `pool6 {}` | `"pool": "A - B"` with `client-class` |
| Shared range | one pool, several `allow members of` | one pool entry per class, same range |
| Vendor options | hex byte string on `option vendor-encapsulated-options` / `dhcp6.vendor-opts` | typed `option-def` + `option-data` per sub-option; **Kea** encodes the TLVs |
| DHCPv6 option 17 container | `option dhcp6.vendor-opts <eid> <hex>` | `vendor-opts` option-data carrying the enterprise ID, `always-send: true` |
| `lease_profile` times | `default-lease-time` / `max-lease-time` / `preferred-lifetime` at pool scope | `valid-lifetime` / `max-valid-lifetime` / `preferred-lifetime` on the client class |
| `lease_profile` T1/T2 | `option dhcp-renewal-time` / `dhcp-rebinding-time` in the class block | same two options as class `option-data` (**fixed in 2.4.0**; IPv4 only — see below) |
| Catch-all class | `match if substring(...) = ""` | `not member('A') and not member('B') ...` |
| Omitted `ipv4_range` | class and pool absent from `dhcpd.conf` | class and pool absent from `kea-dhcp4.conf` |
| Config format | Plain text | JSON |
| Lease storage | `/var/lib/dhcp/dhcpd.leases` | `/var/lib/kea/kea-leases4.csv` |

> **Kea DHCPv6 carries no per-class T1/T2.** In DHCPv6 those are fields of the IA_NA, not options, and Kea sets them per subnet with `renew-timer`/`rebind-timer` — there is no client-class equivalent. So a `lease_profile` with `renewal_time`/`rebinding_time` reaches Kea on IPv4 only. The ISC v6 output carries `option dhcp-renewal-time` because the reference lab config did, but those are DHCPv4 options and ISC does not put them on the wire in DHCPv6 either. If you need non-default T1/T2 on IPv6, set them per subnet in Kea by hand.

> **Kea vendor options must be typed, not pre-encoded.** Any binary blob placed in a Kea vendor space is wrapped by Kea in *that sub-option's* own TLV header. Versions 2.2.0–2.2.2 emitted the whole payload under sub-option `0x01` and so put `01 LL 81 04 ...` on the wire instead of a bare `81 04 ...`; O-RUs skipped the unrecognised sub-option and never learned the controller address, while `kea-dhcp4 -t` still reported the config valid. Fixed in 2.2.3.

---

### Deploying with --deploy

`--deploy` writes each generated file to its system path, backing up whatever is already there. `--restart` then restarts the services for the chosen target. Both need root.

```bash
# ISC: generate to a temp dir, back up, install, restart both v4 and v6
sudo oran-dhcp-gen ~/oran_dhcp.yaml --target isc --deploy --restart

# Kea, keeping a copy of the generated files for review
sudo oran-dhcp-gen ~/oran_dhcp.yaml --target kea --outdir /tmp/kea-out/ --deploy

# Everything, both servers
sudo oran-dhcp-gen ~/oran_dhcp.yaml --target all --deploy --restart
```

Backups are named `<file>.bak.YYYYMMDD-HHMMSS`, for example `/etc/dhcp/dhcpd.conf.bak.20260504-143022`. A file that did not exist before is reported as `(new file)` with no backup.

`--restart` runs `systemctl restart` for the services matching `--target`:

| Target | Services restarted |
|---|---|
| `isc` | `isc-dhcp-server`, `isc-dhcp-server6` |
| `kea` | `kea-dhcp4-server`, `kea-dhcp6-server` |
| `all` | all four |

Two safety properties worth knowing:

- `--restart` without `--deploy` is rejected: `[ERROR] --restart requires --deploy to be specified`.
- If any file fails to deploy, the run reports `[WARN] Deploy completed with errors` and **skips the restart**, leaving the running server on its previous config.

`--deploy` does *not* run `dhcpd -t` or `kea-dhcp4 -t` for you. For a change to a live network, prefer generating to a directory, validating, and then deploying — as below.

### Deploying ISC DHCP Manually

```bash
# Generate
oran-dhcp-gen ~/oran_dhcp.yaml --target isc --outdir /tmp/dhcp-out/

# Review changes
diff /tmp/dhcp-out/dhcpd.conf /etc/dhcp/dhcpd.conf
diff /tmp/dhcp-out/dhcpd6.conf /etc/dhcp/dhcpd6.conf

# Validate syntax before installing
sudo dhcpd -t -cf /tmp/dhcp-out/dhcpd.conf
sudo dhcpd -6 -t -cf /tmp/dhcp-out/dhcpd6.conf

# Deploy
sudo cp /tmp/dhcp-out/dhcpd.conf      /etc/dhcp/dhcpd.conf
sudo cp /tmp/dhcp-out/dhcpd6.conf     /etc/dhcp/dhcpd6.conf
sudo cp /tmp/dhcp-out/isc-dhcp-server /etc/default/isc-dhcp-server

# Restart
sudo systemctl restart isc-dhcp-server
sudo systemctl restart isc-dhcp-server6
```

### Deploying Kea DHCP Manually

```bash
# Install Kea if not already present
sudo apt install kea-dhcp4-server kea-dhcp6-server

# Generate
oran-dhcp-gen ~/oran_dhcp.yaml --target kea --outdir /tmp/kea-out/

# Review changes
diff /tmp/kea-out/kea-dhcp4.conf /etc/kea/kea-dhcp4.conf
diff /tmp/kea-out/kea-dhcp6.conf /etc/kea/kea-dhcp6.conf

# Validate syntax before installing
kea-dhcp4 -t /tmp/kea-out/kea-dhcp4.conf
kea-dhcp6 -t /tmp/kea-out/kea-dhcp6.conf

# Deploy
sudo cp /tmp/kea-out/kea-dhcp4.conf /etc/kea/kea-dhcp4.conf
sudo cp /tmp/kea-out/kea-dhcp6.conf /etc/kea/kea-dhcp6.conf

# Restart
sudo systemctl restart kea-dhcp4-server
sudo systemctl restart kea-dhcp6-server
```

---

## dhcp-lease-list

Replaces the original ISC DHCP `dhcp-lease-list` command. Supports both ISC DHCP and Kea DHCP lease files, displaying unified IPv4 and IPv6 lease tables with automatic MAC extraction.

### Quick Start

```bash
# ISC DHCP (default)
dhcp-lease-list

# Kea DHCP
dhcp-lease-list --server kea
```

### CLI Reference

```
dhcp-lease-list [OPTIONS]

Options:
  --server {isc,kea}                  DHCP server type (default: isc)
  --v4-lease FILE                     IPv4 lease file path (overrides default)
  --v6-lease FILE                     IPv6 lease file path (overrides default)
  --all                               Show all leases including expired/free
  --v4-only                           Show IPv4 leases only
  --v6-only                           Show IPv6 leases only
  --state {active,free,expired,       Filter by binding state
           declined,released}
  --version                           Show version and exit
```

**Default lease file paths:**

| Server | IPv4 | IPv6 |
|--------|------|------|
| ISC | `/var/lib/dhcp/dhcpd.leases` | `/var/lib/dhcp/dhcpd6.leases` |
| Kea | `/var/lib/kea/kea-leases4.csv` | `/var/lib/kea/kea-leases6.csv` |

**Examples:**
```bash
# ISC — show active leases only (default)
dhcp-lease-list

# ISC — show all including expired and free
dhcp-lease-list --all

# ISC — IPv6 only
dhcp-lease-list --v6-only

# ISC — filter by state
dhcp-lease-list --state active

# Kea — show active leases
dhcp-lease-list --server kea

# Kea — show all states
dhcp-lease-list --server kea --all

# Kea — filter declined leases
dhcp-lease-list --server kea --state declined

# Custom lease file paths (useful for non-default install paths)
dhcp-lease-list --server isc \
  --v4-lease /var/lib/dhcp/dhcpd.leases \
  --v6-lease /var/lib/dhcp/dhcpd6.leases

dhcp-lease-list --server kea \
  --v4-lease /var/lib/kea/kea-leases4.csv \
  --v6-lease /var/lib/kea/kea-leases6.csv
```

---

### Output Fields

```
=== ISC DHCP Unified Lease List  v1.3.0 ===
Active leases shown. Use --all to include expired/free.

[ DHCPv4 Leases ]  file: /var/lib/dhcp/dhcpd.leases  total: 5  active: 3
IP Address       MAC / DUID          Hostname   State        Expires (UTC)          Vendor Class
------------------------------------------------------------------------------------------------
192.168.36.160   34:fe:9e:3d:af:5c   -          active       2026/03/05 10:20:49    -
192.168.36.170   34:fe:9e:3d:ad:c8   -          active       2026/03/04 07:15:49    -

[ DHCPv6 Leases ]  file: /var/lib/dhcp/dhcpd6.leases  total: 2  active: 2
IP Address             MAC / DUID          Hostname   State        Expires (UTC)          Vendor Class
------------------------------------------------------------------------------------------------------
fd00:8b36:f2a9::168    34:fe:9e:3d:af:5c   -          active       2026/03/04 16:20:20    -
fd00:8b36:f2a9::139    34:fe:9e:3a:a2:ba   oru-db1    active       2026/03/05 04:15:00    -
```

| Field | Description |
|-------|-------------|
| IP Address | Assigned IPv4 or IPv6 address |
| MAC / DUID | MAC address. For ISC DHCPv6, extracted from DUID. For Kea, read directly from hwaddr column |
| Hostname | Client-reported hostname if available |
| State | Color-coded: `active` (green), `free`/`released` (dim), `expired`/`declined` (yellow) |
| Expires (UTC) | Lease expiry time in UTC |
| Vendor Class | O-RU vendor-class-identifier string if present (ISC only) |

---

### ISC DHCP Mode

ISC DHCP stores leases in a text-based format with `lease {}` blocks for IPv4 and `ia-na {}` blocks for IPv6.

**Lease file locations:**
- IPv4: `/var/lib/dhcp/dhcpd.leases`
- IPv6: `/var/lib/dhcp/dhcpd6.leases`

**State values:** `active`, `free`, `expired`

**Deduplication:** ISC DHCP may have multiple entries per IP (active and historical). The parser keeps the most recent active entry per IP, or the most recent entry by expiry time if no active entry exists.

---

### Kea DHCP Mode

Kea stores leases in CSV files. The files are journal-style — new entries are appended rather than updating existing rows, so multiple rows per IP may exist.

**Lease file locations:**
- IPv4: `/var/lib/kea/kea-leases4.csv`
- IPv6: `/var/lib/kea/kea-leases6.csv`

**IPv4 CSV columns:** `address, hwaddr, client_id, valid_lifetime, expire, subnet_id, fqdn_fwd, fqdn_rev, hostname, state, user_context, pool_id`

**IPv6 CSV columns:** `address, duid, valid_lifetime, expire, subnet_id, pref_lifetime, lease_type, iaid, prefix_len, fqdn_fwd, fqdn_rev, hostname, hwaddr, state, user_context, hwtype, hwaddr_source, pool_id`

**State values:**

| Code | Label | Meaning |
|------|-------|---------|
| 0 | `active` | Lease is assigned and valid |
| 1 | `declined` | Client declined the address |
| 2 | `expired` | Lease has expired and been reclaimed |
| 3 | `released` | Client sent DHCP Release |

**Deduplication:** The parser reads all rows and keeps the most recent entry per IP, always preferring `active` over other states.

**Note:** IPv6 prefix delegation entries (`lease_type=2`) are automatically skipped — only address leases (`lease_type=0`) are displayed.

**MAC addresses in Kea:** Kea DHCPv6 stores the hardware address directly in the `hwaddr` column, so no DUID decoding is required.

---

### DHCPv6 DUID MAC Extraction

For ISC DHCP, the DHCPv6 lease file stores client identifiers as binary DUIDs with octal escape sequences. The tool automatically extracts the MAC address from the DUID.

Three DUID types are supported:

| Type | Name | MAC Location |
|------|------|-------------|
| 1 | DUID-LLT (Link-layer + time) | Raw bytes at offset 8 of DUID |
| 2 | DUID-EN (Enterprise number) | ASCII MAC string scanned from byte 4 onwards. O-RAN equipment (enterprise ID 53148) uses this type |
| 3 | DUID-LL (Link-layer only) | Raw bytes at offset 4 of DUID |

The ia-na key in ISC DHCPv6 lease files contains a 4-byte IAID prefix before the DUID, which the parser accounts for automatically.

---

## O-RAN DHCP Background

O-RU M-Plane discovery follows the O-RAN Alliance WG4 M-Plane specification. On power-up, an O-RU sends a DHCP request containing its vendor-class-identifier which identifies the O-RU model and vendor. The DHCP server returns the controller IP address encoded in vendor-specific options so the O-RU knows which NETCONF controller to call home to.

**DHCPv4 uses option 43** (vendor-encapsulated-options) with O-RAN TLV sub-options, each a 1-byte code, 1-byte length, then value:

| Sub-option | Hex | Description |
|------------|-----|-------------|
| Controller IPv4 | `0x81` | 4-byte IPv4 address of O-RU controller |
| Call-home protocol | `0x86` | `0x01` = TLS, `0x00` = SSH |
| Call-home port | `0x87` | 2-byte TCP port — 4334 (SSH) or 4335 (TLS) |

Example option 43 for SSH: `81:04:c0:a8:24:f9`
Example option 43 for TLS: `81:04:c0:a8:24:f9:86:01:01`
Example option 43 for TLS with an explicit port: `81:04:c0:a8:24:f9:86:01:01:87:02:10:ef`

**DHCPv6 uses option 17** (vendor-opts) with O-RAN enterprise ID `53148`. The sub-option header is wider — 2-byte code, 2-byte length:

| Sub-option | Hex | Description |
|------------|-----|-------------|
| Controller IPv6 | `0x0081` | 16-byte IPv6 address of O-RU controller |
| Call-home protocol | `0x0086` | `0x01` = TLS |
| Call-home port | `0x0087` | 2-byte TCP port — 4334 (SSH) or 4335 (TLS) |

Example option 17 for SSH: `00:81:00:10:<16-byte IPv6>`
Example option 17 for TLS: `00:81:00:10:<16-byte IPv6>:00:86:00:01:01`
Example option 17 for TLS with an explicit port: `00:81:00:10:<16-byte IPv6>:00:86:00:01:01:00:87:00:02:10:ef`

After receiving the controller address, the O-RU initiates a NETCONF call-home session:
- SSH: TCP port 4334
- TLS: TCP port 4335

Sub-option `0x87` states that port explicitly. It is optional: without it the O-RU uses its firmware default, which is where a TLS deployment goes wrong — the Fujitsu units default to 4334, so an O-RU told "use TLS" by `0x86` still connects to the SSH call-home listener. Set `callhome_port: auto` on any class you switch to `protocol: tls`.

**Certificate enrolment (CA/RA).** O-RUs that bootstrap over TLS may also need to enrol for a certificate before the NETCONF session can come up. That is carried in the same vendor option as additional sub-options — CA server address (`0x01`), port (`0x03`), URI path (`0x04`), subject DN (`0x05`) and application protocol (`0x06`), optionally with an M-Plane FQDN (`0x82`). See [Vendor Option Encoding](#vendor-option-encoding) for how `ca_ra_profiles` map onto these codes.

**Sub-option order and unknown codes.** An O-RU walks the sub-options in the order received and skips any code it does not recognise. It does not search for a controller address nested inside another sub-option — which is why an incorrectly wrapped payload produces a healthy-looking lease and no call-home at all.

---

## Troubleshooting

**ISC DHCP server not responding:**
```bash
sudo systemctl status isc-dhcp-server isc-dhcp-server6
sudo journalctl -u isc-dhcp-server -f
sudo journalctl -u isc-dhcp-server6 -f
cat /etc/default/isc-dhcp-server
sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf
sudo dhcpd -6 -t -cf /etc/dhcp/dhcpd6.conf
```

**Kea DHCP server not responding:**
```bash
sudo systemctl status kea-dhcp4-server kea-dhcp6-server
sudo journalctl -u kea-dhcp4-server -f
cat /var/log/kea/kea-dhcp4.log
kea-dhcp4 -t /etc/kea/kea-dhcp4.conf
kea-dhcp6 -t /etc/kea/kea-dhcp6.conf
```

**O-RU gets a lease but never calls home over TLS:**

The lease is healthy and both `dhcpd -t` and `kea-dhcp4 -t` pass, so the DHCP side looks finished. Check the wire bytes rather than the config:

```bash
# What the server actually sends. Look at the sub-option chain, not the length.
sudo tcpdump -i <mplane-if> -vvv -s0 'port 67 or port 68' -c 4

# The chain for a TLS class should end 86:01:01:87:02:10:ef
#   86 01 01   -> call-home mode TLS
#   87 02 10ef -> call-home port 4335
grep -A12 'class "<ClassName>"' /etc/dhcp/dhcpd.conf
```

Three things to confirm, in order:

1. **`0x86` is present and `01`.** Absent or `00` means the class is still `protocol: ssh`.
2. **`0x87` is present and `10:ef` (4335).** If it is missing, the O-RU picks its own default — 4334 on the Fujitsu units — and opens a TLS connection to the SSH call-home listener, which never completes a handshake. Set `callhome_port: auto` on the class. If it reads `10:ee` (4334) on a TLS class, that is the same fault stated explicitly.
3. **The CA/RA chain (`0x01`/`0x03`/`0x04`/`0x05`/`0x06`) is present** if the O-RU has no certificate yet. Without it the O-RU has nothing to enrol against and the TLS session fails at certificate validation rather than at connect. Add a `ca_ra_profiles` entry and reference it from the class with `ca_ra:`.

Confirm the controller side is actually listening on the TLS port:

```bash
sudo ss -lntp | grep -E '4334|4335'
```

**O-RU not matching the expected class (ISC):**
```bash
# See what vendor class the O-RU is actually sending
sudo journalctl -u isc-dhcp-server | grep "Vendor Class"

# The generated configs log every match, so you can also confirm which class won
sudo journalctl -u isc-dhcp-server | grep "Matched"
sudo journalctl -u isc-dhcp-server6 | grep "Unmatched Vendor Class String"
```

**O-RU not matching the expected class (Kea):**
```bash
# Enable debug logging temporarily in kea-dhcp4.conf:
# "severity": "DEBUG", "debuglevel": 55
cat /var/log/kea/kea-dhcp4.log | grep -i "class\|vendor\|classify"
```

**O-RU gets a lease but never calls home.** The lease is proof of DHCP working, not of the vendor option being right. Check, in order:

```bash
# 1. Which controller address did this class actually get? Read it back out of
#    the deployed config rather than the YAML.
grep -A3 'class "Gen1TB"' /etc/dhcp/dhcpd6.conf
python3 -c "import json;d=json.load(open('/etc/kea/kea-dhcp6.conf'));
print([c for c in d['Dhcp6']['client-classes'] if c['name']=='Gen1TB'])"

# 2. Confirm the bytes on the wire. Sub-option 0x81 (v4) / 0x0081 (v6) must
#    appear at the TOP level of the vendor option, not nested inside another.
sudo tcpdump -i <mplane-if> -vvv -n port 67 or port 68     # v4
sudo tcpdump -i <mplane-if> -vvv -n port 546 or port 547   # v6

# 3. Is anything listening where you pointed the O-RU?
ss -lntp | grep -E '4334|4335'
```

Three causes account for most of these:

| Symptom | Cause | Fix |
|---|---|---|
| Wire shows `01 LL 81 04 ...` instead of `81 04 ...` | Kea config generated by 2.2.0–2.2.2 | Regenerate with 2.2.3 or later and redeploy |
| Controller address is wrong but plausible | `controllers[].ipv6` disagrees with its own `ipv4` — invisible in the v4 output when two controllers share an IPv4 | Fix the YAML, regenerate, and diff the **v6** output |
| TLS O-RU never enrols | `ca_ra` block present but class is `protocol: ssh` | The generator warns and ignores it; set `protocol: tls` |

**dhcp-lease-list showing no leases:**
```bash
# ISC — check lease files
ls -lh /var/lib/dhcp/dhcpd.leases /var/lib/dhcp/dhcpd6.leases
cat /var/lib/dhcp/dhcpd6.leases

# Kea — check CSV files
ls -lh /var/lib/kea/kea-leases4.csv /var/lib/kea/kea-leases6.csv
head -5 /var/lib/kea/kea-leases4.csv
```

**dhcp-lease-list permission denied:**
```bash
# Lease files are root-readable only — use sudo
sudo dhcp-lease-list
sudo dhcp-lease-list --server kea
```

**Disk full — DHCP stops writing leases:**
```bash
df -h
sudo apt clean && sudo apt autoremove
sudo journalctl --vacuum-size=100M

# Prevent journal growth permanently
sudo mkdir -p /etc/systemd/journald.conf.d/
echo -e "[Journal]\nSystemMaxUse=100M" | \
  sudo tee /etc/systemd/journald.conf.d/size.conf
sudo systemctl restart systemd-journald
```

**Rolling back a bad deploy.** `--deploy` leaves a timestamped backup of every file it replaced:

```bash
ls -t /etc/dhcp/dhcpd.conf.bak.*        # newest first
sudo cp /etc/dhcp/dhcpd.conf.bak.20260504-143022 /etc/dhcp/dhcpd.conf
sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf
sudo systemctl restart isc-dhcp-server
```

**Generator validation errors:**

| Error | Fix |
|-------|-----|
| `references unknown controller: 'ctrl_xyz'` | Check `controller` field matches a `name` in `controllers` list exactly |
| `invalid ipv4_range format: '...~...'` | Use hyphen `-` not tilde. Correct: `192.168.36.100-109` |
| `invalid ipv6_range format` | Correct format: `fd00:8b36:f2a9::100-109` |
| `ipv4_range start > end` | Range endpoints are in the wrong order |
| `must have at least one of ipv4_range or ipv6_range` | A class may disable one family, not both |
| `global.oran_enterprise_id is required` | Ensure all three `global` fields are present |
| `Duplicate oru_class name` | Each class name must be unique |
| `Controller missing required field: 'ipv6'` | Every controller needs `name`, `ipv4` **and** `ipv6` |
| `references undefined lease_profile: 'x'` | The name must exist as a key under `lease_profiles` |
| `ca_ra references undefined profile: 'x'` | The name must exist as a key under `ca_ra_profiles` |
| `ca_ra block missing required field: 'port'` | `profile` and `port` are both required in a class `ca_ra` block |
| `ca_ra_profile 'x' must define at least one of ca_server_ipv4 or ca_server_ipv6` | Add the address for whichever family the referencing classes serve |
| `ca_ra_profile must define ca_server_ipv6 to emit ipv6 sub-options` | A class with an `ipv6_range` references a profile that only has the v4 CA address |
| `subnets.ipv4 entries must include an 'interface' field` | Required to write the interface binding files |
| `internal: structured sub-options ... refusing to emit divergent configs` | Generator bug — the ISC and Kea encoders disagree. Report it; do not work around it |

**Generator warnings** (generation continues):

| Warning | Meaning |
|---|---|
| `has ca_ra block but protocol is 'ssh' — ca_ra will be ignored` | Set `protocol: tls` to use the block |
| `contains classes with different lease_profiles` | A shared pool can carry only one set of timers; the first member's profile wins |
| `has classes with conflicting interface_mtu values` | Same, for MTU; the lowest-sorted value is used |
| `sets 'netconf_mode_byte' explicitly; this field is deprecated in 2.2.1` | Remove it and let the 0x86 byte follow `class.protocol` |

---

## Version History

### oran-dhcp-gen

| Version | Changes |
|---------|---------|
| 2.7.0 | **`--explain`** prints what each class will actually receive — match prefix, pool range, and the option 43 / 17 chain decoded sub-option by sub-option, plus the flat hex — and writes nothing. Flags a `tls` class sending no 0x87 with the port the O-RU will fall back to. Built on the same resolved sub-options the emitters use, and checked against the generated configs by test, so it cannot drift from what is emitted |
| 2.6.0 | **Top-level `defaults:` block** — every class inherits `controller`, `protocol`, `callhome_port`, `lease_profile`, `ca_ra` and `options` unless it sets its own, so switching a lab between SSH and TLS is one edit rather than one per class. A class setting always wins; `ca_ra` merges one level deep and is not inherited into an `ssh` class. Also: a `protocol: tls` class with no `callhome_port` now warns — it is the exact case 0x87 exists to prevent, and both TLS classes in the Lab01 reference were silently in it |
| 2.5.0 | **`ca_ra.port` accepts a per-family mapping** `{ipv4: N, ipv6: M}` for CAs reached on a different port per family; a scalar still means "both families". A mapping missing a family the class serves is rejected, not defaulted. Added `References/isc/Lab01` — a second lab's hand-written ISC configs plus the YAML that reproduces them — and a test that decodes both and requires the generated sub-option chains to match per class per family. Fixed the test helpers, which decoded a commented-out alternative chain when one sat above the live one |
| 2.4.0 | **`callhome_port` on a class emits sub-option `0x87`**, the NETCONF call-home port — an integer or `auto` (SSH 4334, TLS 4335). Previously a class could say "use TLS" via `0x86` but not say which port, so O-RUs fell back to the firmware default of 4334 and TLS call-home never completed. Opt-in: a model that omits it is byte-identical to 2.3.0. Kea DHCPv4 now also emits T1/T2 (options 58/59) from a `lease_profile`, which it had been dropping while ISC emitted them. A `tls_ca:` block on a controller — never an implemented field, but sketched in the Lab4 reference YAML — is now a hard error pointing at `ca_ra_profiles`, and unknown fields warn instead of being silently ignored |
| 2.3.0 | `--no-timestamp` for byte-reproducible output. Malformed or empty YAML now fails with a message rather than a traceback. Repo restructured (`bin/`, `packaging/`, `tests/`, `examples/`, `docs/`); the version is substituted from `__version__` at build time instead of living in five hand-edited places; test suite added |
| 2.2.3 | **Fixed Kea option 43/17 encoding** (regression from 2.2.0). Payload had been emitted as one binary blob under sub-option `0x01`, which Kea wrapped in its own TLV — O-RUs never learned the controller IP although the config validated cleanly. Kea now emits typed `option-def` / `option-data` per O-RAN sub-option and builds the TLVs itself, matching ISC wire bytes. DHCPv6 `vendor-opts` container forced with `always-send`. Added a generation-time cross-check that re-encodes the Kea representation and aborts on any divergence from the ISC bytes. Commas in string sub-option values escaped for Kea. ISC output unchanged |
| 2.2.2 | Multi-line ISC TLV emission — chains of 3+ sub-options render one sub-option per line. Presentation only; wire bytes unchanged |
| 2.2.1 | Sub-option `0x86` derived from `class.protocol` per O-RAN WG4 §6.2.5. `ca_ra_profiles[].netconf_mode_byte` deprecated (still honoured, now warns) |
| 2.2.0 | Added `lease_profiles` and `ca_ra_profiles`. `ipv4_range` / `ipv6_range` became optional per class (at least one required). Shared-range pool emission. Lease times moved to pool scope, where ISC actually applies them |
| 2.1.1 | Fixed Kea 2.4 schema bugs |
| 2.1.0 | Added `--deploy` and `--restart` |
| 2.0.0 | Added Kea DHCP target (`kea-dhcp4.conf`, `kea-dhcp6.conf`). `--target` now accepts `isc`, `kea`, or `all` |
| 1.1.0 | Added `isc-dhcp-server` defaults file generation (`/etc/default/isc-dhcp-server`) |
| 1.0.0 | Initial release — ISC DHCP IPv4 + IPv6 config generation from YAML |

### dhcp-lease-list

| Version | Changes |
|---------|---------|
| 1.3.0 | Added Kea DHCP CSV lease file support. Added `--server {isc,kea}` switch. Extended `--state` with `declined` and `released`. Kea journal-aware deduplication |
| 1.2.1 | Fixed DUID-EN MAC extraction for 2-byte enterprise number (O-RAN equipment) |
| 1.2.0 | Added DUID-EN (type 2) support. Fixed IPv4 active lease dedup priority |
| 1.1.1 | Fixed MAC extraction offset — IAID prefix handling in ia-na keys |
| 1.1.0 | Fixed DHCPv6 binary DUID parsing with octal escape sequences. Added DUID-LLT/LL MAC extraction |
| 1.0.0 | Initial release — unified ISC DHCPv4 + DHCPv6 lease viewer |

---

*O-RAN DHCP Tools · ISC DHCP and Kea DHCP deployment for O-RU M-Plane discovery*
