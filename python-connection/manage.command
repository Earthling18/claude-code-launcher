#!/bin/zsh
# Management only; CLI working directories remain owned by the launcher.
base=${0:A:h}
for candidate in python3 "$HOME/.local/bin/python3.12" "$HOME/.local/bin/python3.11"; do
  if "$candidate" -c 'import sys; sys.exit(sys.version_info < (3,11))' 2>/dev/null; then
    "$candidate" "$base/ai-connection.py" web
    result=$?
    if (( result != 0 )); then
      print '连接工具未启动，请检查 Python 和方案配置。按回车关闭。'
      read
    fi
    exit $result
  fi
done
print '未找到 Python 3.11+。安装后重试，或在 CC 启动器高级连接中选择解释器。按回车关闭。'
read
exit 1
