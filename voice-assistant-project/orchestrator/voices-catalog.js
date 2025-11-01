/**
 * Inworld TTS Voice Catalog
 *
 * Voice metadata including licensing tiers, languages, and characteristics.
 * Updated from Inworld TTS-1 Demo (https://inworld-ai.github.io/tts/)
 */

const VOICE_TIERS = {
  FREE: 'free',
  PREMIUM: 'premium',
  ENTERPRISE: 'enterprise'
};

const LANGUAGES = {
  EN: 'en',
  ZH: 'zh',
  ES: 'es',
  FR: 'fr',
  KO: 'ko',
  NL: 'nl',
  JA: 'ja',
  DE: 'de',
  IT: 'it',
  PL: 'pl',
  PT: 'pt'
};

const VOICE_CATALOG = [
  // English Voices - Professional/News
  {
    id: 'Ashley',
    name: 'Ashley',
    language: LANGUAGES.EN,
    gender: 'female',
    age: 'adult',
    description: 'TV Host - Delivers news and podcast introductions with enthusiasm',
    category: 'professional',
    tier: VOICE_TIERS.FREE,
    previewUrl: null, // Will be generated via TTS API
    tags: ['news', 'podcast', 'enthusiastic', 'tv-host']
  },
  {
    id: 'Mark',
    name: 'Mark',
    language: LANGUAGES.EN,
    gender: 'male',
    age: 'adult',
    description: 'TV Host - Tech-focused content with excitement and engagement',
    category: 'professional',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['tech', 'enthusiastic', 'engaging', 'tv-host']
  },
  {
    id: 'Deborah',
    name: 'Deborah',
    language: LANGUAGES.EN,
    gender: 'female',
    age: 'adult',
    description: 'News Anchor - Professional news updates and announcements',
    category: 'professional',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['news', 'formal', 'professional', 'anchor']
  },

  // English Voices - Educational
  {
    id: 'Alex',
    name: 'Alex',
    language: LANGUAGES.EN,
    gender: 'male',
    age: 'adult',
    description: 'Teacher - Chemistry lessons with curiosity and clarity',
    category: 'educational',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['teacher', 'educational', 'clear', 'science']
  },
  {
    id: 'Olivia',
    name: 'Olivia',
    language: LANGUAGES.EN,
    gender: 'female',
    age: 'adult',
    description: 'Teacher - Mathematics instruction with pedagogical focus',
    category: 'educational',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['teacher', 'educational', 'math', 'clear']
  },
  {
    id: 'Edward',
    name: 'Edward',
    language: LANGUAGES.EN,
    gender: 'male',
    age: 'adult',
    description: 'Instructor - Educational content about science topics',
    category: 'educational',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['instructor', 'educational', 'science', 'formal']
  },

  // English Voices - Character/Narrative
  {
    id: 'Sarah',
    name: 'Sarah',
    language: LANGUAGES.EN,
    gender: 'female',
    age: 'adult',
    description: 'Adventurer - Fantasy narration with excitement',
    category: 'character',
    tier: VOICE_TIERS.PREMIUM,
    previewUrl: null,
    tags: ['fantasy', 'exciting', 'adventurous', 'storytelling']
  },
  {
    id: 'Hades',
    name: 'Hades',
    language: LANGUAGES.EN,
    gender: 'male',
    age: 'adult',
    description: 'Dark Character - Ominous, dark dialogue delivery',
    category: 'character',
    tier: VOICE_TIERS.PREMIUM,
    previewUrl: null,
    tags: ['dark', 'ominous', 'character', 'dramatic']
  },
  {
    id: 'Theodore',
    name: 'Theodore',
    language: LANGUAGES.EN,
    gender: 'male',
    age: 'adult',
    description: 'Detective - Mystery storytelling with suspenseful tone',
    category: 'character',
    tier: VOICE_TIERS.PREMIUM,
    previewUrl: null,
    tags: ['mystery', 'suspenseful', 'detective', 'storytelling']
  },
  {
    id: 'Julia',
    name: 'Julia',
    language: LANGUAGES.EN,
    gender: 'female',
    age: 'adult',
    description: 'Friend - Conspiratorial whisper, sharing secrets',
    category: 'character',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['friendly', 'conspiratorial', 'casual', 'whisper']
  },
  {
    id: 'Wendy',
    name: 'Wendy',
    language: LANGUAGES.EN,
    gender: 'female',
    age: 'adult',
    description: 'Critic - Judgmental, disapproving tone',
    category: 'character',
    tier: VOICE_TIERS.PREMIUM,
    previewUrl: null,
    tags: ['judgmental', 'critical', 'character']
  },

  // English Voices - Service/Assistant
  {
    id: 'Elizabeth',
    name: 'Elizabeth',
    language: LANGUAGES.EN,
    gender: 'female',
    age: 'adult',
    description: 'Assistant - Helpful, professional assistant responses',
    category: 'assistant',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['assistant', 'helpful', 'professional', 'friendly']
  },
  {
    id: 'Timothy',
    name: 'Timothy',
    language: LANGUAGES.EN,
    gender: 'male',
    age: 'teen',
    description: 'Customer Service - Professional service confirmations',
    category: 'assistant',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['customer-service', 'professional', 'helpful']
  },

  // Chinese Voices
  {
    id: 'Jing',
    name: 'Jing',
    language: LANGUAGES.ZH,
    gender: 'female',
    age: 'adult',
    description: 'Assistant - Helpful assistance in Mandarin',
    category: 'assistant',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['assistant', 'helpful', 'mandarin']
  },
  {
    id: 'Xinyi',
    name: 'Xinyi',
    language: LANGUAGES.ZH,
    gender: 'female',
    age: 'adult',
    description: 'News Anchor - International news updates in Mandarin',
    category: 'professional',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['news', 'professional', 'mandarin', 'anchor']
  },
  {
    id: 'Yichen',
    name: 'Yichen',
    language: LANGUAGES.ZH,
    gender: 'male',
    age: 'adult',
    description: 'Storyteller - Mysterious tales in Mandarin',
    category: 'character',
    tier: VOICE_TIERS.PREMIUM,
    previewUrl: null,
    tags: ['storytelling', 'mysterious', 'mandarin']
  },

  // Spanish Voices
  {
    id: 'Diego',
    name: 'Diego',
    language: LANGUAGES.ES,
    gender: 'male',
    age: 'adult',
    description: 'Customer Service - Professional problem resolution in Spanish',
    category: 'assistant',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['customer-service', 'professional', 'spanish']
  },
  {
    id: 'Lupita',
    name: 'Lupita',
    language: LANGUAGES.ES,
    gender: 'female',
    age: 'adult',
    description: 'Friend - Casual, friendly conversation in Spanish',
    category: 'character',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['friendly', 'casual', 'spanish']
  },
  {
    id: 'Miguel',
    name: 'Miguel',
    language: LANGUAGES.ES,
    gender: 'male',
    age: 'adult',
    description: 'Host - Creative exploration content in Spanish',
    category: 'professional',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['host', 'creative', 'spanish']
  },

  // French Voices
  {
    id: 'Hélène',
    name: 'Hélène',
    language: LANGUAGES.FR,
    gender: 'female',
    age: 'adult',
    description: 'Friend - Friendly, conversational tone in French',
    category: 'character',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['friendly', 'casual', 'french']
  },
  {
    id: 'Mathieu',
    name: 'Mathieu',
    language: LANGUAGES.FR,
    gender: 'male',
    age: 'adult',
    description: 'Host - Scientific mysteries podcast in French',
    category: 'professional',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['host', 'science', 'podcast', 'french']
  },

  // Korean Voices
  {
    id: 'Hyunwoo',
    name: 'Hyunwoo',
    language: LANGUAGES.KO,
    gender: 'male',
    age: 'adult',
    description: 'Host - Welcoming Q&A host in Korean',
    category: 'professional',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['host', 'welcoming', 'korean']
  },
  {
    id: 'Yoona',
    name: 'Yoona',
    language: LANGUAGES.KO,
    gender: 'female',
    age: 'adult',
    description: 'Customer Service - Apologetic, solution-focused support in Korean',
    category: 'assistant',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['customer-service', 'helpful', 'korean']
  },

  // Dutch Voices
  {
    id: 'Lore',
    name: 'Lore',
    language: LANGUAGES.NL,
    gender: 'female',
    age: 'adult',
    description: 'Customer Service - Empathetic problem-solving in Dutch',
    category: 'assistant',
    tier: VOICE_TIERS.FREE,
    previewUrl: null,
    tags: ['customer-service', 'empathetic', 'dutch']
  }
];

