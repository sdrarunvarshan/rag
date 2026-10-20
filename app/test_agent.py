"""Compatibility entry. The agent check lives in app.test."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("app.test.test_agent", run_name="__main__")
