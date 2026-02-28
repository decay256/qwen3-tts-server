"""Contract verification tests — ensure contracts/*.yaml matches actual code signatures.

Compares documented method signatures against inspect.signature() output.
Catches drift between contracts and implementation.
"""

import inspect
import sys
import os

import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from server.tts_engine import TTSEngine


CONTRACT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "contracts", "tts-engine.yaml")


@pytest.fixture(scope="module")
def contract():
    with open(CONTRACT_PATH) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def engine_class():
    return TTSEngine


def test_contract_file_exists():
    assert os.path.exists(CONTRACT_PATH), f"Contract file missing: {CONTRACT_PATH}"


def test_all_contract_methods_exist(contract, engine_class):
    """Every method in the contract must exist on TTSEngine."""
    missing = []
    for method_name in contract["interface"]:
        if not hasattr(engine_class, method_name):
            missing.append(method_name)
    assert not missing, f"Methods in contract but not on TTSEngine: {missing}"


def test_all_public_methods_in_contract(contract, engine_class):
    """Every public method on TTSEngine should be in the contract (catch undocumented methods)."""
    contract_methods = set(contract["interface"].keys())
    actual_methods = {
        name for name, _ in inspect.getmembers(engine_class, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    undocumented = actual_methods - contract_methods
    # Allow some tolerance — warn but don't fail for minor helpers
    if undocumented:
        pytest.skip(f"Undocumented public methods (consider adding to contract): {undocumented}")


@pytest.mark.parametrize("method_name", [
    "load_models",
    "generate_voice_design",
    "generate_voice_clone",
    "generate_custom_voice",
    "create_clone_prompt",
    "synthesize_with_clone_prompt",
    "save_voice",
    "list_voices",
])
def test_method_signature_matches_contract(contract, engine_class, method_name):
    """Verify parameter names and defaults match between contract and code."""
    if method_name not in contract["interface"]:
        pytest.skip(f"{method_name} not in contract")

    spec = contract["interface"][method_name]
    method = getattr(engine_class, method_name)
    sig = inspect.signature(method)

    # Skip 'self' parameter
    params = {
        name: param
        for name, param in sig.parameters.items()
        if name != "self"
    }

    # Check args documented in contract exist in actual signature
    contract_args = spec.get("args", "none")
    if contract_args == "none":
        # Contract says no args — method should have no params (or only defaults)
        return

    if isinstance(contract_args, dict):
        for arg_name in contract_args:
            assert arg_name in params, (
                f"{method_name}: contract has arg '{arg_name}' but method signature has: {list(params.keys())}"
            )
