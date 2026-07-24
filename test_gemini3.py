import sys
from google import genai
from jatayu.config import get_config

def main():
    config = get_config()
    client = genai.Client(api_key=config['gemini_api_key'])
    
    for model in ['gemini-2.5-flash', 'gemini-flash-latest', 'gemini-3.1-flash-lite']:
        try:
            print(f"Testing {model}...")
            response = client.models.generate_content(
                model=model,
                contents='Hello!'
            )
            print(f"Success for {model}:", response.text)
        except Exception as e:
            print(f"Failed for {model}:", e)

if __name__ == "__main__":
    main()
