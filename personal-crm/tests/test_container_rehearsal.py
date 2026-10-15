import importlib.util
from pathlib import Path
import pytest


def helper():
    spec=importlib.util.spec_from_file_location('container_checks',Path('scripts/container_checks.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.mark.parametrize('project',['personal-crm-pilot','personal-crm','crm-check-../../real','crm-check-'])
def test_cleanup_refuses_any_project_not_owned_by_this_rehearsal(project,tmp_path):
    with pytest.raises(ValueError):helper().guard(project,tmp_path)


def test_rehearsal_requires_own_runtime_and_never_remote_docker():
    module=helper();runtime=module.ROOT/'.runtime'/'container-ci-abc123'
    module.guard('crm-check-abc123',runtime)
    with pytest.raises(ValueError):module.guard('crm-check-abc123',module.ROOT)
    with pytest.raises(ValueError):module.local_daemon('ssh://synthetic.example.invalid')
    module.local_daemon('unix:///var/run/docker.sock')
