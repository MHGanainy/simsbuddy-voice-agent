# React Frontend Dockerfile - Simplified (Orchestrator handles tokens)
FROM node:18-alpine as builder

# Build stage
WORKDIR /app
COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

# Production stage
FROM node:18-alpine

# Install serve for static file serving
RUN npm install -g serve

WORKDIR /app

# Copy built files from builder stage
COPY --from=builder /app/dist ./

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3000 || exit 1

# Expose port
EXPOSE 3000

# Serve the React app
CMD ["serve", "-s", ".", "-l", "3000"]
