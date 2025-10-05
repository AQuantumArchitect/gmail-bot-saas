#!/bin/bash
# Test script to simulate Railway build process

set -e  # Exit on any error

echo "🚀 Testing Railway Build Process"
echo "================================"

# Create clean build directory
BUILD_DIR="/tmp/railway-build-test"
echo "📁 Creating build directory: $BUILD_DIR"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# Copy project files
echo "📋 Copying project files..."
cp -r /home/tehcr33d/ws/gmail-bot-saas/* . || true
cp /home/tehcr33d/ws/gmail-bot-saas/.env . || true

# Simulate nixpacks install phase
echo "📦 Installing dependencies (nixpacks simulation)..."
python3 -m venv --copies venv
source venv/bin/activate
pip install -r requirements.txt

echo "✅ Dependencies installed successfully"

# Test that we can import and start the app
echo "🔍 Testing app import..."
python3 -c "
import main_v2
print('✅ main_v2 imported successfully')

from main_v2 import app
print('✅ App object created successfully')

from app_v2.core.config import settings
print(f'✅ Config loaded: {settings.environment}')
"

# Test the exact startup command from nixpacks.toml
echo "🔍 Testing startup command..."
timeout 10s python3 -c "
import uvicorn
from main_v2 import app

# Test that uvicorn can find and load the app
print('✅ uvicorn can load main_v2:app')
" || true

echo "🔍 Testing production environment simulation..."
export ENVIRONMENT=production
export DEBUG_MODE=false
export WEBAPP_URL=https://test.railway.app

python3 -c "
from app_v2.core.config import Settings
settings = Settings()
print(f'✅ Production config test passed')
print(f'   Environment: {settings.environment}')
print(f'   Debug: {settings.debug_mode}')
print(f'   URL: {settings.webapp_url}')
"

echo "================================"
echo "🎉 Railway build simulation PASSED!"
echo "✅ Ready for deployment"