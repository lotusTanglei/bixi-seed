#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
cd "$PROJECT_ROOT"

mkdir -p "$PROJECT_ROOT/data" "$LOG_DIR"
if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
  cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
  echo "已创建 .env，请按需修改配置。"
fi

python_command=""
if command -v python3 >/dev/null 2>&1; then
  python_command="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  python_command="$(command -v python)"
else
  echo "未找到 Python 3，请先安装 Python 3.12 或更高版本。" >&2
  exit 1
fi

if ! "$python_command" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "Python 版本过低，请安装 Python 3.12 或更高版本。" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  "$python_command" -m venv "$PROJECT_ROOT/.venv"
fi
require_environment
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r "$PROJECT_ROOT/requirements-dev.txt"

if grep -qE 'generate-during-setup|replace-this-with-a-long-random-value' "$PROJECT_ROOT/.env"; then
  generated_secret="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  sed -i.bak -E "s/generate-during-setup|replace-this-with-a-long-random-value/${generated_secret}/" "$PROJECT_ROOT/.env"
  rm -f "$PROJECT_ROOT/.env.bak"
  echo "已为当前环境生成 Django Secret Key。"
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "未找到 npm，请先安装 Node.js LTS。" >&2
  exit 1
fi
cd "$PROJECT_ROOT/frontend"
npm install
npm run build
cd "$PROJECT_ROOT"
"$PYTHON_BIN" manage.py migrate --noinput
"$PYTHON_BIN" manage.py collectstatic --noinput

if [[ -t 0 ]]; then
  printf "管理员账号（直接回车跳过）: "
  read -r admin_username
  if [[ -n "$admin_username" ]]; then
    printf "管理员密码（至少 10 个字符）: "
    read -r -s admin_password
    printf "\n"
    printf "管理员联系方式（手机号、微信号等）: "
    read -r admin_contact
    BIXI_ADMIN_USERNAME="$admin_username" BIXI_ADMIN_PASSWORD="$admin_password" BIXI_ADMIN_CONTACT="$admin_contact" "$PYTHON_BIN" manage.py bootstrap_admin
  fi
else
  echo "当前不是交互终端，已跳过管理员创建；之后可运行 bootstrap_admin。"
fi
echo "基础环境已经准备完成，可以运行 ./start.sh 启动服务。"
