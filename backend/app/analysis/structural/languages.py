"""Language detection by extension."""
EXT_MAP = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".java": "java", ".go": "go", ".rb": "ruby", ".php": "php",
    ".cs": "csharp", ".cpp": "cpp", ".c": "c", ".h": "c", ".rs": "rust", ".html": "html",
    ".vue": "vue", ".svelte": "svelte", ".sql": "sql", ".yml": "yaml", ".yaml": "yaml",
    ".json": "json", ".md": "markdown", ".xml": "xml", ".kt": "kotlin", ".swift": "swift",
}


def detect_language(path: str) -> str:
    import os
    return EXT_MAP.get(os.path.splitext(path)[1].lower(), "unknown")
