#!/usr/bin/env python
"""
CLI Import Analyzer - Static analysis to find undefined names before runtime.

This tool parses Python AST to find all names used in functions that are not:
- Imported at module level or within enclosing scope
- Imported within the function itself
- Defined as parameters or local variables
- Defined in enclosing function scopes (closures)
- Python builtins

Run: python scripts/analyze_cli_imports.py [file_path]
Default: src/cli.py

This catches NameError issues BEFORE runtime.
"""

import ast
import builtins
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

BUILTIN_NAMES = set(dir(builtins))
# Add common typing names
TYPING_NAMES = {
    "Dict",
    "List",
    "Set",
    "Tuple",
    "Optional",
    "Union",
    "Any",
    "Callable",
    "Type",
    "Sequence",
    "Mapping",
    "Iterable",
    "TYPE_CHECKING",
    "cast",
    "overload",
    "Final",
    "Literal",
    "TypeVar",
    "Generic",
    "Protocol",
    "ClassVar",
    "NamedTuple",
    "TypedDict",
    "Annotated",
}


@dataclass
class FunctionScope:
    """Track names available in a function scope."""

    name: str
    lineno: int
    qualified_name: str  # Full path like outer_func.inner_func
    parameters: set[str] = field(default_factory=set)
    local_assignments: set[str] = field(default_factory=set)
    local_imports: set[str] = field(default_factory=set)
    names_used: dict[str, int] = field(default_factory=dict)  # name -> first line used
    comprehension_vars: set[str] = field(default_factory=set)
    nested_function_names: set[str] = field(default_factory=set)
    parent_scope: Optional["FunctionScope"] = None


@dataclass
class UndefinedName:
    """Record of an undefined name usage."""

    name: str
    function: str
    lineno: int
    context: str


