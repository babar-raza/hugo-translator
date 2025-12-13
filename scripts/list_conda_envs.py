"""List and clone conda environments."""
import subprocess
import sys
import json

print("Listing conda environments...")
print("=" * 80)

result = subprocess.run(
    [r"C:\Users\prora\anaconda3\Scripts\conda.exe", "env", "list", "--json"],
    capture_output=True,
    text=True
)

if result.returncode == 0:
    try:
        envs_data = json.loads(result.stdout)
        envs = envs_data.get("envs", [])
        print(f"Found {len(envs)} conda environments:\n")
        for env_path in envs:
            env_name = env_path.split("\\")[-1] if "\\" in env_path else env_path.split("/")[-1]
            print(f"  - {env_name}: {env_path}")
    except json.JSONDecodeError:
        print("Raw output:")
        print(result.stdout)
else:
    print(f"Error: {result.stderr}")
    sys.exit(1)
