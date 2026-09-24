S="$1"; CORE=/c/Dev/DiffWitness-Claude/tooltest; export PYTHONIOENCODING=utf-8
for spec in f144d2b:3 80d3ef7:12 ef0b937:14 998acd4:20,21 fd24c18:22,23,24 c1a6948:26 6d35bc2:32,33 855a850:46 d861ec8:49,50 289ea90:53; do
  c=${spec%%:*}; f=${spec#*:}; wt="$S/wt-$c"; v="$S/venv-$c"
  git -C "$CORE" worktree add --detach "$wt" "$c" >/dev/null 2>&1
  py -3.12 -m venv "$v" && "$v/Scripts/python" -m pip install -q "setuptools>=77" wheel 2>/dev/null
  (cd "$wt" && "$v/Scripts/python" -m pip wheel -q . --no-deps --no-build-isolation --wheel-dir "$S/wheel-$c" 2>/dev/null)
  "$v/Scripts/python" -m pip install -q --no-deps "$S/wheel-$c/"*.whl 2>/dev/null
  PATH="$v/Scripts:$PATH" "$v/Scripts/python" "$S/replay_findings.py" "$CORE" "$f" > "$S/replay-at-$c.log" 2>&1
  echo "$c findings=$f :: $(grep -E '^[0-9]+ [0-9]+ (PASS|FAIL)' "$S/replay-at-$c.log" | awk '{print $1"="$3}' | tr '\n' ' ')"
done
