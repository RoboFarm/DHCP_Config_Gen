# TLS Call-Home Bring-Up — Findings, Issues and Resolutions

**Scope:** everything found and fixed between the question *"why doesn't the generated
Kea config do TLS call-home?"* (2026-08-24) and a Fujitsu 44R14 radio completing
DHCP → CMPv2 enrolment → NETCONF call-home over TLS on Lab04 (2026-08-26).
Covers oran-dhcp-gen 2.4.0 through 2.9.0, the reference data that shipped with them,
and two failures that turned out to live outside DHCP entirely.

**End state:** the full bring-up path works on Lab04, every byte the generator emits is
verified against production traffic and against an independent implementation, and
turning TLS on or off for a whole lab is one line of YAML.

```
DHCPv6 option 17          CMPv2 enrolment            NETCONF call-home
(O-RAN 53148, TLS)   →    http://[CA]:8080/pkix/  →  TLS :4335 (mutual)
byte-verified             ir→ip→certConf→pkiconf     radio ⇄ oru-manager
```

The three goals this work served, and where each landed:

1. **Kea supports call-home over TLS, same as ISC.** It largely did already — the real
   gaps were elsewhere (see issues 1–4) — and both backends are now cross-checked at
   generation time and verified byte-identical on the wire.
2. **`oran_dhcp.yaml` expresses it all, and enabling/disabling is simple.** One
   `protocol:` line in a `defaults:` block switches a whole lab (issue 6).
3. **The tool is simple and comprehensive.** One generic YAML produces all five config
   files for both servers with no per-backend intervention, validates itself, and
   `--explain` shows exactly what any radio will be told (issue 7).

---

## Issue catalog

| # | Layer | Issue | Fixed in |
|---|---|---|---|
| 1 | generator | No way to emit `0x87` (call-home port); TLS radios fell back to the SSH port | 2.4.0 |
| 2 | generator | Kea DHCPv4 silently dropped a `lease_profile`'s T1/T2 | 2.4.0 |
| 3 | data model | `tls_ca:` was a silent no-op that looked like the TLS switch | 2.4.0 |
| 4 | generator | CA/RA port could not differ per address family | 2.5.0 |
| 5 | tests | Decode helpers read commented-out chains instead of the live one | 2.5.0 |
| 6 | data model | Enabling TLS took one edit per class; missing one was the failure mode | 2.6.0 |
| 7 | usability | No way to see what a class sends short of a packet capture | 2.7.0 |
| 8 | generator | No `0x02` (CA/RA FQDN); address-only profile could emit a chain with no CA at all | 2.8.0 |
| 9 | generator | Malformed CA address produced a raw traceback | 2.8.1 |
| 10 | reference data | Three of five values recovered from the stale `tls_ca:` sketch were wrong | 2.8.2–2.8.3 |
| 11 | process | Two claims written as "confirmed" that were not | 2.8.3, 2.8.6 |
| 12 | generator | Single-family (e.g. IPv6-only) deployments were impossible to express | 2.9.0 |
| 13 | CA (orucara) | Enrolment loop: issuing CA cert missing from the CMP response chain | oru-cara.yaml |
| 14 | oru-manager | Call-home TLS is mutual; the manager had no identity cert/key | provisioning |

Issues 1–12 are guarded by tests in `tests/run_tests.py` (48 tests; 13 mutations each
verified to fail the suite). Issues 13–14 are outside this repo; their full record is
in the `References/kea/Lab4/oran_dhcp-tls.yaml` header and below.

---

## Part 1 — Bytes the generator could not emit

### 1. Sub-option `0x87` — NETCONF call-home port *(2.4.0)*

**Symptom.** A class could say *use TLS* (`0x86 = 0x01`) but not *which port*. Fujitsu
firmware defaults to 4334 — the **SSH** call-home port — so the radio opened a TLS
session against the SSH listener and call-home never completed. The lease looked
healthy, `dhcpd -t` and `kea-dhcp4 -t` passed, and the whole thing read as a radio
fault.

**Fix.** `callhome_port: auto` (→ 4335 for `tls`, 4334 for `ssh`) or an explicit
integer, emitted as `0x87` (uint16). Deliberately **opt-in**: a model that omits it is
byte-identical to pre-2.4.0 output, which is what made the upgrade safe. Since 2.6.0 a
`tls` class with no `callhome_port` warns, and setting 4334 on a `tls` class warns too.

### 2. Kea DHCPv4 dropped T1/T2 *(2.4.0)*

A class on a `lease_profile` got options 58/59 in the ISC class block but nothing in
the Kea config — Kea has no per-client-class `renew-timer`/`rebind-timer` — so the two
backends renewed on different schedules, precisely for the short bring-up profiles TLS
enrolment classes use. Now emitted as class `option-data`. DHCPv6 needs nothing:
T1/T2 are IA_NA fields there.

