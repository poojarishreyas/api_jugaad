const express = require('express');
const { initBrowser } = require('./browser');
const { sendMessage, isBusy, setProvider, getProviderName } = require('./chat');
const config = require('./config');

const app = express();
app.use(express.json());

// Optional API key middleware
function authMiddleware(req, res, next) {
  if (!config.apiKey) return next();
  const key = req.headers['x-api-key'];
  if (key !== config.apiKey) {
    return res.status(401).json({ error: 'Invalid or missing API key' });
  }
  next();
}

// POST /chat
// Body: { "message": "your question here" }
// Headers: x-api-key (only if API_KEY is set in .env)
app.post('/chat', authMiddleware, async (req, res) => {
  const { message } = req.body;

  if (!message || typeof message !== 'string' || !message.trim()) {
    return res.status(400).json({ error: 'message field is required and must be a non-empty string' });
  }

  if (isBusy()) {
    return res.status(429).json({ error: 'Server is busy with another request. Try again shortly.' });
  }

  try {
    console.log(`[api] Received: "${message.slice(0, 80)}${message.length > 80 ? '...' : ''}"`);
    const response = await sendMessage(message.trim());
    console.log(`[api] Responded (${response.length} chars)`);
    res.json({ response });
  } catch (err) {
    console.error('[api] Error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// POST /v1/chat/completions
// OpenAI-compatible endpoint for VS Code extensions (Claude Code, Cline, etc.)
app.post('/v1/chat/completions', authMiddleware, async (req, res) => {
  const { messages, model } = req.body;

  if (!Array.isArray(messages) || messages.length === 0) {
    return res.status(400).json({ error: { message: "messages array is required" } });
  }

  if (isBusy()) {
    return res.status(429).json({ error: { message: "Server is busy with another request." } });
  }

  // Flatten the messages array into a single prompt string
  const flatMessage = messages.map(m => {
    const role = m.role.toUpperCase();
    return `[${role}]:\n${m.content}`;
  }).join('\n\n');

  try {
    console.log(`[openai-api] Received request (model: ${model || 'default'})`);
    console.log(`[openai-api] Flattened prompt: "${flatMessage.slice(0, 80)}..."`);
    
    const responseText = await sendMessage(flatMessage.trim());
    
    console.log(`[openai-api] Responded (${responseText.length} chars)`);

    // Return the standard OpenAI response JSON format
    res.json({
      id: `chatcmpl-${Date.now()}`,
      object: "chat.completion",
      created: Math.floor(Date.now() / 1000),
      model: model || getProviderName(),
      choices: [
        {
          index: 0,
          message: {
            role: "assistant",
            content: responseText
          },
          finish_reason: "stop"
        }
      ],
      usage: {
        prompt_tokens: flatMessage.length, // Rough estimate
        completion_tokens: responseText.length,
        total_tokens: flatMessage.length + responseText.length
      }
    });
  } catch (err) {
    console.error('[openai-api] Error:', err.message);
    res.status(500).json({ error: { message: err.message } });
  }
});

// POST /v1/messages
// Anthropic-compatible endpoint for Claude Code
app.post('/v1/messages', authMiddleware, async (req, res) => {
  const { messages, system, model } = req.body;

  if (!Array.isArray(messages) || messages.length === 0) {
    return res.status(400).json({ error: { type: "invalid_request_error", message: "messages array is required" } });
  }

  if (isBusy()) {
    return res.status(429).json({ error: { type: "rate_limit_error", message: "Server is busy with another request." } });
  }

  // Flatten system and user messages into a single prompt string
  let flatMessage = system ? `[SYSTEM]:\n${system}\n\n` : '';
  flatMessage += messages.map(m => {
    const role = m.role.toUpperCase();
    // Anthropic content can sometimes be an array of blocks, handle string or array
    const content = Array.isArray(m.content) 
      ? m.content.map(c => c.text).join('\n')
      : m.content;
    return `[${role}]:\n${content}`;
  }).join('\n\n');

  try {
    console.log(`[anthropic-api] Received request (model: ${model || 'default'})`);
    console.log(`[anthropic-api] Flattened prompt: "${flatMessage.slice(0, 80)}..."`);
    
    const responseText = await sendMessage(flatMessage.trim());
    
    console.log(`[anthropic-api] Responded (${responseText.length} chars)`);

    // Return the standard Anthropic Messages API response JSON format
    res.json({
      id: `msg_${Date.now()}`,
      type: "message",
      role: "assistant",
      model: model || getProviderName(),
      content: [
        {
          type: "text",
          text: responseText
        }
      ],
      stop_reason: "end_turn",
      stop_sequence: null,
      usage: {
        input_tokens: flatMessage.length, // Rough estimate
        output_tokens: responseText.length
      }
    });
  } catch (err) {
    console.error('[anthropic-api] Error:', err.message);
    res.status(500).json({ error: { type: "api_error", message: err.message } });
  }
});

// GET /status
app.get('/status', (req, res) => {
  res.json({ status: 'ok', busy: isBusy(), provider: getProviderName() });
});

// Boot
(async () => {
  try {
    const provider = await initBrowser();
    setProvider(provider);
    const server = app.listen(config.port, () => {
      console.log(`[server] API running at http://localhost:${config.port}`);
      console.log(`[server] Provider: ${provider.name}`);
      console.log(`[server] Send POST /chat with { "message": "..." }`);
    });
    server.on('error', (err) => {
      console.error('[server] Listen error:', err.message);
      process.exit(1);
    });
  } catch (err) {
    console.error('[server] Failed to start:', err.message);
    process.exit(1);
  }

  process.on('SIGTERM', () => process.exit(0));
  process.on('SIGINT',  () => process.exit(0));
})();
