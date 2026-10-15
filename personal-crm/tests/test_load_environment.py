def test_load_report_describes_actual_host_instead_of_hardcoding_windows(monkeypatch):
    from personal_crm import load_rehearsal
    monkeypatch.setattr('platform.system',lambda:'Linux')
    assert load_rehearsal.conditions().startswith('Linux ')
    assert 'excludes HTTP/TLS' in load_rehearsal.conditions()