### 4. Per-family CA/RA port *(2.5.0)*

Lab01 fronts one CMP endpoint on a different port per family (v4 8081 / v6 8080, and
8083/8082 for the second class). `ca_ra.port` was a scalar applied to both families,
so v6 clients would have been handed the v4 port. It now also accepts
`port: {ipv4: N, ipv6: M}`; a mapping that omits a family the class serves is a hard
error, never a fallback. Given the dual-stack rule (below), the `ipv6` entry is the
one the radio acts on.

### 8. Sub-option `0x02` — CA/RA server FQDN *(2.8.0)*

`ca_server_fqdn` reaches the CA by name, one value for both families. Adding it closed
a real hole: an **address-only profile must cover every family its classes serve** —
before, an IPv4-only profile on a dual-stack class emitted a v6 CA/RA chain containing
no CA address at all.

> **`0x02` remains the one mapping with no observed example anywhere** — not in either
> lab's hand-written configs, not in the srsllsc1 capture. It is inferred from the gap
> in the `0x01`–`0x06` run and from `0x82` being the named alternative to `0x81`.
> Confirm against O-RAN.WG4.MP.0 clause 6.2.5 before relying on it. Nothing shipped
> depends on it.

### 9, 12. Validation hardening *(2.8.1, 2.9.0)*

A malformed CA address used to surface as an `AddressValueError` traceback from inside
a TLV builder; `validate()` now checks every address with a message naming the field.
2.9.0 made single-family deployments expressible (srsllsc1 runs an IPv6-only M-plane):
`subnets` needs one family rather than both, a controller needs an address only for
the families its classes serve, and the unserved family's files are not written. Two
new hard errors close the gaps that opens — a class serving a family its controller
has no address for (the chain would carry no `0x81`), and a range in a family with no
subnet (it would be silently dropped).

---

## Part 2 — A model that made TLS tedious and easy to get wrong

### 3. `tls_ca:` — the silent no-op *(2.4.0)*

