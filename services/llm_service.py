"""
OpenAI GPT-4o integration for BPMN generation.
Handles text input, image input, conversation history, and JSON extraction.
"""

import json
import re
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL, MAX_CONVERSATION_TURNS
from prompts.system_prompt import SYSTEM_PROMPT, SUMMARY_PROMPT, EDIT_CONTEXT_TEMPLATE
from prompts.few_shot_examples import FEW_SHOT_EXAMPLES

client = OpenAI(api_key=OPENAI_API_KEY)


def _extract_json(text):
    """
    Extract JSON from LLM response. Handles:
    - Raw JSON
    - JSON in code fences (```json ... ```)
    - JSON embedded in text
    """
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from code fences
    fence_pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
    matches = re.findall(fence_pattern, text, re.DOTALL)
    for match in matches:
        try:
            return json.loads(match.strip())
        except json.JSONDecodeError:
            continue

    # Try finding JSON object in text
    brace_start = text.find("{")
    if brace_start >= 0:
        # Find the matching closing brace
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[brace_start:i + 1])
                    except json.JSONDecodeError:
                        break

    return None


def _build_messages(conversation_history, user_message, current_json=None, image_base64=None):
    """Build the messages array for the OpenAI API call."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add few-shot examples
    messages.extend(FEW_SHOT_EXAMPLES)

    # Add conversation history (limited to last N turns)
    history_limit = MAX_CONVERSATION_TURNS * 2  # Each turn = user + assistant
    recent_history = conversation_history[-history_limit:]
    messages.extend(recent_history)

    # Build the current user message
    if current_json and not image_base64:
        # Editing mode: inject current process context
        edit_context = EDIT_CONTEXT_TEMPLATE.format(
            current_json=json.dumps(current_json, indent=2)
        )
        full_message = f"{edit_context}\n\nUser request: {user_message}"
    else:
        full_message = user_message

    if image_base64:
        # Vision API: send image with text
        if full_message:
            text_content = (
                "The user provided both a text description and an image. "
                "Use both sources to generate the BPMN process.\n\n"
                f"Text description: {full_message}"
            )
        else:
            text_content = "Convert this flowchart/diagram into a BPMN process."
        content = [
            {"type": "text", "text": text_content}
        ]
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{image_base64}",
                "detail": "high"
            }
        })
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": full_message})

    return messages


def generate_bpmn(user_message, conversation_history, current_json=None, image_base64=None):
    """
    Call GPT-4o to generate or edit a BPMN process.

    Args:
        user_message: The user's text input
        conversation_history: List of previous messages [{role, content}, ...]
        current_json: Current BPMN JSON (for editing), or None for fresh generation
        image_base64: Base64-encoded image string, or None

    Returns:
        dict: { "json": parsed_json, "raw_response": str, "error": str|None }
    """
    messages = _build_messages(conversation_history, user_message, current_json, image_base64)

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_completion_tokens=4096
        )

        raw_response = response.choices[0].message.content
        parsed_json = _extract_json(raw_response)

        if parsed_json is None:
            return {
                "json": None,
                "raw_response": raw_response,
                "error": "Could not extract valid JSON from LLM response."
            }

        return {
            "json": parsed_json,
            "raw_response": raw_response,
            "error": None
        }

    except Exception as e:
        return {
            "json": None,
            "raw_response": "",
            "error": f"LLM API error: {str(e)}"
        }


def _build_summary_messages(user_message, image_base64=None):
    """Build the messages array for a summary request (no few-shot, no history)."""
    messages = [{"role": "system", "content": SUMMARY_PROMPT}]

    if image_base64:
        if user_message:
            text_content = (
                "The user provided both a text description and an image of a process. "
                "Analyze both sources and combine them into a single summary.\n\n"
                f"Text description: {user_message}"
            )
        else:
            text_content = "Summarize the process shown in this flowchart/diagram."
        content = [
            {"type": "text", "text": text_content}
        ]
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{image_base64}",
                "detail": "high"
            }
        })
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": user_message})

    return messages


def generate_summary(user_message, image_base64=None):
    """
    Call OpenAI to generate a plain-text summary of the user's process description.

    Args:
        user_message: The user's text input
        image_base64: Base64-encoded image string, or None

    Returns:
        dict: { "summary": str, "error": str|None }
    """
    messages = _build_summary_messages(user_message, image_base64)

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_completion_tokens=1024
        )

        summary = response.choices[0].message.content.strip()
        return {"summary": summary, "error": None}

    except Exception as e:
        return {"summary": "", "error": f"LLM API error: {str(e)}"}
