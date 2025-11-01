// simple-orchestrator.js
// Simple multi-process bot manager for <50 concurrent users

const express = require('express');
const cors = require('cors');
const { spawn } = require('child_process');
const { AccessToken } = require('livekit-server-sdk');
const path = require('path');
const fs = require('fs');
require('dotenv').config();

// Import voice catalog
const voiceCatalog = require('./voices-catalog');

// ==================== ENVIRONMENT VALIDATION ====================
function validateEnvironment() {
  const required = ['LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET', 'LIVEKIT_URL'];
  const missing = required.filter(key => !process.env[key]);

  if (missing.length > 0) {
    console.error(`[Bot Manager] FATAL: Missing required environment variables: ${missing.join(', ')}`);
    console.error('[Bot Manager] Please check your .env file and ensure all required variables are set.');
    process.exit(1);
  }

  // Validate URL format
  const urlPattern = /^wss?:\/\/.+/;
  if (!urlPattern.test(process.env.LIVEKIT_URL)) {
    console.error(`[Bot Manager] FATAL: LIVEKIT_URL must be a valid WebSocket URL (ws:// or wss://). Got: ${process.env.LIVEKIT_URL}`);
    process.exit(1);
  }

  console.log('[Bot Manager] ✓ Environment variables validated');
}

validateEnvironment();

const app = express();

// ==================== SECURITY MIDDLEWARE ====================
// Configure CORS with restrictions
const allowedOrigins = process.env.ALLOWED_ORIGINS
  ? process.env.ALLOWED_ORIGINS.split(',')
  : ['http://localhost:3000', 'http://localhost:5173']; // Vite default

app.use(cors({
  origin: (origin, callback) => {
    // Allow requests with no origin (mobile apps, curl, etc.)
    if (!origin) return callback(null, true);

    // Allow all origins if ALLOW_ALL_ORIGINS is set to 'true' (for testing only!)
    if (process.env.ALLOW_ALL_ORIGINS === 'true') {
      return callback(null, true);
    }

    if (allowedOrigins.indexOf(origin) !== -1 || process.env.NODE_ENV === 'development') {
      callback(null, true);
    } else {
      callback(new Error('Not allowed by CORS'));
    }
  },
  credentials: true,
  maxAge: 86400 // 24 hours
}));

// Limit request body size to prevent DoS
app.use(express.json({ limit: '10kb' }));

// Request timeout middleware
app.use((req, res, next) => {
  req.setTimeout(30000); // 30 second timeout
  res.setTimeout(30000);
  next();
});

// ==================== CONFIGURATION ====================
const MAX_BOTS = parseInt(process.env.MAX_BOTS) || 50;
const SESSION_TIMEOUT = parseInt(process.env.SESSION_TIMEOUT) || 30 * 60 * 1000;
const BOT_STARTUP_TIMEOUT = parseInt(process.env.BOT_STARTUP_TIMEOUT) || 20000;
const MAX_LOG_ENTRIES = 1000; // Prevent memory leaks from log accumulation
const PYTHON_SCRIPT_PATH = path.join(__dirname, '../voice_assistant.py');

// Validate Python script exists
if (!fs.existsSync(PYTHON_SCRIPT_PATH)) {
  console.error(`[Bot Manager] FATAL: Python script not found at: ${PYTHON_SCRIPT_PATH}`);
  process.exit(1);
}

// Store active bot processes
const activeBots = new Map();
const sessionTimers = new Map();

// In-memory store for user voice configurations
const userConfigs = new Map();

// Rate limiting: track requests per IP
const rateLimitMap = new Map();
const RATE_LIMIT_WINDOW = 60000; // 1 minute
const MAX_REQUESTS_PER_WINDOW = 10;

// LiveKit credentials
const LIVEKIT_API_KEY = process.env.LIVEKIT_API_KEY;
const LIVEKIT_API_SECRET = process.env.LIVEKIT_API_SECRET;
const LIVEKIT_URL = process.env.LIVEKIT_URL;

