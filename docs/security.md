# Security

- Recursive redaction covers keys containing token, api_key, apikey, secret,
  password, passwd, authorization, cookie, credential, private_key, or
  access_key.
- Bearer token auth is optional and read from environment variables.
- The sidecar defaults to `127.0.0.1`.
- `/v1/status` does not return token values.
