import json
import os

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

load_dotenv()

DEFAULT_MODEL = "gpt-6-luna"


class LLMError(Exception):
    """화면에 그대로 보여 줘도 되는 한국어 한 줄 에러."""


def ask_json(instructions, user_input, schema, name):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMError("OPENAI_API_KEY 가 없어요. .env 파일을 확인해 주세요.")

    model = os.getenv("OPENAI_MODEL") or DEFAULT_MODEL
    try:
        response = OpenAI(api_key=api_key).responses.create(
            model=model,
            instructions=instructions,
            input=user_input,
            text={
                "format": {
                    "type": "json_schema",
                    "name": name,
                    "schema": schema,
                    "strict": True,
                }
            },
        )
        return json.loads(response.output_text)
    except AuthenticationError:
        raise LLMError("API 키가 올바르지 않아요. 키를 다시 확인해 주세요.") from None
    except RateLimitError:
        raise LLMError("크레딧이 부족하거나 요청이 너무 많아요. 잠시 후 다시 시도해 주세요.") from None
    except APIConnectionError:
        raise LLMError("OpenAI에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.") from None
    except APIError:
        raise LLMError("OpenAI 요청에 실패했어요. 잠시 후 다시 시도해 주세요.") from None
    except (ValueError, TypeError):
        raise LLMError("AI 답변을 읽지 못했어요. 다시 시도해 주세요.") from None