// ==================== HELPER FUNCTIONS ====================

// Rate limiting middleware
function rateLimitMiddleware(req, res, next) {
  const ip = req.ip || req.connection.remoteAddress;
  const now = Date.now();

  if (!rateLimitMap.has(ip)) {
    rateLimitMap.set(ip, []);
  }

  const requests = rateLimitMap.get(ip);
  // Remove old requests outside the window
  const recentRequests = requests.filter(time => now - time < RATE_LIMIT_WINDOW);
  rateLimitMap.set(ip, recentRequests);

  if (recentRequests.length >= MAX_REQUESTS_PER_WINDOW) {
    return res.status(429).json({
      error: 'Too many requests',
      message: 'Please wait a moment before trying again',
      retryAfter: Math.ceil(RATE_LIMIT_WINDOW / 1000)
    });
  }

  recentRequests.push(now);
  next();
}

// Input validation helpers
function sanitizeString(str, maxLength = 100) {
  if (typeof str !== 'string') return '';
  // Remove control characters and limit length
  return str.replace(/[\x00-\x1F\x7F]/g, '').substring(0, maxLength).trim();
}

function validateSessionId(sessionId) {
  if (!sessionId || typeof sessionId !== 'string') {
    return { valid: false, error: 'Session ID is required' };
  }
  if (!/^session-\d+-[a-z0-9]{6}$/.test(sessionId)) {
    return { valid: false, error: 'Invalid session ID format' };
  }
  return { valid: true };
}

// Simple session ID generator with collision resistance
function generateSessionId() {
  const timestamp = Date.now();
  const random = Math.random().toString(36).substring(2, 8);
  const sessionId = `session-${timestamp}-${random}`;

  // Ensure uniqueness (extremely rare but possible collision)
  if (activeBots.has(sessionId)) {
    return generateSessionId(); // Recursively try again
  }

  return sessionId;
}

// Bot process management
class BotProcess {
  constructor(sessionId, userId) {
    this.sessionId = sessionId;
    this.userId = userId;
    this.process = null;
    this.startTime = Date.now();
    this.status = 'starting';
    this.logs = [];
    this.retryCount = 0;
    this.maxRetries = 2;
    this.lastError = null;
    this.isShuttingDown = false;
  }

  addLog(type, message) {
    const logEntry = { type, message, timestamp: Date.now() };
    this.logs.push(logEntry);

    // Prevent memory leak: keep only recent logs
    if (this.logs.length > MAX_LOG_ENTRIES) {
      this.logs = this.logs.slice(-MAX_LOG_ENTRIES);
    }
  }