/**
 * Default opening lines for different voice personas
 */
const DEFAULT_OPENING_LINES = {
  Ashley: "Hello! I'm Ashley, your AI assistant. How can I help you today?",
  Mark: "Hey there! I'm Mark. What can I do for you?",
  Deborah: "Good day. I'm here to assist you. What would you like to know?",
  Alex: "Hi! I'm Alex. I'm here to help explain things clearly. What's on your mind?",
  Olivia: "Hello! I'm Olivia. Let's work through this together. What can I help with?",
  Edward: "Greetings. I'm Edward, ready to assist with your questions.",
  Sarah: "Hey! Ready for an adventure? What shall we explore today?",
  Hades: "Welcome... I've been expecting you. What do you seek?",
  Theodore: "Good evening. The game is afoot. What mystery shall we unravel?",
  Julia: "Psst! Come closer, I've got something to tell you. What's up?",
  Wendy: "Well, well... what do we have here? What do you want?",
  Elizabeth: "Hello! I'm Elizabeth, your personal assistant. How may I help you?",
  Timothy: "Hi there! I'm Timothy from support. What can I help you with today?",
  Jing: "你好！我是Jing。我能帮你什么？",
  Xinyi: "大家好。我是Xinyi。有什么可以帮助你的吗？",
  Yichen: "你好。我是Yichen。让我们开始吧。",
  Diego: "¡Hola! Soy Diego. ¿En qué puedo ayudarte hoy?",
  Lupita: "¡Hola amigo! Soy Lupita. ¿Qué tal?",
  Miguel: "¡Hola! Soy Miguel. ¿Qué te gustaría explorar hoy?",
  Hélène: "Bonjour! Je suis Hélène. Comment puis-je vous aider?",
  Mathieu: "Bonjour! Je suis Mathieu. Que puis-je faire pour vous?",
  Hyunwoo: "안녕하세요! 저는 Hyunwoo입니다. 무엇을 도와드릴까요?",
  Yoona: "안녕하세요. 저는 Yoona입니다. 도움이 필요하신가요?",
  Lore: "Hallo! Ik ben Lore. Hoe kan ik je helpen?"
};

