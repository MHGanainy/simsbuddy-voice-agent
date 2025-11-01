# React Frontend Dockerfile - Railway Compatible
FROM node:18-alpine as builder

# Build stage
WORKDIR /app

# Accept API URLs as build arguments (Railway will inject these)
ARG VITE_API_URL
ARG VITE_ORCHESTRATOR_URL
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_ORCHESTRATOR_URL=$VITE_ORCHESTRATOR_URL

COPY package*.json ./
RUN npm ci --only=production

COPY . .
RUN npm run build

# Production stage
FROM node:18-alpine

# Install serve for static file serving
RUN npm install -g serve

WORKDIR /app

# Copy built files from builder stage
COPY --from=builder /app/dist ./dist

# Expose port (Railway will inject $PORT at runtime)
EXPOSE 3000

# Serve the React app using Railway's $PORT
CMD ["sh", "-c", "serve -s dist -l ${PORT:-3000}"]
