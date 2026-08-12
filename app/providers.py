"""AI provider client setup, ported from localize_claude.py's
get_available_gemini_model() / setup_openai(), minus print()/env-var reads --
keys are passed in explicitly (they come from the OS keychain via config.py)."""


def get_gemini_client(api_key):
    """Finds a working Gemini model for the given API key. Raises on failure."""
    if not api_key:
        raise ValueError("Gemini API key is not set.")
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    try:
        available_models = [
            m.name for m in genai.list_models()
            if 'generateContent' in m.supported_generation_methods
        ]
    except Exception as e:
        raise RuntimeError(f"Could not reach Gemini API: {e}") from e

    priority = ['models/gemini-1.5-flash', 'models/gemini-1.5-flash-latest', 'models/gemini-pro']
    for target in priority:
        if target in available_models:
            return genai.GenerativeModel(target), target

    if available_models:
        return genai.GenerativeModel(available_models[0]), available_models[0]

    raise RuntimeError("No Gemini models available for this API key.")


def get_openai_client(api_key):
    """Initializes the OpenAI client. Raises on failure."""
    if not api_key:
        raise ValueError("OpenAI API key is not set.")
    from openai import OpenAI
    return OpenAI(api_key=api_key), "gpt-4o-mini"


def get_client(provider, api_key):
    if provider == "gemini":
        client, model_name = get_gemini_client(api_key)
    elif provider == "openai":
        client, model_name = get_openai_client(api_key)
    else:
        raise ValueError(f"Unknown provider: {provider}")
    return client, model_name
