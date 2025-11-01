# React Frontend Dockerfile - Railway Compatible
FROM node:18-alpine as builder

# Build stage
WORKDIR /app

# Accept API URL as build argument (Railway will inject this)
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL

# Copy from frontend directory (Railway context is repo root)
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
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
