#!/usr/bin/env bash
#
# delete_target.sh — completely remove a marketpulse target from Databricks.
#
# Deletes, for the named target:
#   1. The Unity Catalog catalog + everything in it — every schema, table, and Volume
#      (incl. the raw source Volumes and the reference/crosswalks Volume) — via
#      `databricks catalogs delete --force` (cascades).
#   2. All bundle-deployed JOBS for the target, plus the deployed workspace files, via
#      `databricks bundle destroy`.
#
# DELIBERATELY NOT deleted:
#   - The `marketpulse` secret scope (holds FRED_API_KEY). Secret scopes are WORKSPACE-level
#     and shared across ALL targets — deleting it would break the other targets. Remove it by
#     hand only when decommissioning the whole workspace:  databricks secrets delete-scope marketpulse
#
# This is IRREVERSIBLE. The script shows a plan and requires you to type the catalog name to
# confirm. Pass -y / --yes to skip the prompt (and auto-approve the bundle destroy).
#
# Usage:
#   ./delete_target.sh <target> [-y]
#     <target>   one of: user | dev | staging | prod
#     -y|--yes   non-interactive: skip the typed confirmation and auto-approve
#
# Catalog override (rare):  CATALOG=some_catalog ./delete_target.sh <target>
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="$SCRIPT_DIR/databricks_code"

# ---- args ------------------------------------------------------------------------------------
TARGET="${1:-}"
ASSUME_YES=0
for arg in "${@:2}"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [[ -z "$TARGET" ]]; then
  echo "Usage: ./delete_target.sh <user|dev|staging|prod> [-y]" >&2
  exit 2
fi

# ---- target -> catalog (mirrors databricks_code/databricks.yml) ------------------------------
case "$TARGET" in
  user|dev) DEFAULT_CATALOG="dev_marketpulse" ;;
  staging)  DEFAULT_CATALOG="staging_marketpulse" ;;
  prod)     DEFAULT_CATALOG="marketpulse" ;;
  *) echo "Invalid target '$TARGET'. Expected: user | dev | staging | prod" >&2; exit 2 ;;
esac
CATALOG="${CATALOG:-$DEFAULT_CATALOG}"

if [[ ! -d "$BUNDLE_DIR" ]]; then
  echo "Cannot find bundle dir: $BUNDLE_DIR" >&2
  exit 1
fi

# ---- plan ------------------------------------------------------------------------------------
cat <<PLAN

============================================================
  DELETE TARGET  —  IRREVERSIBLE
============================================================
  Target          : $TARGET
  Catalog         : $CATALOG   (DROP --force, cascades all schemas/tables/volumes)
  Bundle jobs+files: destroy all resources for target '$TARGET'
  Preserved       : secret scope 'marketpulse' (workspace-level, shared)
============================================================
PLAN

if [[ "$TARGET" == "prod" ]]; then
  echo "  ⚠  This is the PRODUCTION target."
  echo
fi

# ---- confirm ---------------------------------------------------------------------------------
if [[ "$ASSUME_YES" -ne 1 ]]; then
  printf "Type the catalog name (%s) to confirm deletion: " "$CATALOG"
  read -r REPLY
  if [[ "$REPLY" != "$CATALOG" ]]; then
    echo "Confirmation did not match ('$REPLY' != '$CATALOG'). Aborted — nothing deleted."
    exit 1
  fi
fi

# ---- 1. drop the catalog (and all schemas/tables/volumes inside it) --------------------------
echo
echo "[1/2] Dropping catalog '$CATALOG' (cascade) ..."
if databricks catalogs get "$CATALOG" >/dev/null 2>&1; then
  databricks catalogs delete "$CATALOG" --force
  echo "      catalog '$CATALOG' deleted."
else
  echo "      catalog '$CATALOG' not found — skipping (already gone)."
fi

# ---- 2. destroy the bundle's jobs + deployed workspace files ---------------------------------
echo
echo "[2/2] Destroying bundle resources (jobs + files) for target '$TARGET' ..."
cd "$BUNDLE_DIR"
if [[ "$ASSUME_YES" -eq 1 ]]; then
  databricks bundle destroy -t "$TARGET" --auto-approve
else
  # bundle destroy runs its own interactive approval here.
  databricks bundle destroy -t "$TARGET"
fi

echo
echo "Done. Target '$TARGET' (catalog '$CATALOG' + bundle jobs/files) removed from Databricks."
echo "Note: the 'marketpulse' secret scope was left intact (shared across targets)."