  async start() {
    return new Promise((resolve, reject) => {
      console.log(`[Bot Manager] Starting bot for session: ${this.sessionId} (attempt ${this.retryCount + 1}/${this.maxRetries + 1})`);

      try {
        // Get user's voice configuration
        const userConfig = userConfigs.get(this.userId);
        const voiceId = userConfig?.voiceId || 'Ashley';
        const openingLine = userConfig?.openingLine || voiceCatalog.getDefaultOpeningLine(voiceId);

        console.log(`[Bot Manager] Using voice: ${voiceId} for user: ${this.userId}`);

        // Build command arguments
        const args = [
          PYTHON_SCRIPT_PATH,
          '--room', this.sessionId,
          '--voice-id', voiceId
        ];

        // Add opening line if customized
        if (openingLine) {
          args.push('--opening-line', openingLine);
        }

        // Spawn Python bot process with proper error handling
        this.process = spawn('python3', args, {
          env: {
            ...process.env,
            PYTHONUNBUFFERED: '1',  // Get real-time output
          },
          cwd: path.join(__dirname, '..'),  // Run from parent directory
          stdio: ['ignore', 'pipe', 'pipe'], // Proper stdio configuration
          detached: false, // Keep as child process for proper cleanup
        });

        // Ensure process was created
        if (!this.process || !this.process.pid) {
          throw new Error('Failed to spawn Python process');
        }

        console.log(`[Bot Manager] Bot process spawned with PID: ${this.process.pid}`);
      } catch (spawnError) {
        console.error(`[Bot Manager] Failed to spawn process:`, spawnError);
        this.status = 'error';
        this.lastError = spawnError.message;
        return reject(new Error(`Failed to spawn bot process: ${spawnError.message}`));
      }

      // Track if we've resolved
      let hasResolved = false;
      let startupTimer = null;

      // Capture stdout
      this.process.stdout.on('data', (data) => {
        const log = data.toString();
        console.log(`[Bot ${this.sessionId.substring(0, 20)}...]: ${log}`);
        this.addLog('stdout', log);

        // Also check for connection in stdout
        if (!hasResolved && (
          log.includes('Connected to') ||
          log.includes('LiveKitOutputTransport started') ||
          log.includes('Audio input task started')
        )) {
          this.status = 'active';
          hasResolved = true;
          if (startupTimer) clearTimeout(startupTimer);
          console.log(`[Bot Manager] Bot connected successfully for session: ${this.sessionId}`);
          resolve(true);
        }
      });

      // Capture stderr (Pipecat logs to stderr)
      this.process.stderr.on('data', (data) => {
        const log = data.toString();
        console.error(`[Bot ${this.sessionId.substring(0, 20)}...]: ${log}`);
        this.addLog('stderr', log);

        // Check multiple connection indicators (case-sensitive!)
        if (!hasResolved && (
          log.includes('Connected to') ||  // This is what actually appears in your logs
          log.includes('Room joined') ||
          log.includes('LiveKitInputTransport started') ||
          log.includes('LiveKitOutputTransport started') ||
          log.includes('Audio input task started') ||
          log.includes('pipeline is now ready')
        )) {
          this.status = 'active';
          hasResolved = true;
          if (startupTimer) clearTimeout(startupTimer);
          console.log(`[Bot Manager] Bot connected successfully for session: ${this.sessionId}`);
          resolve(true);
        }

        // Detect critical errors early
        if (!hasResolved && (
          log.includes('FATAL') ||
          log.includes('cannot import') ||
          log.includes('ModuleNotFoundError') ||
          log.includes('Invalid API key')
        )) {
          this.status = 'error';
          this.lastError = log;
          hasResolved = true;
          if (startupTimer) clearTimeout(startupTimer);
          console.error(`[Bot Manager] Bot startup error for session: ${this.sessionId}`);
          reject(new Error('Bot encountered a startup error. Check logs for details.'));
        }
      });

      // Handle process exit
      this.process.on('close', (code, signal) => {
        console.log(`[Bot Manager] Bot ${this.sessionId} exited with code ${code}, signal ${signal}`);

        if (code !== 0 && code !== null && !this.isShuttingDown) {
          this.lastError = `Process exited with code ${code}`;
          if (!hasResolved) {
            hasResolved = true;
            if (startupTimer) clearTimeout(startupTimer);
            reject(new Error(`Bot process exited unexpectedly with code ${code}`));
          }
        }

        this.status = 'stopped';
        this.cleanup();
      });

      // Handle errors
      this.process.on('error', (error) => {
        console.error(`[Bot Manager] Process error for ${this.sessionId}: ${error.message}`);
        this.status = 'error';
        this.lastError = error.message;

        if (!hasResolved) {
          hasResolved = true;
          if (startupTimer) clearTimeout(startupTimer);
          reject(error);
        }
      });

      // Startup timeout with configurable duration
      startupTimer = setTimeout(() => {
        if (!hasResolved) {
          this.status = 'timeout';
          this.lastError = 'Connection timeout';
          hasResolved = true;
          console.error(`[Bot Manager] Bot connection timeout for session: ${this.sessionId}`);

          // Kill the hung process
          if (this.process && !this.process.killed) {
            this.process.kill('SIGTERM');
          }

          reject(new Error(`Bot failed to connect within ${BOT_STARTUP_TIMEOUT / 1000} seconds`));
        }
      }, BOT_STARTUP_TIMEOUT);
    });
  }

