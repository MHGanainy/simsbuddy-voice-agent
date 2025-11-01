#!/bin/bash

# AUTO-DEPLOY TO RAILWAY - Handles existing projects automatically

echo "🚂 Auto-Deploying to Railway"
echo "============================"

# Install Railway CLI if needed
command -v railway &> /dev/null || npm install -g @railway/cli

# Login if needed
railway whoami &> /dev/null || railway login

# Function to check if a Railway project exists and link/create it
setup_railway_project() {
    local project_name=$1
    local project_dir=$2
    
    cd "$project_dir"
    
    # Check if already linked to a project
    if railway status &> /dev/null; then
        echo "✓ Already linked to a Railway project"
        return 0
    fi
    
    # Check if project exists in Railway account
    if railway list 2>/dev/null | grep -q "^$project_name$"; then
        echo "✓ Project '$project_name' exists, linking..."
        railway link "$project_name"
    else
        echo "✓ Creating new project '$project_name'..."
        railway init -n "$project_name"
    fi
}

# ORCHESTRATOR
echo ""
echo "📦 Deploying Orchestrator..."

# Save current directory
ROOT_DIR=$(pwd)

# Create Dockerfile for orchestrator
cat > Dockerfile << 'EOF'
FROM python:3.10

WORKDIR /app

# Install Node.js
RUN apt-get update && \
    apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Copy everything
COPY voice-assistant-project/ /app/voice-assistant-project/

# Install Node deps
WORKDIR /app/voice-assistant-project/orchestrator
RUN npm install

# Install Python deps (ALL of them including ML packages)
WORKDIR /app/voice-assistant-project
RUN pip install -r requirements.txt

# Set working directory for orchestrator
WORKDIR /app/voice-assistant-project/orchestrator

EXPOSE 8080
CMD ["node", "simple-orchestrator.js"]
EOF

# Setup Railway project for orchestrator
setup_railway_project "voice-orchestrator" "$ROOT_DIR"

# Deploy
railway up

# Set env vars - REPLACE WITH YOUR ACTUAL VALUES
railway variables \
  --set GROQ_API_KEY="your_groq_api_key_here" \
  --set ASSEMBLY_API_KEY="your_assemblyai_api_key_here" \
  --set INWORLD_API_KEY="your_inworld_api_key_here" \
  --set LIVEKIT_URL="your_livekit_url_here" \
  --set LIVEKIT_API_KEY="your_livekit_api_key_here" \
  --set LIVEKIT_API_SECRET="your_livekit_api_secret_here" \
  --set PORT="8080"

railway up

# Generate domain if not exists and get URL
railway domain || railway domain --generate
ORCHESTRATOR_URL=$(railway domain | grep -o '[a-zA-Z0-9.-]*\.up\.railway\.app' | head -n 1)
echo "✅ Orchestrator: https://$ORCHESTRATOR_URL"

# FRONTEND
echo ""
echo "📦 Deploying Frontend..."

# Navigate to frontend directory
FRONTEND_DIR="$ROOT_DIR/voice-assistant-project/livekit-react-app"
cd "$FRONTEND_DIR"

# Create Dockerfile for frontend
cat > Dockerfile << 'EOF'
# React Frontend Dockerfile - Simplified (Orchestrator handles tokens)
FROM node:18-alpine as builder

# Build stage
WORKDIR /app
COPY voice-assistant-project/livekit-react-app/package*.json ./
RUN npm ci

COPY voice-assistant-project/livekit-react-app/ .
RUN npm run build

# Production stage
FROM node:18-alpine

# Install serve for static file serving
RUN npm install -g serve

WORKDIR /app

# Copy built files from builder stage
COPY --from=builder /app/dist ./

# Copy environment file if exists
COPY voice-assistant-project/livekit-react-app/.env* ./

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3000 || exit 1

# Expose port
EXPOSE 3000

# Serve the React app
CMD ["serve", "-s", ".", "-l", "3000"]
EOF

# Setup Railway project for frontend
setup_railway_project "voice-frontend" "$FRONTEND_DIR"

# Deploy
railway up

# Set env vars
railway variables \
  --set VITE_LIVEKIT_URL="wss://simsbuddy-mdszuvzz.livekit.cloud" \
  --set VITE_TOKEN_ENDPOINT="https://$ORCHESTRATOR_URL/api/token" \
  --set PORT="3000"

railway up

# Generate domain if not exists and get URL
railway domain || railway domain --generate
FRONTEND_URL=$(railway domain | grep -o '[a-zA-Z0-9.-]*\.up\.railway\.app' | head -n 1)

# Return to root directory
cd "$ROOT_DIR"

# Done!
echo ""
echo "============================"
echo "✅ Deployment Complete!"
echo "============================"
echo "Frontend: https://$FRONTEND_URL"
echo "Orchestrator: https://$ORCHESTRATOR_URL"
echo "============================"