import { GoogleGenAI } from "@google/genai";
import * as fs from "node:fs";

require('dotenv').config(); // ✅ Load .env variables at the very top

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

const base64ImageFile = fs.readFileSync("test.png", {
  encoding: "base64",
});

const contents = [
  {
    inlineData: {
      mimeType: "image/jpeg",
      data: base64ImageFile,
    },
  },
  { text: "Caption this image." },
];

const response = await ai.models.generateContent({
  model: "gemini-2.5-flash",
  contents: contents,
});
console.log(response.text);