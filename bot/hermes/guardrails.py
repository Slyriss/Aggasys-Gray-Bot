from __future__ import annotations

import re


INVISIBLE_CHARS = (
    "\u200b", "\u200c", "\u200d", "\u2060",
    "\u2061", "\u2062", "\u2063", "\u2064",
    "\u2066", "\u2067", "\u2068", "\u2069",
    "\ufeff",
)

PROMPT_THREAT_PATTERNS = [
    (r"ignore\s+(?:\w+\s+)*(?:previous|all|above|prior)\s+(?:\w+\s+)*instructions", "prompt_injection"),
    (r"disregard\s+(your|all|any)\s+(instructions|rules|guidelines)", "disregard_rules"),
    (r"system\s+prompt\s+override", "system_prompt_override"),
    (r"do\s+not\s+tell\s+the\s+user", "deception_hide"),
    (r"cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass)", "read_secrets"),
    (r"authorized_keys", "ssh_backdoor"),
    (r"/etc/sudoers|visudo", "sudoers_modification"),
    (r"rm\s+-rf\s+/", "destructive_root_delete"),
]

SECRET_EXFIL_PATTERNS = [
    (r"curl\s+[^\n]*(?:--data|-d|--form|-F)\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD)\w*\}?", "curl_secret_exfil"),
    (r"wget\s+[^\n]*--post-(?:data|file)=[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD)\w*\}?", "wget_secret_exfil"),
]


def scan_prompt_for_threats(prompt: str) -> str:
    """Return a blocking reason for dangerous workflow prompts, else empty."""
    if not prompt:
        return ""

    for char in INVISIBLE_CHARS:
        if char in prompt:
            return f"Blocked: prompt contains invisible unicode U+{ord(char):04X}."

    for pattern, threat_id in PROMPT_THREAT_PATTERNS + SECRET_EXFIL_PATTERNS:
        if re.search(pattern, prompt, re.IGNORECASE):
            return f"Blocked: prompt matches threat pattern '{threat_id}'."

    return ""
