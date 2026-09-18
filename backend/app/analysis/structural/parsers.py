
from __future__ import annotations
import ast, re
from dataclasses import dataclass


@dataclass
class Symbol:
    kind: str
    name: str
    start_line: int
    end_line: int
    signature: str = ""
    docstring: str = ""


def parse_python(source: str) -> list[Symbol]:
    out: list[Symbol] = []
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                out.append(Symbol("class", node.name, node.lineno,
                                  getattr(node, "end_lineno", node.lineno) or node.lineno,
                                  f"class {node.name}", ast.get_docstring(node) or ""))
                base_names = [b.id for b in node.bases if isinstance(b, ast.Name)] + \
                             [b.attr for b in node.bases if isinstance(b, ast.Attribute)]
                if any(b in ("Base", "Model", "SQLModel", "DeclarativeBase") or "Model" in b for b in base_names):
                    out.append(Symbol("model", node.name, node.lineno,
                                      getattr(node, "end_lineno", node.lineno) or node.lineno,
                                      f"class {node.name}", ast.get_docstring(node) or ""))
                if any("Form" in b for b in base_names):
                    out.append(Symbol("form", node.name, node.lineno,
                                      getattr(node, "end_lineno", node.lineno) or node.lineno,
                                      f"class {node.name}", ast.get_docstring(node) or ""))
                if any("Serializer" in b for b in base_names):
                    out.append(Symbol("serializer", node.name, node.lineno,
                                      getattr(node, "end_lineno", node.lineno) or node.lineno,
                                      f"class {node.name}", ast.get_docstring(node) or ""))

                # Extract class fields (form fields, serializer fields, model fields)
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                out.append(Symbol("field", f"{node.name}.{target.id}", item.lineno, item.lineno, f"{target.id} field in {node.name}"))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [a.arg for a in node.args.args]
                out.append(Symbol("function", node.name, node.lineno,
                                  getattr(node, "end_lineno", node.lineno) or node.lineno,
                                  f"{node.name}({', '.join(args)})", ast.get_docstring(node) or ""))
    except SyntaxError:
        pass

    # Function regex fallback (for partial or indented snippets)
    if not any(s.kind == "function" for s in out):
        for m in re.finditer(r"(?:async\s+)?def\s+([a-zA-Z_]\w*)\s*\(([^)]*)\)", source):
            line = source[:m.start()].count("\n") + 1
            out.append(Symbol("function", m.group(1), line, line, f"{m.group(1)}({m.group(2)})"))

    # routes: Flask/FastAPI/Django decorators
    for m in re.finditer(
            r"@(?:app|router|api|blueprint)\.(get|post|put|patch|delete|route)\(['\"]([^'\"]+)['\"]",
            source):
        line = source[:m.start()].count("\n") + 1
        out.append(Symbol("route", f"{m.group(1).upper()} {m.group(2)}", line, line, m.group(0)))
    for m in re.finditer(r"path\(['\"]([^'\"]+)['\"],\s*([\w.]+)", source):
        line = source[:m.start()].count("\n") + 1
        out.append(Symbol("route", f"DJANGO {m.group(1)} -> {m.group(2)}", line, line, m.group(0)))
    # models: SQLAlchemy / Django / SQLModel
    for m in re.finditer(r"class\s+(\w+)\((?:Base|Model|models\.Model|SQLModel)[^)]*\)", source):
        line = source[:m.start()].count("\n") + 1
        if not any(s.kind == "model" and s.name == m.group(1) for s in out):
            out.append(Symbol("model", m.group(1), line, line, m.group(0)))
    return out


