#!/usr/bin/env python3
"""Offline GitHub CLI stub. Every request must have an explicit response."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

args = sys.argv[1:]
state_file = Path(os.environ["KOWSU_TEST_STATE"])
state = json.loads(state_file.read_text())
state["calls"].append(args)
if args[0] == "api":
    key = next(arg for arg in args if arg.startswith("repos/") or arg == "graphql")
else:
    key = " ".join(args[:3])
responses = state["routes"].get(key, [])
if not responses:
    state_file.write_text(json.dumps(state))
    sys.exit("Unexpected gh request: " + repr(args))
response = responses.pop(0)
state_file.write_text(json.dumps(state))

status = response.get("status", 200)
if "--include" in args:
    sys.stdout.write(f"HTTP/2.0 {status} Test\r\nContent-Type: application/json\r\n\r\n")
    sys.stdout.flush()
if "zip" in response:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in response["zip"].items():
            archive.writestr(name, content)
    sys.stdout.buffer.write(output.getvalue())
elif "pages" in response or "json" in response:
    pages = response.get("pages", [response.get("json")])
    if "--paginate" not in args:
        pages = pages[:1]
    for page in pages:
        if "--jq" in args:
            query = args[args.index("--jq") + 1]
            result = subprocess.run(["jq", "-r", query], input=json.dumps(page), text=True)
            if result.returncode:
                sys.exit(result.returncode)
        else:
            print(json.dumps(page))
else:
    sys.stdout.write(response.get("stdout", ""))
if response.get("stderr"):
    print(response["stderr"], file=sys.stderr)
sys.exit(response.get("exit", 1 if status >= 400 else 0))
