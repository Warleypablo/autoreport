# env2gcloud.py
with open(".env.cloudrun") as f:
    pairs = []
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"): continue
        key, value = line.split("=", 1)
        value = value.strip('"')
        pairs.append(f"{key}={value}")
print(",".join(pairs))