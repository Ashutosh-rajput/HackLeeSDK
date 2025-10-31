import sys
import asyncio
import logging
import os
from datetime import datetime
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

# Autogen imports
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
from autogen_agentchat.base import TaskResult
from autogen_agentchat.conditions import TextMentionTermination
from autogen_agentchat.messages import TextMessage
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_core import CancellationToken
from autogen_ext.models.openai import OpenAIChatCompletionClient, AzureOpenAIChatCompletionClient
from dotenv import load_dotenv
from pydantic import BaseModel

# Use PySide6
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLineEdit, QLabel, QSplitter, QMessageBox, QFrame, QScrollArea,
    QSizePolicy
)
from PySide6.QtCore import QThread, Signal, Slot, Qt
from PySide6.QtGui import QTextCursor, QFont, QColor, QPalette, QBrush

from code_run import compile_java_code, run_java_class, compile_and_run_java
from prompts import code_agent_prompt, critic_agent_prompt

LOG_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.log")

load_dotenv()

api_key = os.environ.get("API_KEY")
azure_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
api_version = os.environ.get("AZURE_OPENAI_API_VERSION")
APIFY_API_KEY = os.environ.get("APIFY_API_KEY")


class InitTaskRequest(BaseModel):
    problem: str


class UserInputRequest(BaseModel):
    content: str


class AgentWorker(QThread):
    # Signals to communicate with the main thread
    message_received = Signal(dict)
    user_prompt = Signal(str)
    task_finished = Signal()

    def __init__(self, problem: str):
        super().__init__()
        self.problem = problem
        self.user_reply = None
        self.user_reply_ready = asyncio.Event()

    def set_user_reply(self, reply: str):
        """Called by the main thread to set user reply"""
        self.user_reply = reply
        self.user_reply_ready.set()

    async def _user_input(self, prompt: str, cancellation_token=None) -> str:
        """Async function to get user input via GUI"""
        # Emit signal to prompt user in main thread
        self.user_prompt.emit(prompt)
        # Wait for user to provide input
        await self.user_reply_ready.wait()
        reply = self.user_reply
        self.user_reply = None
        self.user_reply_ready.clear()
        return reply

    def run(self):
        """Run the agent team in the thread"""
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._run_agent_team())
        loop.close()

    async def _run_agent_team(self):
        """Core agent logic"""
        self.message_received.emit(
            {"type": "sys", "msg": f"Received problem '{self.problem}'. Assembling agent team..."})

        try:
            # Initialize Model
            model_client = OpenAIChatCompletionClient(
                model="gemini-2.0-flash",
                api_key=api_key
            )

            # Create Agents
            coding_agent = AssistantAgent(
                name="Coding_Agent",
                model_client=model_client,
                tools=[compile_and_run_java],
                system_message=code_agent_prompt,
            )
            critic_agent = AssistantAgent(
                name="Critic_Agent",
                model_client=model_client,
                tools=[compile_and_run_java],
                system_message=critic_agent_prompt,
            )

            user_proxy = UserProxyAgent(name="user_proxy", input_func=self._user_input)

            outter_termination = TextMentionTermination("exit", sources=["user_proxy"])
            inner_chat = RoundRobinGroupChat(
                [coding_agent, critic_agent],
                termination_condition=TextMentionTermination("Approved"),
            )

            team = RoundRobinGroupChat(
                [inner_chat, user_proxy],
                termination_condition=outter_termination,
            )

            await team.reset()

            task = f"You are tasked to solve the problem: '{self.problem}'."
            stream = team.run_stream(task=task)

            async for message in stream:
                if isinstance(message, TaskResult):
                    continue
                self.message_received.emit(message.model_dump(mode="json"))

            self.message_received.emit({"type": "done", "msg": "Team has finished the task."})

        except Exception as e:
            logging.exception("Error in run_agent_team:")
            self.message_received.emit({"type": "error", "msg": str(e)})
        finally:
            self.task_finished.emit()


