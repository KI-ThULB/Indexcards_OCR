from unittest.mock import Mock, patch

from app.core.config import settings
from app.services.validation.corrector import invoke_corrector


def _cap_state():
    return {"used": 0, "cap": 10, "lock": None}


def _response():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"proposal": "Holz", '
                        '"rationale": "Matches the allowed vocabulary"}'
                    )
                }
            }
        ]
    }
    return response


def test_corrector_uses_openrouter_by_default(monkeypatch):
    monkeypatch.setattr(settings, "CORRECTOR_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "CORRECTOR_MODEL_NAME", "test-cloud-model")

    with patch(
        "app.services.validation.corrector.requests.post",
        return_value=_response(),
    ) as post:
        result = invoke_corrector(
            field_name="Material",
            raw_value="HoIz",
            rule={"vocabulary": ["Holz", "Metall"]},
            cap_state=_cap_state(),
            api_key="openrouter-test-key",
        )

    assert result["status"] == "corrected"
    assert result["proposal"] == "Holz"

    post.assert_called_once()
    args, kwargs = post.call_args

    assert args[0] == settings.API_ENDPOINT
    assert kwargs["headers"]["Authorization"] == "Bearer openrouter-test-key"
    assert kwargs["json"]["model"] == "test-cloud-model"
    assert "chat_template_kwargs" not in kwargs["json"]


def test_corrector_uses_gpustack(monkeypatch):
    monkeypatch.setattr(settings, "CORRECTOR_PROVIDER", "gpustack")
    monkeypatch.setattr(settings, "CORRECTOR_MODEL_NAME", "stable-text")
    monkeypatch.setattr(settings, "GPUSTACK_API_KEY", "gpustack-test-key")
    monkeypatch.setattr(settings, "CORRECTOR_ENABLE_THINKING", False)

    with patch(
        "app.services.validation.corrector.requests.post",
        return_value=_response(),
    ) as post:
        result = invoke_corrector(
            field_name="Material",
            raw_value="HoIz",
            rule={"vocabulary": ["Holz", "Metall"]},
            cap_state=_cap_state(),
            api_key="unused-openrouter-key",
        )

    assert result["status"] == "corrected"
    assert result["proposal"] == "Holz"

    post.assert_called_once()
    args, kwargs = post.call_args

    assert args[0] == settings.GPUSTACK_API_ENDPOINT
    assert kwargs["headers"]["Authorization"] == "Bearer gpustack-test-key"
    assert kwargs["json"]["model"] == "stable-text"
    assert kwargs["json"]["chat_template_kwargs"] == {
        "enable_thinking": False
    }

def test_empty_value_does_not_invoke_corrector(monkeypatch):
    from threading import Lock

    from app.services.validation import runner

    called = False

    def fake_corrector(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("Corrector must not be called for an empty value")

    monkeypatch.setattr(runner, "invoke_corrector", fake_corrector)

    outcomes = runner.run_validation(
        data={"Jahr": ""},
        field_rules={
            "Jahr": {
                "pattern": r"^\d{4}$",
                "corrector_enabled": True,
            }
        },
        corrector_enabled=True,
        cap_state={
            "used": 0,
            "cap": 10,
            "lock": Lock(),
        },
        api_key="",
    )

    assert called is False
    assert outcomes["Jahr"]["status"] == "invalid"
    assert outcomes["Jahr"]["rule_failed"] == "regex"
    assert outcomes["Jahr"]["corrector_proposal"] is None