  stop() {
    this.isShuttingDown = true;
    console.log(`[Bot Manager] Stopping bot for session: ${this.sessionId}`);

    if (this.process && !this.process.killed) {
      try {
        // Try graceful shutdown first
        this.process.kill('SIGTERM');

        // Force kill after 5 seconds if still running
        const forceKillTimer = setTimeout(() => {
          if (this.process && !this.process.killed) {
            console.warn(`[Bot Manager] Force killing bot ${this.sessionId} after timeout`);
            try {
              this.process.kill('SIGKILL');
            } catch (err) {
              console.error(`[Bot Manager] Error force killing process: ${err.message}`);
            }
          }
        }, 5000);

        // Clean up the force kill timer if process exits normally
        this.process.once('exit', () => {
          clearTimeout(forceKillTimer);
        });
      } catch (err) {
        console.error(`[Bot Manager] Error stopping bot ${this.sessionId}: ${err.message}`);
      }
    }

    this.status = 'stopped';
    this.cleanup();
  }

  cleanup() {
    console.log(`[Bot Manager] Cleaning up session: ${this.sessionId}`);

    // Remove from active bots
    activeBots.delete(this.sessionId);

    // Clear session timer
    if (sessionTimers.has(this.sessionId)) {
      clearTimeout(sessionTimers.get(this.sessionId));
      sessionTimers.delete(this.sessionId);
    }

    // Remove event listeners to prevent memory leaks
    if (this.process) {
      try {
        this.process.stdout?.removeAllListeners();
        this.process.stderr?.removeAllListeners();
        this.process.removeAllListeners();
      } catch (err) {
        console.error(`[Bot Manager] Error removing listeners: ${err.message}`);
      }
    }
  }

  getInfo() {
    return {
      sessionId: this.sessionId,
      userId: this.userId,
      status: this.status,
      startTime: this.startTime,
      uptime: Date.now() - this.startTime,
      pid: this.process ? this.process.pid : null,
      retryCount: this.retryCount,
      lastError: this.lastError,
    };
  }
}

// API endpoint to start a new bot session
app.post('/api/session/start', rateLimitMiddleware, async (req, res) => {
  try {
    // Input validation and sanitization
    const userId = sanitizeString(req.body?.userId, 50) || `user-${Date.now()}`;
    const userName = sanitizeString(req.body?.userName, 50) || 'Guest';

    // Check if we've reached the bot limit
    if (activeBots.size >= MAX_BOTS) {
      return res.status(503).json({
        error: 'Server at capacity',
        message: 'Too many active sessions. Please try again in a few minutes.',
        retryAfter: 60
      });
    }

    // Generate unique session ID
    const sessionId = generateSessionId();

    // Create bot process
    const bot = new BotProcess(sessionId, userId);
    activeBots.set(sessionId, bot);

    console.log(`[Bot Manager] Starting session ${sessionId} for user: ${userId} (${userName})`);

    // Try to start the bot
    try {
      await bot.start();

      // Set auto-cleanup timer
      const timer = setTimeout(() => {
        console.log(`[Bot Manager] Auto-stopping inactive session: ${sessionId}`);
        if (activeBots.has(sessionId)) {
          bot.stop();
        }
      }, SESSION_TIMEOUT);
      sessionTimers.set(sessionId, timer);

      res.json({
        success: true,
        sessionId: sessionId,
        message: 'Bot started successfully',
        info: bot.getInfo()
      });

    } catch (error) {
      // Failed to start bot - clean up
      console.error(`[Bot Manager] Failed to start bot for session ${sessionId}:`, error.message);
      bot.cleanup();

      res.status(500).json({
        error: 'Failed to start bot',
        message: process.env.NODE_ENV === 'production'
          ? 'Unable to start voice assistant. Please try again.'
          : error.message
      });
    }

  } catch (error) {
    console.error('[Bot Manager] Error in start session:', error);
    res.status(500).json({
      error: 'Internal server error',
      message: process.env.NODE_ENV === 'production'
        ? 'An unexpected error occurred'
        : error.message
    });
  }
});

