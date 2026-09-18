"""Role/permission + business-rule detection via decorator/guard-clause patterns."""
from __future__ import annotations
import os, re, json
from sqlalchemy.orm import Session
from app.models.models import CodeSymbol, SourceFile, Role, BusinessRule, ApiEndpoint

ROLE_PATTERNS = [
    (re.compile(r"@(?:login_required|permission_required|roles_required|requires_auth|authorize)[^\n]*", re.I), "decorator"),
    (re.compile(r"@roles_allowed\s*\(([^)]+)\)"), "roles_allowed"),
    (re.compile(r"if\s+.*user\.role\s*==\s*['\"](\w+)['\"]"), "role-check"),
    (re.compile(r"if\s+not?\s+.*\.has_(?:perm|permission|role)"), "perm-check"),
    (re.compile(r"IsAuthenticated|IsAdminUser|DjangoModelPermissions|has_permission", re.I), "drf-perm"),
    (re.compile(r"canActivate|AuthGuard|roleGuard|allowedRoles", re.I), "fe-guard"),
]
ROLE_NAME_RE = re.compile(r"['\"](admin\w*|manager\w*|owner\w*|staff\w*|user\w*|viewer\w*|editor\w*|ba\w*|pm\w*)['\"]", re.I)

RULE_PATTERNS = [
    (re.compile(r"raise\s+(?:ValidationError|ValueError|PermissionDenied| serializers\.ValidationError)"), "validation-raise"),
    (re.compile(r"if\s+.*(?:status|state|stock|quantity|amount|total|balance|role|approval|approved).*(?:!=|==|<=|>=|<|>).*:") , "guard-clause"),
    (re.compile(r"def\s+clean(?:_|s)|def\s+validate_\w+|def\s+clean\w*"), "validator-fn"),
    (re.compile(r"validators\s*=\s*\["), "validator-list"),
    (re.compile(r"serializers\.\w+Field.*required=True|blank=False|null=False"), "required-field"),
    (re.compile(r"CHECK\s*\(|check\s*=\s*models\.\w+\(.*check"), "db-check"),
]


def _text(repo_dir, rel):
    try:
        with open(os.path.join(repo_dir, rel), "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def run_role_rule_detection(db: Session, project_id: int, repo_dir: str,
                            module_map: dict[str, int]) -> tuple[int, int]:
    from app.analysis.functional.modules import infer_module_name
    symbols = db.query(CodeSymbol).filter(CodeSymbol.project_id == project_id).all()
    files = {sf.id: sf for sf in db.query(SourceFile).filter(SourceFile.project_id == project_id).all()}
    db.query(Role).filter(Role.project_id == project_id).delete()
    db.query(BusinessRule).filter(BusinessRule.project_id == project_id).delete()
    db.commit()
    roles_found: dict[str, set[str]] = {}
    n_rules = 0
    for s in symbols:
        sf = files.get(s.source_file_id)
        if not sf:
            continue
        text = _text(repo_dir, sf.path)
        snippet = "\n".join(text.splitlines()[max(0, s.start_line - 3):s.end_line + 2])
        for pat, kind in ROLE_PATTERNS:
            m = pat.search(snippet) or pat.search(text[:8000])
            if m:
                names = ROLE_NAME_RE.findall(snippet) or ["authenticated"]
                for rname in set(x.lower() for x in names):
                    roles_found.setdefault(rname, set()).add(sf.path)
                # attach to endpoint if this symbol is a handler
                ep = db.query(ApiEndpoint).filter(
                    ApiEndpoint.project_id == project_id,
                    ApiEndpoint.handler_symbol_id == s.id).first()
                if ep:
                    try:
                        cur = json.loads(ep.roles_allowed or "[]")
                    except Exception:
                        cur = []
                    ep.roles_allowed = json.dumps(sorted(set(cur) | {x.lower() for x in names}))
                    ep.auth_required = "yes"
                    db.add(ep)
                break
        for pat, kind in RULE_PATTERNS:
            m = pat.search(snippet)
            if m:
                mod = module_map.get(infer_module_name(sf.path))
                desc = f"{kind}: `{snippet.strip()[:300]}` in {s.name} ({sf.path}:{s.start_line})"
                db.add(BusinessRule(project_id=project_id, description=desc,
                                    source_symbol_id=s.id, module_id=mod,
                                    trigger_condition=m.group(0)[:300]))
                n_rules += 1
                break
    for rname, paths in roles_found.items():
        db.add(Role(project_id=project_id, name=rname,
                    permissions_json=json.dumps({"seen_in": sorted(paths)[:20]})))
    db.commit()
    return len(roles_found), n_rules
