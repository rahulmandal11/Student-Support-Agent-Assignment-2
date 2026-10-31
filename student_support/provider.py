"""Groq is the only production model provider. Tests inject a scripted adapter."""
from groq import Groq, APIConnectionError, APIStatusError, APITimeoutError


class ProviderError(Exception):
    pass


class GroqProvider:
    label = "groq"

    def __init__(self, api_key, model):
        self.api_key = api_key
        self.model = model

    def complete(self, messages, tools):
        if not self.api_key:
            raise ProviderError("Groq is not configured. Add GROQ_API_KEY to your local .env file and restart the app.")
        try:
            with Groq(api_key=self.api_key, timeout=25, max_retries=1) as client:
                response = client.chat.completions.create(
                    model=self.model, messages=messages, tools=tools,
                    tool_choice="auto", temperature=0, max_completion_tokens=1200,
                    parallel_tool_calls=False,
                )
            return response.model_dump(exclude_none=True)
        except (APIConnectionError, APITimeoutError) as exc:
            raise ProviderError("Groq could not be reached. Please try again shortly.") from exc
        except APIStatusError as exc:
            if exc.status_code == 429:
                message = "Groq's rate limit was reached. Please wait and try again."
            elif exc.status_code in (401, 403):
                message = "Groq rejected the API credentials or model access. Check the local configuration."
            elif exc.status_code == 404:
                message = "The configured Groq model is unavailable to this account. Set GROQ_MODEL in .env to an available tool-calling model and restart the app."
            else:
                message = "Groq could not complete this request. Check your model configuration or try again."
            raise ProviderError(message) from exc