_FN_RE = re.compile(r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(|(\w+)\s*:\s*function\s*\(|(?:export\s+)?(?:async\s+)?function\s+(\w+))")
_CLASS_RE = re.compile(r"class\s+(\w+)")
_COMP_RE = re.compile(r"(?:export\s+default\s+function\s+([A-Z]\w*)|(?:const|let|var)\s+([A-Z]\w*)\s*=\s*(?:\([^)]*\)|[^=]*?)\s*=>)")
_ROUTE_RE = re.compile(r"(?:app|router)\.(get|post|put|patch|delete|use)\(\s*['\"`]([^'\"`]+)['\"`]")
_FETCH_RE = re.compile(r"(?:fetch\(\s*['\"`]([^'\"`]+)['\"`]|axios\.(get|post|put|patch|delete)\(\s*['\"`]([^'\"`]+)['\"`])")


def parse_js_ts(source: str) -> list[Symbol]:
    out: list[Symbol] = []
    for i, line in enumerate(source.splitlines(), 1):
        m = _CLASS_RE.search(line)
        if m:
            out.append(Symbol("class", m.group(1), i, i, line.strip()))
            continue
        m = _COMP_RE.search(line)
        if m:
            out.append(Symbol("component", m.group(1) or m.group(2), i, i, line.strip()[:200]))
            continue
        m = _FN_RE.search(line)
        if m:
            name = m.group(1) or m.group(2) or m.group(3) or m.group(4)
            if name:
                out.append(Symbol("function", name, i, i, line.strip()[:200]))
        m = _ROUTE_RE.search(line)
        if m:
            out.append(Symbol("route", f"{m.group(1).upper()} {m.group(2)}", i, i, line.strip()[:200]))
        m = _FETCH_RE.search(line)
        if m:
            out.append(Symbol("function", f"api_call:{m.group(1) or m.group(3)}", i, i, line.strip()[:200]))
    return out


def parse_generic(source: str, language: str) -> list[Symbol]:
    """Fallback for Java/Go/Ruby/PHP/C#: class + function-ish lines."""
    out: list[Symbol] = []
    for i, line in enumerate(source.splitlines(), 1):
        s = line.strip()
        m = re.match(r"(?:public|private|protected|static|\s)*(?:class|interface|struct|enum)\s+(\w+)", s)
        if m:
            out.append(Symbol("class", m.group(1), i, i, s[:200]))
            continue
        m = re.match(r"(?:public|private|protected|static|def|func|fn|\s)*[\w<>\[\]]+\s+(\w+)\s*\(", s)
        if m and len(s) < 200 and not s.startswith(("//", "#", "*", "import ")):
            out.append(Symbol("function", m.group(1), i, i, s[:200]))
    return out


def try_treesitter(source: str, language: str) -> list[Symbol] | None:
    """Best-effort tree-sitter use; returns None when unavailable."""
    try:
        import tree_sitter  # noqa
    except ImportError:
        return None
    return None  # grammar loading is env-specific; regex/ast path is authoritative here


def parse_html_template(source: str) -> list[Symbol]:
    out: list[Symbol] = []
    lines = source.splitlines()

    # 1. Forms
    for m in re.finditer(r"<form\b([^>]*)>", source, re.IGNORECASE):
        line = source[:m.start()].count("\n") + 1
        attrs = m.group(1)
        action_m = re.search(r'action=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        method_m = re.search(r'method=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        action = action_m.group(1) if action_m else ""
        method = (method_m.group(1) if method_m else "POST").upper()
        out.append(Symbol("form", f"form {method} {action}".strip(), line, line, m.group(0)[:200]))

    # 2. Input / Select / Textarea fields
    for m in re.finditer(r"<(?:input|select|textarea)\b([^>]*)/?>", source, re.IGNORECASE):
        line = source[:m.start()].count("\n") + 1
        attrs = m.group(1)
        name_m = re.search(r'name=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        id_m = re.search(r'id=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        inp_type_m = re.search(r'type=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        inp_name = name_m.group(1) if name_m else (id_m.group(1) if id_m else "")
        inp_type = inp_type_m.group(1) if inp_type_m else "text"
        if inp_name:
            out.append(Symbol("form_field", f"field:{inp_name}", line, line, f"<{inp_type} name='{inp_name}'>"))

    # 3. Headings & Labels (Functional UI concepts like 'Shipping address', 'Billing address')
    for m in re.finditer(r"<(?:h[1-6]|label|legend)\b[^>]*>([^<]+)</(?:h[1-6]|label|legend)>", source, re.IGNORECASE):
        line = source[:m.start()].count("\n") + 1
        label_text = m.group(1).strip()
        if len(label_text) >= 3 and not label_text.startswith("{%"):
            out.append(Symbol("ui_label", label_text[:100], line, line, label_text[:200]))

    # 4. Buttons and submit triggers
    for m in re.finditer(r"<button\b[^>]*>([^<]+)</button>", source, re.IGNORECASE):
        line = source[:m.start()].count("\n") + 1
        btn_text = m.group(1).strip()
        if btn_text:
            out.append(Symbol("button", f"button:{btn_text[:60]}", line, line, btn_text[:150]))

    return out


def parse_source(source: str, language: str) -> list[Symbol]:
    ts = try_treesitter(source, language)
    if ts is not None:
        return ts
    if language == "python":
        return parse_python(source)
    if language in ("html", "jinja", "django", "xml"):
        return parse_html_template(source)
    if language in ("vue", "svelte"):
        return parse_js_ts(source) + parse_html_template(source)
    if language in ("javascript", "typescript"):
        return parse_js_ts(source)
    return parse_generic(source, language)

