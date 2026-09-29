#!/usr/bin/env bash
# Turn an agent's structured judgement into a build verdict.
#
# The agent decides *what is risky*. This script decides *what fails the build*.
# Keeping those separate means the policy can be tightened or relaxed without
# touching the prompt, and the prompt can be improved without silently changing
# which pull requests get blocked.
#
# Usage: gate.sh <structured-output.json>
# Env:
#   FAIL_ON   lowest severity that fails the build   (default: high)
#   ON_ERROR  fail | neutral — what to do when the agent did not produce a
#             usable verdict at all                   (default: fail)

set -euo pipefail

FILE="${1:?usage: gate.sh <structured-output.json>}"
FAIL_ON="${FAIL_ON:-high}"
ON_ERROR="${ON_ERROR:-fail}"

rank() {
  case "$1" in
    none) echo 0 ;; low) echo 1 ;; medium) echo 2 ;;
    high) echo 3 ;; critical) echo 4 ;; *) echo -1 ;;
  esac
}

summary() { if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then cat >> "$GITHUB_STEP_SUMMARY"; else cat; fi; }

die_unusable() {
  echo "::error::agent produced no usable verdict: $1"
  { echo "## Migration safety — inconclusive"; echo; echo "**$1**"; echo;
    echo "The gate could not read a verdict, so it did not evaluate this pull request."; } | summary
  # An analysis gate that silently passes when the analyser is down is not a
  # gate. Teams with high PR volume may prefer ON_ERROR=neutral plus an alert.
  [ "$ON_ERROR" = "neutral" ] && { echo "ON_ERROR=neutral — not blocking."; exit 0; }
  exit 1
}

[ -s "$FILE" ] || die_unusable "no output file at $FILE"
jq -e . "$FILE" >/dev/null 2>&1 || die_unusable "output is not valid JSON"

VERDICT=$(jq -r '.verdict // empty' "$FILE")
SEVERITY=$(jq -r '.severity // empty' "$FILE")
SUMMARY=$(jq -r '.summary // ""' "$FILE")
COUNT=$(jq -r '.findings | length' "$FILE")

case "$VERDICT" in pass|fail) ;; *) die_unusable "verdict was '${VERDICT:-<missing>}'" ;; esac
[ "$(rank "$SEVERITY")" -ge 0 ] || die_unusable "severity was '${SEVERITY:-<missing>}'"

# The build fails on the highest severity actually present in the findings, not
# on the agent's own verdict field — a model that says "pass" while reporting a
# critical finding should still block, and vice versa.
TOP="none"
if [ "$COUNT" -gt 0 ]; then
  TOP=$(jq -r '[.findings[].severity] | map({none:0,low:1,medium:2,high:3,critical:4}[.])
               | max as $m | ["none","low","medium","high","critical"][$m]' "$FILE")
fi

{
  echo "## Migration safety"
  echo
  echo "| | |"; echo "|---|---|"
  echo "| Agent verdict | \`$VERDICT\` |"
  echo "| Highest finding | \`$TOP\` |"
  echo "| Policy | fail at \`$FAIL_ON\` or above |"
  echo "| Findings | $COUNT |"
  echo
  [ -n "$SUMMARY" ] && { echo "$SUMMARY"; echo; }
  if [ "$COUNT" -gt 0 ]; then
    echo "| Severity | Risk | File | Why |"
    echo "|---|---|---|---|"
    jq -r '.findings[] | "| `\(.severity)` | `\(.risk)` | `\(.file)\(if .line then ":\(.line)" else "" end)` | \(.why | gsub("\\|";"\\\\|")) |"' "$FILE"
    echo
    jq -r '.findings[] | select(.mitigation) | "- **\(.file)** — \(.mitigation)"' "$FILE"
  fi
} | summary

# Annotate in the diff so a reviewer sees it on the changed line.
jq -r '.findings[] | select(.severity == "high" or .severity == "critical")
       | "::error file=\(.file)\(if .line then ",line=\(.line)" else "" end),title=\(.risk)::\(.why)"' "$FILE"
jq -r '.findings[] | select(.severity == "medium" or .severity == "low")
       | "::warning file=\(.file)\(if .line then ",line=\(.line)" else "" end),title=\(.risk)::\(.why)"' "$FILE"

if [ "$(rank "$TOP")" -ge "$(rank "$FAIL_ON")" ]; then
  echo "FAIL: highest finding '$TOP' meets the '$FAIL_ON' threshold."
  exit 1
fi
echo "PASS: highest finding '$TOP' is below the '$FAIL_ON' threshold."
exit 0
