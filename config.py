import os
import sys
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = "gpt-5-mini"
MAX_CONVERSATION_TURNS = 6
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload

# OpenAI request budget. gpt-5-mini is a reasoning model — internal reasoning
# consumes the same budget as visible output, so traces and image summaries
# get extra headroom. Image summaries push reasoning further than text-only
# ones, hence the larger cap.
MAX_TRACE_TOKENS = int(os.getenv("MAX_TRACE_TOKENS", "16384"))
MAX_SUMMARY_TOKENS_TEXT = int(os.getenv("MAX_SUMMARY_TOKENS_TEXT", "4096"))
MAX_SUMMARY_TOKENS_IMAGE = int(os.getenv("MAX_SUMMARY_TOKENS_IMAGE", "8192"))

# Hard timeout for OpenAI HTTP calls (seconds). Anything beyond this ties up
# a gunicorn worker, so it's deliberately well under the 120s gunicorn limit.
OPENAI_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT", "60"))

# SECRET_KEY signs Flask session cookies. A predictable value lets attackers
# forge sessions, so refuse to start without one in production. Set
# FLASK_DEBUG=1 to opt into a generated dev key for local work.
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    if os.getenv("FLASK_DEBUG") == "1":
        SECRET_KEY = os.urandom(32).hex()
    else:
        sys.exit(
            "SECRET_KEY is not set. Add it to your .env (or export it) before "
            "starting the app. For local development, set FLASK_DEBUG=1 to use "
            "an ephemeral generated key."
        )