class ImportAnalyzer(ast.NodeVisitor):
    """AST visitor that tracks imports and name usage with proper closure support."""

    def __init__(self, source_code: str):
        self.source_lines = source_code.splitlines()
        self.module_level_names: set[str] = set()
        self.type_checking_names: set[str] = set()
        self.function_scopes: list[FunctionScope] = []
        self.scope_stack: list[FunctionScope] = []  # Stack for nested functions
        self.in_type_checking_block = False
        self.class_names: set[str] = set()
        self.undefined_names: list[UndefinedName] = []

    @property
    def current_scope(self) -> FunctionScope | None:
        return self.scope_stack[-1] if self.scope_stack else None

    def get_line_context(self, lineno: int) -> str:
        if 0 < lineno <= len(self.source_lines):
            return self.source_lines[lineno - 1].strip()
        return ""

    def visit_Import(self, node: ast.Import):
        names = {alias.asname or alias.name.split(".")[0] for alias in node.names}
        if self.current_scope:
            self.current_scope.local_imports.update(names)
        elif self.in_type_checking_block:
            self.type_checking_names.update(names)
        else:
            self.module_level_names.update(names)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        names = set()
        for alias in node.names:
            if alias.name == "*":
                continue
            names.add(alias.asname or alias.name)

        if self.current_scope:
            self.current_scope.local_imports.update(names)
        elif self.in_type_checking_block:
            self.type_checking_names.update(names)
        else:
            self.module_level_names.update(names)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        if not self.current_scope:
            self.module_level_names.add(node.name)
            self.class_names.add(node.name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        # Add function name to enclosing scope or module
        if self.current_scope:
            self.current_scope.nested_function_names.add(node.name)
            self.current_scope.local_assignments.add(node.name)
            qualified_name = f"{self.current_scope.qualified_name}.{node.name}"
            parent = self.current_scope
        else:
            self.module_level_names.add(node.name)
            qualified_name = node.name
            parent = None

        # Create new scope
        new_scope = FunctionScope(
            name=node.name,
            lineno=node.lineno,
            qualified_name=qualified_name,
            parameters=self._extract_parameters(node),
            parent_scope=parent,
        )

        # Push scope and visit
        self.scope_stack.append(new_scope)
        for child in ast.iter_child_nodes(node):
            self.visit(child)
        self.scope_stack.pop()

        self.function_scopes.append(new_scope)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _extract_parameters(self, node: ast.FunctionDef) -> set[str]:
        params = set()
        args = node.args
        for arg in args.args:
            params.add(arg.arg)
        if args.vararg:
            params.add(args.vararg.arg)
        if args.kwarg:
            params.add(args.kwarg.arg)
        for arg in args.kwonlyargs:
            params.add(arg.arg)
        if hasattr(args, "posonlyargs"):
            for arg in args.posonlyargs:
                params.add(arg.arg)
        return params

    def visit_Assign(self, node: ast.Assign):
        if self.current_scope:
            for target in node.targets:
                self._extract_assigned_names(target, self.current_scope.local_assignments)
        else:
            for target in node.targets:
                self._extract_assigned_names(target, self.module_level_names)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if node.target and isinstance(node.target, ast.Name):
            if self.current_scope:
                self.current_scope.local_assignments.add(node.target.id)
            else:
                self.module_level_names.add(node.target.id)
        self.generic_visit(node)

    def visit_For(self, node: ast.For):
        if self.current_scope:
            self._extract_assigned_names(node.target, self.current_scope.local_assignments)
        self.generic_visit(node)

    def visit_With(self, node: ast.With):
        if self.current_scope:
            for item in node.items:
                if item.optional_vars:
                    self._extract_assigned_names(
                        item.optional_vars, self.current_scope.local_assignments
                    )
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        if self.current_scope and node.name:
            self.current_scope.local_assignments.add(node.name)
        self.generic_visit(node)

    def visit_ListComp(self, node: ast.ListComp):
        if self.current_scope:
            for gen in node.generators:
                self._extract_assigned_names(gen.target, self.current_scope.comprehension_vars)
        self.generic_visit(node)

    def visit_SetComp(self, node: ast.SetComp):
        if self.current_scope:
            for gen in node.generators:
                self._extract_assigned_names(gen.target, self.current_scope.comprehension_vars)
        self.generic_visit(node)

    def visit_DictComp(self, node: ast.DictComp):
        if self.current_scope:
            for gen in node.generators:
                self._extract_assigned_names(gen.target, self.current_scope.comprehension_vars)
        self.generic_visit(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp):
        if self.current_scope:
            for gen in node.generators:
                self._extract_assigned_names(gen.target, self.current_scope.comprehension_vars)
        self.generic_visit(node)

    def _extract_assigned_names(self, node: ast.AST, target_set: set[str]):
        if isinstance(node, ast.Name):
            target_set.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                self._extract_assigned_names(elt, target_set)
        elif isinstance(node, ast.Starred):
            self._extract_assigned_names(node.value, target_set)

    def visit_Name(self, node: ast.Name):
        if self.current_scope and isinstance(node.ctx, ast.Load):
            if node.id not in self.current_scope.names_used:
                self.current_scope.names_used[node.id] = node.lineno
        self.generic_visit(node)

    def visit_If(self, node: ast.If):
        if isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
            old_in_type_checking = self.in_type_checking_block
            self.in_type_checking_block = True
            for child in node.body:
                self.visit(child)
            self.in_type_checking_block = old_in_type_checking
            for child in node.orelse:
                self.visit(child)
        else:
            self.generic_visit(node)

    def _get_closure_names(self, scope: FunctionScope) -> set[str]:
        """Get all names available via closure from parent scopes."""
        closure_names = set()
        parent = scope.parent_scope
        while parent:
            closure_names.update(parent.parameters)
            closure_names.update(parent.local_assignments)
            closure_names.update(parent.local_imports)
            closure_names.update(parent.nested_function_names)
            closure_names.update(parent.comprehension_vars)
            parent = parent.parent_scope
        return closure_names

    def analyze(self) -> list[UndefinedName]:
        """Analyze all function scopes for undefined names."""
        for scope in self.function_scopes:
            # Collect all available names
            available = (
                self.module_level_names
                | scope.parameters
                | scope.local_assignments
                | scope.local_imports
                | scope.comprehension_vars
                | scope.nested_function_names
                | self._get_closure_names(scope)
                | BUILTIN_NAMES
                | TYPING_NAMES
            )

            for name, lineno in scope.names_used.items():
                if name not in available:
                    self.undefined_names.append(
                        UndefinedName(
                            name=name,
                            function=scope.qualified_name,
                            lineno=lineno,
                            context=self.get_line_context(lineno),
                        )
                    )

        return self.undefined_names


def analyze_file(file_path: Path) -> list[UndefinedName]:
    """Analyze a Python file for undefined names."""
    source_code = file_path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source_code)
    except SyntaxError as e:
        print(f"Syntax error in {file_path}: {e}")
        return []

    analyzer = ImportAnalyzer(source_code)
    analyzer.visit(tree)
    return analyzer.analyze()


def main():
    if len(sys.argv) > 1:
        file_path = Path(sys.argv[1])
    else:
        file_path = Path("src/cli.py")

    if not file_path.exists():
        print(f"File not found: {file_path}")
        sys.exit(1)

    print(f"Analyzing {file_path} for undefined names...")
    print("=" * 70)

    undefined = analyze_file(file_path)

    if not undefined:
        print("No undefined names found!")
        print("\nAll names used in functions are properly imported or defined.")
        sys.exit(0)

    # Group by name
    by_name: dict[str, list[UndefinedName]] = defaultdict(list)
    for undef in undefined:
        by_name[undef.name].append(undef)

    print(f"\nFound {len(by_name)} potentially undefined names:\n")

    for name, occurrences in sorted(by_name.items()):
        print(f"  {name}")
        for occ in occurrences:
            print(f"    Line {occ.lineno}: {occ.function}")
            print(f"      {occ.context}")
        print()

    print("=" * 70)
    print(f"TOTAL: {len(by_name)} undefined names in {len(undefined)} locations")
    print("\nTo fix: Add imports at function level or module level")

    sys.exit(1)


if __name__ == "__main__":
    main()
