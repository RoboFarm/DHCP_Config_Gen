# O-RAN DHCP Tools — User Guide

**Version:** 4.0.0
**Last Updated:** 2026-03-19
**Packages Covered:** `oran-dhcp-gen` v2.3.0 · `dhcp-oru-toolkit` v2.1.2

> The lease viewer was renamed. `dhcp-lease-list` 1.3.0 became the
> `dhcp-oru-toolkit` package at 2.0.0, which ships `dhcp-lease-list` and
> `dhcp-forensics`, and now lives in its own repository
> (`RoboFarm/oran-dhcp`). Its section below covers the current release.

---

## Table of Contents

1. [Overview](#overview)
2. [Package Summary](#package-summary)
3. [Installation](#installation)
4. [oran-dhcp-gen — Configuration Generator](#oran-dhcp-gen)
   - [Quick Start](#quick-start)
   - [CLI Reference](#cli-reference)
   - [YAML Data Model Reference](#yaml-data-model-reference)
   - [Generated Output Files](#generated-output-files)
   - [ISC DHCP vs Kea DHCP — Config Translation](#isc-dhcp-vs-kea-dhcp--config-translation)
   - [Deploying ISC DHCP](#deploying-isc-dhcp)
   - [Deploying Kea DHCP](#deploying-kea-dhcp)
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

**Configuration management** — a single YAML data model (`oran_dhcp.yaml`) generates all DHCP config files for both ISC DHCP and Kea DHCP. Change a controller IP or add a new O-RU model in one place and regenerate — no manual config editing.

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
# Install config generator (requires python3, python3-yaml)
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

# 3. Generate configs — choose your target
oran-dhcp-gen ~/oran_dhcp.yaml --target isc --outdir /tmp/out/   # ISC DHCP
oran-dhcp-gen ~/oran_dhcp.yaml --target kea --outdir /tmp/out/   # Kea DHCP
oran-dhcp-gen ~/oran_dhcp.yaml --target all --outdir /tmp/out/   # Both at once
```

### CLI Reference

```
oran-dhcp-gen <yaml_file> [OPTIONS]

Arguments:
  yaml_file             Path to oran_dhcp.yaml data model

Options:
  --target {isc,kea,all}   Output target (default: isc)
  --outdir DIR             Output directory (default: a temp dir with --deploy,
                           the current directory otherwise)
  --deploy                 Copy generated configs to their system paths,
                           backing up each existing file to <name>.bak.<stamp>
  --restart                Restart the DHCP service(s) after deploying
                           (requires --deploy)
  --no-timestamp           Omit the generation time from config headers, so
                           output depends only on the input YAML
  --version                Show version and exit
  --help                   Show help
```

`--deploy` writes to `/etc/dhcp/`, `/etc/default/` and `/etc/kea/`, so it needs
`sudo`. Every file it replaces is backed up first with a timestamped suffix.

`--no-timestamp` exists so that generated output can be byte-compared against a
known-good reference. With the timestamp in place, every such diff shows a
spurious header line; without it, an empty diff means the configs are genuinely
identical. The test suite relies on this.

**Examples:**
```bash
# Generate ISC DHCP configs into current directory
oran-dhcp-gen oran_dhcp.yaml

# Generate Kea configs into /tmp/kea-out/
oran-dhcp-gen oran_dhcp.yaml --target kea --outdir /tmp/kea-out/

# Generate all 5 files at once
oran-dhcp-gen oran_dhcp.yaml --target all --outdir /tmp/all-out/

# Validate YAML without deploying (review stdout for errors)
oran-dhcp-gen oran_dhcp.yaml --target isc --outdir /tmp/test/

# Deploy to /etc and restart the service in one step
sudo oran-dhcp-gen oran_dhcp.yaml --target kea --deploy --restart

# Byte-compare against the configs currently deployed
oran-dhcp-gen oran_dhcp.yaml --target kea --outdir /tmp/new/ --no-timestamp
diff /tmp/new/kea-dhcp4.conf /etc/kea/kea-dhcp4.conf
```

---

### YAML Data Model Reference

`oran_dhcp.yaml` is the **single source of truth** — never edit generated files directly.

#### `global` — Global Settings

```yaml
global:
  default_lease_time: 43200      # Lease duration in seconds (12 hours)
  max_lease_time: 86400          # Maximum lease duration (24 hours)
  oran_enterprise_id: 53148      # O-RAN Alliance IANA enterprise ID (do not change)
```

#### `controllers` — O-RU Controller Definitions

Define one or more controllers. Each O-RU class references a controller by name. Multiple controllers allow different O-RU families to point to different management endpoints.

```yaml
controllers:
  - name: ctrl_primary           # Unique name used as reference key
    description: "Primary O-RU controller"
    ipv4: "192.168.36.249"       # Encoded into DHCPv4 option 43 TLV (0x81)
    ipv6: "fd00:8b36:f2a9::24:dc"  # Encoded into DHCPv6 option 17 TLV (0x0081)

  - name: ctrl_att
    description: "ATT-specific controller"
    ipv4: "192.168.36.220"
    ipv6: "fd00:8b36:f2a9::24:dc"

  - name: ctrl_lab
    description: "Lab test controller"
    ipv4: "10.0.0.1"
    ipv6: "fd00:dead:beef::1"
```

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

  # Catch-all — always keep this last
  - name: Unmatched
    description: "Fallback for unrecognised vendor class"
    match_prefix: ""                       # Empty string = match anything
    controller: ctrl_primary
    protocol: ssh
    ipv4_range: "192.168.36.180-189"
    ipv6_range: "fd00:8b36:f2a9::180-199"
```

**Field reference:**

| Field | Required | Notes |
|-------|----------|-------|
| `name` | Yes | Unique class identifier |
| `match_prefix` | Yes | Vendor-class-identifier prefix. `""` = catch-all |
| `controller` | Yes | Must match a `name` in the `controllers` list |
| `protocol` | Yes | `ssh` or `tls` |
| `ipv4_range` | No | Omit to disable IPv4 for this class (since 2.2.0) |
| `ipv6_range` | No | Omit to disable IPv6 for this class (since 2.2.0) |
| `lease_profile` | No | Name of an entry in `lease_profiles` (since 2.2.0) |
| `ca_ra` / `ca_ra_profile` | No | CA/RA bootstrap chain; only takes effect when `protocol: tls` |
| `options.interface_mtu` | No | Sets DHCP option 26 (MTU) |

**Protocol TLV encoding:**

| Protocol | DHCPv4 option 43 | DHCPv6 option 17 |
|----------|-----------------|-----------------|
| `ssh` | `81:04:<IPv4>` | `00:81:00:10:<IPv6>` |
| `tls` | `81:04:<IPv4>:86:01:01` | `00:81:00:10:<IPv6>:00:86:00:01:01` |

#### `lease_profiles` — Reusable Lease Times (since 2.2.0)

Named lease-time sets that classes reference by name, so a change lands in one
place instead of in every class:

```yaml
lease_profiles:
  short:
    default_lease_time: 600
    max_lease_time: 1200
```

A class opts in with `lease_profile: short`. Lease times are emitted at **pool**
scope for ISC — dhcpd ignores them at class scope, which is a common way for a
hand-written config to look right and behave otherwise.

#### `ca_ra_profiles` — Certificate Enrollment Chains (since 2.2.0)

Named CA/RA bootstrap settings for O-RUs that enroll for a certificate before
calling home. Referenced per class as `ca_ra_profile: <name>`, or given inline
as a `ca_ra:` block:

```yaml
ca_ra_profiles:
  att:
    server_ipv6: "fd00:8b36:f2a9::24:dc"
    port: 8091
    path: "/pkix/"
    subject_dn: "..."
    protocol: http
```

These populate O-RAN sub-options `0x01` (CA server IP), `0x03` (port), `0x04`
(URI path), `0x05` (subject DN) and `0x06` (application protocol). **A `ca_ra`
block only takes effect when the class sets `protocol: tls`** — it is silently
irrelevant for `ssh` classes.

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

---

### Generated Output Files

| Target | File | Install Path | Purpose |
|--------|------|-------------|---------|
| ISC | `dhcpd.conf` | `/etc/dhcp/dhcpd.conf` | ISC DHCPv4 server config |
| ISC | `dhcpd6.conf` | `/etc/dhcp/dhcpd6.conf` | ISC DHCPv6 server config |
| ISC | `isc-dhcp-server` | `/etc/default/isc-dhcp-server` | Interface binding |
| Kea | `kea-dhcp4.conf` | `/etc/kea/kea-dhcp4.conf` | Kea DHCPv4 config (JSON) |
| Kea | `kea-dhcp6.conf` | `/etc/kea/kea-dhcp6.conf` | Kea DHCPv6 config (JSON) |

All generated files embed a header comment with the generator version, timestamp, and source YAML filename.

---

### ISC DHCP vs Kea DHCP — Config Translation

The same `oran_dhcp.yaml` generates both formats. Here is how key concepts map:

| YAML concept | ISC DHCP | Kea DHCP |
|-------------|----------|----------|
| `match_prefix` | `substring(vendor-class-identifier, 0, N) = "..."` | `substring(option[60].hex, 0, N) == '...'` (v4) |
| DHCPv6 class match | `substring(dhcp6.vendor-class, 6, N)` | `substring(vendor-class[53148].data[0], 0, N)` |
| `ipv4_range` | `range A B` inside `pool {}` | `"pool": "A - B"` with `client-class` field |
| `ipv6_range` | `range6 A B` inside `pool6 {}` | `"pool": "A - B"` with `client-class` field |
| `protocol: ssh` | `81:04:<IP>` in option 43 | Binary sub-option 129 in vendor space |
| `protocol: tls` | `81:04:<IP>:86:01:01` | Binary sub-option 129 with TLS flag appended |
| Catch-all class | `match if substring(...) = ""` | `not member('A') and not member('B') ...` |
| Config format | Plain text | JSON |
| Lease storage | `/var/lib/dhcp/dhcpd.leases` | `/var/lib/kea/kea-leases4.csv` |

---

### Deploying ISC DHCP

```bash
# Generate
oran-dhcp-gen ~/oran_dhcp.yaml --target isc --outdir /tmp/dhcp-out/

# Review changes
diff /tmp/dhcp-out/dhcpd.conf /etc/dhcp/dhcpd.conf
diff /tmp/dhcp-out/dhcpd6.conf /etc/dhcp/dhcpd6.conf

# Deploy
sudo cp /tmp/dhcp-out/dhcpd.conf      /etc/dhcp/dhcpd.conf
sudo cp /tmp/dhcp-out/dhcpd6.conf     /etc/dhcp/dhcpd6.conf
sudo cp /tmp/dhcp-out/isc-dhcp-server /etc/default/isc-dhcp-server

# Validate syntax
sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf
sudo dhcpd -6 -t -cf /etc/dhcp/dhcpd6.conf

# Restart
sudo systemctl restart isc-dhcp-server
sudo systemctl restart isc-dhcp-server6
```

### Deploying Kea DHCP

```bash
# Install Kea if not already present
sudo apt install kea-dhcp4-server kea-dhcp6-server

# Generate
oran-dhcp-gen ~/oran_dhcp.yaml --target kea --outdir /tmp/kea-out/

# Review changes
diff /tmp/kea-out/kea-dhcp4.conf /etc/kea/kea-dhcp4.conf
diff /tmp/kea-out/kea-dhcp6.conf /etc/kea/kea-dhcp6.conf

# Deploy
sudo cp /tmp/kea-out/kea-dhcp4.conf /etc/kea/kea-dhcp4.conf
sudo cp /tmp/kea-out/kea-dhcp6.conf /etc/kea/kea-dhcp6.conf

# Validate syntax
kea-dhcp4 -t /etc/kea/kea-dhcp4.conf
kea-dhcp6 -t /etc/kea/kea-dhcp6.conf

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

**DHCPv4 uses option 43** (vendor-encapsulated-options) with O-RAN TLV sub-options:

| Sub-option | Hex | Description |
|------------|-----|-------------|
| Controller IPv4 | `0x81` | 4-byte IPv4 address of O-RU controller |
| Call-home protocol | `0x86` | `0x01` = TLS, `0x00` = SSH |

Example option 43 for SSH: `81:04:c0:a8:24:f9`
Example option 43 for TLS: `81:04:c0:a8:24:f9:86:01:01`

**DHCPv6 uses option 17** (vendor-opts) with O-RAN enterprise ID `53148`:

| Sub-option | Hex | Description |
|------------|-----|-------------|
| Controller IPv6 | `0x0081` | 16-byte IPv6 address of O-RU controller |
| Call-home protocol | `0x0086` | `0x01` = TLS |

Example option 17 for SSH: `00:81:00:10:<16-byte IPv6>`
Example option 17 for TLS: `00:81:00:10:<16-byte IPv6>:00:86:00:01:01`

After receiving the controller address, the O-RU initiates a NETCONF call-home session:
- SSH: TCP port 4334
- TLS: TCP port 4335

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

**O-RU not matching the expected class (ISC):**
```bash
# See what vendor class the O-RU is actually sending
sudo journalctl -u isc-dhcp-server | grep "Vendor Class"
```

**O-RU not matching the expected class (Kea):**
```bash
# Enable debug logging temporarily in kea-dhcp4.conf:
# "severity": "DEBUG", "debuglevel": 55
cat /var/log/kea/kea-dhcp4.log | grep -i "class\|vendor\|classify"
```

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

**Generator validation errors:**

| Error | Fix |
|-------|-----|
| `references unknown controller: 'ctrl_xyz'` | Check `controller` field matches a `name` in `controllers` list exactly |
| `invalid ipv4_range format: '...~...'` | Use hyphen `-` not tilde. Correct: `192.168.36.100-109` |
| `invalid ipv6_range format` | Correct format: `fd00:8b36:f2a9::100-109` |
| `global.oran_enterprise_id is required` | Ensure all three `global` fields are present |
| `Duplicate oru_class name` | Each class name must be unique |

---

## Version History

### oran-dhcp-gen

| Version | Changes |
|---------|---------|
| 2.3.0 | `--no-timestamp` for byte-reproducible output. Malformed YAML fails with a message rather than a traceback. Repo restructured; version now substituted from one source at build time; test suite added |
| 2.2.3 | **FIX** Kea option-43/17 was emitted as a binary blob nested under sub-option `0x01`, so Kea re-wrapped it and O-RUs never learned the controller IP. Kea now gets typed per-sub-option data. Configs validated cleanly throughout, so `kea-dhcp4 -t` never flagged it |
| 2.2.2 | Multi-line ISC TLV emission for long bootstrap chains (presentation only; wire bytes unchanged) |
| 2.2.1 | Spec-compliant `0x86` byte, derived automatically from `class.protocol` |
| 2.2.0 | `lease_profiles`, `ca_ra_profiles`, per-class IPv4/IPv6 enable/disable, pool-scoped lease times, `--deploy` / `--restart` |
| 2.0.0 | Added Kea DHCP target (`kea-dhcp4.conf`, `kea-dhcp6.conf`). `--target` now accepts `isc`, `kea`, or `all` |
| 1.1.0 | Added `isc-dhcp-server` defaults file generation (`/etc/default/isc-dhcp-server`) |
| 1.0.0 | Initial release — ISC DHCP IPv4 + IPv6 config generation from YAML |

### dhcp-lease-list / dhcp-oru-toolkit

Now developed in `RoboFarm/oran-dhcp`; see that repository for the current
changelog.

| Version | Changes |
|---------|---------|
| 2.1.2 | Documented reading lease files without sudo (`_kea` group; a `chmod` does not survive Kea's lease-file cleanup) |
| 2.1.1 | **FIX** an unreadable Kea lease file was reported as "not found", because `Path.exists()` raises on Python ≤3.12 and returns False on 3.13+ |
| 2.1.0 | Kea as a first-class server: `--server auto`/`both`, lease path read from the Kea config, LFC generations read, journal replay, MAC recovery from DUID and client-id, UTC timestamps |
| 2.0.0 | Renamed to `dhcp-oru-toolkit`; adds `dhcp-forensics` and `--conflicts` |
| 1.3.0 | Added Kea DHCP CSV lease file support. Added `--server {isc,kea}` switch. Extended `--state` with `declined` and `released`. Kea journal-aware deduplication |
| 1.2.1 | Fixed DUID-EN MAC extraction for 2-byte enterprise number (O-RAN equipment) |
| 1.2.0 | Added DUID-EN (type 2) support. Fixed IPv4 active lease dedup priority |
| 1.1.1 | Fixed MAC extraction offset — IAID prefix handling in ia-na keys |
| 1.1.0 | Fixed DHCPv6 binary DUID parsing with octal escape sequences. Added DUID-LLT/LL MAC extraction |
| 1.0.0 | Initial release — unified ISC DHCPv4 + DHCPv6 lease viewer |

---

*O-RAN DHCP Tools · ISC DHCP and Kea DHCP deployment for O-RU M-Plane discovery*
