


HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PROFILE=inline
export CSV="${CSV:-$HERE/../../../datasets/inline.csv}"
exec bash "$HERE/capstone-oracle-grid-common.sh"