Never an implemented field, but the Lab4 reference YAML shipped a commented-out
`tls_ca:` block on its controller, so uncommenting it *looked like* the way to turn on
TLS bootstrap — and silently produced a payload with no CA/RA sub-options at all. Now
a hard error pointing at `ca_ra_profiles`. Unknown fields elsewhere warn instead of
vanishing. (Deployment later proved the block's *contents* stale too — issue 10.)

### 6. `defaults:` — one edit, not one per class *(2.6.0)*

Enabling TLS meant editing `protocol`, `callhome_port` and `ca_ra` on every class, and
the failure mode was missing one. A top-level `defaults:` block now supplies any
per-class setting (`controller`, `protocol`, `callhome_port`, `lease_profile`,
`ca_ra`, `options`) to classes that do not set their own. Switching a lab between SSH
and TLS is the one `protocol:` line; the catch-all class overrides back to `ssh` so an
unrecognised radio is never pointed at the CA. Merge rules chosen so the block cannot
surprise: a class setting always wins, `ca_ra` merges one level deep and is not
inherited into an `ssh` class, and `defaults:` rejects identity fields.

### 7. `--explain` *(2.7.0)*

`dhcpd.conf` carries a hex chain and `kea-dhcp4.conf` typed `option-data`; neither
reads as *"this radio will call home to X on port Y"*. `--explain` decodes the payload
per class per family, ends with the flat hex for diffing against `tcpdump`, and flags
what a byte dump cannot: a `tls` class sending no `0x87`, a `tls` class with no
`ca_ra`. It renders the same resolved values the emitters consume — a test decodes
both and requires them equal — so it cannot drift from what is generated. It predicted
the 148-byte v6 chain later captured on the wire, to the byte.

---

## Part 3 — Reference data and the discipline of "confirmed"

### 10. The stale `tls_ca:` values *(corrected 2.8.2–2.8.3)*

The Lab4 TLS model's CA/RA profile was initially recovered from that commented-out
`tls_ca:` sketch. Deployment proved three of its five values wrong:

| value | recovered from the sketch | actually on the wire |
|---|---|---|
| CA address | `::95:240` | the controller host itself (`192.168.44.6` / `fd00:8b36:f2a9::2c:6`) |
| `0x03` port | 8091 | **8080** |
| `0x05` subject DN | `/OU=SPM/…/CN=ATT-SSL/…` | **`/CN=1FinityLab Root CA/OU=WV Lab/O=1Finity/L=Richardson/ST=Texas/C=US`** |

`/pkix/` and `http` survived, later confirmed directly: a GET to
`http://[fd00:8b36:f2a9::2c:6]:8080/pkix/` answers `405 CMP requires POST`, which only
that path and scheme produce.

### 11. Two overclaims, both caught and walked back

Recorded deliberately, because both are the same failure class this tool exists to
prevent:

- **2.8.2** wrote the CMP port as *"confirmed against the running CMP endpoint"* on
  the strength of a report that it had been checked. The capture showed it had been
  checked and **corrected** (8091 → 8080). Fixed in 2.8.3.
- **2.8.5** described `subject_dn` as confirmed because it "matches what's on the
  wire" — which only proves the generator emits what the model says, not that the
  model is right. Walked back in 2.8.6.

**Rule that came out of this: a value is "confirmed" only when it traces to something
decoded — a capture, a certificate, a probe response — never to wording about one.**
A related trap: a byte-compare against an empty capture reports success. Check the
capture's size before diffing it.

---

## Part 4 — Independent verification: the srsllsc1 capture *(2.9.0)*

`References/srsllsc1/` records the DHCPv6 option 17 chain a **second stack in the same
lab** puts on the wire — captured by the radio itself (scapy decode in its `dhcp_b.py`
log), in a run where CMPv2 completed in ten seconds and TLS call-home came up. That
DHCP server was not generated by this tool and was configured by nobody involved with
it, which is what makes it evidence of a different kind: every other test compares the
generator to itself, to a hand-written config, or to a reading of the spec.

The generator reproduces the 142-byte chain **byte for byte**
(`test_generator_reproduces_srsllsc1_observed_chain`), settling on the DHCPv6 side:
the 2-byte/2-byte TLV framing, `0x01` as a bare 16-byte address, `0x03` as uint16
big-endian, `0x04` with both slashes, `0x05` as one string in OpenSSL slash form,
`0x06` as the ASCII protocol name, and `0x81`/`0x86` alongside the CA/RA run at the
same level.

It also **retired a wrong theory**: srsllsc1 advertises the identical 69-byte
`subject_dn` a Lab04 radio was looping on, and its radio enrolled without complaint —
so a DN mismatch was not the loop's cause, which redirected the investigation to the
CMP exchange itself (Part 5).

Sub-option coverage after this capture: **seven of ten confirmed on the wire against
an independent implementation** (`0x01 0x03 0x04 0x05 0x06 0x81 0x86`); `0x82`/`0x87`
verified against working configs and corroborating notes; `0x02` inferred (see issue
8). The full audit table lives in the user guide under *"Sub-option coverage and its
basis"*.

---

## Part 5 — Beyond DHCP: the enrolment loop *(CA side)*

**Symptom.** After deployment the radio enrolled against the Lab04 CA (`orucara`, a
Python CMPv2 responder) every ~7 seconds forever — a fresh certificate and transaction
ID each time, no error anywhere. The radio sat at *"TLS mode detected, waiting for
CMPV2 to complete"*.

**Investigation.** The exchange is CMP over plain HTTP on 8080, so a 25-second
`tcpdump` on `br-mplane` captured three full cycles in the clear. A purpose-built
decoder (pcap → TCP reassembly → HTTP → DER/CMP) showed every cycle was
`ir` → `ip` (status **accepted**, certificate issued) and then **no `certConf` ever
sent back** — the radio was rejecting the response, silently (Fujitsu's client drops
the connection and retries; it reports nothing).

The response's own certificate list contained the defect. The server sent
`extraCerts = [mplane.lab, oru-cara Sub-CA, 1FinityLab Root CA]` and
`caPubs = [Sub-CA, Root]` — but both chains the radio must validate are signed by
**`1FinityLab Issuing CA`, which was in neither list**:

```
protection signer:   mplane.lab      ← 1FinityLab Issuing CA ← 1FinityLab Root CA
issued certificate:  radio ← Sub-CA  ← 1FinityLab Issuing CA ← 1FinityLab Root CA
                                            ▲ MISSING
```

**Proof, from the capture alone.** `openssl verify` with exactly the certs the server
sent reproduces the radio's failure — `error 20: unable to get local issuer
certificate` at depth 1 — and flips both chains to `OK` once `issuingca.pem` is added.
SKI/AKI arithmetic agrees (the Sub-CA's authority key `93:2D:38:4A…` matched no
delivered certificate; it is the Issuing CA's subject key). The CMP protection
signature was verified cryptographically against `mplane.lab`'s RSA key. Notably, the
DHCP `0x05` DN matches the delivered Root's subject RDN for RDN — the trust anchor was
named correctly and delivered; the chain simply could not reach it.

**Fix.** One line in `oru-cara.yaml`:

```yaml
chain: [/opt/cmp/pki/subca.pem, /opt/cmp/pki/issuingca.pem, /opt/cmp/pki/root.pem]
```

— a trap the config file's own comment had warned about, two lines above the
misconfigured value. Confirmed live: the first `confirmed serial` orucara has ever
logged, **62 ms** after issuance, and the loop stopped.

**Also observed in the capture** (all harmless): the radio's clock ran ~37 s behind
the server (orucara backdates `notBefore` by an hour, so no impact); the issued
certificate re-certifies the radio's IDevID EC key; the radio signs with ECDSA while
the server protects with RSA (legal — each side uses its own key); the `ir` carries
the full Fujitsu factory chain (IDevID ← Factory Sub CA3 ← Factory Root CA), which is
how orucara authenticates the radio via its `Fujitsu_Factory_Root.pem` trust anchor.

---

## Part 6 — Beyond DHCP: call-home is mutual TLS *(manager side)*

With enrolment fixed, one provisioning step still stood before a completed call-home:
**NETCONF call-home over TLS authenticates both directions.** The radio presents its
freshly-enrolled certificate, and the manager must present one back — which the radio
validates against the operator CA it received in `caPubs` (the very chain Part 5
completed). oru-manager had no identity certificate or key. With a cert/key from the
1Finity hierarchy provisioned to it, the radio's TLS call-home to port 4335 completed
and the path was closed end to end.

*Provisioning checklist that falls out of Parts 5–6, for the next lab:* the CMP
responder's chain must include **every intermediate** between its issuing key and the
root the radios trust; the manager needs its **own cert/key** from that hierarchy; the
DHCP `0x05` DN should be the **root's subject** in OpenSSL slash form.

---

## Domain rules established along the way

- **A dual-stack radio calls home over IPv6.** Option 17 is the operative payload;
  the v6 CA address, controller and `ca_ra.port` are the values that matter; verifying
  only a DHCPv4 capture proves nothing about the path in use. Confirmed by the radio
  writing the v6 values to its `dhcp_scan_file.json`.
- Call-home ports: SSH **4334**, TLS **4335** (RFC 8071). `0x86`: `00`/absent = SSH,
  `01` = TLS. Without `0x87`, Fujitsu firmware defaults to 4334.
- `0x05` carries the CA hierarchy root's subject DN, as one string in OpenSSL slash
  form — not DER, not comma-separated.
- A working CMP enrolment is four messages (`ir → ip → certConf → pkiconf`); a CA log
  that shows only issuance, repeating, means the client is rejecting the responses.

## How everything was verified

A ladder, each rung independent of the one below:

1. **Golden files** — byte-stable output for four reference inputs.
2. **Real servers** — ISC dhcpd 4.4.3 and Kea 2.4.1 run on the generated configs and
   probed with a crafted `DHCPDISCOVER`; both backends byte-identical on every model.
3. **Generation-time cross-check** — the Kea typed representation re-encoded and
   compared against the ISC bytes for every class and family; mismatch aborts.
4. **Production** — Lab04's wire capture, byte-identical on both families; the radio's
   own decode agrees sub-option for sub-option.
5. **Independent implementation** — srsllsc1's chain, byte-identical.
6. **Mutation testing** — 13 deliberate regressions, each fails the suite.

## Open items

- **`0x02`** — confirm the CA/RA-FQDN mapping against O-RAN.WG4.MP.0 §6.2.5. The one
  unverified claim left; nothing shipped depends on it.
- **`dhcp_b.py:1399`** in the O-RU image passes a scapy `NetworkInterface` object to
  `subprocess` where a string is required, so its interface-clear step silently fails.
  Worth a ticket against the radio image.
- The oru-manager cert/key provisioning (Part 6) is manual today; worth folding into
  the oru-manager deployment procedure.

## Timeline

| When (2026) | Version | What |
|---|---|---|
| Aug 24 evening | 2.4.0 | `0x87`; Kea T1/T2; `tls_ca` rejection |
| Aug 25 early | 2.5.0 | Per-family CA/RA port; Lab01 reference; decoder anchoring |
| Aug 25 | 2.6.0–2.7.0 | `defaults:` one-edit toggle; `--explain` |
| Aug 25 | 2.8.0–2.8.1 | `0x02`; CA-reachability check; Lab4 TLS model; address validation |
| Aug 25 | 2.8.2–2.8.5 | Deployed on Lab04; wire capture; three stale values corrected; byte-identical on both families |
| Aug 25 late | 2.8.6 | `subject_dn` overclaim walked back |
| Aug 26 | 2.9.0 | srsllsc1 independent verification; single-family support |
| Aug 26 | — | CMP loop root-caused (missing issuing CA) and fixed; first `certConf` ever |
| Aug 26 | — | oru-manager cert/key provisioned; **TLS call-home established on 4335** |

All of it merged to `main` in PR #2 (merge commit `e38cb29`).
