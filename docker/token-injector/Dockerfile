# Syn137 Token Injector
# HTTP ext_authz service that injects credentials into agent requests (ISS-43).
# Uses Python stdlib only — no external packages needed.

FROM python:3.12-slim

WORKDIR /app
COPY token_injector.py .

EXPOSE 9002

CMD ["python", "token_injector.py"]
