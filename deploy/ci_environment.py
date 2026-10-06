"""Generate disposable smoke-test credentials; never use sample passwords in deployments."""

import json
import os
import secrets
from pathlib import Path

users = [
    {"login": f"editor{i}", "name": f"Test {i}", "password": secrets.token_urlsafe(24)}
    for i in range(1, 5)
]
Path(".env").write_text(
    "POSTGRES_PASSWORD="
    + secrets.token_hex(24)
    + "\nALLOWED_HOSTS=localhost,127.0.0.1\nSECURE_COOKIES=false\nBOOTSTRAP_USERS='"
    + json.dumps(users)
    + "'\n"
)

if os.getenv("GITHUB_ENV"):
    with open(os.environ["GITHUB_ENV"], "a") as f:
        f.write(
            "E2E_LOGIN="
            + users[0]["login"]
            + "\nE2E_PASSWORD="
            + users[0]["password"]
            + "\n"
        )
