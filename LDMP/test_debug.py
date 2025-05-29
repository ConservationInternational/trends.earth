def test_debug():
    try:
        import pydevd_pycharm

        pydevd_pycharm.settrace(
            "localhost",
            port=53100,
            stdoutToServer=True,
            stderrToServer=True,
            suspend=False,
        )
    except Exception as e:
        print("Could not connect to debugger:", e)
    print("test")


test_debug()
