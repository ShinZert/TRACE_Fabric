import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = "gpt-5-mini"
MAX_CONVERSATION_TURNS = 6
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload
SECRET_KEY = os.getenv("SECRET_KEY", "bpmn-chatbot-dev-key")