// API endpoint to stop a bot session
app.post('/api/session/stop', rateLimitMiddleware, (req, res) => {
  try {
    const sessionId = sanitizeString(req.body?.sessionId, 100);

    // Validate session ID format
    const validation = validateSessionId(sessionId);
    if (!validation.valid) {
      return res.status(400).json({
        error: 'Invalid input',
        message: validation.error
      });
    }

    const bot = activeBots.get(sessionId);
    if (bot) {
      bot.stop();
      console.log(`[Bot Manager] Session ${sessionId} stopped by user request`);
      res.json({
        success: true,
        message: 'Bot stopped successfully'
      });
    } else {
      res.status(404).json({
        error: 'Session not found',
        message: 'No active bot found for this session'
      });
    }
  } catch (error) {
    console.error('[Bot Manager] Error in stop session:', error);
    res.status(500).json({
      error: 'Failed to stop bot',
      message: process.env.NODE_ENV === 'production'
        ? 'Unable to stop session'
        : error.message
    });
  }
});

// API endpoint to generate user token
app.post('/api/token', rateLimitMiddleware, async (req, res) => {
  try {
    const sessionId = sanitizeString(req.body?.sessionId, 100);
    const userName = sanitizeString(req.body?.userName, 50) || `user-${Date.now()}`;

    // Validate session ID format
    const validation = validateSessionId(sessionId);
    if (!validation.valid) {
      return res.status(400).json({
        error: 'Invalid input',
        message: validation.error
      });
    }

    // Verify bot exists for this session and is active
    const bot = activeBots.get(sessionId);
    if (!bot) {
      return res.status(404).json({
        error: 'Invalid session',
        message: 'No bot found for this session. Please start a session first.'
      });
    }

    // Check if bot is still connecting
    if (bot.status !== 'active') {
      return res.status(503).json({
        error: 'Bot not ready',
        message: `Bot is ${bot.status}. Please wait a moment and try again.`,
        retryAfter: 5
      });
    }

    // Create user token for the session room
    const token = new AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET, {
      identity: userName,
      ttl: '2h',
    });

    token.addGrant({
      room: sessionId,  // Use session ID as room name
      roomJoin: true,
      canPublish: true,
      canSubscribe: true,
      canPublishData: true,
    });

    const jwt = await token.toJwt();

    console.log(`[Bot Manager] Generated token for user ${userName} in session ${sessionId}`);

    res.json({
      token: jwt,
      url: LIVEKIT_URL,
      sessionId: sessionId,
    });

  } catch (error) {
    console.error('[Bot Manager] Error generating token:', error);
    res.status(500).json({
      error: 'Failed to generate token',
      message: process.env.NODE_ENV === 'production'
        ? 'Unable to generate access token'
        : error.message
    });
  }
});

// API endpoint to get session info
app.get('/api/session/:sessionId', rateLimitMiddleware, (req, res) => {
  try {
    const sessionId = sanitizeString(req.params?.sessionId, 100);

    const validation = validateSessionId(sessionId);
    if (!validation.valid) {
      return res.status(400).json({
        error: 'Invalid input',
        message: validation.error
      });
    }

    const bot = activeBots.get(sessionId);
    if (!bot) {
      return res.status(404).json({ error: 'Session not found' });
    }

    res.json(bot.getInfo());
  } catch (error) {
    console.error('[Bot Manager] Error getting session info:', error);
    res.status(500).json({
      error: 'Internal server error',
      message: process.env.NODE_ENV === 'production' ? 'Unable to retrieve session info' : error.message
    });
  }
});

