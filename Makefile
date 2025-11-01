# ════════════════════════════════════════════════════════════════════════
# LiveKit Voice Assistant - Developer Makefile
# ════════════════════════════════════════════════════════════════════════

.PHONY: help dev dev-d build stop restart clean logs logs-orchestrator logs-celery logs-beat logs-agent logs-redis logs-frontend logs-all ps shell-orchestrator shell-redis redis-keys redis-sessions redis-flush test health status
.DEFAULT_GOAL := help

# ════════════════════════════════════════════════════════════════════════
# Configuration
# ════════════════════════════════════════════════════════════════════════

# Colors for pretty output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
CYAN := \033[0;36m
MAGENTA := \033[0;35m
NC := \033[0m# No Color
BOLD := \033[1m

# Docker Compose
COMPOSE_FILE := docker-compose.yml
COMPOSE := docker-compose -f $(COMPOSE_FILE)

# Service names
ORCHESTRATOR := voice-agent-orchestrator
REDIS := voice-agent-redis
FRONTEND := voice-agent-frontend

# ════════════════════════════════════════════════════════════════════════
# Help & Information
# ════════════════════════════════════════════════════════════════════════

help: ## Show this help message
	@echo "$(BOLD)$(BLUE)═══════════════════════════════════════════════════════════════$(NC)"
	@echo "$(BOLD)$(CYAN)  LiveKit Voice Assistant - Developer Commands$(NC)"
	@echo "$(BOLD)$(BLUE)═══════════════════════════════════════════════════════════════$(NC)"
	@echo ""
	@echo "$(BOLD)Core Commands:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E '^(help|dev|dev-d|build|stop|restart|clean):' | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(BOLD)Logging Commands:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E '^logs' | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(BOLD)Utility Commands:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E '^(ps|shell|redis|test|health|status):' | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(BOLD)Quick Start:$(NC)"
	@echo "  1. $(GREEN)make dev-d$(NC)           # Start services in background"
	@echo "  2. $(CYAN)make logs-all$(NC)       # View recent logs"
	@echo "  3. $(YELLOW)make health$(NC)          # Check service health"
	@echo "  4. $(GREEN)make stop$(NC)            # Stop when done"
	@echo ""

# ════════════════════════════════════════════════════════════════════════
# Core Commands
# ════════════════════════════════════════════════════════════════════════

dev: ## Start all services (attached, see logs)
	@echo "$(BOLD)$(BLUE)Starting all services in development mode...$(NC)"
	@echo "$(YELLOW)Press Ctrl+C to stop$(NC)"
	@echo ""
	$(COMPOSE) up --build

dev-d: ## Start all services in background (detached)
	@echo "$(BOLD)$(BLUE)Starting all services in background...$(NC)"
	$(COMPOSE) up -d --build
	@echo ""
	@echo "$(GREEN)✓ Services started!$(NC)"
	@echo ""
	@echo "$(BOLD)Next steps:$(NC)"
	@echo "  • View logs:        $(CYAN)make logs$(NC)"
	@echo "  • Check health:     $(YELLOW)make health$(NC)"
	@echo "  • View status:      $(YELLOW)make status$(NC)"
	@echo ""

build: ## Build all Docker images
	@echo "$(BOLD)$(BLUE)Building Docker images...$(NC)"
	$(COMPOSE) build
	@echo "$(GREEN)✓ Build complete$(NC)"

stop: ## Stop all services
	@echo "$(YELLOW)Stopping all services...$(NC)"
	$(COMPOSE) stop
	@echo "$(GREEN)✓ Services stopped$(NC)"

restart: ## Restart all services
	@echo "$(YELLOW)Restarting all services...$(NC)"
	$(COMPOSE) restart
	@echo "$(GREEN)✓ Services restarted$(NC)"

clean: ## Stop and remove all containers, volumes, networks
	@echo "$(BOLD)$(RED)⚠ WARNING: This will remove all containers and volumes!$(NC)"
	@printf "Are you sure? [y/N] " && read ans && [ $${ans:-N} = y ]
	@$(COMPOSE) down -v
	@echo "$(GREEN)✓ Cleaned up$(NC)"

# ════════════════════════════════════════════════════════════════════════
# Logging Commands
# ════════════════════════════════════════════════════════════════════════

logs: ## Follow logs from all services
	@echo "$(BOLD)$(CYAN)Following logs from all services (Ctrl+C to exit)...$(NC)"
	@echo ""
	$(COMPOSE) logs -f

logs-orchestrator: ## Follow FastAPI orchestrator logs
	@echo "$(BOLD)$(CYAN)Following orchestrator (FastAPI) logs...$(NC)"
	@echo "$(YELLOW)Press Ctrl+C to exit$(NC)"
	@echo ""
	@docker exec $(ORCHESTRATOR) tail -f /var/log/supervisor/fastapi.log

logs-celery: ## Follow Celery worker logs
	@echo "$(BOLD)$(CYAN)Following Celery worker logs...$(NC)"
	@echo "$(YELLOW)Press Ctrl+C to exit$(NC)"
	@echo ""
	@docker exec $(ORCHESTRATOR) tail -f /var/log/supervisor/celery-worker.log

logs-beat: ## Follow Celery beat logs
	@echo "$(BOLD)$(CYAN)Following Celery beat logs...$(NC)"
	@echo "$(YELLOW)Press Ctrl+C to exit$(NC)"
	@echo ""
	@docker exec $(ORCHESTRATOR) tail -f /var/log/supervisor/celery-beat.log

logs-agent: ## Show running voice agent processes and recent logs
	@echo "$(BOLD)$(CYAN)Voice agent processes:$(NC)"
	@echo ""
	@docker exec $(ORCHESTRATOR) sh -c "ps aux | grep voice_assistant.py | grep -v grep" || echo "$(YELLOW)No voice agents running$(NC)"
	@echo ""
	@echo "$(BOLD)$(CYAN)Recent agent sessions in Redis:$(NC)"
	@echo ""
	@docker exec voice-agent-redis redis-cli KEYS "agent:*:logs" | head -10

logs-agent-session: ## View logs for a specific agent session (usage: make logs-agent-session SESSION=session_id)
	@if [ -z "$(SESSION)" ]; then \
		echo "$(RED)Error: SESSION variable required$(NC)"; \
		echo "Usage: make logs-agent-session SESSION=session_1234567890"; \
		echo ""; \
		echo "Available sessions:"; \
		docker exec voice-agent-redis redis-cli KEYS "agent:*:logs" | sed 's/agent://g' | sed 's/:logs//g' | head -10; \
		exit 1; \
	fi
	@echo "$(BOLD)$(CYAN)Logs for agent session: $(SESSION)$(NC)"
	@echo ""
	@docker exec voice-agent-redis redis-cli LRANGE "agent:$(SESSION):logs" 0 -1 || echo "$(YELLOW)No logs found for session $(SESSION)$(NC)"

logs-agent-live: ## Follow live logs for a specific agent (usage: make logs-agent-live SESSION=session_id)
	@if [ -z "$(SESSION)" ]; then \
		echo "$(RED)Error: SESSION variable required$(NC)"; \
		echo "Usage: make logs-agent-live SESSION=session_1234567890"; \
		echo ""; \
		echo "Available sessions with log files:"; \
		docker exec $(ORCHESTRATOR) sh -c 'ls -1t /var/log/voice-agents/*.log 2>/dev/null | head -10 | xargs -I {} basename {} .log' || echo "$(YELLOW)No log files found$(NC)"; \
		exit 1; \
	fi
	@echo "$(BOLD)$(CYAN)Following live logs for agent: $(SESSION)$(NC)"
	@echo "$(YELLOW)Press Ctrl+C to exit$(NC)"
	@echo ""
	@docker exec $(ORCHESTRATOR) tail -f /var/log/voice-agents/$(SESSION).log 2>/dev/null || echo "$(RED)Log file not found for session $(SESSION)$(NC)"

logs-agent-files: ## List all agent log files
	@echo "$(BOLD)$(CYAN)Agent log files (most recent first):$(NC)"
	@echo ""
	@docker exec $(ORCHESTRATOR) sh -c 'ls -lth /var/log/voice-agents/*.log 2>/dev/null | head -20' || echo "$(YELLOW)No log files found$(NC)"

logs-redis: ## Follow Redis logs
	@echo "$(BOLD)$(CYAN)Following Redis logs...$(NC)"
	@echo "$(YELLOW)Press Ctrl+C to exit$(NC)"
	@echo ""
	$(COMPOSE) logs -f redis

logs-frontend: ## Follow frontend logs
	@echo "$(BOLD)$(CYAN)Following frontend logs...$(NC)"
	@echo "$(YELLOW)Press Ctrl+C to exit$(NC)"
	@echo ""
	$(COMPOSE) logs -f frontend

logs-all: ## Show recent logs from all services
	@echo "$(BOLD)$(BLUE)═══════════════════════════════════════════════════════════════$(NC)"
	@echo "$(BOLD)$(CYAN)  Recent Logs from All Services$(NC)"
	@echo "$(BOLD)$(BLUE)═══════════════════════════════════════════════════════════════$(NC)"
	@echo ""
	@echo "$(BOLD)$(GREEN)=== ORCHESTRATOR (FastAPI) ===$(NC)"
	@docker exec $(ORCHESTRATOR) tail -50 /var/log/supervisor/fastapi.log 2>/dev/null || echo "$(YELLOW)Service not running$(NC)"
	@echo ""
	@echo "$(BOLD)$(GREEN)=== CELERY WORKER ===$(NC)"
	@docker exec $(ORCHESTRATOR) tail -50 /var/log/supervisor/celery-worker.log 2>/dev/null || echo "$(YELLOW)Service not running$(NC)"
	@echo ""
	@echo "$(BOLD)$(GREEN)=== CELERY BEAT ===$(NC)"
	@docker exec $(ORCHESTRATOR) tail -20 /var/log/supervisor/celery-beat.log 2>/dev/null || echo "$(YELLOW)Service not running$(NC)"
	@echo ""
	@echo "$(BOLD)$(GREEN)=== REDIS ===$(NC)"
	@$(COMPOSE) logs --tail=30 redis 2>/dev/null || echo "$(YELLOW)Service not running$(NC)"
	@echo ""
	@echo "$(BOLD)$(GREEN)=== FRONTEND ===$(NC)"
	@$(COMPOSE) logs --tail=30 frontend 2>/dev/null || echo "$(YELLOW)Service not running$(NC)"

# ════════════════════════════════════════════════════════════════════════
# Utility Commands
# ════════════════════════════════════════════════════════════════════════

ps: ## Show status of all containers
	@echo "$(BOLD)$(BLUE)Container status:$(NC)"
	@echo ""
	@$(COMPOSE) ps

status: ## Show detailed status of all services
	@echo "$(BOLD)$(BLUE)═══════════════════════════════════════════════════════════════$(NC)"
	@echo "$(BOLD)$(CYAN)  Service Status Overview$(NC)"
	@echo "$(BOLD)$(BLUE)═══════════════════════════════════════════════════════════════$(NC)"
	@echo ""
	@echo "$(BOLD)Container Status:$(NC)"
	@$(COMPOSE) ps
	@echo ""
	@echo "$(BOLD)Health Checks:$(NC)"
	@echo -n "  Orchestrator API: "
	@curl -s http://localhost:8000/health | jq -r .status 2>/dev/null | grep -q "healthy" && echo "$(GREEN)✓ HEALTHY$(NC)" || echo "$(RED)✗ DOWN$(NC)"
	@echo -n "  Redis:            "
	@docker exec $(REDIS) redis-cli PING 2>/dev/null | grep -q "PONG" && echo "$(GREEN)✓ HEALTHY$(NC)" || echo "$(RED)✗ DOWN$(NC)"
	@echo -n "  Frontend:         "
	@curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 2>/dev/null | grep -q "200" && echo "$(GREEN)✓ HEALTHY$(NC)" || echo "$(RED)✗ DOWN$(NC)"
	@echo ""

health: ## Quick health check of all services
	@echo "$(BOLD)$(CYAN)Checking service health...$(NC)"
	@echo ""
	@echo -n "  Orchestrator: "
	@curl -s http://localhost:8000/health 2>/dev/null | jq -r .status | grep -q "healthy" && echo "$(GREEN)HEALTHY$(NC)" || echo "$(RED)DOWN$(NC)"
	@echo -n "  Redis:        "
	@docker exec $(REDIS) redis-cli PING 2>/dev/null | grep -q "PONG" && echo "$(GREEN)HEALTHY$(NC)" || echo "$(RED)DOWN$(NC)"
	@echo -n "  Frontend:     "
	@curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 2>/dev/null | grep -q "200" && echo "$(GREEN)HEALTHY$(NC)" || echo "$(RED)DOWN$(NC)"
	@echo ""

shell-orchestrator: ## Open bash shell in orchestrator container
	@echo "$(BOLD)$(CYAN)Opening shell in orchestrator container...$(NC)"
	@echo "$(YELLOW)Type 'exit' to return$(NC)"
	@echo ""
	@docker exec -it $(ORCHESTRATOR) /bin/bash

shell-redis: ## Open redis-cli in Redis container
	@echo "$(BOLD)$(CYAN)Opening redis-cli...$(NC)"
	@echo "$(YELLOW)Type 'exit' to return$(NC)"
	@echo ""
	@docker exec -it $(REDIS) redis-cli

# ════════════════════════════════════════════════════════════════════════
# Redis Utilities
# ════════════════════════════════════════════════════════════════════════

redis-keys: ## Show all Redis keys
	@echo "$(BOLD)$(CYAN)Redis keys:$(NC)"
	@echo ""
	@docker exec $(REDIS) redis-cli KEYS '*' 2>/dev/null || echo "$(RED)Redis not running$(NC)"

redis-sessions: ## Show active sessions in Redis
	@echo "$(BOLD)$(CYAN)Active sessions:$(NC)"
	@echo ""
	@docker exec $(REDIS) redis-cli KEYS 'session:*' 2>/dev/null | while read key; do \
		if [ -n "$$key" ]; then \
			echo "$(GREEN)$$key$(NC)"; \
			docker exec $(REDIS) redis-cli HGETALL "$$key"; \
			echo ""; \
		fi \
	done || echo "$(YELLOW)No sessions found or Redis not running$(NC)"

redis-flush: ## Flush Redis database (WARNING: deletes all data)
	@echo "$(BOLD)$(RED)⚠ WARNING: This will delete ALL data in Redis!$(NC)"
	@printf "Type 'yes' to confirm: " && read ans && [ "$${ans}" = yes ]
	@docker exec $(REDIS) redis-cli FLUSHDB
	@echo "$(GREEN)✓ Redis flushed$(NC)"

redis-stats: ## Show Redis statistics
	@echo "$(BOLD)$(CYAN)Redis Statistics:$(NC)"
	@echo ""
	@docker exec $(REDIS) redis-cli INFO stats 2>/dev/null | grep -E "(total_commands_processed|total_connections_received|keyspace)" || echo "$(RED)Redis not running$(NC)"

# ════════════════════════════════════════════════════════════════════════
# Testing
# ════════════════════════════════════════════════════════════════════════

test: ## Run full test suite
	@echo "$(BOLD)$(BLUE)═══════════════════════════════════════════════════════════════$(NC)"
	@echo "$(BOLD)$(CYAN)  Running Test Suite$(NC)"
	@echo "$(BOLD)$(BLUE)═══════════════════════════════════════════════════════════════$(NC)"
	@echo ""
	@echo "$(CYAN)Starting services...$(NC)"
	@$(COMPOSE) up -d
	@echo "$(YELLOW)Waiting for services to be ready...$(NC)"
	@sleep 10
	@echo ""
	@echo "$(BOLD)Test 1: Health Check$(NC)"
	@curl -s http://localhost:8000/health | jq . && echo "$(GREEN)✓ Health check passed$(NC)" || (echo "$(RED)✗ Health check failed$(NC)" && exit 1)
	@echo ""
	@echo "$(BOLD)Test 2: Session Creation$(NC)"
	@curl -s -X POST http://localhost:8000/api/session/start \
		-H "Content-Type: application/json" \
		-d '{"userName":"MakeTest","voiceId":"Ashley"}' | jq .sessionId && echo "$(GREEN)✓ Session creation passed$(NC)" || (echo "$(RED)✗ Session creation failed$(NC)" && exit 1)
	@echo ""
	@echo "$(GREEN)$(BOLD)✓ All tests passed!$(NC)"

test-quick: ## Quick health check only
	@echo "$(CYAN)Quick health test...$(NC)"
	@curl -s http://localhost:8000/health | jq -r .status | grep -q "healthy" && echo "$(GREEN)✓ API is healthy$(NC)" || echo "$(RED)✗ API is down$(NC)"

# ════════════════════════════════════════════════════════════════════════
# Additional Utilities
# ════════════════════════════════════════════════════════════════════════

docs: ## Show logging documentation
	@echo "$(BOLD)$(CYAN)Opening logging documentation...$(NC)"
	@cat backend/LOGGING.md 2>/dev/null || echo "$(YELLOW)Documentation not found$(NC)"

env: ## Show environment variables
	@echo "$(BOLD)$(CYAN)Current environment:$(NC)"
	@echo ""
	@echo "  LOG_LEVEL:   $${LOG_LEVEL:-INFO}"
	@echo "  LOG_FORMAT:  $${LOG_FORMAT:-console}"
	@echo "  LIVEKIT_URL: $${LIVEKIT_URL:-(not set)}"
	@echo ""

ports: ## Show which ports are in use
	@echo "$(BOLD)$(CYAN)Service Ports:$(NC)"
	@echo ""
	@echo "  Orchestrator API: $(GREEN)http://localhost:8000$(NC)"
	@echo "  Frontend:         $(GREEN)http://localhost:3000$(NC)"
	@echo "  Redis:            $(GREEN)localhost:6379$(NC)"
	@echo "  API Docs:         $(YELLOW)http://localhost:8000/docs$(NC)"
	@echo ""

urls: ## Show useful URLs
	@echo "$(BOLD)$(CYAN)Useful URLs:$(NC)"
	@echo ""
	@echo "  API Documentation:  $(YELLOW)http://localhost:8000/docs$(NC)"
	@echo "  Health Endpoint:    $(YELLOW)http://localhost:8000/health$(NC)"
	@echo "  Frontend:           $(YELLOW)http://localhost:3000$(NC)"
	@echo "  Logging Docs:       $(CYAN)cat backend/LOGGING.md$(NC)"
	@echo ""

# ════════════════════════════════════════════════════════════════════════
# Development Shortcuts
# ════════════════════════════════════════════════════════════════════════

up: dev-d ## Alias for dev-d (start in background)

down: stop ## Alias for stop

rebuild: ## Rebuild and restart all services
	@echo "$(BOLD)$(YELLOW)Rebuilding all services...$(NC)"
	@$(COMPOSE) down
	@$(COMPOSE) build --no-cache
	@$(COMPOSE) up -d
	@echo "$(GREEN)✓ Rebuild complete$(NC)"

restart-orchestrator: ## Restart just the orchestrator
	@echo "$(YELLOW)Restarting orchestrator...$(NC)"
	@docker restart $(ORCHESTRATOR)
	@echo "$(GREEN)✓ Orchestrator restarted$(NC)"

restart-redis: ## Restart just Redis
	@echo "$(YELLOW)Restarting Redis...$(NC)"
	@docker restart $(REDIS)
	@echo "$(GREEN)✓ Redis restarted$(NC)"

restart-frontend: ## Restart just the frontend
	@echo "$(YELLOW)Restarting frontend...$(NC)"
	@docker restart $(FRONTEND)
	@echo "$(GREEN)✓ Frontend restarted$(NC)"
