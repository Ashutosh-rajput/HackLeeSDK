const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  onScreenshotAndCaption: (callback) => ipcRenderer.on('screenshot-and-caption', (_event, value) => callback(value))
});