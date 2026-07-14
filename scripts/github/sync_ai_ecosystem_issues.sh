#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_MANIFEST="$SCRIPT_DIR/backlog"

MANIFEST_SOURCE="${MANIFEST:-$DEFAULT_MANIFEST}"
TARGET_REPO="${TARGET_REPO:-all}"
ASSIGNEE="${ASSIGNEE:-}"
DRY_RUN="${DRY_RUN:-false}"
UPDATE_EXISTING="${UPDATE_EXISTING:-true}"
REOPEN_CLOSED="${REOPEN_CLOSED:-false}"

usage() {
  cat <<'EOF'
Synchronize the owner-only personal AI ecosystem backlog across five repositories.

This script creates missing labels, one shared milestone per repository, local
epics, and scoped lifecycle issues. Existing issues are reused by roadmap key
or exact title. Their original body is preserved outside a managed alignment
block. The script never closes or deletes issues.

Usage:
  bash scripts/github/sync_ai_ecosystem_issues.sh [options]

Options:
  --repo OWNER/REPO   Sync one repository instead of all five.
  --manifest PATH     Use another manifest JSON file or manifest directory.
  --assignee USER     Assign created/reused issues, e.g. Dyu20705 or @me.
  --dry-run           Validate and print the planned mutations only.
  -h, --help          Show this help.

Environment equivalents:
  TARGET_REPO=all
  MANIFEST=path/to/manifest.json-or-directory
  ASSIGNEE=@me
  DRY_RUN=true
  UPDATE_EXISTING=true
  REOPEN_CLOSED=false

Requirements:
  - jq 1.6+
  - GitHub CLI (`gh`) authenticated with issue and label write access
    (not required for mutation-free dry-run)

Examples:
  DRY_RUN=true bash scripts/github/sync_ai_ecosystem_issues.sh
  bash scripts/github/sync_ai_ecosystem_issues.sh --repo Dyu20705/chat-assistant --dry-run
  ASSIGNEE=@me bash scripts/github/sync_ai_ecosystem_issues.sh
EOF
}

while (($#)); do
  case "$1" in
    --repo)
      TARGET_REPO="${2:?--repo requires OWNER/REPO}"
      shift 2
      ;;
    --manifest)
      MANIFEST_SOURCE="${2:?--manifest requires a path}"
      shift 2
      ;;
    --assignee)
      ASSIGNEE="${2:?--assignee requires a username}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'error: unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

log() {
  printf '%s\n' "$*" >&2
}

die() {
  log "error: $*"
  exit 1
}

command -v jq >/dev/null 2>&1 || die "jq is required"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

