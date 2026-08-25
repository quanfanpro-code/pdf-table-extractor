def test_app_package_can_be_imported():
    import app

    assert app.__all__ == []
