import sys
try:
    from google import genai
    from google.genai import types
    print("genai version:", getattr(genai, '__version__', 'unknown'))
    config = types.GenerateContentConfig(
        http_options=types.HttpOptions(timeout=2.0)
    )
    print("Success")
except Exception as e:
    print(f"Error: {e}")
