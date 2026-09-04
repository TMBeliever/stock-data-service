import pytest
from ai_core.orchestrator import AIOrchestrator
from ai_core.providers.key_provider import APIKeyProvider
from ai_core.providers.cli_provider import CLIProcessProvider

def test_orchestrator_factory():
    orch = AIOrchestrator(default_provider="key")

    key_p = orch.get_provider("key")
    assert isinstance(key_p, APIKeyProvider)
    assert key_p.provider_type == "key"

    cli_p = orch.get_provider("cli")
    assert isinstance(cli_p, CLIProcessProvider)
    assert cli_p.provider_type == "cli"

    default_p = orch.get_provider()
    assert isinstance(default_p, APIKeyProvider)

    with pytest.raises(ValueError):
        orch.get_provider("unknown_driver")
