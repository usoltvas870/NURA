#!/bin/bash
# Claude Code status line script
input=$(cat)

# Working directory
cwd=$(echo "$input" | jq -r '.cwd // empty')
[ -z "$cwd" ] && cwd=$(pwd)

# Shorten home directory to ~
home="$HOME"
short_cwd="${cwd/#$home/~}"

# Model display name
model=$(echo "$input" | jq -r '.model.display_name // empty')

# Context usage
used_pct=$(echo "$input" | jq -r '.context_window.used_percentage // empty')

# Total tokens in context
total_tokens=$(echo "$input" | jq -r '(.context_window.total_input_tokens // 0) + (.context_window.total_output_tokens // 0)')

# Git branch (skip optional locks to avoid conflicts)
branch=$(git -C "$cwd" symbolic-ref --short HEAD 2>/dev/null)

# Rate limits (Claude.ai subscription)
five_hour=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')

# Build status line parts
parts=()

# Directory (blue)
parts+=("$(printf '\033[34m%s\033[0m' "$short_cwd")")

# Git branch (yellow)
[ -n "$branch" ] && parts+=("$(printf '\033[33m(%s)\033[0m' "$branch")")

# Model (cyan)
[ -n "$model" ] && parts+=("$(printf '\033[36m%s\033[0m' "$model")")

# Context usage with color coding
if [ -n "$used_pct" ]; then
  used_int=$(printf '%.0f' "$used_pct")
  if [ "$used_int" -ge 80 ]; then
    parts+=("$(printf '\033[31mctx:%s%%\033[0m' "$used_int")")
  elif [ "$used_int" -ge 50 ]; then
    parts+=("$(printf '\033[33mctx:%s%%\033[0m' "$used_int")")
  else
    parts+=("$(printf '\033[32mctx:%s%%\033[0m' "$used_int")")
  fi
elif [ -n "$total_tokens" ] && [ "$total_tokens" -gt 0 ]; then
  parts+=("$(printf '\033[32mtokens:%s\033[0m' "$total_tokens")")
fi

# Rate limit 5-hour (magenta) — only show when available
[ -n "$five_hour" ] && parts+=("$(printf '\033[35m5h:%.0f%%\033[0m' "$five_hour")")

# Join parts with separator
printf '%s' "${parts[0]}"
for ((i=1; i<${#parts[@]}; i++)); do
  printf ' | %s' "${parts[$i]}"
done
printf '\n'