// API endpoint to get all active sessions
app.get('/api/sessions', rateLimitMiddleware, (req, res) => {
  try {
    const sessions = Array.from(activeBots.values()).map(bot => bot.getInfo());
    res.json({
      total: sessions.length,
      maxCapacity: MAX_BOTS,
      available: MAX_BOTS - sessions.length,
      utilizationPercent: Math.round((sessions.length / MAX_BOTS) * 100),
      sessions: sessions
    });
  } catch (error) {
    console.error('[Bot Manager] Error getting sessions:', error);
    res.status(500).json({
      error: 'Internal server error',
      message: process.env.NODE_ENV === 'production' ? 'Unable to retrieve sessions' : error.message
    });
  }
});

// ==================== VOICE CUSTOMIZATION ENDPOINTS ====================

// GET /api/voices - List all available voices with optional filtering
app.get('/api/voices', rateLimitMiddleware, async (req, res) => {
  try {
    const { language, category, tier } = req.query;

    // Start with all voices
    let voices = [...voiceCatalog.VOICE_CATALOG];

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

    // Group voices by category
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
      availableLanguages: voiceCatalog.getAvailableLanguages(),
      availableCategories: voiceCatalog.getAvailableCategories()
    });
  } catch (error) {
    console.error('[Bot Manager] Error fetching voices:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to fetch voices'
    });
  }
});

// GET /api/voices/:id - Get details for a specific voice
app.get('/api/voices/:id', rateLimitMiddleware, async (req, res) => {
  try {
    const voiceId = req.params.id;
    const voice = voiceCatalog.getVoiceById(voiceId);

    if (!voice) {
      return res.status(404).json({
        success: false,
        error: 'Voice not found'
      });
    }

    const defaultOpeningLine = voiceCatalog.getDefaultOpeningLine(voiceId);
    const previewSample = voiceCatalog.getPreviewSample(voiceId);

    res.json({
      success: true,
      voice,
      defaultOpeningLine,
      previewSample
    });
  } catch (error) {
    console.error('[Bot Manager] Error fetching voice:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to fetch voice details'
    });
  }
});

// POST /api/agent/configure - Save user's voice configuration
app.post('/api/agent/configure', rateLimitMiddleware, async (req, res) => {
  try {
    const { userId, voiceId, openingLine, userTier = 'free' } = req.body;

    // Validation
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

    // Validate voice exists and user has access
    const voiceValidation = voiceCatalog.validateVoiceId(voiceId, userTier);
    if (!voiceValidation.valid) {
      return res.status(400).json({
        success: false,
        error: voiceValidation.error
      });
    }

    // Use default opening line if not provided
    let finalOpeningLine = openingLine || voiceCatalog.getDefaultOpeningLine(voiceId);

    // Validate opening line
    const lineValidation = voiceCatalog.validateOpeningLine(finalOpeningLine);
    if (!lineValidation.valid) {
      return res.status(400).json({
        success: false,
        error: lineValidation.error
      });
    }

    // Store configuration in memory
    userConfigs.set(userId, {
      voiceId,
      openingLine: finalOpeningLine,
      updatedAt: Date.now()
    });

    console.log(`[Bot Manager] Saved voice config for user ${userId}: ${voiceId}`);

    res.json({
      success: true,
      message: 'Agent configuration saved',
      config: {
        userId,
        voiceId,
        openingLine: finalOpeningLine,
        voice: voiceValidation.voice,
        updatedAt: Date.now()
      }
    });
  } catch (error) {
    console.error('[Bot Manager] Error saving configuration:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to save configuration'
    });
  }
});

