#!/usr/bin/env bash
echo "🪛 Installing VSCode Extensions:"
echo "--------------------------------"

# Locate QGIS binary
QGIS_BIN=$(which qgis)

if [[ -z "$QGIS_BIN" ]]; then
    echo "Error: QGIS binary not found!"
    exit 1
fi

# Extract the Nix store path (removing /bin/qgis)
QGIS_PREFIX=$(dirname "$(dirname "$QGIS_BIN")")

# Construct the correct QGIS Python path
QGIS_PYTHON_PATH="$QGIS_PREFIX/share/qgis/python"
# Needed for qgis processing module import
PROCESSING_PATH="$QGIS_PREFIX/share/qgis/python/qgis"

# Check if the Python directory exists
if [[ ! -d "$QGIS_PYTHON_PATH" ]]; then
    echo "Error: QGIS Python path not found at $QGIS_PYTHON_PATH"
    exit 1
fi

# Create .env file for VSCode
ENV_FILE=".env"

QTPOSITIONING="/nix/store/nb3gkbi161fna9fxh9g3bdgzxzpq34gf-python3.11-pyqt5-5.15.10/lib/python3.11/site-packages"

echo "Creating VSCode .env file..."
cat <<EOF > "$ENV_FILE"
PYTHONPATH=$QGIS_PYTHON_PATH:$QTPOSITIONING
# needed for launch.json
QGIS_EXECUTABLE=$QGIS_BIN
QGIS_PREFIX_PATH=$QGIS_PREFIX
PYQT5_PATH="$QGIS_PREFIX/share/qgis/python/PyQt"
QT_QPA_PLATFORM=offscreen
EOF

echo "✅ .env file created successfully!"
echo "Contents of .env:"
cat "$ENV_FILE"

# Also set the python path in this shell in case we want to run tests etc from the command line
export PYTHONPATH=$PYTHONPATH:$QGIS_PYTHON_PATH

# Ensure .vscode directory exists
mkdir -p .vscode

# Define the settings.json file path
SETTINGS_FILE=".vscode/settings.json"

# Ensure settings.json exists
if [[ ! -f "$SETTINGS_FILE" ]]; then
    echo "{}" > "$SETTINGS_FILE"
fi

# Update settings.json non-destructively
echo "Updating VSCode settings.json..."
jq --arg pyenv "\${workspaceFolder}/.env" \
   --arg qgispath "$QGIS_PYTHON_PATH" \
   --arg prefixpath "$QGIS_PREFIX" \
   '.["python.envFile"] = $pyenv |
    .["python.analysis.extraPaths"] += [$qgispath] |
    .["terminal.integrated.env.linux"].PYTHONPATH = $qgispath |
    .["git.enableCommitSigning"] = true |
    .["editor.formatOnSave"] = true |
    .["editor.defaultFormatter"] = "ms-python.black-formatter"' \
   "$SETTINGS_FILE" > "$SETTINGS_FILE.tmp" && mv "$SETTINGS_FILE.tmp" "$SETTINGS_FILE"

echo "✅ VSCode settings.json updated successfully!"
echo "Contents of settings.json:"
cat "$SETTINGS_FILE"

# Install required extensions
code --user-data-dir='.vscode' \
--profile='geest' \
--extensions-dir='.vscode-extensions' . \
code --extensions-dir=.vscode-extensions --install-extension batisteo.vscode-django@1.15.0 \
code --extensions-dir=.vscode-extensions --install-extension donjayamanne.python-environment-manager@1.2.7 \
code --extensions-dir=.vscode-extensions --install-extension donjayamanne.python-extension-pack@1.7.0 \
code --extensions-dir=.vscode-extensions --install-extension fabianlauer.vs-code-xml-format@0.1.5 \
code --extensions-dir=.vscode-extensions --install-extension github.copilot@1.277.0 \
code --extensions-dir=.vscode-extensions --install-extension github.copilot-chat@0.24.1 \
code --extensions-dir=.vscode-extensions --install-extension github.vscode-github-actions@0.27.1 \
code --extensions-dir=.vscode-extensions --install-extension github.vscode-pull-request-github@0.106.0 \
code --extensions-dir=.vscode-extensions --install-extension hbenl.vscode-test-explorer@2.22.1 \
code --extensions-dir=.vscode-extensions --install-extension jamesqquick.python-class-generator@0.0.3 \
code --extensions-dir=.vscode-extensions --install-extension kevinrose.vsc-python-indent@1.21.0 \
code --extensions-dir=.vscode-extensions --install-extension littlefoxteam.vscode-python-test-adapter@0.8.2 \
code --extensions-dir=.vscode-extensions --install-extension ms-python.black-formatter@2025.2.0 \
code --extensions-dir=.vscode-extensions --install-extension ms-python.debugpy@2025.4.1 \
code --extensions-dir=.vscode-extensions --install-extension ms-python.python@2025.2.0 \
code --extensions-dir=.vscode-extensions --install-extension ms-python.vscode-pylance@2025.3.2 \
code --extensions-dir=.vscode-extensions --install-extension ms-vscode.test-adapter-converter@0.2.1 \
code --extensions-dir=.vscode-extensions --install-extension njpwerner.autodocstring@0.6.1 \
code --extensions-dir=.vscode-extensions --install-extension visualstudioexptteam.intellicode-api-usage-examples@0.2.9 \
code --extensions-dir=.vscode-extensions --install-extension visualstudioexptteam.vscodeintellicode@1.3.2 \
code --extensions-dir=.vscode-extensions --install-extension wholroyd.jinja@0.0.8
# Launch VSCode with the sandboxed environment
code --user-data-dir='.vscode' \
--profile='geest' \
--extensions-dir='.vscode-extensions' .
