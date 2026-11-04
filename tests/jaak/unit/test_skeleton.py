import inspect

import mel_agent.jaak as jaak
from mel_agent.jaak import errors
from mel_agent.jaak.logs import LogSink, NullLogSink


def test_package_imports():
    assert jaak is not None


def test_null_sink_accepts_entries():
    sink = NullLogSink()
    assert isinstance(sink, LogSink)
    assert sink.write({"event": "x"}) is None


def test_every_error_is_a_jaak_error():
    classes = [
        c for _, c in inspect.getmembers(errors, inspect.isclass)
        if c.__module__ == errors.__name__
    ]
    names = {c.__name__ for c in classes}
    assert names >= {
        "JaakError", "InputRejected", "InvalidRequest", "LanguageUnavailable",
        "GreetingFailed", "SurveyTextMissing", "TemplateError", "UnknownSession",
        "SessionFinalised", "OutOfOrder", "NotEnded", "TurnsPending",
        "EventRejected", "RecordInvalid", "ConfigError",
    }
    assert all(issubclass(c, errors.JaakError) for c in classes)


def test_error_attributes():
    e = errors.InputRejected("survey_input", [("$.a", "required")])
    assert e.boundary == "survey_input" and e.failures == (("$.a", "required"),)
    assert e.logging_failed is False
    t = errors.TemplateError("greeting_plain", "max_sentences")
    assert (t.template_id, t.rule) == ("greeting_plain", "max_sentences")
    assert errors.JaakError("x", logging_failed=True).logging_failed is True