resolve_manifest() {
  local source="$1"
  if [[ -d "$source" ]]; then
    local common="$source/common.json"
    [[ -r "$common" ]] || die "manifest directory is missing common.json: $source"
    local -a parts=()
    while IFS= read -r part; do
      parts+=("$part")
    done < <(find "$source" -maxdepth 1 -type f -name '*.json' ! -name 'common.json' -print | sort)
    ((${#parts[@]} > 0)) || die "manifest directory has no repository JSON files: $source"
    jq -s '
      .[0] as $common
      | $common + {
          repositories: (
            .[1:]
            | map({(.repository): {epic_key: .epic_key, issues: .issues}})
            | add
          )
        }
    ' "$common" "${parts[@]}" >"$TMP_DIR/manifest.json"
    printf '%s\n' "$TMP_DIR/manifest.json"
    return
  fi

  [[ -r "$source" ]] || die "manifest is not readable: $source"
  printf '%s\n' "$source"
}

MANIFEST="$(resolve_manifest "$MANIFEST_SOURCE")"

jq -e '
  .schema_version == 1
  and (.milestone.title | type == "string" and length > 0)
  and (.labels | type == "array" and length > 0)
  and (.repositories | type == "object" and length > 0)
  and ([.repositories[] | .issues[] | .key] | length > 0)
' "$MANIFEST" >/dev/null || die "manifest schema validation failed"

jq -e '
  all(
    .repositories | to_entries[];
    (.value.epic_key as $epic
      | ([.value.issues[].key] | index($epic)) != null
      and ([.value.issues[].key] | length == (unique | length)))
  )
' "$MANIFEST" >/dev/null || die "each repository must have a unique issue key set and a valid epic_key"

if [[ "$TARGET_REPO" != all ]]; then
  jq -e --arg repo "$TARGET_REPO" '.repositories[$repo] != null' "$MANIFEST" >/dev/null \
    || die "repository is not present in manifest: $TARGET_REPO"
fi

if [[ "$DRY_RUN" != true ]]; then
  command -v gh >/dev/null 2>&1 || die "gh is required outside dry-run"
  gh auth status --hostname github.com >/dev/null
fi

MILESTONE_TITLE="$(jq -r '.milestone.title' "$MANIFEST")"
MANAGED_START='<!-- managed-by:ai-ecosystem-backlog -->'
MANAGED_END='<!-- /managed-by:ai-ecosystem-backlog -->'

repository_list() {
  if [[ "$TARGET_REPO" == all ]]; then
    jq -r '.repositories | keys[]' "$MANIFEST"
  else
    printf '%s\n' "$TARGET_REPO"
  fi
}

validate_repository() {
  local repo="$1"
  if [[ "$DRY_RUN" == true ]]; then
    log "[dry-run] repository: $repo"
  else
    gh repo view "$repo" --json nameWithOwner >/dev/null
  fi
}

ensure_labels() {
  local repo="$1"
  jq -c '.labels[]' "$MANIFEST" | while IFS= read -r label; do
    local name color description
    name="$(jq -r '.name' <<<"$label")"
    color="$(jq -r '.color' <<<"$label")"
    description="$(jq -r '.description' <<<"$label")"
    if [[ "$DRY_RUN" == true ]]; then
      log "[dry-run] label $repo: $name"
    else
      gh label create "$name" \
        --repo "$repo" \
        --color "$color" \
        --description "$description" \
        --force >/dev/null
    fi
  done
}

ensure_milestone() {
  local repo="$1"
  if [[ "$DRY_RUN" == true ]]; then
    log "[dry-run] milestone $repo: $MILESTONE_TITLE"
    printf '0\n'
    return
  fi

  local existing
  existing="$(
    gh api --paginate "repos/$repo/milestones?state=all&per_page=100" \
      | jq -r --arg title "$MILESTONE_TITLE" '[.[] | select(.title == $title) | .number][0] // empty'
  )"
  if [[ -n "$existing" ]]; then
    printf '%s\n' "$existing"
    return
  fi

  local description state
  description="$(jq -r '.milestone.description' "$MANIFEST")"
  state="$(jq -r '.milestone.state // "open"' "$MANIFEST")"
  gh api "repos/$repo/milestones" \
    --method POST \
    -f title="$MILESTONE_TITLE" \
    -f description="$description" \
    -f state="$state" \
    --jq '.number'
}

list_issues() {
  local repo="$1" output="$2"
  gh issue list \
    --repo "$repo" \
    --state all \
    --limit 1000 \
    --json number,title,body,url,state >"$output"
}

find_existing_issue() {
  local issue_json="$1" issues_file="$2"
  local key title matches_json
  key="$(jq -r '.key' <<<"$issue_json")"
  title="$(jq -r '.title' <<<"$issue_json")"
  matches_json="$(jq -c --arg title "$title" '[ $title ] + (.match_titles // [])' <<<"$issue_json")"

  jq -c \
    --arg marker "<!-- roadmap-key:$key -->" \
    --argjson titles "$matches_json" '
      ([.[] | select((.body // "") | contains($marker))][0])
      // ([.[] | select(.title as $t | $titles | index($t))][0])
      // empty
    ' "$issues_file"
}

strip_managed_block() {
  awk -v start="$MANAGED_START" -v end="$MANAGED_END" '
    $0 == start { skipping=1; next }
    $0 == end   { skipping=0; next }
    !skipping  { print }
  '
}

build_managed_body() {
  local issue_json="$1" existing_body="$2" extra_markdown="${3:-}"
  local key desired_body cleaned
  key="$(jq -r '.key' <<<"$issue_json")"
  desired_body="$(jq -r '.body' <<<"$issue_json")"
  cleaned="$(printf '%s' "$existing_body" | strip_managed_block)"

  {
    if [[ -n "${cleaned//[[:space:]]/}" ]]; then
      printf '%s\n\n' "$cleaned"
    fi
    printf '%s\n' "$MANAGED_START"
    printf '<!-- roadmap-key:%s -->\n\n' "$key"
    printf '%s\n' "$desired_body"
    if [[ -n "$extra_markdown" ]]; then
      printf '\n%s\n' "$extra_markdown"
    fi
    printf '%s\n' "$MANAGED_END"
  }
}

issue_labels_args() {
  local issue_json="$1"
  jq -r '.labels[]' <<<"$issue_json"
}

create_or_update_issue() {
  local repo="$1" issue_json="$2" milestone_number="$3" issues_file="$4" extra_markdown="${5:-}"
  local key title existing existing_body body_file url number state
  key="$(jq -r '.key' <<<"$issue_json")"
  title="$(jq -r '.title' <<<"$issue_json")"
  existing=""

  if [[ "$DRY_RUN" != true ]]; then
    existing="$(find_existing_issue "$issue_json" "$issues_file")"
  fi

  if [[ -z "$existing" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
      log "[dry-run] create $repo: $key — $title"
      jq -cn \
        --arg repository "$repo" \
        --arg key "$key" \
        --arg title "$title" \
        --arg url "dry-run://$repo/$key" \
        '{repository:$repository,key:$key,title:$title,url:$url,action:"create"}'
      return
    fi

    body_file="$TMP_DIR/${key//[^A-Za-z0-9_.-]/_}.md"
    build_managed_body "$issue_json" "" "$extra_markdown" >"$body_file"

    local -a args=(issue create --repo "$repo" --title "$title" --body-file "$body_file")
    while IFS= read -r label; do
      args+=(--label "$label")
    done < <(issue_labels_args "$issue_json")
    args+=(--milestone "$MILESTONE_TITLE")
    [[ -n "$ASSIGNEE" ]] && args+=(--assignee "$ASSIGNEE")

    url="$(gh "${args[@]}")"
    log "created $repo: $key -> $url"

    list_issues "$repo" "$issues_file"

    jq -cn \
      --arg repository "$repo" \
      --arg key "$key" \
      --arg title "$title" \
      --arg url "$url" \
      '{repository:$repository,key:$key,title:$title,url:$url,action:"create"}'
    return
  fi

  number="$(jq -r '.number' <<<"$existing")"
  url="$(jq -r '.url' <<<"$existing")"
  state="$(jq -r '.state' <<<"$existing")"
  existing_body="$(jq -r '.body // ""' <<<"$existing")"

  if [[ "$UPDATE_EXISTING" != true ]]; then
    log "reused without edit $repo: $key -> $url"
    jq -cn \
      --arg repository "$repo" \
      --arg key "$key" \
      --arg title "$title" \
      --arg url "$url" \
      '{repository:$repository,key:$key,title:$title,url:$url,action:"reuse"}'
    return
  fi

  body_file="$TMP_DIR/${key//[^A-Za-z0-9_.-]/_}.md"
  build_managed_body "$issue_json" "$existing_body" "$extra_markdown" >"$body_file"

  local -a edit_args=(issue edit "$number" --repo "$repo" --title "$title" --body-file "$body_file" --milestone "$MILESTONE_TITLE")
  while IFS= read -r label; do
    edit_args+=(--add-label "$label")
  done < <(issue_labels_args "$issue_json")
  [[ -n "$ASSIGNEE" ]] && edit_args+=(--add-assignee "$ASSIGNEE")
  gh "${edit_args[@]}" >/dev/null

  if [[ "$state" == CLOSED && "$REOPEN_CLOSED" == true ]]; then
    gh issue reopen "$number" --repo "$repo" >/dev/null
  fi

  log "updated $repo: $key -> $url"
  list_issues "$repo" "$issues_file"

  jq -cn \
    --arg repository "$repo" \
    --arg key "$key" \
    --arg title "$title" \
    --arg url "$url" \
    '{repository:$repository,key:$key,title:$title,url:$url,action:"update"}'
}

make_local_checklist() {
  local results_file="$1"
  jq -r '
    "## Managed child issue checklist\n\n" +
    (map("- [ ] [" + .title + "](" + .url + ") `"+ .key +"`") | join("\n"))
  ' "$results_file"
}

sync_repository() {
  local repo="$1"
  local repo_slug="${repo//\//_}"
  local issues_file="$TMP_DIR/${repo_slug}_issues.json"
  local results_ndjson="$TMP_DIR/${repo_slug}_results.ndjson"
  local results_json="$TMP_DIR/${repo_slug}_results.json"
  local milestone_number epic_key epic_issue epic_result checklist

  validate_repository "$repo"
  ensure_labels "$repo"
  milestone_number="$(ensure_milestone "$repo")"
  : >"$results_ndjson"

  if [[ "$DRY_RUN" == true ]]; then
    printf '[]\n' >"$issues_file"
  else
    list_issues "$repo" "$issues_file"
  fi

  epic_key="$(jq -r --arg repo "$repo" '.repositories[$repo].epic_key' "$MANIFEST")"

  jq -c --arg repo "$repo" --arg epic "$epic_key" '
    .repositories[$repo].issues[] | select(.key != $epic)
  ' "$MANIFEST" | while IFS= read -r issue_json; do
    create_or_update_issue "$repo" "$issue_json" "$milestone_number" "$issues_file" \
      | tee -a "$results_ndjson" >/dev/null
  done

  jq -s '.' "$results_ndjson" >"$results_json"
  checklist="$(make_local_checklist "$results_json")"
  epic_issue="$(jq -c --arg repo "$repo" --arg epic "$epic_key" '
    .repositories[$repo].issues[] | select(.key == $epic)
  ' "$MANIFEST")"
  epic_result="$(
    create_or_update_issue "$repo" "$epic_issue" "$milestone_number" "$issues_file" "$checklist"
  )"

  jq -n \
    --arg repository "$repo" \
    --argjson epic "$epic_result" \
    --argjson children "$(cat "$results_json")" \
    '{repository:$repository,epic:$epic,children:$children}' \
    >"$TMP_DIR/${repo_slug}_summary.json"

  printf '%s\n' "$TMP_DIR/${repo_slug}_summary.json"
}

update_global_epic_links() {
  local all_summary="$1"
  [[ "$TARGET_REPO" == all ]] || return 0

  local gateway_repo="Dyu20705/chat-assistant"
  local gateway_summary
  gateway_summary="$(jq -c --arg repo "$gateway_repo" '.[] | select(.repository == $repo)' "$all_summary")"
  [[ -n "$gateway_summary" ]] || return 0

  local extra
  extra="$(jq -r '
    "## Related repository epics\n\n" +
    (map("- [ ] [" + .epic.title + "](" + .epic.url + ") — `" + .repository + "`") | join("\n"))
  ' "$all_summary")"

  if [[ "$DRY_RUN" == true ]]; then
    log "[dry-run] update cross-repository epic links in $gateway_repo"
    return
  fi

  local issues_file="$TMP_DIR/global_gateway_issues.json"
  list_issues "$gateway_repo" "$issues_file"

  local epic_key epic_issue existing existing_body number body_file
  epic_key="$(jq -r --arg repo "$gateway_repo" '.repositories[$repo].epic_key' "$MANIFEST")"
  epic_issue="$(jq -c --arg repo "$gateway_repo" --arg epic "$epic_key" '
    .repositories[$repo].issues[] | select(.key == $epic)
  ' "$MANIFEST")"
  existing="$(find_existing_issue "$epic_issue" "$issues_file")"
  [[ -n "$existing" ]] || die "global epic was not found after synchronization"

  existing_body="$(jq -r '.body // ""' <<<"$existing")"
  number="$(jq -r '.number' <<<"$existing")"
  body_file="$TMP_DIR/global_epic.md"

  local gateway_children
  gateway_children="$(jq -r '
    "## Managed child issue checklist\n\n" +
    (.children | map("- [ ] [" + .title + "](" + .url + ") `"+ .key +"`") | join("\n"))
  ' <<<"$gateway_summary")"

  build_managed_body "$epic_issue" "$existing_body" "$gateway_children"$'\n\n'"$extra" >"$body_file"
  gh issue edit "$number" --repo "$gateway_repo" --body-file "$body_file" >/dev/null
  log "updated cross-repository epic links: $(jq -r '.url' <<<"$existing")"
}

main() {
  local summary_files=()
  while IFS= read -r repo; do
    summary_files+=("$(sync_repository "$repo")")
  done < <(repository_list)

  local all_summary="$TMP_DIR/all_summary.json"
  jq -s '.' "${summary_files[@]}" >"$all_summary"
  update_global_epic_links "$all_summary"

  jq -n \
    --arg manifest "$MANIFEST" \
    --arg target "$TARGET_REPO" \
    --argjson dry_run "$DRY_RUN" \
    --argjson repositories "$(cat "$all_summary")" \
    '{
      manifest:$manifest,
      target:$target,
      dry_run:$dry_run,
      repositories:$repositories,
      totals:{
        repositories:($repositories|length),
        epics:($repositories|length),
        child_issues:([$repositories[].children[]]|length),
        creates:([$repositories[] | .epic, .children[] | select(.action=="create")]|length),
        updates:([$repositories[] | .epic, .children[] | select(.action=="update")]|length),
        reuses:([$repositories[] | .epic, .children[] | select(.action=="reuse")]|length)
      }
    }'
}

main
