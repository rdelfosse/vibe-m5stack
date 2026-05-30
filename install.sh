#!/bin/bash
# Vibe M5Stack - Install script for Linux/macOS
# Copyright 2026 Romain Delfosse
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Stop on first error
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Status output
write_status() {
    local message="$1"
    local color="$2"
    echo -e "${color}[install] ${message}${NC}"
}

write_step() {
    local number="$1"
    local message="$2"
    echo -e "\n${CYAN} === Étape ${number} : ${message} ===${NC}\n"
}

# Welcome banner
clear
cat << "EOF"
  ▄████████████████████████████████████████████▄
 ████████████████████████████████████ ███
████ ▀███ █████   ██████ █████ ████ ████ ██████ █████ ██
████   █   ████   ▀███ ███   ████   █   ████   █   ███   █
████       ████        ███          ████       ████       ███
 ████████████████   █████   █████       █████   ████     ███
  ▀██████████████ ██████████   ███       █████████   ██████
                          ███                        ███
                          ▀▀▀                        ▀▀▀

  VIBE M5Stack - Installateur
  =========================

EOF

# Step 1: Check Python
write_step 1 "Vérification de Python"

if ! command -v python3 &> /dev/null; then
    write_status "Python 3 non trouvé!" "$RED"
    echo ""
    echo "Installe Python 3.10+ depuis:"
    echo "  https://www.python.org/downloads/"
    echo ""
    exit 1
fi

PYTHON=$(command -v python3)
PYTHON_VERSION=$($PYTHON --version 2>&1)
write_status "Python trouvé: $PYTHON_VERSION" "$GREEN"

# Check Python version
MAJOR=$(echo "$PYTHON_VERSION" | grep -oP '\d+\.\d+' | cut -d. -f1)
MINOR=$(echo "$PYTHON_VERSION" | grep -oP '\d+\.\d+' | cut -d. -f2)

if [ "$MAJOR" -lt 3 ] || [ "$MAJOR" -eq 3 -a "$MINOR" -lt 10 ]; then
    write_status "Python 3.10+ requis (trouvé: $PYTHON_VERSION)" "$RED"
    exit 1
fi

# Step 2: Install uv
write_step 2 "Installation de uv"

UV_PATH="$HOME/.local/bin/uv"

if [ -f "$UV_PATH" ]; then
    write_status "uv déjà installé" "$GREEN"
else
    write_status "Installation de uv..." "$YELLOW"
    
    # Install uv using the official installer
    curl -fsSL https://astral-sh.github.io/uv/install.sh | sh
    
    # Verify installation
    if [ -f "$UV_PATH" ]; then
        # Add to PATH if not already there
        if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
            export PATH="$HOME/.local/bin:$PATH"
            # Add to shell config
            echo "" >> ~/.bashrc
            echo "# Added by vibe-m5stack installer" >> ~/.bashrc
            echo "export PATH="\$HOME/.local/bin:\$PATH"" >> ~/.bashrc
            
            if [ -f ~/.zshrc ]; then
                echo "" >> ~/.zshrc
                echo "# Added by vibe-m5stack installer" >> ~/.zshrc
                echo "export PATH="\$HOME/.local/bin:\$PATH"" >> ~/.zshrc
            fi
        fi
        write_status "uv installé avec succès" "$GREEN"
    else
        write_status "Échec de l'installation de uv" "$RED"
        echo ""
        echo "Tu peux aussi installer uv manuellement depuis:"
        echo "  https://docs.astral.sh/uv/getting-started#installation"
        exit 1
    fi
fi

# Step 3: Install vibe with vibe-m5stack
write_step 3 "Installation de mistral-vibe + vibe-m5stack"

REPO_ROOT=$(dirname "$(readlink -f "$0")")

write_status "Installation depuis: $REPO_ROOT" "$YELLOW"

uv tool install --reinstall mistral-vibe --with-editable "$REPO_ROOT" --with-executables-from vibe-m5stack
write_status "Installation terminée" "$GREEN"

# Step 4: Setup M5Stack
write_step 4 "Configuration du M5Stack"

write_status "Détection du port série..." "$YELLOW"

if vibe-m5stack setup; then
    write_status "Configuration terminée" "$GREEN"
else
    EXIT_CODE=$?
    write_status "Configuration échouée (code: $EXIT_CODE)" "$RED"
    echo ""
    echo "Si le M5Stack n'est pas détecté:"
    echo "  1. Branche le M5Stack par USB (câble data, pas charge-only)"
    echo "  2. Sous Linux, vérifie que ton user fait partie du groupe 'dialout'"
    echo "     (sudo usermod -a -G dialout \$USER, puis logout/login)"
    echo "  3. Relance: vibe-m5stack setup"
fi

# Step 5: Web flasher info
write_step 5 "Web Flasher"

WEB_FLASHER_URL="https://rdelfosse.github.io/vibe-m5stack/flash/"
write_status "Web flasher disponible:" "$GREEN"
echo -e "  ${CYAN}$WEB_FLASHER_URL${NC}"
echo ""
echo "Ouvre cette URL dans Chrome/Edge pour flasher le firmware"
echo "sans installer PlatformIO."

# Summary
echo ""
echo -e "${CYAN}============================================================${NC}"
echo -e "  ${GREEN}Installation terminée!${NC}"
echo -e "${CYAN}============================================================${NC}"
echo ""
echo "Pour commencer:"
echo "  1. Flashe le firmware: ouvre $WEB_FLASHER_URL dans Chrome"
echo "  2. Branche le M5Stack par USB"
echo "  3. Lance: vibe-m5stack"
echo ""
echo "En cas de problème: vibe-m5stack doctor"
echo ""
