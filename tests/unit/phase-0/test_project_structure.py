"""
Unit tests for Phase 0: Project structure validation
"""
from pathlib import Path


class TestProjectStructure:
    """Test that the project structure is correctly set up."""

    def test_required_directories_exist(self, project_root_dir: Path) -> None:
        """Verify all required directories exist."""
        required_dirs = [
            'src',
            'src/translation_engine',
            'src/tm',
            'src/model_runtime',
            'src/orchestrator',
            'src/workers',
            'src/observability',
            'src/utils',
            'config',
            'config/site_profiles',
            'config/schemas',
            'tests',
            'tests/unit',
            'tests/integration',
            'docs',
            'docker',
            'scripts',
            'requirements',
        ]

        for dir_path in required_dirs:
            assert (project_root_dir / dir_path).exists(), f"{dir_path} should exist"
            assert (project_root_dir / dir_path).is_dir(), f"{dir_path} should be a directory"

    def test_required_files_exist(self, project_root_dir: Path) -> None:
        """Verify all required configuration files exist."""
        required_files = [
            'pyproject.toml',
            'README.md',
            '.gitignore',
            '.env.example',
            'requirements/base.txt',
            'requirements/cpu.txt',
            'requirements/gpu.txt',
            'requirements/dev.txt',
        ]

        for file_path in required_files:
            assert (project_root_dir / file_path).exists(), f"{file_path} should exist"
            assert (project_root_dir / file_path).is_file(), f"{file_path} should be a file"

    def test_python_modules_have_init(self, project_root_dir: Path) -> None:
        """Verify all Python module directories have __init__.py files."""
        module_dirs = [
            'src',
            'src/translation_engine',
            'src/tm',
            'src/model_runtime',
            'src/orchestrator',
            'src/workers',
            'src/observability',
            'src/utils',
            'tests',
        ]

        for module_dir in module_dirs:
            init_file = project_root_dir / module_dir / '__init__.py'
            assert init_file.exists(), f"{module_dir}/__init__.py should exist"


class TestConfigurationFiles:
    """Test that configuration files are valid."""

    def test_pyproject_toml_is_valid(self, project_root_dir: Path) -> None:
        """Verify pyproject.toml is valid TOML."""
        import tomllib

        with open(project_root_dir / 'pyproject.toml', 'rb') as f:
            config = tomllib.load(f)

        assert 'project' in config
        assert config['project']['name'] == 'hugo-translation-system'
        assert 'requires-python' in config['project']

    def test_readme_exists_and_not_empty(self, project_root_dir: Path) -> None:
        """Verify README exists and has content."""
        readme = project_root_dir / 'README.md'
        content = readme.read_text()

        assert len(content) > 100, "README should have substantial content"
        assert 'Hugo Translation System' in content

    def test_gitignore_exists(self, project_root_dir: Path) -> None:
        """Verify .gitignore exists and has Python ignores."""
        gitignore = project_root_dir / '.gitignore'
        content = gitignore.read_text()

        assert '__pycache__' in content
        assert 'venv/' in content
        assert '*.pyc' in content
