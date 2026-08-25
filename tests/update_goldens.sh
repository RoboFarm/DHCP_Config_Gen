#!/bin/bash
# Regenerate the golden files after an intended change to generator output.
#
#     bash tests/update_goldens.sh && git diff tests/golden/
#
# ALWAYS read the resulting diff before committing: these files are the only
# thing standing between a wire-format regression and a lab. A bump of
# __version__ alone changes the header line of every file, which is expected.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

gen() {  # <name> <yaml>
    mkdir -p "tests/golden/$1"
    python3 bin/oran-dhcp-gen "$2" --target all --outdir "tests/golden/$1/" \
        --no-timestamp >/dev/null
    echo "   updated tests/golden/$1/"
}

gen lab4    References/kea/Lab4/oran_dhcp.yaml
gen example examples/oran_dhcp.yaml.example
gen lab01   References/isc/Lab01/oran_dhcp.yaml
echo ">> Done. Review with: git diff tests/golden/"
