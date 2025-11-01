/**
 * Celery-based Voice Agent Orchestrator
 *
 * Non-blocking Express API that uses Celery tasks for agent spawning.
 * Features:
 * - Instant response via pre-warmed agent pool
 * - Async agent spawning via Celery tasks
 * - Redis-based session state management
 * - Graceful degradation (fallback to on-demand spawn)
 */

const express = require('express');
const cors = require('cors');
const Redis = require('ioredis');
const { AccessToken } = require('livekit-server-sdk');
const { v4: uuidv4 } = require('crypto').randomUUID ? require('crypto') : { randomUUID: () => uuidv4() };
const voiceCatalog = require('./voices-catalog');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 8080;

// Redis client
const redis = new Redis(process.env.REDIS_URL || 'redis://localhost:6379/0', {
  retryStrategy: (times) => {
    const delay = Math.min(times * 50, 2000);
    return delay;
  },
  maxRetriesPerRequest: 3
});

// Redis connection event handlers
redis.on('connect', () => {
  console.log('[Redis] Connected successfully');
});

redis.on('error', (err) => {
  console.error('[Redis] Connection error:', err.message);
});

redis.on('close', () => {
  console.log('[Redis] Connection closed');
});

// Middleware
app.use(cors());
app.use(express.json());

// Request timeout middleware
app.use((req, res, next) => {
  req.setTimeout(30000);
  res.setTimeout(30000);
  next();
});

// Configuration
const LIVEKIT_URL = process.env.LIVEKIT_URL;
const LIVEKIT_API_KEY = process.env.LIVEKIT_API_KEY;
const LIVEKIT_API_SECRET = process.env.LIVEKIT_API_SECRET;
const MAX_BOTS = parseInt(process.env.MAX_BOTS) || 50;
const RATE_LIMIT_WINDOW = 60; // seconds
const RATE_LIMIT_MAX_REQUESTS = 10;

// Validate environment variables
function validateEnv() {
  const required = ['LIVEKIT_URL', 'LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET'];
  const missing = required.filter(key => !process.env[key]);

  if (missing.length > 0) {
    console.error(`[Config] Missing required environment variables: ${missing.join(', ')}`);
    process.exit(1);
  }

  console.log('[Config] Environment validation passed');
}

validateEnv();

// Rate limiting helper
async function checkRateLimit(ip) {
  const key = `ratelimit:${ip}`;

  try {
    const count = await redis.incr(key);

    if (count === 1) {
      await redis.expire(key, RATE_LIMIT_WINDOW);
    }

    return count <= RATE_LIMIT_MAX_REQUESTS;
  } catch (error) {
    console.error('[RateLimit] Error checking rate limit:', error);
    return true; // Allow request on error
  }
}

// Helper: Get session from Redis
async function getSession(sessionId) {
  try {
    const data = await redis.hgetall(`session:${sessionId}`);
    if (!data || Object.keys(data).length === 0) return null;
    return data;
  } catch (error) {
    console.error(`[Session] Error fetching session ${sessionId}:`, error);
    return null;
  }
}

// Helper: Assign pre-warmed agent to user
async function assignPrewarmedAgent(userId) {
  try {
    const prewarmedId = await redis.spop('pool:ready');

    if (!prewarmedId) {
      console.log('[PreWarm] No pre-warmed agents available');
      return null;
    }

    console.log(`[PreWarm] Assigning ${prewarmedId} to user ${userId}`);

    // Update session with user info
    await redis.hset(`session:${prewarmedId}`, 'userId', userId);
    await redis.hset(`session:${prewarmedId}`, 'status', 'ready');
    await redis.hset(`session:${prewarmedId}`, 'lastActive', Date.now());
    await redis.set(`session:user:${userId}`, prewarmedId);
    await redis.sadd('session:ready', prewarmedId);
    await redis.hincrby('pool:stats', 'total_assigned', 1);

    return prewarmedId;
  } catch (error) {
    console.error('[PreWarm] Error assigning agent:', error);
    return null;
  }
}

