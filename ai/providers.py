import json
import logging

from openai import OpenAI

from .models import LLMProviderConfig


logger = logging.getLogger(__name__)


class ProviderConfigurationError(Exception):
    pass


class OpenAICompatibleProvider:
    def __init__(self, config: LLMProviderConfig):
        if not config.is_enabled or not config.api_key_encrypted:
            raise ProviderConfigurationError("请先配置当前组织的 AI API Key")
        options = {"api_key": config.get_api_key()}
        if config.base_url:
            options["base_url"] = config.base_url
        self.config = config
        self.client = OpenAI(**options)

    def stream(self, messages):
        return self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            stream=True,
        )

    def complete_json(self, messages):
        options = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            response = self.client.chat.completions.create(**options)
        except Exception as first_error:
            # Some compatible endpoints do not implement response_format.
            logger.info("JSON response format unsupported by configured provider; retrying without it")
            options.pop("response_format")
            try:
                response = self.client.chat.completions.create(**options)
            except Exception:
                raise first_error
        return response.choices[0].message.content or ""


def parse_json_response(content):
    text = (content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.strip().startswith("```"))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("AI 返回的功能方案不是有效 JSON")
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("AI 返回的功能方案不是有效 JSON") from exc


def get_provider(organization):
    config = LLMProviderConfig.objects.filter(organization=organization, is_enabled=True).first()
    if config is None:
        raise ProviderConfigurationError("请先配置当前组织的 AI 模型")
    return OpenAICompatibleProvider(config)
