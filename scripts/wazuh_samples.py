"""Synthetic audit fixtures; no real user data or secrets."""
import json

SAMPLES = {
    "view": (110000, 3),
    "malware_detected": (110001, 12),
    "admin_breakglass": (110002, 12),
    "change_acl": (110003, 8),
    "legal_hold_enabled": (110004, 8),
    "legal_hold_disabled": (110004, 8),
    "retention_changed": (110004, 8),
    "classification_changed": (110004, 8),
    "quota_exceeded": (110005, 5),
    "login_failed": (110006, 5),
    "access_denied": (110010, 5),
    "download": (110012, 3),
    "purge_started": (110014, 8),
}
if __name__ == "__main__":
    for event, (rule, level) in SAMPLES.items():
        print(f"{rule}\t{level}\t" + json.dumps({
            "application": "nambadrive", "schema_version": 1,
            "event_type": event, "result": "denied" if event == "access_denied" else "success",
            "user": "synthetic-test", "resource": "synthetic-resource", "ip": "192.0.2.1",
            "user_agent": "CI", "correlation_id": "synthetic-correlation",
        }))
