


HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PROFILE=vfw
export CSV="${CSV:-$HERE/../../../datasets/vfw.csv}"
exec bash "$HERE/capstone-oracle-grid-common.sh"
