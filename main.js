// [LOG 1] Starting main.js execution...
console.log('[LOG 1] Starting main.js execution...');

require('dotenv').config(); // ✅ Load environment variables

const { app, BrowserWindow, globalShortcut, desktopCapturer } = require('electron');
const path = require('path');
const fs = require('fs');

// ✅ Ensure fetch works in Electron’s main process
global.fetch = (...args) =>
  import('node-fetch').then(({ default: fetch }) => fetch(...args));

const { GoogleGenAI } = require('@google/genai');

let ai;
let capturedScreens = []; // store screenshots
let lastGeminiResponse = ''; // store latest Gemini response text

/**
 * Create main app window and initialize Gemini
 */
function createWindow() {
  console.log('[LOG 2] createWindow() called.');

  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    console.error('[ERROR] Missing GEMINI_API_KEY in .env file!');
    return;
  }

  try {
    ai = new GoogleGenAI({ apiKey });
    console.log('[LOG 3] GoogleGenAI client initialized successfully.');
  } catch (error) {
    console.error('[ERROR] Failed to initialize GoogleGenAI client:', error);
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
 * Register keyboard shortcuts
 */
app.whenReady().then(() => {
  console.log('[LOG 5] App is ready.');
  createWindow();

  // ✅ Capture screenshot (Shift + Q + R)
  const captureShortcut = globalShortcut.register('Shift+Q+R', async () => {
    console.log('--- Shortcut Pressed: Capturing screenshot ---');
    await captureAndProcessScreenshot();
  });

  // ✅ Finish capturing (Shift + Q + F)
  const finishShortcut = globalShortcut.register('Shift+Q+F', async () => {
    console.log('--- Shortcut Pressed: Finishing question ---');
    await sendFinalResultToBackend();
  });

  if (!captureShortcut || !finishShortcut) {
    console.error('[ERROR] Failed to register one or more shortcuts.');
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
 * Capture one screenshot and send to Gemini with previous response context
 */
async function captureAndProcessScreenshot() {
  const mainWindow = BrowserWindow.getAllWindows()[0];
  if (!mainWindow) return console.error('[ERROR] No main window found.');

  if (!ai) return console.error('[ERROR] GoogleGenAI client not initialized.');

  try {
    const sources = await desktopCapturer.getSources({
      types: ['screen'],
      thumbnailSize: { width: 1920, height: 1080 }
    });

    if (!sources.length) throw new Error('No screens detected.');

    const screenshotPath = path.join(app.getPath('temp'), `screenshot_${Date.now()}.png`);
    fs.writeFileSync(screenshotPath, sources[0].thumbnail.toPNG());

    const base64ImageFile = fs.readFileSync(screenshotPath, { encoding: 'base64' });
    capturedScreens.push(base64ImageFile);
    console.log(`[LOG] Screenshot ${capturedScreens.length} captured.`);

    // Build Gemini request
    const contents = [
      {
        inlineData: {
          mimeType: 'image/png',
          data: base64ImageFile
        }
      },
      {
        text:
          capturedScreens.length === 1
            ? "Extract the DSA question, code boilerplate, examples, and input/output details from this image."
            : `Update the previous extracted information with any new details from this new screenshot.
               Prior extracted content:\n${lastGeminiResponse}`
      }
    ];

    console.log('[LOG] Sending screenshot to Gemini...');
    const response = await ai.models.generateContent({
      model: 'gemini-2.5-flash',
      contents
    });

    lastGeminiResponse = response.text || lastGeminiResponse; // update context
    console.log(`[LOG] Gemini response length: ${lastGeminiResponse.length}`);

    // Send update to frontend
    mainWindow.webContents.send('screenshot-and-caption', {
      image: `data:image/png;base64,${base64ImageFile}`,
      caption: `Processed Screenshot ${capturedScreens.length}\n\n${truncateText(
        lastGeminiResponse,
        400
      )}`
    });
  } catch (error) {
    console.error('[ERROR] During screenshot or Gemini processing:', error);
  }
}

/**
 * Send final Gemini response to backend and reset
 */
async function sendFinalResultToBackend() {
  if (!lastGeminiResponse) {
    console.error('[ERROR] No Gemini response to send.');
    return;
  }

  try {
    const backendBase = process.env.BASE_URL || 'http://localhost:8000';
    const payload = { problem: lastGeminiResponse.trim() };

    console.log('[LOG] Sending final Gemini response to backend...');
    const res = await fetch(`${backendBase}/init_task`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    console.log('[LOG] Backend response:', res.status);

    // Notify frontend
    const mainWindow = BrowserWindow.getAllWindows()[0];
    if (mainWindow) {
      mainWindow.webContents.send('screenshot-and-caption', {
        image: '',
        caption: `✅ Sent final structured question to backend (${res.status})`
      });
    }

    // Reset state for next question
    capturedScreens = [];
    lastGeminiResponse = '';
  } catch (error) {
    console.error('[ERROR] Sending to backend:', error);
  }
}

/**
 * Helper to shorten long Gemini text for UI display
 */
function truncateText(text, maxLength) {
  if (!text) return '';
  return text.length > maxLength ? text.slice(0, maxLength) + '...' : text;
}
