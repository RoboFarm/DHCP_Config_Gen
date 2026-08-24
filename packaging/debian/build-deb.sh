#!/bin/bash
# build-deb.sh -- build the oran-dhcp-gen .deb from this checkout.
#
#     bash packaging/debian/build-deb.sh
#
# The version is read from __version__ in bin/oran-dhcp-gen and substituted
# into every file that carries it (control, postinst, man page). That is the
# whole point: before this script the version lived in five hand-edited places
# and had already drifted -- the shipped 2.2.3 man page said 2.2.2, and the
# postinst banner announced "What's new in 2.2.2" under a "v2.2.3 installed"
# header. Bump __version__, add a changelog entry, rebuild; nothing else.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

PKG="oran-dhcp-gen"
SRC="bin/oran-dhcp-gen"
DEB_DIR="packaging/debian"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -f "${SRC}" ]] || die "${SRC} not found; run from a checkout."

# --- Single source of truth --------------------------------------------------
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "${SRC}")"
[[ -n "${VERSION}" ]] || die "could not read __version__ from ${SRC}"

# The changelog must lead with this version, or the package ships a history
# that disagrees with the binary.
CL_VERSION="$(sed -n '1s/^oran-dhcp-gen (\([^)]*\)).*/\1/p' "${DEB_DIR}/changelog")"
[[ "${CL_VERSION}" == "${VERSION}" ]] || die \
    "version mismatch: ${SRC} says ${VERSION}, changelog leads with ${CL_VERSION:-<unparseable>}.
       Add a changelog entry for ${VERSION} before building."

# Man-page date comes from the changelog trailer, so a rebuild of an unchanged
# tree is reproducible rather than stamped with today.
CL_DATE_RAW="$(sed -n '/^ -- /{s/^ -- [^>]*>  //p;q}' "${DEB_DIR}/changelog")"
DATE="$(date -u -d "${CL_DATE_RAW}" +%Y-%m-%d 2>/dev/null || echo "${CL_DATE_RAW}")"

echo ">> Building ${PKG} ${VERSION} (man date ${DATE})"

# --- Stage -------------------------------------------------------------------
STAGE="build/deb/${PKG}"
rm -rf "${STAGE}"
mkdir -p "${STAGE}/DEBIAN" \
         "${STAGE}/usr/local/bin" \
         "${STAGE}/usr/share/${PKG}" \
         "${STAGE}/usr/share/doc/${PKG}" \
         "${STAGE}/usr/share/man/man1"

install -m 0755 "${SRC}"                          "${STAGE}/usr/local/bin/${PKG}"
install -m 0644 examples/oran_dhcp.yaml.example   "${STAGE}/usr/share/${PKG}/oran_dhcp.yaml.example"
install -m 0644 "${DEB_DIR}/copyright"            "${STAGE}/usr/share/doc/${PKG}/copyright"

# control + man page: substitute the version (and date).
sed "s/@VERSION@/${VERSION}/g" "${DEB_DIR}/control" > "${STAGE}/DEBIAN/control"
chmod 0644 "${STAGE}/DEBIAN/control"

sed -e "s/@VERSION@/${VERSION}/g" -e "s/@DATE@/${DATE}/g" "${DEB_DIR}/${PKG}.1" \
    | gzip -9nc > "${STAGE}/usr/share/man/man1/${PKG}.1.gz"
chmod 0644 "${STAGE}/usr/share/man/man1/${PKG}.1.gz"

# postinst: substitute the version, and build the "what's new" banner from the
# top changelog entry so it can never again announce an older release.
WHATSNEW="$(awk '
    NR == 1              { next }                 # skip the "pkg (ver)" line
    /^ -- /              { exit }                 # stop at the trailer
    /^[[:space:]]*\*/    { sub(/^[[:space:]]*\* */, ""); print }
' "${DEB_DIR}/changelog" \
  | awk '{ if (length($0) > 66) { s = substr($0, 1, 66); sub(/[^ ]*$/, "", s); sub(/ +$/, "", s); print s "..." } else print }' \
  | sed 's/[\\"`$]/\\&/g; s/^/echo "  * /; s/$/"/')"

WHATSNEW="${WHATSNEW}" python3 - "${DEB_DIR}/postinst" "${STAGE}/DEBIAN/postinst" "${VERSION}" <<'PY'
import os
import sys
src, dst, version = sys.argv[1], sys.argv[2], sys.argv[3]
whatsnew = os.environ.get("WHATSNEW", "").rstrip("\n")
text = open(src).read().replace("@VERSION@", version).replace("@WHATSNEW@", whatsnew)
open(dst, "w").write(text)
PY
chmod 0755 "${STAGE}/DEBIAN/postinst"

install -m 0755 "${DEB_DIR}/prerm" "${STAGE}/DEBIAN/prerm"
gzip -9nc "${DEB_DIR}/changelog" > "${STAGE}/usr/share/doc/${PKG}/changelog.gz"
chmod 0644 "${STAGE}/usr/share/doc/${PKG}/changelog.gz"

# --- Build -------------------------------------------------------------------
mkdir -p dist
OUT="dist/${PKG}_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "${STAGE}" "${OUT}" >/dev/null

echo ">> Built ${OUT}"
dpkg-deb --info "${OUT}" | sed -n 's/^/   /p' | head -8
