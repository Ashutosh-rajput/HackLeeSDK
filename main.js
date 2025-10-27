// [LOG 1] Starting main.js execution...
console.log('[LOG 1] Starting main.js execution...');

require('dotenv').config(); // ✅ Load .env variables at the very top

const { app, BrowserWindow, globalShortcut, desktopCapturer } = require('electron');
const path = require('path');
const fs = require('fs');

// ✅ Ensure fetch works in Electron’s main process (important!)
global.fetch = (...args) =>
  import('node-fetch').then(({ default: fetch }) => fetch(...args));

const { GoogleGenAI } = require('@google/genai');

let ai;

/**
 * Create the main application window and initialize the AI client.
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
 * When Electron is ready, create the window and register global shortcuts.
 */
app.whenReady().then(() => {
  console.log('[LOG 5] App is ready.');

  createWindow();

  // ✅ Register Shift + Q + R for screenshot and caption
  const ret = globalShortcut.register('Shift+Q+R', () => {
    console.log('--- Shortcut Pressed: Starting screenshot + caption process ---');
    takeScreenshotAndCaption();
  });

  if (!ret) {
    console.error('[ERROR] Failed to register global shortcut. Possibly already in use.');
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

/**
 * Unregister all shortcuts when quitting.
 */
app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});

/**
 * Quit when all windows are closed (except on macOS).
 */
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

/**
 * Take a screenshot, send it to Gemini, and show caption in the app.
 */
async function takeScreenshotAndCaption() {
  const mainWindow = BrowserWindow.getAllWindows()[0];
  if (!mainWindow) {
    console.error('[ERROR] No main window found.');
    return;
  }

  if (!ai) {
    console.error('[ERROR] GoogleGenAI client not initialized.');
    return;
  }

  try {
    const sources = await desktopCapturer.getSources({
      types: ['screen'],
      thumbnailSize: { width: 1920, height: 1080 }
    });

    if (!sources.length) {
      throw new Error('No screens detected for capture.');
    }

    const screenshotPath = path.join(app.getPath('temp'), 'screenshot.png');
    fs.writeFileSync(screenshotPath, sources[0].thumbnail.toPNG());
    console.log('[LOG 6] Screenshot saved at:', screenshotPath);

    const base64ImageFile = fs.readFileSync(screenshotPath, { encoding: 'base64' });

    const contents = [
      {
        inlineData: {
          mimeType: 'image/png',
          data: base64ImageFile
        }
      },
      { text: 'Caption this image.' }
    ];

    console.log('[LOG 7] Sending screenshot to Gemini for caption...');
    const response = await ai.models.generateContent({
      model: 'gemini-2.5-flash',
      contents: contents
    });

    const caption = response.text || '(No caption received)';
    console.log('[LOG 8] Caption received:', caption);

    const dataUrl = `data:image/png;base64,${base64ImageFile}`;
    mainWindow.webContents.send('screenshot-and-caption', {
      image: dataUrl,
      caption: caption
    });

  } catch (error) {
    console.error('[ERROR] During screenshot or caption generation:', error);
    mainWindow.webContents.send('screenshot-and-caption', {
      image: '',
      caption: `Error: ${error.message}`
    });
  }
}
