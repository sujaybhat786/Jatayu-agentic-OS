import json

new_id = input("Paste the new Client ID: ").strip()
new_secret = input("Paste the new Client Secret: ").strip()

data = {
    "web": {
        "client_id": new_id,
        "project_id": "jatayu-os",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": new_secret,
        "redirect_uris": ["http://localhost:8000/api/integrations/google/callback"]
    }
}

with open("credentials.json", "w") as f:
    json.dump(data, f)

print("✅ Created credentials.json successfully.")
