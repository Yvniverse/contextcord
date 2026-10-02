"""Validate packaged schemas, profile contracts and generated adapter JSON."""
import json
import tempfile
from pathlib import Path
import tomllib
from jsonschema import Draft202012Validator
from contextcord.adapters import capabilities, render
from contextcord.contracts import validate
from contextcord.profiles import PROFILES

root=Path(__file__).resolve().parents[1]
for path in (root/'src/contextcord/schemas').glob('*.json'):
    schema=json.loads(path.read_text()); Draft202012Validator.check_schema(schema)
    assert schema==json.loads((root/'schemas'/path.name).read_text()),path.name
for profile, manifests in PROFILES.items():
    for name,text in zip(('project','truth','workflow','authority','runtime','evidence','qualification'),manifests):
        validate(name,tomllib.loads(text))
with tempfile.TemporaryDirectory() as td:
    for host in capabilities():
        for path in render(host,Path(td)/host):
            if path.suffix=='.json': json.loads(path.read_text())
print('PASS: schemas, profiles and generated adapter JSON')
