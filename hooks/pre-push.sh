#!/usr/bin/env bash
# effortkit pre-push hook. effortkit renders this file: change the rules in instance.json, not here.
# It protects the owner. Agents never push, and the gate refuses `git push` for them.
#
# On a shared remote it refuses three things:
#   1. More tags than the limit in one push. `--tags` would publish every local tag, and a tag is hard to withdraw.
#   2. A push to a protected branch. Those change only through a merge request.
#   3. A non-fast-forward update. It discards commits that somebody else may already have.
# A local path that exists is a private mirror, for example a backup, so the guard does not apply.
set -u
PROTECTED=(__PROTECTED__)
MAX_TAGS=__MAX_TAGS__
remote_name="${1:-}"; remote_url="${2:-}"
case "$remote_url" in
  /*) [ -e "$remote_url" ] && exit 0 ;;
esac

ZERO=0000000000000000000000000000000000000000
tags=0; protected=""; forced=""
while read -r local_ref local_sha remote_ref remote_sha; do
  [ -n "${local_ref:-}" ] || continue
  case "$local_ref" in refs/tags/*) tags=$((tags + 1)) ;; esac
  for b in "${PROTECTED[@]}"; do
    [ "$remote_ref" = "refs/heads/$b" ] && protected="$b"
  done
  # A missing remote object also counts as forced. git refuses that push anyway, and a fetch is the fix.
  if [ "$local_sha" != "$ZERO" ] && [ "$remote_sha" != "$ZERO" ] \
     && ! git merge-base --is-ancestor "$remote_sha" "$local_sha" 2>/dev/null; then
    forced="$remote_ref"
  fi
done

refuse() {
  if [ "${EFFORTKIT_PUSH_OVERRIDE:-0}" = 1 ]; then
    printf 'pre-push: override used: %s\n' "$1" >&2
    return 0
  fi
  printf '\npre-push REFUSED: %s\n%s\nremote: %s (%s)\nOverride once, on purpose: EFFORTKIT_PUSH_OVERRIDE=1 git push ...\n\n' \
    "$1" "$2" "$remote_name" "$remote_url" >&2
  exit 1
}

[ "$tags" -le "$MAX_TAGS" ] || refuse "this push carries $tags tags" "Push one tag by name instead: git push $remote_name <tag>"
[ -z "$protected" ] || refuse "the destination is the protected branch $protected" "Push a feature branch and open a merge request."
[ -z "$forced" ] || refuse "non-fast-forward update to $forced" "Fetch and rebase. Use the override only when the branch is yours alone."
exit 0
