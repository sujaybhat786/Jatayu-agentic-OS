import sys
from google import genai
from jatayu.config import get_config

def main():
    config = get_config()
    print(f"Testing Gemini API Key: {config['gemini_api_key'][:5]}...")
    client = genai.Client(api_key=config['gemini_api_key'])
    
    # Try gemini-1.5-flash
    try:
        print("Testing gemini-1.5-flash...")
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents='Hello!'
        )
        print("Success for gemini-1.5-flash:", response.text)
    except Exception as e:
        print("Failed for gemini-1.5-flash:", e)

    # Try gemini-2.0-flash
    try:
        print("Testing gemini-2.0-flash...")
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents='Hello!'
        )
        print("Success for gemini-2.0-flash:", response.text)
    except Exception as e:
        print("Failed for gemini-2.0-flash:", e)

    # Try gemini-3.5-flash
    try:
        print("Testing gemini-3.5-flash...")
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents='Hello!'
        )
        print("Success for gemini-3.5-flash:", response.text)
    except Exception as e:
        print("Failed for gemini-3.5-flash:", e)

if __name__ == "__main__":
    main()
