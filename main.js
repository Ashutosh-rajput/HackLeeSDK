// [LOG 1] Starting main.js execution...
console.log('[LOG 1] Starting main.js execution...');

process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';


require('dotenv').config(); // ✅ Load environment variables



const { app, BrowserWindow, globalShortcut, desktopCapturer } = require('electron');
const path = require('path');
const fs = require('fs');
const OpenAI = require('openai'); // ✅ Switched to the OpenAI package

// ✅ Ensure fetch works in Electron’s main process
global.fetch = (...args) =>
  import('node-fetch').then(({ default: fetch }) => fetch(...args));

let openai; // ✅ Renamed for clarity
let capturedScreens = []; // store screenshots (as base64 strings)
let lastGeminiResponse = ''; // store latest Gemini response (as a JSON string)

/**
 * Creates the main application window and initializes the Gemini client via the OpenAI SDK.
 */
function createWindow() {
  console.log('[LOG 2] createWindow() called.');

  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    console.error('[ERROR] Missing GEMINI_API_KEY in .env file!');
    return;
  }

  try {
    // ✅ Initialize with OpenAI package pointing to Google's API endpoint
    openai = new OpenAI({
      apiKey: apiKey,
      baseURL: "https://generativelanguage.googleapis.com/v1beta/openai/"
    });
    console.log('[LOG 3] OpenAI client for Gemini initialized successfully.');
  } catch (error) {
    console.error('[ERROR] Failed to initialize OpenAI client for Gemini:', error);
    return;
  }

  const mainWindow = new BrowserWindow({
    width: 800,
    height: 600,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.loadFile('index.html');
  console.log('[LOG 4] Main window created and loaded index.html.');
}

/**
 * Register global keyboard shortcuts when the app is ready.
 */
app.whenReady().then(() => {
  console.log('[LOG 5] App is ready.');
  createWindow();

  // ✅ Capture screenshot with Shift + Q + R
  const captureShortcut = globalShortcut.register('Shift+Q+R', async () => {
    console.log('--- Shortcut Pressed: Capturing screenshot ---');
    await captureAndProcessScreenshot();
  });

  // ✅ Finalize and send data with Shift + Q + F
  const finishShortcut = globalShortcut.register('Shift+Q+F', async () => {
    console.log('--- Shortcut Pressed: Finishing question ---');
    await sendFinalResultToBackend();
  });

  if (!captureShortcut || !finishShortcut) {
    console.error('[ERROR] Failed to register one or more global shortcuts.');
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('will-quit', () => globalShortcut.unregisterAll());
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});


/**
 * Generates the structured prompt for the Gemini model.
 * @returns {string} The detailed prompt.
 */
function getEnhancedPrompt() {
    const jsonSchema = `{
  "title": "Problem title or name",
  "description": "A clear, concise summary of the problem statement.",
  "constraints": ["List of constraints, e.g., '1 <= nums.length <= 1000'"],
  "functionSignature": "The code boilerplate or function signature to be completed.",
  "examples": [
    {
      "input": "Input for example 1",
      "output": "Output for example 1",
      "explanation": "Optional explanation for example 1"
    }
  ]
}`;

    if (capturedScreens.length === 1) {
        // This is the first screenshot
        return `You are an expert assistant for extracting programming problems from images. Analyze the following image and extract the key information.
Respond ONLY with a single JSON object that follows this exact schema:
${jsonSchema}

Fill in all fields based on the content of the image. If some information is missing, use null for its value.`;
    } else {
        // This is a subsequent screenshot, provide the previous response as context
        return `You are an expert assistant for extracting programming problems from images.
You have already processed a previous image and extracted the following JSON data:
\`\`\`json
${lastGeminiResponse}
\`\`\`
Now, analyze this new image. Update and complete the previous JSON data with any new or missing information from this new screenshot.
If the new image contains a correction or refinement of existing data, update the corresponding fields.
Respond ONLY with the single, complete, and updated JSON object.`;
    }
}


/**
 * Captures a screenshot, formats it, and sends it to Gemini for processing.
 */
async function captureAndProcessScreenshot() {
  const mainWindow = BrowserWindow.getAllWindows()[0];
  if (!mainWindow) return console.error('[ERROR] No main window found.');
  if (!openai) return console.error('[ERROR] OpenAI client not initialized.');

  try {
    const sources = await desktopCapturer.getSources({
      types: ['screen'],
      thumbnailSize: { width: 1920, height: 1080 }
    });

    if (!sources.length) throw new Error('No screens detected for capture.');

    const screenshotBuffer = sources[0].thumbnail.toPNG();
    const base64ImageFile = screenshotBuffer.toString('base64');
    capturedScreens.push(base64ImageFile);
    console.log(`[LOG] Screenshot ${capturedScreens.length} captured.`);

    // ✅ Enhanced prompt for structured JSON output
    const promptText = getEnhancedPrompt();

    // ✅ Structure the request payload in the OpenAI format
    const messages = [{
        "role": "user",
        "content": [
            { "type": "text", "text": promptText },
            { "type": "image_url", "image_url": { "url": `data:image/png;base64,${base64ImageFile}` } },
        ],
    }];

    console.log('[LOG] Sending screenshot to Gemini for structured extraction...');

    // ✅ Use the openai.chat.completions.create method
    const response = await openai.chat.completions.create({
      model: "gemini-pro-vision", // Use a compatible vision model
      messages: messages,
    });

    // ✅ Update context with the new JSON string, cleaning it up first
    let responseText = response.choices[0].message.content || lastGeminiResponse;
    responseText = responseText.replace(/```json\n|```/g, '').trim(); // Clean markdown fences
    lastGeminiResponse = responseText;

    console.log(`[LOG] Gemini response updated.`);

    // Send update to the frontend UI
    mainWindow.webContents.send('screenshot-and-caption', {
      image: `data:image/png;base64,${base64ImageFile}`,
      caption: `Processed Screenshot ${capturedScreens.length}\n\n${truncateText(lastGeminiResponse, 400)}`
    });
  } catch (error) {
    console.error('[ERROR] During screenshot or Gemini processing:', error);
    mainWindow.webContents.send('screenshot-and-caption', {
      image: '',
      caption: `Error: ${error.message}`
    });
  }
}

/**
 * Sends the final compiled Gemini response to the backend service.
 */
async function sendFinalResultToBackend() {
  if (!lastGeminiResponse) {
    console.error('[ERROR] No Gemini response to send.');
    return;
  }

  try {
    const backendBase = process.env.BASE_URL || 'http://localhost:8000';
    // ✅ Send the structured JSON string to the backend
    const payload = { problem: lastGeminiResponse };

    console.log('[LOG] Sending final structured JSON to backend...');
    const res = await fetch(`${backendBase}/init_task`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    console.log('[LOG] Backend response status:', res.status);

    const mainWindow = BrowserWindow.getAllWindows()[0];
    if (mainWindow) {
      mainWindow.webContents.send('screenshot-and-caption', {
        image: '',
        caption: `✅ Sent final data to backend (Status: ${res.status})`
      });
    }

    // Reset state for the next problem
    capturedScreens = [];
    lastGeminiResponse = '';
  } catch (error) {
    console.error('[ERROR] Failed to send data to backend:', error);
  }
}

/**
 * Helper function to shorten long text for UI display.
 */
function truncateText(text, maxLength) {
  if (!text) return '';
  return text.length > maxLength ? text.slice(0, maxLength) + '...' : text;
}