from google import genai
try:
    client = genai.Client(api_key="fake", http_options={'timeout': 2.0})
    print("Success")
except Exception as e:
    print(f"Error: {e}")
