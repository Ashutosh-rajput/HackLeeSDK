import sys
import json
import logging
import os

import google.generativeai as genai
import requests
from pynput import keyboard

# --- PyQt6 Imports ---
# Import pyqtSignal for thread-safe communication
from PyQt6.QtCore import QBuffer, QIODevice, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QPixmap
from PyQt6.QtWidgets import (QApplication, QLabel, QTextEdit, QVBoxLayout,
                             QWidget)

# --- Environment and Logging Setup ---
import dotenv

dotenv.load_dotenv()

# Configure logging to file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

logging.info("Application starting...")


# --- Main Application Class ---
class ScreenshotApp(QWidget):
    # --- THREADING FIX: Define signals that will be emitted from the keyboard listener thread ---
    # These signals act as a thread-safe bridge to the main GUI thread.
    capture_requested = pyqtSignal()
    finish_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.captured_screens_bytes = []
        self.last_gemini_response = ""
        self.model = None

        self.init_ui()
        self.init_gemini()

        # --- THREADING FIX: Connect the signals to the methods (slots) that will do the work ---
        # When capture_requested is emitted, self.capture_and_process_screenshot will run in the main GUI thread.
        self.capture_requested.connect(self.capture_and_process_screenshot)
        self.finish_requested.connect(self.send_final_result_to_backend)

    def init_ui(self):
        """Initializes the graphical user interface."""
        self.setWindowTitle('Screenshot to JSON Tool')
        self.setGeometry(100, 100, 800, 700)

        self.layout = QVBoxLayout()

        self.image_label = QLabel("Press Shift+Q+R to capture a screenshot")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumHeight(400)
        self.image_label.setStyleSheet("border: 1px solid gray;")
        self.layout.addWidget(self.image_label)

        self.caption_label = QTextEdit("Processed text and logs will appear here.")
        self.caption_label.setReadOnly(True)
        self.layout.addWidget(self.caption_label)

        self.setLayout(self.layout)
        logging.info("UI initialized successfully.")

    def init_gemini(self):
        """Configures and initializes the Generative AI client."""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            error_msg = "GEMINI_API_KEY not found in .env file."
            self.caption_label.setText(f"ERROR: {error_msg}")
            logging.error(error_msg)
            return

        try:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-2.0-flash')
            logging.info("Gemini client initialized successfully.")
        except Exception as e:
            error_msg = f"Error initializing Gemini: {e}"
            self.caption_label.setText(f"ERROR: {error_msg}")
            logging.error(error_msg)

    def get_enhanced_prompt(self):
        """Generates the structured prompt for the Gemini model based on context."""
        json_schema = {
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
        }

        if not self.last_gemini_response:
            return f"""You are an expert assistant for extracting programming problems from images. Analyze the following image and extract the key information. Respond ONLY with a single JSON object that follows this exact schema: {json.dumps(json_schema, indent=2)}. Fill in all fields based on the content of the image. If some information is missing, use null for its value."""
        else:
            return f"""You are an expert assistant for extracting programming problems from images. You have already processed a previous image and extracted the following JSON data: ```json\n{self.last_gemini_response}\n```. Now, analyze this new image. Update and complete the previous JSON data with any new or missing information from this new screenshot. If the new image contains a correction or refinement of existing data, update the corresponding fields. Respond ONLY with the single, complete, and updated JSON object."""

    def capture_and_process_screenshot(self):
        """
        This method is now a "slot" that runs safely in the main GUI thread.
        NOTE: The UI will freeze during the API call. For a smoother experience,
        the API call itself could be moved to another worker thread.
        """
        if not self.model:
            logging.error("Attempted to capture, but Gemini model is not initialized.")
            return

        logging.info("--- Capturing screenshot ---")
        try:
            screen = QGuiApplication.primaryScreen()
            pixmap = screen.grabWindow(0)

            self.image_label.setPixmap(
                pixmap.scaled(self.image_label.size(),
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
            )
            logging.info("Screenshot captured and displayed in the UI.")

            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.ReadWrite)
            pixmap.save(buffer, "PNG")
            image_bytes = buffer.data().data()
            self.captured_screens_bytes.append(image_bytes)

            prompt = self.get_enhanced_prompt()
            image_parts = [{"mime_type": "image/png", "data": image_bytes}]

            logging.info("Sending screenshot to Gemini for processing...")
            # This is a blocking call and will freeze the GUI.
            response = self.model.generate_content([prompt] + image_parts)

            response_text = response.text.replace("```json\n", "").replace("```", "").strip()
            self.last_gemini_response = response_text

            self.caption_label.setText(
                f"Processed Screenshot {len(self.captured_screens_bytes)}\n\n{self.last_gemini_response}")
            logging.info("Successfully received and processed response from Gemini.")

        except Exception as e:
            error_msg = f"An error occurred during screenshot or Gemini processing: {e}"
            self.caption_label.setText(f"ERROR: {error_msg}")
            logging.error(error_msg, exc_info=True)

    def send_final_result_to_backend(self):
        """This method is now a "slot" that runs safely in the main GUI thread."""
        logging.info("--- Finalizing and sending data to backend ---")
        if not self.last_gemini_response:
            error_msg = "No Gemini response to send. Capture a screenshot first."
            self.caption_label.setText(error_msg)
            logging.warning(error_msg)
            return

        try:
            backend_base = os.getenv("BASE_URL", "http://localhost:8000")
            url = f"{backend_base}/init_task"
            payload = {"problem": self.last_gemini_response}

            logging.info(f"Sending final JSON to backend at {url}")
            res = requests.post(url, json=payload)

            status_msg = f"✅ Sent final data to backend (Status: {res.status_code})"
            self.caption_label.setText(status_msg)
            logging.info(f"Backend responded with status: {res.status_code}")

            self.captured_screens_bytes = []
            self.last_gemini_response = ""
            self.image_label.setText("State reset. Press Shift+Q+R for a new problem.")

        except Exception as e:
            error_msg = f"Failed to send data to backend: {e}"
            self.caption_label.setText(f"ERROR: {error_msg}")
            logging.error(error_msg, exc_info=True)


# --- Keyboard Shortcut Listener ---
pressed_keys = set()
COMBINATION_CAPTURE = {keyboard.Key.shift, keyboard.KeyCode.from_char('Q'), keyboard.KeyCode.from_char('R')}
COMBINATION_FINISH = {keyboard.Key.shift, keyboard.KeyCode.from_char('Q'), keyboard.KeyCode.from_char('F')}


def on_press(key):
    """Handle key press events. Runs in the pynput thread."""
    if key in COMBINATION_CAPTURE or key in COMBINATION_FINISH:
        pressed_keys.add(key)

        if pressed_keys == COMBINATION_CAPTURE:
            logging.info("Capture shortcut detected. Emitting signal...")
            if 'app_instance' in globals():
                # --- THREADING FIX: Emit a signal instead of calling the function directly ---
                app_instance.capture_requested.emit()

        elif pressed_keys == COMBINATION_FINISH:
            logging.info("Finish shortcut detected. Emitting signal...")
            if 'app_instance' in globals():
                # --- THREADING FIX: Emit a signal ---
                app_instance.finish_requested.emit()


def on_release(key):
    """Handle key release events. Runs in the pynput thread."""
    try:
        pressed_keys.remove(key)
    except KeyError:
        pass


def main():
    app = QApplication(sys.argv)

    global app_instance
    app_instance = ScreenshotApp()
    app_instance.show()

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    exit_code = app.exec()

    listener.stop()
    logging.info("Application shutting down.")
    sys.exit(exit_code)


if __name__ == '__main__':
    main()