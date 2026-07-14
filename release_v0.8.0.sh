#!/usr/bin/env bash
# digitallife v0.8.0 发布脚本（在你自己的 shell 运行，使用你的 git/gh 凭据）
# 用法： bash /root/DigitalLife/release_v0.8.0.sh
# 安全：版本不一致或 tracked 文件含真实密钥时会在推送前中止。

set -euo pipefail
cd /root/DigitalLife
PY=.venv/bin/python3
TAG="v0.8.0"

echo "========== 1. 清理临时文件 =========="
rm -f verify.sh verify_ghost.sh verify_final.sh verify_m.sh deploy_frontend.sh \
      dev_storage_root/_ghost_e2e.py dev_storage_root/_search_probe.py 2>/dev/null || true
rm -rf docs/audit 2>/dev/null || true
echo "done"

echo "========== 2. 版本一致性检查 =========="
"$PY" scripts/check_version_consistency.py

echo "========== 3. 密钥扫描（tracked 文件不得含真实 key）=========="
if git ls-files -z | xargs -0 grep -lE "tvly-dev-|BSAH281FnqsbZAzhS8gF4fMnBrJMo6e|6a33bd3e8991c100010cf0e7:|2465dc7cac4f8e0d1abe159f0d" 2>/dev/null; then
  echo "❌ 上面这些 tracked 文件含真实密钥，已中止。请处理后重跑。"
  exit 1
fi
if git ls-files | grep -q "dev_storage_root/"; then
  echo "❌ dev_storage_root（含你的凭据）被 git 跟踪，已中止。"
  exit 1
fi
echo "✅ 未发现真实密钥进入版本库"

echo "========== 4. 变更概览 =========="
git status --short
echo "分支: $(git branch --show-current) | 远端: $(git remote get-url origin)"

echo "========== 5. 提交（不署名 AI，符合仓库约定）=========="
git add -A
git commit -m "release: digitallife v0.8.0

- web search/fetch fix with multi-provider multi-key rotation and failover
- LLM provider presets with preferred + fallback model chain
- Ghost blog config and full (untruncated) conclusion auto-publish
- dossier history viewing and start-new-topic entry
- per-department professional skills
- security hardening (SSRF/CSRF/SDK approval, configurable via setting.security)
- concurrency and data-consistency fixes"

echo "========== 6. 推送到 origin =========="
git push origin HEAD

echo "========== 7. 打 tag 并推送（触发 CI 构建 macOS + Docker，并创建 Draft Release）=========="
git tag "$TAG"
git push origin "$TAG"

echo "========== 8. CI 状态 =========="
gh run list --limit 5 2>/dev/null || echo "（gh 未配置，可到 GitHub Actions 页面查看）"

echo ""
echo "========== 发布已触发 =========="
echo "CI 约 5-10 分钟内产出："
echo "  - macOS arm64 / x86_64 签名安装包（Draft Release）"
echo "  - Docker 多架构镜像（amd64 / arm64，Ubuntu 部署用）"
echo "完成后： gh release view $TAG  # 确认产物齐全后再发布 Draft，并可用 RELEASE_NOTES_v0.8.0.md 更新 Release Note"