class ChatMessageWidget(QWidget):
    """A widget to display a single chat message with styling"""

    def __init__(self, message_text, message_type, sender=""):
        super().__init__()
        self.message_type = message_type
        self.sender = sender

        # Main layout - horizontal for alignment
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(10, 5, 10, 5)

        # Create message bubble
        self.message_bubble = QFrame()
        self.message_bubble.setFrameShape(QFrame.StyledPanel)
        self.message_bubble.setFrameShadow(QFrame.Raised)
        self.message_bubble.setStyleSheet(self.get_style())

        # Message content layout
        content_layout = QVBoxLayout()
        content_layout.setSpacing(2)

        # Sender label (optional)
        if sender:
            sender_label = QLabel(f"<strong>{sender}:</strong>")
            sender_label.setStyleSheet("color: #888; font-weight: bold;")
            content_layout.addWidget(sender_label)

        # Message text - using QTextEdit for better expansion
        self.message_text = QTextEdit()
        self.message_text.setReadOnly(True)
        self.message_text.setHtml(message_text)
        self.message_text.setStyleSheet("background-color: transparent; border: none; padding: 5px;")
        self.message_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self.message_text.setMaximumWidth(9999)  # Allow very wide content
        self.message_text.setLineWrapMode(QTextEdit.WidgetWidth)  # Wrap at widget width

        content_layout.addWidget(self.message_text)

        self.message_bubble.setLayout(content_layout)

        # Set size policy for bubble to expand horizontally
        self.message_bubble.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)

        # Align based on message type
        if message_type == "user":
            main_layout.addStretch()
            main_layout.addWidget(self.message_bubble)
        else:
            main_layout.addWidget(self.message_bubble)
            main_layout.addStretch()

        self.setLayout(main_layout)

    def get_style(self):
        """Get CSS style for the message bubble based on type"""
        if self.message_type == "user":
            return """
                QFrame {
                    background-color: #007acc;
                    border-radius: 15px;
                    padding: 10px;
                    margin: 5px;
                    color: white;
                }
            """
        elif self.message_type == "agent":
            return """
                QFrame {
                    background-color: #e0e0e0;
                    border-radius: 15px;
                    padding: 10px;
                    margin: 5px;
                    color: #333;
                }
            """
        elif self.message_type == "system":
            return """
                QFrame {
                    background-color: #fffbe6;
                    border-radius: 15px;
                    padding: 10px;
                    margin: 5px;
                    color: #666;
                    border: 1px solid #ddd;
                }
            """
        else:
            return """
                QFrame {
                    background-color: #f0f0f0;
                    border-radius: 15px;
                    padding: 10px;
                    margin: 5px;
                    color: #333;
                }
            """


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Intelli Compare Agent")
        self.setGeometry(100, 100, 1000, 700)

        # Set dark theme
        self.set_dark_theme()

        # Central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)

        # Header section
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(10, 10, 10, 10)

        # Problem input area
        self.problem_input = QLineEdit()
        self.problem_input.setPlaceholderText("Enter the problem to solve...")
        self.problem_input.setMinimumHeight(30)
        self.problem_input.textChanged.connect(self.check_problem_input)

        self.start_button = QPushButton("▶️ Start Build")
        self.start_button.clicked.connect(self.start_task)
        self.start_button.setEnabled(False)
        self.start_button.setMinimumHeight(30)

        header_layout.addWidget(QLabel("Problem:"), 1)
        header_layout.addWidget(self.problem_input, 3)
        header_layout.addWidget(self.start_button, 1)

        main_layout.addLayout(header_layout)

        # Chat display area - using QScrollArea for better control
        self.chat_scroll_area = QScrollArea()
        self.chat_scroll_area.setWidgetResizable(True)
        self.chat_scroll_area.setStyleSheet("background-color: #2b2b2b; border: none;")

        self.chat_content = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_content)
        self.chat_layout.setSpacing(5)
        self.chat_layout.setAlignment(Qt.AlignTop)
        self.chat_layout.setContentsMargins(10, 10, 10, 10)

        self.chat_scroll_area.setWidget(self.chat_content)
        main_layout.addWidget(self.chat_scroll_area, 1)

        # User input area (initially hidden)
        self.user_input_area = QFrame()
        self.user_input_area.setVisible(False)
        self.user_input_area.setStyleSheet("background-color: #333; padding: 5px;")
        input_area_layout = QHBoxLayout(self.user_input_area)
        input_area_layout.setContentsMargins(0, 0, 0, 0)

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Enter your reply...")
        self.user_input.setStyleSheet("background-color: #444; color: white; padding: 5px;")
        self.user_input.returnPressed.connect(self.send_user_reply)

        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_user_reply)
        self.send_button.setStyleSheet("background-color: #007acc; color: white; padding: 5px;")

        input_area_layout.addWidget(self.user_input, 1)
        input_area_layout.addWidget(self.send_button)
        main_layout.addWidget(self.user_input_area)

        # Status bar
        self.statusBar().showMessage("Ready")
        self.statusBar().setStyleSheet("background-color: #333; color: white;")

        # Agent worker
        self.worker = None
        self.thread = None

    def set_dark_theme(self):
        """Set a dark theme for the application"""
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(40, 40, 40))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(40, 40, 40))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.black)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(40, 40, 40))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        self.setPalette(palette)

    @Slot(str)
    def check_problem_input(self, text):
        """Enable/disable start button based on problem input"""
        self.start_button.setEnabled(len(text.strip()) > 0)

    @Slot()
    def start_task(self):
        problem = self.problem_input.text().strip()
        if not problem:
            QMessageBox.warning(self, "Warning", "Please enter a problem description first.")
            return

        # Clear previous chat
        for i in reversed(range(self.chat_layout.count())):
            widget = self.chat_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()

        self.append_message(f"Starting task: {problem}", "system")

        # Start the agent in a separate thread
        self.worker = AgentWorker(problem)
        self.thread = QThread()
        self.worker.moveToThread(self.thread)

        # Connect signals
        self.worker.message_received.connect(self.handle_message)
        self.worker.user_prompt.connect(self.handle_user_prompt)
        self.worker.task_finished.connect(self.handle_task_finished)

        self.thread.started.connect(self.worker.run)
        self.thread.start()

        self.start_button.setEnabled(False)
        self.statusBar().showMessage("Task running...")

    @Slot(dict)
    def handle_message(self, msg):
        if msg["type"] == "sys" or msg["type"] == "error":
            self.append_message(f"{msg['msg']}", "system")
        elif msg["type"] == "done":
            self.append_message(f"{msg['msg']}", "system")
        elif msg["type"] == "user":
            self.append_message(f"{msg['msg']}", "user", "You")
        else:
            # Agent message
            content = msg.get("content", "")
            sender = msg.get("source", "Agent")
            formatted_content = self.format_content(content)
            self.append_message(formatted_content, "agent", sender)

    @Slot(str)
    def handle_user_prompt(self, prompt):
        self.append_message(f"Agent requests: {prompt}", "system")
        self.user_input_area.setVisible(True)
        self.user_input.setFocus()

    @Slot()
    def handle_task_finished(self):
        self.user_input_area.setVisible(False)
        self.start_button.setEnabled(True)
        self.statusBar().showMessage("Task complete")

        # Clean up thread
        if self.thread:
            self.thread.quit()
            self.thread.wait()
            self.thread = None
        self.worker = None

    def send_user_reply(self):
        reply = self.user_input.text().strip()
        if not reply:
            return

        self.append_message(reply, "user", "You")
        self.user_input.clear()
        self.user_input_area.setVisible(False)

        # Send reply to worker
        if self.worker:
            self.worker.set_user_reply(reply)

    def append_message(self, html_content, message_type, sender=""):
        """Add a message to the chat display"""
        # Create a new message widget
        message_widget = ChatMessageWidget(html_content, message_type, sender)

        # Add to layout
        self.chat_layout.addWidget(message_widget)

        # Scroll to bottom
        self.chat_scroll_area.verticalScrollBar().setValue(
            self.chat_scroll_area.verticalScrollBar().maximum()
        )

    def format_content(self, content):
        """Format content for display, handling code blocks"""
        import re

        # Handle case where content is a list of messages
        if isinstance(content, list):
            content = " ".join(str(item) for item in content)

        # Ensure content is a string
        if not isinstance(content, str):
            content = str(content)

        # Handle code blocks (```language\n...\n```)
        pattern = r'```(\w*)\n([\s\S]*?)```'
        formatted = re.sub(pattern,
                           '<pre style="background-color: #333; color: #ffffff; padding: 10px; border-radius: 5px; font-family: monospace;">\\2</pre>',
                           content)

        # Replace newlines with <br> for HTML display
        formatted = formatted.replace("\n", "<br>")

        # Escape HTML special characters for safety
        formatted = formatted.replace("<", "<").replace(">", ">")

        return formatted


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Set global stylesheet for dark theme
    app.setStyleSheet("""
        QMainWindow {
            background-color: #2b2b2b;
        }
        QLineEdit {
            background-color: #333;
            color: white;
            border: 1px solid #555;
            padding: 5px;
            border-radius: 4px;
        }
        QPushButton {
            background-color: #444;
            color: white;
            border: 1px solid #555;
            padding: 5px 10px;
            border-radius: 4px;
        }
        QPushButton:hover {
            background-color: #555;
        }
        QPushButton:pressed {
            background-color: #666;
        }
        QPushButton:disabled {
            background-color: #222;
            color: #777;
        }
        QLabel {
            color: white;
        }
        QTextEdit {
            background-color: #222;
            color: white;
            border: 1px solid #555;
        }
        QScrollArea {
            background-color: #2b2b2b;
        }
    """)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())