/**
 * Voice preview text samples for testing
 */
const PREVIEW_SAMPLES = {
  default: "Hello! This is a sample of my voice. I'm here to help you with whatever you need. How does this sound?",
  zh: "你好！这是我的声音样本。我在这里帮助你。你觉得怎么样？",
  es: "¡Hola! Esta es una muestra de mi voz. Estoy aquí para ayudarte. ¿Qué te parece?",
  fr: "Bonjour! Ceci est un échantillon de ma voix. Je suis là pour vous aider. Qu'en pensez-vous?",
  ko: "안녕하세요! 이것은 제 목소리 샘플입니다. 도와드리겠습니다. 어떻게 생각하세요?",
  nl: "Hallo! Dit is een voorbeeld van mijn stem. Ik ben er om je te helpen. Wat vind je ervan?"
};

/**
 * Get voice by ID
 */
function getVoiceById(voiceId) {
  return VOICE_CATALOG.find(v => v.id === voiceId);
}

/**
 * Get voices by language
 */
function getVoicesByLanguage(languageCode) {
  return VOICE_CATALOG.filter(v => v.language === languageCode);
}

/**
 * Get voices by category
 */
function getVoicesByCategory(category) {
  return VOICE_CATALOG.filter(v => v.category === category);
}

/**
 * Get voices by tier
 */
function getVoicesByTier(tier) {
  return VOICE_CATALOG.filter(v => v.tier === tier);
}

/**
 * Get default opening line for voice
 */
function getDefaultOpeningLine(voiceId) {
  return DEFAULT_OPENING_LINES[voiceId] || DEFAULT_OPENING_LINES.Ashley;
}

/**
 * Get preview sample text for voice
 */
function getPreviewSample(voiceId) {
  const voice = getVoiceById(voiceId);
  if (!voice) return PREVIEW_SAMPLES.default;

  return PREVIEW_SAMPLES[voice.language] || PREVIEW_SAMPLES.default;
}

/**
 * Validate voice ID exists and is available
 */
function validateVoiceId(voiceId, userTier = VOICE_TIERS.FREE) {
  const voice = getVoiceById(voiceId);
  if (!voice) {
    return { valid: false, error: 'Voice not found' };
  }

  // Check tier access
  if (voice.tier === VOICE_TIERS.PREMIUM && userTier === VOICE_TIERS.FREE) {
    return { valid: false, error: 'Premium voice requires upgrade' };
  }

  if (voice.tier === VOICE_TIERS.ENTERPRISE && userTier !== VOICE_TIERS.ENTERPRISE) {
    return { valid: false, error: 'Enterprise voice requires enterprise plan' };
  }

  return { valid: true, voice };
}

/**
 * Validate opening line text
 */
function validateOpeningLine(text) {
  const MIN_LENGTH = 5;
  const MAX_LENGTH = 500;

  if (!text || text.trim().length < MIN_LENGTH) {
    return { valid: false, error: `Opening line must be at least ${MIN_LENGTH} characters` };
  }

  if (text.length > MAX_LENGTH) {
    return { valid: false, error: `Opening line must not exceed ${MAX_LENGTH} characters` };
  }

  // Check for unsupported characters or patterns
  const unsupportedPatterns = [
    /[<>]/g, // HTML tags
    /\{|\}/g, // Template literals
  ];

  for (const pattern of unsupportedPatterns) {
    if (pattern.test(text)) {
      return { valid: false, error: 'Opening line contains unsupported characters' };
    }
  }

  return { valid: true };
}

module.exports = {
  VOICE_CATALOG,
  VOICE_TIERS,
  LANGUAGES,
  DEFAULT_OPENING_LINES,
  PREVIEW_SAMPLES,
  getVoiceById,
  getVoicesByLanguage,
  getVoicesByCategory,
  getVoicesByTier,
  getDefaultOpeningLine,
  getPreviewSample,
  validateVoiceId,
  validateOpeningLine
};
