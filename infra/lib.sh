# Shared helpers for infra scripts. Source this file; do not run it.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The only project Shadow City may use (AGENTS.md). Guards against a wrong .env.
EXPECTED_PROJECT="ebc-cloud-dev-03"

load_env() {
  local env_file="$REPO_ROOT/.env"
  [[ -f "$env_file" ]] || env_file="$REPO_ROOT/.env.example"
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
  : "${GCP_PROJECT_ID:?GCP_PROJECT_ID is not set in $env_file}"
  : "${GCP_REGION:?GCP_REGION is not set in $env_file}"
  : "${FIRESTORE_DATABASE:?FIRESTORE_DATABASE is not set in $env_file}"
  if [[ "$GCP_PROJECT_ID" != "$EXPECTED_PROJECT" ]]; then
    echo "Refusing to run: GCP_PROJECT_ID is '$GCP_PROJECT_ID', expected '$EXPECTED_PROJECT'." >&2
    exit 1
  fi
}

confirm() {
  [[ "${ASSUME_YES:-false}" == "true" ]] && return 0
  read -r -p "$1 [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
}
