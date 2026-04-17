"""Test docker-compose.yml syntax."""
from pathlib import Path

import yaml


def test_docker_compose_no_version_tag():
    """Verify docker-compose.yml has no obsolete version tag."""
    compose_file = Path("docker-compose.yml")
    content = compose_file.read_text()

    # Parse YAML
    config = yaml.safe_load(content)

    # Check version is not present
    assert "version" not in config, "Obsolete 'version' tag should be removed"


def test_docker_compose_valid_yaml():
    """Verify docker-compose.yml is valid YAML."""
    compose_file = Path("docker-compose.yml")
    content = compose_file.read_text()

    try:
        config = yaml.safe_load(content)
        assert config is not None
        assert "services" in config
    except yaml.YAMLError as e:
        raise AssertionError(f"Invalid YAML: {e}")


if __name__ == "__main__":
    test_docker_compose_no_version_tag()
    test_docker_compose_valid_yaml()
    print("OK: docker-compose.yml syntax is valid")
