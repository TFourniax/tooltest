#!/bin/bash
H="$1"; REQ="$2"; last=""
while true; do
  rev=$(gh api repos/TFourniax/tooltest/pulls/128/reviews --paginate --jq '[.[] | select(.commit_id=="'"$H"'" and .user.login!="TFourniax") | "\(.id):\(.state)"] | join(",")' 2>/dev/null)
  newc=$(gh api "repos/TFourniax/tooltest/pulls/128/comments?per_page=100" --paginate --jq '[.[] | select(.original_commit_id=="'"$H"'" and .user.login!="TFourniax" and .in_reply_to_id==null) | .id] | join(",")' 2>/dev/null)
  react=$(gh api repos/TFourniax/tooltest/issues/comments/$REQ/reactions --jq '[.[] | select(.user.login!="TFourniax") | .content] | join(",")' 2>/dev/null)
  ci=$(gh api "repos/TFourniax/tooltest/commits/$H/check-runs?per_page=100" --jq '"\(.total_count) " + ([.check_runs[] | "\(.status)/\(.conclusion)"] | group_by(.) | map("\(.[0])x\(length)") | join(","))' 2>/dev/null)
  cur="reviews=[$rev] newFindings=[$newc] reactions=[$react] ci=[$ci]"
  [ "$cur" != "$last" ] && echo "$cur" && last="$cur"
  if [ -n "$rev" ] && echo "$ci" | grep -q '^27 ' && ! echo "$ci" | grep -qE 'in_progress|queued|null'; then echo "DONE"; break; fi
  sleep 60
done
