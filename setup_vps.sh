#!/bin/bash
# ===========================================
# Polymarket Bot - VPS Setup Script
# ===========================================
# Kjør dette på en fersk Ubuntu 22.04/24.04 VPS
# Usage: curl -sSL <url> | bash
# ===========================================

set -e

echo "🚀 Polymarket Bot - VPS Setup"
echo "=============================="

# Oppdater system
echo "📦 Oppdaterer system..."
sudo apt-get update
sudo apt-get upgrade -y

# Installer Docker
echo "🐳 Installerer Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker $USER
    echo "⚠️  Logg ut og inn igjen for docker-tilgang uten sudo"
fi

# Installer Docker Compose
echo "🐳 Installerer Docker Compose..."
sudo apt-get install -y docker-compose-plugin

# Klon repository
echo "📥 Kloner repository..."
if [ ! -d "cdpm" ]; then
    git clone https://github.com/LokeL-no/cdpm.git
fi
cd cdpm

# Start botten
echo "🤖 Starter bot..."
sudo docker compose up -d --build

# Vis status
echo ""
echo "✅ Setup fullført!"
echo ""
echo "📋 Nyttige kommandoer:"
echo "   docker compose logs -f     # Se live logs"
echo "   docker compose restart     # Restart bot"
echo "   docker compose down        # Stopp bot"
echo "   docker compose up -d       # Start bot"
echo ""
echo "🌐 Bot kjører på: http://$(curl -s ifconfig.me):8080"