// GET /api/agent/configure/:userId - Get user's voice configuration
app.get('/api/agent/configure/:userId', rateLimitMiddleware, async (req, res) => {
  try {
    const userId = req.params.userId;
    const config = userConfigs.get(userId);

    if (!config) {
      // Return default configuration
      const defaultVoice = voiceCatalog.getVoiceById('Ashley');
      return res.json({
        success: true,
        config: {
          userId,
          voiceId: 'Ashley',
          openingLine: voiceCatalog.getDefaultOpeningLine('Ashley'),
          voice: defaultVoice,
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
        updatedAt: config.updatedAt,
        isDefault: false
      }
    });
  } catch (error) {
    console.error('[Bot Manager] Error fetching configuration:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to fetch configuration'
    });
  }
});

// Health check endpoint (no rate limiting for monitoring)
app.get('/api/health', (req, res) => {
  try {
    const memUsage = process.memoryUsage();
    res.json({
      status: 'healthy',
      timestamp: new Date().toISOString(),
      activeBots: activeBots.size,
      maxBots: MAX_BOTS,
      uptime: Math.floor(process.uptime()),
      memory: {
        heapUsedMB: Math.round(memUsage.heapUsed / 1024 / 1024),
        heapTotalMB: Math.round(memUsage.heapTotal / 1024 / 1024),
        rssMB: Math.round(memUsage.rss / 1024 / 1024),
      },
      environment: {
        nodeVersion: process.version,
        platform: process.platform,
      }
    });
  } catch (error) {
    console.error('[Bot Manager] Error in health check:', error);
    res.status(500).json({
      status: 'unhealthy',
      error: error.message
    });
  }
});

// ==================== GRACEFUL SHUTDOWN ====================
let isShuttingDown = false;

async function gracefulShutdown(signal) {
  if (isShuttingDown) {
    console.log('[Bot Manager] Shutdown already in progress...');
    return;
  }

  isShuttingDown = true;
  console.log(`[Bot Manager] Received ${signal}, starting graceful shutdown...`);

  // Stop accepting new requests
  server.close(() => {
    console.log('[Bot Manager] HTTP server closed');
  });

  // Stop all bots
  const stopPromises = [];
  activeBots.forEach((bot) => {
    console.log(`[Bot Manager] Stopping bot ${bot.sessionId}...`);
    bot.stop();
  });

  // Wait a bit for processes to terminate gracefully
  await new Promise(resolve => setTimeout(resolve, 2000));

  // Force exit if still running
  const stillActive = activeBots.size;
  if (stillActive > 0) {
    console.warn(`[Bot Manager] ${stillActive} bots still active, forcing shutdown`);
  }

  console.log('[Bot Manager] Shutdown complete');
  process.exit(0);
}

process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT', () => gracefulShutdown('SIGINT'));

// Handle uncaught errors
process.on('uncaughtException', (error) => {
  console.error('[Bot Manager] Uncaught exception:', error);
  gracefulShutdown('uncaughtException');
});

process.on('unhandledRejection', (reason, promise) => {
  console.error('[Bot Manager] Unhandled rejection at:', promise, 'reason:', reason);
  // Don't exit on unhandled rejection, just log it
});

// ==================== START SERVER ====================
const PORT = process.env.PORT || 8080;
const server = app.listen(PORT, () => {
  console.log(`
╔════════════════════════════════════════╗
║     Bot Orchestrator Running           ║
║     Port: ${PORT}                          ║
║     Max Concurrent Bots: ${MAX_BOTS}          ║
║     Session Timeout: ${Math.floor(SESSION_TIMEOUT / 60000)} minutes        ║
║     Environment: ${process.env.NODE_ENV || 'development'}       ║
╚════════════════════════════════════════╝
  `);
  console.log('[Bot Manager] Ready to accept connections');
});

// Handle server errors
server.on('error', (error) => {
  console.error('[Bot Manager] Server error:', error);
  if (error.code === 'EADDRINUSE') {
    console.error(`[Bot Manager] Port ${PORT} is already in use`);
    process.exit(1);
  }
});