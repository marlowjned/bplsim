#!/bin/bash
# WSL setup, steps 2-3: uv, the bplsim environment, GetDP 3.5.0 (Linux), site profile.
set -e
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh >/tmp/uv.log 2>&1
fi
uv --version
cd ~/Projects/bplsim
[ -d .venv ] || uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]" 2>&1 | tail -1

# GetDP 3.5.0 for Linux (same version as the legacy Windows build)
mkdir -p ~/tools && cd ~/tools
if [ ! -x ~/tools/getdp/bin/getdp ]; then
  for name in getdp-3.5.0-Linux64c getdp-3.5.0-Linux64; do
    if curl -fsSL -o $name.tgz https://getdp.info/bin/Linux/$name.tgz; then
      tar xzf $name.tgz && rm -f $name.tgz && rm -rf getdp && mv getdp-3.5.0-Linux64 getdp   # unpacks without the c
      echo "GetDP downloaded as $name.tgz"
      break
    fi
  done
fi
~/tools/getdp/bin/getdp --version 2>&1 | head -1

mkdir -p ~/.config/bplsim/sites ~/bplsim_data
cat > ~/.config/bplsim/sites/local.yaml <<EOF
name: local
data_root: $HOME/bplsim_data
executor: local
tools: {getdp: $HOME/tools/getdp/bin/getdp}
EOF
cat ~/.config/bplsim/sites/local.yaml
