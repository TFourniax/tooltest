"""Shared lightweight grammar selection and exact package pins; no adapters loaded."""
from __future__ import annotations

PINNED = {'tree-sitter': '0.25.2', 'tree-sitter-javascript': '0.25.0', 'tree-sitter-typescript': '0.23.2',
          'tree-sitter-go': '0.25.0', 'tree-sitter-rust': '0.24.2',
          'tree-sitter-java': '0.23.5', 'tree-sitter-c-sharp': '0.23.5', 'tree-sitter-kotlin': '1.1.0', 'tree-sitter-ruby': '0.23.1', 'tree-sitter-php': '0.24.1', 'tree-sitter-sql': '0.3.11', 'tree-sitter-json': '0.24.8',
          'tree-sitter-toml': '0.7.0', 'tree-sitter-yaml': '0.7.2'}
SPECS = {
    **{suffix: ('javascript', 'tree-sitter-javascript', 'tree_sitter_javascript', 'language')
       for suffix in ('.js', '.jsx', '.mjs', '.cjs')},
    **{suffix: ('typescript', 'tree-sitter-typescript', 'tree_sitter_typescript', 'language_typescript')
       for suffix in ('.ts', '.mts', '.cts')},
    '.tsx': ('typescript', 'tree-sitter-typescript', 'tree_sitter_typescript', 'language_tsx'),
    '.go': ('go', 'tree-sitter-go', 'tree_sitter_go', 'language'),
    '.rs': ('rust', 'tree-sitter-rust', 'tree_sitter_rust', 'language'),
    **{'.' + lang: (lang, 'tree-sitter-' + lang, 'tree_sitter_' + lang, 'language')
       for lang in ('sql', 'json', 'toml', 'yaml')},
    '.yml': ('yaml', 'tree-sitter-yaml', 'tree_sitter_yaml', 'language'),
    '.rb': ('ruby', 'tree-sitter-ruby', 'tree_sitter_ruby', 'language'),
    '.php': ('php', 'tree-sitter-php', 'tree_sitter_php', 'language_php'),
    '.java': ('java', 'tree-sitter-java', 'tree_sitter_java', 'language'),
    '.cs': ('csharp', 'tree-sitter-c-sharp', 'tree_sitter_c_sharp', 'language'),
    **{suffix: ('kotlin', 'tree-sitter-kotlin', 'tree_sitter_kotlin', 'language') for suffix in ('.kt', '.kts')},
}