// Helper: Queue Celery task for agent spawning
async function queueAgentSpawn(sessionId, userId) {
  try {
    const taskId = `task_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

    // Send task to Celery via Redis
    const taskPayload = {
      id: taskId,
      task: 'spawn_voice_agent',
      args: [sessionId, userId, false],
      kwargs: {},
      retries: 0,
      eta: null
    };

    await redis.lpush('celery', JSON.stringify(taskPayload));

    console.log(`[Celery] Queued spawn task ${taskId} for session ${sessionId}`);

    return taskId;
  } catch (error) {
    console.error('[Celery] Error queuing task:', error);
    throw error;
  }
}

/**
 * POST /api/session/start
 * Start a voice agent session (NON-BLOCKING)
 *
 * Flow:
 * 1. Try to assign pre-warmed agent (instant response)
 * 2. If no pre-warmed agents, queue spawn task and return immediately
 * 3. Client polls /api/session/:id for status updates
 */
app.post('/api/session/start', async (req, res) => {
  try {
    const { userId } = req.body;
    const ip = req.headers['x-forwarded-for'] || req.connection.remoteAddress;

    if (!userId) {
      return res.status(400).json({
        success: false,
        error: 'userId is required'
      });
    }

    // Rate limiting
    const allowed = await checkRateLimit(ip);
    if (!allowed) {
      return res.status(429).json({
        success: false,
        error: `Rate limit exceeded. Max ${RATE_LIMIT_MAX_REQUESTS} requests per ${RATE_LIMIT_WINDOW} seconds.`
      });
    }

    // Check capacity
    const activeSessions = await redis.scard('session:ready') +
                          await redis.scard('session:starting');

    if (activeSessions >= MAX_BOTS) {
      return res.status(503).json({
        success: false,
        error: 'Maximum capacity reached. Please try again later.',
        capacity: { current: activeSessions, max: MAX_BOTS }
      });
    }

    // Check if user already has an active session
    const existingSessionId = await redis.get(`session:user:${userId}`);
    if (existingSessionId) {
      const session = await getSession(existingSessionId);
      if (session && (session.status === 'ready' || session.status === 'starting')) {
        console.log(`[Session] User ${userId} already has session: ${existingSessionId}`);
        return res.json({
          success: true,
          sessionId: existingSessionId,
          status: session.status,
          message: 'Using existing session',
          prewarmed: false
        });
      }
    }

    // FAST PATH: Try to assign pre-warmed agent (instant)
    const prewarmedId = await assignPrewarmedAgent(userId);

    if (prewarmedId) {
      return res.json({
        success: true,
        sessionId: prewarmedId,
        status: 'ready',
        message: 'Assigned pre-warmed agent',
        prewarmed: true,
        latency: '<500ms'
      });
    }

    // FALLBACK PATH: Queue new agent spawn (async)
    const sessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    const taskId = await queueAgentSpawn(sessionId, userId);

    // Initialize session state
    await redis.hset(`session:${sessionId}`, {
      status: 'starting',
      userId: userId,
      createdAt: Date.now(),
      taskId: taskId
    });
    await redis.set(`session:user:${userId}`, sessionId);

    // Return immediately with "starting" status
    res.json({
      success: true,
      sessionId,
      status: 'starting',
      message: 'Agent is being spawned. Poll /api/session/:id for status.',
      taskId,
      prewarmed: false,
      estimatedWait: '15-20s'
    });

  } catch (error) {
    console.error('[API] Error starting session:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * GET /api/session/:id
 * Get session status (for polling)
 */
app.get('/api/session/:id', async (req, res) => {
  try {
    const { id } = req.params;

    const session = await getSession(id);

    if (!session) {
      return res.status(404).json({
        success: false,
        error: 'Session not found'
      });
    }

    // Update last active timestamp
    await redis.hset(`session:${id}`, 'lastActive', Date.now());

    res.json({
      success: true,
      sessionId: id,
      status: session.status,
      userId: session.userId || null,
      createdAt: parseInt(session.createdAt) || null,
      startupTime: parseFloat(session.startupTime) || null,
      error: session.error || null,
      taskId: session.taskId || null
    });

  } catch (error) {
    console.error('[API] Error fetching session:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * POST /api/session/stop
 * Stop a session
 */
app.post('/api/session/stop', async (req, res) => {
  try {
    const { sessionId } = req.body;

    if (!sessionId) {
      return res.status(400).json({
        success: false,
        error: 'sessionId is required'
      });
    }

    const session = await getSession(sessionId);

    if (!session) {
      return res.status(404).json({
        success: false,
        error: 'Session not found'
      });
    }

    const pid = session.agentPid;

    // Send signal to Python process to stop
    if (pid) {
      try {
        process.kill(parseInt(pid), 'SIGTERM');
        console.log(`[Session] Sent SIGTERM to agent ${sessionId} (PID ${pid})`);

        // Give it 5 seconds, then force kill
        setTimeout(() => {
          try {
            process.kill(parseInt(pid), 'SIGKILL');
            console.log(`[Session] Force killed agent ${sessionId} (PID ${pid})`);
          } catch (e) {
            // Process already dead
          }
        }, 5000);
      } catch (error) {
        console.log(`[Session] Process ${pid} already terminated`);
      }
    }

    // Clean up Redis
    const userId = session.userId;
    await redis.del(`session:${sessionId}`);
    await redis.del(`agent:${sessionId}:pid`);
    await redis.del(`agent:${sessionId}:logs`);
    await redis.del(`agent:${sessionId}:health`);
    await redis.srem('session:ready', sessionId);
    await redis.srem('session:starting', sessionId);
    await redis.srem('pool:ready', sessionId);
    if (userId) {
      await redis.del(`session:user:${userId}`);
    }

    console.log(`[Session] Stopped and cleaned up session ${sessionId}`);

    res.json({
      success: true,
      message: 'Session stopped'
    });

  } catch (error) {
    console.error('[API] Error stopping session:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * POST /api/token
 * Generate LiveKit access token
 */
app.post('/api/token', async (req, res) => {
  try {
    const { sessionId, userName } = req.body;

    if (!sessionId) {
      return res.status(400).json({
        success: false,
        error: 'sessionId is required'
      });
    }

    const session = await getSession(sessionId);

    if (!session) {
      return res.status(404).json({
        success: false,
        error: 'Session not found'
      });
    }

    if (session.status !== 'ready') {
      return res.status(400).json({
        success: false,
        error: `Session not ready. Current status: ${session.status}`,
        status: session.status
      });
    }

    // Generate LiveKit token
    const token = new AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET, {
      identity: userName || `user_${Date.now()}`,
      ttl: '2h'
    });

    token.addGrant({
      room: sessionId,
      roomJoin: true,
      canPublish: true,
      canSubscribe: true,
      canPublishData: true
    });

    const jwt = await token.toJwt();

    console.log(`[Token] Generated for session ${sessionId}, user ${userName || 'anonymous'}`);

    res.json({
      success: true,
      token: jwt,
      url: LIVEKIT_URL,
      roomName: sessionId
    });

  } catch (error) {
    console.error('[API] Error generating token:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * GET /api/health
 * Health check endpoint
 */
app.get('/api/health', async (req, res) => {
  try {
    // Check Redis connection
    await redis.ping();

    const readyCount = await redis.scard('session:ready');
    const startingCount = await redis.scard('session:starting');
    const poolCount = await redis.scard('pool:ready');
    const stats = await redis.hgetall('pool:stats');

    res.json({
      success: true,
      status: 'healthy',
      timestamp: new Date().toISOString(),
      sessions: {
        ready: readyCount,
        starting: startingCount,
        pool: poolCount,
        total: readyCount + startingCount
      },
      stats: {
        totalSpawned: parseInt(stats.total_spawned) || 0,
        totalAssigned: parseInt(stats.total_assigned) || 0
      },
      capacity: {
        current: readyCount + startingCount,
        max: MAX_BOTS,
        available: MAX_BOTS - (readyCount + startingCount)
      }
    });
  } catch (error) {
    console.error('[Health] Health check failed:', error);
    res.status(503).json({
      success: false,
      status: 'unhealthy',
      error: error.message,
      timestamp: new Date().toISOString()
    });
  }
});

/**
 * GET /api/sessions
 * List all active sessions (admin endpoint)
 */
app.get('/api/sessions', async (req, res) => {
  try {
    const readySessions = await redis.smembers('session:ready');
    const startingSessions = await redis.smembers('session:starting');
    const poolSessions = await redis.smembers('pool:ready');

    const allSessions = [...readySessions, ...startingSessions, ...poolSessions];

    const sessions = await Promise.all(
      allSessions.map(async (id) => {
        const data = await getSession(id);
        return { sessionId: id, ...data };
      })
    );

    res.json({
      success: true,
      count: sessions.length,
      breakdown: {
        ready: readySessions.length,
        starting: startingSessions.length,
        pool: poolSessions.length
      },
      sessions
    });
  } catch (error) {
    console.error('[API] Error listing sessions:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * GET /api/session/:id/logs
 * Get recent logs for a session (debugging)
 */
app.get('/api/session/:id/logs', async (req, res) => {
  try {
    const { id } = req.params;
    const limit = parseInt(req.query.limit) || 50;

    const logs = await redis.lrange(`agent:${id}:logs`, -limit, -1);

    res.json({
      success: true,
      sessionId: id,
      logs: logs,
      count: logs.length
    });

  } catch (error) {
    console.error('[API] Error fetching logs:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * POST /api/pool/resize
 * Resize the pre-warm pool (admin endpoint)
 */
app.post('/api/pool/resize', async (req, res) => {
  try {
    const { size } = req.body;

    if (!size || size < 0 || size > 10) {
      return res.status(400).json({
        success: false,
        error: 'Size must be between 0 and 10'
      });
    }

    await redis.set('pool:target', size);

    console.log(`[Pool] Target size updated to ${size}`);

    res.json({
      success: true,
      message: `Pre-warm pool target size set to ${size}`,
      targetSize: size
    });

  } catch (error) {
    console.error('[API] Error resizing pool:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * GET /api/voices
 *
 * List all available Inworld TTS voices with filtering options
 */
app.get('/api/voices', async (req, res) => {
  try {
    const { language, category, tier } = req.query;

    let voices = voiceCatalog.VOICE_CATALOG;

    // Apply filters
    if (language) {
      voices = voiceCatalog.getVoicesByLanguage(language);
    }

    if (category) {
      voices = voices.filter(v => v.category === category);
    }

    if (tier) {
      voices = voices.filter(v => v.tier === tier);
    }

    // Group voices by category for better UX
    const groupedVoices = voices.reduce((acc, voice) => {
      if (!acc[voice.category]) {
        acc[voice.category] = [];
      }
      acc[voice.category].push(voice);
      return acc;
    }, {});

    res.json({
      success: true,
      voices,
      groupedVoices,
      totalCount: voices.length,
      filters: {
        languages: Object.values(voiceCatalog.LANGUAGES),
        categories: ['professional', 'educational', 'character', 'assistant'],
        tiers: Object.values(voiceCatalog.VOICE_TIERS)
      }
    });

  } catch (error) {
    console.error('[API] Error fetching voices:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * GET /api/voices/:id
 *
 * Get details for a specific voice
 */
app.get('/api/voices/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const voice = voiceCatalog.getVoiceById(id);

    if (!voice) {
      return res.status(404).json({
        success: false,
        error: 'Voice not found'
      });
    }

    // Get default opening line for this voice
    const defaultOpeningLine = voiceCatalog.getDefaultOpeningLine(id);
    const previewSample = voiceCatalog.getPreviewSample(id);

    res.json({
      success: true,
      voice,
      defaultOpeningLine,
      previewSample
    });

  } catch (error) {
    console.error('[API] Error fetching voice:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * POST /api/agent/configure
 *
 * Configure voice and opening line for a user's agent
 * Stores preferences in Redis for use when spawning agents
 */
app.post('/api/agent/configure', async (req, res) => {
  try {
    const { userId, voiceId, openingLine, userTier = 'free' } = req.body;

    if (!userId) {
      return res.status(400).json({
        success: false,
        error: 'userId is required'
      });
    }

    if (!voiceId) {
      return res.status(400).json({
        success: false,
        error: 'voiceId is required'
      });
    }

    // Validate voice ID and tier access
    const voiceValidation = voiceCatalog.validateVoiceId(voiceId, userTier);
    if (!voiceValidation.valid) {
      return res.status(400).json({
        success: false,
        error: voiceValidation.error
      });
    }

    // Use provided opening line or default
    let finalOpeningLine = openingLine;
    if (!finalOpeningLine) {
      finalOpeningLine = voiceCatalog.getDefaultOpeningLine(voiceId);
    } else {
      // Validate custom opening line
      const lineValidation = voiceCatalog.validateOpeningLine(finalOpeningLine);
      if (!lineValidation.valid) {
        return res.status(400).json({
          success: false,
          error: lineValidation.error
        });
      }
    }

    // Store configuration in Redis
    const configKey = `user:${userId}:config`;
    await redis.hset(configKey, {
      voiceId,
      openingLine: finalOpeningLine,
      updatedAt: Date.now()
    });

    console.log(`[Config] User ${userId} configured: voice=${voiceId}, opening=${finalOpeningLine.substring(0, 50)}...`);

    res.json({
      success: true,
      message: 'Agent configuration saved',
      config: {
        userId,
        voiceId,
        openingLine: finalOpeningLine,
        voice: voiceValidation.voice
      }
    });

  } catch (error) {
    console.error('[API] Error configuring agent:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * GET /api/agent/configure/:userId
 *
 * Get current agent configuration for a user
 */
app.get('/api/agent/configure/:userId', async (req, res) => {
  try {
    const { userId } = req.params;

    const configKey = `user:${userId}:config`;
    const config = await redis.hgetall(configKey);

    if (!config || !config.voiceId) {
      // Return default configuration
      const defaultVoiceId = 'Ashley';
      const defaultOpeningLine = voiceCatalog.getDefaultOpeningLine(defaultVoiceId);

      return res.json({
        success: true,
        config: {
          userId,
          voiceId: defaultVoiceId,
          openingLine: defaultOpeningLine,
          voice: voiceCatalog.getVoiceById(defaultVoiceId),
          isDefault: true
        }
      });
    }

    const voice = voiceCatalog.getVoiceById(config.voiceId);

    res.json({
      success: true,
      config: {
        userId,
        voiceId: config.voiceId,
        openingLine: config.openingLine,
        voice,
        updatedAt: parseInt(config.updatedAt),
        isDefault: false
      }
    });

  } catch (error) {
    console.error('[API] Error fetching agent config:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * POST /api/voices/:id/preview
 *
 * Generate a preview audio sample for a voice
 * This returns a pre-generated preview URL or generates one on-the-fly
 */
app.post('/api/voices/:id/preview', async (req, res) => {
  try {
    const { id } = req.params;
    const { text } = req.body;

    const voice = voiceCatalog.getVoiceById(id);
    if (!voice) {
      return res.status(404).json({
        success: false,
        error: 'Voice not found'
      });
    }

    // Use provided text or default preview sample
    const previewText = text || voiceCatalog.getPreviewSample(id);

    // For now, return metadata for client-side TTS generation
    // In production, you would call Inworld TTS API here to generate actual audio
    res.json({
      success: true,
      voice,
      previewText,
      message: 'Preview generation not yet implemented. Use client-side TTS for preview.',
      // In production, this would be:
      // audioUrl: 'https://cdn.inworld.ai/previews/...',
      // duration: 3.5,
      // format: 'audio/mpeg'
    });

  } catch (error) {
    console.error('[API] Error generating preview:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

// 404 handler
app.use((req, res) => {
  res.status(404).json({
    success: false,
    error: 'Endpoint not found'
  });
});

// Error handler
app.use((err, req, res, next) => {
  console.error('[API] Unhandled error:', err);
  res.status(500).json({
    success: false,
    error: 'Internal server error'
  });
});

// Graceful shutdown
let isShuttingDown = false;

process.on('SIGTERM', async () => {
  if (isShuttingDown) return;
  isShuttingDown = true;

  console.log('[Shutdown] SIGTERM received, shutting down gracefully...');

  // Stop accepting new requests
  server.close(() => {
    console.log('[Shutdown] HTTP server closed');
  });

  // Close Redis connection
  try {
    await redis.quit();
    console.log('[Shutdown] Redis connection closed');
  } catch (error) {
    console.error('[Shutdown] Error closing Redis:', error);
  }

  process.exit(0);
});

process.on('SIGINT', async () => {
  if (isShuttingDown) return;
  isShuttingDown = true;

  console.log('[Shutdown] SIGINT received, shutting down gracefully...');

  server.close(() => {
    console.log('[Shutdown] HTTP server closed');
  });

  try {
    await redis.quit();
    console.log('[Shutdown] Redis connection closed');
  } catch (error) {
    console.error('[Shutdown] Error closing Redis:', error);
  }

  process.exit(0);
});

// Start server
const server = app.listen(PORT, () => {
  console.log('='.repeat(60));
  console.log('[Orchestrator] Celery-based Voice Agent Orchestrator');
  console.log('='.repeat(60));
  console.log(`[Server] Listening on port ${PORT}`);
  console.log(`[Redis] Connected to ${process.env.REDIS_URL ? 'Railway Redis' : 'localhost:6379'}`);
  console.log(`[LiveKit] URL: ${LIVEKIT_URL}`);
  console.log(`[Config] Max bots: ${MAX_BOTS}`);
  console.log(`[Config] Rate limit: ${RATE_LIMIT_MAX_REQUESTS} req/${RATE_LIMIT_WINDOW}s`);
  console.log('='.repeat(60));
});

module.exports = app;
