"""
OpenAI integration for Fabric trace generation.
Handles text input, image input, conversation history, and JSON extraction.
"""

import json
import logging
import re
from openai import OpenAI

log = logging.getLogger(__name__)
from config import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    MAX_CONVERSATION_TURNS,
    MAX_TRACE_TOKENS,
    MAX_SUMMARY_TOKENS_TEXT,
    MAX_SUMMARY_TOKENS_IMAGE,
    OPENAI_TIMEOUT,
)
from prompts.system_prompt import SYSTEM_PROMPT, SUMMARY_PROMPT, EDIT_CONTEXT_TEMPLATE
from prompts.few_shot_examples import FEW_SHOT_EXAMPLES

client = OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TIMEOUT)


def _extract_json(text):
    """
    Extract JSON from LLM response. Handles raw JSON, code-fenced JSON, and
    JSON embedded in surrounding prose via brace-matching fallback.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fence_pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
    for match in re.findall(fence_pattern, text, re.DOTALL):
        try:
            return json.loads(match.strip())
        except json.JSONDecodeError:
            continue

    brace_start = text.find("{")
    if brace_start >= 0:
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


def _image_content(text, image_base64, image_mime, detail):
    """Build an OpenAI multimodal user-content array (one text + one image)."""
    mime = image_mime or "image/png"
    return [
        {"type": "text", "text": text},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime};base64,{image_base64}",
                "detail": detail,
            },
        },
    ]


def _build_messages(conversation_history, user_message, current_trace=None, image_base64=None, image_mime=None):
    """Assemble the messages array for the OpenAI Chat Completions call."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(FEW_SHOT_EXAMPLES)

    history_limit = MAX_CONVERSATION_TURNS * 2
    messages.extend(conversation_history[-history_limit:])

    if current_trace and not image_base64:
        edit_context = EDIT_CONTEXT_TEMPLATE.format(
            current_json=json.dumps(current_trace, indent=2)
        )
        full_message = f"{edit_context}\n\nUser request: {user_message}"
    else:
        full_message = user_message

    if image_base64:
        if full_message:
            text_content = (
                "The user provided both a text description and an image. "
                "Use both sources to generate the Fabric trace.\n\n"
                f"Text description: {full_message}"
            )
        else:
            text_content = "Convert this flowchart/diagram into a Fabric decision trace."
        messages.append({
            "role": "user",
            "content": _image_content(text_content, image_base64, image_mime, "high"),
        })
    else:
        messages.append({"role": "user", "content": full_message})

    return messages


def generate_trace(user_message, conversation_history, current_trace=None, image_base64=None, image_mime=None):
    """
    Call the LLM to generate or edit a Fabric trace.

    Returns: { "json": parsed_trace, "raw_response": str, "error": str|None }
    """
    messages = _build_messages(conversation_history, user_message, current_trace, image_base64, image_mime)

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_completion_tokens=MAX_TRACE_TOKENS,
        )
        choice = response.choices[0]
        raw_response = choice.message.content or ""
        finish_reason = choice.finish_reason

        parsed = _extract_json(raw_response)
        if parsed is None:
            log.warning(
                "JSON parse failed. finish_reason=%s, content_len=%d, content_head=%r",
                finish_reason, len(raw_response), raw_response[:300],
            )
            hint = ""
            if finish_reason == "length":
                hint = " (response was truncated — model hit token budget)"
            elif not raw_response:
                hint = " (model returned empty content)"
            return {
                "json": None,
                "raw_response": raw_response,
                "error": f"Could not extract valid JSON from LLM response{hint}.",
            }
        return {"json": parsed, "raw_response": raw_response, "error": None}
    except Exception as e:
        log.exception("OpenAI call failed")
        return {"json": None, "raw_response": "", "error": f"LLM API error: {type(e).__name__}: {str(e) or '(empty)'}"}


def _build_summary_messages(user_message, image_base64=None, image_mime=None):
    """Build the messages array for a summary request (no few-shot, no history)."""
    messages = [{"role": "system", "content": SUMMARY_PROMPT}]

    if image_base64:
        if user_message:
            text_content = (
                "The user provided both a text description and an image of a workflow. "
                "Analyze both sources and combine them into a single summary.\n\n"
                f"Text description: {user_message}"
            )
        else:
            text_content = "Summarize the workflow shown in this diagram."
        messages.append({
            "role": "user",
            "content": _image_content(text_content, image_base64, image_mime, "low"),
        })
    else:
        messages.append({"role": "user", "content": user_message})

    return messages


def generate_summary(user_message, image_base64=None, image_mime=None):
    """Plain-text summary of the user's process description for confirmation."""
    messages = _build_summary_messages(user_message, image_base64, image_mime)
    try:
        params = {
            "model": OPENAI_MODEL,
            "messages": messages,
            "max_completion_tokens": (
                MAX_SUMMARY_TOKENS_IMAGE if image_base64 else MAX_SUMMARY_TOKENS_TEXT
            ),
        }
        response = client.chat.completions.create(**params)

        message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason
        raw_content = message.content
        refusal = getattr(message, "refusal", None)

        summary = raw_content.strip() if raw_content else ""
        if not summary:
            diag = f"finish_reason={finish_reason}, refusal={refusal}, content={raw_content!r}"
            log.warning("Empty summary response: %s", diag)
            return {"summary": "", "error": f"LLM returned an empty summary ({diag})."}
        return {"summary": summary, "error": None}
    except Exception as e:
        log.exception("OpenAI summary call failed")
        return {"summary": "", "error": f"LLM API error: {str(e)}"}
