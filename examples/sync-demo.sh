#!/usr/bin/env bash
# sync-config 完整同步範例
set -euo pipefail

SC="python3 $HOME/.claude/skills/sync-config/scripts/sync_config.py"

echo "=========================================="
echo "  sync-config Demo"
echo "=========================================="
echo ""

# 1. 查看目前跨 CLI 狀態
echo "--- Step 1: 查看狀態 ---"
$SC status
echo ""

# 2. 同步 MCP Servers
echo "--- Step 2: 同步 MCP ---"
$SC sync mcp
echo ""

# 3. 同步可攜式 Skills
echo "--- Step 3: 同步 Skills ---"
$SC sync skills
echo ""

# 4. 同步專案指令（如果有 CLAUDE.md）
echo "--- Step 4: 同步專案指令 ---"
$SC sync instructions 2>/dev/null || echo "  ⏭️ 跳過 (無 CLAUDE.md)"
echo ""

# 5. 同步 Custom Agents → Gemini
echo "--- Step 5: 同步 Agents → Gemini ---"
$SC sync agents --target gemini 2>/dev/null || echo "  ⏭️ 跳過 (無 agents)"
echo ""

# 6. 同步 Hooks → Gemini
echo "--- Step 6: 同步 Hooks → Gemini ---"
$SC sync hooks --target gemini
echo ""

# 7. 最終狀態
echo "--- Step 7: 最終狀態 ---"
$SC status
echo ""

echo "=========================================="
echo "  ✅ 同步完成"
echo "=========================================="
