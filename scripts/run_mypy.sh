#!/usr/bin/env bash

if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
  PIP_CMD=(".venv/bin/python" "-m" "pip")
else
  PYTHON_BIN="python"
  PIP_CMD=("$PYTHON_BIN" "-m" "pip")
fi

cmd="$PYTHON_BIN -m mypy --config-file=\"mypy.ini\""

eval "$cmd"
mypy_ret_code=$?

printf "mypy_ret_code: %s\n" "$mypy_ret_code"

if [ "$mypy_ret_code" != 0 ];
then
  echo "mypy check failed, has fatal or error"
  echo "python version:"
  "$PYTHON_BIN" --version
  echo "package version:"
  "${PIP_CMD[@]}" list 2>/dev/null || echo "pip is not installed in this interpreter"
  exit 1
fi

exit "$mypy_ret_code"
