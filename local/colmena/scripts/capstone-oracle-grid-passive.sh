


HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PROFILE=passive
export CSV="${CSV:-$HERE/../../../datasets/passive.csv}"
exec bash "$HERE/capstone-oracle-grid-common.sh"
